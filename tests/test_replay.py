"""Tests for frontend/panels/replay.py — replaying a logged run.

No Streamlit, no network.  The "no model" tests replace every model entry point
with a function that raises, so a replay that reached one would fail loudly
instead of quietly making a call.
"""
import copy
import json

import pytest

from gemmabot.simulator import new_world
from frontend.panels import replay

# Two plans on the default world: one that walks into the wall column, and the
# verified route the log's second attempt really produced.
HAZARD_PLAN = [{"cmd": "forward", "steps": 7}]
SAFE_PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]


def _record(**overrides):
    """A record shaped exactly like ``logger.log_run`` writes them."""
    record = {
        "timestamp": "2026-10-06T19:15:20.940844+00:00",
        "instruction": "Move to the goal using the safest route.",
        "backend": "dry",
        "success": True,
        "attempts": 2,
        "latency": 0.0002,
        "actions": copy.deepcopy(SAFE_PLAN),
        "world": new_world(),
        "history": [
            {"attempt": 1, "prompt": "p", "reply": "r", "ok": False,
             "feedback": "action 1 would enter the obstacle at [3, 0]",
             "actions": copy.deepcopy(HAZARD_PLAN)},
            {"attempt": 2, "prompt": "p2", "reply": "r2", "ok": True,
             "feedback": "ok", "actions": copy.deepcopy(SAFE_PLAN)},
        ],
    }
    record.update(overrides)
    return record


@pytest.fixture
def no_model(monkeypatch):
    """Every path to a model raises.  A replay must not need any of them."""
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("replay must not call a model")

    from frontend.panels import engine as engine_impl

    monkeypatch.setattr(engine_impl, "run_plan", explode)
    monkeypatch.setattr(engine_impl, "run_map_vision", explode)
    monkeypatch.setattr(engine_impl, "get_ask", explode)
    monkeypatch.setattr(engine_impl, "get_vision_ask", explode)
    monkeypatch.setattr(engine_impl, "_planner_functions", explode)
    monkeypatch.setattr(engine_impl, "_vision_functions", explode)
    monkeypatch.setattr(engine_impl, "dry_ask", explode)
    monkeypatch.setattr(engine_impl, "dry_vision_ask", explode)
    return explode


# ---------------------------------------------------------------------------
# runs() — the log as display models
# ---------------------------------------------------------------------------

def test_runs_are_listed_newest_first_with_stable_numbers():
    models = replay.runs([_record(), _record(), _record()])
    assert [model["label"] for model in models] == ["Run 3", "Run 2", "Run 1"]
    assert [model["number"] for model in models] == [3, 2, 1]


def test_a_run_reads_its_own_record():
    model = replay.run(_record(), 7)
    assert model["label"] == "Run 7"
    assert model["instruction"] == "Move to the goal using the safest route."
    assert model["backend"] == "dry"
    assert model["backend_label"] == "Scripted (dry mode)"
    assert model["latency"] == pytest.approx(0.0002)
    assert model["latency_label"] == "0.00 s"
    assert model["attempts"] == 2
    assert model["attempts_label"] == "2"
    assert model["success"] is True
    assert model["mark"] == "✓"
    assert model["failed_attempts"] == 1
    assert model["when"] == "2026-10-06 19:15:20 UTC"


def test_a_failed_run_is_marked_as_such():
    model = replay.run(
        _record(success=False, actions=None,
                history=[{"attempt": 1, "prompt": "p", "reply": "r",
                          "ok": False, "feedback": "blocked"}]),
        2,
    )
    assert model["success"] is False
    assert model["mark"] == "✕"
    assert model["state"] == "error"


def test_missing_numbers_do_not_become_invented_ones():
    model = replay.run({"instruction": "i", "backend": "api", "world": new_world(),
                        "actions": [{"cmd": "forward"}]}, 1)
    assert model["latency"] is None
    assert model["latency_label"] == "—"
    assert model["attempts"] == 0
    assert model["history_length"] == 0


@pytest.mark.parametrize(
    "timestamp,expected",
    [
        ("2026-10-06T19:15:20.940844+00:00", "2026-10-06 19:15:20 UTC"),
        ("2026-10-06T19:15:20Z", "2026-10-06 19:15:20 UTC"),
        ("2026-10-06T19:15:20+02:00", "2026-10-06 19:15:20"),
        ("not a timestamp", "not a timestamp"),
        ("", "no timestamp"),
        (None, "no timestamp"),
    ],
)
def test_timestamps_are_shown_as_logged(timestamp, expected):
    assert replay.run({"timestamp": timestamp}, 1)["when"] == expected


