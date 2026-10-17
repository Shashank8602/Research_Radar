"""Label items for the golden set (local only). One click per item; the labels feed the evals."""

import streamlit as st

from radar import db
from radar.config import get_env
from radar.evals import labeling

st.title("Label items")
if get_env().app_env == "production":
    st.error("Labeling writes to the database, so it is off in production. Run the dashboard locally.")
    st.stop()

st.markdown(
    "For each item ask: **would I want this in my daily email?** Click **Relevant** or "
    "**Not relevant**. Use **Skip** if you can't tell."
)
skipped = st.session_state.setdefault("skipped", [])

with db.connect() as conn:
    p = labeling.progress(conn)
    item = labeling.next_item(conn, skipped)

c1, c2, c3 = st.columns(3)
c1.metric("Labeled", p["total"])
c2.metric("Relevant", p["relevant"])
c3.metric("Not relevant", p["not_relevant"])
st.progress(min(1.0, p["total"] / p["goal"]), text=f"Goal: about {p['goal']} labels")

if item is None:
    st.success("Nothing left to label. Run the pipeline to collect more candidates.")
    st.stop()

with st.container(border=True):
    where = "was in the digest" if item["in_digest"] else "not in the digest"
    st.caption(f"{item['source']} · {item['best_topic']} · {where}")
    st.subheader(item["headline"] or item["title"])
    st.write(item["summary"])
    st.caption(f"Original title: {item['title']}")
    st.link_button("Open original", item["canonical_url"])

b1, b2, b3 = st.columns(3)
for col, text, relevant in ((b1, "Relevant", True), (b2, "Not relevant", False)):
    if col.button(text, width="stretch", type="primary" if relevant else "secondary"):
        with db.connect() as conn:
            labeling.save_label(conn, str(item["id"]), relevant)
        st.rerun()
if b3.button("Skip", width="stretch"):
    skipped.append(str(item["id"]))
    st.rerun()
