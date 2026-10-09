"""Planner reply parsing — the canonical parser every call site shares.

Owner: BACKEND.  ``backend.parsing`` is the one implementation; the planner,
the repair loop and map vision all parse through it, so this suite pins the
fence tolerance, the defaults and the failure sentence they rely on.
"""
import pytest

from backend.parsing import parse_plan_reply, parse_world_reply


def test_actions_are_extracted_from_a_fenced_reply():
    """Models wrap JSON in prose and code fences; both must be tolerated."""
    thought, actions = parse_plan_reply(
        "Here is my plan:\n"
        "```json\n"
        '{"thought": "head east then south", "actions": '
        '[{"cmd": "forward", "steps": 3}, {"cmd": "turn_right"}]}\n'
        "```\n"
        "Let me know if you want changes."
    )
    assert thought == "head east then south"
    assert actions == [{"cmd": "forward", "steps": 3}, {"cmd": "turn_right"}]


def test_missing_fields_default_instead_of_failing():
    """`thought` and `actions` are optional to the parser, not required."""
    assert parse_plan_reply('{"actions": []}') == ("", [])
    assert parse_plan_reply('{"thought": "just thinking"}') == ("just thinking", [])


def test_a_reply_without_json_is_refused_with_a_readable_reason():
    """The exact sentence the harness records as feedback."""
    with pytest.raises(ValueError, match="No JSON found in reply"):
        parse_plan_reply("I would move forward three steps.")


def test_malformed_json_is_refused_not_guessed():
    with pytest.raises(ValueError):
        parse_plan_reply('{"thought": "t", "actions": [}')


def test_world_replies_use_the_same_extraction():
    """Map vision's failure sentence is the one its repair prompt quotes."""
    assert parse_world_reply('noise {"robot": [0, 0]} tail') == {"robot": [0, 0]}
    with pytest.raises(ValueError, match="No JSON object found in model reply"):
        parse_world_reply("I can't read this map.")


def test_the_compatibility_shim_uses_the_same_parser():
    """`gemmabot.planner.parse_plan` is a thin re-export, not a second parser."""
    pytest.importorskip("google.genai")  # the shim imports the transport module
    pytest.importorskip("ollama")
    from gemmabot.planner import parse_plan

    assert parse_plan('{"thought": "t", "actions": [{"cmd": "turn_left"}]}') == (
        "t",
        [{"cmd": "turn_left"}],
    )
