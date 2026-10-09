"""World validation — ``backend.vision.map_vision.check_world_report``.

Owner: BACKEND.  A world read from an image is admitted only after three
independent checks (shape, grid extents, reachability); a check that could not
be evaluated is ``ok=None`` and is never shown as a pass.  These tests pin
that convention and the exact failure sentences the UI quotes.
"""
from backend.vision.map_vision import check_world, check_world_report, WORLD_CHECKS
from gemmabot.simulator import new_world

CHECK_IDS = {check_id for check_id, _ in WORLD_CHECKS}


def test_the_default_world_passes_all_three_checks():
    ok, reason = check_world(new_world())
    assert ok is True, reason
    report = check_world_report(new_world())
    assert report["ok"] is True
    assert report["reason"] == "ok"
    assert {check["id"] for check in report["checks"]} == CHECK_IDS == {
        "valid", "in_bounds", "reachable",
    }
    assert all(check["ok"] is True for check in report["checks"])


def test_an_off_grid_goal_is_refused_with_its_cell_and_the_grid_size():
    world = new_world()
    world["goal"] = [7, 8]
    report = check_world_report(world)
    assert report["ok"] is False
    assert "goal position [7, 8] is outside the 8×8 grid" in report["reason"]
    # The failure is attributed to the bounds check, with the cell as data.
    failed = [check for check in report["checks"] if check["ok"] is False]
    assert [(c["id"], c["data"].get("field")) for c in failed] == [
        ("in_bounds", "goal"),
    ]


def test_a_goal_on_a_wall_is_refused():
    world = new_world()
    world["goal"] = list(world["walls"][0])
    ok, reason = check_world(world)
    assert ok is False
    assert "goal" in reason and "wall" in reason.lower()


def test_an_unreachable_goal_is_refused_by_the_search():
    # Box the robot in on all four sides; the goal is far away and free.
    world = {
        "robot": [1, 1],
        "dir": "E",
        "goal": [7, 7],
        "walls": [[0, 1], [2, 1], [1, 0], [1, 2]],
    }
    report = check_world_report(world)
    assert report["ok"] is False
    assert "unreachable" in report["reason"]
    reachable = next(c for c in report["checks"] if c["id"] == "reachable")
    assert reachable["ok"] is False
    # Shape and bounds are still proven independently — a failure in one
    # check must not hide a pass in another.
    others = [c for c in report["checks"] if c["id"] != "reachable"]
    assert all(c["ok"] is True for c in others)


def test_a_reading_that_is_not_a_world_leaves_later_checks_unproven():
    report = check_world_report({"robot": [0, 0]})
    assert report["ok"] is False
    by_id = {check["id"]: check for check in report["checks"]}
    assert by_id["valid"]["ok"] is False
    assert "missing required key" in by_id["valid"]["detail"]
    # Unproven, not passed: nothing was bounds-checked or searched.
    assert by_id["in_bounds"]["ok"] is None
    assert by_id["reachable"]["ok"] is None


def test_validation_never_raises_on_hostile_input():
    for hostile in (None, "map", 7, [], {"robot": "x", "dir": "E", "goal": [1, 1], "walls": []}):
        report = check_world_report(hostile)
        assert report["ok"] is False
        assert isinstance(report["reason"], str)
