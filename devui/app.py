"""TEMPORARY dev console. Delete this folder in Phase 4 (see plan.md, "Dev console").

Run: uv sync --group devui && uv run streamlit run devui/app.py
Rules: read-only, local only, no business logic, nothing in src/ imports this.
"""

import streamlit as st

st.set_page_config(page_title="Radar dev console", layout="wide")
st.title("Research Radar: dev console")
st.caption("Temporary stage-by-stage viewer. Pages appear in the sidebar as stages are built.")
st.info("Open **Runs** in the sidebar to see recent pipeline runs.")
