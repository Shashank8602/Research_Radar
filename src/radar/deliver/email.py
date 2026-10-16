"""Email delivery behind one interface; backend picked by EMAIL_BACKEND."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import httpx

from radar.config import Env, get_env


def _build_message(subject: str, html: str, sender: str, to: str, text: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(text or "This email is best viewed as HTML.")
    msg.add_alternative(html, subtype="html")
    return msg


def _send_smtp(env: Env, subject: str, html: str, to: str, text: str | None) -> None:
    env.require("smtp_user", "smtp_password")
    sender = env.email_from or env.smtp_user
    msg = _build_message(subject, html, sender, to, text)
    with smtplib.SMTP(env.smtp_host, env.smtp_port, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(env.smtp_user, env.smtp_password)
        server.send_message(msg)


def _send_resend(env: Env, subject: str, html: str, to: str, text: str | None) -> None:
    env.require("resend_api_key", "email_from")
    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {env.resend_api_key}"},
        json={"from": env.email_from, "to": [to], "subject": subject, "html": html, "text": text},
        timeout=30,
    )
    resp.raise_for_status()


def send(subject: str, html: str, to: str | None = None, text: str | None = None) -> None:
    env = get_env()
    to = to or env.email_to
    if not to:
        raise RuntimeError("No recipient: pass `to` or set EMAIL_TO")
    backends = {"smtp": _send_smtp, "resend": _send_resend}
    try:
        backend = backends[env.email_backend]
    except KeyError:
        raise RuntimeError(f"Unknown EMAIL_BACKEND {env.email_backend!r}") from None
    backend(env, subject, html, to, text)
