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
