"""MILP that assigns PO line quantities to individual containers.

Per-unit cost of sending PO line i on shipment s:

    L = max(0, arrival_s - import_eta_i - grace_days)
    E = max(0, import_eta_i - arrival_s)
    late = w_i * COGS_i * (late_fee_rate * [L > 0] + late_daily_rate * L)
    hold = early_holding_rate * COGS_i * E
    w_i  = priority_multiplier ** priority_level_i      (higher level = more important)

Per-unit cost of leaving a unit of PO line i unshipped:

    u_i = max(w_i * unmet_penalty_i, (1 + unmet_margin) * max_s (late + hold))

The floor keeps "unmet" strictly more expensive than any shipment the line could
take inside the planning horizon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pulp

logger = logging.getLogger(__name__)

REQUIRED_PO_COLS = {
    "From Port",
    "To Port",
    "Export ETA",
    "Import ETA",
    "To Be Shipped Quantity",
    "Volume (m3)",
    "Weight (kg)",
    "COGS",
    "Priority Level",
    "Unmet Penalty",
}
REQUIRED_CAP_COLS = {
    "Shipment ID",
    "From Port",
    "To Port",
    "Departure Date",
    "Arrival Date",
    "Max Volume (m³)",
    "Max Weight (kg)",
    "Price (USD)",
}

PO_RESULT_COLS = [
    "PO Number",
    "PO Line Number",
    "SKU",
    "Product Name",
    "Product Family",
    "IsElectronic",
    "From Port",
    "To Port",
    "Export ETA",
    "Import ETA",
    "Volume (m3)",
    "Weight (kg)",
    "COGS",
    "Priority Level",
]
SHIP_RESULT_COLS = [
    "Shipment ID",
    "Base Shipment ID",
    "Carrier",
    "Container Type",
    "Max Volume (m³)",
    "Max Weight (kg)",
    "Price (USD)",
    "Departure Date",
    "Arrival Date",
]

# Tolerance for floor(capacity / unit size) so e.g. 66 / 0.66 is not rounded down to 99.
_FIT_EPS = 1e-9


@dataclass(frozen=True)
class PenaltyParams:
    """Cost settings. Rates are fractions of per-unit COGS."""

    late_fee_rate: float = 0.05
    late_daily_rate: float = 0.005
    grace_days: int = 0
    priority_multiplier: float = 2.0
    early_holding_rate: float = 0.0
    unmet_margin: float = 0.10

    def priority_weight(self, priority_level):
        return self.priority_multiplier**priority_level


@dataclass(frozen=True)
class SolverParams:
    time_limit_s: int | None = 120
    gap_rel: float | None = None
    msg: bool = False


@dataclass
class OptimizationResult:
    results: pd.DataFrame
    status: str
    is_optimal: bool
    objective: float


class OptimizationError(RuntimeError):
    """Raised when the solver returns no usable solution."""


def lateness_days(arrival, import_eta, grace_days: int = 0):
    """Return (late_days, early_days) for scalars or aligned Series of timestamps."""
    delta = arrival - import_eta
    days = delta.dt.days if isinstance(delta, pd.Series) else delta.days
    return np.maximum(days - grace_days, 0), np.maximum(-days, 0)


def late_cost(po, ship, params: PenaltyParams):
    """Per-unit (late penalty, early holding cost) of sending `po` on `ship`.

    Accepts single rows or aligned DataFrames; both the objective and the reported
    result columns come from this function.
    """
    late, early = lateness_days(ship["Arrival Date"], po["Import ETA"], params.grace_days)
    weight = params.priority_weight(po["Priority Level"])
    late_penalty = (
        weight * po["COGS"] * (params.late_fee_rate * (late > 0) + params.late_daily_rate * late)
    )
    holding = params.early_holding_rate * po["COGS"] * early
    return late_penalty, holding


def _check_columns(df: pd.DataFrame, required: set[str], label: str) -> None:
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{label} is missing columns: {sorted(missing)}")


def _build_routes(po: pd.DataFrame, cap: pd.DataFrame, params: PenaltyParams) -> pd.DataFrame:
    """Every feasible (PO line, container) pair with its per-unit costs and quantity cap."""
    routes = po[
        [
            "po_idx",
            "From Port",
            "To Port",
            "Export ETA",
            "Import ETA",
            "To Be Shipped Quantity",
            "Volume (m3)",
            "Weight (kg)",
            "COGS",
            "Priority Level",
        ]
    ].merge(
        cap[
            [
                "ship_idx",
                "From Port",
                "To Port",
                "Departure Date",
                "Arrival Date",
                "Max Volume (m³)",
                "Max Weight (kg)",
            ]
        ],
        on=["From Port", "To Port"],
    )
    routes = routes[routes["Departure Date"] >= routes["Export ETA"]]

    fit_by_volume = np.floor(routes["Max Volume (m³)"] / routes["Volume (m3)"] + _FIT_EPS)
    fit_by_weight = np.floor(routes["Max Weight (kg)"] / routes["Weight (kg)"] + _FIT_EPS)
    routes = routes.assign(
        max_qty=np.minimum(
            routes["To Be Shipped Quantity"], np.minimum(fit_by_volume, fit_by_weight)
        ).astype(int)
    )
    routes = routes[routes["max_qty"] > 0].reset_index(drop=True)

    late_days, _ = lateness_days(routes["Arrival Date"], routes["Import ETA"])
    late_unit, hold_unit = late_cost(routes, routes, params)
    return routes.assign(
        late_days=late_days,
        late_unit=late_unit,
        hold_unit=hold_unit,
        route_unit=late_unit + hold_unit,
    )


def _unmet_rates(po: pd.DataFrame, routes: pd.DataFrame, params: PenaltyParams) -> pd.Series:
    base = params.priority_weight(po["Priority Level"]) * po["Unmet Penalty"]
    worst_route = routes.groupby("po_idx")["route_unit"].max().reindex(po["po_idx"]).fillna(0)
    floor = (1 + params.unmet_margin) * worst_route.to_numpy()
    raised = floor > base.to_numpy()
    if raised.any():
        logger.warning(
            "Unmet penalty raised above the worst-case late cost for %d PO line(s)", raised.sum()
        )
    return pd.Series(np.maximum(base.to_numpy(), floor), index=po.index)


def _symmetry_groups(cap: pd.DataFrame) -> list[list[int]]:
    """Groups of interchangeable containers, each listed in unit order."""
    key_cols = [
        c
        for c in [
            "Base Shipment ID",
            "Departure Date",
            "Arrival Date",
            "Max Volume (m³)",
            "Max Weight (kg)",
            "Price (USD)",
        ]
        if c in cap.columns
    ]
    if "Base Shipment ID" not in key_cols:
        return []
    return [g["ship_idx"].tolist() for _, g in cap.groupby(key_cols, sort=False) if len(g) > 1]


def _allocate_container_cost(assigned: pd.DataFrame) -> pd.Series:
    """Split each container's price across its rows by volume share."""
    row_volume = assigned["Qty Assigned"] * assigned["Volume (m3)"]
    total = row_volume.groupby(assigned["Shipment ID"]).transform("sum")
    rows = assigned.groupby("Shipment ID")["Shipment ID"].transform("size")
    share = np.where(total > 0, row_volume / total.where(total > 0, 1), 1 / rows)
    return assigned["Price (USD)"] * share


