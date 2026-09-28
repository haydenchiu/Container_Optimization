import hashlib
import io

import pandas as pd
import plotly.express as px
import streamlit as st

from container_optimization.optimizer import PenaltyParams, SolverParams, optimize_shipping
from container_optimization.preprocessing import (
    DataValidationError,
    find_unserved_lanes,
    preprocess_data,
)

COST_COLS = ["Unmet Penalty", "Late Penalty", "Early Holding Cost", "Allocated Container Cost"]


@st.cache_data(show_spinner="Running optimization...")
def run_pipeline(po_bytes: bytes, cap_bytes: bytes, penalty: dict, time_limit_s: int):
    po_df, cap_df = preprocess_data(io.BytesIO(po_bytes), io.BytesIO(cap_bytes))
    outcome = optimize_shipping(
        po_df, cap_df, PenaltyParams(**penalty), SolverParams(time_limit_s=time_limit_s)
    )
    return (
        outcome.results,
        cap_df,
        outcome.status,
        outcome.is_optimal,
        find_unserved_lanes(po_df, cap_df),
    )


def _penalty_sidebar() -> tuple[dict, int]:
    st.sidebar.header("Penalty Configuration")
    late_fee_pct = st.sidebar.number_input(
        "Late fee (% of unit COGS)",
        value=5.0,
        min_value=0.0,
        step=1.0,
        key="late_fee_pct",
        help="One-off charge per unit that arrives after Import ETA + grace days",
    )
    late_daily_pct = st.sidebar.number_input(
        "Daily late rate (% of unit COGS per day)",
        value=0.5,
        min_value=0.0,
        step=0.1,
        key="late_daily_pct",
        help="Charged per unit for every day past Import ETA + grace days",
    )
    grace_days = st.sidebar.number_input(
        "Grace days",
        value=0,
        min_value=0,
        step=1,
        key="grace_days",
        help="Days after Import ETA that are not treated as late",
    )
    priority_multiplier = st.sidebar.number_input(
        "Priority multiplier",
        value=2.0,
        min_value=1.0,
        step=0.5,
        key="priority_multiplier",
        help="Weight = multiplier ^ Priority Level; higher levels are more important. "
        "Scales both late and unmet penalties.",
    )
    early_holding_pct = st.sidebar.number_input(
        "Early holding rate (% of unit COGS per day)",
        value=0.0,
        min_value=0.0,
        step=0.05,
        key="early_holding_pct",
        help="Storage cost per unit for every day a shipment arrives before Import ETA",
    )
    time_limit_s = st.sidebar.number_input(
        "Solver time limit (s)", value=120, min_value=5, step=5, key="time_limit_s"
    )
    penalty = {
        "late_fee_rate": late_fee_pct / 100,
        "late_daily_rate": late_daily_pct / 100,
        "grace_days": int(grace_days),
        "priority_multiplier": float(priority_multiplier),
        "early_holding_rate": early_holding_pct / 100,
    }
    return penalty, int(time_limit_s)


def _signature(po_bytes: bytes, cap_bytes: bytes, penalty: dict, time_limit_s: int) -> tuple:
    digest = hashlib.sha256(po_bytes + b"\0" + cap_bytes).hexdigest()
    return digest, tuple(sorted(penalty.items())), time_limit_s


def _fulfillment_status(row) -> str:
    if row["Unmet Qty"] == 0:
        return "Fully Met"
    return "Partially Met" if row["Qty Assigned"] > 0 else "Unmet"


