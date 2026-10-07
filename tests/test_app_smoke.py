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


def test_vision_lab_reads_a_map_validates_it_and_loads_it_into_the_simulator():
    """Phase 6: image → world model → simulator, through the real app."""
    from gemmabot.simulator import new_world

    at = _run_app()
    # The tab it supersedes is gone: one reader, not two.
    assert "Map scanner" not in "\n".join(
        element.value for element in at.markdown
    )

    _button(at, "Read map").click().run()
    assert not at.exception, [element.value for element in at.exception]

    lab = at.session_state["vision_result"]
    assert lab["backend"] == "dry"
    assert lab["reader"] == "Scripted (dry mode)"
    assert lab["attempts"] == 2
    assert lab["world"] == new_world()
    # The first reading really was rejected, by the real validator.
    assert [record["ok"] for record in lab["history"]] == [False, True]
    assert "outside the 8×8 grid" in lab["history"][0]["feedback"]
    assert at.session_state["last_run"]["source"] == "vision"
    assert at.session_state["vision_loaded"] is False

    # Three columns, three checks (all passing on the accepted reading), and the
    # animated flow waiting on the load.
    rendered = "\n".join(element.value for element in at.markdown)
    assert "Vision lab" in rendered
    assert rendered.count("data-column=") == 3
    assert "data-column='image'" in rendered
    assert "data-column='vision'" in rendered
    assert "data-column='world'" in rendered
    assert rendered.count("data-check=") == 3
    assert "data-check='valid' data-ok='true'" in rendered
    assert "data-check='in_bounds' data-ok='true'" in rendered
    assert "data-check='reachable' data-ok='true'" in rendered
    assert "World it proposed" in rendered        # the reading, verbatim
    assert "data-attempt='1'" in rendered
    assert "data-stage='image' data-state='done'" in rendered
    assert "data-stage='world' data-state='done'" in rendered
    assert "data-stage='simulator' data-state='active'" in rendered
    # The map is still the default: reading a map does not adopt it.
    assert at.session_state["world"] == new_world()

    _button(at, "Load into simulator").click().run()
    assert not at.exception, [element.value for element in at.exception]

    assert at.session_state["world"] == new_world()
    assert at.session_state["map_name"] == "scanned"
    assert at.session_state["vision_loaded"] is True
    assert at.session_state["map_source"]["scanned"] == new_world()

    rendered = "\n".join(element.value for element in at.markdown)
    assert "data-stage='simulator' data-state='done'" in rendered
    assert rendered.count("data-stage=") == 3
    # The loaded world is a copy: executing on it cannot write back into the lab.
    assert at.session_state["world"] is not lab["world"]


def test_vision_lab_shows_unproven_checks_before_any_reading():
    at = _run_app()
    assert not at.exception, [element.value for element in at.exception]
    assert at.session_state["vision_result"] is None

    rendered = "\n".join(element.value for element in at.markdown)
    assert rendered.count("data-check=") == 3
    assert rendered.count("data-ok='none'") == 3      # never shown as a pass
    assert "no validated reading yet" in rendered
    # An image is already in hand (the built-in sample), so World is the stage
    # waiting on real work and the simulator is still pending.
    assert "data-stage='image' data-state='done'" in rendered
    assert "data-stage='world' data-state='active'" in rendered
    assert "data-stage='simulator' data-state='pending'" in rendered
    # With nothing validated there is nothing to load.
    load = _button(at, "Load into simulator")
    assert load.disabled is True
    assert at.session_state["vision_loaded"] is False


def _selectbox(at: AppTest, label: str):
    """The one selectbox carrying *label* (main body or sidebar)."""
    for box in at.selectbox:
        if box.label == label:
            return box
    raise AssertionError(f"no selectbox labelled {label!r}")


