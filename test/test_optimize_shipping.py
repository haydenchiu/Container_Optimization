from pathlib import Path

import pandas as pd
import pytest

from container_optimization.optimizer import (
    PenaltyParams,
    late_cost,
    lateness_days,
    optimize_shipping,
)
from container_optimization.preprocessing import preprocess_data

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"

PO_DEFAULTS = {
    "PO Number": "PO1",
    "PO Line Number": 1,
    "SKU": "SKU1",
    "Product Name": "Widget",
    "Product Family": "Accessories",
    "IsElectronic": 0,
    "COGS": 100.0,
    "From Port": "HK",
    "To Port": "LA",
    "Export ETA": "2025-06-01",
    "Import ETA": "2025-06-10",
    "To Be Shipped Quantity": 5,
    "Volume (m3)": 1.0,
    "Weight (kg)": 100.0,
    "Priority Level": 1,
    "Unmet Penalty": 1000.0,
}

CAP_DEFAULTS = {
    "Shipment ID": "S1-1",
    "Base Shipment ID": "S1",
    "From Port": "HK",
    "To Port": "LA",
    "Departure Date": "2025-06-02",
    "Arrival Date": "2025-06-08",
    "Price (USD)": 500.0,
    "Max Volume (m³)": 10.0,
    "Max Weight (kg)": 2000.0,
    "Carrier": "ONE",
    "Container Type": "40FT",
}


def make_po_df(*rows):
    df = pd.DataFrame([{**PO_DEFAULTS, **row} for row in rows])
    for col in ["Export ETA", "Import ETA"]:
        df[col] = pd.to_datetime(df[col])
    return df


def make_cap_df(*rows):
    df = pd.DataFrame([{**CAP_DEFAULTS, **row} for row in rows])
    for col in ["Departure Date", "Arrival Date"]:
        df[col] = pd.to_datetime(df[col])
    return df


def solve(po_df, cap_df, **params):
    outcome = optimize_shipping(po_df, cap_df, PenaltyParams(**params))
    assert outcome.is_optimal
    return outcome.results


def test_basic_assignment():
    results = solve(make_po_df({}), make_cap_df({}))
    assert results["Qty Assigned"].sum() == 5
    assert results["Unmet Qty"].sum() == 0
    assert results["Used Container"].sum() == 1
    assert results["Late Penalty"].sum() == 0


def test_no_feasible_shipment_is_unmet_with_priority_weighted_penalty():
    po_df = make_po_df(
        {
            "Export ETA": "2025-06-10",
            "Import ETA": "2025-06-20",
            "To Be Shipped Quantity": 10,
            "Priority Level": 2,
            "Unmet Penalty": 2000.0,
        }
    )
    cap_df = make_cap_df({"Departure Date": "2025-06-01", "Arrival Date": "2025-06-05"})

    results = solve(po_df, cap_df, priority_multiplier=2.0)
    assert results["Qty Assigned"].sum() == 0
    assert results["Unmet Qty"].sum() == 10
    assert results.iloc[0]["Unmet Penalty"] == pytest.approx(10 * 2000 * 2**2)


def test_partial_assignment_due_to_capacity():
    po_df = make_po_df({"To Be Shipped Quantity": 10, "Volume (m3)": 20.0, "Weight (kg)": 1000.0})
    cap_df = make_cap_df(
        {"Price (USD)": 1000.0, "Max Volume (m³)": 60.0, "Max Weight (kg)": 3000.0}
    )

    results = solve(po_df, cap_df)
    assert results["Qty Assigned"].sum() == 3
    assert results["Unmet Qty"].sum() == 7


def test_multiple_containers():
    po_df = make_po_df({"To Be Shipped Quantity": 8, "Volume (m3)": 5.0, "Weight (kg)": 500.0})
    cap_df = make_cap_df(
        {"Shipment ID": "S4-1", "Max Volume (m³)": 20.0},
        {"Shipment ID": "S4-2", "Max Volume (m³)": 20.0},
    )

    results = solve(po_df, cap_df)
    assert results["Qty Assigned"].sum() == 8
    assert results["Used Container"].sum() == 2


def test_shared_container_across_po_lines_allocates_cost_by_volume():
    po_df = make_po_df(
        {"PO Line Number": 1, "To Be Shipped Quantity": 3},
        {"PO Line Number": 2, "To Be Shipped Quantity": 1, "Volume (m3)": 3.0},
    )
    results = solve(po_df, make_cap_df({"Price (USD)": 600.0}))

    assert results["Qty Assigned"].sum() == 4
    assert results["Used Container"].sum() == 1
    allocated = results.set_index("PO Line Number")["Allocated Container Cost"]
    assert allocated.sum() == pytest.approx(600.0)
    assert allocated[1] == pytest.approx(300.0)
    assert allocated[2] == pytest.approx(300.0)


def test_high_priority_line_is_shipped_before_low_priority_line():
    # One container that fits only one of two otherwise identical lines, arriving late.
    # The old formula scaled only the late penalty by priority, so it dropped the
    # high-priority line and shipped the low-priority one.
    po_df = make_po_df(
        {
            "PO Line Number": 1,
            "Priority Level": 0,
            "To Be Shipped Quantity": 10,
            "Unmet Penalty": 100.0,
        },
        {
            "PO Line Number": 2,
            "Priority Level": 2,
            "To Be Shipped Quantity": 10,
            "Unmet Penalty": 100.0,
        },
    )
    cap_df = make_cap_df({"Arrival Date": "2025-06-20", "Price (USD)": 0.0})

    results = solve(po_df, cap_df, late_fee_rate=0.05, late_daily_rate=0.05)
    by_line = results.groupby("PO Line Number")[["Qty Assigned", "Unmet Qty"]].sum()
    assert by_line.loc[2, "Qty Assigned"] == 10
    assert by_line.loc[1, "Unmet Qty"] == 10


