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


# ---------------------------------------------------------------------------
# Provenance — what the animation may claim
# ---------------------------------------------------------------------------

def _approved_plan():
    """A real ApprovedPlan: the guard verifies the default route itself."""
    from frontend.panels import engine
    from gemmabot.simulator import new_world

    return engine.approve(new_world(), DEFAULT_PLAN, instruction="go to the goal")


def _approved_timeline():
    return playback.build_approved_timeline(_approved_plan())


def _tampered_plan():
    """An approval whose digest no longer matches — the gate refuses it."""
    import dataclasses

    return dataclasses.replace(_approved_plan(), approval_id="not-the-digest")


def test_a_preview_timeline_is_not_an_approved_execution():
    from gemmabot.simulator import new_world

    timeline = playback.build_timeline(new_world(), DEFAULT_PLAN)
    assert timeline["approved"] is False
    assert timeline["refused"] is None


def test_an_approved_timeline_records_where_the_run_really_ended():
    timeline = _approved_timeline()

    assert timeline["approved"] is True
    assert timeline["refused"] is None
    assert timeline["planned"] == len(DEFAULT_PLAN)
    assert timeline["actions_run"] == len(DEFAULT_PLAN)
    assert timeline["unexecuted"] == 0
    assert timeline["halted_step"] is None
    assert timeline["final"] == [6, 5]
    assert timeline["final_dir"] == "N"
    assert timeline["reached"] is True


def test_a_halted_timeline_counts_the_plans_actions_not_the_captured_steps():
    """The simulator stops at the first refusal, so only the plan can say how
    many actions were never reached — the captured steps report zero of them."""
    world = {"robot": [0, 0], "dir": "E", "goal": [7, 0], "walls": [[2, 0]]}
    plan = [
        {"cmd": "forward", "steps": 5},
        {"cmd": "turn_left"},
        {"cmd": "forward", "steps": 2},
    ]
    timeline = playback.build_timeline(world, plan)

    assert timeline["planned"] == 3
    assert timeline["actions_run"] == 1          # the loop broke at the wall
    assert timeline["unexecuted"] == 2           # not 0: both later ones are pending
    assert timeline["halted_step"] == 1
    assert timeline["halted_label"] == "forward ×5"
    assert timeline["halted_message"] == "blocked at [1, 0]"
    assert timeline["halted_at"] == [1, 0]
    assert timeline["final"] == [1, 0]


def test_a_refused_approval_records_that_nothing_ran():
    timeline = playback.build_approved_timeline(_tampered_plan())

    assert timeline["refused"]
    assert timeline["approved"] is False
    assert timeline["steps"] == []
    assert timeline["events"] == []
    assert timeline["actions_run"] == 0
    assert timeline["unexecuted"] == len(DEFAULT_PLAN)   # the whole plan, untouched
    assert timeline["final"] == [0, 0]                   # never left the start


# ---------------------------------------------------------------------------
# outcome_copy — the outcome row's words
# ---------------------------------------------------------------------------

def test_outcome_copy_of_a_verified_run_states_goal_actions_duration_and_cell():
    from gemmabot.simulator import new_world

    copy = player_view.outcome_copy(_approved_timeline())

    assert copy["state"] == "reached"
    assert "Goal reached" in copy["terminal"]
    assert f"6 of {len(DEFAULT_PLAN)} executed" in copy["terminal"]
    assert "at 1×" in copy["terminal"]                # the duration, labelled
    assert "(6, 5) facing N" in copy["terminal"]
    assert "verified plan" in copy["ready"]
    # The preview of an unapproved plan is not an execution and says so.
    assert "not approve" in player_view.outcome_copy(
        playback.build_timeline(new_world(), DEFAULT_PLAN)
    )["ready"]


def test_outcome_copy_of_a_preview_never_claims_an_execution():
    world = {"robot": [0, 0], "dir": "E", "goal": [7, 0], "walls": [[2, 0]]}
    copy = player_view.outcome_copy(
        playback.build_timeline(world, [{"cmd": "forward", "steps": 5}])
    )

    assert copy["state"] == "halted"
    assert "unverified preview" in copy["ready"]
    assert "nothing was executed" in copy["ready"]
    # The reason is the simulator's own message, not a phrase this module chose.
    assert "blocked at [1, 0]" in copy["terminal"]
    assert "1 of 1 simulated" in copy["terminal"]
    assert "executed" not in copy["terminal"]


