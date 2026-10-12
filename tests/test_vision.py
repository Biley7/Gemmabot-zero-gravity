"""Tests for frontend/panels/vision.py — the Vision Lab.

No Streamlit, no network: every world is a plain dict and every reading comes
from a fake ask_vision (or the dry reader, whose replies are scripted but whose
pipeline is real).
"""
import pytest

import engine
from gemmabot.simulator import new_world
from frontend.panels import vision

WALL_COLUMN = [[3, 0], [3, 1], [3, 2], [3, 3]]


# ---------------------------------------------------------------------------
# checks — the five verdicts stayed honest
# ---------------------------------------------------------------------------

def test_the_five_checks_are_the_ones_the_lab_displays():
    rows = vision.checks(new_world())
    assert [(row["id"], row["label"]) for row in rows] == [
        ("bounds", "8×8 bounds"),
        ("robot", "Robot valid"),
        ("goal", "Goal valid"),
        ("overlaps", "No overlaps"),
        ("reachable", "Reachable"),
    ]


def test_a_validated_world_passes_all_five_checks():
    rows = vision.checks(new_world())
    assert [row["ok"] for row in rows] == [True] * 5
    assert [row["mark"] for row in rows] == ["✓"] * 5
    assert all(row["passed"] for row in rows)
    assert all(row["state"] == "success" for row in rows)


def test_no_reading_yet_is_unproven_not_a_failure():
    """Nothing has been read, which is a different statement from a bad read."""
    rows = vision.checks(None)
    assert [row["ok"] for row in rows] == [None] * 5
    assert [row["mark"] for row in rows] == ["–"] * 5
    assert all(row["detail"] == "no reading to check yet" for row in rows)
    assert not any(row["passed"] for row in rows)


def test_an_off_grid_goal_fails_bounds_and_leaves_reachability_unproven():
    rows = {row["id"]: row for row in vision.checks({**new_world(), "goal": [7, 8]})}
    assert rows["robot"]["ok"] is True             # the robot really is fine
    assert rows["goal"]["ok"] is True              # and the goal cell is a cell
    assert rows["overlaps"]["ok"] is True
    assert rows["bounds"]["ok"] is False
    assert rows["reachable"]["ok"] is None        # never searched, so never a pass
    assert rows["reachable"]["passed"] is False
    assert "not evaluated" in rows["reachable"]["detail"]


def test_an_unreachable_goal_fails_only_the_reachability_check():
    world = {"robot": [0, 0], "dir": "E", "goal": [7, 7],
             "walls": [[6, 7], [7, 6], [6, 6]]}
    rows = {row["id"]: row for row in vision.checks(world)}
    assert [rows[c]["ok"] for c in ("bounds", "robot", "goal", "overlaps")] == [True] * 4
    assert rows["reachable"]["ok"] is False
    assert "unreachable" in rows["reachable"]["detail"]


def test_check_data_is_only_attached_to_a_failure():
    for world in (new_world(), {**new_world(), "goal": [7, 8]}, None):
        for row in vision.checks(world):
            if row["ok"] is not False:
                assert row["data"] == {}


def test_a_failed_check_carries_the_cell_behind_it():
    rows = {row["id"]: row for row in vision.checks({**new_world(), "goal": [7, 8]})}
    assert rows["bounds"]["data"]["cell"] == [7, 8]
    assert rows["bounds"]["data"]["field"] == "goal"


# ---------------------------------------------------------------------------
# world_verdict — ✓ WORLD ACCEPTED / ✕ WORLD REJECTED
# ---------------------------------------------------------------------------

def test_an_accepted_world_says_so_and_claims_all_five_checks():
    decision = vision.world_verdict(vision.validation(new_world()))
    assert decision["key"] == "accepted"
    assert decision["label"] == "✓ WORLD ACCEPTED"
    assert decision["state"] == "success"
    assert "5 checks passed" in decision["detail"]
    assert decision["reason"] == ""


def test_a_refused_world_carries_the_validators_own_reason():
    rows = vision.checks({**new_world(), "goal": [7, 8]})
    decision = vision.world_verdict(
        vision.validation({**new_world(), "goal": [7, 8]})
    )
    assert decision["key"] == "rejected"
    assert decision["label"] == "✕ WORLD REJECTED"
    assert decision["check"] == "bounds"
    assert decision["check_label"] == "8×8 bounds"
    # The exact deterministic sentence, not a paraphrase of the check's label.
    assert decision["reason"] == "goal position [7, 8] is outside the 8×8 grid"
    assert decision["reason"] == next(r for r in rows if r["id"] == "bounds")["detail"]


