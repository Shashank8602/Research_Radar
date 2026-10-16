import streamlit as st

from dev_db import query

st.title("Collected items")
days = st.slider("Created in the last N days", 1, 14, 2)
df = query(
    "select source, title, published_at, popularity, canonical_url, cluster_id is not null as is_duplicate, created_at "
    "from items where created_at > now() - make_interval(days => %s) order by created_at desc",
    (days,),
)
if df.empty:
    st.info("No items yet. Run `uv run radar-run --dry-run`.")
else:
    c1, c2, c3 = st.columns(3)
    c1.metric("Items", len(df))
    c2.metric("Near-duplicates", int(df["is_duplicate"].sum()))
    c3.metric("Sources", df["source"].nunique())
    st.bar_chart(df.groupby("source").size())
    src = st.multiselect("Source", sorted(df["source"].unique()), default=sorted(df["source"].unique()))
    st.dataframe(df[df["source"].isin(src)], width="stretch", hide_index=True)
