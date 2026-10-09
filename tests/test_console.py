"""Tests for the console shell, the pipeline, the timeline and the status strip.

These blocks are the product's claim made visible: AI proposes → GemmaBot
verifies → the robot executes.  The tests pin that every stage state, verdict
and row comes from a real artifact — and that a stage nothing produced is never
drawn as a pass.
"""
import json

from backend.verifier.harness import VERIFICATION_CHECKS, verify_plan
from frontend.components import colors as C
from frontend.console import pipeline as console
from frontend.console import shell as console_shell
from frontend.simulation import player as playback
from gemmabot.simulator import new_world

# A plan that really solves the default world (verified in harness tests).
PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]

CHECK_IDS = [check_id for check_id, _ in VERIFICATION_CHECKS]


def _states(stages: list[dict]) -> dict[str, str]:
    return {stage["id"]: stage["state"] for stage in stages}


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

def test_the_console_speaks_the_status_vocabulary_the_product_names():
    assert console_shell.PRODUCT == "GemmaBot"
    assert console_shell.TAGLINE == "AI Robotics Validation Platform"
    assert set(console_shell.STATUSES) == {
        "ready", "thinking", "verifying", "executing", "complete", "failed",
    }
    assert [stage[0] for stage in console.PIPELINE_STAGES] == [
        "input", "plan", "verify", "simulate", "approve", "execute",
    ]
    assert "idle" in console.STAGE_STATES and "skipped" in console.STAGE_STATES


def test_the_status_is_derived_from_what_really_happened():
    assert console_shell.console_status()[0] == "ready"
    assert console_shell.console_status(phase="plan")[0] == "thinking"
    assert console_shell.console_status(phase="verify")[0] == "verifying"
    assert console_shell.console_status(phase="execute")[0] == "executing"
    assert console_shell.console_status(executed=True)[0] == "complete"
    assert console_shell.console_status(executed=False)[0] == "failed"
    assert console_shell.console_status(verified=True)[0] == "complete"
    assert console_shell.console_status(verified=False)[0] == "failed"


def test_a_running_phase_outranks_a_stale_outcome():
    """While the loop is working, the console says what it is doing now."""
    assert console_shell.console_status(
        phase="verify", verified=False, executed=False
    )[0] == "verifying"


def test_every_loop_state_maps_to_one_console_phase():
    assert console_shell.phase_for("thinking") == "plan"
    assert console_shell.phase_for("repairing") == "verify"
    assert console_shell.phase_for("executing") == "execute"
    assert console_shell.phase_for("ready") is None


# ---------------------------------------------------------------------------
# The header and the viewport
# ---------------------------------------------------------------------------

def test_the_header_names_the_product_and_the_configured_model():
    html = console_shell.header_html(
        backend_label="API (Gemini)", model="gemma-4-26b-a4b-it"
    )

    assert "gb-wordmark'>GemmaBot<" in html
    assert console_shell.TAGLINE in html
    assert "data-backend='API (Gemini)'" in html
    assert "gemma-4-26b-a4b-it" in html


def test_the_status_bar_carries_the_verdict_that_was_derived():
    html = console_shell.status_bar_html(
        key="executing", activity="the plan is stepping", meta="attempt 2/3"
    )

    assert "data-status='executing'" in html
    assert "EXECUTING" in html
    assert "the plan is stepping" in html
    assert "attempt 2/3" in html


def test_an_unknown_status_falls_back_to_ready_rather_than_claiming_progress():
    html = console_shell.status_bar_html(key="daydreaming")

    assert "data-status='ready'" in html
    assert "READY" in html


def test_the_viewport_frames_the_drawing_with_its_own_readout():
    html = console_shell.viewport_html(
        "<div>board</div>", title="Simulator", meta="7 obstacles", foot="legend"
    )

    assert "gb-viewport" in html
    assert "Simulator" in html
    assert "7 obstacles" in html
    assert "<div>board</div>" in html
    assert "legend" in html


def test_a_zone_bar_is_a_label_and_a_readout():
    html = console_shell.zone_bar_html("Pipeline", "input → execute")

    assert "gb-zone-title'>Pipeline<" in html
    assert "input → execute" in html


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def test_a_session_that_has_run_nothing_is_idle_at_every_stage():
    stages = console.pipeline_stages()
    states = _states(stages)

    assert states == {stage[0]: "idle" for stage in console.PIPELINE_STAGES}
    assert set(states.values()) == {"idle"}