def test_the_verdict_and_the_rows_always_tell_the_same_story():
    corpus = [
        new_world(),
        {**new_world(), "goal": [7, 8]},
        {**new_world(), "goal": [3, 1]},
        {"robot": [0, 0], "dir": "E", "goal": [7, 7],
         "walls": [[6, 7], [7, 6], [6, 6]]},
        {"robot": [0, 0]},
    ]
    for world in corpus:
        result = vision.validation(world)
        decision = vision.world_verdict(result)
        failing = [row for row in result["rows"] if row["ok"] is False]
        assert (decision["key"] == "rejected") is bool(failing)
        if failing:
            assert decision["reason"] == result["reason"]
        assert (decision["key"] == "accepted") is all(
            row["ok"] is True for row in result["rows"]
        )


def test_no_reading_is_not_a_rejection():
    decision = vision.world_verdict(vision.validation(None))
    assert decision["key"] == "none"
    assert decision["label"] == "NOT VALIDATED"
    assert decision["reason"] == ""


def test_verdict_html_escapes_its_reason():
    world = {"robot": [0, 0], "dir": "E", "goal": [3, 1],
             "walls": [[3, 0], [3, 1]]}
    html = vision.verdict_html(vision.world_verdict(vision.validation(world)))
    assert "data-verdict='rejected'" in html
    assert "✕ WORLD REJECTED" in html
    assert "goal [3, 1] is on a wall" in html
    assert "data-check='overlaps'" in html


def test_verdict_html_carries_no_reason_under_an_acceptance():
    html = vision.verdict_html(vision.world_verdict(vision.validation(new_world())))
    assert "data-verdict='accepted'" in html
    assert "gb-vision-reason" not in html


# ---------------------------------------------------------------------------
# world_rows — robot, goal, walls, direction
# ---------------------------------------------------------------------------

def test_world_rows_display_the_four_world_facts():
    world = new_world()
    rows = {row["id"]: row for row in vision.world_rows(world)}
    assert list(rows) == ["robot", "heading", "goal", "walls"]
    assert rows["robot"]["value"] == f"[{world['robot'][0]}, {world['robot'][1]}]"
    assert rows["heading"]["value"] == "E ➡️"
    assert rows["goal"]["value"] == f"[{world['goal'][0]}, {world['goal'][1]}]"
    assert rows["walls"]["value"] == str(len(world["walls"]))


def test_world_rows_never_show_a_default_map_when_nothing_was_read():
    rows = vision.world_rows(None)
    assert [row["value"] for row in rows] == ["—", "—", "—", "—"]
    assert all(row["detail"] == "not read yet" for row in rows)


@pytest.mark.parametrize("heading,arrow", [("N", "⬆️"), ("E", "➡️"),
                                           ("S", "⬇️"), ("W", "⬅️")])
def test_world_rows_show_the_readings_own_heading(heading, arrow):
    rows = {row["id"]: row for row in vision.world_rows({**new_world(), "dir": heading})}
    assert rows["heading"]["value"] == f"{heading} {arrow}"


def test_world_rows_escape_hostile_values():
    rows = vision.world_rows({**new_world(), "dir": "<img src=x onerror=alert(1)>"})
    rendered = vision.facts_html(rows)
    assert "<img" not in rendered
    assert "&lt;img" in rendered


# ---------------------------------------------------------------------------
# readings — the Gemma Vision column
# ---------------------------------------------------------------------------

def _history(records):
    return [dict(record, prompt="read the maze") for record in records]


def test_readings_keep_the_reply_the_parsed_world_and_the_verdict():
    items = vision.readings(_history([
        {"attempt": 1, "reply": '{"robot": [0, 0], "dir": "E", "goal": [7, 8],'
                                ' "walls": [[3, 0]]}', "ok": False,
         "feedback": "goal position [7, 8] is outside the 8×8 grid"},
        {"attempt": 2, "reply": '{"robot": [0, 0], "dir": "E", "goal": [6, 5],'
                                ' "walls": []}', "ok": True, "feedback": "ok"},
    ]))
    assert [item["status"] for item in items] == ["FAIL", "OK"]
    assert [item["mark"] for item in items] == ["✕", "✓"]
    assert items[0]["world"]["goal"] == [7, 8]
    assert "outside the 8×8 grid" in items[0]["error"]
    assert items[1]["error"] is None
    assert items[1]["world"]["goal"] == [6, 5]


