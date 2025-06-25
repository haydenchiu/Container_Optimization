# 📦 Container Shipping Optimizer

A web-based dashboard for optimizing purchase order fulfillment using available container capacities. Upload your data, configure penalties, and visualize optimization results with interactive dashboards.

---

## 🚀 Features

- 📁 Upload PO and container capacity CSVs
- ⚙️ Configure late delivery and priority penalties
- 🧠 Run container optimization engine
- 📊 View KPI metrics: cost, unmet quantity, container usage
- 📅 Filter results by PO number and export time (year/week/month)
- 📈 Interactive visualizations (histograms, pie charts, bar charts)
- 📥 Download aggregated or full results as CSV

---

## 🛠️ Project Structure

├── app/
│ ├── main.py # UI entry point
│ └──components.py #UI and logics
├── src/
│ ├── preprocessing.py # File input preprocessing
│ └── optimizer.py # Optimization algorithm
├── requirements.txt
└── README.md

---

## 📄 Sample Input Files

| File                 | Description                                                |
|----------------------|------------------------------------------------------------|
| `purchase_orders.csv` | Contains PO number, line item, SKU, required qty, priority |
| `container_capacity.csv` | Shipment ID, capacity, port details, cost, dates         |

---

## 🧪 Local Setup

### 1. Clone and Create Environment

```bash
git clone https://github.com/haydenchiu/Container_Optimization.git
cd Container_Optimization

# (Recommended) Use virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -r requirements.txt # Install Dependencies

PYTHONPATH=. streamlit run app/main.py # Run the Dashboard