def test_an_instruction_alone_fills_only_the_input_stage():
    states = _states(console.pipeline_stages(instruction="go to the goal"))

    assert states["input"] == "passed"
    assert states["plan"] == "failed" or states["plan"] == "idle"


def test_a_verified_and_executed_run_passes_every_stage():
    world = new_world()
    verification = verify_plan(world, PLAN)
    timeline = playback.build_timeline(world, PLAN)

    stages = console.pipeline_stages(
        instruction="go to the goal",
        actions=PLAN,
        verification=verification,
        approved=True,
        timeline=timeline,
    )

    assert _states(stages) == {
        "input": "passed", "plan": "passed", "verify": "passed",
        "simulate": "passed", "approve": "passed", "execute": "passed",
    }
    details = {stage["id"]: stage["detail"] for stage in stages}
    assert details["plan"] == "6 actions proposed"
    assert details["execute"] == "the robot reached the goal"
    assert "steps" in details["simulate"]


def test_a_refused_plan_fails_verification_and_skips_what_follows():
    world = new_world()
    refused = [{"cmd": "forward", "steps": 7}]
    verification = verify_plan(world, refused)

    stages = console.pipeline_stages(
        instruction="go",
        actions=refused,
        verification=verification,
        approved=False,
        timeline=None,
        error="blocked at [3, 0]",
    )
    states = _states(stages)

    assert verification["ok"] is False
    assert states["plan"] == "passed"
    assert states["verify"] == "failed"
    assert states["simulate"] == "skipped"
    assert states["approve"] == "skipped"
    assert states["execute"] == "skipped"


def test_a_run_that_produced_no_plan_fails_at_the_plan_stage():
    stages = console.pipeline_stages(
        instruction="go",
        actions=None,
        verification=None,
        approved=False,
        timeline=None,
        error="could not parse reply as JSON",
    )
    states = _states(stages)

    assert states["plan"] == "failed"
    assert states["verify"] == "skipped"
    assert states["execute"] == "skipped"
    assert "could not parse reply as JSON" in stages[1]["detail"]


def test_the_live_phase_marks_the_stage_that_is_running():
    planning = _states(console.pipeline_stages(instruction="go", phase="plan"))
    verifying = _states(console.pipeline_stages(instruction="go", phase="verify"))
    executing = _states(console.pipeline_stages(
        instruction="go", actions=PLAN, verification=verify_plan(new_world(), PLAN),
        approved=True, phase="execute",
    ))

    assert planning["plan"] == "running"
    assert verifying["verify"] == "running"
    assert executing["execute"] == "running"


def test_a_verified_plan_the_gate_refused_fails_the_approve_stage():
    world = new_world()
    stages = console.pipeline_stages(
        instruction="go",
        actions=PLAN,
        verification=verify_plan(world, PLAN),
        approved=False,
        timeline=None,
    )

    assert _states(stages)["approve"] == "failed"


def test_the_pipeline_html_carries_the_state_of_every_stage():
    stages = console.pipeline_stages(instruction="go", phase="plan")
    html = console.pipeline_html(stages)

    for stage_id, _ in console.PIPELINE_STAGES:
        assert f"data-pipe-stage='{stage_id}'" in html
    assert html.count("data-pipe-stage=") == len(console.PIPELINE_STAGES)
    assert "data-state='running'" in html
    assert "INPUT" in html


def test_the_pipeline_escapes_what_the_model_wrote():
    stages = console.pipeline_stages(instruction="<script>alert('x')</script>")
    html = console.pipeline_html(stages)

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# Status strip
# ---------------------------------------------------------------------------

def test_the_strip_is_the_four_harness_checks_in_the_console_order():
    rows = console.status_checks(verify_plan(new_world(), PLAN))

    # The console's own order (the order the product names them in) …
    assert [row["id"] for row in rows] == [
        "valid_actions", "no_collisions", "in_bounds", "goal_reachable",
    ]
    # … over exactly the harness's checks, so a row and a record are one check.
    assert sorted(row["id"] for row in rows) == sorted(CHECK_IDS)
    assert [row["label"] for row in rows] == [
        "Plan valid", "No collision", "In bounds", "Goal reachable",
    ]
    assert all(row["ok"] is True for row in rows)


def test_an_unproven_check_is_a_dash_never_a_tick():
    rows = console.status_checks(None)
    html = console.status_strip_html(rows)

    assert [row["mark"] for row in rows] == ["–"] * 4
    assert html.count("data-verdict='none'") == 4
    assert "✓" not in html


