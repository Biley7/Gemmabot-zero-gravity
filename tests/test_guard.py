"""The GemmaBot Guard — contracts, planner interface, approval, execution.

Owner: BACKEND.  The safety rule these tests enforce:

    the execution layer must not trust the UI — it requires an approved plan.

``execute()`` accepts only an ``ApprovedPlan`` sealed by ``approve()``,
re-verifies the actions and re-computes the approval digest first, so a UI bug
that mutates a plan, a world or an approval object cannot reach the simulator.
No AI and no network: planners are scripted callables.
"""
import copy
import dataclasses
import json

import pytest

from backend.guard import (
    ApprovedPlan,
    CallablePlanner,
    FallbackPlanner,
    approve,
    approval_digest,
    build_planner,
    canonical_actions,
    canonical_world,
    execute,
    plan,
    register_planner,
    simulate,
    verify_run,
)
from gemmabot.simulator import new_world

# A tiny open world: 3 steps east and the robot is on the goal.
OPEN_WORLD = {"robot": [0, 0], "dir": "E", "goal": [3, 0], "walls": []}
DIRECT = [{"cmd": "forward", "steps": 3}]
SPLIT = [{"cmd": "forward", "steps": 1}, {"cmd": "forward", "steps": 2}]
# In the default world a 7-step walk east is refused by the wall column at x=3.
HAZARD = [{"cmd": "forward", "steps": 7}]


def _reply(actions):
    return json.dumps({"thought": "scripted", "actions": actions})


# ---------------------------------------------------------------------------
# Canonical representations
# ---------------------------------------------------------------------------

def test_canonical_world_normalizes_coordinates_and_copies():
    world = {"robot": (0, 0), "dir": "E", "goal": (3, 0), "walls": [(1, 1)],
             "unrelated": "dropped"}
    canonical = canonical_world(world)
    assert canonical == {"robot": [0, 0], "dir": "E", "goal": [3, 0],
                         "walls": [[1, 1]]}
    world["robot"] = [9, 9]
    assert canonical["robot"] == [0, 0], "canonical_world must deep-copy"


@pytest.mark.parametrize("broken", [
    None,
    "world",
    {"robot": [0, 0], "dir": "E", "goal": [1, 1]},              # missing walls
    {"robot": [0, 0], "dir": "X", "goal": [1, 1], "walls": []},  # bad heading
    {"robot": [0], "dir": "E", "goal": [1, 1], "walls": []},     # bad robot cell
    {"robot": [0, 0], "dir": "E", "goal": [1, 1], "walls": "no"},
])
def test_canonical_world_rejects_structural_errors(broken):
    with pytest.raises(ValueError):
        canonical_world(broken)


def test_canonical_actions_requires_action_dicts_with_a_command():
    assert canonical_actions(DIRECT) == DIRECT
    assert canonical_actions([], allow_empty=True) == []
    for broken in ([], ["forward"], [{"steps": 2}], [{"cmd": ""}], "forward"):
        with pytest.raises(ValueError):
            canonical_actions(broken)


def test_approval_digest_is_stable_over_equal_values():
    first = approval_digest(canonical_world(OPEN_WORLD), DIRECT)
    second = approval_digest(canonical_world(copy.deepcopy(OPEN_WORLD)),
                             copy.deepcopy(DIRECT))
    assert first == second
    assert first != approval_digest(canonical_world(OPEN_WORLD), SPLIT)
    assert first != approval_digest(canonical_world(new_world()), DIRECT)


# ---------------------------------------------------------------------------
# Planner interface — Gemma is one implementation, not the assumption
# ---------------------------------------------------------------------------

def test_callable_planner_adapts_a_plain_function():
    planner = CallablePlanner("mine", lambda instruction, world: "reply")
    assert planner.propose("go", OPEN_WORLD) == "reply"
    assert planner.name == "mine"


def test_fallback_planner_records_which_planner_answered():
    fallback = CallablePlanner("ollama", lambda instruction, world: "local reply")

    def broken(instruction, world):
        raise RuntimeError("api down")

    auto = FallbackPlanner(CallablePlanner("api", broken), fallback)
    assert auto.name == "auto"
    assert auto.propose("go", OPEN_WORLD) == "local reply"
    assert auto.used == "ollama", "the UI must be able to report the real backend"

    healthy = FallbackPlanner(
        CallablePlanner("api", lambda i, w: "cloud reply"), fallback
    )
    assert healthy.propose("go", OPEN_WORLD) == "cloud reply"
    assert healthy.used == "api"


def test_the_registry_resolves_names_and_rejects_unknown_ones():
    assert build_planner("api", api_fn=lambda i, w: "A").propose("go", OPEN_WORLD) == "A"
    assert build_planner("local", local_fn=lambda i, w: "L").propose("go", OPEN_WORLD) == "L"

    register_planner("unit-test-model", lambda: CallablePlanner("unit-test-model", lambda i, w: "U"))
    assert build_planner("unit-test-model").propose("go", OPEN_WORLD) == "U"

    with pytest.raises(ValueError, match="unknown planner"):
        build_planner("no-such-model")


# ---------------------------------------------------------------------------
# The guard loop: propose -> parse -> verify -> repair -> approve
# ---------------------------------------------------------------------------

