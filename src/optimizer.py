import pulp
import pandas as pd

def optimize_shipping(po_df, cap_df, late_penalty_per_day=2, priority_multiplier=2):
    model = pulp.LpProblem("PO_Container_Optimization", pulp.LpMinimize)
    assign = {}
    use_container = {}
    unmet_vars = {}

    # Feasible routes: PO line to shipment match
    feasible_routes = []
    for po_idx, po in po_df.iterrows():
        for cap_idx, cap in cap_df.iterrows():
            if (
                po["From Port"] == cap["From Port"] and
                po["To Port"] == cap["To Port"] and
                cap["Departure Date"] >= po["Export ETA"]
            ):
                feasible_routes.append((po_idx, cap["Shipment ID"]))

    print(f"Feasible routes found: {len(feasible_routes)}")

    # Create decision variables
    for po_idx, ship_id in feasible_routes:
        max_qty = po_df.loc[po_idx, "To Be Shipped Quantity"]
        assign[(po_idx, ship_id)] = pulp.LpVariable(f"x_{po_idx}_{ship_id}", 0, max_qty, cat='Integer')

    for ship_id in cap_df["Shipment ID"]:
        use_container[ship_id] = pulp.LpVariable(f"use_{ship_id}", cat='Binary')

    # Unmet variables
    for po_idx, po in po_df.iterrows():
        unmet = pulp.LpVariable(f"unmet_{po_idx}", 0, po["To Be Shipped Quantity"], cat='Integer')
        unmet_vars[po_idx] = unmet

    # Objective function: penalties + container cost
    objective_terms = []

    for (po_idx, ship_id), var in assign.items():
        po = po_df.loc[po_idx]
        ship = cap_df[cap_df["Shipment ID"] == ship_id].iloc[0]

        late_days = max((ship["Arrival Date"] - po["Import ETA"]).days, 0)
        penalty = late_days * late_penalty_per_day * (priority_multiplier ** po["Priority Level"])
        objective_terms.append(penalty * var)

        print(f"Late Penalty for PO Line {po_idx} on {ship_id}: {penalty} * {var}")

    for ship_id in use_container:
        price = cap_df[cap_df["Shipment ID"] == ship_id].iloc[0]["Price (USD)"]
        objective_terms.append(price * use_container[ship_id])
        print(f"Container Cost for {ship_id}: {price} * {use_container[ship_id]}")

    for po_idx, unmet in unmet_vars.items():
        penalty = po_df.loc[po_idx, "Unmet Penalty"]
        objective_terms.append(unmet * penalty)

    model += pulp.lpSum(objective_terms)

    # Constraints: demand fulfillment
    for po_idx in po_df.index:
        model += (
            pulp.lpSum(var for (idx, sid), var in assign.items() if idx == po_idx) + unmet_vars[po_idx]
            == po_df.loc[po_idx, "To Be Shipped Quantity"],
            f"Demand_PO_{po_idx}"
        )

    # Capacity constraints per container
    for ship_id in cap_df["Shipment ID"]:
        ship = cap_df[cap_df["Shipment ID"] == ship_id].iloc[0]
        max_vol = ship["Max Volume (m³)"]
        max_wt = ship["Max Weight (kg)"]

        volume_used = pulp.lpSum(
            assign.get((po_idx, ship_id), 0) * po_df.loc[po_idx, "Volume (m3)"]
            for po_idx in po_df.index
        )
        weight_used = pulp.lpSum(
            assign.get((po_idx, ship_id), 0) * po_df.loc[po_idx, "Weight (kg)"]
            for po_idx in po_df.index
        )

        model += volume_used <= max_vol * use_container[ship_id], f"VolCap_{ship_id}"
        model += weight_used <= max_wt * use_container[ship_id], f"WtCap_{ship_id}"

    # Solve
    model.solve()

    # Result output
    results = []
    used_shipment_ids = set()

    for (po_idx, ship_id), var in assign.items():
        if var.varValue and var.varValue > 0:
            po = po_df.loc[po_idx]
            ship = cap_df[cap_df["Shipment ID"] == ship_id].iloc[0]

            used_flag = 0
            if ship_id not in used_shipment_ids:
                used_flag = 1
                used_shipment_ids.add(ship_id)

            results.append({
                "PO Number": po["PO Number"],
                "PO Line Number": po["PO Line Number"],
                "SKU": po["SKU"],
                "Product Name": po["Product Name"],
                "Product Family": po["Product Family"],
                "IsElectronic": po["IsElectronic"],
                "From Port": po["From Port"],
                "To Port": po["To Port"],
                "Export ETA": po["Export ETA"],
                "Import ETA": po["Import ETA"],
                "Volume (m3)": po["Volume (m3)"],
                "Weight (kg)": po["Weight (kg)"],
                "COGS": po["COGS"],
                "Priority Level": po["Priority Level"],
                "Unmet Penalty Rate": po["Unmet Penalty"],
                "Shipment ID": ship_id,
                "Base Shipment ID": ship["Base Shipment ID"],
                "Carrier": ship["Carrier"],
                "Container Type": ship["Container Type"],
                "Max Volume (m³)": ship["Max Volume (m³)"],
                "Max Weight (kg)": ship["Max Weight (kg)"],
                "Price (USD)": ship["Price (USD)"],
                "Departure Date": ship["Departure Date"],
                "Arrival Date": ship["Arrival Date"],
                "Qty Assigned": int(var.varValue),
                "COGS Value Assigned" : int(var.varValue) * po["COGS"],
                "Late Days": max((ship["Arrival Date"] - po["Import ETA"]).days, 0),
                "Late Penalty": max((ship["Arrival Date"] - po["Import ETA"]).days, 0) * late_penalty_per_day * (priority_multiplier ** po["Priority Level"]) * int(var.varValue),
                "Used Container": used_flag,
                "Unmet Qty": 0,
                "COGS Value Unmet": 0,
                "Unmet Penalty": 0,
            })

    for po_idx, unmet in unmet_vars.items():
        if unmet.varValue and unmet.varValue > 0:
            po = po_df.loc[po_idx]
            results.append({
                "PO Number": po["PO Number"],
                "PO Line Number": po["PO Line Number"],
                "SKU": po["SKU"],
                "Product Name": po["Product Name"],
                "Product Family": po["Product Family"],
                "IsElectronic": po["IsElectronic"],
                "From Port": po["From Port"],
                "To Port": po["To Port"],
                "Export ETA": po["Export ETA"],
                "Import ETA": po["Import ETA"],
                "Volume (m3)": po["Volume (m3)"],
                "Weight (kg)": po["Weight (kg)"],
                "COGS": po["COGS"],
                "Priority Level": po["Priority Level"],
                "Unmet Penalty Rate": po["Unmet Penalty"],
                "Shipment ID": None,
                "Base Shipment ID": None,
                "Carrier": None,
                "Container Type": None,
                "Max Volume (m³)": None,
                "Max Weight (kg)": None,
                "Price (USD)": None,
                "Departure Date": None,
                "Arrival Date": None,
                "Qty Assigned": 0,
                "COGS Value Assigned" : 0,
                "Late Days": None,
                "Late Penalty": None,
                "Used Container": 0,
                "Unmet Qty": int(unmet.varValue),
                "COGS Value Unmet": int(unmet.varValue) * po["COGS"],
                "Unmet Penalty": int(unmet.varValue * po["Unmet Penalty"]),
            })

    return pd.DataFrame(results)


if __name__ == "__main__":
    from src.preprocessing import preprocess_data
    from src.optimizer import optimize_shipping

    po_df, cap_df = preprocess_data("data/sample_purchase_order_v1.csv", "data/sample_container_capacity_v1.csv")
    results_df = optimize_shipping(po_df, cap_df)
    print(results_df)
