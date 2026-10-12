"""Tests for the GemmaBot Guard verification interface (frontend/console/guard.py).

The interface is the product: it decides whether a plan may execute, shows the
seven stages that answer came from, and — when a plan was refused — names the
exact failure and explains it in plain language.  These tests pin the two rules
that make it worth trusting:

* only deterministic facts are printed — every sentence is composed from the
  verifier's records, and nothing a model wrote can reach the markup, not even
  inside an action dict or a check's own detail string;
* nothing is approved that the verifier did not prove — an unproven check is
  never a tick, and a partly proven plan is refused.
"""
from __future__ import annotations

import json
import re

import pytest

from backend.guard import pipeline as guard_pipeline
from backend.guard.planner import CallablePlanner
from backend.verifier.harness import VERIFICATION_CHECKS, verify_plan
from frontend.components import theme
from frontend.console import guard
from frontend.panels import brain
from gemmabot.simulator import new_world

CSS = theme._css()
# Whitespace-normalised, for assertions about a rule written across lines.
SPACED = " ".join(CSS.split())

PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]

# The default world's wall column starts at x=3: walking straight into it is a
# real collision, verified by the real verifier.
HAZARD = [{"cmd": "forward", "steps": 7}]
# A world with no walls and the robot on the last column: one step further
# really would leave the grid, so the boundary check is the one that refuses it.
OPEN_WORLD = {"robot": [6, 0], "dir": "E", "goal": [6, 5], "walls": []}
OFF_GRID = [{"cmd": "forward", "steps": 2}]

CHECK_IDS = [check_id for check_id, _ in VERIFICATION_CHECKS]


def _checks(world: dict, actions: list) -> list[dict]:
    return verify_plan(world, actions)["checks"]


def _meta(**overrides) -> dict:
    """A display model for a run that verified, executed and was approved."""
    kwargs = dict(
        backend="API (Gemini)",
        model="gemma-4-26b-a4b-it",
        status="executing",
        attempts=1,
        max_tries=3,
        latency=1.25,
        plan_actions=PLAN,
        checks=_checks(new_world(), PLAN),
        steps=19,
        reached=True,
        executed=True,
        approved=True,
    )
    kwargs.update(overrides)
    return brain.brain_metadata(**kwargs)


SHORT_PLAN = [{"cmd": "turn_left"}]


def _refused(
    *,
    attempt: int = 1,
    attempts: int = 3,
    repaired: bool = False,
    final: list | None = None,
    **overrides,
) -> dict:
    """A display model for a run whose first attempt was refused.

    ``attempt`` is the attempt the refusal record names, ``attempts`` how many
    the loop made, and *final* the plan the last attempt proposed (the hazard
    again unless a test wants the run to have ended somewhere else).
    """
    kwargs = dict(
        backend="API (Gemini)",
        model="gemma-4-26b-a4b-it",
        status="executing" if repaired else "repairing",
        attempts=attempts,
        max_tries=3,
        plan_actions=PLAN if repaired else None,
        checks=_checks(new_world(), PLAN if repaired else (final or HAZARD)),
        executed=repaired,
        approved=repaired,
        reached=repaired,
        refusal={"attempt": attempt, "verification": verify_plan(new_world(), HAZARD)},
    )
    kwargs.update(overrides)
    return brain.brain_metadata(**kwargs)


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

def test_the_chain_is_the_seven_stages_in_the_order_the_product_names_them():
    assert [stage for stage, _ in guard.GUARD_STAGES] == [
        "plan", "structural", "boundary", "collision", "reachability",
        "simulation", "verdict",
    ]
    assert [label.upper() for _, label in guard.GUARD_STAGES] == [
        "PLAN RECEIVED", "STRUCTURAL CHECK", "BOUNDARY CHECK", "COLLISION CHECK",
        "REACHABILITY CHECK", "SIMULATION", "APPROVED / REJECTED",
    ]


