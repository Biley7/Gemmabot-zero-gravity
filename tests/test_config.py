"""Tests for gemmabot/config.py — env overrides and credential helpers.

No network, no real key: the helpers report presence only, and the message
must never contain a configured value.
"""
import importlib

import pytest


def test_missing_key_is_reported_without_a_value(monkeypatch):
    from gemmabot import config

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert config.api_key() == ""
    assert config.has_api_key() is False

    message = config.missing_api_key_message()
    assert "GEMINI_API_KEY" in message
    assert "Nothing was sent" in message


def test_a_present_key_reports_presence_only(monkeypatch):
    from gemmabot import config

    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    assert config.has_api_key() is True
    assert "super-secret-value" not in config.missing_api_key_message()


def test_max_repairs_reads_a_valid_env_override(monkeypatch):
    from gemmabot import config

    monkeypatch.setenv("MAX_REPAIRS", "4")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MAX_REPAIRS == 4
    finally:
        monkeypatch.delenv("MAX_REPAIRS", raising=False)
        importlib.reload(config)


@pytest.mark.parametrize("value", ["not-a-number", "", "  ", "0", "-3"])
def test_max_repairs_falls_back_safely_on_a_bad_value(monkeypatch, value):
    from gemmabot import config

    monkeypatch.setenv("MAX_REPAIRS", value)
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MAX_REPAIRS == reloaded.DEFAULT_MAX_REPAIRS
    finally:
        monkeypatch.delenv("MAX_REPAIRS", raising=False)
        importlib.reload(config)