def show_dashboard():
    st.title("Container Shipping Optimizer")

    st.markdown("""
    Upload your purchase order and container capacity files below, configure parameters, and run the optimization.
    """)

    po_file = st.file_uploader("Upload Purchase Order CSV", type="csv", key="po_upload")
    cap_file = st.file_uploader("Upload Container Capacity CSV", type="csv", key="cap_upload")

    penalty, time_limit_s = _penalty_sidebar()
    current_signature = (
        _signature(po_file.getvalue(), cap_file.getvalue(), penalty, time_limit_s)
        if po_file and cap_file
        else None
    )

    if st.button("Run Optimization"):
        if not (po_file and cap_file):
            st.warning("Please upload both CSV files to continue.")
            st.stop()
        try:
            results_df, cap_df, status, is_optimal, unserved = run_pipeline(
                po_file.getvalue(), cap_file.getvalue(), penalty, time_limit_s
            )
        except DataValidationError as e:
            st.error(f"Input error: {e}")
            st.stop()
        except Exception as e:
            st.error(f"Error: {e}")
            st.stop()

        results_df["Export Date"] = pd.to_datetime(results_df["Export ETA"])
        results_df["Export Year"] = results_df["Export Date"].dt.strftime("%Y")
        results_df["Export YearMonth"] = results_df["Export Date"].dt.strftime("%Y-%m")
        results_df["Export YearWeek"] = results_df["Export Date"].dt.strftime("%G-W%V")

        st.session_state.update(
            results_df=results_df,
            cap_df=cap_df,
            solver_status=status,
            solver_optimal=is_optimal,
            unserved_lanes=unserved,
            run_signature=current_signature,
            penalty=penalty,
        )
        st.success("Optimization completed!")

    if "results_df" not in st.session_state:
        return

    results_df = st.session_state["results_df"]
    cap_df = st.session_state["cap_df"]

    if current_signature is not None and current_signature != st.session_state["run_signature"]:
        st.info(
            "Inputs or parameters changed since the last run. "
            "Click Run Optimization to refresh the results below."
        )
    if not st.session_state["solver_optimal"]:
        st.warning(
            f"Solver status: {st.session_state['solver_status']}. The time limit was reached, "
            "so this plan is feasible but may not be optimal."
        )
    if st.session_state["unserved_lanes"]:
        lanes = ", ".join(f"{a} -> {b}" for a, b in st.session_state["unserved_lanes"])
        st.warning(f"No container capacity for these PO lanes, so they are unmet: {lanes}")

    # Shared filter inputs
    st.sidebar.subheader("Filters")
    filter_po = st.sidebar.text_input("Filter by PO Number (partial match)", key="filter_po")
    filter_export_year = st.sidebar.multiselect(
        "Filter by Export Year",
        options=sorted(results_df["Export Year"].dropna().unique()),
        key="filter_year",
        help="Using export ETA",
    )
    filter_export_yearmonth = st.sidebar.multiselect(
        "Filter by Export YearMonth",
        options=sorted(results_df["Export YearMonth"].dropna().unique()),
        key="filter_yearmonth",
        help="Using export ETA",
    )
    filter_export_yearweek = st.sidebar.multiselect(
        "Filter by Export YearWeek",
        options=sorted(results_df["Export YearWeek"].dropna().unique()),
        key="filter_yearweek",
        help="ISO week of export ETA",
    )

    filtered_df = results_df.copy()
    if filter_po:
        filtered_df = filtered_df[
            filtered_df["PO Number"].astype(str).str.contains(filter_po, regex=False)
        ]
    if filter_export_year:
        filtered_df = filtered_df[filtered_df["Export Year"].isin(filter_export_year)]
    if filter_export_yearmonth:
        filtered_df = filtered_df[filtered_df["Export YearMonth"].isin(filter_export_yearmonth)]
    if filter_export_yearweek:
        filtered_df = filtered_df[filtered_df["Export YearWeek"].isin(filter_export_yearweek)]

    # Sorting and grouping controls
    st.sidebar.subheader("Data Display Settings")
    groupable_cols = [
        "PO Number",
        "PO Line Number",
        "SKU",
        "Product Name",
        "Product Family",
        "To Port",
        "Carrier",
        "Shipment ID",
        "Base Shipment ID",
        "Export Year",
        "Export YearMonth",
        "Export YearWeek",
    ]
    numeric_cols = [
        "Qty Assigned",
        "Unmet Qty",
        "Unmet Penalty",
        "Late Penalty",
        "Early Holding Cost",
        "Allocated Container Cost",
        "COGS Value Assigned",
        "COGS Value Unmet",
    ]

    valid_groupable_cols = [col for col in groupable_cols if col in filtered_df.columns]
    valid_numeric_cols = [col for col in numeric_cols if col in filtered_df.columns]

    groupby_cols = st.sidebar.multiselect(
        "Group by columns:",
        options=valid_groupable_cols,
        default=["PO Number", "PO Line Number"],
        key="groupby_cols",
    )
    sort_by = st.sidebar.selectbox("Sort by column:", options=valid_numeric_cols, key="sort_by")
    sort_ascending = (
        st.sidebar.radio("Sort Order", ["Ascending", "Descending"], key="sort_order") == "Ascending"
    )

    st.subheader("KPI Summary")

    total_pos = filtered_df[["PO Number", "PO Line Number"]].drop_duplicates().shape[0]
    used_containers = filtered_df["Shipment ID"].dropna().nunique()
    unmet_penalty = filtered_df["Unmet Penalty"].sum()
    late_penalty = filtered_df["Late Penalty"].sum()
    holding_cost = filtered_df["Early Holding Cost"].sum()
    container_cost = filtered_df["Allocated Container Cost"].sum()
    total_cost = filtered_df[COST_COLS].sum().sum()

    row1 = st.columns(4)
    row1[0].metric("Total PO Lines", total_pos)
    row1[1].metric("Used Containers", used_containers)
    row1[2].metric("Total Value Assigned", f"{filtered_df['COGS Value Assigned'].sum():,.0f}")
    row1[3].metric("Total Unmet Value", f"{filtered_df['COGS Value Unmet'].sum():,.0f}")
    row2 = st.columns(5)
    row2[0].metric("Total Unmet Penalty", f"{unmet_penalty:,.0f}")
    row2[1].metric("Total Late Penalty", f"{late_penalty:,.0f}")
    row2[2].metric("Total Early Holding Cost", f"{holding_cost:,.0f}")
    row2[3].metric(
        "Total Container Cost",
        f"{container_cost:,.0f}",
        help="Container prices split across PO lines by volume share, so filtered totals "
        "only include the filtered lines' share of shared containers",
    )
    row2[4].metric("Estimated Total Cost ($)", f"{total_cost:,.0f}")

    st.subheader("Visualization")

    po_status = filtered_df.groupby(["PO Number", "PO Line Number"], as_index=False).agg(
        {"Qty Assigned": "sum", "Unmet Qty": "sum"}
    )
    po_status["Status"] = po_status.apply(_fulfillment_status, axis=1)
    st.plotly_chart(
        px.histogram(po_status, x="Status", title="PO Line Fulfillment Status"),
        width="stretch",
    )

    carrier_summary = filtered_df.groupby(["Carrier", "PO Number"], as_index=False)[
        "Qty Assigned"
    ].sum()
    st.plotly_chart(
        px.bar(
            carrier_summary,
            x="Carrier",
            y="Qty Assigned",
            color="PO Number",
            title="Assigned Quantities per Carrier by PO Number",
        ),
        width="stretch",
    )

    cogs_status = filtered_df.groupby(["PO Number", "PO Line Number"], as_index=False).agg(
        {
            "Qty Assigned": "sum",
            "Unmet Qty": "sum",
            "COGS Value Assigned": "sum",
            "COGS Value Unmet": "sum",
        }
    )
    cogs_status["Status"] = cogs_status.apply(_fulfillment_status, axis=1)
    cogs_status["COGS Value"] = cogs_status["COGS Value Assigned"] + cogs_status["COGS Value Unmet"]
    st.plotly_chart(
        px.pie(
            cogs_status.groupby("Status", as_index=False).agg({"COGS Value": "sum"}),
            names="Status",
            values="COGS Value",
            title="COGS Breakdown by Fulfillment Status",
        ),
        width="stretch",
    )

    if "Product Family" in filtered_df.columns:
        fam_summary = (
            filtered_df.groupby("Product Family", as_index=False)
            .agg({"COGS Value Assigned": "sum", "COGS Value Unmet": "sum"})
            .rename(
                columns={
                    "COGS Value Assigned": "Assigned Value",
                    "COGS Value Unmet": "Unmet Value",
                }
            )
        )
        fam_melted = fam_summary.melt(
            id_vars="Product Family",
            value_vars=["Assigned Value", "Unmet Value"],
            var_name="Status",
            value_name="COGS Value",
        )
        st.plotly_chart(
            px.bar(
                fam_melted,
                x="Product Family",
                y="COGS Value",
                color="Status",
                barmode="stack",
                title="COGS Fulfillment by Product Family",
            ),
            width="stretch",
        )

    st.subheader("Aggregated Results")

    if groupby_cols:
        try:
            display_df = filtered_df.groupby(groupby_cols, as_index=False)[valid_numeric_cols].sum()
        except Exception as e:
            st.error(f"Aggregation failed: {e}")
            display_df = filtered_df.copy()
    else:
        display_df = filtered_df.copy()

    if not display_df.empty and sort_by in display_df.columns:
        display_df = display_df.sort_values(by=sort_by, ascending=sort_ascending)

        st.dataframe(display_df, width="stretch")
        st.download_button(
            label="Download Aggregated CSV",
            data=display_df.to_csv(index=False),
            file_name="aggregated_results.csv",
            mime="text/csv",
        )
    else:
        st.warning("No data available for aggregation.")

    used_containers_set = set(results_df["Shipment ID"].dropna())
    unused_df = cap_df[~cap_df["Shipment ID"].isin(used_containers_set)]
    st.subheader("Unused Container Details")
    st.dataframe(
        unused_df[
            [
                "Shipment ID",
                "Base Shipment ID",
                "From Port",
                "To Port",
                "Carrier",
                "Container Type",
                "Departure Date",
                "Arrival Date",
                "Max Volume (m³)",
                "Max Weight (kg)",
                "Price (USD)",
            ]
        ],
        width="stretch",
    )

    csv = filtered_df.to_csv(index=False)
    st.download_button("Download Full Results CSV", csv, "optimized_results.csv", "text/csv")


