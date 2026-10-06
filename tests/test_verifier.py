"""Tests for the verifier: dry_run's verdict and the structured checks.

verify_plan() is what the Gemma Brain panel displays, so these tests pin two
things: each check reports a fact the simulation really observed, and the
panel's verdict can never disagree with the verdict that gates the repair loop.
"""
import copy

from backend.verifier.harness import (
    MAX_PLAN_STEPS,
    VERIFICATION_CHECKS,
    dry_run,
    verify_plan,
)
from gemmabot.simulator import new_world

# Solves new_world() ([0,0] E → goal [6,5]) without touching the wall column
# at x=3 or the cluster at x=5, y=4-6.  Verified by dry_run.
GOOD_PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]

# Walks straight into the wall at [3, 0]; the robot stops on [2, 0].
WALL_PLAN = [{"cmd": "forward", "steps": 5}]

# turn_left faces N from [0, 0]; one step aims at [0, -1], off the grid.
OFF_GRID_PLAN = [{"cmd": "turn_left"}, {"cmd": "forward", "steps": 1}]

CHECK_IDS = [check_id for check_id, _ in VERIFICATION_CHECKS]
CHECK_LABELS = [label for _, label in VERIFICATION_CHECKS]


def _checks(result) -> dict:
    """The result's checks keyed by id, for compact assertions."""
    return {entry["id"]: entry for entry in result["checks"]}


def _verdict(result) -> list:
    return [entry["ok"] for entry in result["checks"]]


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_verify_plan_reports_the_four_checks_in_a_stable_order():
    result = verify_plan(new_world(), GOOD_PLAN)

    assert [entry["id"] for entry in result["checks"]] == CHECK_IDS
    assert [entry["label"] for entry in result["checks"]] == CHECK_LABELS
    assert result["ok"] is True
    assert result["reason"] == "ok"
    assert _verdict(result) == [True, True, True, True]


def test_every_check_carries_a_non_empty_detail():
    result = verify_plan(new_world(), GOOD_PLAN)

    for entry in result["checks"]:
        assert isinstance(entry["detail"], str)
        assert entry["detail"].strip()


def test_verify_plan_never_mutates_the_world():
    world = new_world()
    before = copy.deepcopy(world)

    verify_plan(world, GOOD_PLAN)

    assert world == before, "verify_plan must not touch the caller's world"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def test_wall_hit_fails_collisions_and_the_goal_only():
    result = verify_plan(new_world(), WALL_PLAN)
    checks = _checks(result)

    assert result["ok"] is False
    assert checks["valid_actions"]["ok"] is True
    assert checks["in_bounds"]["ok"] is True
    assert checks["no_collisions"]["ok"] is False
    assert checks["goal_reachable"]["ok"] is False
    # The detail names the cell the simulator refused, not a guess.
    assert "[3, 0]" in checks["no_collisions"]["detail"]
    assert "[2, 0]" in checks["goal_reachable"]["detail"]
    assert "blocked" in result["reason"]


def test_leaving_the_grid_fails_bounds_and_not_collisions():
    result = verify_plan(new_world(), OFF_GRID_PLAN)
    checks = _checks(result)

    assert result["ok"] is False
    assert checks["valid_actions"]["ok"] is True
    assert checks["in_bounds"]["ok"] is False
    assert checks["no_collisions"]["ok"] is True
    assert checks["goal_reachable"]["ok"] is False
    assert "[0, -1]" in checks["in_bounds"]["detail"]


def test_short_plan_fails_only_the_goal():
    result = verify_plan(new_world(), [{"cmd": "forward", "steps": 2}])
    checks = _checks(result)

    assert _verdict(result) == [True, True, True, False]
    assert "goal not reached" in result["reason"]
    assert "[2, 0]" in checks["goal_reachable"]["detail"]


def test_unknown_command_fails_actions_and_leaves_the_rest_unproven():
    result = verify_plan(new_world(), [{"cmd": "fly", "steps": 2}])
    checks = _checks(result)

    assert result["ok"] is False
    assert checks["valid_actions"]["ok"] is False
    # Nothing about bounds, collisions or the goal was proven — so nothing is
    # reported as a pass.
    assert checks["in_bounds"]["ok"] is None
    assert checks["no_collisions"]["ok"] is None
    assert checks["goal_reachable"]["ok"] is None
    assert "unknown command" in result["reason"]


