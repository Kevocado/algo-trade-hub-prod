"""Tests for the failure notifier: build the message, and only send it when configured.

The notifier never reads `.env` and never prints a secret. Configuration is read from the process
environment only, and an unconfigured notifier is a silent no-op (the caller is told so it can say so
out loud rather than implying an alert was delivered).
"""
from __future__ import annotations

from tradehub.health_alerts import alert_on_failures, build_alert_message, telegram_configured

NOW = "2026-10-17T12:00:00+00:00"


def _report(problems, status="degraded"):
    return {"status": status, "generated_at": NOW, "problems": problems}


def test_the_message_names_each_problem():
    text = build_alert_message(_report(["timer journal is stale", "family weather_high is daily but froze nothing"]))
    assert "journal" in text
    assert "weather_high" in text


def test_a_healthy_report_produces_no_message():
    assert build_alert_message(_report([], status="ok")) == ""


def test_telegram_configured_reflects_the_two_env_vars(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_configured() is False
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    assert telegram_configured() is False  # chat id still missing
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    assert telegram_configured() is True


def test_alert_does_nothing_and_reports_false_when_not_configured(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    called = []
    result = alert_on_failures(_report(["timer journal is stale"]), post=lambda *a, **k: called.append(a))
    assert result is False
    assert called == []  # nothing was sent


def test_alert_posts_the_message_when_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    sent = {}

    class Resp:
        status_code = 200

    def post(url, json=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        return Resp()

    result = alert_on_failures(_report(["timer journal is stale"]), post=post)
    assert result is True
    assert "bottok/sendMessage" in sent["url"]
    assert sent["json"]["chat_id"] == "123"
    assert "journal" in sent["json"]["text"]


def test_a_failed_post_is_reported_false_not_raised(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    class Resp:
        status_code = 500

    assert alert_on_failures(_report(["timer journal is stale"]), post=lambda *a, **k: Resp()) is False


def test_a_healthy_report_is_never_sent_even_when_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    called = []
    assert alert_on_failures(_report([], status="ok"), post=lambda *a, **k: called.append(a)) is False
    assert called == []


def test_a_long_message_is_split_to_fit_telegram_and_keeps_every_line(monkeypatch):
    from tradehub.health_alerts import TELEGRAM_MAX_CHARS, split_message

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    problems = [f"- problem {i} {'x' * 200}" for i in range(40)]
    sent_texts = []

    class Resp:
        status_code = 200

    def post(url, json=None, timeout=None):
        sent_texts.append(json["text"])
        return Resp()

    assert alert_on_failures(_report(problems), post=post) is True
    assert len(sent_texts) > 1, "a 40-line alert must not go out as one rejected message"
    for text in sent_texts:
        assert len(text) <= TELEGRAM_MAX_CHARS
    rejoined = "\n".join(sent_texts)
    for p in problems:
        assert p in rejoined, "splitting must not drop a problem line"
    assert split_message("short") == ["short"]


def test_one_rejected_chunk_fails_the_whole_send(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    class Resp:
        status_code = 500

    assert alert_on_failures(_report(["timer journal is stale"]), post=lambda *a, **k: Resp()) is False
