"""Generate the scenario sample files in data/samples/.

Run with `uv run python scripts/generate_scenarios.py`. Output is deterministic.

Each scenario is a purchase order + container capacity pair built to show one behavior:
  1. irregular_schedule  - blank sailings, biweekly services, congestion, a suspended lane
  2. demand_surge        - one week of POs far above weekly capacity
  3. capacity_shortage   - total capacity below demand, so priority and value decide
  4. consolidation       - many small POs with plenty of capacity
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"
YEAR = 2025

# SKU: (name, family, is_electronic, COGS, length_cm, width_cm, height_cm)
CATALOG = {
    "SKU1001": ("Smartphone X", "Electronics", 1, 250, 33, 24, 13),
    "SKU1002": ("Coffee Maker", "Appliances", 1, 75, 32, 49, 16),
    "SKU1003": ("Notebook A4", "Stationery", 0, 2, 36, 39, 42),
    "SKU1005": ("Bluetooth Speaker", "Electronics", 1, 45, 27, 44, 44),
    "SKU1006": ("Electric Kettle", "Appliances", 1, 40, 28, 29, 33),
    "SKU1010": ("Canvas Tote Bag", "Accessories", 0, 10, 47, 18, 44),
    "SKU1013": ("Sticky Notes", "Stationery", 0, 1, 14, 29, 40),
    "SKU1015": ("Action Camera", "Electronics", 1, 120, 42, 11, 21),
    "SKU1016": ("Mini Projector", "Electronics", 1, 130, 27, 48, 35),
    "SKU1017": ("Water Bottle", "Accessories", 0, 12, 36, 15, 25),
    "SKU1019": ("Mechanical Pencil", "Stationery", 0, 3, 29, 40, 46),
    "SKU1020": ("Rice Cooker", "Appliances", 1, 80, 44, 28, 44),
}
# Carton density in kg/m³, kept below the 40FT limit (26500 kg / 66 m³ ≈ 400 kg/m³).
DENSITY = {"Electronics": 220, "Appliances": 180, "Stationery": 350, "Accessories": 140}
CONTAINERS = {"20FT": (33.0, 18000.0), "40FT": (66.0, 26500.0)}


def monday(week: int) -> date:
    return date.fromisocalendar(YEAR, week, 1)


def next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


def fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def unit_volume(sku: str) -> float:
    *_, length, width, height = CATALOG[sku]
    return length * width * height / 1e6


def po_row(
    po_number: str,
    line: int,
    sku: str,
    lane: tuple[str, str],
    export: date,
    import_eta: date,
    volume_m3: float,
    priority: int,
    unmet_factor: float = 1.5,
) -> dict:
    name, family, is_electronic, cogs, length, width, height = CATALOG[sku]
    unit_vol = unit_volume(sku)
    return {
        "PO Number": po_number,
        "PO Line Number": line,
        "SKU": sku,
        "Product Name": name,
        "Product Family": family,
        "IsElectronic": is_electronic,
        "COGS": cogs,
        "From Port": lane[0],
        "To Port": lane[1],
        "Export ETA": fmt(export),
        "Import ETA": fmt(import_eta),
        "To Be Shipped Quantity": max(1, round(volume_m3 / unit_vol)),
        "Length (cm)": length,
        "Width (cm)": width,
        "Height (cm)": height,
        "Weight (kg)": round(unit_vol * DENSITY[family], 2),
        "Priority Level": priority,
        "Unmet Penalty": round(unmet_factor * cogs, 2),
    }


def cap_row(
    week: int,
    lane: tuple[str, str],
    carrier: str,
    container: str,
    units: int,
    transit: int,
    price: float,
) -> dict:
    max_vol, max_wt = CONTAINERS[container]
    return {
        "Week_Year": f"{YEAR}-W{week:02d}",
        "From Port": lane[0],
        "To Port": lane[1],
        "Carrier": carrier,
        "Container Type": container,
        "Available Units": units,
        "Max Volume (m³)": max_vol,
        "Max Weight (kg)": max_wt,
        "Estimated Transit Time (days)": transit,
        "Price (USD)": price,
    }


def random_weekday(rng: np.random.Generator, first_week: int, last_week: int) -> date:
    week = int(rng.integers(first_week, last_week + 1))
    return monday(week) + timedelta(days=int(rng.integers(0, 5)))


def on_time_eta(export: date, transit: int, slack: int) -> date:
    """Due date that is met only by the first sailing after export on the normal schedule."""
    return next_monday(export) + timedelta(days=transit + slack)


def irregular_schedule():
    rng = np.random.default_rng(1)
    hk_la, sh_la, sg_ny, sh_ny = ("HK", "LA"), ("SH", "LA"), ("SG", "NY"), ("SH", "NY")

    cap = []
    for week in [23, 24, 26, 27, 28]:  # W25 blank sailing
        cap.append(cap_row(week, hk_la, "MAERSK", "40FT", 1, 21 if week == 26 else 14, 4000))
    for week in [23, 25, 27]:  # biweekly service
        cap.append(cap_row(week, hk_la, "CMA", "20FT", 1, 14, 2000))
    for week in [24, 26]:  # premium express, biweekly
        cap.append(cap_row(week, hk_la, "MATSON", "20FT", 1, 9, 3400))
    for week in [24, 27]:  # one sailing every three weeks
        cap.append(cap_row(week, sh_la, "ONE", "40FT", 2, 16, 4200))
    sg_ny_transit = {23: 26, 24: 31, 25: 27, 26: 36, 27: 28, 28: 30}
    for week, transit in sg_ny_transit.items():
        cap.append(cap_row(week, sg_ny, "CMA", "40FT", 2, transit, 4600))

    po = []
    # lane, PO lines, normal transit days, (min, max) m³ per line, SKUs
    lanes = [
        (hk_la, 12, 14, (8, 16), ["SKU1001", "SKU1015", "SKU1002", "SKU1010", "SKU1005"]),
        (sh_la, 6, 16, (3, 8), ["SKU1020", "SKU1006", "SKU1016"]),
        (sg_ny, 6, 26, (4, 10), ["SKU1003", "SKU1017", "SKU1015"]),
        (sh_ny, 2, 30, (3, 6), ["SKU1002", "SKU1005"]),
    ]
    n = 0
    for lane, count, normal_transit, (vol_min, vol_max), skus in lanes:
        for k in range(count):
            n += 1
            export = random_weekday(rng, 23, 26)
            po.append(
                po_row(
                    f"PO-A{100 + n}",
                    1,
                    skus[k % len(skus)],
                    lane,
                    export,
                    on_time_eta(export, normal_transit, 4),
                    float(rng.uniform(vol_min, vol_max)),
                    int(rng.integers(0, 3)),
                )
            )
    return po, cap


def demand_surge():
    rng = np.random.default_rng(2)
    hk_la, sh_la = ("HK", "LA"), ("SH", "LA")

    cap = []
    for week in range(23, 31):
        cap.append(cap_row(week, hk_la, "MAERSK", "40FT", 2, 14, 4000))
        cap.append(cap_row(week, hk_la, "CMA", "20FT", 2, 14, 2000))
        cap.append(cap_row(week, sh_la, "ONE", "40FT", 1, 16, 4200))

    po = []
    n = 0
    hk_skus = ["SKU1001", "SKU1015", "SKU1005", "SKU1002", "SKU1020"]
    for week in [23, 24, 26, 27]:
        for _ in range(4):
            n += 1
            export = random_weekday(rng, week, week)
            po.append(
                po_row(
                    f"PO-B{100 + n}",
                    1,
                    hk_skus[n % len(hk_skus)],
                    hk_la,
                    export,
                    on_time_eta(export, 14, 4),
                    float(rng.uniform(5, 9)),
                    int(rng.integers(0, 3)),
                )
            )
    surge_export = monday(25)
    for k in range(12):
        n += 1
        po.append(
            po_row(
                f"PO-B{100 + n}",
                1,
                hk_skus[k % len(hk_skus)],
                hk_la,
                surge_export,
                on_time_eta(surge_export, 14, 4),
                float(rng.uniform(32, 45)),
                [2, 1, 0][k % 3],
            )
        )
    for week in range(23, 28):
        for _ in range(3):
            n += 1
            export = random_weekday(rng, week, week)
            po.append(
                po_row(
                    f"PO-B{100 + n}",
                    1,
                    ["SKU1006", "SKU1016", "SKU1010"][n % 3],
                    sh_la,
                    export,
                    on_time_eta(export, 16, 4),
                    float(rng.uniform(10, 18)),
                    int(rng.integers(0, 3)),
                )
            )
    return po, cap


def capacity_shortage():
    rng = np.random.default_rng(3)
    sg_sf = ("SG", "SF")

    cap = []
    for week in [23, 24, 25]:
        cap.append(cap_row(week, sg_sf, "CMA", "40FT", 1, 16, 4000))
        cap.append(cap_row(week, sg_sf, "MAERSK", "20FT", 1, 16, 2000))

    groups = [
        ("PO-KEY", 2, ["SKU1001", "SKU1015", "SKU1016"]),  # key account
        ("PO-MKT", 0, ["SKU1001", "SKU1015", "SKU1016"]),  # marketplace restock, same SKUs
        ("PO-RTL", 1, ["SKU1002", "SKU1020", "SKU1006"]),  # retail appliances
        ("PO-OFC", 1, ["SKU1003", "SKU1019", "SKU1013"]),  # office supplies
    ]
    po = []
    for prefix, priority, skus in groups:
        for line, sku in enumerate(skus, start=1):
            export = monday(23) + timedelta(days=int(rng.integers(0, 3)) * 7)
            po.append(
                po_row(
                    f"{prefix}-01",
                    line,
                    sku,
                    sg_sf,
                    export,
                    on_time_eta(export, 16, 10),
                    float(rng.uniform(35, 45)),
                    priority,
                    unmet_factor=1.0,
                )
            )
    return po, cap


def consolidation():
    rng = np.random.default_rng(4)
    lanes = {("HK", "LA"): 14, ("HK", "NY"): 20, ("SG", "SF"): 16}

    cap = []
    for lane, transit in lanes.items():
        for week in range(23, 30):
            cap.append(cap_row(week, lane, "MAERSK", "20FT", 2, transit, 2000))
            cap.append(cap_row(week, lane, "CMA", "40FT", 2, transit, 4000))

    high_value = ["SKU1001", "SKU1015", "SKU1016", "SKU1005"]
    low_value = ["SKU1003", "SKU1013", "SKU1010", "SKU1017"]
    po = []
    for n in range(40):
        lane = list(lanes)[n % len(lanes)]
        export = random_weekday(rng, 23, 26)
        sku = (high_value if n % 2 == 0 else low_value)[(n // 2) % 4]
        po.append(
            po_row(
                f"PO-D{100 + n}",
                1,
                sku,
                lane,
                export,
                on_time_eta(export, lanes[lane], 3),
                float(rng.uniform(0.5, 3.0)),
                int(rng.integers(0, 3)),
            )
        )
    return po, cap


SCENARIOS = {
    "scenario1_irregular_schedule": irregular_schedule,
    "scenario2_demand_surge": demand_surge,
    "scenario3_capacity_shortage": capacity_shortage,
    "scenario4_consolidation": consolidation,
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug, build in SCENARIOS.items():
        po, cap = build()
        pd.DataFrame(po).to_csv(OUT_DIR / f"{slug}_purchase_order.csv", index=False)
        pd.DataFrame(cap).to_csv(OUT_DIR / f"{slug}_container_capacity.csv", index=False)
        print(f"{slug}: {len(po)} PO lines, {len(cap)} capacity rows")


if __name__ == "__main__":
    main()