# ---------------------------------------------------------------------------
# replayable() — never a guess
# ---------------------------------------------------------------------------

def test_a_record_with_a_world_and_a_plan_is_replayable():
    can_replay, reason = replay.replayable(_record())
    assert can_replay is True
    assert reason == ""


def test_a_record_from_before_worlds_were_captured_is_not_replayable():
    record = _record()
    del record["world"]
    can_replay, reason = replay.replayable(record)
    assert can_replay is False
    assert "before the world was captured" in reason


def test_a_record_with_no_world_key_value_is_not_replayable():
    can_replay, reason = replay.replayable(_record(world=None))
    assert can_replay is False
    assert reason == "no world was captured for this run"


def test_a_record_without_a_plan_is_not_replayable():
    can_replay, reason = replay.replayable(
        _record(actions=None, success=False,
                history=[{"attempt": 1, "prompt": "p", "reply": "r",
                          "ok": False, "feedback": "no json"}])
    )
    assert can_replay is False
    assert "no plan was recorded" in reason


def test_a_corrupt_world_is_reported_with_the_validators_own_sentence():
    can_replay, reason = replay.replayable(_record(world={"robot": [0, 0]}))
    assert can_replay is False
    assert "fails valid" in reason
    assert "missing required key" in reason


def test_an_out_of_grid_world_is_not_replayable():
    can_replay, reason = replay.replayable(_record(world={**new_world(),
                                                         "robot": [8, 0]}))
    assert can_replay is False
    assert "inside bounds" in reason.lower()
    assert "outside the 8×8 grid" in reason


def test_reachability_is_not_required_to_replay_an_already_run_plan():
    """The goal may be out of reach; the plan still ran, so it still replays."""
    world = {"robot": [0, 0], "dir": "E", "goal": [7, 7],
             "walls": [[6, 7], [7, 6], [6, 6]]}
    can_replay, reason = replay.replayable(_record(world=world))
    assert can_replay is True, reason


def test_a_log_line_that_is_not_a_record_is_not_replayable():
    for value in (None, "not a record", [], 7):
        can_replay, reason = replay.replayable(value)
        assert can_replay is False
        assert isinstance(reason, str) and reason


# ---------------------------------------------------------------------------
# plans() — only what the run recorded
# ---------------------------------------------------------------------------

def test_plans_lists_every_recorded_attempt_in_order():
    options = replay.plans(_record())
    assert [option["id"] for option in options] == ["attempt-1", "attempt-2"]
    assert [option["attempt"] for option in options] == [1, 2]
    assert [option["ok"] for option in options] == [False, True]
    assert [option["count"] for option in options] == [1, 6]
    assert options[0]["label"] == "Attempt 1 — rejected · 1 action"
    assert options[1]["label"] == "Attempt 2 — accepted · 6 actions"
    assert options[0]["actions"] == HAZARD_PLAN


def test_plans_falls_back_to_the_plan_the_record_stored():
    """A log written without per-attempt plans still has the accepted one."""
    options = replay.plans(_record(history=[
        {"attempt": 1, "prompt": "p", "reply": "r", "ok": True, "feedback": "ok"}
    ]))
    assert [option["id"] for option in options] == ["logged-plan"]
    assert options[0]["label"] == "Logged plan · 6 actions"
    assert options[0]["actions"] == SAFE_PLAN
    assert options[0]["attempt"] is None


def test_plans_is_empty_when_nothing_was_recorded():
    assert replay.plans(_record(actions=None, history=[])) == []
    assert replay.plans({}) == []


def test_plans_ignores_an_attempt_whose_reply_never_parsed():
    options = replay.plans(_record(history=[
        {"attempt": 1, "prompt": "p", "reply": "no json", "ok": False,
         "feedback": "could not parse reply as JSON", "actions": None},
        {"attempt": 2, "prompt": "p2", "reply": "r2", "ok": True,
         "feedback": "ok", "actions": SAFE_PLAN},
    ]))
    assert [option["attempt"] for option in options] == [2]


# ---------------------------------------------------------------------------
# timeline() — the simulator re-runs the recorded plan
# ---------------------------------------------------------------------------

def test_the_replay_runs_the_recorded_plan_on_the_recorded_world(no_model):
    record = _record()
    timeline = replay.timeline(record, replay.plans(record)[1])

    assert [step["label"] for step in timeline["steps"]] == [
        "turn right", "forward ×7", "turn left", "forward ×6",
        "turn left", "forward ×2",
    ]
    assert [step["message"] for step in timeline["steps"]] == [
        "turned right", "moved forward 7", "turned left", "moved forward 6",
        "turned left", "moved forward 2",
    ]
    assert timeline["reached"] is True
    assert timeline["halted"] is None
    assert timeline["final_world"]["robot"] == [6, 5]


