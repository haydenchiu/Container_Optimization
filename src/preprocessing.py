import pandas as pd
import numpy as np
from datetime import datetime, timedelta
# from .volume_utils import compute_volume
# from .date_utils import parse_week_year_to_date

def compute_volume(length_cm, width_cm, height_cm):
    # Convert cm³ to m³
    return (length_cm * width_cm * height_cm) / 1e6

def parse_week_year_to_date(week_year):
    # Convert '2025-W25' to a Monday datetime object
    year, week = int(week_year[:4]), int(week_year[-2:])
    return datetime.strptime(f'{year}-W{week}-1', "%Y-W%W-%w")


def preprocess_data(po_path, capacity_path):
    # Load data
    po_df = pd.read_csv(po_path, dtype={
        "PO Number": str,
        "PO Line Number": int,
        "SKU": str,
        "Product Name": str,
        "Product Family": str,
        "IsElectronic": int,
        "COGS": float,
        "From Port": str,
        "To Port": str,
        "To Be Shipped Quantity": int,
        "Length (cm)": float,
        "Width (cm)": float,
        "Height (cm)": float,
        "Weight (kg)": float,
        "Priority Level": int,
        "Unmet Penalty": float
    })

    cap_df = pd.read_csv(capacity_path, dtype={
        "Week_Year": str,
        "From Port": str,
        "To Port": str,
        "Carrier": str,
        "Container Type": str,
        "Available Units": int,
        "Max Volume (m³)": float,
        "Max Weight (kg)": float,
        "Estimated Transit Time (days)": int,
        "Price (USD)": float
    })

    # --- Schema Validation ---
    required_po_cols = {
        "PO Number", "PO Line Number", "SKU", "Product Name",
        "Product Family", "IsElectronic", "COGS", "From Port",
        "To Port", "Export ETA", "Import ETA", "To Be Shipped Quantity",
        "Length (cm)", "Width (cm)", "Height (cm)", "Weight (kg)",
        "Priority Level", "Unmet Penalty"
    }

    required_cap_cols = {
        "Week_Year", "From Port", "To Port", "Carrier", "Container Type",
        "Available Units", "Max Volume (m³)", "Max Weight (kg)",
        "Estimated Transit Time (days)", "Price (USD)"
    }

    assert required_po_cols.issubset(po_df.columns), \
        f"Missing required PO columns: {required_po_cols - set(po_df.columns)}"
    assert required_cap_cols.issubset(cap_df.columns), \
        f"Missing required capacity columns: {required_cap_cols - set(cap_df.columns)}"

    # --- Compute Volume ---
    po_df["Volume (m3)"] = compute_volume(
        po_df["Length (cm)"], po_df["Width (cm)"], po_df["Height (cm)"]
    )

    # --- Date Parsing ---
    po_df["Export ETA"] = pd.to_datetime(po_df["Export ETA"], format="%d/%m/%Y", errors="raise")
    po_df["Import ETA"] = pd.to_datetime(po_df["Import ETA"], format="%d/%m/%Y", errors="raise")
    cap_df["Departure Date"] = cap_df["Week_Year"].apply(parse_week_year_to_date)
    cap_df["Arrival Date"] = cap_df["Departure Date"] + pd.to_timedelta(
        cap_df["Estimated Transit Time (days)"], unit='D'
    )

    # --- Expand by Available Units ---
    expanded_rows = []
    for _, row in cap_df.iterrows():
        available_units = int(row.get("Available Units", 1))
        base_id = f"{row['Week_Year']}_{row['From Port']}_{row['To Port']}_{row['Carrier']}_{row['Container Type']}"
        for i in range(1, available_units + 1):
            new_row = row.copy()
            new_row["Shipment ID"] = f"{base_id}-{i}"
            new_row["Base Shipment ID"] = base_id
            expanded_rows.append(new_row)

    cap_df_expanded = pd.DataFrame(expanded_rows)

    return po_df, cap_df_expanded


if __name__ == "__main__":
    po_df, cap_df = preprocess_data("data/sample_purchase_order_v1.csv", "data/sample_container_capacity.csv")
    print(po_df.head())
    print(cap_df.head())