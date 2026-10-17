"""Research Radar dashboard: is the digest running, what does it contain, do the votes agree?

Run locally: python -m uv run streamlit run dashboard/app.py
Pages in the sidebar: Feedback, Quality, and Labeling (local only). Read-only: nothing here writes
except the Labeling page, which is hidden when APP_ENV=production.
"""

import streamlit as st

import queries

st.set_page_config(page_title="Research Radar", layout="wide")
st.title("Research Radar")
st.caption("A daily AI-research digest, built and watched in the open. Aggregates only; no private notes.")

try:
    o = queries.overview()
except Exception as e:  # missing credentials, database paused, ...
    st.error(f"Could not read the database: {e}")
    st.stop()

last = o["last_run"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("Digests sent", o["digests_sent"])
c2.metric("Items collected", f"{o['items_collected']:,}")
c3.metric("Votes", sum(o["votes"][a] for a in ("up", "down", "save")))
c4.metric("Labels (golden set)", o["labels"])
if last:
    st.caption(
        f"Latest real digest: {last['digest_date']}, {last['status']}, {last['n_sent']} items from "
        f"{last['n_collected']} collected."
    )

st.subheader("Where the items come from")
collected, digested = queries.source_mix()
left, right = st.columns(2)
with left:
    st.caption("Collected per week")
    if collected.empty:
        st.info("Nothing collected yet.")
    else:
        st.bar_chart(collected)
with right:
    st.caption("Reached a digest, per week")
    if digested.empty:
        st.info("No real digests yet.")
    else:
        st.bar_chart(digested)

st.subheader("Recent digests")
runs = queries.runs()
if runs.empty:
    st.info("No real digests yet.")
else:
    st.dataframe(runs, width="stretch", hide_index=True)
