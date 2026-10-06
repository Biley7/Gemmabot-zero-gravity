"""Tests for gemmabot/map_vision.py — pure validation and fake vision only.

No network: ``ask_vision`` is always a fake.
"""
import json

import pytest

from gemmabot.map_vision import (
    build_map_prompt,
    check_world,
    check_world_report,
    read_map,
)
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


# ---------------------------------------------------------------------------
# check_world_report — the same verdict, reported per check
# ---------------------------------------------------------------------------

def test_the_report_reports_the_three_checks_the_lab_shows():
    report = check_world_report(new_world())
    assert [(check["id"], check["label"]) for check in report["checks"]] == [
        ("valid", "Valid"),
        ("in_bounds", "Inside bounds"),
        ("reachable", "Reachable"),
    ]


def test_a_good_world_passes_every_check_and_carries_no_failure_data():
    report = check_world_report(new_world())
    assert report["ok"] is True
    assert report["reason"] == "ok"
    assert [check["ok"] for check in report["checks"]] == [True, True, True]
    assert all(check["data"] == {} for check in report["checks"])
    assert all(check["detail"] for check in report["checks"])


def test_an_off_grid_goal_is_a_bounds_failure_with_the_cell_in_the_data():
    report = check_world_report(_world(goal=[7, 8]))
    by_id = {check["id"]: check for check in report["checks"]}
    assert by_id["in_bounds"]["ok"] is False
    assert by_id["in_bounds"]["data"] == {"cell": [7, 8], "field": "goal"}
    # The shape really is well formed, and reachability was never asked.
    assert by_id["valid"]["ok"] is True
    assert by_id["reachable"]["ok"] is None
    assert by_id["reachable"]["data"] == {}
    assert report["reason"] == "goal position [7, 8] is outside the 8×8 grid"


def test_an_off_grid_wall_names_the_wall_it_failed_on():
    report = check_world_report(_world(walls=[[3, 0], [8, 8]]))
    by_id = {check["id"]: check for check in report["checks"]}
    assert by_id["in_bounds"]["ok"] is False
    assert by_id["in_bounds"]["data"]["field"] == "walls[1]"
    assert by_id["in_bounds"]["data"]["cell"] == [8, 8]


def test_an_unreachable_goal_fails_only_reachability():
    world = {
        "robot": [0, 0], "dir": "E", "goal": [7, 7],
        "walls": [[6, 7], [7, 6], [6, 6]],
    }
    report = check_world_report(world)
    by_id = {check["id"]: check for check in report["checks"]}
    assert by_id["valid"]["ok"] is True
    assert by_id["in_bounds"]["ok"] is True
    assert by_id["reachable"]["ok"] is False
    assert by_id["reachable"]["data"] == {"robot": [0, 0], "goal": [7, 7], "walls": 3}
    assert "unreachable" in report["reason"]


def test_a_goal_on_a_wall_fails_validity_and_leaves_reachability_unproven():
    report = check_world_report(_world(goal=[3, 1]))
    by_id = {check["id"]: check for check in report["checks"]}
    assert by_id["valid"]["ok"] is False
    assert by_id["valid"]["data"] == {"cell": [3, 1], "field": "goal"}
    assert by_id["in_bounds"]["ok"] is True          # extents were still checked
    assert by_id["reachable"]["ok"] is None
    assert "not evaluated" in by_id["reachable"]["detail"]


def test_start_equals_goal_fails_validity_and_leaves_reachability_unproven():
    report = check_world_report(_world(goal=[0, 0]))
    by_id = {check["id"]: check for check in report["checks"]}
    assert by_id["valid"]["ok"] is False
    assert by_id["reachable"]["ok"] is None


@pytest.mark.parametrize(
    "malformed",
    [
        None, "not a world", [], {}, {"robot": [0, 0]},
        {"robot": [0, 0], "dir": "E", "goal": [1, 1]},
        {"robot": [0, 0], "dir": "Q", "goal": [1, 1], "walls": []},
        {"robot": [0.0, 0.0], "dir": "E", "goal": [1, 1], "walls": []},
        {"robot": [0, 0], "dir": "E", "goal": [1, 1], "walls": "lots"},
    ],
)
def test_a_reading_that_is_not_a_world_reports_the_later_checks_unproven(malformed):
    report = check_world_report(malformed)
    by_id = {check["id"]: check for check in report["checks"]}
    assert by_id["valid"]["ok"] is False
    assert report["ok"] is False
    for check_id in ("in_bounds", "reachable"):
        assert by_id[check_id]["ok"] is None, check_id
        assert "not evaluated" in by_id[check_id]["detail"]
        assert by_id[check_id]["data"] == {}


def test_reachability_unproven_details_name_the_problem_that_blocked_it():
    report = check_world_report(_world(robot=[8, 0]))
    reachable = next(c for c in report["checks"] if c["id"] == "reachable")
    assert reachable["ok"] is None
    assert "robot position [8, 0] is outside the 8×8 grid" in reachable["detail"]


def _report_corpus():
    """Worlds that exercise every branch, including malformed input."""
    yield new_world()
    yield from (None, "x", [], {}, 0, True)
    yield _world(goal=[7, 8])
    yield _world(robot=[8, 0])
    yield _world(goal=[-1, 0])
    yield _world(walls=[[8, 8]])
    yield _world(goal=[3, 1])
    yield _world(robot=[3, 1])
    yield _world(goal=[0, 0])
    yield {"robot": [0, 0], "dir": "E", "goal": [7, 7],
           "walls": [[6, 7], [7, 6], [6, 6]]}
    yield _world(walls=[[3, 0], [3, 0], [3, 1]])
    for heading in ("N", "E", "S", "W"):
        yield _world(dir=heading)


def test_check_world_always_agrees_with_the_report():
    """The terse form is a wrapper: it can never disagree with the report."""
    for world in _report_corpus():
        report = check_world_report(world)
        assert check_world(world) == (report["ok"], report["reason"])


def test_report_ok_is_exactly_all_three_checks_passing():
    for world in _report_corpus():
        report = check_world_report(world)
        assert report["ok"] is all(check["ok"] is True for check in report["checks"])


def test_failure_data_is_attached_only_to_a_failed_check():
    for world in _report_corpus():
        for check in check_world_report(world)["checks"]:
            if check["ok"] is not False:
                assert check["data"] == {}, (world, check)


def test_every_check_is_labelled_and_explained():
    for world in _report_corpus():
        for check in check_world_report(world)["checks"]:
            assert check["label"]
            assert isinstance(check["detail"], str) and check["detail"]
            assert check["ok"] in (True, False, None)