def test_every_stage_that_judges_a_property_judges_a_real_harness_check():
    """A stage and a check record are one thing under two names, so the chain
    can never claim a check the verifier did not evaluate."""
    assert [check_id for _, check_id in guard.CHECK_STAGES] == CHECK_IDS
    assert guard.GUARD_STAGES[0][0] == "plan"
    assert guard.GUARD_STAGES[-1][0] == "verdict"
    for stage_id, check_id in guard.CHECK_STAGES:
        assert guard.CHECK_FOR_STAGE[stage_id] == check_id
        assert guard.STAGE_FOR_CHECK[check_id] == stage_id


def test_the_six_outcomes_are_the_four_checks_then_the_two_that_follow():
    # The four checks in the console's reading order, then the two that follow.
    assert [item for item, _ in guard.GUARD_ITEMS] == [
        "valid_actions", "no_collisions", "in_bounds", "goal_reachable",
        "simulation", "execution",
    ]
    assert [label.upper() for _, label in guard.GUARD_ITEMS] == [
        "VALID PLAN", "NO COLLISION", "WITHIN BOUNDS", "GOAL REACHABLE",
        "SIMULATION PASSED", "EXECUTION APPROVED",
    ]


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------

def test_a_proven_plan_is_approved_and_an_unproven_one_is_not():
    assert guard.verdict(_meta())["label"] == "APPROVED"
    assert guard.verdict(_meta(checks=None))["label"] == "NOT EVALUATED"
    assert guard.verdict(_meta(checks=None))["label"] == "NOT EVALUATED"


def test_approval_requires_all_four_checks_not_merely_an_absence_of_failures():
    """The verifier can return ``ok=False`` with only one check proven (a
    simulation fault).  Nothing may read that as an approval."""
    partial = [
        {"id": "valid_actions", "ok": True, "detail": "", "data": {}},
        {"id": "in_bounds", "ok": None, "detail": "", "data": {}},
        {"id": "no_collisions", "ok": None, "detail": "", "data": {}},
        {"id": "goal_reachable", "ok": None, "detail": "", "data": {}},
    ]
    decision = guard.verdict(_meta(checks=partial))

    assert decision["key"] == "rejected"
    assert "could not prove every check" in decision["detail"]


def test_a_refused_plan_names_the_check_that_refused_it():
    decision = guard.verdict(_meta(checks=_checks(new_world(), HAZARD)))

    assert decision["key"] == "rejected"
    assert decision["label"] == "REJECTED"
    assert decision["state"] == "error"
    assert "collision check" in decision["detail"]
    assert "collision at (3, 0)" in decision["detail"]


def test_a_fresh_session_is_not_evaluated_rather_than_failed():
    decision = guard.verdict(_meta(status="ready", attempts=0, checks=None,
                                   plan_actions=None, executed=None, approved=None))

    assert decision["key"] == "pending"
    assert decision["label"] == "NOT EVALUATED"
    assert decision["state"] == "neutral"


def test_an_in_flight_run_says_what_it_is_waiting_on():
    thinking = guard.verdict(_meta(status="thinking", attempts=0, checks=None,
                                   plan_actions=None, executed=None, approved=None, error="x"))
    repairing = guard.verdict(_meta(status="repairing", attempts=1, checks=None,
                                    plan_actions=None, executed=None, approved=None))
    over = guard.verdict(_meta(status="repairing", attempts=3, max_tries=3, checks=None,
                               plan_actions=None, executed=None, approved=None))

    assert "the model is still proposing" in thinking["detail"]
    assert "repairing" in repairing["detail"]
    assert "produced no plan to verify" in over["detail"]


def test_the_verdict_never_reads_as_an_approval_for_an_unexecuted_plan():
    """Verified but nothing simulated: APPROVED for execution, and the banner
    says sealed, not executed."""
    decision = guard.verdict(_meta(executed=None, approved=None))

    assert decision["key"] == "approved"
    assert "sealed for execution" in decision["detail"]


def test_only_the_three_verdict_keys_exist():
    keys = {
        guard.verdict(_meta())["key"],
        guard.verdict(_meta(checks=_checks(new_world(), HAZARD)))["key"],
        guard.verdict(_meta(status="ready", checks=None, plan_actions=None))["key"],
    }

    assert keys == {"approved", "rejected", "pending"}


# ---------------------------------------------------------------------------
# The stage chain
# ---------------------------------------------------------------------------