def test_a_garbled_reply_is_a_reading_with_no_world():
    items = vision.readings(_history([
        {"attempt": 1, "reply": "I think the robot is top-left.", "ok": False,
         "feedback": "could not parse reply as JSON: No JSON object found"},
    ]))
    assert items[0]["world"] is None
    assert items[0]["ok"] is False
    assert "json" in items[0]["error"].lower()


def test_readings_html_shows_the_reply_verbatim_and_escaped():
    nasty = '{"robot": [0, 0]} <script>alert(1)</script>'
    html = vision.readings_html(vision.readings(_history([
        {"attempt": 1, "reply": nasty, "ok": False, "feedback": "no JSON object"},
    ])))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "data-attempt='1'" in html
    assert "data-ok='false'" in html


def test_readings_html_says_so_before_any_reading():
    html = vision.readings_html([])
    assert "No reading has been attempted yet." in html


# ---------------------------------------------------------------------------
# flow_stages — the six steps of the product story
# ---------------------------------------------------------------------------

def test_the_flow_is_the_product_story_in_order():
    assert vision.STAGES == (
        "Hand-drawn environment",
        "Vision model",
        "World representation",
        "Deterministic validation",
        "Simulation",
        "Robot execution",
    )
    stages = vision.flow_stages(has_image=False, world_ok=False, loaded=False)
    assert [stage["label"] for stage in stages] == list(vision.STAGES)


def test_nothing_in_hand_leaves_the_first_stage_active_and_the_rest_pending():
    stages = vision.flow_stages(has_image=False, world_ok=False, loaded=False)
    assert [stage["state"] for stage in stages] == ["active"] + ["pending"] * 5


def test_a_validated_reading_hands_over_to_the_simulation_stage():
    stages = vision.flow_stages(
        has_image=True, replied=True, parsed=True, world_ok=True, loaded=False
    )
    assert [stage["state"] for stage in stages] == ["done"] * 4 + ["active", "pending"]
    assert [stage["mark"] for stage in stages] == ["✓"] * 4 + ["●", "○"]


def test_loading_the_world_leaves_only_the_robot_execution_stage():
    stages = vision.flow_stages(
        has_image=True, replied=True, parsed=True, world_ok=True, loaded=True
    )
    assert [stage["state"] for stage in stages] == ["done"] * 5 + ["active"]


def test_running_a_plan_on_the_loaded_world_completes_the_story():
    stages = vision.flow_stages(
        has_image=True, replied=True, parsed=True, world_ok=True,
        loaded=True, executed=True,
    )
    assert [stage["state"] for stage in stages] == ["done"] * 6
    assert [stage["mark"] for stage in stages] == ["✓"] * 6


def test_the_flow_never_claims_a_later_stage_that_could_not_have_happened():
    """No image, no world, no load: the diagram cannot claim any of them."""
    stages = vision.flow_stages(
        has_image=False, replied=True, parsed=True, world_ok=True,
        loaded=True, executed=True,
    )
    assert [stage["done"] for stage in stages] == [False] * 6
    assert [stage["state"] for stage in stages] == ["active"] + ["pending"] * 5


def test_the_story_never_lights_validation_without_a_parsed_world():
    """A reply that parsed into nothing cannot have been validated."""
    stages = vision.flow_stages(
        has_image=True, replied=True, parsed=False, world_ok=False, loaded=False
    )
    assert [stage["state"] for stage in stages] == (
        ["done", "done", "active"] + ["pending"] * 3
    )


def test_each_stage_carries_the_detail_it_was_given():
    stages = vision.flow_stages(
        has_image=True, replied=True, parsed=True, world_ok=True, loaded=True,
        executed=True,
        image_detail="maze.png · 9.2 kB",
        vision_detail="Scripted (dry mode) · scripted reading",
        world_detail="7 obstacles · robot [0, 0] facing E · goal [6, 5]",
        validation_detail="reading passed 5 of 5 checks on attempt 2",
        sim_detail="active map: Scanned map (Vision Lab)",
        execution_detail="a plan has run on this world",
    )
    assert [stage["detail"] for stage in stages] == [
        "maze.png · 9.2 kB",
        "Scripted (dry mode) · scripted reading",
        "7 obstacles · robot [0, 0] facing E · goal [6, 5]",
        "reading passed 5 of 5 checks on attempt 2",
        "active map: Scanned map (Vision Lab)",
        "a plan has run on this world",
    ]