def test_outcome_copy_of_a_refused_approval_says_no_action_ran():
    copy = player_view.outcome_copy(
        playback.build_approved_timeline(_tampered_plan())
    )

    assert copy["state"] == "refused"
    assert "Refused" in copy["terminal"]
    assert "no action ran" in copy["terminal"]
    assert "never left (0, 0)" in copy["terminal"]
    # Nothing is playable, so there is no separate "ready" line to show.
    assert copy["ready"] == copy["terminal"]


def test_outcome_copy_of_an_empty_plan_says_there_is_nothing_to_play():
    copy = player_view.outcome_copy(playback.build_timeline(SIMPLE_WORLD, []))

    assert copy["state"] == "none"
    assert "no actions" in copy["terminal"]


# ---------------------------------------------------------------------------
# Step mode
# ---------------------------------------------------------------------------

def test_every_action_has_its_own_stop_point_for_step_mode_to_land_on():
    timeline = _approved_timeline()
    ends = [step["end_ms"] for step in timeline["steps"]]

    assert ends == sorted(ends)
    assert len(set(ends)) == len(ends)            # no two actions share a boundary
    assert ends[-1] == timeline["duration_ms"]    # the last step lands on the end
    assert all(step["end_ms"] > step["start_ms"] for step in timeline["steps"])


def test_the_transport_offers_step_beside_play_and_reset():
    html = player_view.player_html(_approved_timeline())

    assert "id='gb-step'" in html
    assert "&#9197; Step" in html
    assert "id='gb-play'" in html and "id='gb-reset'" in html
    assert "stepBtn.addEventListener('click', stepOnce)" in html


def test_step_moves_by_action_boundaries_and_stops_at_the_end():
    html = player_view.player_html(_approved_timeline())

    assert "function stepOnce" in html
    assert "function nextStepEnd" in html
    assert "TL.steps[i].end_ms > ms + 0.5" in html       # the next action's end
    assert "t = Math.min(TL.duration_ms, end);" in html   # never past the run
    # Stepping pauses first, so a step never races the animation loop.
    step_body = html.split("function stepOnce")[1].split("\n  }")[0]
    assert "pause();" in step_body


def test_step_is_disabled_when_there_is_nothing_to_step_through():
    html = player_view.player_html(playback.build_timeline(SIMPLE_WORLD, []))
    assert "stepBtn.disabled" in html
    assert "TL.duration_ms > 0 && TL.steps.length > 0" in html


def test_step_has_a_keyboard_shortcut():
    html = player_view.player_html(_approved_timeline())
    assert "key === 's' || key === 'S'" in html


def test_the_transport_keeps_to_one_row_at_any_host_width():
    """The Mission viewport column measures ~363px of usable width at a 1024px
    window, and the transport must fit it on one row: a second row would push
    the outcome line past the iframe height the caller computed from these same
    constants.  So every control keeps its natural width and the bar — the only
    stretchy item — gives all of it back, and nothing extra may be added.
    """
    from frontend.components import spacing as S

    html = player_view.player_html(_approved_timeline())
    css = player_view._css(40)

    assert ".gb-transport {\n  display: flex; flex-wrap: nowrap;" in css
    assert "flex: 1 1 0; height: 3px; min-width: 0" in css          # the bar
    assert "white-space: nowrap" in css                              # the controls
    # The tight paddings are what bought the room; both are load-bearing.
    assert f"padding: 5px {S.px(S.SM)};" in css
    assert f"padding: 5px {S.px(S.XS)};" in css
    # Five items, no more: play, step, reset, the speed group and the bar.
    for item in ("id='gb-play'", "id='gb-step'", "id='gb-reset'",
                 "class='gb-speed'", "class='gb-progress'"):
        assert item in html
    # The separate clock was ~44px this budget cannot spare; the outcome line
    # states the duration and the bar carries the progress.
    assert "gb-time" not in html
    assert "of ' + seconds(TL.duration_ms) + ' at 1×'" in html       # bar tooltip


# ---------------------------------------------------------------------------
# The outcome row
# ---------------------------------------------------------------------------

def test_the_outcome_row_shows_the_verdict_and_carries_the_full_sentence():
    html = player_view.player_html(_approved_timeline(), autoplay=False)

    assert "id='gb-outcome'" in html
    assert "data-state='reached'" in html
    assert "Goal reached" in html
    # The line ellipsises in a narrow frame, so the whole sentence is the title.
    assert "title='Goal reached" in html


