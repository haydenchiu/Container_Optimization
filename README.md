# Container Shipping Optimizer

A web-based dashboard for optimizing purchase order fulfillment using available container capacities. Upload your data, configure penalties, and visualize optimization results with interactive dashboards.

**Live demo:** [containeroptimization-fjucc2hy794xnc9t7cbgyo.streamlit.app](https://containeroptimization-fjucc2hy794xnc9t7cbgyo.streamlit.app/)

---

## Try It Live

No installation needed. The app is hosted on Streamlit Community Cloud.

1. Open the [live demo](https://containeroptimization-fjucc2hy794xnc9t7cbgyo.streamlit.app/).
2. Pick **Sample Data & Templates** in the sidebar navigation and download both files of a scenario (see [Sample Scenarios](#sample-scenarios) below).
3. Switch back to **Dashboard** and upload the purchase order file and the container capacity file.
4. Optionally adjust the penalty settings in the sidebar, then click **Run Optimization**.
5. Explore the KPIs, charts and tables, and use the sidebar filters to slice the results.

If the app has been idle it may show a "This app has gone to sleep" page; click the wake-up button and wait about a minute.
To use your own data, download blank templates from the same **Sample Data & Templates** page.

---

## Features

- Upload PO and container capacity CSVs
- Configure late fees, daily late rates, grace days, priority weighting and early-arrival holding costs
- Run container optimization engine (MILP solved with CBC via PuLP)
- View KPI metrics: cost, unmet quantity, container usage
- Filter results by PO number and export time (year/week/month)
- Interactive visualizations (histograms, pie charts, bar charts)
- Download aggregated or full results as CSV

---

## Project Structure

```
├── app/
│   ├── main.py                      # Streamlit entry point
│   └── components.py                # Dashboard pages
├── src/container_optimization/
│   ├── preprocessing.py             # CSV loading, validation, container expansion
│   └── optimizer.py                 # Optimization model
├── data/samples/                    # Sample input files (baseline + scenarios)
├── scripts/generate_scenarios.py    # Regenerates the scenario sample files
├── test/                            # pytest suite
├── pyproject.toml                   # Project metadata and dependencies (uv)
└── uv.lock
```

---

## Sample Scenarios

Each scenario is a purchase order file plus a container capacity file, built to demonstrate one behavior. They can be downloaded from the app's **Sample Data & Templates** page or from the links below (right-click, "Save link as..."). Results quoted are for the default sidebar settings.

| Scenario | Files | What it shows |
|----------|-------|---------------|
| Baseline: mixed network | [PO](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/sample_purchase_order_v1.csv), [capacity](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/sample_container_capacity_v1.csv) | 70 PO lines on 9 lanes with weekly sailings; a general-purpose run. |
| 1. Irregular shipping schedule | [PO](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario1_irregular_schedule_purchase_order.csv), [capacity](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario1_irregular_schedule_container_capacity.csv) | Blank sailing, a congested sailing, biweekly and every-three-weeks services, swinging transit times and a suspended lane. The optimizer pays for a premium express to avoid the congested sailing, SH to LA lines wait for the next sailing and arrive up to 10 days late, and the suspended lane is unmet with a warning. |
| 2. Demand surge | [PO](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario2_demand_surge_purchase_order.csv), [capacity](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario2_demand_surge_container_capacity.csv) | A one-week product launch at more than twice the weekly capacity. The backlog rolls into later sailings: high-priority lines are at most 3 days late, low-priority volume waits up to 10 days. |
| 3. Capacity shortage and priority triage | [PO](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario3_capacity_shortage_purchase_order.csv), [capacity](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario3_capacity_shortage_container_capacity.csv) | Capacity covers about 60% of demand. Low-value office supplies are dropped, and the marketplace (priority 0) projectors are dropped while the key account's (priority 2) identical projectors ship. Set Priority multiplier to 1 and the choice flips to value per m³ alone. |
| 4. Consolidation vs. speed | [PO](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario4_consolidation_purchase_order.csv), [capacity](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/scenario4_consolidation_container_capacity.csv) | Many small POs and plenty of capacity. Cheap goods wait a week to share containers (8 containers, 12 late lines); raise Daily late rate to 5% and the plan opens 10 containers with only 2 late lines. |

The scenario files are generated by `scripts/generate_scenarios.py` (deterministic): `uv run python scripts/generate_scenarios.py`.

---

## Optimization Model

Each container in the capacity file is expanded into `Available Units` individual containers. A PO line can use a container if it serves the same lane and departs on or after the line's Export ETA. Containers depart on the Monday of their ISO `Week_Year`.

The model minimizes container prices + late penalties + early holding costs + unmet penalties. For PO line $i$ on container $s$:

$$w_i = m^{p_i}$$

$$L_{is} = \max(0,\ \text{arrival}_s - \text{ImportETA}_i - g), \qquad E_{is} = \max(0,\ \text{ImportETA}_i - \text{arrival}_s)$$

$$\text{late}_{is} = w_i \cdot \text{COGS}_i \cdot \left(f \cdot \mathbb{1}[L_{is} > 0] + r \cdot L_{is}\right), \qquad \text{hold}_{is} = h \cdot \text{COGS}_i \cdot E_{is}$$

$$u_i = \max\left(w_i \cdot \text{UnmetPenalty}_i,\ 1.1 \cdot \max_s (\text{late}_{is} + \text{hold}_{is})\right)$$

| Symbol | Meaning | Default |
|--------|---------|---------|
| $m$ | Priority multiplier; higher Priority Level $p_i$ is more important | 2 |
| $f$ | One-off late fee, fraction of unit COGS | 5% |
| $r$ | Daily late rate, fraction of unit COGS per day | 0.5% |
| $g$ | Grace days after Import ETA | 0 |
| $h$ | Early-arrival holding rate, fraction of unit COGS per day | 0% |

Late and holding costs are charged per unit shipped, and $u_i$ per unit left unshipped. Priority scales both the late and the unmet penalty, and $u_i$ is floored above the worst late cost, so the optimizer never prefers dropping a unit over shipping it late.

Constraints: demand per PO line is either assigned or unmet, container volume and weight limits apply, and a container's price is paid when it carries anything.

---

## Running Locally

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which also installs a matching Python (3.12+) if you don't have one:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh      # macOS / Linux
  # Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

### Install and run

```bash
git clone https://github.com/haydenchiu/Container_Optimization.git
cd Container_Optimization

uv sync                                  # Create .venv and install locked dependencies
uv run streamlit run app/main.py         # Start the dashboard
```

Streamlit opens [http://localhost:8501](http://localhost:8501). Upload the files from `data/samples/` and click **Run Optimization**.

### Run in GitHub Codespaces

The repo includes a dev container. Open it in [GitHub Codespaces](https://codespaces.new/haydenchiu/Container_Optimization); dependencies install automatically and the dashboard starts on port 8501.

### Development

```bash
uv run pytest                            # Tests
uv run ruff check . && uv run ruff format .   # Lint and format
uv run python -m container_optimization.optimizer   # Solve the sample files from the CLI
uv add <package>                         # Add a dependency
```
