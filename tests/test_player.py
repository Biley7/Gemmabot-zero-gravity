"""Tests for the Phase 3 execution player — timeline + HTML document.

No Streamlit, no network: the timeline is built from real ``simulator.step``
results, the document is a pure string.
"""
import copy
import re

from frontend.components import animations as A
from frontend.simulation import player as playback
from frontend.simulation import player_view

# Robot [0,0] facing East with a clear row to the goal.
SIMPLE_WORLD = {"robot": [0, 0], "dir": "E", "goal": [3, 0], "walls": []}

# The default world's verified route (same plan as the app smoke tests).
DEFAULT_PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]


def _moves(timeline):
    return [event for event in timeline["events"] if event["type"] == "move"]


def _turns(timeline):
    return [event for event in timeline["events"] if event["type"] == "turn"]


# ---------------------------------------------------------------------------
# build_timeline
# ---------------------------------------------------------------------------

def test_forward_moves_cell_by_cell_at_300ms_each():
    timeline = playback.build_timeline(SIMPLE_WORLD, [{"cmd": "forward", "steps": 3}])

    moves = _moves(timeline)
    assert [event["to"] for event in moves] == [[1, 0], [2, 0], [3, 0]]
    assert [event["ms"] for event in moves] == [A.CELL_STEP_MS] * 3
    assert [event["start"] for event in moves] == [0, 300, 600]
    assert timeline["duration_ms"] == 900
    assert timeline["cells"] == 3
    assert timeline["reached"] is True
    assert timeline["ok"] is True
    assert timeline["halted"] is None


def test_path_lists_every_cell_the_robot_occupies_in_order():
    timeline = playback.build_timeline(SIMPLE_WORLD, [{"cmd": "forward", "steps": 2}])
    assert timeline["path"] == [[0, 0], [1, 0], [2, 0]]
    assert timeline["final_world"]["robot"] == [2, 0]


def test_turn_rotates_smoothly_then_the_next_action_waits_for_a_gap():
    timeline = playback.build_timeline(
        SIMPLE_WORLD, [{"cmd": "turn_right"}, {"cmd": "forward", "steps": 1}]
    )

    turn, move = _turns(timeline)[0], _moves(timeline)[0]
    assert (turn["from_dir"], turn["to_dir"]) == ("E", "S")
    assert turn["start"] == 0 and turn["ms"] == A.TURN_MS
    assert move["start"] == A.TURN_MS + A.STEP_GAP_MS
    assert (move["from"], move["to"]) == ([0, 0], [0, 1])
    assert timeline["duration_ms"] == A.TURN_MS + A.STEP_GAP_MS + A.CELL_STEP_MS


def test_steps_carry_the_simulators_own_labels_and_messages():
    timeline = playback.build_timeline(
        SIMPLE_WORLD, [{"cmd": "turn_right"}, {"cmd": "forward", "steps": 2}]
    )

    first, second = timeline["steps"]
    assert first["label"] == "turn right"
    assert first["message"] == "turned right"
    assert second["label"] == "forward ×2"
    assert second["message"] == "moved forward 2"
    # Step windows line up with their events.
    assert first["start_ms"] == 0 and first["end_ms"] == A.TURN_MS
    assert second["start_ms"] == A.TURN_MS + A.STEP_GAP_MS


def test_timeline_never_mutates_the_caller_world():
    world = copy.deepcopy(SIMPLE_WORLD)
    playback.build_timeline(world, [{"cmd": "forward", "steps": 3}])
    assert world == SIMPLE_WORLD


def test_blocked_forward_keeps_partial_progress_and_halts():
    world = {"robot": [0, 0], "dir": "E", "goal": [7, 0], "walls": [[2, 0]]}
    timeline = playback.build_timeline(world, [{"cmd": "forward", "steps": 5}])

    assert [event["to"] for event in _moves(timeline)] == [[1, 0]]
    assert timeline["ok"] is False
    assert timeline["halted"] == "blocked"
    assert timeline["reached"] is False
    assert timeline["final_world"]["robot"] == [1, 0]
    assert timeline["steps"][0]["halted"] == "blocked"
    assert timeline["log"][0]["message"].startswith("blocked")
    # A blocked action still gets a beat on screen so the failure is visible.
    assert timeline["events"][-1]["type"] == "hold"
    assert timeline["events"][-1]["halted"] == "blocked"


def test_unknown_command_halts_the_timeline():
    timeline = playback.build_timeline(SIMPLE_WORLD, [{"cmd": "teleport"}])

    assert timeline["halted"] == "unknown"
    assert timeline["ok"] is False
    assert _moves(timeline) == []
    assert timeline["events"][0]["type"] == "hold"
    assert timeline["steps"][0]["label"] == "teleport"
    assert timeline["duration_ms"] == A.HALT_MS


