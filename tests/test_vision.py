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
# checks — the three verdicts stayed honest
# ---------------------------------------------------------------------------

def test_the_three_checks_are_the_ones_the_lab_displays():
    rows = vision.checks(new_world())
    assert [(row["id"], row["label"]) for row in rows] == [
        ("valid", "Valid"),
        ("in_bounds", "Inside bounds"),
        ("reachable", "Reachable"),
    ]


def test_a_validated_world_passes_all_three_checks():
    rows = vision.checks(new_world())
    assert [row["ok"] for row in rows] == [True, True, True]
    assert [row["mark"] for row in rows] == ["✓", "✓", "✓"]
    assert all(row["passed"] for row in rows)
    assert all(row["state"] == "success" for row in rows)


def test_no_reading_yet_is_unproven_not_a_failure():
    """Nothing has been read, which is a different statement from a bad read."""
    rows = vision.checks(None)
    assert [row["ok"] for row in rows] == [None, None, None]
    assert [row["mark"] for row in rows] == ["–", "–", "–"]
    assert all(row["detail"] == "no validated reading yet" for row in rows)
    assert not any(row["passed"] for row in rows)


def test_an_off_grid_goal_fails_bounds_and_leaves_reachability_unproven():
    rows = {row["id"]: row for row in vision.checks({**new_world(), "goal": [7, 8]})}
    assert rows["valid"]["ok"] is True            # the shape really is fine
    assert rows["in_bounds"]["ok"] is False
    assert rows["reachable"]["ok"] is None        # never searched, so never a pass
    assert rows["reachable"]["passed"] is False
    assert "not evaluated" in rows["reachable"]["detail"]


def test_an_unreachable_goal_fails_only_the_reachability_check():
    world = {"robot": [0, 0], "dir": "E", "goal": [7, 7],
             "walls": [[6, 7], [7, 6], [6, 6]]}
    rows = {row["id"]: row for row in vision.checks(world)}
    assert rows["valid"]["ok"] is True
    assert rows["in_bounds"]["ok"] is True
    assert rows["reachable"]["ok"] is False
    assert "unreachable" in rows["reachable"]["detail"]


def test_check_data_is_only_attached_to_a_failure():
    for world in (new_world(), {**new_world(), "goal": [7, 8]}, None):
        for row in vision.checks(world):
            if row["ok"] is not False:
                assert row["data"] == {}


def test_a_failed_check_carries_the_cell_behind_it():
    rows = {row["id"]: row for row in vision.checks({**new_world(), "goal": [7, 8]})}
    assert rows["in_bounds"]["data"]["cell"] == [7, 8]
    assert rows["in_bounds"]["data"]["field"] == "goal"


# ---------------------------------------------------------------------------
# world_rows — robot, goal, walls, direction
# ---------------------------------------------------------------------------

def test_world_rows_display_the_four_world_facts():
    world = new_world()
    rows = {row["id"]: row for row in vision.world_rows(world)}
    assert rows["robot"]["value"] == f"[{world['robot'][0]}, {world['robot'][1]}]"
    assert rows["goal"]["value"] == f"[{world['goal'][0]}, {world['goal'][1]}]"
    assert rows["walls"]["value"] == str(len(world["walls"]))
    assert rows["direction"]["value"] == "E ➡️"


def test_world_rows_never_show_a_default_map_when_nothing_was_read():
    rows = vision.world_rows(None)
    assert [row["value"] for row in rows] == ["—", "—", "—", "—"]
    assert all(row["detail"] == "not read yet" for row in rows)


@pytest.mark.parametrize("heading,arrow", [("N", "⬆️"), ("E", "➡️"),
                                           ("S", "⬇️"), ("W", "⬅️")])
def test_world_rows_show_the_readings_own_heading(heading, arrow):
    rows = {row["id"]: row for row in vision.world_rows({**new_world(), "dir": heading})}
    assert rows["direction"]["value"] == f"{heading} {arrow}"


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
# flow_stages — Image ↓ World ↓ Simulator
# ---------------------------------------------------------------------------

def test_the_flow_is_the_three_stages_in_order():
    assert vision.STAGES == ("Image", "World", "Simulator")
    stages = vision.flow_stages(has_image=False, world_ok=False, loaded=False)
    assert [stage["label"] for stage in stages] == ["Image", "World", "Simulator"]


def test_nothing_in_hand_leaves_the_first_stage_active_and_the_rest_pending():
    stages = vision.flow_stages(has_image=False, world_ok=False, loaded=False)
    assert [stage["state"] for stage in stages] == ["active", "pending", "pending"]