def test_replay_tab_replays_a_logged_run_without_any_model_call(monkeypatch):
    """Phase 7: pure replay out of the run log — no planner, no vision, no net."""
    from gemmabot import logger as run_logger
    from gemmabot.simulator import new_world
    from frontend.panels import engine as engine_impl

    world = new_world()
    hazard = [{"cmd": "forward", "steps": 7}]
    safe = [
        {"cmd": "turn_right"}, {"cmd": "forward", "steps": 7},
        {"cmd": "turn_left"}, {"cmd": "forward", "steps": 6},
        {"cmd": "turn_left"}, {"cmd": "forward", "steps": 2},
    ]
    replayable = {
        "timestamp": "2026-10-06T19:15:20.940844+00:00",
        "instruction": "Move to the goal using the safest route.",
        "backend": "dry", "success": True, "attempts": 2, "latency": 0.0,
        "actions": safe, "world": world,
        "history": [
            {"attempt": 1, "prompt": "p", "reply": "r", "ok": False,
             "feedback": "action 1 would enter the obstacle at [3, 0]",
             "actions": hazard},
            {"attempt": 2, "prompt": "p2", "reply": "r2", "ok": True,
             "feedback": "ok", "actions": safe},
        ],
    }
    # Written before worlds were captured: shown, offered, but not replayable.
    without_world = {
        "timestamp": "2026-10-04T10:00:00+00:00", "instruction": "an older run",
        "backend": "api", "success": True, "attempts": 1, "latency": 2.41,
        "history": [{"attempt": 1, "prompt": "p", "reply": "r", "ok": True,
                     "feedback": "ok"}],
    }

    monkeypatch.setattr(run_logger, "load_runs",
                        lambda path=None, **kwargs: [without_world, replayable])
    monkeypatch.setattr(run_logger, "summarize_run", lambda record: "summary")

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("a replay must not call a model")

    for name in ("run_plan", "run_map_vision", "get_ask", "get_vision_ask",
                 "_planner_functions", "_vision_functions", "dry_ask",
                 "dry_vision_ask"):
        monkeypatch.setattr(engine_impl, name, explode)

    at = _run_app()
    assert not at.exception, [element.value for element in at.exception]
    assert at.session_state["log_replay"] is None

    # The log table states run, backend, latency and attempts for every entry.
    rendered = "\n".join(element.value for element in at.markdown)
    assert ("data-run='2' data-backend='dry' data-latency='0.00 s' "
            "data-attempts='2' data-replayable='true'") in rendered
    assert "data-run='1' data-backend='api' data-latency='2.41 s'" in rendered
    assert "data-attempts='1' data-replayable='false'" in rendered
    assert "not replayable" in rendered

    # A record with no world offers no replay at all.
    runs_box = _selectbox(at, "Run")
    runs_box.select(runs_box.options[1]).run()
    assert _button(at, "Replay").disabled is True
    captions = "\n".join(element.value for element in at.caption)
    assert "Not replayable — logged before the world was captured" in captions

    runs_box = _selectbox(at, "Run")
    runs_box.select(runs_box.options[0]).run()
    _selectbox(at, "Plan to replay").select(
        "Attempt 2 — accepted · 6 actions"
    ).run()
    _button(at, "Replay").click().run()
    assert not at.exception, [element.value for element in at.exception]

    shown = at.session_state["log_replay"]
    assert shown["run"]["number"] == 2
    assert shown["plan"]["id"] == "attempt-2"
    assert [step["message"] for step in shown["timeline"]["steps"]] == [
        "turned right", "moved forward 7", "turned left", "moved forward 6",
        "turned left", "moved forward 2",
    ]
    assert shown["timeline"]["reached"] is True
    # The player was handed this replay and told to play it once.  That flag is
    # consumed by the render (popped), so its absence is the proof it ran.
    assert "log_replay_autoplay" not in at.session_state

    rendered = "\n".join(element.value for element in at.markdown)
    for fact in ("run", "backend", "latency", "attempts"):
        assert f"data-fact='{fact}'" in rendered
    assert "data-kind='run'" in rendered
    assert "data-kind='attempt'" in rendered
    assert "data-kind='repair'" in rendered
    assert "data-kind='replay'" in rendered
    assert "no model is called" in rendered
    assert "Replayed from" in rendered
    # Replaying is pure: the simulator's active world is untouched.
    assert at.session_state["world"] == new_world()
    assert at.session_state["log_replay"]["run"]["record"]["world"] == new_world()