def test_default_world_plan_duration_is_turns_cells_and_gaps():
    from gemmabot.simulator import new_world

    timeline = playback.build_timeline(new_world(), DEFAULT_PLAN)
    turns, cells, gaps = len(_turns(timeline)), timeline["cells"], len(DEFAULT_PLAN) - 1

    assert timeline["duration_ms"] == turns * A.TURN_MS + cells * A.CELL_STEP_MS + gaps * A.STEP_GAP_MS
    assert timeline["reached"] is True
    assert timeline["final_world"]["robot"] == [6, 5]
    # Events are ordered and never overlap.
    ends = [event["start"] + event["ms"] for event in timeline["events"]]
    starts = [event["start"] for event in timeline["events"]]
    assert starts == sorted(starts)
    assert all(starts[i + 1] >= ends[i] for i in range(len(ends) - 1))


def test_every_move_event_carries_the_direction_it_was_made_in():
    timeline = playback.build_timeline(SIMPLE_WORLD, [{"cmd": "forward", "steps": 2}])
    assert {event["dir"] for event in _moves(timeline)} == {"E"}


def test_empty_plan_produces_an_empty_timeline():
    timeline = playback.build_timeline(SIMPLE_WORLD, [])
    assert timeline["events"] == []
    assert timeline["steps"] == []
    assert timeline["duration_ms"] == 0
    assert timeline["reached"] is False


def test_log_lines_keep_the_execution_log_format():
    timeline = playback.build_timeline(SIMPLE_WORLD, [{"cmd": "forward", "steps": 1}])
    assert playback.log_lines(timeline) == [
        "step 1: {'cmd': 'forward', 'steps': 1} -> moved forward 1"
    ]


# ---------------------------------------------------------------------------
# player_html
# ---------------------------------------------------------------------------

def _default_timeline():
    from gemmabot.simulator import new_world

    return playback.build_timeline(new_world(), DEFAULT_PLAN)


def test_player_html_draws_one_cell_per_grid_coordinate():
    html = player_view.player_html(_default_timeline())
    assert html.count("class='gb-pc gb-pc-") == 64
    assert html.count("id='gb-robot'") == 1
    assert html.count("data-x='0'") == 8


def test_player_html_is_self_contained():
    html = player_view.player_html(_default_timeline())
    assert "<script src" not in html
    assert "<link" not in html
    assert "@import" not in html
    assert "cdn" not in html.lower()
    assert "https://" not in html


def test_player_html_offers_play_pause_reset_and_all_speeds():
    html = player_view.player_html(_default_timeline(), speed=2.0)
    assert ">▶ Play</button>" in html or "&#9654; Play" in html
    assert "Reset" in html
    for option in A.SPEED_OPTIONS:
        assert f"data-speed='{option:g}'" in html
    assert "data-speed='2' aria-pressed='true'" in html
    assert "'(prefers-reduced-motion: reduce)'" in html
    assert "'r' === key" in html or "key === 'r'" in html


def test_player_html_embeds_timeline_state_for_the_runtime():
    timeline = _default_timeline()
    html = player_view.player_html(timeline, autoplay=False, cell_px=56)

    assert '"duration_ms":' + str(timeline["duration_ms"]) in html
    assert '"autoplay":false' in html
    assert '"cell_px":56' in html
    assert '"pitch":58' in html      # cell + 2px gap
    assert '"reached":true' in html
    assert "window.__TL__" in html


def test_player_html_escapes_a_script_break_in_model_supplied_labels():
    nasty = "</script><script>alert(1)</script>"
    timeline = playback.build_timeline(SIMPLE_WORLD, [{"cmd": nasty}])

    html = player_view.player_html(timeline)
    # Only the player's own closing tag survives, and the label is inert.
    assert html.count("</script>") == 1
    assert "<\\/script>" in html
    assert "&lt;/script&gt;" in html


def test_player_html_survives_an_empty_timeline():
    html = player_view.player_html(playback.build_timeline(SIMPLE_WORLD, []))
    assert "no actions to execute" in html
    assert html.count("class='gb-step gb-step-empty'") == 1
    assert "data-step=" not in html


def test_player_height_covers_the_stage_and_grows_with_the_cell():
    small, large = player_view.player_height(40), player_view.player_height(56)
    assert small > player_view.stage_px(40)
    assert large > small
    assert player_view.stage_px(40) == 7 * 42 + 40


def test_css_uses_design_tokens_not_literal_colors():
    from frontend.components import colors as C

    css = player_view._css(40)
    assert C.ACCENT_BLUE in css
    assert C.BG_BASE in css
    assert re.search(r"#0e0f11", css)            # BG_BASE as a value
