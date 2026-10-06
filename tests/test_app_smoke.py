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
    assert len(at.sidebar.number_input) == 1   # Max tries
    # Playback speed now lives in the execution player (0.5× / 1× / 2× / 4×),
    # so the old per-step sleep slider is gone.
    assert len(at.sidebar.slider) == 0


def test_map_picker_switches_the_active_world():
    at = _run_app()
    at.sidebar.selectbox[0].select("sample").run()
    assert not at.exception, [element.value for element in at.exception]
    world = at.session_state["world"]
    assert world["robot"] == [0, 0]
    assert world["goal"] == [7, 7]
    assert world["dir"] == "E"


def test_run_plan_builds_a_replayable_execution_timeline(monkeypatch):
    """A verified plan is executed into a timeline the player can replay."""
    import engine

    def fake_run_plan(
        instruction, world, backend="api", max_tries=3, ask=None, on_attempt=None
    ):
        history = [
            {
                "attempt": 1,
                "prompt": instruction,
                "reply": json.dumps({"thought": "t", "actions": DEFAULT_WORLD_PLAN}),
                "actions": DEFAULT_WORLD_PLAN,
                "ok": True,
                "feedback": "ok",
            }
        ]
        # The real harness streams each record to the UI the moment it exists.
        if on_attempt is not None:
            for record in history:
                on_attempt(record)
        return {
            "actions": DEFAULT_WORLD_PLAN,
            "attempts": 1,
            "history": history,
            "latency": 1.25,
            "backend": "api",
            "error": None,
            "verification": engine.verify_run(world, DEFAULT_WORLD_PLAN, history),
        }

    monkeypatch.setattr(engine, "run_plan", fake_run_plan)

    at = _run_app()
    _button(at, "Run plan").click().run()

    assert not at.exception, [element.value for element in at.exception]
    assert at.session_state["world"]["robot"] == [6, 5]
    assert at.session_state["last_run"]["status"] == "Verified safe"
    assert at.session_state["last_run"]["backend"] == "api"

    # Phase 3: the board slot now shows the player for this run.
    replay = at.session_state["replay"]
    assert replay["reached"] is True
    assert replay["duration_ms"] > 0
    assert replay["cells"] >= len(DEFAULT_WORLD_PLAN) - 1
    assert replay["final_world"]["robot"] == [6, 5]
    assert at.session_state["text_result"]["replay"] == replay
    # The one-shot autoplay flag is consumed while the player renders.
    assert at.session_state.get("replay_autoplay") in (None, False)


# A distinctive marker for the model's private reasoning.  The panel must
# never contain it: it renders metadata, not a transcript.
REASONING = "SECRET-reasoning-marker"


def test_run_plan_shows_the_gemma_brain_metadata(monkeypatch):
    """Phase 4: the panel reports the run's real numbers and four checks."""
    import engine

    def fake_run_plan(
        instruction, world, backend="api", max_tries=3, ask=None, on_attempt=None
    ):
        history = [
            {
                "attempt": 1,
                "prompt": instruction,
                "reply": json.dumps({"thought": REASONING, "actions": DEFAULT_WORLD_PLAN}),
                "actions": DEFAULT_WORLD_PLAN,
                "ok": True,
                "feedback": "ok",
            }
        ]
        return {
            "actions": DEFAULT_WORLD_PLAN,
            "attempts": 1,
            "history": history,
            "latency": 1.25,
            "backend": "api",
            "error": None,
            "verification": engine.verify_run(world, DEFAULT_WORLD_PLAN, history),
        }

    monkeypatch.setattr(engine, "run_plan", fake_run_plan)

    at = _run_app()
    _button(at, "Run plan").click().run()

    assert not at.exception, [element.value for element in at.exception]
    meta = at.session_state["text_result"]["brain"]
    assert meta["model"]["family"] == "Gemma 4"
    assert meta["model"]["id"]          # the configured id, not a placeholder
    assert meta["backend"]["label"] == "API (Gemini)"
    assert meta["status"]["key"] == "executing"
    assert meta["attempts"]["label"] == "1 / 3"
    assert meta["latency"]["label"] == "1.25 s"
    assert meta["plan"]["label"] == f"{len(DEFAULT_WORLD_PLAN)} actions"
    assert [entry["ok"] for entry in meta["checks"]] == [True] * 4
    assert meta["verified"] is True

    panels = [element.value for element in at.markdown if "Gemma Brain" in element.value]
    assert len(panels) == 1, "expected exactly one Brain panel"
    panel = panels[0]
    assert panel.count("data-ok='true'") == 4
    # The panel is structured metadata: the model's reasoning is not in it.
    assert REASONING not in panel
    assert "Model reply" not in panel