def test_a_fresh_session_shows_every_stage_idle():
    stages = guard.chain(_meta(status="ready", attempts=0, checks=None,
                               plan_actions=None, executed=None, approved=None))

    assert [stage["id"] for stage in stages] == [stage for stage, _ in guard.GUARD_STAGES]
    assert [stage["state"] for stage in stages] == ["idle"] * 7
    assert all(stage["state"] != "passed" for stage in stages)


def test_every_stage_of_an_approved_execution_passed():
    stages = {stage["id"]: stage for stage in guard.chain(_meta())}

    assert [stages[stage]["state"] for stage, _ in guard.CHECK_STAGES] == ["passed"] * 4
    assert stages["plan"]["state"] == "passed"
    assert "6 actions proposed" in stages["plan"]["detail"]
    assert stages["simulation"]["state"] == "passed"
    assert "19 simulator steps applied" in stages["simulation"]["detail"]
    assert stages["verdict"]["state"] == "passed"
    assert stages["verdict"]["detail"] == "the guard approved the plan for execution"


def test_a_boundary_failure_is_reported_exactly_where_the_verifier_found_it():
    stages = {stage["id"]: stage for stage in guard.chain(
        _meta(checks=_checks(OPEN_WORLD, OFF_GRID), executed=None, approved=None)
    )}

    assert stages["structural"]["state"] == "passed"
    assert stages["boundary"]["state"] == "failed"
    assert stages["boundary"]["detail"] == "Out of bounds at (8, 0)"
    # The verifier did reach the later checks, so the chain reports them as it
    # found them — no obstacle was entered, and the plan ends short of the goal.
    assert stages["collision"]["state"] == "passed"
    assert stages["reachability"]["state"] == "failed"
    assert stages["reachability"]["detail"] == "Goal not reached"
    assert stages["verdict"]["state"] == "failed"


def test_a_plan_stopped_at_the_structural_check_marks_the_rest_skipped():
    stages = {stage["id"]: stage for stage in guard.chain(
        _meta(checks=_checks(new_world(), [{"cmd": "jump"}]))
    )}

    assert stages["structural"]["state"] == "failed"
    assert stages["structural"]["detail"] == "Invalid action at step 1"
    assert stages["boundary"]["state"] == "skipped"
    assert stages["boundary"]["detail"] == "an earlier check failed"


def test_a_halted_execution_fails_the_simulation_stage():
    stages = {stage["id"]: stage for stage in guard.chain(
        _meta(executed=True, halted="blocked", reached=False)
    )}

    assert stages["simulation"]["state"] == "failed"
    assert "blocked" in stages["simulation"]["detail"]
    assert stages["verdict"]["state"] == "passed"   # the plan itself was approved


def test_a_refusal_fails_the_last_stage_and_says_nothing_executed():
    stages = {stage["id"]: stage for stage in guard.chain(
        _meta(checks=_checks(new_world(), HAZARD), executed=None, approved=None)
    )}

    assert stages["verdict"]["state"] == "failed"
    assert stages["verdict"]["detail"] == "the plan was refused — nothing executed"
    assert stages["simulation"]["state"] == "skipped"


# ---------------------------------------------------------------------------
# The six outcomes
# ---------------------------------------------------------------------------

def test_the_outcomes_are_the_six_in_order_with_their_marks():
    rows = guard.items(_meta())

    assert [row["id"] for row in rows] == [item for item, _ in guard.GUARD_ITEMS]
    assert [row["mark"] for row in rows] == ["✓"] * 6
    assert all(row["ok"] is True for row in rows)


def test_an_unproven_outcome_is_a_dash_and_never_a_tick():
    rows = guard.items(_meta(status="ready", checks=None, plan_actions=None,
                             executed=None, approved=None))

    assert [row["mark"] for row in rows] == ["–"] * 6
    assert all(row["ok"] is None for row in rows)
    html = guard.items_html(rows)
    assert html.count("data-ok='none'") == 6
    assert "✓" not in html