def test_plan_returns_an_approved_plan_when_verification_passes():
    planner = CallablePlanner("test", lambda instruction, world: _reply(DIRECT))
    result = plan("go to the goal", OPEN_WORLD, planner, max_tries=1)

    assert result["backend"] == "test"
    assert result["actions"] == DIRECT
    assert result["attempts"] == 1
    assert result["error"] is None
    assert result["verification"]["ok"] is True
    approved = result["approved"]
    assert isinstance(approved, ApprovedPlan)
    assert approved.action_list() == DIRECT
    assert approved.verification["ok"] is True


def test_plan_never_approves_a_refused_plan():
    planner = CallablePlanner("test", lambda instruction, world: _reply(HAZARD))
    result = plan("go to the goal", new_world(), planner, max_tries=2)

    assert result["actions"] is None
    assert result["approved"] is None
    assert result["attempts"] == 2
    assert result["verification"]["ok"] is False
    assert result["error"], "a failed run must carry the reason it failed"


def test_plan_does_not_mutate_the_world_it_plans_against():
    world = new_world()
    before = json.dumps(world, sort_keys=True)
    planner = CallablePlanner("test", lambda instruction, w: _reply(DIRECT))
    plan("go", world, planner, max_tries=1)
    assert json.dumps(world, sort_keys=True) == before


def test_verify_run_reports_the_last_attempted_plan():
    history = [{"attempt": 1, "actions": HAZARD, "ok": False, "feedback": "blocked"}]
    report = verify_run(new_world(), None, history)
    assert report["ok"] is False
    assert report["actions"] == HAZARD
    assert verify_run(new_world(), None, []) is None


# ---------------------------------------------------------------------------
# Approval is sealed to the world and the actions it verified
# ---------------------------------------------------------------------------

def test_approve_seals_a_snapshot_and_does_not_alias_the_caller():
    world = copy.deepcopy(OPEN_WORLD)
    approved = approve(world, DIRECT, instruction="go", planner="test")
    assert isinstance(approved, ApprovedPlan)

    world["robot"][0] = 99
    assert approved.world["robot"] == [0, 0], "approval must bind its own snapshot"
    assert approved.approval_id == approved.digest()
    assert approved.action_list() == DIRECT


def test_approve_refuses_a_plan_that_fails_verification():
    assert approve(new_world(), HAZARD) is None
    assert approve(OPEN_WORLD, []) is None
    assert approve(OPEN_WORLD, None) is None
    assert approve({"robot": [0, 0]}, DIRECT) is None  # not a world


# ---------------------------------------------------------------------------
# Execution requires an approved plan — a UI bug cannot bypass validation
# ---------------------------------------------------------------------------

def test_execute_refuses_anything_that_is_not_an_approved_plan():
    with pytest.raises(TypeError):
        execute({"world": OPEN_WORLD, "actions": DIRECT})
    with pytest.raises(TypeError):
        execute(None)


def test_execute_runs_an_approved_plan_and_reaches_the_goal():
    approved = approve(OPEN_WORLD, DIRECT, instruction="go", planner="test")
    outcome = execute(approved)

    assert outcome["ok"] is True
    assert outcome["reached"] is True
    assert outcome["verified"] is True, "an approved execution is marked verified"
    assert outcome["approval_id"] == approved.approval_id
    assert outcome["world"]["robot"] == [3, 0]
    assert len(outcome["log"]) == 1


def test_execute_refuses_a_tampered_approval_without_stepping():
    approved = approve(OPEN_WORLD, DIRECT, instruction="go", planner="test")
    # Same world, a different plan that also verifies — but not the one sealed.
    tampered = dataclasses.replace(approved, actions=tuple(canonical_actions(SPLIT)))

    outcome = execute(tampered)
    assert outcome["ok"] is False
    assert outcome["verified"] is False
    assert outcome["log"] == [], "a refused plan must not step the simulator"
    assert "digest" in outcome["refused"]


def test_execute_refuses_a_hand_built_approval():
    """Even a forged object with ok=True cannot execute a hazardous plan."""
    forged = ApprovedPlan(
        instruction="go",
        planner="ui",
        world=canonical_world(new_world()),
        actions=tuple(canonical_actions(HAZARD)),
        verification={"ok": True, "reason": "ok", "checks": []},
        approval_id="forged",
    )
    outcome = execute(forged)
    assert outcome["ok"] is False
    assert outcome["verified"] is False
    assert outcome["log"] == []
    assert "verification failed" in outcome["refused"]
    assert outcome["world"]["robot"] == [0, 0], "the world did not move"


# ---------------------------------------------------------------------------
# Simulation is the deliberate non-execution path
# ---------------------------------------------------------------------------

def test_simulate_runs_any_plan_but_never_claims_verification():
    outcome = simulate(new_world(), HAZARD)
    assert outcome["ok"] is False, "the simulator refused the wall"
    assert outcome["verified"] is False
    assert outcome["approval_id"] is None
    assert outcome["log"][0]["message"].startswith("blocked")


def test_simulate_can_replay_an_approved_plan_without_marking_it_verified():
    approved = approve(OPEN_WORLD, DIRECT, instruction="go", planner="test")
    outcome = simulate(approved.world, approved.action_list())
    assert outcome["ok"] is True
    assert outcome["reached"] is True
    assert outcome["verified"] is False, "replay is a demonstration, not an execution"
    assert outcome["approval_id"] is None
