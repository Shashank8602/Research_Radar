"""Cached, read-only data for the dashboard pages. Every query runs on a read-only connection."""

import pandas as pd
import streamlit as st

from radar import db, stats
from radar.config import load_config
from radar.evals import cli

TTL = 300  # seconds; the data changes once a day


def _frame(weekly: dict, order: list[str] | None = None) -> pd.DataFrame:
    df = pd.DataFrame.from_dict(weekly, orient="index").fillna(0).astype(int).sort_index()
    return df[[c for c in (order or list(df.columns)) if c in df.columns]] if not df.empty else df


@st.cache_data(ttl=TTL)
def overview() -> dict:
    with db.connect(read_only=True) as conn:
        return stats.overview(conn)


@st.cache_data(ttl=TTL)
def runs() -> pd.DataFrame:
    with db.connect(read_only=True) as conn:
        return pd.DataFrame(stats.recent_runs(conn))


@st.cache_data(ttl=TTL)
def source_mix() -> tuple[pd.DataFrame, pd.DataFrame]:
    with db.connect(read_only=True) as conn:
        return _frame(stats.collected_by_source(conn)), _frame(stats.digested_by_source(conn))


@st.cache_data(ttl=TTL)
def votes() -> tuple[pd.DataFrame, pd.Series, dict]:
    with db.connect(read_only=True) as conn:
        rows, sections = stats.vote_rows(conn), stats.section_vote_rows(conn)
    weekly = _frame(stats.pivot_weekly(rows, "action"), list(stats.VOTE_ACTIONS))
    rate = pd.Series(stats.weekly_up_rate(rows), name="up-rate").dropna()
    return weekly, rate, stats.section_up_rates(sections)


@st.cache_data(ttl=3600, show_spinner="Replaying the evals...")
def eval_report() -> tuple[cli.EvalResult, str]:
    config = load_config()
    with db.connect(read_only=True) as conn:
        result = cli.compute(conn, config)
    cli.apply_gate(result, config)
    return result, cli.render(result, config)