def test_a_rejected_attempt_replays_as_the_simulator_really_ran_it(no_model):
    record = _record()
    timeline = replay.timeline(record, replay.plans(record)[0])

    assert [step["message"] for step in timeline["steps"]] == ["blocked at [2, 0]"]
    assert timeline["halted"] == "blocked"
    assert timeline["reached"] is False
    assert timeline["final_world"]["robot"] == [2, 0]


def test_replaying_does_not_move_the_robot_in_the_log(no_model):
    record = _record()
    before = copy.deepcopy(record["world"])
    replay.timeline(record, replay.plans(record)[1])
    assert record["world"] == before


def test_the_replay_timeline_carries_the_path_the_player_draws(no_model):
    record = _record()
    timeline = replay.timeline(record, replay.plans(record)[1])
    assert timeline["path"][0] == [0, 0]
    assert [6, 5] in timeline["path"]
    assert timeline["duration_ms"] > 0


def test_a_record_that_cannot_be_replayed_produces_no_timeline(no_model):
    assert replay.timeline({"world": None}, {"actions": SAFE_PLAN}) is None
    assert replay.timeline(_record(), None) is None
    assert replay.timeline(_record(), {"actions": []}) is None


# ---------------------------------------------------------------------------
# facts_rows
# ---------------------------------------------------------------------------

def test_the_four_readouts_are_run_backend_latency_attempts():
    rows = replay.facts_rows(replay.run(_record(), 4))
    assert [row["id"] for row in rows] == ["run", "backend", "latency", "attempts"]
    assert [row["label"] for row in rows] == ["Run", "Backend", "Latency", "Attempts"]
    values = {row["id"]: row["value"] for row in rows}
    assert values["run"] == "#4"
    assert values["backend"] == "Scripted (dry mode)"
    assert values["latency"] == "0.00 s"
    assert values["attempts"] == "2"


def test_the_attempts_readout_counts_what_the_history_shows():
    rows = {row["id"]: row for row in replay.facts_rows(replay.run(_record(), 1))}
    assert rows["attempts"]["detail"] == "1 failed · 2 recorded"
    assert rows["attempts"]["state"] == "error"


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def test_the_log_table_shows_the_four_fields_per_run():
    html = replay.runs_html(replay.runs([_record(success=False, attempts=3)]))
    assert "data-backend='dry'" in html
    assert "data-latency='0.00 s'" in html
    assert "data-attempts='3'" in html
    assert "data-run='1'" in html
    assert "run" in html and "backend" in html
    assert "latency" in html and "attempts" in html


def test_the_log_table_marks_what_cannot_be_replayed():
    record = _record()
    del record["world"]
    html = replay.runs_html(replay.runs([record]))
    assert "data-replayable='false'" in html
    assert "not replayable" in html


def test_the_log_table_says_so_when_the_log_is_empty():
    assert "No runs have been logged yet." in replay.runs_html([])


def test_the_timeline_shows_attempts_retries_and_the_replay():
    record = _record()
    model = replay.run(record, 1)
    html = replay.timeline_html(model, replay.plans(record)[1])
    kinds = [kind for kind in ("run", "attempt", "repair", "replay")
             if f"data-kind='{kind}'" in html]
    assert kinds == ["run", "attempt", "repair", "replay"]
    assert html.index("data-kind='run'") < html.index("data-kind='attempt'")
    assert html.index("data-kind='attempt'") < html.index("data-kind='repair'")
    assert html.index("data-kind='repair'") < html.index("data-kind='replay'")
    assert "Attempt 1" in html and "Attempt 2" in html
    assert "data-attempt='1' data-ok='false'" in html
    assert "data-attempt='2' data-ok='true'" in html
    assert "data-plan='attempt-2'" in html


def test_the_timeline_without_a_replay_stops_at_the_last_attempt():
    record = _record()
    html = replay.timeline_html(replay.run(record, 1), None)
    assert "data-kind='replay'" not in html
    assert "data-kind='attempt'" in html


def test_the_meta_line_offers_the_run_and_what_is_being_replayed():
    record = _record()
    model = replay.run(record, 9)
    html = replay.meta_html(model, replay.plans(record)[1])
    assert "Succeeded" in html
    assert "Run" in html and "#9" in html
    assert "Scripted (dry mode)" in html
    assert "0.00 s" in html
    assert "Attempt 2 — accepted · 6 actions" in html
    assert "instruction" in html