def test_unmet_always_costs_more_than_shipping_late():
    po_df = make_po_df({"Unmet Penalty": 1.0, "Priority Level": 0})
    cap_df = make_cap_df({"Arrival Date": "2025-08-30", "Price (USD)": 0.0})
    params = {"late_fee_rate": 0.5, "late_daily_rate": 0.1}

    results = solve(po_df, cap_df, **params)
    assert results["Qty Assigned"].sum() == 5
    assert results["Unmet Qty"].sum() == 0

    late_per_unit = results["Late Penalty"].sum() / 5
    assert results.iloc[0]["Unmet Penalty Rate"] > late_per_unit


@pytest.mark.parametrize(("grace_days", "expected_late_days"), [(0, 3), (2, 1), (3, 0), (5, 0)])
def test_grace_days(grace_days, expected_late_days):
    po = pd.Series({"Import ETA": pd.Timestamp("2025-06-10"), "COGS": 100.0, "Priority Level": 1})
    ship = pd.Series({"Arrival Date": pd.Timestamp("2025-06-13")})
    params = PenaltyParams(
        late_fee_rate=0.05, late_daily_rate=0.01, grace_days=grace_days, priority_multiplier=2.0
    )

    late, _ = lateness_days(ship["Arrival Date"], po["Import ETA"], grace_days)
    penalty, holding = late_cost(po, ship, params)

    assert late == expected_late_days
    expected = 2.0 * 100.0 * (0.05 * (expected_late_days > 0) + 0.01 * expected_late_days)
    assert penalty == pytest.approx(expected)
    assert holding == 0


def test_late_penalty_scales_with_cogs_and_reported_late_days_ignore_grace():
    po_df = make_po_df(
        {"PO Line Number": 1, "COGS": 10.0, "Priority Level": 0},
        {"PO Line Number": 2, "COGS": 200.0, "Priority Level": 0},
    )
    cap_df = make_cap_df({"Arrival Date": "2025-06-14", "Price (USD)": 0.0})

    results = solve(po_df, cap_df, late_fee_rate=0.0, late_daily_rate=0.01, grace_days=1)
    by_line = results.set_index("PO Line Number")
    assert (by_line["Late Days"] == 4).all()
    assert by_line.loc[1, "Late Penalty"] == pytest.approx(5 * 10.0 * 0.01 * 3)
    assert by_line.loc[2, "Late Penalty"] == pytest.approx(5 * 200.0 * 0.01 * 3)


def test_early_holding_cost_prefers_on_time_container():
    po_df = make_po_df({"Import ETA": "2025-06-20"})
    cap_df = make_cap_df(
        {"Shipment ID": "EARLY-1", "Base Shipment ID": "EARLY", "Arrival Date": "2025-06-08"},
        {"Shipment ID": "ONTIME-1", "Base Shipment ID": "ONTIME", "Arrival Date": "2025-06-20"},
    )

    results = solve(po_df, cap_df, early_holding_rate=0.01)
    assert results["Shipment ID"].tolist() == ["ONTIME-1"]
    assert results["Early Holding Cost"].sum() == 0


def test_identical_containers_are_used_in_unit_order():
    cap_df = make_cap_df(*({"Shipment ID": f"S1-{k}"} for k in range(1, 4)))
    results = solve(make_po_df({}), cap_df)
    assert results["Shipment ID"].dropna().tolist() == ["S1-1"]


def test_unit_larger_than_container_is_unmet():
    po_df = make_po_df({"Volume (m3)": 11.0})
    results = solve(po_df, make_cap_df({}))
    assert results["Qty Assigned"].sum() == 0
    assert results["Unmet Qty"].sum() == 5


@pytest.mark.parametrize(("multiplier", "marketplace_projectors_ship"), [(2.0, False), (1.0, True)])
def test_capacity_shortage_scenario_triage(multiplier, marketplace_projectors_ship):
    prefix = SAMPLES / "scenario3_capacity_shortage"
    po_df, cap_df = preprocess_data(
        f"{prefix}_purchase_order.csv", f"{prefix}_container_capacity.csv"
    )
    results = solve(po_df, cap_df, priority_multiplier=multiplier)
    by_line = results.groupby(["PO Number", "Product Name"])[["Qty Assigned", "Unmet Qty"]].sum()

    assert by_line.loc[("PO-KEY-01", "Mini Projector"), "Unmet Qty"] == 0
    assert (by_line.loc[("PO-MKT-01", "Mini Projector"), "Unmet Qty"] == 0) == (
        marketplace_projectors_ship
    )
    assert by_line.loc["PO-OFC-01", "Qty Assigned"].sum() == 0


def test_missing_required_column_raises():
    po_df = make_po_df({}).drop(columns=["COGS"])
    with pytest.raises(ValueError, match="COGS"):
        optimize_shipping(po_df, make_cap_df({}))