def test_a_waiting_stage_says_what_it_is_waiting_for():
    stages = vision.flow_stages(has_image=True, world_ok=False, loaded=False)
    assert stages[1]["detail"] == "no request has been made yet"
    assert stages[2]["detail"] == "no world has been parsed yet"
    assert stages[3]["detail"] == "no reading has passed validation yet"
    assert stages[4]["detail"] == "load the validated world to finish"
    assert stages[5]["detail"] == "run a plan in Mission to finish"


# ---------------------------------------------------------------------------
# flow_html — the animated diagram
# ---------------------------------------------------------------------------

def test_flow_html_stamps_each_stage_with_its_real_state():
    html = vision.flow_html(vision.flow_stages(
        has_image=True, replied=True, parsed=True, world_ok=True, loaded=False
    ))
    assert "data-stage='image' data-state='done'" in html
    assert "data-stage='vision' data-state='done'" in html
    assert "data-stage='world' data-state='done'" in html
    assert "data-stage='validation' data-state='done'" in html
    assert "data-stage='simulation' data-state='active'" in html
    assert "data-stage='execution' data-state='pending'" in html


def test_flow_html_draws_the_downward_arrows_between_the_stages():
    html = vision.flow_html(vision.flow_stages(
        has_image=True, replied=True, parsed=True, world_ok=True, loaded=True
    ))
    assert html.count("↓") == 5
    order = [
        html.index(f"data-stage='{key}'") for key in vision._STAGE_KEYS
    ]
    assert order == sorted(order)


def test_flow_html_animates_with_design_system_tokens():
    from frontend.components import animations as A

    html = vision.flow_html(vision.flow_stages(has_image=True, world_ok=True,
                                               loaded=False))
    assert "gb-fade-in" in html
    assert A.animation_pulse() in html        # the active stage breathes
    assert "120ms" in html and "240ms" in html  # the stagger is the token's


def test_only_the_active_stage_pulses():
    html = vision.flow_html(vision.flow_stages(has_image=False, world_ok=False,
                                               loaded=False))
    assert html.count("gb-pulse") == 1


# ---------------------------------------------------------------------------
# checks_html / facts_html / meta_html
# ---------------------------------------------------------------------------

def test_checks_html_marks_every_check_with_its_own_verdict():
    html = vision.checks_html(vision.checks({**new_world(), "goal": [7, 8]}))
    assert "data-check='robot' data-ok='true'" in html
    assert "data-check='goal' data-ok='true'" in html
    assert "data-check='overlaps' data-ok='true'" in html
    assert "data-check='bounds' data-ok='false'" in html
    assert "data-check='reachable' data-ok='none'" in html
    assert "–" in html


def test_facts_html_labels_every_readout():
    html = vision.facts_html(vision.world_rows(new_world()))
    for row_id in ("robot", "heading", "goal", "walls"):
        assert f"data-fact='{row_id}'" in html


def test_meta_html_reports_the_reading_run():
    html = vision.meta_html("API (Gemini)", attempts=2, max_tries=2, latency=1.25,
                            request="live")
    assert "API (Gemini)" in html
    assert "2 / 2" in html
    assert "1.25 s" in html
    assert "data-kind='live'" in html
    assert "no image left this app" not in html


def test_meta_html_discloses_scripted_readings():
    html = vision.meta_html("Scripted (dry mode)", attempts=2, max_tries=2,
                            latency=0.0, scripted=True)
    assert "Scripted (dry mode)" in html
    assert "data-kind='scripted'" in html
    assert "no image left this app" in html


def test_request_kind_never_claims_a_live_call_without_one():
    assert vision.request_kind(ran=False, backend="dry", dry_backend="dry") == "none"
    assert vision.request_kind(ran=True, backend="dry", dry_backend="dry") == "scripted"
    assert vision.request_kind(ran=True, backend="api", dry_backend="dry") == "live"


