import pytest
from pydantic import BaseModel

from radar import llm
from radar.config import Env, load_config
from radar.deliver import email as mail


def test_topics_yaml_loads():
    cfg = load_config()
    assert cfg.models.judge.startswith("groq/")
    assert cfg.digest.sections["core"].max_items == 5
    assert {t.name for t in cfg.topics} >= {"agentic-systems", "rag-retrieval"}


def test_env_require_reports_missing():
    env = Env(_env_file=None, database_url=None)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        env.require("database_url")


def test_router_has_groq_primary_and_fallbacks():
    cfg = load_config()
    router = llm.build_router(cfg, Env(_env_file=None, groq_api_key="x"))
    names = [m["model_name"] for m in router.model_list]
    assert names[0] == "judge"
    assert len(names) == 1 + len(cfg.models.fallbacks)


class _Out(BaseModel):
    n: int


class _FakeRouter:
    def __init__(self, contents):
        self.contents = list(contents)
        self.model_list = [{"litellm_params": {"model": "fake/model"}}]
        self.calls = 0

    def completion(self, **kwargs):
        self.calls += 1
        content = self.contents.pop(0)

        class M:
            pass

        m = M()
        m.message = M()
        m.message.content = content
        r = M()
        r.choices = [m]
        r.model = "fake-model"
        return r


def test_structured_retries_once_on_invalid_json():
    router = _FakeRouter(['{"n": "oops"}', '{"n": 3}'])
    obj, model = llm.complete_structured("p", _Out, router=router)
    assert obj.n == 3 and model == "fake-model" and router.calls == 2


def test_structured_raises_after_retries():
    router = _FakeRouter(["nope", "still nope"])
    with pytest.raises(ValueError):
        llm.complete_structured("p", _Out, router=router)


def test_email_unknown_backend(monkeypatch):
    env = Env(_env_file=None, email_backend="carrier-pigeon", email_to="a@b.c")
    monkeypatch.setattr(mail, "get_env", lambda: env)
    with pytest.raises(RuntimeError, match="Unknown EMAIL_BACKEND"):
        mail.send("s", "<p>h</p>")


def test_email_message_has_html_alternative():
    msg = mail._build_message("s", "<p>hi</p>", "a@b.c", "d@e.f", None)
    assert msg.get_body(preferencelist=("html",)).get_content().strip() == "<p>hi</p>"


def test_digest_date_follows_the_readers_timezone_not_the_runners():
    from datetime import UTC, date, datetime

    from radar.config import load_config, local_today

    tz = load_config().timezone
    assert tz == "Asia/Kolkata"
    # The scheduled run (22:00 UTC) is already the next morning in India, so it is tomorrow's digest.
    assert local_today(tz, datetime(2026, 10, 17, 22, 0, tzinfo=UTC)) == date(2026, 10, 18)
    # The 07:58 UTC run earlier that day (13:28 IST) is still the 17th: no collision with the 22:00 one.
    assert local_today(tz, datetime(2026, 10, 17, 7, 58, tzinfo=UTC)) == date(2026, 10, 17)
    assert local_today("UTC", datetime(2026, 10, 17, 22, 0, tzinfo=UTC)) == date(2026, 10, 17)
