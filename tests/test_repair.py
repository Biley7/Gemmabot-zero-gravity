"""The bounded repair loop — ``backend.verifier.harness.plan_with_repair``.

Owner: BACKEND.  The loop is the "repair" stage of the guard: a refused plan
is fed back once per attempt, bounded by ``max_tries``, and the world is never
mutated.  These tests pin that contract with scripted planners (no AI, no
network) — the same convention the harness self-test uses.
"""
import json

from backend.verifier.harness import _repair_prompt, plan_with_repair
from gemmabot.simulator import new_world

# Default world: robot [0, 0] facing E, goal [6, 5], a wall column at x=3.
# A 7-step walk east runs into the wall at [3, 0]; this route goes around.
HAZARD = [{"cmd": "forward", "steps": 7}]
SAFE = [
    {"cmd": "forward", "steps": 2},   # [2, 0]
    {"cmd": "turn_right"},            # face S
    {"cmd": "forward", "steps": 7},   # [2, 7]
    {"cmd": "turn_left"},             # face E
    {"cmd": "forward", "steps": 4},   # [6, 7]
    {"cmd": "turn_left"},             # face N
    {"cmd": "forward", "steps": 2},   # [6, 5] — goal
]


def _reply(actions):
    return json.dumps({"thought": "scripted", "actions": actions})


def test_a_refused_plan_is_repaired_on_the_next_attempt():
    replies = [_reply(HAZARD), _reply(SAFE)]
    actions, attempts, history = plan_with_repair(
        "go to the goal", new_world(), lambda i, w: replies.pop(0), max_tries=3
    )
    assert actions == SAFE
    assert attempts == 2
    assert [record["ok"] for record in history] == [False, True]
    # The first failure names the action that was blocked, at its real cell.
    assert history[0]["feedback"].startswith("action 1")
    assert "blocked at [2, 0]" in history[0]["feedback"]


def test_the_repair_prompt_carries_the_original_instruction_and_one_failure():
    prompt = _repair_prompt("original instruction", "the failed reply", "blocked at [2, 0]")
    assert "original instruction" in prompt
    assert "the failed reply" in prompt
    assert "blocked at [2, 0]" in prompt


def test_repairs_are_bounded_and_never_mutate_the_world():
    calls = {"n": 0}

    def always_bad(instruction, world):
        calls["n"] += 1
        return _reply(HAZARD)

    world = new_world()
    before = json.dumps(world, sort_keys=True)
    actions, attempts, history = plan_with_repair(
        "go to the goal", world, always_bad, max_tries=3
    )
    assert actions is None, "nothing executable may be returned after 3 failures"
    assert attempts == 3
    assert len(history) == 3
    assert calls["n"] == 3, "the loop must stop exactly at max_tries"
    assert json.dumps(world, sort_keys=True) == before, "the world was mutated"


def test_a_parse_failure_is_repaired_without_crashing():
    replies = ["not json at all", _reply(SAFE)]
    actions, attempts, history = plan_with_repair(
        "go", new_world(), lambda i, w: replies.pop(0), max_tries=2
    )
    assert actions == SAFE
    assert attempts == 2
    assert history[0]["actions"] is None
    assert "parse" in history[0]["feedback"].lower()
    # The repair prompt kept the original instruction, not a growing chain.
    assert "go" in history[1]["prompt"]


def test_a_planner_exception_is_reported_as_feedback_not_raised():
    replies = ["boom-handled"]

    def flaky(instruction, world):
        if replies:
            replies.pop()
            raise RuntimeError("model endpoint unreachable")
        return _reply(SAFE)

    actions, attempts, history = plan_with_repair(
        "go", new_world(), flaky, max_tries=2
    )
    assert actions == SAFE
    assert "model endpoint unreachable" in history[0]["feedback"]
