import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import pandas as pd
import plotly.express as px
from src.preprocessing import preprocess_data
from src.optimizer import optimize_shipping
from app.components import show_dashboard, show_definitions, show_download_templates

# Navigation
page = st.sidebar.selectbox("Navigation", ["Dashboard", "Definitions & Assumptions", "Download CSV Templates"])


if page == "Dashboard":
    show_dashboard()
elif page == "Definitions & Assumptions":
    show_definitions()
elif page == "Download CSV Templates":
    show_download_templates()