def test_replay_picker_follows_a_newly_logged_replayable_run(monkeypatch):
    """A fresh replayable run becomes the selection; a hand-picked one sticks."""
    from gemmabot import logger as run_logger
    from gemmabot.simulator import new_world

    world = new_world()
    safe = [
        {"cmd": "turn_right"}, {"cmd": "forward", "steps": 7},
        {"cmd": "turn_left"}, {"cmd": "forward", "steps": 6},
        {"cmd": "turn_left"}, {"cmd": "forward", "steps": 2},
    ]
    legacy = {
        "timestamp": "2026-10-04T10:00:00+00:00", "instruction": "an older run",
        "backend": "api", "success": True, "attempts": 1, "latency": 2.41,
        "history": [{"attempt": 1, "prompt": "p", "reply": "r", "ok": True,
                     "feedback": "ok"}],
    }
    fresh = {
        "timestamp": "2026-10-06T19:15:20+00:00", "instruction": "a later run",
        "backend": "dry", "success": True, "attempts": 2, "latency": 0.1,
        "actions": safe, "world": world,
        "history": [
            {"attempt": 1, "prompt": "p", "reply": "r", "ok": False,
             "feedback": "blocked", "actions": [{"cmd": "forward", "steps": 7}]},
            {"attempt": 2, "prompt": "p2", "reply": "r2", "ok": True,
             "feedback": "ok", "actions": safe},
        ],
    }

    log = {"records": [legacy]}
    monkeypatch.setattr(run_logger, "load_runs",
                        lambda path=None, **kwargs: list(log["records"]))
    monkeypatch.setattr(run_logger, "summarize_run", lambda record: "summary")

    at = _run_app()
    assert not at.exception, [element.value for element in at.exception]
    # The only run in the log cannot be replayed, so Replay is disabled.
    assert _selectbox(at, "Run").value.startswith("Run 1 · ")
    assert _button(at, "Replay").disabled is True

    # A replayable run is logged: the picker follows it, instead of stranding
    # the user on a record whose Replay button is disabled.
    log["records"] = [legacy, fresh]
    at.run()
    assert not at.exception, [element.value for element in at.exception]
    runs_box = _selectbox(at, "Run")
    assert runs_box.value == runs_box.options[0]
    assert runs_box.value.startswith("Run 2 · Scripted (dry mode) · 0.10 s · 2")
    assert _button(at, "Replay").disabled is False

    # A run the user picked by hand is never overridden by the default.
    runs_box.select(runs_box.options[1]).run()
    assert _selectbox(at, "Run").value.startswith("Run 1 · ")
    assert _button(at, "Replay").disabled is True
    log["records"] = [legacy, fresh, dict(fresh, instruction="a third run")]
    at.run()
    assert _selectbox(at, "Run").value.startswith("Run 1 · ")

    # Switching to a replayable run offers its plans; the plan pick belongs to
    # one run, so moving to another run drops it rather than replaying the
    # previous run's plan under the new run's name.
    runs_box = _selectbox(at, "Run")
    runs_box.select(runs_box.options[0]).run()
    assert _button(at, "Replay").disabled is False
    assert _selectbox(at, "Plan to replay").value == (
        "Attempt 1 — rejected · 1 action"
    )
    _selectbox(at, "Plan to replay").select(
        "Attempt 2 — accepted · 6 actions"
    ).run()
    runs_box = _selectbox(at, "Run")
    assert runs_box.value.startswith("Run 3")
    runs_box.select(runs_box.options[1]).run()
    assert _selectbox(at, "Run").value.startswith("Run 2")
    assert _selectbox(at, "Plan to replay").value == (
        "Attempt 1 — rejected · 1 action"
    )
