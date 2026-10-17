from dataclasses import asdict

import pandas as pd
import streamlit as st

import queries

st.title("Quality")
st.caption(
    "Replays stored scores against the golden labels and checks the writing. "
    "Same report as `radar-eval`; the LLM faithfulness check runs weekly in CI."
)

try:
    r, report = queries.eval_report()
except Exception as e:
    st.error(f"Could not compute the evals: {e}")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Golden labels", len({e.item_id for e in r.examples}))
c2.metric("Jargon in entries", "-" if r.plain.jargon_rate is None else f"{r.plain.jargon_rate:.0%}")
c3.metric("Reading grade", "-" if r.plain.reading_grade is None else f"{r.plain.reading_grade:.1f}")

st.subheader("Ranking: precision@5 by ranker")
if r.ablation:
    st.dataframe(pd.DataFrame([asdict(a) for a in r.ablation]), width="stretch", hide_index=True)
else:
    st.info("Needs labels. Use the Labeling page (run the dashboard locally).")

for msg in r.gate_failures:
    st.error(msg)
for msg in (r.text_gate_skipped_reason, r.gate_skipped_reason):
    if msg:
        st.caption(msg)
with st.expander("Full report"):
    st.markdown(report)