def test_the_two_outcomes_after_verification_claim_nothing_without_a_timeline():
    proposed = {row["id"]: row for row in guard.items(_meta(executed=None, approved=None))}

    assert proposed["simulation"]["ok"] is None
    assert proposed["execution"]["ok"] is None
    assert proposed["simulation"]["detail"] == "nothing was simulated"
    assert proposed["execution"]["detail"] == "no approved plan"


def test_a_failing_check_carries_its_own_verdict_into_the_outcome():
    rows = {row["id"]: row for row in guard.items(_meta(checks=_checks(new_world(), HAZARD)))}

    assert rows["valid_actions"]["mark"] == "✓"
    assert rows["no_collisions"]["mark"] == "✕"
    assert rows["no_collisions"]["detail"] == "Collision at (3, 0)"
    assert rows["goal_reachable"]["detail"] == "Goal not reached"


def test_a_halted_timeline_is_not_a_passing_simulation():
    rows = {row["id"]: row for row in guard.items(_meta(executed=True, halted="blocked"))}

    assert rows["simulation"]["ok"] is False
    assert "halted" in rows["simulation"]["detail"]


def test_a_refused_execution_gate_is_reported_not_hidden():
    rows = {row["id"]: row for row in guard.items(_meta(approved=False, executed=None))}

    assert rows["execution"]["ok"] is False
    assert "refused the plan" in rows["execution"]["detail"]


# ---------------------------------------------------------------------------
# The refusal: ERROR · ACTION · ATTEMPT · the repair
# ---------------------------------------------------------------------------

def test_the_refusal_names_the_error_the_action_and_the_attempt():
    refused = guard.rejection(_refused(attempts=1))

    assert refused["headline"] == "Collision at (3, 0)"
    assert refused["fact"] == "step 1 (FORWARD ×7) would enter the obstacle at (3, 0)"
    assert refused["action"] == "FORWARD ×7"
    assert refused["action_index"] == 1
    assert refused["cell"] == "(3, 0)"
    assert refused["check"] == "no_collisions"
    assert refused["check_label"] == "Collision check"
    assert refused["attempt"] == 1
    assert refused["attempt_label"] == "1 / 3"


def test_a_run_that_never_passed_explains_the_attempt_its_banner_judged():
    """The first refusal is a different plan that failed for a different reason,
    so a rejected run is explained by its last attempt — the one the banner and
    the stage chain above are reporting.  Naming the first refusal here would
    contradict the verdict two lines above it."""
    meta = _refused(attempts=3, final=SHORT_PLAN)
    refused = guard.rejection(meta)

    # The banner refuses the run at the reachability check…
    assert "reachability check" in guard.verdict(meta)["detail"]
    # …and the refusal block agrees, instead of reporting attempt 1's collision.
    assert refused["check"] == "goal_reachable"
    assert refused["headline"] == "Goal not reached"
    assert refused["attempt"] == 3
    assert refused["attempt_label"] == "3 / 3"
    assert refused["repair"]["key"] == "exhausted"

    # The repaired run tells the other story, and tells it the same way round:
    # APPROVED above, the refusal that was repaired in the block below.
    repaired = guard.rejection(_refused(repaired=True, attempts=2))
    assert repaired["check"] == "no_collisions"
    assert repaired["attempt"] == 1
    assert repaired["repair"]["key"] == "verified"


def test_a_repaired_plan_says_so_instead_of_claiming_a_live_repair():
    repaired = guard.rejection(_refused(repaired=True, attempts=2))

    assert repaired["repair"]["key"] == "verified"
    assert repaired["repair"]["label"] == "REPAIRED PLAN VERIFIED"
    assert "attempt 1 was refused" in repaired["repair"]["detail"]


def test_a_refused_plan_with_attempts_left_requests_a_repair():
    refused = guard.rejection(_refused(attempt=1, attempts=1))

    assert refused["attempt"] == 1

    assert refused["repair"]["key"] == "requested"
    assert refused["repair"]["label"] == "REPAIR REQUESTED"
    assert "no later attempt passed" in refused["repair"]["detail"]


def test_a_refused_plan_with_no_attempt_left_does_not_promise_one():
    exhausted = guard.rejection(_refused(attempts=3))

    assert exhausted["repair"]["key"] == "exhausted"
    assert exhausted["repair"]["label"] == "REPAIR EXHAUSTED"


