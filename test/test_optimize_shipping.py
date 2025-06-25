import pytest
import pandas as pd
from datetime import datetime
from optimizer import optimize_shipping  # Replace with actual module name


def make_po_df(data):
    return pd.DataFrame(data)

def make_cap_df(data):
    return pd.DataFrame(data)

def test_case_1_basic_assignment():
    po_df = make_po_df([{
        "PO Number": "PO1", "PO Line Number": 1, "SKU": "SKU1",
        "From Port": "HK", "To Port": "LA",
        "Export ETA": "2025-06-01", "Import ETA": "2025-06-10",
        "To Be Shipped Quantity": 5, "Volume (m3)": 1, "Weight (kg)": 100,
        "Priority Level": 1, "Unmet Penalty": 1000
    }])
    cap_df = make_cap_df([{
        "Shipment ID": "S1-1", "Base Shipment ID": "S1",
        "From Port": "HK", "To Port": "LA",
        "Departure Date": pd.Timestamp("2025-06-02"),
        "Arrival Date": pd.Timestamp("2025-06-08"),
        "Price (USD)": 500, "Max Volume (m³)": 10, "Max Weight (kg)": 2000,
        "Carrier": "ONE", "Container Type": "40FT"
    }])

    po_df["Export ETA"] = pd.to_datetime(po_df["Export ETA"])
    po_df["Import ETA"] = pd.to_datetime(po_df["Import ETA"])

    results = optimize_shipping(po_df, cap_df)
    assert results["Qty Assigned"].sum() == 5
    assert results["Unmet Qty"].sum() == 0
    assert results["Used Container"].sum() == 1

def test_case_2_no_feasible_shipment():
    po_df = make_po_df([{
        "PO Number": "PO2", "PO Line Number": 1, "SKU": "SKU2",
        "From Port": "HK", "To Port": "NY",
        "Export ETA": "2025-06-10", "Import ETA": "2025-06-20",
        "To Be Shipped Quantity": 10, "Volume (m3)": 1, "Weight (kg)": 100,
        "Priority Level": 2, "Unmet Penalty": 2000
    }])
    cap_df = make_cap_df([{
        "Shipment ID": "S2-1", "Base Shipment ID": "S2",
        "From Port": "HK", "To Port": "NY",
        "Departure Date": pd.Timestamp("2025-06-01"),
        "Arrival Date": pd.Timestamp("2025-06-05"),
        "Price (USD)": 500, "Max Volume (m³)": 20, "Max Weight (kg)": 5000,
        "Carrier": "MSC", "Container Type": "20FT"
    }])

    po_df["Export ETA"] = pd.to_datetime(po_df["Export ETA"])
    po_df["Import ETA"] = pd.to_datetime(po_df["Import ETA"])

    results = optimize_shipping(po_df, cap_df)
    assert results["Qty Assigned"].sum() == 0
    assert results["Unmet Qty"].sum() == 10
    assert results.iloc[0]["Unmet Penalty"] == 20000

def test_case_3_partial_assignment_due_to_capacity():
    po_df = make_po_df([{
        "PO Number": "PO3", "PO Line Number": 1, "SKU": "SKU3",
        "From Port": "HK", "To Port": "SF",
        "Export ETA": "2025-06-05", "Import ETA": "2025-06-15",
        "To Be Shipped Quantity": 10, "Volume (m3)": 20, "Weight (kg)": 1000,
        "Priority Level": 1, "Unmet Penalty": 500
    }])
    cap_df = make_cap_df([{
        "Shipment ID": "S3-1", "Base Shipment ID": "S3",
        "From Port": "HK", "To Port": "SF",
        "Departure Date": pd.Timestamp("2025-06-06"),
        "Arrival Date": pd.Timestamp("2025-06-10"),
        "Price (USD)": 1000, "Max Volume (m³)": 60, "Max Weight (kg)": 3000,
        "Carrier": "CMA", "Container Type": "40FT"
    }])

    po_df["Export ETA"] = pd.to_datetime(po_df["Export ETA"])
    po_df["Import ETA"] = pd.to_datetime(po_df["Import ETA"])

    results = optimize_shipping(po_df, cap_df)
    assert 0 < results["Qty Assigned"].sum() < 10
    assert results["Unmet Qty"].sum() > 0

def test_case_4_multiple_containers():
    po_df = make_po_df([{
        "PO Number": "PO4", "PO Line Number": 1, "SKU": "SKU4",
        "From Port": "HK", "To Port": "LA",
        "Export ETA": "2025-06-01", "Import ETA": "2025-06-10",
        "To Be Shipped Quantity": 8, "Volume (m3)": 5, "Weight (kg)": 500,
        "Priority Level": 1, "Unmet Penalty": 1000
    }])
    cap_df = make_cap_df([
        {
            "Shipment ID": "S4-1", "Base Shipment ID": "S4",
            "From Port": "HK", "To Port": "LA",
            "Departure Date": pd.Timestamp("2025-06-02"),
            "Arrival Date": pd.Timestamp("2025-06-07"),
            "Price (USD)": 400, "Max Volume (m³)": 20, "Max Weight (kg)": 2000,
            "Carrier": "ONE", "Container Type": "20FT"
        },
        {
            "Shipment ID": "S4-2", "Base Shipment ID": "S4",
            "From Port": "HK", "To Port": "LA",
            "Departure Date": pd.Timestamp("2025-06-02"),
            "Arrival Date": pd.Timestamp("2025-06-07"),
            "Price (USD)": 400, "Max Volume (m³)": 20, "Max Weight (kg)": 2000,
            "Carrier": "ONE", "Container Type": "20FT"
        }
    ])

    po_df["Export ETA"] = pd.to_datetime(po_df["Export ETA"])
    po_df["Import ETA"] = pd.to_datetime(po_df["Import ETA"])

    results = optimize_shipping(po_df, cap_df)
    assert results["Qty Assigned"].sum() == 8
    assert results["Used Container"].sum() <= 2

def test_case_5_shared_container_across_po_lines():
    po_df = make_po_df([
        {
            "PO Number": "PO5", "PO Line Number": 1, "SKU": "SKU5A",
            "From Port": "HK", "To Port": "LA",
            "Export ETA": "2025-06-01", "Import ETA": "2025-06-12",
            "To Be Shipped Quantity": 3, "Volume (m3)": 1, "Weight (kg)": 100,
            "Priority Level": 1, "Unmet Penalty": 1000
        },
        {
            "PO Number": "PO5", "PO Line Number": 2, "SKU": "SKU5B",
            "From Port": "HK", "To Port": "LA",
            "Export ETA": "2025-06-01", "Import ETA": "2025-06-12",
            "To Be Shipped Quantity": 2, "Volume (m3)": 1, "Weight (kg)": 100,
            "Priority Level": 1, "Unmet Penalty": 1000
        }
    ])
    cap_df = make_cap_df([{
        "Shipment ID": "S5-1", "Base Shipment ID": "S5",
        "From Port": "HK", "To Port": "LA",
        "Departure Date": pd.Timestamp("2025-06-03"),
        "Arrival Date": pd.Timestamp("2025-06-09"),
        "Price (USD)": 600, "Max Volume (m³)": 10, "Max Weight (kg)": 2000,
        "Carrier": "ONE", "Container Type": "20FT"
    }])

    po_df["Export ETA"] = pd.to_datetime(po_df["Export ETA"])
    po_df["Import ETA"] = pd.to_datetime(po_df["Import ETA"])

    results = optimize_shipping(po_df, cap_df)
    assert results["Qty Assigned"].sum() == 5
    assert results["Used Container"].sum() == 1
