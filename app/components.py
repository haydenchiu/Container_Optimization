import streamlit as st
import pandas as pd
import io
import plotly.express as px
from src.preprocessing import preprocess_data
from src.optimizer import optimize_shipping

def show_dashboard():

    st.set_page_config(page_title="Container Optimization Dashboard", layout="wide",initial_sidebar_state="expanded")
    st.title("📦 Container Shipping Optimizer")

    st.markdown("""
    Upload your purchase order and container capacity files below, configure parameters, and run the optimization.
    """)

    # --- File Upload ---
    po_file = st.file_uploader("Upload Purchase Order CSV", type="csv", key="po_upload")
    cap_file = st.file_uploader("Upload Container Capacity CSV", type="csv", key="cap_upload")

    # --- Sidebar Config ---
    st.sidebar.header("Penalty Configuration")
    late_penalty_per_day = st.sidebar.number_input("Late Penalty per Day", value=2, min_value=0, key="late_penalty_per_day", help="Cost per day for late delivery")
    priority_multiplier = st.sidebar.number_input("Priority Multiplier", value=2, min_value=1, key="priority_multiplier")

    # --- Run Optimization ---
    if st.button("Run Optimization"):
        if po_file and cap_file:
            try:
                po_df, cap_df = preprocess_data(po_file, cap_file)
                results_df = optimize_shipping(po_df, cap_df, late_penalty_per_day, priority_multiplier)

                # Derive temporal fields
                if "Export ETA" in results_df.columns:
                    results_df['Export Date'] = pd.to_datetime(results_df["Export ETA"])
                    results_df['Export Year'] = results_df['Export Date'].dt.strftime('%Y')
                    results_df['Export YearMonth'] = results_df['Export Date'].dt.strftime('%Y-%m')
                    results_df['Export YearWeek'] = results_df['Export Date'].dt.strftime('%Y-%U')

                st.session_state["results_df"] = results_df
                st.session_state["cap_df"] = cap_df
                st.session_state["po_file"] = po_file
                st.session_state["cap_file"] = cap_file
            except Exception as e:
                st.error(f"❌ Error: {e}")
                st.stop()
        else:
            st.warning("⚠️ Please upload both CSV files to continue.")
            st.stop()

    # Reuse cached data if available
    if "results_df" in st.session_state and "cap_df" in st.session_state:
        results_df = st.session_state["results_df"]
        cap_df = st.session_state["cap_df"]

        # Shared filter inputs
        st.sidebar.subheader("🔍 Filters")
        filter_po = st.sidebar.text_input("Filter by PO Number (partial match)", key="filter_po")
        filter_export_year = st.sidebar.multiselect("Filter by Export Year", options=sorted(results_df['Export Year'].dropna().unique()), key="filter_year", help="Using export ETA")
        filter_export_yearmonth = st.sidebar.multiselect("Filter by Export YearMonth", options=sorted(results_df['Export YearMonth'].dropna().unique()), key="filter_yearmonth", help="Using export ETA")
        filter_export_yearweek = st.sidebar.multiselect("Filter by Export YearWeek", options=sorted(results_df['Export YearWeek'].dropna().unique()), key="filter_yearweek", help="Using export ETA")

        filtered_df = results_df.copy()
        if filter_po:
            filtered_df = filtered_df[filtered_df['PO Number'].astype(str).str.contains(filter_po)]
        if filter_export_year:
            filtered_df = filtered_df[filtered_df['Export Year'].isin(filter_export_year)]
        if filter_export_yearmonth:
            filtered_df = filtered_df[filtered_df['Export YearMonth'].isin(filter_export_yearmonth)]
        if filter_export_yearweek:
            filtered_df = filtered_df[filtered_df['Export YearWeek'].isin(filter_export_yearweek)]

        # Sorting and grouping controls
        st.sidebar.subheader("📊 Data Display Settings")
        groupable_cols = [
            "PO Number", "PO Line Number", "SKU", "Product Name", "Product Family",
            "To Port", "Carrier", "Shipment ID", "Base Shipment ID",
            "Export Year", "Export YearMonth", "Export YearWeek"
        ]
        numeric_cols = ["Qty Assigned", "Unmet Qty", "Unmet Penalty", "Late Penalty", "COGS Value Assigned", "COGS Value Unmet"]

        valid_groupable_cols = [col for col in groupable_cols if col in filtered_df.columns]
        valid_numeric_cols = [col for col in numeric_cols if col in filtered_df.columns]

        groupby_cols = st.sidebar.multiselect("Group by columns:", options=valid_groupable_cols, default=["PO Number", "PO Line Number"], key="groupby_cols")
        sort_by = st.sidebar.selectbox("Sort by column:", options=valid_numeric_cols, key="sort_by")
        sort_ascending = st.sidebar.radio("Sort Order", ["Ascending", "Descending"], key="sort_order") == "Ascending"

        st.success("✅ Optimization completed!")
        st.subheader("📊 KPI Summary")

        total_pos = filtered_df[["PO Number", "PO Line Number"]].drop_duplicates().shape[0]
        used_containers = filtered_df["Shipment ID"].dropna().nunique()
        # total_unmet = filtered_df["Unmet Qty"].sum()
        # total_assigned = filtered_df["Qty Assigned"].sum()
        total_unmet_value = filtered_df["COGS Value Unmet"].sum()
        total_assigned_value = filtered_df["COGS Value Assigned"].sum()

    
        # total_late_penalty = (filtered_df["Late Days"].fillna(0) * late_penalty_per_day * (priority_multiplier ** filtered_df["Priority Level"].fillna(0))).sum()

        total_cost = (
            filtered_df["Unmet Penalty"].sum()
            + cap_df[cap_df["Shipment ID"].isin(filtered_df["Shipment ID"].unique())]["Price (USD)"].sum()
            + filtered_df["Late Penalty"].sum()
        )

        all_containers = set(cap_df["Shipment ID"])
        used_containers_set = set(filtered_df["Shipment ID"].dropna())
        # unused_containers = len(all_containers - used_containers_set)

        col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)
        col1.metric("Total PO Lines", total_pos)
        col2.metric("Used Containers", used_containers)
        # col3.metric("Total Qty Assigned", total_assigned)
        # col4.metric("Total Unmet Qty", total_unmet)
        col3.metric("Total Value Assigned", f"{total_assigned_value:,.0f}")
        col4.metric("Total Unmet Value", f"{total_unmet_value:,.0f}")
        col5.metric("Total Unmet Penalty", f"{filtered_df["Unmet Penalty"].sum():,.0f}")
        col6.metric("Total Late Penalty", f"{filtered_df["Late Penalty"].sum():,.0f}")
        col7.metric("Total Container Cost", f"{cap_df[cap_df["Shipment ID"].isin(filtered_df["Shipment ID"].unique())]["Price (USD)"].sum():,.0f}")
        col8.metric("Estimated Total Cost ($)", f"{total_cost:,.0f}")

        st.subheader("📈 Visualization")

        po_status = filtered_df.groupby(["PO Number", "PO Line Number"], as_index=False).agg({
            "Qty Assigned": "sum",
            "Unmet Qty": "sum"
        })
        po_status["Status"] = po_status.apply(lambda row: "Fully Met" if row["Unmet Qty"] == 0 
                                                else ("Partially Met" if row["Qty Assigned"] > 0 else "Unmet"), axis=1)
        st.plotly_chart(px.histogram(po_status, x="Status", title="PO Line Fulfillment Status"), use_container_width=True)

        carrier_summary = filtered_df.groupby(["Carrier", "PO Number"], as_index=False)["Qty Assigned"].sum()
        st.plotly_chart(px.bar(carrier_summary, x="Carrier", y="Qty Assigned", color="PO Number",
                            title="Assigned Quantities per Carrier by PO Number"), use_container_width=True)

        cogs_status = filtered_df.groupby(["PO Number", "PO Line Number", "COGS"], as_index=False).agg({
            "Qty Assigned": "sum",
            "Unmet Qty": "sum"
        })
        cogs_status["Status"] = cogs_status.apply(
            lambda row: "Fully Met" if row["Unmet Qty"] == 0
            else ("Partially Met" if row["Qty Assigned"] > 0 else "Unmet"),
            axis=1
        )
        cogs_status["COGS Value"] = (cogs_status["Qty Assigned"] + cogs_status["Unmet Qty"]) * cogs_status["COGS"]

        st.plotly_chart(
            px.pie(cogs_status.groupby("Status", as_index=False).agg({"COGS Value": "sum"}),
                names="Status", values="COGS Value", title="COGS Breakdown by Fulfillment Status"),
            use_container_width=True
        )

        if "Product Family" in filtered_df.columns:
            fam_summary = filtered_df.groupby("Product Family", as_index=False).agg({
                "Qty Assigned": "sum",
                "Unmet Qty": "sum",
                "COGS": "mean"
            })
            fam_summary["Assigned Value"] = fam_summary["Qty Assigned"] * fam_summary["COGS"]
            fam_summary["Unmet Value"] = fam_summary["Unmet Qty"] * fam_summary["COGS"]

            fam_melted = fam_summary.melt(id_vars="Product Family", value_vars=["Assigned Value", "Unmet Value"],
                                        var_name="Status", value_name="COGS Value")
            st.plotly_chart(
                px.bar(fam_melted, x="Product Family", y="COGS Value", color="Status", barmode="stack",
                    title="COGS Fulfillment by Product Family"),
                use_container_width=True
            )

        st.subheader("📊 Aggregated Results")

        if groupby_cols:
            try:
                display_df = filtered_df.groupby(groupby_cols, as_index=False)[valid_numeric_cols].sum()
            except Exception as e:
                st.error(f"⚠️ Aggregation failed: {e}")
                display_df = filtered_df.copy()
        else:
            display_df = filtered_df.copy()

        if not display_df.empty and sort_by in display_df.columns:
            display_df = display_df.sort_values(by=sort_by, ascending=sort_ascending)

            st.dataframe(display_df, use_container_width=True)
            st.download_button(
                label="Download Aggregated CSV",
                data=display_df.to_csv(index=False),
                file_name="aggregated_results.csv",
                mime="text/csv"
            )
        else:
            st.warning("No data available for aggregation.")

        unused_df = cap_df[cap_df["Shipment ID"].isin(all_containers - used_containers_set)]
        st.subheader("🪣 Unused Container Details")
        st.dataframe(unused_df[[
            "Shipment ID", "Base Shipment ID", "From Port", "To Port", "Carrier",
            "Container Type", "Departure Date", "Arrival Date", "Max Volume (m³)",
            "Max Weight (kg)", "Price (USD)"
        ]], use_container_width=True)

        csv = filtered_df.to_csv(index=False)
        st.download_button("Download Full Results CSV", csv, "optimized_results.csv", "text/csv")




