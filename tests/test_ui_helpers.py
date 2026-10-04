"""Tests for ui_helpers.py — pure presentation helpers, no Streamlit, no network."""
import json

from gemmabot.simulator import new_world, render

import ui_helpers


# ---------------------------------------------------------------------------
# grid_html
# ---------------------------------------------------------------------------

def test_grid_html_renders_one_cell_per_grid_position():
    world = new_world()
    html = ui_helpers.grid_html(render(world))
    # 8x8 world -> exactly 64 cell divs.
    assert html.count("class='gb-cell'") == 64


def test_grid_html_keeps_multi_codepoint_emoji_in_one_cell():
    # "⬆️" is U+2B06 + U+FE0F; a naive char split would produce two cells.
    html = ui_helpers.grid_html(["⬆️⬜"])
    assert html.count("class='gb-cell'") == 2
    assert "⬆️" in html


def test_grid_html_includes_coordinate_labels():
    html = ui_helpers.grid_html(["⬜⬜", "⬜🎯"])
    # Column header 0/1 and row labels 0/1 must be present for 2x2.
    assert ">0<" in html
    assert ">1<" in html


def test_grid_html_escapes_untrusted_cell_content():
    # Cells are escaped one glyph at a time, so "<" and ">" become entities.
    html = ui_helpers.grid_html(["<b>"])
    assert "&lt;" in html and "&gt;" in html
    assert "<b>" not in html


def test_grid_html_handles_empty_rows():
    assert ui_helpers.grid_html([]).startswith("<div")


# ---------------------------------------------------------------------------
# attempt_cards
# ---------------------------------------------------------------------------

def _plan_reply(actions):
    return json.dumps({"thought": "t", "actions": actions})


def test_attempt_cards_shapes_real_harness_history():
    history = [
        {
            "attempt": 1,
            "prompt": "navigate to the goal",
            "reply": _plan_reply([{"cmd": "forward", "steps": 5}]),
            "ok": False,
            "feedback": "action 1 failed: blocked at [2, 0]",
        },
        {
            "attempt": 2,
            "prompt": "navigate to the goal\n\nYour previous plan failed...",
            "reply": _plan_reply([{"cmd": "turn_right"}]),
            "ok": True,
            "feedback": "ok",
        },
    ]
    cards = ui_helpers.attempt_cards(history)
    assert len(cards) == 2

    first, second = cards
    assert first["label"] == "Attempt 1"
    assert first["status"] == "FAIL"
    assert first["ok"] is False
    assert "blocked" in first["error"]
    assert first["parsed"]["actions"] == [{"cmd": "forward", "steps": 5}]

    assert second["label"] == "Attempt 2"
    assert second["status"] == "OK"
    assert second["error"] is None
    assert second["parsed"]["actions"] == [{"cmd": "turn_right"}]


def test_attempt_cards_unparsable_reply_keeps_raw_text():
    history = [
        {
            "attempt": 1,
            "prompt": "p",
            "reply": "Here is the map! No JSON at all.",
            "ok": False,
            "feedback": "could not parse reply as JSON: No JSON object found",
        }
    ]
    card = ui_helpers.attempt_cards(history)[0]
    assert card["parsed"] is None
    assert "No JSON" in card["error"]
    assert "Here is the map!" in card["reply"]


def test_attempt_cards_empty_history():
    assert ui_helpers.attempt_cards([]) == []


def test_attempt_cards_skips_non_dict_records():
    cards = ui_helpers.attempt_cards(["nonsense", {"attempt": 2, "ok": True, "reply": "{}"}])
    assert len(cards) == 1
    assert cards[0]["attempt"] == 2


# ---------------------------------------------------------------------------
# accepted_reply
# ---------------------------------------------------------------------------

def test_accepted_reply_returns_first_ok_attempt():
    history = [
        {"attempt": 1, "reply": "bad", "ok": False, "feedback": "blocked"},
        {"attempt": 2, "reply": "{}", "ok": True, "feedback": "ok"},
        {"attempt": 3, "reply": "{}", "ok": True, "feedback": "ok"},
    ]
    accepted = ui_helpers.accepted_reply(history)
    assert accepted is not None
    assert accepted["attempt"] == 2


def test_accepted_reply_none_when_every_attempt_failed():
    history = [{"attempt": 1, "reply": "x", "ok": False, "feedback": "nope"}]
    assert ui_helpers.accepted_reply(history) is None


# ---------------------------------------------------------------------------
# run_metrics
# ---------------------------------------------------------------------------

def test_run_metrics_success_uses_measured_values():
    metrics = ui_helpers.run_metrics([{"cmd": "forward"}], 2, 3, 1.424242)
    assert metrics["attempts_label"] == "2 / 3"
    assert metrics["latency_label"] == "1.42 s"
    assert metrics["status"] == "Verified safe"
    assert metrics["actions_label"] == "1"
    assert metrics["ok"] is True


def test_run_metrics_failure():
    metrics = ui_helpers.run_metrics(None, 3, 3, 0.5)
    assert metrics["status"] == "No valid plan"
    assert metrics["actions_label"] == "0"
    assert metrics["ok"] is False


def test_run_metrics_handles_missing_latency():
    metrics = ui_helpers.run_metrics(None, 0, 2, None)
    assert metrics["latency_label"] == "n/a"


# ---------------------------------------------------------------------------
# short_json
# ---------------------------------------------------------------------------

def test_short_json_compact_and_truncated():
    text = ui_helpers.short_json({"a": [1, 2, 3]})
    assert text == '{"a":[1,2,3]}'

    long_text = ui_helpers.short_json(list(range(500)), limit=40)
    assert len(long_text) == 41  # 40 chars + ellipsis
    assert long_text.endswith("…")


def test_short_json_handles_unserializable_values():
    class Weird:
        def __repr__(self):
            return "Weird()"

    assert "Weird()" in ui_helpers.short_json(Weird())