def test_a_booting_run_shows_the_plan_line_not_a_verdict_it_has_not_reached():
    html = player_view.player_html(_approved_timeline(), autoplay=True)
    row = html.split("id='gb-outcome'")[1].split("</div>")[0]

    assert "data-state='ready'" in row
    assert "verified plan" in row and "press Play or Step" in row
    # The verdict is in the payload for the runtime to switch to, but the line
    # the reader sees before the first frame is not a claim about the run.
    assert "Goal reached" not in row


def test_a_finished_run_shows_the_verdict_instead_of_the_plan_line():
    html = player_view.player_html(_approved_timeline(), autoplay=False)
    row = html.split("id='gb-outcome'")[1].split("</div>")[0]

    assert "data-state='reached'" in row
    assert "Goal reached" in row
    assert "press Play or Step" not in row


def test_the_outcome_row_is_drawn_even_for_a_run_with_nothing_to_play():
    html = player_view.player_html(playback.build_timeline(SIMPLE_WORLD, []))

    assert "id='gb-outcome'" in html
    assert "data-state='none'" in html
    assert "no actions" in html


def test_the_outcome_row_rates_its_height_and_the_frame_covers_it():
    assert player_view.player_height(40) > player_view.stage_px(40) + player_view.OUTCOME_H
    assert player_view.player_height(40) > player_view.player_height(40) - 1


# ---------------------------------------------------------------------------
# Provenance in the document itself
# ---------------------------------------------------------------------------

def test_a_preview_is_labelled_a_preview_in_its_heading_and_tooltips():
    from gemmabot.simulator import new_world

    html = player_view.player_html(
        playback.build_timeline(new_world(), DEFAULT_PLAN)
    )

    assert "Simulation preview" in html
    assert "Execution playback" not in html
    # The control the reader is offered matches the provenance: a preview has no
    # verified action to advance, so its Step button must not promise one.
    assert "Advance one action of this preview (&amp;S)" in html
    assert "Advance one verified action (&amp;S)" not in html
    assert "Replay this preview of an unverified plan (&amp;space)" in html


def test_an_approved_run_says_execution_and_offers_a_verified_action():
    html = player_view.player_html(_approved_timeline())

    assert "Execution playback" in html
    assert "Advance one verified action" in html
    assert "Simulation preview" not in html


def test_the_payload_carries_provenance_the_outcome_copy_and_the_scope():
    html = player_view.player_html(_approved_timeline(), timeline_scope="mission")

    assert '"approved":true' in html
    assert '"timeline_scope":"mission"' in html
    assert '"copy":{' in html
    assert '"state":"reached"' in html


def test_a_player_with_no_scope_carries_none_and_marks_nothing():
    html = player_view.player_html(_approved_timeline())

    assert '"timeline_scope":""' in html
    assert "if (!TL.timeline_scope || window.parent === window) { return []; }" in html


def test_the_player_marks_the_host_timeline_it_was_pointed_at():
    html = player_view.player_html(_approved_timeline(), timeline_scope="mission")

    assert "function syncHost" in html
    assert "function markHost" in html
    assert "function hostRows" in html
    # It reaches only the timeline it was scoped to.
    assert "'.gb-tl[data-timeline=\"' + TL.timeline_scope + '\"] .gb-tl-row[data-action]'" in html
    assert "found[i].setAttribute('data-live', 'true')" in html
    assert "found[i].removeAttribute('data-live')" in html


def test_the_host_mark_never_rewrites_a_rows_own_state():
    """The console renders each row's state from the backend; the player owns
    only the question "which action is on screen now"."""
    html = player_view.player_html(_approved_timeline(), timeline_scope="mission")
    marking = html.split("function markHost")[1].split("function syncHost")[0]

    assert "setAttribute('data-live'" in marking
    assert "setAttribute('data-state'" not in marking
    assert "setAttribute('data-current'" not in marking
    assert "setAttribute('data-ok'" not in marking


def test_the_host_mark_is_cleared_when_the_run_finishes():
    html = player_view.player_html(_approved_timeline(), timeline_scope="mission")

    assert "var shown = finished ? 0 : shownStep(t);" in html
    # The first sync always runs, so a fresh player never leaves a stale mark.
    assert "lastPosted = 'unset'" in html


