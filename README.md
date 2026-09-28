# Container Shipping Optimizer

A web-based dashboard for optimizing purchase order fulfillment using available container capacities. Upload your data, configure penalties, and visualize optimization results with interactive dashboards.

**Live demo:** [containeroptimization-fjucc2hy794xnc9t7cbgyo.streamlit.app](https://containeroptimization-fjucc2hy794xnc9t7cbgyo.streamlit.app/)

---

## Try It Live

No installation needed. The app is hosted on Streamlit Community Cloud.

1. Download the two sample files:
   [sample_purchase_order_v1.csv](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/sample_purchase_order_v1.csv) and
   [sample_container_capacity_v1.csv](https://raw.githubusercontent.com/haydenchiu/Container_Optimization/main/data/samples/sample_container_capacity_v1.csv)
   (right-click, "Save link as...").
2. Open the [live demo](https://containeroptimization-fjucc2hy794xnc9t7cbgyo.streamlit.app/).
3. Upload the purchase order file and the container capacity file.
4. Optionally adjust the penalty settings in the sidebar, then click **Run Optimization**.
5. Explore the KPIs, charts and tables, and use the sidebar filters to slice the results.

If the app has been idle it may show a "This app has gone to sleep" page; click the wake-up button and wait about a minute.
To use your own data, download blank templates from the **Download CSV Templates** page in the sidebar navigation.

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
├── data/samples/                    # Sample input files
├── test/                            # pytest suite
├── pyproject.toml                   # Project metadata and dependencies (uv)
└── uv.lock
```

---

## Sample Input Files

| File | Description |
|------|-------------|
| `data/samples/sample_purchase_order_v1.csv` | PO number, line item, SKU, quantity, dimensions, ETAs, priority, unmet penalty |
| `data/samples/sample_container_capacity_v1.csv` | ISO departure week, lane, carrier, container type, units, capacity, transit time, price |

Templates for both files can be downloaded from the dashboard's "Download CSV Templates" page.

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