def show_definitions():
    st.title("📘 Definitions & Assumptions")

    st.markdown("""
    ## 📦 Purchase Order (PO) Data
    - **PO Number / PO Line Number**: Unique identifiers for each purchase order and item line.
    - **SKU**: Stock Keeping Unit, uniquely identifies a product.
    - **Product Name / Family**: Name and category of the product.
    - **IsElectronic**: 1 if the product is electronic; otherwise 0.
    - **COGS**: Cost of Goods Sold per unit.
    - **Export ETA / Import ETA**: Expected shipping and receiving dates.
    - **To Be Shipped Quantity**: Demand quantity for this PO line.

    ## 🚢 Container Capacity Data
    - **Week_Year**: The week of the shipment.
    - **Available Units**: Number of available containers for this configuration.
    - **From/To Port**: Origin and destination of the shipment.
    - **Carrier / Container Type**: Shipping provider and container size.
    - **Estimated Transit Time (days)**: Time from departure to arrival.
    - **Price (USD)**: Cost of using one container.

    ## 🧮 Optimization Logic
    - **Objective**: Minimize total cost, combining:
        - Late penalty (days late × late penalty per day × (priority multiplier ^ priority level))
        - Container costs (fixed per unit)
        - Unmet penalty (unmet penalty × unmet quantity)
    - **Constraints**:
        - Shipment date must be on or after Export ETA
        - Volume/weight must not exceed container limits
        - Containers limited by availability (expanded into unique shipment IDs)

    ## 📊 KPIs and Metrics
    - **Used Containers**: Number of containers utilized in assignments
    - **Unused Containers**: Available containers not used in optimization
    - **Total Unmet Quantity**: Demand not fulfilled by any container
    - **Estimated Total Cost**: Sum of all penalties and container costs

    ## 🎯 Fulfillment Status Classification
    - **Fully Met**: All ordered quantity shipped
    - **Partially Met**: Some but not all quantity shipped
    - **Unmet**: No quantity shipped for the PO line

    ## 📈 Visualizations
    - **PO Fulfillment Status (by count and COGS)**
    - **Carrier Distribution of Assignments**
    - **Container Usage Summary**

    """)