def test_safety_lab_dry_run_builds_the_verifier_and_repair_timeline():
    """Phase 5: the lab runs the real loop; dry mode scripts only the replies."""
    at = _run_app()
    _button(at, "Run safety check").click().run()

    assert not at.exception, [element.value for element in at.exception]
    lab = at.session_state["safety_result"]
    assert lab["planner"] == "Scripted (dry mode)"

    # ✓ Proposal → ✕ Collision → ↻ Repair → ✓ Proposal → ✓ Safe
    assert [stage["kind"] for stage in lab["stages"]] == [
        "proposal", "collision", "repair", "proposal", "safe"
    ]
    assert lab["summary"]["collision"]["cell"] == [3, 0]
    assert lab["summary"]["collision"]["attempt"] == 1
    assert lab["summary"]["repairs"] == {"count": 1, "attempts": [1], "label": "1 repair"}
    assert lab["summary"]["success"]["ok"] is True
    assert lab["summary"]["success"]["attempt"] == 2

    # Both attempts are replayable, from the simulator's own timelines.
    assert [item["attempt"] for item in lab["replays"]] == [1, 2]
    assert lab["replays"][0]["halted"] == "blocked"
    assert lab["replays"][1]["reached"] is True

    # The lab demonstrates on its own world: the main board is untouched.
    assert at.session_state["world"]["robot"] == [0, 0]
    assert at.session_state["last_run"]["source"] == "safety"

    rendered = "\n".join(element.value for element in at.markdown)
    assert "Safety lab" in rendered
    assert rendered.count("gb-safety-chip") == 5
    assert rendered.count("gb-safety-fact") == 4
    assert "data-cell='[3, 0]'" in rendered
    # The refused cell is marked on the map the lab draws.
    assert "gb-danger-pulse" in rendered
    assert "Gemma Plan" in rendered


def test_run_plan_failure_renders_reason_and_does_not_move_robot(monkeypatch):
    import engine

    reason = "could not parse reply as JSON"

    def fake_run_plan(
        instruction, world, backend="api", max_tries=3, ask=None, on_attempt=None
    ):
        return {
            "actions": None,
            "attempts": 1,
            "history": [
                {
                    "attempt": 1,
                    "prompt": instruction,
                    "reply": "no json here",
                    "actions": None,
                    "ok": False,
                    "feedback": reason,
                }
            ],
            "latency": 0.5,
            "backend": "api",
            "error": reason,
            "verification": None,
        }

    monkeypatch.setattr(engine, "run_plan", fake_run_plan)

    at = _run_app()
    _button(at, "Run plan").click().run()

    assert not at.exception, [element.value for element in at.exception]
    assert at.session_state["world"]["robot"] == [0, 0], "failed AI must not move the robot"
    assert any(reason in element.value for element in at.error)

    # The panel still reports the run honestly: nothing was verified.
    meta = at.session_state["text_result"]["brain"]
    assert meta["status"]["key"] == "repairing"
    assert meta["plan"]["label"] == "—"
    assert [entry["ok"] for entry in meta["checks"]] == [None] * 4
    assert meta["verified"] is False
    panel = next(element.value for element in at.markdown if "Gemma Brain" in element.value)
    assert panel.count("data-ok='none'") == 4
    assert "data-ok='true'" not in panel
