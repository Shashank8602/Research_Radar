"""Deep dive chat (Streamlit). Opens from a signed link in the digest email: ?t=<token>.

Run locally: python -m uv run streamlit run agent/app.py
Local-only shortcut (disabled when APP_ENV=production): ?item=<item uuid>, or pick from the sidebar.
Logic lives in src/radar/agent/; this file is only the page.
"""

import time

import streamlit as st

from radar import db, feedback, tracing
from radar.agent import store
from radar.agent.graph import ask, build_graph, history_from_chat
from radar.config import get_env

MAX_QUESTIONS_PER_ITEM = 20
MIN_SECONDS_BETWEEN = 3.0

st.set_page_config(page_title="Research Radar: deep dive", page_icon="🔎", layout="centered")


@st.cache_resource
def _counters() -> dict:
    """Per-process rate limits, keyed by item. A Space restart resets them, which is acceptable."""
    return {}


def _resolve_item() -> tuple[str | None, str | None]:
    """Return (item_id, run_id) from the signed link, or from ?item= in development."""
    env = get_env()
    params = st.query_params
    if token := params.get("t"):
        env.require("feedback_signing_secret")
        claims = feedback.verify(token, env.feedback_signing_secret)
        if claims and claims.get("a") == "deepdive":
            return claims["i"], claims.get("r")
        st.error("This link is invalid or has expired. Use the link from a newer digest.")
        return None, None
    if env.app_env != "production":
        if item := params.get("item"):
            return item, None
        with db.connect() as conn:
            rows = store.recent_items(conn)
        if rows:
            choice = st.sidebar.selectbox(
                "Dev: pick an item", rows, format_func=lambda r: f"{r['digest_date']} · {r['title'][:60]}"
            )
            return str(choice["id"]), None
    st.info("Open the Deep dive link from your digest email.")
    return None, None


@st.cache_resource
def _graph():
    def load(item_id: str):
        with db.connect() as conn:
            return store.load_item(conn, item_id)

    return build_graph(load)


def _show_citations(citations: list[dict]) -> None:
    for c in citations:
        label = f"[{c['n']}]" + (f" page {c['page']}" if c.get("page") else "")
        with st.expander(f"Source {label}"):
            st.write(c["quote"])


def _turn(item_id: str, question: str | None, chat: list[dict] | None = None) -> dict | None:
    limits = _counters().setdefault(item_id, {"n": 0, "last": 0.0})
    now = time.monotonic()
    if limits["n"] >= MAX_QUESTIONS_PER_ITEM:
        st.warning("That's the limit of questions for this item. Come back with the next digest.")
        return None
    if now - limits["last"] < MIN_SECONDS_BETWEEN:
        st.warning("One moment, please wait a few seconds between questions.")
        return None
    limits["n"] += 1
    limits["last"] = now
    try:
        with tracing.deepdive_trace(item_id, question) as span:
            out = ask(_graph(), item_id, question, history=history_from_chat(chat or []))
            span.update(output={"answer_chars": len(out["answer"]),
                                "cited": [c["n"] for c in out["citations"]]})
            return out
    except Exception:
        st.error("Something went wrong while answering. Please try again in a minute.")
        return None
    finally:
        tracing.flush()


def _save(item_id: str, chat: list[dict]) -> None:
    """Best effort: a failed save must never break the conversation."""
    try:
        with db.connect() as conn:
            store.save_chat(conn, item_id, chat)
    except Exception:
        pass


def main() -> None:
    item_id, run_id = _resolve_item()
    if not item_id:
        return
    try:
        with db.connect() as conn:
            item = store.load_item(conn, item_id)
            item_id = item.id  # the cleaned, validated id
            if st.session_state.get("logged") != item_id:
                store.log_deepdive(conn, item_id, run_id)
                st.session_state["logged"] = item_id
    except LookupError:
        st.error("That item could not be found.")
        return

    st.title("🔎 Deep dive")
    st.subheader(item.title)
    st.caption(f"[Open the original]({item.url})")

    if f"chat:{item_id}" not in st.session_state:  # new browser session: pick up the saved chat
        try:
            with db.connect() as conn:
                st.session_state[f"chat:{item_id}"] = store.load_chat(conn, item_id)
        except Exception:
            st.session_state[f"chat:{item_id}"] = []
    chat = st.session_state[f"chat:{item_id}"]
    if not chat:
        with st.spinner("Reading the paper... this can take about half a minute."):
            out = _turn(item_id, None)
        if out:
            chat.append({"role": "assistant", "text": out["answer"], "citations": out["citations"],
                         "notice": out.get("notice", "")})
            _save(item_id, chat)

    for msg in chat:
        with st.chat_message(msg["role"]):
            if msg.get("notice"):
                st.warning(msg["notice"])
            st.write(msg["text"])
            _show_citations(msg.get("citations", []))

    if question := st.chat_input("Ask a follow-up about this item"):
        earlier = list(chat)
        chat.append({"role": "user", "text": question})
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"), st.spinner("Thinking..."):
            out = _turn(item_id, question, earlier)
            if out:
                st.write(out["answer"])
                _show_citations(out["citations"])
                chat.append({"role": "assistant", "text": out["answer"],
                             "citations": out["citations"]})
                _save(item_id, chat)


main()