def test_the_meta_line_explains_why_nothing_can_be_replayed():
    record = _record()
    del record["world"]
    html = replay.meta_html(replay.run(record, 1), None)
    assert "Not replayable" in html
    assert "before the world was captured" in html


def test_hostile_log_text_cannot_inject_markup():
    record = _record(
        instruction='<img src=x onerror=alert(1)> " <script>alert(2)</script>',
        backend="<b>api</b>",
    )
    model = replay.run(record, 1)
    rendered = {
        "runs": replay.runs_html(replay.runs([record])),
        "meta": replay.meta_html(model, replay.plans(record)[0]),
        "timeline": replay.timeline_html(model, replay.plans(record)[0]),
        "source": replay.source_html("logs/runs.jsonl", model),
    }
    for name, html in rendered.items():
        assert "<img" not in html, name
        assert "<script>" not in html, name
    # The three that carry the hostile text escaped it rather than dropping it.
    for name in ("runs", "meta", "timeline"):
        assert "&lt;" in rendered[name], name


def test_the_source_line_names_the_log_and_the_absence_of_a_model():
    html = replay.source_html("logs/runs.jsonl", replay.run(_record(), 3))
    assert "logs/runs.jsonl" in html
    assert "no model is called" in html or "no model" in html
    assert "Run 3" in html


def test_the_panel_is_a_design_system_panel():
    html = replay.panel("<div>body</div>")
    assert "gb-panel" in html
    assert "Replay" in html


# ---------------------------------------------------------------------------
# end to end through the real logger, with no model anywhere in sight
# ---------------------------------------------------------------------------

def test_a_logged_run_replays_from_the_log_alone(tmp_path, no_model):
    from gemmabot import logger as run_logger

    path = tmp_path / "runs.jsonl"
    run_logger.log_run(
        instruction="Move to the goal using the safest route.",
        backend="dry",
        actions=SAFE_PLAN,
        attempts=2,
        history=_record()["history"],
        latency=0.5,
        path=str(path),
        world=new_world(),
    )
    run_logger.log_run(
        instruction="an older run",
        backend="api",
        actions=None,
        attempts=1,
        history=[],
        latency=1.0,
        path=str(path),
    )

    models = replay.runs(run_logger.load_runs(path=str(path)))
    # Newest first: the second call is the one without a world.
    assert [model["instruction"] for model in models] == [
        "an older run", "Move to the goal using the safest route.",
    ]
    without_world, with_world = models

    # The logger always writes the key, so this record says the world was not
    # captured; a log file written before the key existed says so differently.
    assert without_world["replayable"] is False
    assert without_world["reason"] == "no world was captured for this run"
    assert "world" in without_world["record"]
    assert with_world["replayable"] is True

    # Both recorded attempts replay, straight out of the log file.
    rejected, accepted = with_world["plans"]
    assert rejected["ok"] is False
    assert [step["message"] for step in
            replay.timeline(with_world["record"], rejected)["steps"]] == [
        "blocked at [2, 0]"]

    timeline = replay.timeline(with_world["record"], accepted)
    assert [step["message"] for step in timeline["steps"]] == [
        "turned right", "moved forward 7", "turned left", "moved forward 6",
        "turned left", "moved forward 2",
    ]
    assert timeline["reached"] is True
    assert json.dumps(timeline["final_world"])  # plain data, nothing exotic


# ---------------------------------------------------------------------------
# The replay feeds the Phase 3 player: movement, action highlighting, timeline
# ---------------------------------------------------------------------------

def test_the_player_is_handed_one_highlightable_row_per_action(no_model):
    from frontend.simulation import player_view

    record = _record()
    timeline = replay.timeline(record, replay.plans(record)[1])
    html = player_view.player_html(timeline)

    # One row per action, addressed by index — the player highlights the active
    # one and marks the finished ones.
    for index in range(1, len(timeline["steps"]) + 1):
        assert f"data-step='{index}'" in html
    assert "turn right" in html
    assert "forward ×7" in html
    assert ".gb-step.active" in html          # the highlight rule
    assert "classList.toggle('active'" in html  # what drives it while playing
    assert "gb-step-dot" in html
    # The trace the player draws behind the robot is the replayed path.
    assert timeline["path"]


def test_a_halted_replay_still_renders_its_own_step(no_model):
    from frontend.simulation import player_view

    record = _record()
    timeline = replay.timeline(record, replay.plans(record)[0])
    html = player_view.player_html(timeline)

    assert "data-step='1'" in html
    assert "blocked at [2, 0]" in html
    assert "gb-step-dot err" in html          # the halted action is marked
