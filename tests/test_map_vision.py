"""Tests for gemmabot/map_vision.py — pure validation and fake vision only.

No network: ``ask_vision`` is always a fake.
"""
import json

import pytest

from gemmabot.map_vision import build_map_prompt, check_world, read_map
from gemmabot.simulator import new_world

FAKE_IMAGE = b"\x00"  # placeholder bytes; never sent anywhere
FAKE_MIME = "image/png"


def _world(**overrides):
    world = new_world()
    world.update(overrides)
    return world


# ---------------------------------------------------------------------------
# check_world — pure Python, never raises
# ---------------------------------------------------------------------------

def test_valid_world_is_accepted():
    ok, reason = check_world(new_world())
    assert ok is True
    assert reason == "ok"


def test_goal_on_wall_is_rejected():
    ok, reason = check_world(_world(goal=[3, 1]))
    assert ok is False
    assert "wall" in reason.lower()


def test_robot_on_wall_is_rejected():
    ok, reason = check_world(_world(robot=[3, 1]))
    assert ok is False
    assert "wall" in reason.lower()


def test_out_of_bounds_robot_is_rejected():
    ok, reason = check_world(_world(robot=[8, 0]))
    assert ok is False
    assert "outside" in reason.lower()


def test_out_of_bounds_goal_is_rejected():
    ok, reason = check_world(_world(goal=[-1, 0]))
    assert ok is False
    assert "outside" in reason.lower()


def test_out_of_bounds_wall_is_rejected():
    ok, reason = check_world(_world(walls=[[8, 8]]))
    assert ok is False
    assert "outside" in reason.lower()


def test_robot_equals_goal_is_rejected():
    ok, reason = check_world(_world(goal=[0, 0]))
    assert ok is False
    assert "same cell" in reason.lower()


def test_unreachable_goal_is_rejected():
    world = {
        "robot": [0, 0],
        "dir": "E",
        "goal": [7, 7],
        "walls": [[6, 7], [7, 6], [6, 6]],  # seal the goal into the corner
    }
    ok, reason = check_world(world)
    assert ok is False
    assert "unreachable" in reason.lower()


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        "not a world",
        [],
        {},
        {"robot": [0, 0]},
        {"robot": [0, 0], "dir": "E", "goal": [1, 1]},                      # no walls key
        {"robot": [0, 0], "dir": "Q", "goal": [1, 1], "walls": []},         # bad heading
        {"robot": [0.0, 0.0], "dir": "E", "goal": [1, 1], "walls": []},     # float coords
        {"robot": [0, 0, 0], "dir": "E", "goal": [1, 1], "walls": []},      # wrong length
        {"robot": [0, 0], "dir": "E", "goal": [1, 1], "walls": [[2, 2, 2]]},
        {"robot": [0, 0], "dir": "E", "goal": [1, 1], "walls": "lots"},
    ],
)
def test_malformed_worlds_are_rejected_without_raising(malformed):
    ok, reason = check_world(malformed)
    assert ok is False
    assert isinstance(reason, str) and reason


def test_duplicate_walls_are_tolerated_like_the_simulator():
    world = _world(walls=[[3, 0], [3, 0], [3, 1]])
    ok, reason = check_world(world)
    assert ok is True, reason


def test_all_simulator_headings_are_accepted():
    for heading in ("N", "E", "S", "W"):
        ok, reason = check_world(_world(dir=heading))
        assert ok is True, f"{heading}: {reason}"


# ---------------------------------------------------------------------------
# build_map_prompt
# ---------------------------------------------------------------------------

def test_build_map_prompt_states_the_world_contract():
    prompt = build_map_prompt()
    assert '"robot": [x, y]' in prompt
    assert '"dir": "E"' in prompt
    assert '"walls": [[x, y], [x, y]]' in prompt
    assert "N, E, S, W" in prompt
    assert "Never infer" in prompt or "never infer" in prompt


# ---------------------------------------------------------------------------
# read_map — fake vision, no network
# ---------------------------------------------------------------------------

VALID_JSON = json.dumps({
    "robot": [0, 0],
    "dir": "E",
    "goal": [6, 5],
    "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]],
})
BAD_JSON = json.dumps({"robot": [0, 0], "dir": "E", "goal": [3, 0],
                       "walls": [[3, 0], [3, 1]]})
FENCED_JSON = "```json\n" + VALID_JSON + "\n```"
PREFIXED_JSON = "Here is the JSON:\n" + VALID_JSON


def test_read_map_accepts_fenced_and_prefixed_json():
    for reply in (FENCED_JSON, PREFIXED_JSON):
        calls = {"n": 0}

        def fake_vision(prompt, image_bytes, mime, _reply=reply):
            calls["n"] += 1
            return _reply

        world, history = read_map(FAKE_IMAGE, FAKE_MIME, fake_vision, max_tries=2)
        assert world is not None
        assert world["goal"] == [6, 5]
        assert len(history) == 1
        assert calls["n"] == 1


def test_read_map_retries_with_failure_reason_in_the_prompt():
    calls = {"n": 0}
    prompts = []

    def fake_vision(prompt, image_bytes, mime):
        calls["n"] += 1
        prompts.append(prompt)
        return VALID_JSON if calls["n"] >= 2 else BAD_JSON

    world, history = read_map(FAKE_IMAGE, FAKE_MIME, fake_vision, max_tries=2)

    assert world is not None
    assert [record["ok"] for record in history] == [False, True]
    assert "wall" in history[0]["feedback"].lower()
    assert "wall" in prompts[1].lower(), "repair prompt must carry the exact error"
    assert len(history) == 2


def test_read_map_malformed_json_becomes_a_failed_attempt():
    fake_vision = lambda prompt, image_bytes, mime: "I think the robot is top-left."
    world, history = read_map(FAKE_IMAGE, FAKE_MIME, fake_vision, max_tries=2)

    assert world is None
    assert len(history) == 2
    assert set(history[0]) >= {"attempt", "prompt", "reply", "ok", "feedback"}
    assert "json" in history[0]["feedback"].lower()
    assert history[0]["reply"] == "I think the robot is top-left."


def test_read_map_isolates_vision_exceptions_per_attempt():
    calls = {"n": 0}

    def flaky(prompt, image_bytes, mime):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model overloaded")
        return VALID_JSON

    world, history = read_map(FAKE_IMAGE, FAKE_MIME, flaky, max_tries=2)

    assert world is not None
    assert "model overloaded" in history[0]["feedback"]
    assert history[1]["ok"] is True


def test_read_map_never_stores_image_bytes_in_history():
    fake_vision = lambda prompt, image_bytes, mime: VALID_JSON
    world, history = read_map(FAKE_IMAGE, FAKE_MIME, fake_vision, max_tries=2)

    assert world is not None
    for record in history:
        assert "image_bytes" not in record
        assert all(value != FAKE_IMAGE for value in record.values())
