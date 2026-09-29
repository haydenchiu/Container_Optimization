import streamlit as st

st.set_page_config(
    page_title="Container Optimization Dashboard", layout="wide", initial_sidebar_state="expanded"
)

from components import show_dashboard, show_definitions, show_download_templates  # noqa: E402

page = st.sidebar.selectbox(
    "Navigation", ["Dashboard", "Definitions & Assumptions", "Sample Data & Templates"]
)

if page == "Dashboard":
    show_dashboard()
elif page == "Definitions & Assumptions":
    show_definitions()
elif page == "Sample Data & Templates":
    show_download_templates()
