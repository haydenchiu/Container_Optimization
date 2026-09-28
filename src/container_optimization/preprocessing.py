"""Load, validate and reshape the purchase order and container capacity CSVs."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

PO_DTYPES = {
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
    "Unmet Penalty": float,
}
PO_DATE_COLS = ["Export ETA", "Import ETA"]
PO_DATE_FORMAT = "%d/%m/%Y"

CAP_DTYPES = {
    "Week_Year": str,
    "From Port": str,
    "To Port": str,
    "Carrier": str,
    "Container Type": str,
    "Available Units": int,
    "Max Volume (m³)": float,
    "Max Weight (kg)": float,
    "Estimated Transit Time (days)": int,
    "Price (USD)": float,
}

REQUIRED_PO_COLS = set(PO_DTYPES) | set(PO_DATE_COLS)
REQUIRED_CAP_COLS = set(CAP_DTYPES)


class DataValidationError(ValueError):
    """Raised when an input file is missing columns or contains invalid values."""


def compute_volume(length_cm, width_cm, height_cm):
    """Convert per-unit dimensions in cm to a volume in m³."""
    return (length_cm * width_cm * height_cm) / 1e6


def parse_week_year_to_date(week_year: str) -> pd.Timestamp:
    """Return the Monday of an ISO 8601 week string such as '2025-W25'."""
    try:
        year_str, week_str = week_year.strip().upper().split("-W")
        return pd.Timestamp(date.fromisocalendar(int(year_str), int(week_str), 1))
    except ValueError as exc:
        raise DataValidationError(
            f"Invalid Week_Year {week_year!r}; expected ISO format like '2025-W25'"
        ) from exc


def _read_csv(source, required_cols: set[str], dtypes: dict, label: str) -> pd.DataFrame:
    df = pd.read_csv(source, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()

    missing = required_cols - set(df.columns)
    if missing:
        raise DataValidationError(f"Missing required {label} columns: {sorted(missing)}")

    try:
        return df.astype(dtypes)
    except (ValueError, TypeError) as exc:
        raise DataValidationError(f"Invalid values in {label} file: {exc}") from exc


def _check(problems: list[str], mask: pd.Series, message: str) -> None:
    if mask.any():
        rows = (mask[mask].index + 2).tolist()[:10]
        problems.append(f"{message} (CSV rows {rows})")


def validate_po(po_df: pd.DataFrame) -> None:
    problems: list[str] = []
    _check(problems, po_df["To Be Shipped Quantity"] <= 0, "To Be Shipped Quantity must be > 0")
    for col in ["Length (cm)", "Width (cm)", "Height (cm)", "Weight (kg)"]:
        _check(problems, po_df[col] <= 0, f"{col} must be > 0")
    for col in ["COGS", "Unmet Penalty", "Priority Level"]:
        _check(problems, po_df[col] < 0, f"{col} must be >= 0")
    _check(problems, ~po_df["IsElectronic"].isin([0, 1]), "IsElectronic must be 0 or 1")
    _check(
        problems,
        po_df["Import ETA"] < po_df["Export ETA"],
        "Import ETA must be on/after Export ETA",
    )
    if problems:
        raise DataValidationError("Purchase order file is invalid:\n- " + "\n- ".join(problems))


def validate_capacity(cap_df: pd.DataFrame) -> None:
    problems: list[str] = []
    _check(problems, cap_df["Available Units"] < 0, "Available Units must be >= 0")
    for col in ["Max Volume (m³)", "Max Weight (kg)"]:
        _check(problems, cap_df[col] <= 0, f"{col} must be > 0")
    for col in ["Estimated Transit Time (days)", "Price (USD)"]:
        _check(problems, cap_df[col] < 0, f"{col} must be >= 0")
    if problems:
        raise DataValidationError("Container capacity file is invalid:\n- " + "\n- ".join(problems))


def find_unserved_lanes(po_df: pd.DataFrame, cap_df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return PO (From Port, To Port) lanes that no container in the capacity file serves."""
    po_lanes = set(zip(po_df["From Port"], po_df["To Port"], strict=True))
    cap_lanes = set(zip(cap_df["From Port"], cap_df["To Port"], strict=True))
    return sorted(po_lanes - cap_lanes)


def expand_available_units(cap_df: pd.DataFrame) -> pd.DataFrame:
    """Turn each capacity row into one row per physical container."""
    expanded = cap_df.loc[cap_df.index.repeat(cap_df["Available Units"])].reset_index(drop=True)
    expanded["Base Shipment ID"] = (
        expanded["Week_Year"]
        + "_"
        + expanded["From Port"]
        + "_"
        + expanded["To Port"]
        + "_"
        + expanded["Carrier"]
        + "_"
        + expanded["Container Type"]
    )
    unit_number = expanded.groupby("Base Shipment ID").cumcount() + 1
    expanded["Shipment ID"] = expanded["Base Shipment ID"] + "-" + unit_number.astype(str)
    return expanded


def preprocess_data(po_path, capacity_path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load both files, validate them and derive volume, dates and per-container rows."""
    po_df = _read_csv(po_path, REQUIRED_PO_COLS, PO_DTYPES, "PO")
    cap_df = _read_csv(capacity_path, REQUIRED_CAP_COLS, CAP_DTYPES, "capacity")

    try:
        for col in PO_DATE_COLS:
            po_df[col] = pd.to_datetime(po_df[col], format=PO_DATE_FORMAT)
    except ValueError as exc:
        raise DataValidationError(f"PO dates must use DD/MM/YYYY: {exc}") from exc

    validate_po(po_df)
    validate_capacity(cap_df)

    po_df["Volume (m3)"] = compute_volume(
        po_df["Length (cm)"], po_df["Width (cm)"], po_df["Height (cm)"]
    )

    week_starts = {wk: parse_week_year_to_date(wk) for wk in cap_df["Week_Year"].unique()}
    cap_df["Departure Date"] = cap_df["Week_Year"].map(week_starts)
    cap_df["Arrival Date"] = cap_df["Departure Date"] + pd.to_timedelta(
        cap_df["Estimated Transit Time (days)"], unit="D"
    )

    for lane in find_unserved_lanes(po_df, cap_df):
        logger.warning("No container capacity for lane %s -> %s", *lane)

    return po_df, expand_available_units(cap_df)


if __name__ == "__main__":
    po, cap = preprocess_data(
        "data/samples/sample_purchase_order_v1.csv", "data/samples/sample_container_capacity_v1.csv"
    )
    print(po.head())
    print(cap.head())
