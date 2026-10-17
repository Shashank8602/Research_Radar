import streamlit as st

import queries

st.title("Feedback")
st.caption(
    "Votes from the buttons in the email: More like this (up), Less like this (down), Save for later, "
    "and Explain in depth (deep-dive opens)."
)

weekly, rate, sections = queries.votes()
o = queries.overview()
labels = [("More like this", "up"), ("Less like this", "down"), ("Saved", "save"), ("Deep dives", "deepdive")]
for col, (label, key) in zip(st.columns(4), labels, strict=True):
    col.metric(label, o["votes"][key])

st.subheader("Share of votes that were 'more like this'")
if rate.empty:
    st.info("No up/down votes yet. Click the buttons under each item in the email.")
else:
    st.line_chart(rate)
    st.caption("Each item counts once (the latest up or down wins). Small weeks are noisy.")

st.subheader("By section")
if sections:
    for name, s in sections.items():
        pct = "-" if s["rate"] is None else f"{s['rate']:.0%}"
        st.write(f"**{name}**: {s['up']} up, {s['down']} down ({pct} up)")
    st.caption("Top picks sit first in the email, so position can inflate their rate.")
else:
    st.info("No section data yet.")

st.subheader("Votes per week")
if weekly.empty:
    st.info("No votes yet.")
else:
    st.bar_chart(weekly)
