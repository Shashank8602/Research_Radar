"""Read-only DB helper for the dev console."""

import pandas as pd
import psycopg

from radar.config import get_env


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    env = get_env()
    env.require("database_url")
    with psycopg.connect(env.database_url) as conn:
        conn.read_only = True
        cur = conn.execute(sql, params)
        cols = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def execute(sql: str, params: tuple = ()) -> None:
    """Write helper. ONLY the Labeling page uses this, and only for the golden_labels table."""
    env = get_env()
    env.require("database_url")
    assert "golden_labels" in sql, "dev console may only write golden labels"
    with psycopg.connect(env.database_url) as conn:
        conn.execute(sql, params)
        conn.commit()
