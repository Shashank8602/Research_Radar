import streamlit as st

from dev_db import query

st.title("Filter + judge scores")
runs = query("select id, started_at, digest_date, is_dry_run, status from runs order by started_at desc limit 30")
if runs.empty:
    st.info("No runs yet.")
    st.stop()
labels = {
    r.id: f"{r.started_at:%Y-%m-%d %H:%M} · {r.status}{' (dry)' if r.is_dry_run else ''}"
    for r in runs.itertuples()
}
run_id = st.selectbox("Run", list(labels), format_func=labels.get)
df = query(
    "select s.final_rank, s.filter_score, s.relevance, s.novelty, s.actionability, s.best_topic, "
    "i.source, i.title, s.rationale, s.filter_parts, d.section "
    "from item_scores s join items i on i.id = s.item_id "
    "left join digests d on d.run_id = s.run_id and d.item_id = s.item_id "
    "where s.run_id = %s order by s.final_rank desc",
    (run_id,),
)
st.caption(f"{len(df)} candidates reached the judge; rows with a section made it into the digest.")
st.dataframe(df, width="stretch", hide_index=True)
if not df.empty:
    st.subheader("Judged relevance distribution")
    st.bar_chart(df["relevance"].value_counts().sort_index())
