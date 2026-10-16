"""Label items for the golden set. One click per item; labels feed the Phase 2 evals."""

import streamlit as st

from dev_db import execute, query

st.title("Label items")
st.markdown(
    "For each item, ask: **would I want this in my daily email?**  \n"
    "Click **Relevant** or **Not relevant**. That is all. Use **Skip** if you can't tell."
)

stats = query("select relevant, count(*) as n from golden_labels group by relevant")
yes = int(stats.loc[stats["relevant"], "n"].sum()) if not stats.empty else 0
no = int(stats.loc[~stats["relevant"], "n"].sum()) if not stats.empty else 0
c1, c2, c3 = st.columns(3)
c1.metric("Labeled", yes + no)
c2.metric("Relevant", yes)
c3.metric("Not relevant", no)
st.progress(min(1.0, (yes + no) / 250), text="Goal: about 250 labels")

if "skipped" not in st.session_state:
    st.session_state.skipped = set()


@st.cache_data(ttl=5)
def next_item(skipped: tuple[str, ...]):
    # Alternate between items that made the digest and items that did not (hard negatives).
    for in_digest in (True, False):
        df = query(
            "select distinct on (i.id) i.id, i.canonical_url, i.title, i.source, s.headline, s.summary, "
            "s.best_topic, (d.item_id is not null) as in_digest "
            "from item_scores s join items i on i.id = s.item_id "
            "left join digests d on d.item_id = s.item_id and d.run_id = s.run_id "
            "where s.judge_model is not null "
            "and not exists (select 1 from golden_labels g where g.item_id = i.id) "
            "and i.id::text <> all(%s) "
            "and (d.item_id is not null) = %s "
            "order by i.id, random() limit 50",
            (list(skipped) or [""], in_digest),
        )
        if not df.empty:
            return df.sample(1).iloc[0]
    return None


# Alternate pools so about half the labels are non-digest items.
item = next_item(tuple(st.session_state.skipped))
if item is None:
    st.success("Nothing left to label. Run the pipeline to collect more candidates.")
    st.stop()

with st.container(border=True):
    st.caption(f"{item['source']} · {item['best_topic']} · {'was in the digest' if item['in_digest'] else 'not in the digest'}")
    st.subheader(item["headline"] or item["title"])
    st.write(item["summary"])
    st.caption(f"Original title: {item['title']}")
    st.link_button("Open original", item["canonical_url"])

b1, b2, b3 = st.columns(3)
if b1.button("✅ Relevant", width="stretch", type="primary"):
    execute(
        "insert into golden_labels (item_id, relevant) values (%s, true) "
        "on conflict (item_id) do update set relevant = true, labeled_at = now()",
        (str(item["id"]),),
    )
    st.rerun()
if b2.button("❌ Not relevant", width="stretch"):
    execute(
        "insert into golden_labels (item_id, relevant) values (%s, false) "
        "on conflict (item_id) do update set relevant = false, labeled_at = now()",
        (str(item["id"]),),
    )
    st.rerun()
if b3.button("⏭ Skip", width="stretch"):
    st.session_state.skipped.add(str(item["id"]))
    st.rerun()