def test_a_not_yet_run_reading_is_not_a_live_claim():
    decision = vision.reader_status("none")
    assert decision["live"] is False
    assert "no request yet" in decision["label"]
    assert vision.reader_status("scripted")["live"] is False
    assert vision.reader_status("live")["live"] is True


def test_an_unknown_request_kind_is_never_a_live_claim():
    assert vision.reader_status("whatever")["kind"] == "none"
    assert vision.reader_status("whatever")["live"] is False


def test_meta_html_escapes_the_reader_label():
    html = vision.meta_html("<b>Reader</b>")
    assert "<b>" not in html
    assert "&lt;b&gt;" in html


# ---------------------------------------------------------------------------
# column framing + image metadata
# ---------------------------------------------------------------------------

def test_the_lab_frames_three_columns_left_to_right():
    assert list(vision.COLUMN_TITLES) == ["image", "world", "validation"]
    assert vision.COLUMN_TITLES["image"] == "Input image"
    assert vision.COLUMN_TITLES["world"] == "Detected world"
    assert vision.COLUMN_TITLES["validation"] == "Validation"
    for kind in vision.COLUMN_TITLES:
        assert f"data-column='{kind}'" in vision.column_html(kind, "body")


def test_the_last_step_of_the_story_is_loading_into_mission():
    assert vision.LOAD_LABEL == "Load into Mission"
    assert vision.REPLY_TITLE == "Gemma Vision"


def test_image_rows_describe_the_bytes_that_were_read():
    rows = {row["id"]: row for row in vision.image_rows(
        name="maze.png", size=9468, mime="image/png", source="uploaded photo"
    )}
    assert rows["name"]["value"] == "maze.png"
    assert rows["name"]["detail"] == "uploaded photo"
    assert rows["size"]["value"] == "9.2 kB"
    assert rows["type"]["value"] == "image/png"


@pytest.mark.parametrize("size,label", [(512, "512 B"), (2048, "2.0 kB"), (None, "—")])
def test_image_size_formatting(size, label):
    rows = {row["id"]: row for row in vision.image_rows(
        name="m", size=size, mime="image/png", source="s"
    )}
    assert rows["size"]["value"] == label


# ---------------------------------------------------------------------------
# sample_image_bytes — a real raster, drawn in the prompt's own terms
# ---------------------------------------------------------------------------

def test_the_sample_is_a_real_png():
    data = vision.sample_image_bytes(new_world())
    if data is None:
        pytest.skip("Pillow is not installed")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 1000


def test_the_sample_is_deterministic():
    first = vision.sample_image_bytes(new_world())
    second = vision.sample_image_bytes(new_world())
    if first is None:
        pytest.skip("Pillow is not installed")
    assert first == second


@pytest.mark.parametrize(
    "world",
    [
        {},
        {"robot": "x", "goal": "y", "walls": "lots"},
        {"robot": [0, 0], "goal": [99, 99], "walls": [[99, 99], None], "dir": "Q"},
        {"robot": [0, 0], "goal": [6, 5], "walls": [], "dir": "N"},
    ],
)
def test_the_sample_survives_a_malformed_world(world):
    """Drawing must not explode on junk, but it only ever draws real PNG bytes."""
    data = vision.sample_image_bytes(world)
    if data is None:
        pytest.skip("Pillow is not installed")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# end to end: the dry reader through the real pipeline into the lab
# ---------------------------------------------------------------------------

def test_a_dry_run_reads_a_world_the_lab_then_validates():
    result = engine.run_map_vision(b"\x00", "image/png", backend="dry", max_tries=2)

    assert result["backend"] == "dry"
    assert result["attempts"] == 2
    assert result["world"] == new_world()

    # The first reading is a real rejection by the real validator; the second is
    # accepted, with the failure reason carried into its prompt.
    assert [record["ok"] for record in result["history"]] == [False, True]
    assert "outside the 8×8 grid" in result["history"][0]["feedback"]
    assert "outside the 8×8 grid" in result["history"][1]["prompt"]

    assert [row["ok"] for row in vision.checks(result["world"])] == [True] * 5
    stages = vision.flow_stages(
        has_image=True, replied=True, parsed=True, world_ok=True, loaded=False
    )
    assert stages[4]["state"] == "active"
    assert vision.world_rows(result["world"])[0]["value"] == "[0, 0]"
