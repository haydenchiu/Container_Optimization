from pathlib import Path

import pandas as pd
import pytest

from container_optimization.preprocessing import (
    DataValidationError,
    expand_available_units,
    find_unserved_lanes,
    parse_week_year_to_date,
    preprocess_data,
)

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"

PO_ROW = {
    "PO Number": "PO1",
    "PO Line Number": 1,
    "SKU": "SKU1",
    "Product Name": "Widget",
    "Product Family": "Accessories",
    "IsElectronic": 0,
    "COGS": 10.0,
    "From Port": "HK",
    "To Port": "LA",
    "Export ETA": "01/06/2025",
    "Import ETA": "20/06/2025",
    "To Be Shipped Quantity": 5,
    "Length (cm)": 10.0,
    "Width (cm)": 10.0,
    "Height (cm)": 10.0,
    "Weight (kg)": 1.0,
    "Priority Level": 1,
    "Unmet Penalty": 100.0,
}

CAP_ROW = {
    "Week_Year": "2025-W23",
    "From Port": "HK",
    "To Port": "LA",
    "Carrier": "ONE",
    "Container Type": "40FT",
    "Available Units": 2,
    "Max Volume (m³)": 66.0,
    "Max Weight (kg)": 26500.0,
    "Estimated Transit Time (days)": 10,
    "Price (USD)": 3000.0,
}


def write_csvs(tmp_path, po_rows=None, cap_rows=None):
    po_path, cap_path = tmp_path / "po.csv", tmp_path / "cap.csv"
    pd.DataFrame(po_rows or [PO_ROW]).to_csv(po_path, index=False)
    pd.DataFrame(cap_rows or [CAP_ROW]).to_csv(cap_path, index=False)
    return po_path, cap_path


@pytest.mark.parametrize(
    ("week", "monday"),
    [
        ("2025-W25", "2025-06-16"),
        ("2025-W01", "2024-12-30"),
        ("2026-W01", "2025-12-29"),
        ("2026-W53", "2026-12-28"),
    ],
)
def test_parse_week_year_uses_iso_weeks(week, monday):
    assert parse_week_year_to_date(week) == pd.Timestamp(monday)


@pytest.mark.parametrize("week", ["2025-25", "2025-W54", "W25-2025"])
def test_parse_week_year_rejects_bad_values(week):
    with pytest.raises(DataValidationError):
        parse_week_year_to_date(week)


def test_expand_available_units_gives_unique_ids():
    cap = pd.DataFrame(
        [
            CAP_ROW,
            {**CAP_ROW, "Available Units": 1},
            {**CAP_ROW, "Carrier": "MSC", "Available Units": 0},
        ]
    )
    expanded = expand_available_units(cap)

    assert len(expanded) == 3
    assert expanded["Shipment ID"].is_unique
    assert expanded["Shipment ID"].tolist() == [
        "2025-W23_HK_LA_ONE_40FT-1",
        "2025-W23_HK_LA_ONE_40FT-2",
        "2025-W23_HK_LA_ONE_40FT-3",
    ]


def test_preprocess_data_derives_volume_and_dates(tmp_path):
    po_df, cap_df = preprocess_data(*write_csvs(tmp_path))

    assert po_df.loc[0, "Volume (m3)"] == pytest.approx(0.001)
    assert po_df.loc[0, "Export ETA"] == pd.Timestamp("2025-06-01")
    assert len(cap_df) == 2
    assert (cap_df["Departure Date"] == pd.Timestamp("2025-06-02")).all()
    assert (cap_df["Arrival Date"] == pd.Timestamp("2025-06-12")).all()


def test_missing_column_raises(tmp_path):
    po_row = {k: v for k, v in PO_ROW.items() if k != "COGS"}
    with pytest.raises(DataValidationError, match="COGS"):
        preprocess_data(*write_csvs(tmp_path, po_rows=[po_row]))


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"To Be Shipped Quantity": 0}, "To Be Shipped Quantity"),
        ({"Length (cm)": -1.0}, "Length"),
        ({"IsElectronic": 2}, "IsElectronic"),
        ({"Import ETA": "01/05/2025"}, "Import ETA"),
        ({"Export ETA": "2025-06-01"}, "DD/MM/YYYY"),
    ],
)
def test_invalid_po_values_raise(tmp_path, override, message):
    with pytest.raises(DataValidationError, match=message):
        preprocess_data(*write_csvs(tmp_path, po_rows=[{**PO_ROW, **override}]))


def test_invalid_capacity_values_raise(tmp_path):
    with pytest.raises(DataValidationError, match="Max Volume"):
        preprocess_data(*write_csvs(tmp_path, cap_rows=[{**CAP_ROW, "Max Volume (m³)": 0}]))


def test_find_unserved_lanes():
    po = pd.DataFrame({"From Port": ["HK", "SG"], "To Port": ["LA", "NY"]})
    cap = pd.DataFrame({"From Port": ["HK"], "To Port": ["LA"]})
    assert find_unserved_lanes(po, cap) == [("SG", "NY")]


def test_sample_files_load():
    po_df, cap_df = preprocess_data(
        SAMPLES / "sample_purchase_order_v1.csv", SAMPLES / "sample_container_capacity_v1.csv"
    )
    assert len(po_df) == 70
    assert len(cap_df) == 289
    assert (cap_df["Departure Date"].dt.dayofweek == 0).all()