def show_download_templates():
    st.title("📂 Download CSV Templates")

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
        ("Priority Level", "int"),
        ("Unmet Penalty", "float")
    ]

    po_template = pd.DataFrame([
        ["PO001", 1, "SKU1001", "Smartphone X", "Electronics", 1, 250, "HK", "LA", "15/06/2025", "25/06/2025", 10, 15.0, 7.5, 0.8, 0.2, 2, 1000]
    ], columns=[col[0] for col in po_columns])

    # Define Capacity template schema
    cap_columns = [
        ("Week_Year", "str (e.g. 2025-W25)"),
        ("From Port", "str"),
        ("To Port", "str"),
        ("Carrier", "str"),
        ("Container Type", "str"),
        ("Available Units", "int"),
        ("Max Volume (m³)", "float"),
        ("Max Weight (kg)", "float"),
        ("Estimated Transit Time (days)", "int"),
        ("Price (USD)", "float")
    ]

    cap_template = pd.DataFrame([
        ["2025-W25", "HK", "LA", "Maersk", "40FT", 3, 66.0, 26500.0, 10, 3000.0]
    ], columns=[col[0] for col in cap_columns])

    st.subheader("📄 Purchase Order Template")
    st.dataframe(po_template, use_container_width=True)
    st.download_button(
        label="Download Purchase Order Template",
        data=po_template.to_csv(index=False),
        file_name="purchase_order_template.csv",
        mime="text/csv"
    )

    st.subheader("🚚 Container Capacity Template")
    st.dataframe(cap_template, use_container_width=True)
    st.download_button(
        label="Download Container Capacity Template",
        data=cap_template.to_csv(index=False),
        file_name="container_capacity_template.csv",
        mime="text/csv"
    )

    st.markdown("""
    ## 🧾 Column Descriptions
    """)

    st.markdown("### Purchase Order Columns")
    for col, dtype in po_columns:
        st.markdown(f"- **{col}**: `{dtype}`")

    st.markdown("### Container Capacity Columns")
    for col, dtype in cap_columns:
        st.markdown(f"- **{col}**: `{dtype}`")