def test_malformed_actions_are_reported_as_invalid():
    for action in ("fly", {"steps": 2}, 42):
        result = verify_plan(new_world(), [action])
        checks = _checks(result)

        assert result["ok"] is False
        assert checks["valid_actions"]["ok"] is False
        assert "not a valid action dict" in checks["valid_actions"]["detail"]


def test_a_valid_command_that_raises_is_a_fault_not_a_pass():
    # "forward" is a real command, but its step count is not a number, so the
    # simulator raises — the movement checks stay unproven.
    result = verify_plan(new_world(), [{"cmd": "forward", "steps": "many"}])
    checks = _checks(result)

    assert result["ok"] is False
    assert checks["valid_actions"]["ok"] is True
    assert checks["in_bounds"]["ok"] is None
    assert checks["no_collisions"]["ok"] is None
    assert checks["goal_reachable"]["ok"] is None
    assert "raised an unexpected error" in result["reason"]


def test_empty_plan_cannot_reach_the_goal_but_passes_the_other_checks():
    result = verify_plan(new_world(), [])
    checks = _checks(result)

    assert _verdict(result) == [True, True, True, False]
    assert "empty plan" in result["reason"]
    assert "but the goal is at" not in checks["goal_reachable"]["detail"]


def test_empty_plan_on_the_goal_is_accepted():
    world = new_world()
    world["robot"] = list(world["goal"])

    result = verify_plan(world, [])

    assert result["ok"] is True
    assert result["reason"] == "ok"


def test_plan_over_the_step_limit_is_rejected():
    actions = [{"cmd": "forward", "steps": 1}] * (MAX_PLAN_STEPS + 1)

    result = verify_plan(new_world(), actions)
    checks = _checks(result)

    assert result["ok"] is False
    assert "exceeds the maximum" in result["reason"]
    assert checks["valid_actions"]["ok"] is True
    assert checks["goal_reachable"]["ok"] is None


def test_bad_worlds_are_rejected_with_the_guard_reason():
    cases = [
        (None, "world must be a dict"),
        ({}, "missing required key"),
        ({"robot": [0, 0], "dir": "Q", "goal": [1, 1]}, "invalid heading"),
    ]
    for world, fragment in cases:
        result = verify_plan(world, GOOD_PLAN)

        assert result["ok"] is False
        assert fragment in result["reason"]
        assert _verdict(result) == [None, None, None, None]


def test_actions_must_be_a_list():
    result = verify_plan(new_world(), "forward please")

    assert result["ok"] is False
    assert result["reason"] == "actions must be a list"


# ---------------------------------------------------------------------------
# The panel and the gate can never disagree
# ---------------------------------------------------------------------------

def test_dry_run_and_verify_plan_agree_on_every_case():
    goal_world = new_world()
    goal_world["robot"] = list(goal_world["goal"])
    walled = new_world()
    walled["walls"] = [[1, 0]]

    cases = [
        (new_world(), GOOD_PLAN),
        (new_world(), WALL_PLAN),
        (new_world(), OFF_GRID_PLAN),
        (new_world(), []),
        (goal_world, []),
        (new_world(), [{"cmd": "fly"}]),
        (new_world(), [{"cmd": "forward", "steps": "many"}]),
        (new_world(), [{"cmd": "forward", "steps": 1}] * (MAX_PLAN_STEPS + 1)),
        (walled, [{"cmd": "forward", "steps": 2}]),
        (None, GOOD_PLAN),
        ({}, GOOD_PLAN),
        (new_world(), "not a list"),
        ({"robot": [0, 0], "dir": "Q", "goal": [1, 1]}, GOOD_PLAN),
    ]

    for world, actions in cases:
        verdict, reason = dry_run(world, actions)
        result = verify_plan(world, actions)

        assert result["ok"] is verdict, (world, actions)
        if verdict is False:
            assert result["reason"] == reason, (world, actions)
        else:
            assert result["reason"] == "ok"


def test_a_passing_result_means_every_check_passed():
    for actions in (GOOD_PLAN, [{"cmd": "turn_left"}]):
        result = verify_plan(new_world(), actions)

        assert result["ok"] is all(entry["ok"] is True for entry in result["checks"])