def show_definitions():
    st.title("Definitions & Assumptions")

    st.markdown("""
    ## Purchase Order (PO) Data
    - **PO Number / PO Line Number**: Unique identifiers for each purchase order and item line.
    - **SKU**: Stock Keeping Unit, uniquely identifies a product.
    - **Product Name / Family**: Name and category of the product.
    - **IsElectronic**: 1 if the product is electronic; otherwise 0.
    - **COGS**: Cost of Goods Sold per unit.
    - **Export ETA / Import ETA**: Date goods are ready at the origin port / date they are due at the destination port.
    - **To Be Shipped Quantity**: Demand quantity for this PO line.
    - **Priority Level**: Higher numbers are more important (0 = lowest).
    - **Unmet Penalty**: Base cost per unit left unshipped, before priority weighting.

    ## Container Capacity Data
    - **Week_Year**: ISO week of departure (e.g. 2025-W25); containers depart on the Monday of that week.
    - **Available Units**: Number of available containers for this configuration.
    - **From/To Port**: Origin and destination of the shipment.
    - **Carrier / Container Type**: Shipping provider and container size.
    - **Estimated Transit Time (days)**: Time from departure to arrival.
    - **Price (USD)**: Cost of using one container.
    """)

    st.markdown("## Optimization Logic")
    st.markdown(
        "The optimizer minimizes total cost = container prices + late penalties "
        "+ early holding costs + unmet penalties. For PO line $i$ on container $s$:"
    )
    st.latex(r"w_i = m^{\,p_i}")
    st.latex(
        r"L_{is} = \max(0,\ \text{arrival}_s - \text{ImportETA}_i - g), \qquad "
        r"E_{is} = \max(0,\ \text{ImportETA}_i - \text{arrival}_s)"
    )
    st.latex(
        r"\text{late}_{is} = w_i \cdot \text{COGS}_i \cdot "
        r"\left(f \cdot \mathbb{1}[L_{is} > 0] + r \cdot L_{is}\right), \qquad "
        r"\text{hold}_{is} = h \cdot \text{COGS}_i \cdot E_{is}"
    )
    st.latex(
        r"u_i = \max\left(w_i \cdot \text{UnmetPenalty}_i,\ "
        r"1.1 \cdot \max_s (\text{late}_{is} + \text{hold}_{is})\right)"
    )
    st.markdown("""
    - $m$: priority multiplier, $p_i$: priority level, $g$: grace days
    - $f$: late fee, $r$: daily late rate, $h$: early holding rate (all fractions of unit COGS)
    - Late and holding costs are charged per unit shipped; $u_i$ is charged per unit left unshipped.
    - Priority scales both the late and the unmet penalty, and $u_i$ is floored above the worst
      late cost, so the optimizer never prefers dropping a unit over shipping it late.

    **Constraints**:
    - A container is only eligible if it serves the PO lane and departs on or after Export ETA.
    - Volume/weight must not exceed container limits; a container's price is paid if it carries anything.
    - Containers are limited by availability (expanded into unique shipment IDs).

    ## KPIs and Metrics
    - **Used Containers**: Number of containers utilized in assignments
    - **Total Container Cost**: Container prices split across PO lines by volume share
    - **Unused Containers**: Available containers not used in optimization
    - **Estimated Total Cost**: Sum of all penalties and container costs

    ## Fulfillment Status Classification
    - **Fully Met**: All ordered quantity shipped
    - **Partially Met**: Some but not all quantity shipped
    - **Unmet**: No quantity shipped for the PO line

    ## Visualizations
    - **PO Fulfillment Status (by count and COGS)**
    - **Carrier Distribution of Assignments**
    - **COGS Fulfillment by Product Family**
    """)