def test_a_run_that_refused_nothing_has_no_refusal_to_show():
    assert guard.rejection(_meta()) is None
    assert guard.rejection(_meta(status="ready", checks=None, plan_actions=None,
                                 executed=None, approved=None)) is None


def test_a_refusal_without_its_own_records_still_reports_the_runs_failing_check():
    """A caller may hand the interface a result with no refusal record; the
    run's own checks explain it rather than nothing at all."""
    refused = guard.rejection(_meta(checks=_checks(new_world(), HAZARD), attempts=1,
                                    executed=None, approved=None, refusal=None))

    assert refused["headline"] == "Collision at (3, 0)"
    assert refused["attempt"] == 1


def test_a_verification_fault_is_reported_as_a_fault_not_as_a_collision():
    partial = [
        {"id": "valid_actions", "ok": True, "detail": "", "data": {}},
        {"id": "in_bounds", "ok": None, "detail": "", "data": {}},
        {"id": "no_collisions", "ok": None, "detail": "", "data": {}},
        {"id": "goal_reachable", "ok": None, "detail": "", "data": {}},
    ]
    refused = guard.rejection(_meta(checks=partial, attempts=2,
                                    executed=None, approved=None, refusal=None))

    assert refused["headline"] == "Verification faulted"
    assert "the simulator raised" in refused["fact"]


def test_the_refusal_html_shows_the_three_facts_and_the_repair():
    html = guard.rejection_html(guard.rejection(_refused(attempts=1)))

    for field, value in (
        ("error", "Collision at (3, 0)"),
        ("action", "FORWARD ×7"),
        ("attempt", "1 / 3"),
    ):
        assert f"data-field='{field}' data-value='{value}'" in html
    assert "✕ PLAN REJECTED" in html
    assert "→ REPAIR REQUESTED" in html
    assert "data-repair='requested'" in html


# ---------------------------------------------------------------------------
# "Why was this rejected?"
# ---------------------------------------------------------------------------

def test_the_why_fold_explains_the_deterministic_result_in_plain_language():
    fold = guard.why(_refused(attempts=1))
    text = " ".join(fold["lines"])

    assert fold["title"] == "Why was this rejected?"
    assert text.startswith("Attempt 1 of 3 was refused at the collision check:")
    assert "step 1 (FORWARD ×7) would enter the obstacle at (3, 0)" in text
    assert "structural and boundary checks passed first" in text
    assert "never reached the simulator" in text
    assert "no later attempt passed" in text


def test_the_why_fold_reports_a_repair_that_worked():
    text = " ".join(guard.why(_refused(repaired=True, attempts=2))["lines"])

    assert text.startswith("Attempt 1 of 3 was refused at the collision check:")
    assert "repair was requested" in text
    assert "the guard approved it" in text


def test_the_why_fold_says_when_the_loop_had_no_attempt_left():
    text = " ".join(guard.why(_refused(attempts=3))["lines"])

    assert text.startswith("Attempt 3 of 3 was refused at the collision check:")
    assert "No attempt remained, so nothing was approved." in text


def test_the_why_fold_is_a_fold_and_not_a_wall_of_text():
    html = guard.why_html(guard.why(_refused()))

    assert "<details class='gb-guard-why'>" in html
    assert "<summary class='gb-guard-why-summary'>Why was this rejected?</summary>" in html
    assert html.count("gb-guard-why-line") == 4


def test_nothing_refused_means_no_why_fold():
    assert guard.why(_meta()) is None


# ---------------------------------------------------------------------------
# Only deterministic facts — never a transcript
# ---------------------------------------------------------------------------

SECRET = "SECRET-divert-around-the-wall-because-it-is-closer"

# The model put its reasoning inside the action dict, and the plan is invalid so
# the harness reports it with a repr.  Neither may reach the interface.
HOSTILE_ACTION = [{"cmd": "warp", "steps": 2, "thought": SECRET, "reply": SECRET}]


def test_a_reasoning_key_smuggled_into_an_action_never_reaches_the_panel():
    meta = _meta(checks=_checks(new_world(), HOSTILE_ACTION), executed=None, approved=None)
    html = brain.brain_panel_html(meta)

    assert SECRET not in html
    assert "thought" not in html.lower()
    assert "'cmd'" not in html          # no action dict is printed as a repr
    assert "warp" in html.lower() or "invalid action" in html.lower()


