"""Tests for the simulator module."""
import pytest
from gemmabot.simulator import new_world, step, reached_goal


def test_turn_right_wraps_e_to_s():
    """Test that turning right from East wraps to South."""
    world = new_world()
    world["dir"] = "E"
    step(world, {"cmd": "turn_right"})
    assert world["dir"] == "S"


def test_forward_blocked_by_wall():
    """Test that forward movement is blocked by a wall."""
    world = new_world()
    world["robot"] = [2, 0]
    world["walls"] = [[3, 0]]
    msg = step(world, {"cmd": "forward", "steps": 2})
    assert "blocked" in msg.lower()
    assert world["robot"] == [2, 0]


def test_reached_goal_true_when_robot_equals_goal():
    """Test that reached_goal returns True when robot is at goal."""
    world = new_world()
    world["robot"] = [6, 5]
    world["goal"] = [6, 5]
    assert reached_goal(world) is True
