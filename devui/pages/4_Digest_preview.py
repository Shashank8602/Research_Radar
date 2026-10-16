import streamlit as st

from dev_db import query
from radar import compose
from radar.config import load_config
from radar.models import Candidate

st.title("Digest preview")
runs = query("select id, started_at, digest_date, status from runs where n_sent > 0 order by started_at desc limit 30")
if runs.empty:
    st.info("No digests yet.")
    st.stop()
labels = {r.id: f"{r.started_at:%Y-%m-%d %H:%M} · {r.status}" for r in runs.itertuples()}
run_id = st.selectbox("Run", list(labels), format_func=labels.get)
rows = query(
    "select i.id, i.canonical_url, i.title, i.source, s.best_topic, s.relevance, s.novelty, s.actionability, "
    "s.summary, s.why_it_matters, s.headline, s.example, s.final_rank, d.section, d.position, (s.judge_model is not null) as judged "
    "from digests d join items i on i.id = d.item_id "
    "join item_scores s on s.run_id = d.run_id and s.item_id = d.item_id where d.run_id = %s",
    (run_id,),
)
items = [
    Candidate(
        id=str(r.id), url=r.canonical_url, title=r.title, source=r.source, best_topic=r.best_topic or "",
        relevance=r.relevance, novelty=r.novelty, actionability=r.actionability,
        summary=r.summary or "", why_it_matters=r.why_it_matters or "", headline=r.headline or "",
        example=r.example or "", final_rank=r.final_rank,
        section=r.section, position=int(r.position), judged=bool(r.judged),
    )
    for r in rows.itertuples()
]
run = runs[runs["id"] == run_id].iloc[0]
html, _ = compose.render(
    compose.build_context(
        items, digest_date=run["digest_date"], run_id=str(run_id), degraded=False,
        topic_labels={t.name: t.label or t.name for t in load_config().topics},
    )
)
# Safe enough for a local tool: the template autoescapes every title/summary field.
st.iframe(html, height=900)
