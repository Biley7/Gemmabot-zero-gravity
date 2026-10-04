"""Plan harness: validate and execute action plans on the robot world.

Owner: BACKEND

Public API
----------
dry_run(world, actions) -> (bool, str)
    Validates a list of actions against a *copy* of the world.
    The original world is never modified.

plan_with_repair(instruction, world, ask, max_tries=3)
    -> (actions | None, attempts: int, history: list[dict])
    Calls ``ask`` up to ``max_tries`` times, validates each plan with
    ``dry_run``, and repairs via a new prompt on failure.  Returns None
    (and executes nothing) if every attempt fails.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Callable

from gemmabot.simulator import step, reached_goal, DIRS, ARROW

# Hard limit on plan length to catch runaway models early.
MAX_PLAN_STEPS = 20


def dry_run(world: dict[str, Any], actions: list[dict]) -> tuple[bool, str]:
    """Validate *actions* against a deep-copy of *world*.

    Applies every action in order using the same ``step()`` that the real
    executor uses, so "what is checked" is exactly "what would run".

    Parameters
    ----------
    world:
        Robot world dict with at least ``robot`` ([x, y]), ``dir`` (heading),
        ``goal`` ([x, y]), and ``walls`` (list of [x, y]).
    actions:
        Ordered list of action dicts, e.g.
        ``[{"cmd": "forward", "steps": 3}, {"cmd": "turn_left"}]``.

    Returns
    -------
    (True, "ok")
        All actions ran without error and the goal was reached.
    (False, reason)
        Validation failed; *reason* describes exactly what went wrong.
    """
    # --- Guard: bad / missing inputs -------------------------------------------
    if not isinstance(world, dict):
        return False, "world must be a dict"
    for key in ("robot", "dir", "goal"):
        if key not in world:
            return False, f"world is missing required key: '{key}'"
    if world.get("dir") not in DIRS:
        return False, f"world has invalid heading: {world.get('dir')!r}"

    if not isinstance(actions, list):
        return False, "actions must be a list"

    if len(actions) == 0:
        # An empty plan can never reach the goal (unless already there).
        sim = copy.deepcopy(world)
        if reached_goal(sim):
            return True, "ok"
        return False, (
            f"empty plan: robot is at {world['robot']} but goal is at {world['goal']}"
        )

    # --- Guard: plan too long ---------------------------------------------------
    if len(actions) > MAX_PLAN_STEPS:
        return False, (
            f"plan has {len(actions)} actions, which exceeds the maximum of "
            f"{MAX_PLAN_STEPS}"
        )

    # --- Run on a deep copy so the real world is never touched -----------------
    sim = copy.deepcopy(world)

    for i, action in enumerate(actions, start=1):
        if not isinstance(action, dict) or "cmd" not in action:
            return False, (
                f"action {i} is not a valid action dict: {action!r}"
            )

        try:
            msg = step(sim, action)
        except Exception as exc:  # noqa: BLE001
            return False, (
                f"action {i} ({action!r}) raised an unexpected error: {exc}"
            )

        # step() signals failure through its return string.
        if msg.startswith("blocked") or msg.startswith("unknown"):
            heading_arrow = ARROW.get(sim["dir"], sim["dir"])
            return False, (
                f"action {i} ({action!r}) failed: {msg}. "
                f"Robot is at {sim['robot']} facing {sim['dir']} {heading_arrow}"
            )

    # --- All actions ran; check whether the goal was reached -------------------
    if not reached_goal(sim):
        return False, (
            f"plan finished but goal not reached: "
            f"robot ended at {sim['robot']}, goal is at {world['goal']}"
        )

    return True, "ok"


def plan_with_repair(
    instruction: str,
    world: dict[str, Any],
    ask: Callable[[str, dict], str],
    max_tries: int = 3,
) -> tuple[list[dict] | None, int, list[dict]]:
    """Call *ask* up to *max_tries* times, repairing the plan on each failure.

    Parameters
    ----------
    instruction:
        Plain-English goal for the robot, e.g. ``"go to the goal"``.
    world:
        Current world dict.  Never mutated by this function.
    ask:
        Callable with signature ``ask(instruction: str, world: dict) -> str``.
        Compatible with ``ask_api`` and ``ask_ollama`` from ``planner.py``,
        as well as any fake/stub passed in for testing.
    max_tries:
        Hard cap on the number of attempts (default 3).

    Returns
    -------
    (actions, attempt_number, history)
        *actions* is the validated list on success, or ``None`` if all
        attempts failed.  *attempt_number* is how many attempts were made.
        *history* is one record per attempt (see below).

    History record shape
    --------------------
    {
        "attempt":  int,   # 1-based
        "prompt":   str,   # instruction string sent to ask()
        "reply":    str,   # raw string returned by ask()
        "ok":       bool,  # True only when dry_run passed
        "feedback": str,   # "ok" on success; failure reason otherwise
    }
    """
    history: list[dict] = []
    # Keep the original instruction intact; repair prompts extend it inline.
    current_instruction = instruction

    # parse_plan is inlined here so harness.py works without google/ollama
    # installed.  The canonical copy lives in planner.py for runtime use.
    import re as _re

    def _parse_plan(text: str) -> tuple[str, list]:
        text = _re.sub(r"```(?:json)?", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON found in reply")
        data = json.loads(text[start:end + 1])
        return data.get("thought", ""), data.get("actions", [])

    for attempt in range(1, max_tries + 1):
        # ── Call the model ────────────────────────────────────────────────
        try:
            reply = ask(current_instruction, world)
        except Exception as exc:  # noqa: BLE001
            feedback = f"ask() raised an error: {exc}"
            print(f"  [attempt {attempt}/{max_tries}] ask error — {feedback}")
            history.append({
                "attempt": attempt,
                "prompt": current_instruction,
                "reply": "",
                "ok": False,
                "feedback": feedback,
            })
            # Rebuild repair prompt from original instruction.
            current_instruction = _repair_prompt(instruction, "", feedback)
            continue

        # ── Parse the reply ───────────────────────────────────────────────
        try:
            _thought, actions = _parse_plan(reply)
        except Exception as exc:  # noqa: BLE001
            feedback = f"could not parse reply as JSON: {exc}"
            print(f"  [attempt {attempt}/{max_tries}] parse error — {feedback}")
            history.append({
                "attempt": attempt,
                "prompt": current_instruction,
                "reply": reply,
                "ok": False,
                "feedback": feedback,
            })
            current_instruction = _repair_prompt(instruction, reply, feedback)
            continue

        # ── Validate with dry_run ─────────────────────────────────────────
        ok, feedback = dry_run(world, actions)
        print(
            f"  [attempt {attempt}/{max_tries}] "
            + ("✓ plan ok" if ok else f"✗ {feedback}")
        )
        history.append({
            "attempt": attempt,
            "prompt": current_instruction,
            "reply": reply,
            "ok": ok,
            "feedback": feedback,
        })

        if ok:
            return actions, attempt, history

        # Build next prompt from the ORIGINAL instruction + latest failure.
        current_instruction = _repair_prompt(
            instruction,
            json.dumps({"actions": actions}, separators=(",", ":")),
            feedback,
        )

    # All tries exhausted — return nothing executable.
    return None, max_tries, history


def _repair_prompt(original_instruction: str, failed_plan: str, reason: str) -> str:
    """Construct a repair prompt rooted in the original instruction.

    Keeping it brief avoids prompt-growth across retries: the model always
    sees the original goal + *one* failure, never a chain of failures.
    """
    return (
        f"{original_instruction}\n\n"
        f"Your previous plan failed.\n"
        f"Failed plan: {failed_plan or '(none parsed)'}\n"
        f"Reason: {reason}\n\n"
        f"Provide a corrected plan in the same JSON format: "
        f'{{\"thought\":\"...\",\"actions\":[...]}}'
    )


# ---------------------------------------------------------------------------
# Self-test (no AI, no network)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from gemmabot.simulator import new_world

    SEP = "-" * 55

    # ── Case A: plan that hits a wall ──────────────────────────────────────
    print(SEP)
    print("Case A: plan that hits a wall")
    world_a = new_world()         # robot at [0,0] facing E; wall column at x=3
    original_robot_a = list(world_a["robot"])

    # Moving 4 steps East walks into the wall at [3, 0]
    actions_a = [{"cmd": "forward", "steps": 4}]
    ok_a, msg_a = dry_run(world_a, actions_a)
    print(f"  Result : ok={ok_a}")
    print(f"  Message: {msg_a}")
    print(f"  Original world robot (must be unchanged): {world_a['robot']}")
    assert world_a["robot"] == original_robot_a, "FAIL: world was mutated!"
    assert ok_a is False
    assert "blocked" in msg_a

    # ── Case B: correct plan that reaches the goal ─────────────────────────
    print(SEP)
    print("Case B: correct plan that reaches the goal [6, 5]")
    world_b = new_world()         # robot [0,0] E; goal [6,5]
    original_robot_b = list(world_b["robot"])

    # Route that avoids the wall column at x=3 and the cluster at x=5 y=4-6:
    #   go south to y=7, east past x=5, north to y=5, east to x=6
    actions_b = [
        {"cmd": "turn_right"},           # face S
        {"cmd": "forward", "steps": 7},  # [0,0] -> [0,7]
        {"cmd": "turn_left"},            # face E
        {"cmd": "forward", "steps": 6},  # [0,7] -> [6,7]
        {"cmd": "turn_left"},            # face N
        {"cmd": "forward", "steps": 2},  # [6,7] -> [6,5]  ← goal!
    ]
    ok_b, msg_b = dry_run(world_b, actions_b)
    print(f"  Result : ok={ok_b}")
    print(f"  Message: {msg_b}")
    print(f"  Original world robot (must be unchanged): {world_b['robot']}")
    assert world_b["robot"] == original_robot_b, "FAIL: world was mutated!"
    assert ok_b is True
    assert msg_b == "ok"

    # ── Case C: plan that ends short of the goal ───────────────────────────
    print(SEP)
    print("Case C: plan that ends short of the goal")
    world_c = new_world()
    original_robot_c = list(world_c["robot"])

    # Takes only 2 steps east — not even close to [6,5]
    actions_c = [{"cmd": "forward", "steps": 2}]
    ok_c, msg_c = dry_run(world_c, actions_c)
    print(f"  Result : ok={ok_c}")
    print(f"  Message: {msg_c}")
    print(f"  Original world robot (must be unchanged): {world_c['robot']}")
    assert world_c["robot"] == original_robot_c, "FAIL: world was mutated!"
    assert ok_c is False
    assert "goal not reached" in msg_c

    print(SEP)
    print("All three dry_run cases passed. Original worlds were not mutated.")

    # ══════════════════════════════════════════════════════════════════════
    # plan_with_repair tests (fake ask — no API, no Ollama)
    # ══════════════════════════════════════════════════════════════════════
    import json as _json

    # Helper: build a valid JSON reply string from a list of action dicts.
    def _reply(actions):
        return _json.dumps({"thought": "test", "actions": actions})

    # ── Test D: wall hit → bad JSON → correct plan  ────────────────────────
    print(SEP)
    print("Test D: repair loop — wall hit, then bad JSON, then correct plan")

    _d_calls = [0]   # mutable counter (nonlocal not available at module scope)
    def fake_ask_d(instruction, world):
        _d_calls[0] += 1
        if _d_calls[0] == 1:
            # Attempt 1: plan that walks straight into the wall at x=3
            return _reply([{"cmd": "forward", "steps": 5}])
        if _d_calls[0] == 2:
            # Attempt 2: completely invalid JSON (not parseable)
            return "Sure! Here is a plan: go forward a lot 🤖"
        # Attempt 3: correct route to [6,5]
        return _reply([
            {"cmd": "turn_right"},
            {"cmd": "forward", "steps": 7},
            {"cmd": "turn_left"},
            {"cmd": "forward", "steps": 6},
            {"cmd": "turn_left"},
            {"cmd": "forward", "steps": 2},
        ])

    world_d = new_world()
    original_robot_d = list(world_d["robot"])
    actions_d, attempts_d, history_d = plan_with_repair(
        "navigate to the goal", world_d, fake_ask_d, max_tries=3
    )

    print(f"  actions returned : {actions_d is not None}")
    print(f"  attempts         : {attempts_d}")
    print(f"  history length   : {len(history_d)}")
    print(f"  attempt 1 ok     : {history_d[0]['ok']}  (expected False — wall hit)")
    print(f"  attempt 2 ok     : {history_d[1]['ok']}  (expected False — bad JSON)")
    print(f"  attempt 3 ok     : {history_d[2]['ok']}  (expected True)")
    print(f"  world not mutated: {world_d['robot'] == original_robot_d}")

    assert actions_d is not None,           "FAIL: should have returned actions"
    assert attempts_d == 3,                 "FAIL: should have taken 3 attempts"
    assert len(history_d) == 3,             "FAIL: history should have 3 records"
    assert history_d[0]["ok"] is False,     "FAIL: attempt 1 should have failed"
    assert "blocked" in history_d[0]["feedback"], \
        "FAIL: attempt 1 feedback should mention 'blocked'"
    assert history_d[1]["ok"] is False,     "FAIL: attempt 2 should have failed"
    assert "parse" in history_d[1]["feedback"].lower(), \
        "FAIL: attempt 2 feedback should mention parse error"
    assert history_d[2]["ok"] is True,      "FAIL: attempt 3 should have succeeded"
    assert world_d["robot"] == original_robot_d, "FAIL: world was mutated!"
    # Repair prompts must reference the original instruction, not grow unboundedly.
    for rec in history_d[1:]:
        assert "navigate to the goal" in rec["prompt"], \
            "FAIL: repair prompt lost the original instruction"

    print("  ✓ Test D passed")

    # ── Test E: always-bad fake — must return None after exactly 3 tries  ──
    print(SEP)
    print("Test E: repair loop — always bad plan → None after 3 attempts")

    _e_calls = [0]   # mutable counter
    def fake_ask_e(instruction, world):
        _e_calls[0] += 1
        # Always return a plan that hits the wall immediately
        return _reply([{"cmd": "forward", "steps": 5}])

    world_e = new_world()
    original_robot_e = list(world_e["robot"])
    actions_e, attempts_e, history_e = plan_with_repair(
        "navigate to the goal", world_e, fake_ask_e, max_tries=3
    )

    print(f"  actions returned : {actions_e}  (expected None)")
    print(f"  attempts         : {attempts_e}  (expected 3)")
    print(f"  history length   : {len(history_e)}  (expected 3)")
    print(f"  ask called times : {_e_calls[0]}  (expected 3)")
    print(f"  world not mutated: {world_e['robot'] == original_robot_e}")

    assert actions_e is None,           "FAIL: should have returned None"
    assert attempts_e == 3,             "FAIL: should report 3 attempts"
    assert len(history_e) == 3,         "FAIL: history should have 3 records"
    assert _e_calls[0] == 3,               "FAIL: ask() called wrong number of times"
    assert all(not r["ok"] for r in history_e), "FAIL: all attempts should have failed"
    assert world_e["robot"] == original_robot_e, "FAIL: world was mutated!"

    print("  ✓ Test E passed")

    print(SEP)
    print("All tests passed.")
