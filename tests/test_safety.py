"""Tests for the Safety Lab (timeline, readouts, replays, HTML).

The lab exists to demonstrate the verifier and the repair loop, so these tests
mostly pin honesty: each stage is read off a real attempt record, a collision
cell is the cell the verifier actually refused, and nothing is invented for an
attempt that never produced a runnable plan.
"""
import copy
import json
import re

import engine
from backend.verifier.harness import plan_with_repair
from frontend.components import colors as C
from frontend.panels import safety
from gemmabot.simulator import new_world

# A plan that really walks into the wall column at x=3 of the default world.
HAZARD_PLAN = [{"cmd": "forward", "steps": 7}]
# turn_left from [0,0] E faces N, so one step aims at [0, -1] — off the grid.
OFF_GRID_PLAN = [{"cmd": "turn_left"}, {"cmd": "forward", "steps": 1}]
# Runs cleanly but stops two cells short of the goal [6, 5].
SHORT_PLAN = [{"cmd": "forward", "steps": 2}]


def _record(attempt, actions, ok, feedback, reply=None):
    """One harness history record, in the shape plan_with_repair writes."""
    return {
        "attempt": attempt,
        "prompt": f"go to the goal (attempt {attempt})",
        "reply": reply if reply is not None else json.dumps(
            {"thought": "t", "actions": actions or []}
        ),
        "actions": actions,
        "ok": ok,
        "feedback": feedback,
    }


def _dry_history(safe_on_attempt: int = 2, max_tries: int = 3):
    """A real dry run's history — the scripted planner through the real loop."""
    _, _, history = plan_with_repair(
        "Move to the goal using the safest route.",
        new_world(),
        engine.dry_ask(safe_on_attempt),
        max_tries=max_tries,
    )
    return history


def _kinds(stage_list):
    return [stage["kind"] for stage in stage_list]


def _timeline_text(stage_list):
    return [f"{s['mark']} {s['label']}" for s in stage_list]


# ---------------------------------------------------------------------------
# The timeline
# ---------------------------------------------------------------------------

def test_a_real_dry_run_produces_the_documented_timeline():
    stages = safety.stages(new_world(), _dry_history())

    assert _timeline_text(stages) == [
        "✓ Proposal",
        "✕ Collision",
        "↻ Repair",
        "✓ Proposal",
        "✓ Safe",
    ]
    assert [s["attempt"] for s in stages] == [1, 1, 1, 2, 2]


def test_the_collision_cell_is_the_cell_the_verifier_refused():
    stages = safety.stages(new_world(), _dry_history())
    collision = next(s for s in stages if s["kind"] == "collision")

    # The wall column at x=3 — the simulator's own answer, not a guess.
    assert collision["cell"] == [3, 0]
    assert collision["action_index"] == 1
    assert "[3, 0]" in collision["detail"]
    assert stages[0]["actions_count"] == 1


def test_the_repair_stage_carries_the_prompt_the_loop_really_sent():
    history = _dry_history()
    stages = safety.stages(new_world(), history)
    repair = next(s for s in stages if s["kind"] == "repair")

    assert repair["prompt"] == history[1]["prompt"]
    # The repair prompt keeps the original instruction and states the failure.
    assert "Move to the goal using the safest route." in repair["prompt"]
    assert "blocked" in repair["prompt"]


def test_no_repair_stage_after_the_accepted_attempt():
    stages = safety.stages(new_world(), _dry_history())

    assert stages[-1]["kind"] == "safe"
    assert _kinds(stages).count("repair") == 1


def test_a_reply_that_never_parsed_is_a_failed_proposal_with_no_collision():
    history = [
        _record(1, None, False, "could not parse reply as JSON: No JSON found"),
        _record(1, [], False, "empty plan: robot is at [0, 0] but goal is at [6, 5]"),
    ]

    stages = safety.stages(new_world(), history)

    assert _kinds(stages) == ["invalid", "repair", "invalid"]
    assert stages[0]["mark"] == "✕"
    assert stages[0]["label"] == "Proposal"
    assert all(stage["cell"] is None for stage in stages)
    assert "JSON" in stages[0]["error"]