def test_a_failing_check_keeps_its_own_verdict_and_detail():
    world = new_world()
    blocked = [{"cmd": "forward", "steps": 7}]
    rows = console.status_checks(verify_plan(world, blocked))
    by_id = {row["id"]: row for row in rows}

    assert by_id["no_collisions"]["ok"] is False
    assert "[3, 0]" in by_id["no_collisions"]["detail"]
    assert "✗" in console.status_strip_html(rows)


def test_the_strip_does_not_borrow_the_panels_check_attribute():
    """The vision strip and the guard console both use ``data-check``: the
    console's own strip must not collide with either."""
    html = console.status_strip_html(console.status_checks(None))

    assert "data-status-check=" in html
    assert "data-check=" not in html
    assert "data-ok=" not in html


# ---------------------------------------------------------------------------
# Action timeline
# ---------------------------------------------------------------------------

def test_the_timeline_lists_the_actions_with_the_simulators_messages():
    world = new_world()
    timeline = playback.build_timeline(world, PLAN)
    rows = console.timeline_rows(PLAN, timeline=timeline)

    assert [row["index"] for row in rows] == [1, 2, 3, 4, 5, 6]
    assert rows[0]["label"] == "turn right"
    assert rows[1]["label"] == "forward ×7"
    # Every message is the simulator's own, not a label this module made up.
    assert [row["message"] for row in rows] == [
        step["message"] for step in timeline["steps"]
    ]
    assert all(row["state"] == "done" for row in rows)
    assert [row["current"] for row in rows].count(True) == 1
    assert rows[-1]["current"] is True


def test_a_halted_execution_marks_the_blocked_action_and_leaves_the_rest_pending():
    world = new_world()
    hazard = [{"cmd": "forward", "steps": 7}, {"cmd": "turn_left"}]
    timeline = playback.build_timeline(world, hazard)
    rows = console.timeline_rows(hazard, timeline=timeline)

    assert rows[0]["state"] == "blocked"
    assert rows[0]["current"] is True
    assert rows[1]["state"] == "pending"
    assert rows[1]["current"] is False
    html = console.timeline_html(rows)
    assert "data-state='blocked'" in html
    assert "data-current='true'" in html


def test_a_plan_that_never_executed_is_all_pending():
    rows = console.timeline_rows(PLAN)

    assert [row["state"] for row in rows] == ["pending"] * len(PLAN)
    assert not any(row["current"] for row in rows)


def test_an_empty_plan_is_an_empty_timeline_not_a_blank():
    html = console.timeline_html(console.timeline_rows(None))

    assert "gb-tl" in html
    assert "no actions" in html


def test_the_timeline_html_numbers_and_escapes_every_row():
    rows = console.timeline_rows([{"cmd": "forward", "steps": 2}])
    html = console.timeline_html(rows)

    assert "data-action='1'" in html
    assert ">01<" in html
    assert "FORWARD ×2" in html
    assert html.count("data-action=") == 1


def test_the_timeline_escapes_a_model_supplied_command():
    rows = console.timeline_rows([{"cmd": "<img src=x onerror=1>"}])
    html = console.timeline_html(rows)

    assert "<img" not in html
    assert "&lt;img" in html


# ---------------------------------------------------------------------------
# Tokens, not literals; no external assets
# ---------------------------------------------------------------------------

def test_every_block_uses_design_tokens():
    html = (
        console_shell.header_html(backend_label="API (Gemini)", model="gemma-4-26b-a4b-it")
        + console_shell.status_bar_html(key="complete", activity="done")
        + console.pipeline_html(console.pipeline_stages(instruction="go"))
        + console.timeline_html(console.timeline_rows(PLAN))
        + console.status_strip_html(console.status_checks(None))
    )

    assert "http://" not in html.lower()
    assert "https://" not in html.lower()
    assert "<script" not in html.lower()
    assert "gb-console-chip" in html
    assert "gb-pipe-stage" in html
    assert "gb-tl-row" in html
    assert "gb-status-item" in html
    assert C.SUCCESS in html or "data-verdict" in html


def test_the_timeline_row_count_is_the_plan_size():
    rows = console.timeline_rows(json.loads(json.dumps(PLAN)))
    html = console.timeline_html(rows)

    assert f"data-actions='{len(PLAN)}'" in html