def optimize_shipping(
    po_df: pd.DataFrame,
    cap_df: pd.DataFrame,
    params: PenaltyParams | None = None,
    solver: SolverParams | None = None,
) -> OptimizationResult:
    """Minimise container cost + late penalties + early holding + unmet penalties."""
    params = params or PenaltyParams()
    solver = solver or SolverParams()
    _check_columns(po_df, REQUIRED_PO_COLS, "PO data")
    _check_columns(cap_df, REQUIRED_CAP_COLS, "Capacity data")
    if (po_df["Volume (m3)"] <= 0).any() or (po_df["Weight (kg)"] <= 0).any():
        raise ValueError("PO unit volume and weight must be > 0")

    po = po_df.reset_index(drop=True).assign(po_idx=lambda d: range(len(d)))
    cap = cap_df.reset_index(drop=True).assign(ship_idx=lambda d: range(len(d)))
    if "Base Shipment ID" not in cap.columns:
        cap["Base Shipment ID"] = cap["Shipment ID"]

    routes = _build_routes(po, cap, params)
    unmet_rate = _unmet_rates(po, routes, params)
    logger.info("Feasible routes: %d", len(routes))

    model = pulp.LpProblem("PO_Container_Optimization", pulp.LpMinimize)

    x = [
        model.add_variable(f"x_{r}", 0, int(ub), cat=pulp.LpInteger)
        for r, ub in enumerate(routes["max_qty"])
    ]
    used_ships = sorted(routes["ship_idx"].unique())
    use = {s: model.add_variable(f"use_{s}", 0, 1, cat=pulp.LpBinary) for s in used_ships}
    unmet = [
        model.add_variable(f"unmet_{i}", 0, int(q), cat=pulp.LpInteger)
        for i, q in enumerate(po["To Be Shipped Quantity"])
    ]

    price = cap["Price (USD)"].to_numpy()
    model += (
        pulp.lpSum(c * v for c, v in zip(routes["route_unit"], x, strict=True) if c)
        + pulp.lpSum(price[s] * use[s] for s in used_ships)
        + pulp.lpSum(r * v for r, v in zip(unmet_rate, unmet, strict=True))
    )

    routes_by_po = routes.groupby("po_idx").indices
    for i, qty in enumerate(po["To Be Shipped Quantity"]):
        model += (
            pulp.lpSum(x[r] for r in routes_by_po.get(i, [])) + unmet[i] == int(qty),
            f"demand_{i}",
        )

    max_vol = cap["Max Volume (m³)"].to_numpy()
    max_wt = cap["Max Weight (kg)"].to_numpy()
    unit_vol = routes["Volume (m3)"].to_numpy()
    unit_wt = routes["Weight (kg)"].to_numpy()
    max_qty = routes["max_qty"].to_numpy()
    for s, idx in routes.groupby("ship_idx").indices.items():
        model += (
            pulp.lpSum(unit_vol[r] * x[r] for r in idx) <= max_vol[s] * use[s],
            f"vol_{s}",
        )
        model += (
            pulp.lpSum(unit_wt[r] * x[r] for r in idx) <= max_wt[s] * use[s],
            f"wt_{s}",
        )
        for r in idx:
            model += x[r] <= int(max_qty[r]) * use[s], f"link_{r}"

    for group in _symmetry_groups(cap):
        group = [s for s in group if s in use]
        for a, b in zip(group, group[1:], strict=False):
            model += use[a] >= use[b], f"sym_{a}_{b}"

    model.solve(
        pulp.PULP_CBC_CMD(msg=solver.msg, timeLimit=solver.time_limit_s, gapRel=solver.gap_rel)
    )

    if model.sol_status not in (pulp.LpSolutionOptimal, pulp.LpSolutionIntegerFeasible):
        raise OptimizationError(
            f"Solver returned no usable solution: {pulp.LpSolution[model.sol_status]}"
        )
    is_optimal = model.sol_status == pulp.LpSolutionOptimal
    if not is_optimal:
        logger.warning("Solver stopped before proving optimality; the plan may be suboptimal")

    results = _build_results(po, cap, routes, x, unmet, unmet_rate)
    return OptimizationResult(
        results=results,
        status=pulp.LpSolution[model.sol_status],
        is_optimal=is_optimal,
        objective=float(pulp.value(model.objective) or 0.0),
    )