def test_an_out_of_bounds_move_is_not_reported_as_a_collision():
    history = [_record(1, OFF_GRID_PLAN, False, "blocked at [0, 0]")]

    stages = safety.stages(new_world(), history)
    bounds = next(s for s in stages if s["kind"] == "bounds")

    assert _kinds(stages) == ["proposal", "bounds"]
    assert bounds["cell"] == [0, -1]
    # A grid edge is not an obstacle: no collision may be claimed.
    assert not any(s["kind"] == "collision" for s in stages)


def test_a_plan_that_runs_but_misses_the_goal_is_a_missed_goal():
    history = [_record(1, SHORT_PLAN, False, "plan finished but goal not reached")]

    stages = safety.stages(new_world(), history)
    missed = next(s for s in stages if s["kind"] == "missed")

    assert _kinds(stages) == ["proposal", "missed"]
    assert missed["mark"] == "✕"
    assert missed["cell"] is None
    assert "[2, 0]" in missed["detail"]


def test_an_unknown_command_in_a_parsed_plan_is_an_invalid_plan():
    history = [_record(1, [{"cmd": "fly"}], False, "unknown command: {'cmd': 'fly'}")]

    stages = safety.stages(new_world(), history)

    assert _kinds(stages) == ["proposal", "invalid"]
    assert stages[1]["label"] == "Invalid reply"
    assert stages[1]["cell"] is None


def test_stages_never_mutate_the_world():
    world = new_world()
    before = copy.deepcopy(world)

    safety.stages(world, _dry_history())

    assert world == before


def test_an_empty_history_is_an_empty_timeline():
    assert safety.stages(new_world(), None) == []
    assert safety.stages(new_world(), []) == []


# ---------------------------------------------------------------------------
# The four readouts
# ---------------------------------------------------------------------------

def test_summary_reports_the_collision_the_error_the_repair_and_success():
    stages = safety.stages(new_world(), _dry_history())
    summary = safety.summary(stages)

    assert summary["collision"]["cell"] == [3, 0]
    assert summary["collision"]["text"] == "[3, 0]"
    assert summary["collision"]["attempt"] == 1
    assert summary["error"]["attempt"] == 1
    assert "[3, 0]" in summary["error"]["message"]
    assert "blocked" in summary["error"]["reason"]
    assert summary["repairs"] == {"count": 1, "attempts": [1], "label": "1 repair"}
    assert summary["success"]["ok"] is True
    assert summary["success"]["attempt"] == 2
    assert summary["attempts"] == 2


def test_an_accepted_safe_stage_is_not_counted_as_a_failure():
    summary = safety.summary(safety.stages(new_world(), _dry_history()))

    assert summary["failures"] == 1


def test_an_unrepaired_run_reports_no_success():
    history = [_record(1, HAZARD_PLAN, False, "blocked"), _record(2, HAZARD_PLAN, False, "blocked")]

    summary = safety.summary(safety.stages(new_world(), history))

    assert summary["success"]["ok"] is False
    assert summary["success"]["attempt"] is None
    assert "Not resolved" in summary["success"]["label"]
    assert summary["repairs"]["count"] == 1
    assert summary["failures"] == 2


def test_facts_rows_are_the_four_requested_readouts():
    rows = safety.facts_rows(safety.summary(safety.stages(new_world(), _dry_history())))

    assert [row["id"] for row in rows] == ["collision", "error", "repair", "success"]
    assert [row["label"] for row in rows] == [
        "Collision location", "Error", "Repair attempt", "Success"
    ]
    by_id = {row["id"]: row for row in rows}
    assert by_id["collision"]["value"] == "[3, 0]"
    assert by_id["collision"]["state"] == "error"
    assert by_id["repair"]["value"] == "1 repair"
    assert by_id["success"]["value"] == "✓ Safe"
    assert by_id["success"]["state"] == "success"


def test_facts_rows_stay_honest_when_nothing_failed():
    stages = safety.stages(new_world(), [_record(1, engine.DRY_SAFE_PLAN, True, "ok")])
    rows = safety.facts_rows(safety.summary(stages))

    by_id = {row["id"]: row for row in rows}
    assert by_id["collision"]["value"] == "none"
    assert by_id["collision"]["state"] == "success"
    assert by_id["repair"]["value"] == "no repair"
    assert by_id["error"]["value"] == "none"


