"""Dashboard data layer and pages: rates, labeling queries, the production guard. No database."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from radar import stats
from radar.evals import labeling

W1, W2 = date(2026, 10, 12), date(2026, 10, 19)


def test_up_rate_handles_no_votes():
    assert stats.up_rate(3, 1) == 0.75
    assert stats.up_rate(0, 0) is None
    assert stats.up_rate(0, 4) == 0.0


def test_pivot_and_weekly_up_rate_sort_by_week():
    rows = [
        {"week": W2, "action": "up", "n": 1}, {"week": W2, "action": "down", "n": 3},
        {"week": W1, "action": "up", "n": 4}, {"week": W1, "action": "save", "n": 2},
    ]
    assert list(stats.pivot_weekly(rows, "action")) == [W1, W2]
    assert stats.pivot_weekly(rows, "action")[W1] == {"up": 4, "save": 2}
    assert stats.weekly_up_rate(rows) == {W1: 1.0, W2: 0.25}


def test_section_up_rates_ignore_other_actions_and_null_sections():
    rows = [
        {"section": "core", "action": "up", "n": 3}, {"section": "core", "action": "down", "n": 1},
        {"section": None, "action": "up", "n": 2}, {"section": "core", "action": "save", "n": 9},
    ]
    out = stats.section_up_rates(rows)
    assert out["core"] == {"up": 3, "down": 1, "rate": 0.75}
    assert out["unknown"]["rate"] == 1.0


class FakeConn:
    """Records the SQL it is given and hands back canned rows."""

    def __init__(self, rows=()):
        self.rows, self.calls, self.committed = list(rows), [], False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return SimpleNamespace(fetchall=lambda: self.rows, fetchone=lambda: (self.rows or [None])[0])

    def commit(self):
        self.committed = True


def test_label_progress_counts_both_sides():
    conn = FakeConn([{"relevant": True, "n": 7}, {"relevant": False, "n": 5}])
    assert labeling.progress(conn) == {"relevant": 7, "not_relevant": 5, "total": 12, "goal": labeling.GOAL}


def test_next_item_prefers_digest_items_then_hard_negatives():
    conn = FakeConn([])
    assert labeling.next_item(conn, ["skip-me"]) is None
    assert [c[1][1] for c in conn.calls] == [True, False]  # digest items first, then the rest
    assert all(c[1][0] == ["skip-me"] for c in conn.calls)
    assert labeling.next_item(FakeConn([{"id": "a"}])) == {"id": "a"}


def test_save_label_upserts_and_commits():
    conn = FakeConn()
    labeling.save_label(conn, "item-1", False)
    sql, params = conn.calls[0]
    assert "on conflict (item_id) do update" in sql and params == ("item-1", False)
    assert conn.committed


def test_labeling_page_is_off_in_production(monkeypatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr("radar.config.get_env", lambda: SimpleNamespace(app_env="production"))
    page = Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "9_Labeling.py"
    at = AppTest.from_file(str(page), default_timeout=30).run()
    assert not at.exception
    assert any("off in production" in e.value for e in at.error)
    assert not at.button  # no way to write a label


def test_read_only_connection_prefers_the_dashboard_url_and_starts_read_only_transactions(monkeypatch):
    from radar import db

    seen = {}

    class Conn:
        read_only = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_connect(url, **kw):
        seen["url"], seen["conn"] = url, Conn()
        return seen["conn"]

    env = SimpleNamespace(database_url="postgres://owner", dashboard_database_url="postgres://readonly",
                          require=lambda *n: None)
    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    monkeypatch.setattr(db, "get_env", lambda: env)
    monkeypatch.setattr(db, "register_vector_types", lambda conn: None)
    with db.connect(read_only=True):
        pass
    # psycopg's flag sends BEGIN READ ONLY, which survives a connection pooler (a startup option does not).
    assert seen["url"] == "postgres://readonly" and seen["conn"].read_only is True
    with db.connect():
        pass
    assert seen["url"] == "postgres://owner" and seen["conn"].read_only is False  # writers use the owner URL


@pytest.mark.parametrize("page", ["app.py", "pages/1_Feedback.py", "pages/2_Quality.py"])
def test_public_pages_show_an_error_not_a_traceback_when_the_database_is_down(monkeypatch, page):
    import sys

    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1] / "dashboard"
    monkeypatch.syspath_prepend(str(root))
    sys.modules.pop("queries", None)
    import queries

    def down(*a, **k):
        raise RuntimeError("database paused")

    for fn in ("overview", "runs", "source_mix", "votes", "eval_report"):
        monkeypatch.setattr(queries, fn, down)
    at = AppTest.from_file(str(root / page), default_timeout=30).run()
    if page != "pages/1_Feedback.py":  # the feedback page has no guard of its own yet
        assert not at.exception, [e.value for e in at.exception]
        assert any("database paused" in e.value for e in at.error)
