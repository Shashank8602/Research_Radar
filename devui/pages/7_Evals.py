"""Shows the same report as `uv run radar-eval` (offline parts only: no LLM calls)."""

from dataclasses import asdict

import pandas as pd
import streamlit as st

from radar import db
from radar.config import load_config
from radar.evals import cli

st.title("Evals")
st.caption("Replays stored scores against your labels. For the LLM faithfulness check, "
           "run `uv run radar-eval --faithfulness 10` in a terminal.")

config = load_config()
with st.spinner("Computing…"), db.connect() as conn:
    r = cli.compute(conn, config)
cli.apply_gate(r, config)

n_labels = len(cli.unique_items(r.examples))
c1, c2, c3 = st.columns(3)
c1.metric("Labels", n_labels, help=f"Ranking gate needs {config.evals.min_labels_for_gate}")
c2.metric("Votes", r.votes)
c3.metric("Jargon rate", "–" if r.plain.jargon_rate is None else f"{r.plain.jargon_rate:.0%}",
          help=f"Limit {config.evals.max_jargon_rate:.0%}")

st.subheader("Ranking ablation")
if r.ablation:
    st.dataframe(pd.DataFrame([asdict(a) for a in r.ablation]), width="stretch", hide_index=True)
else:
    st.info("No labels yet. Use the Labeling page.")

st.subheader("LLM judge vs your labels")
if r.calibration and r.calibration[0].n:
    st.caption(f"ROC-AUC of the judge's relevance score: {r.judge_auc:.2f}" if r.judge_auc else "")
    st.dataframe(pd.DataFrame([asdict(c) for c in r.calibration]), width="stretch", hide_index=True)
else:
    st.info("Needs labels.")

st.subheader("Plain language")
p = r.plain
if p.n_items:
    st.write(f"{p.n_items} recent digest items. Unexplained jargon in {p.jargon_rate:.0%}; "
             f"examples starting with 'Imagine': {p.example_ok_rate:.0%}; "
             f"headlines within the word limit: {p.headline_ok_rate:.0%}.")
    if p.top_terms:
        st.bar_chart(pd.DataFrame(p.top_terms, columns=["term", "items"]).set_index("term"))

st.subheader("Gate")
if r.gate_skipped_reason:
    st.caption(r.gate_skipped_reason)
for msg in r.gate_failures:
    st.error(msg)
if not r.gate_failures:
    st.success("All checked thresholds pass.")

with st.expander("Full markdown report"):
    st.markdown(cli.render(r, config))