def test_a_validated_reading_hands_over_to_the_simulator_stage():
    stages = vision.flow_stages(has_image=True, world_ok=True, loaded=False)
    assert [stage["state"] for stage in stages] == ["done", "done", "active"]
    assert [stage["mark"] for stage in stages] == ["✓", "✓", "●"]


def test_loading_the_world_completes_the_flow():
    stages = vision.flow_stages(has_image=True, world_ok=True, loaded=True)
    assert [stage["state"] for stage in stages] == ["done", "done", "done"]
    assert [stage["mark"] for stage in stages] == ["✓", "✓", "✓"]


def test_the_flow_never_claims_a_later_stage_that_could_not_have_happened():
    """No image, no world, no load: the diagram cannot claim any of them."""
    stages = vision.flow_stages(has_image=False, world_ok=True, loaded=True)
    assert [stage["done"] for stage in stages] == [False, False, False]
    assert [stage["state"] for stage in stages] == ["active", "pending", "pending"]


def test_each_stage_carries_the_detail_it_was_given():
    stages = vision.flow_stages(
        has_image=True, world_ok=True, loaded=True,
        image_detail="maze.png · 9.2 kB",
        world_detail="reading passed 3 of 3 checks on attempt 2",
        sim_detail="active map: Scanned map (Vision Lab)",
    )
    assert [stage["detail"] for stage in stages] == [
        "maze.png · 9.2 kB",
        "reading passed 3 of 3 checks on attempt 2",
        "active map: Scanned map (Vision Lab)",
    ]


def test_a_waiting_stage_says_what_it_is_waiting_for():
    stages = vision.flow_stages(has_image=True, world_ok=False, loaded=False)
    assert stages[1]["detail"] == "no reading has passed validation yet"
    assert stages[2]["detail"] == "load the validated world to finish"


# ---------------------------------------------------------------------------
# flow_html — the animated diagram
# ---------------------------------------------------------------------------

def test_flow_html_stamps_each_stage_with_its_real_state():
    html = vision.flow_html(vision.flow_stages(has_image=True, world_ok=True,
                                               loaded=False))
    assert "data-stage='image' data-state='done'" in html
    assert "data-stage='world' data-state='done'" in html
    assert "data-stage='simulator' data-state='active'" in html


def test_flow_html_draws_the_downward_arrows_between_the_stages():
    html = vision.flow_html(vision.flow_stages(has_image=True, world_ok=True,
                                               loaded=True))
    assert html.count("↓") == 2
    assert html.index("data-stage='image'") < html.index("data-stage='world'")
    assert html.index("data-stage='world'") < html.index("data-stage='simulator'")


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
    assert "data-check='valid' data-ok='true'" in html
    assert "data-check='in_bounds' data-ok='false'" in html
    assert "data-check='reachable' data-ok='none'" in html
    assert "–" in html


def test_facts_html_labels_every_readout():
    html = vision.facts_html(vision.world_rows(new_world()))
    for row_id in ("robot", "goal", "walls", "direction"):
        assert f"data-fact='{row_id}'" in html


def test_meta_html_reports_the_reading_run():
    html = vision.meta_html("API (Gemini)", attempts=2, max_tries=2, latency=1.25)
    assert "API (Gemini)" in html
    assert "2 / 2" in html
    assert "1.25 s" in html
    assert "not sent to a model" not in html


def test_meta_html_discloses_scripted_readings():
    html = vision.meta_html("Scripted (dry mode)", attempts=2, max_tries=2,
                            latency=0.0, scripted=True)
    assert "Scripted (dry mode)" in html
    assert "scripted replies — the image is not sent to a model" in html


def test_meta_html_escapes_the_reader_label():
    html = vision.meta_html("<b>Reader</b>")
    assert "<b>" not in html
    assert "&lt;b&gt;" in html


# ---------------------------------------------------------------------------
# column framing + image metadata
# ---------------------------------------------------------------------------

def test_the_lab_frames_three_columns_left_to_right():
    assert list(vision.COLUMN_TITLES) == ["image", "vision", "world"]
    assert vision.COLUMN_TITLES["image"] == "Uploaded image"
    assert vision.COLUMN_TITLES["vision"] == "Gemma Vision"
    assert vision.COLUMN_TITLES["world"] == "World model"
    for kind in vision.COLUMN_TITLES:
        assert f"data-column='{kind}'" in vision.column_html(kind, "body")


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

    assert [row["ok"] for row in vision.checks(result["world"])] == [True] * 3
    assert vision.flow_stages(has_image=True, world_ok=True, loaded=False)[2][
        "state"] == "active"
    assert vision.world_rows(result["world"])[0]["value"] == "[0, 0]"