def _var_values(variables) -> np.ndarray:
    return np.array([round(v.varValue or 0) for v in variables], dtype=int)


def _build_results(po, cap, routes, x, unmet, unmet_rate) -> pd.DataFrame:
    po_cols = ["po_idx"] + [c for c in PO_RESULT_COLS if c in po.columns]
    ship_cols = ["ship_idx"] + [c for c in SHIP_RESULT_COLS if c in cap.columns]
    po_out = po[po_cols].assign(
        **{"Base Unmet Penalty": po["Unmet Penalty"], "Unmet Penalty Rate": unmet_rate}
    )

    qty = _var_values(x)
    assigned = (
        routes.loc[qty > 0, ["po_idx", "ship_idx", "late_days", "late_unit", "hold_unit"]]
        .assign(**{"Qty Assigned": qty[qty > 0]})
        .merge(po_out, on="po_idx")
        .merge(cap[ship_cols], on="ship_idx")
        .sort_values(["ship_idx", "po_idx"])
        .reset_index(drop=True)
    )
    assigned = assigned.assign(
        **{
            "COGS Value Assigned": assigned["Qty Assigned"] * assigned["COGS"],
            "Late Days": assigned["late_days"],
            "Late Penalty": assigned["late_unit"] * assigned["Qty Assigned"],
            "Early Holding Cost": assigned["hold_unit"] * assigned["Qty Assigned"],
            "Used Container": (~assigned["Shipment ID"].duplicated()).astype(int),
            "Allocated Container Cost": _allocate_container_cost(assigned),
            "Unmet Qty": 0,
            "COGS Value Unmet": 0.0,
            "Unmet Penalty": 0.0,
        }
    ).drop(columns=["late_days", "late_unit", "hold_unit"])

    unmet_qty = _var_values(unmet)
    unmet_rows = po_out[unmet_qty > 0].assign(
        **{
            "Qty Assigned": 0,
            "COGS Value Assigned": 0.0,
            "Used Container": 0,
            "Allocated Container Cost": 0.0,
            "Unmet Qty": unmet_qty[unmet_qty > 0],
        }
    )
    unmet_rows = unmet_rows.assign(
        **{
            "COGS Value Unmet": unmet_rows["Unmet Qty"] * unmet_rows["COGS"],
            "Unmet Penalty": unmet_rows["Unmet Qty"] * unmet_rows["Unmet Penalty Rate"],
        }
    )

    ordered = (
        [c for c in PO_RESULT_COLS if c in po.columns]
        + ["Base Unmet Penalty", "Unmet Penalty Rate"]
        + [c for c in SHIP_RESULT_COLS if c in cap.columns]
        + [
            "Qty Assigned",
            "COGS Value Assigned",
            "Late Days",
            "Late Penalty",
            "Early Holding Cost",
            "Used Container",
            "Allocated Container Cost",
            "Unmet Qty",
            "COGS Value Unmet",
            "Unmet Penalty",
        ]
    )
    frames = [f for f in (assigned, unmet_rows) if not f.empty]
    if not frames:
        return pd.DataFrame(columns=ordered)
    return pd.concat(frames, ignore_index=True).reindex(columns=ordered)


if __name__ == "__main__":
    from container_optimization.preprocessing import preprocess_data

    logging.basicConfig(level=logging.INFO)
    po_data, cap_data = preprocess_data(
        "data/samples/sample_purchase_order_v1.csv", "data/samples/sample_container_capacity_v1.csv"
    )
    outcome = optimize_shipping(po_data, cap_data)
    print(outcome.status, round(outcome.objective, 2))
    print(outcome.results)
