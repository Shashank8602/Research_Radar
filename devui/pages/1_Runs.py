import streamlit as st

from dev_db import query

st.title("Runs")

try:
    df = query(
        "select started_at, digest_date, is_dry_run, status, n_collected, n_filtered, n_sent, "
        "cost_usd, notes, id from runs order by started_at desc limit 50"
    )
except Exception as e:
    st.error(f"Could not read runs: {e}")
    st.stop()

if df.empty:
    st.info("No runs yet. Run `uv run radar-smoke`.")
else:
    st.dataframe(df, width="stretch", hide_index=True)