def test_the_action_shown_is_the_last_one_that_has_begun():
    """A readout that used the step list's notion of "active" would announce the
    action *before* the one a step landed on: at an exact boundary nothing is
    active, because the action is complete.  Every readout goes through one
    function with the boundary-inclusive rule instead."""
    html = player_view.player_html(_approved_timeline())

    assert "function shownStep(ms)" in html
    assert "if (TL.steps[i].start_ms <= ms + 0.5) { at = i + 1; }" in html
    assert "var shown = shownStep(ms);" in html      # the header readout
    assert "var index = shownStep(t);" in html       # the outcome line
    assert "var shown = finished ? 0 : shownStep(t);" in html   # the host mark
    # The step list keeps its own rule: there, a finished action is done.
    assert "var done = ms >= spec.end_ms;" in html


def test_an_unreachable_host_never_breaks_the_player():
    html = player_view.player_html(_approved_timeline(), timeline_scope="mission")

    assert "window.parent.document.querySelectorAll" in html
    assert "return [];   // not same-origin with the host: nothing to mark" in html


# ---------------------------------------------------------------------------
# The host timeline the playhead marks
# ---------------------------------------------------------------------------

def test_the_axis_labels_are_exactly_as_tall_and_wide_as_the_stage():
    """Seven full pitches plus one cell, so the numbers end where the cells end.

    Without this the label bands were a pitch taller than the stage they label,
    which pushed the transport and the outcome row past the iframe height the
    caller computed from the same constants.
    """
    html = player_view.player_html(_approved_timeline(), cell_px=40)

    assert 7 * player_view.pitch(40) + 40 == player_view.stage_px(40)
    assert "style='width:40px;height:20px'>7</div>" in html     # last column
    assert "style='width:28px;height:40px'>7</div>" in html     # last row
    assert "style='width:42px;height:20px'>0</div>" in html     # first column


def test_the_document_stays_self_contained_with_a_scope():
    html = player_view.player_html(_approved_timeline(), timeline_scope="mission")

    assert "<script src" not in html
    assert "https://" not in html
    assert html.count("<script") == 1


# ---------------------------------------------------------------------------
# Playback kinds — an execution, a demonstration and a replay are three things
# ---------------------------------------------------------------------------

def test_an_approved_run_declares_the_execution_kind():
    assert playback.kind_of(_approved_timeline()) == playback.KIND_EXECUTION


def test_a_demonstrated_plan_declares_the_preview_kind():
    from gemmabot.simulator import new_world

    timeline = playback.build_timeline(new_world(), DEFAULT_PLAN)
    assert playback.kind_of(timeline) == playback.KIND_PREVIEW


def test_a_replay_says_replay_and_claims_nothing_about_approval():
    """The log records a plan, not whether the guard approved it — so the replay
    line must describe the replay and stay silent on approval."""
    from gemmabot.simulator import new_world

    timeline = playback.build_timeline(
        new_world(), DEFAULT_PLAN, kind=playback.KIND_REPLAY
    )
    copy = player_view.outcome_copy(timeline)

    assert playback.kind_of(timeline) == playback.KIND_REPLAY
    assert "replay of a logged run" in copy["ready"]
    assert "not the original session" in copy["ready"]
    assert "approve" not in copy["ready"]
    assert "unverified preview" not in copy["ready"]


def test_each_kind_introduces_itself_differently_in_the_document():
    from gemmabot.simulator import new_world

    execution = player_view.player_html(_approved_timeline())
    preview = player_view.player_html(playback.build_timeline(new_world(), DEFAULT_PLAN))
    replay = player_view.player_html(
        playback.build_timeline(new_world(), DEFAULT_PLAN, kind=playback.KIND_REPLAY)
    )

    assert "Execution playback" in execution and "Run replay" not in execution
    assert "Simulation preview" in preview and "Run replay" not in preview
    assert "Run replay" in replay
    # The Step control never offers a verified action outside an execution.
    assert "Advance one verified action" in execution
    assert "Advance one verified action" not in preview
    assert "Advance one verified action" not in replay


def test_a_timeline_with_no_kind_is_read_as_a_preview():
    from gemmabot.simulator import new_world

    timeline = playback.build_timeline(new_world(), DEFAULT_PLAN)
    timeline.pop("kind")

    assert playback.kind_of(timeline) == playback.KIND_PREVIEW
    assert "unverified preview" in player_view.outcome_copy(timeline)["ready"]
    assert playback.kind_of({}) == playback.KIND_PREVIEW


def test_an_unrecognised_kind_falls_back_to_the_cautious_wording():
    from gemmabot.simulator import new_world

    timeline = playback.build_timeline(new_world(), DEFAULT_PLAN)
    timeline["kind"] = "something-else"

    assert playback.kind_of(timeline) == playback.KIND_PREVIEW
    assert "Simulation preview" in player_view.player_html(timeline)
