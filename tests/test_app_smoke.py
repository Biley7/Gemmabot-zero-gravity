"""Smoke and flow tests for app.py using Streamlit's AppTest.

These run the real script headlessly.  Model backends are patched with fakes
so nothing touches the network or writes run logs.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"

# A plan that really solves the default world (verified in harness tests).
DEFAULT_WORLD_PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]


@pytest.fixture(autouse=True)
def _no_run_log_writes(monkeypatch):
    """Keep tests from appending to logs/runs.jsonl."""
    try:
        from gemmabot import logger as run_logger
    except ImportError:  # pragma: no cover
        return
    monkeypatch.setattr(run_logger, "log_run", lambda *args, **kwargs: {})


def _run_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=60).run()


def _button(at: AppTest, label: str):
    for button in at.button:
        if button.label == label:
            return button
    raise AssertionError(f"button {label!r} not found; got {[b.label for b in at.button]}")


def test_app_starts_without_exceptions():
    at = _run_app()
    assert not at.exception, [element.value for element in at.exception]
    assert at.title[0].value == "🤖 GemmaBot"


def test_sidebar_controls_exist():
    at = _run_app()
    assert len(at.sidebar.radio) == 1          # Engine
    assert len(at.sidebar.selectbox) == 1      # Map picker
    assert len(at.sidebar.slider) == 1         # Animation speed
    assert len(at.sidebar.number_input) == 1   # Max tries


def test_map_picker_switches_the_active_world():
    at = _run_app()
    at.sidebar.selectbox[0].select("sample").run()
    assert not at.exception, [element.value for element in at.exception]
    world = at.session_state["world"]
    assert world["robot"] == [0, 0]
    assert world["goal"] == [7, 7]
    assert world["dir"] == "E"


def test_run_plan_renders_metrics_and_executes(monkeypatch):
    """Regression: rendering a finished run must not crash (audio KeyError)."""
    import engine

    def fake_run_plan(instruction, world, backend="api", max_tries=3, ask=None):
        return {
            "actions": DEFAULT_WORLD_PLAN,
            "attempts": 1,
            "history": [
                {
                    "attempt": 1,
                    "prompt": instruction,
                    "reply": json.dumps({"thought": "t", "actions": DEFAULT_WORLD_PLAN}),
                    "ok": True,
                    "feedback": "ok",
                }
            ],
            "latency": 1.25,
            "backend": "api",
            "error": None,
        }

    monkeypatch.setattr(engine, "run_plan", fake_run_plan)

    at = _run_app()
    at.sidebar.slider[0].set_value(0.0).run()   # no animation delay
    _button(at, "Run plan").click().run()

    assert not at.exception, [element.value for element in at.exception]
    assert at.session_state["world"]["robot"] == [6, 5]
    assert at.session_state["last_run"]["status"] == "Verified safe"
    assert at.session_state["last_run"]["backend"] == "api"
    metrics = {m.label: m.value for m in at.metric}
    assert metrics.get("Attempts") == "1 / 3"
    assert metrics.get("Latency") == "1.25 s"
    assert metrics.get("Backend") == "api"
    assert metrics.get("Status") == "Verified safe"


def test_run_plan_failure_renders_reason_and_does_not_move_robot(monkeypatch):
    import engine

    reason = "could not parse reply as JSON"

    def fake_run_plan(instruction, world, backend="api", max_tries=3, ask=None):
        return {
            "actions": None,
            "attempts": 1,
            "history": [
                {
                    "attempt": 1,
                    "prompt": instruction,
                    "reply": "no json here",
                    "ok": False,
                    "feedback": reason,
                }
            ],
            "latency": 0.5,
            "backend": "api",
            "error": reason,
        }

    monkeypatch.setattr(engine, "run_plan", fake_run_plan)

    at = _run_app()
    _button(at, "Run plan").click().run()

    assert not at.exception, [element.value for element in at.exception]
    assert at.session_state["world"]["robot"] == [0, 0], "failed AI must not move the robot"
    assert any(reason in element.value for element in at.error)