# ---------------------------------------------------------------------------
# Replays
# ---------------------------------------------------------------------------

def test_each_attempt_with_a_plan_gets_a_real_replay():
    history = _dry_history()
    replay_list = safety.replays(new_world(), history)

    assert [item["attempt"] for item in replay_list] == [1, 2]
    assert [item["ok"] for item in replay_list] == [False, True]

    rejected, accepted = replay_list
    # The rejected plan really walks into the wall and is halted there.
    assert rejected["halted"] == "blocked"
    assert rejected["reached"] is False
    assert rejected["timeline"]["final_world"]["robot"] != [6, 5]
    # The accepted plan really reaches the goal.
    assert accepted["halted"] is None
    assert accepted["reached"] is True
    assert accepted["timeline"]["final_world"]["robot"] == [6, 5]


def test_replays_skip_attempts_with_nothing_to_run():
    history = [_record(1, None, False, "no JSON"), _record(2, HAZARD_PLAN, False, "blocked")]

    replay_list = safety.replays(new_world(), history)

    assert [item["attempt"] for item in replay_list] == [2]


def test_replays_never_mutate_the_world():
    world = new_world()
    before = copy.deepcopy(world)

    safety.replays(world, _dry_history())

    assert world == before


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def test_pipeline_diagram_lists_the_loop_in_order():
    html = safety.pipeline_html()

    positions = [html.index(name) for name in safety.PIPELINE]
    assert positions == sorted(positions), "the pipeline must read left to right"
    assert safety.PIPELINE == (
        "Gemma Plan", "Verification", "Failure", "Repair", "New Plan"
    )


def test_timeline_chips_carry_the_marks_and_kinds():
    stages = safety.stages(new_world(), _dry_history())
    html = safety.timeline_html(stages)

    assert html.count("gb-safety-chip") == len(stages)
    for kind in ("proposal", "collision", "repair", "safe"):
        assert f"data-kind='{kind}'" in html
    assert "✓ Proposal" in html
    assert "✕ Collision" in html
    assert "↻ Repair" in html
    assert "✓ Safe" in html
    assert "data-cell='[3, 0]'" in html


def test_timeline_handles_an_empty_run():
    html = safety.timeline_html([])

    assert "No safety check has run yet" in html
    assert "gb-safety-chip" not in html


def test_report_renders_pipeline_timeline_facts_and_events():
    stages = safety.stages(new_world(), _dry_history())
    html = safety.report_html(stages, safety.summary(stages))

    assert "Safety lab" in html
    assert "gb-panel" in html
    for kind in safety.PIPELINE:
        assert kind in html
    assert html.count("gb-safety-fact") == 4
    assert html.count("gb-safety-event") == len(stages)


def test_event_rows_do_not_repeat_the_verifiers_sentence():
    stages = safety.stages(new_world(), _dry_history())
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", safety.events_html(stages)))

    assert "1 action 1 action" not in text
    for stage in stages:
        assert text.count(stage["detail"]) == 1
    # The refused cell is still pointed at.
    assert "cell [3, 0]" in text


def test_report_is_self_contained():
    stages = safety.stages(new_world(), _dry_history())
    html = safety.report_html(stages, safety.summary(stages)).lower()

    assert "<script src" not in html
    assert "<link" not in html
    assert "@import" not in html
    assert "http://" not in html
    assert "https://" not in html


def test_report_styles_come_from_the_design_tokens():
    stages = safety.stages(new_world(), _dry_history())
    html = safety.report_html(stages, safety.summary(stages))

    for token in (C.ERROR, C.SUCCESS, C.WARNING, C.BORDER_SUBTLE, C.BG_SURFACE):
        assert token in html
    assert "gb-status-chip" in html


def test_meta_line_escapes_untrusted_text():
    html = safety.meta_html(
        "Scripted (dry mode)", "<script>alert('x')</script>", 2, 0.5
    )

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "0.50 s" in html


def test_meta_line_reports_missing_latency_as_unknown():
    assert "—" in safety.meta_html("Scripted (dry mode)", "go", 1, None)