def test_a_check_detail_can_never_reach_the_interface():
    """The verifier's own detail strings can assemble an action repr, so the
    interface composes its text from ``data`` and never prints them."""
    checks = _checks(new_world(), HOSTILE_ACTION)
    detail = next(entry["detail"] for entry in checks if entry["id"] == "valid_actions")
    assert SECRET in detail, "the fixture must really carry the repr"

    html = brain.brain_panel_html(_meta(checks=checks, executed=None, approved=None))

    assert SECRET not in html
    assert detail not in html
    assert "not evaluated —" not in html


def test_an_action_is_rendered_from_the_two_fields_the_simulator_reads():
    assert guard.action_text({"cmd": "forward", "steps": 7, "thought": SECRET}) == "FORWARD ×7"
    assert guard.action_text({"cmd": "forward"}) == "FORWARD"
    assert guard.action_text({"cmd": "turn_left", "note": SECRET}) == "TURN LEFT"
    # A step count the simulator cannot read falls back to one step, exactly as
    # the execution timeline labels that action.
    assert guard.action_text({"cmd": "forward", "steps": "many"}) == "FORWARD"
    assert guard.action_text({"steps": 3}) == "?"
    assert guard.action_text(None) == "?"


def test_untrusted_metadata_is_escaped_like_everything_else():
    html = brain.brain_panel_html(_meta(
        backend="<script>alert('x')</script>",
        model="<img src=x onerror=alert(1)>",
    ))

    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html


def test_the_interface_is_self_contained():
    html = brain.brain_panel_html(_refused(repaired=True, attempts=2))

    assert "<script" not in html.lower()
    assert "<link" not in html.lower()
    assert "@import" not in html.lower()
    assert "http://" not in html.lower()
    assert "https://" not in html.lower()


def test_the_interface_prints_a_cell_only_when_the_verifier_recorded_one():
    assert guard.cell_text([3, 0]) == "(3, 0)"
    assert guard.cell_text((3, 0)) == "(3, 0)"
    assert guard.cell_text([3]) is None
    assert guard.cell_text("(3, 0)") is None
    assert guard.cell_text([True, False]) is None
    assert guard.cell_text(None) is None


# ---------------------------------------------------------------------------
# The stylesheet paints it
# ---------------------------------------------------------------------------

GUARD_CLASSES = (
    "gb-guard-head", "gb-guard-purpose", "gb-guard-verdict",
    "gb-guard-verdict-label", "gb-guard-verdict-detail", "gb-guard-chain",
    "gb-guard-stage", "gb-guard-mark", "gb-guard-stage-label",
    "gb-guard-stage-detail", "gb-guard-arrow", "gb-guard-checks",
    "gb-guard-check", "gb-guard-check-label", "gb-guard-check-detail",
    "gb-guard-reject", "gb-guard-reject-head", "gb-guard-reject-fact",
    "gb-guard-reject-row", "gb-guard-reject-label", "gb-guard-reject-value",
    "gb-guard-repair", "gb-guard-repair-detail", "gb-guard-why",
    "gb-guard-why-summary", "gb-guard-why-body", "gb-guard-why-line",
    "gb-guard-meta", "gb-guard-meta-item", "gb-guard-meta-value",
)


def test_every_class_the_interface_emits_has_a_rule():
    for name in GUARD_CLASSES:
        assert f".{name}" in CSS, f"{name} is emitted by the guard but never styled"


@pytest.mark.parametrize("state", ["passed", "failed", "running", "skipped", "idle"])
def test_every_stage_state_has_a_rule(state):
    assert f'.gb-guard-stage[data-state="{state}"]' in SPACED or state == "idle"


@pytest.mark.parametrize("verdict_key", ["approved", "rejected"])
def test_every_verdict_has_a_rule(verdict_key):
    assert f'.gb-guard-verdict[data-verdict="{verdict_key}"]' in SPACED


