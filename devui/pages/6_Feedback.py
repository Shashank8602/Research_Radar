import streamlit as st

from dev_db import query

st.title("Feedback")
st.caption("Votes from the email buttons: More like this (up), Less like this (down), Save for later (save).")

counts = query("select action, count(*) as n from feedback group by action order by action")
c1, c2, c3 = st.columns(3)
lookup = dict(zip(counts["action"], counts["n"], strict=False)) if not counts.empty else {}
c1.metric("More like this", int(lookup.get("up", 0)))
c2.metric("Less like this", int(lookup.get("down", 0)))
c3.metric("Saved", int(lookup.get("save", 0)))

votes = query(
    "select f.created_at, f.action, f.section, coalesce(nullif(s.headline, ''), i.title) as item, i.source "
    "from feedback f join items i on i.id = f.item_id "
    "left join item_scores s on s.item_id = f.item_id and s.run_id = f.run_id "
    "order by f.created_at desc limit 200"
)
if votes.empty:
    st.info("No votes yet. Use the buttons under each item in the email.")
else:
    st.dataframe(votes, width="stretch", hide_index=True)

st.subheader("Link usage")
tokens = query(
    "select count(*) as issued, count(used_at) as used, "
    "count(*) filter (where used_at is null and expires_at < now()) as expired "
    "from feedback_tokens"
)
st.dataframe(tokens, width="stretch", hide_index=True)
st.caption("Each email item gets 3 single-use links; most will never be clicked, which is expected.")