def show_download_templates():
    st.title("Download CSV Templates")

    st.markdown("""
    Use the following templates to prepare your input files for the optimizer.
    Ensure your uploaded files match the expected column names and formats exactly.
    """)

    # Define PO template schema
    po_columns = [
        ("PO Number", "str"),
        ("PO Line Number", "int"),
        ("SKU", "str"),
        ("Product Name", "str"),
        ("Product Family", "str"),
        ("IsElectronic", "int (0 or 1)"),
        ("COGS", "float"),
        ("From Port", "str"),
        ("To Port", "str"),
        ("Export ETA", "date (DD/MM/YYYY)"),
        ("Import ETA", "date (DD/MM/YYYY)"),
        ("To Be Shipped Quantity", "int"),
        ("Length (cm)", "float"),
        ("Width (cm)", "float"),
        ("Height (cm)", "float"),
        ("Weight (kg)", "float"),
        ("Priority Level", "int (higher = more important)"),
        ("Unmet Penalty", "float"),
    ]

    po_template = pd.DataFrame(
        [
            [
                "PO001",
                1,
                "SKU1001",
                "Smartphone X",
                "Electronics",
                1,
                250,
                "HK",
                "LA",
                "15/06/2025",
                "25/06/2025",
                10,
                15.0,
                7.5,
                0.8,
                0.2,
                2,
                1000,
            ]
        ],
        columns=[col[0] for col in po_columns],
    )

    # Define Capacity template schema
    cap_columns = [
        ("Week_Year", "str (ISO week, e.g. 2025-W25)"),
        ("From Port", "str"),
        ("To Port", "str"),
        ("Carrier", "str"),
        ("Container Type", "str"),
        ("Available Units", "int"),
        ("Max Volume (m³)", "float"),
        ("Max Weight (kg)", "float"),
        ("Estimated Transit Time (days)", "int"),
        ("Price (USD)", "float"),
    ]

    cap_template = pd.DataFrame(
        [["2025-W25", "HK", "LA", "Maersk", "40FT", 3, 66.0, 26500.0, 10, 3000.0]],
        columns=[col[0] for col in cap_columns],
    )

    st.subheader("Purchase Order Template")
    st.dataframe(po_template, width="stretch")
    st.download_button(
        label="Download Purchase Order Template",
        data=po_template.to_csv(index=False),
        file_name="purchase_order_template.csv",
        mime="text/csv",
    )

    st.subheader("Container Capacity Template")
    st.dataframe(cap_template, width="stretch")
    st.download_button(
        label="Download Container Capacity Template",
        data=cap_template.to_csv(index=False),
        file_name="container_capacity_template.csv",
        mime="text/csv",
    )

    st.markdown("""
    ## Column Descriptions
    """)

    st.markdown("### Purchase Order Columns")
    for col, dtype in po_columns:
        st.markdown(f"- **{col}**: `{dtype}`")

    st.markdown("### Container Capacity Columns")
    for col, dtype in cap_columns:
        st.markdown(f"- **{col}**: `{dtype}`")