@pytest.mark.parametrize("ok", ["true", "false", "none"])
def test_every_outcome_verdict_has_a_rule(ok):
    assert f'.gb-guard-check[data-ok="{ok}"]' in SPACED


def test_the_state_colours_are_the_design_tokens():
    approved = CSS.split('.gb-guard-verdict[data-verdict="approved"] {')[1].split("}")[0]
    rejected = CSS.split('.gb-guard-verdict[data-verdict="rejected"] {')[1].split("}")[0]
    passed = CSS.split('.gb-guard-stage[data-state="passed"] .gb-guard-mark,')[1].split("}")[0]
    failed = CSS.split('.gb-guard-stage[data-state="failed"] .gb-guard-mark,')[1].split("}")[0]

    from frontend.components import colors as C

    assert C.SUCCESS_BG in approved and C.SUCCESS_BORDER in approved
    assert C.ERROR_BG in rejected and C.ERROR_BORDER in rejected
    assert C.SUCCESS in passed
    assert C.ERROR in failed


def test_the_interface_carries_no_colour_of_its_own():
    """Every colour comes from the stylesheet, so one state has one rule.

    The panel wrapper (``components.panel``) and the status chip style
    themselves from the tokens, as every other panel does; the guard's own
    blocks carry classes and data attributes and no style at all.
    """
    refused = _refused(repaired=True, attempts=2)
    html = (
        guard.verdict_html(guard.verdict(refused))
        + guard.chain_html(guard.chain(refused))
        + guard.items_html(guard.items(refused))
        + guard.rejection_html(guard.rejection(refused))
        + guard.why_html(guard.why(refused))
        + guard.metadata_html(refused)
    )

    assert "style=" not in html
    assert not re.search(r"color:\s*#", html)


# ---------------------------------------------------------------------------
# The model is the quietest thing in the panel
# ---------------------------------------------------------------------------

def test_the_banner_comes_before_the_model_name_and_the_name_is_muted():
    html = brain.brain_panel_html(_meta())

    assert html.index("gb-guard-verdict") < html.index("gb-guard-chain")
    assert html.index("gb-guard-chain") < html.index("data-field='model'")
    assert html.index("gb-guard-checks") < html.index("data-field='model'")
    assert "gb-guard-meta-value'>Gemma 4<" in html


# ---------------------------------------------------------------------------
# End to end: the guard's own refusal drives the interface
# ---------------------------------------------------------------------------

def _scripted_planner() -> CallablePlanner:
    """A real guard loop: the naive plan first, the corrected route second."""
    state = {"calls": 0}

    def ask(instruction: str, world: dict) -> str:
        state["calls"] += 1
        plan = PLAN if state["calls"] >= 2 else HAZARD
        return json.dumps({"thought": SECRET, "actions": plan})

    return CallablePlanner("scripted", ask)


def test_a_real_refusal_and_repair_reads_through_the_interface(monkeypatch):
    """One real loop run: attempt 1 refused, attempt 2 verified.  The panel
    shows the refusal, the repair that fixed it, and the approval."""
    world = new_world()
    result = guard_pipeline.plan("go to the goal", world, _scripted_planner(), max_tries=3)
    refusal = guard_pipeline.first_refusal(world, result["history"])
    assert result["attempts"] == 2 and result["actions"] == PLAN
    assert refusal is not None and refusal["attempt"] == 1

    meta = brain.run_metadata(
        backend_label="Scripted (dry mode)",
        model="gemma-4-26b-a4b-it",
        verification=result["verification"],
        actions=result["actions"],
        attempts=result["attempts"],
        max_tries=3,
        latency=result["latency"],
        steps=19,
        reached=True,
        approved=True,
        executed=True,
        refusal=refusal,
    )
    html = brain.brain_panel_html(meta)

    assert "APPROVED" in html
    assert "data-field='error' data-value='Collision at (3, 0)'" in html
    assert "data-field='attempt' data-value='1 / 3'" in html
    assert "REPAIRED PLAN VERIFIED" in html
    assert "data-guard-stage='collision' data-state='passed'" in html
    assert "data-guard-stage='verdict' data-state='passed'" in html
    # The model's reasoning travelled with the plan and still did not arrive.
    assert SECRET not in html
