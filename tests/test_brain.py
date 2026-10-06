"""Tests for the Gemma Brain panel (view model + HTML).

The panel is the app's structured readout of one planning run.  These tests
pin that every field it shows comes from the run's real values, that an
unproven check is never drawn as a pass, and that no model reasoning can reach
the panel at all.
"""
import inspect
import json

from backend.verifier.harness import VERIFICATION_CHECKS, verify_plan
from frontend.components import colors as C
from frontend.panels import brain
from gemmabot.simulator import new_world

PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]

# Real verifier output for that plan — all four checks genuinely pass.
PASSING_CHECKS = verify_plan(new_world(), PLAN)["checks"]

CHECK_LABELS = [label for _, label in VERIFICATION_CHECKS]


def _meta(**overrides) -> dict:
    kwargs = dict(
        backend="API (Gemini)",
        model="gemma-4-26b-a4b-it",
        status="executing",
        attempts=1,
        max_tries=3,
        latency=1.25,
        plan_actions=PLAN,
        checks=PASSING_CHECKS,
        steps=19,
        reached=True,
    )
    kwargs.update(overrides)
    return brain.brain_metadata(**kwargs)


# ---------------------------------------------------------------------------
# Model naming
# ---------------------------------------------------------------------------

def test_model_family_reads_the_configured_id():
    assert brain.model_family("gemma-4-26b-a4b-it") == "Gemma 4"
    assert brain.model_family("gemma4:e4b") == "Gemma 4"
    assert brain.model_family("gemma-3-27b-it") == "Gemma 3"
    assert brain.model_family("gemma2:9b") == "Gemma 2"


def test_unrecognised_and_missing_models_are_not_guessed():
    assert brain.model_family("llama3:8b") == "llama3:8b"
    assert brain.model_family("") == "—"
    assert brain.model_family(None) == "—"


# ---------------------------------------------------------------------------
# Metadata fields
# ---------------------------------------------------------------------------

def test_metadata_reports_the_real_run_numbers():
    meta = _meta()

    assert meta["model"]["family"] == "Gemma 4"
    assert meta["model"]["id"] == "gemma-4-26b-a4b-it"
    assert meta["backend"]["label"] == "API (Gemini)"
    assert meta["status"]["label"] == "Executing"
    assert meta["status"]["state"] == "running"
    assert meta["attempts"]["label"] == "1 / 3"
    assert meta["latency"]["label"] == "1.25 s"
    assert meta["plan"]["label"] == "6 actions"
    assert meta["verified"] is True


def test_status_keys_map_to_the_three_loop_states():
    expected = {
        "thinking": ("Thinking", "thinking"),
        "repairing": ("Repairing", "warning"),
        "executing": ("Executing", "running"),
    }
    for key, (label, state) in expected.items():
        meta = brain.brain_metadata(backend="API (Gemini)", status=key)
        assert meta["status"]["label"] == label
        assert meta["status"]["state"] == state


def test_an_unknown_status_falls_back_to_thinking():
    meta = brain.brain_metadata(backend="API (Gemini)", status="daydreaming")

    assert meta["status"]["key"] == "thinking"
    assert meta["status"]["label"] == "Thinking"


def test_missing_measurements_are_shown_as_unknown_not_as_zero():
    meta = brain.brain_metadata(backend="Auto (API → Ollama)", model=None)

    assert meta["latency"]["label"] == "—"
    assert meta["plan"]["label"] == "—"
    assert meta["model"]["family"] == "—"
    assert meta["model"]["id"] is None


def test_one_action_is_not_pluralised():
    meta = _meta(plan_actions=[{"cmd": "turn_left"}])

    assert meta["plan"]["label"] == "1 action"


def test_derived_details_use_the_run_itself():
    assert "19 simulator steps" in _meta()["status"]["detail"]
    repaired = brain.brain_metadata(
        backend="Ollama (local)",
        status="repairing",
        attempts=3,
        max_tries=3,
        error="blocked at [2, 0]",
    )
    assert "3 of 3" in repaired["status"]["detail"]
    assert "blocked at [2, 0]" in repaired["status"]["detail"]


def test_an_explicit_detail_wins():
    meta = _meta(detail="attempt 2/3 failed: blocked at [2, 0]")

    assert meta["status"]["detail"] == "attempt 2/3 failed: blocked at [2, 0]"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def test_checks_are_always_the_four_harness_checks_in_order():
    labels = [entry["label"] for entry in _meta(checks=None)["checks"]]

    assert labels == CHECK_LABELS
    assert [entry["ok"] for entry in _meta(checks=None)["checks"]] == [None] * 4


def test_a_missing_or_untyped_verdict_is_unproven_not_a_pass():
    meta = _meta(checks=[{"id": "in_bounds", "ok": "yes", "detail": "?"}])

    by_id = {entry["id"]: entry for entry in meta["checks"]}
    assert by_id["in_bounds"]["ok"] is None
    assert meta["verified"] is False


def test_a_failing_check_keeps_its_real_detail():
    failed = verify_plan(new_world(), [{"cmd": "forward", "steps": 5}])["checks"]
    meta = _meta(checks=failed, status="repairing", reached=False)

    by_id = {entry["id"]: entry for entry in meta["checks"]}
    assert by_id["no_collisions"]["ok"] is False
    assert "[3, 0]" in by_id["no_collisions"]["detail"]
    assert meta["verified"] is False


def test_live_status_comes_from_the_attempt_record():
    assert brain.attempt_status({"attempt": 1, "ok": False, "feedback": "blocked at [2, 0]"}, 3) == (
        "repairing",
        "attempt 1/3 failed: blocked at [2, 0]",
    )
    assert brain.attempt_status({"attempt": 2, "ok": True, "feedback": "ok"}, 3) == (
        "executing",
        "attempt 2/3 verified — executing the plan",
    )


def test_live_status_survives_an_incomplete_record():
    key, detail = brain.attempt_status({}, 3)

    assert key == "repairing"
    assert "0/3" in detail


# ---------------------------------------------------------------------------
# Panel HTML
# ---------------------------------------------------------------------------

def test_panel_renders_every_field_and_check():
    html = brain.brain_panel_html(_meta())

    assert "Gemma Brain" in html
    for label in ("Model", "Backend", "Status", "Attempts", "Latency", "Plan"):
        assert f"data-field='{label.lower()}'" in html
    for check_id, _ in VERIFICATION_CHECKS:
        assert f"data-check='{check_id}'" in html


def test_panel_marks_reflect_the_real_verdicts():
    html = brain.brain_panel_html(_meta())

    assert html.count("data-ok='true'") == 4
    assert html.count("data-ok='false'") == 0
    assert "✓" in html


def test_unproven_checks_are_drawn_as_unproven():
    html = brain.brain_panel_html(_meta(checks=None))

    assert html.count("data-ok='none'") == 4
    assert "✓" not in html
    assert "–" in html


def test_failing_checks_are_drawn_as_failures():
    failed = verify_plan(new_world(), [{"cmd": "forward", "steps": 5}])["checks"]
    html = brain.brain_panel_html(_meta(checks=failed))

    assert "data-ok='false'" in html
    assert "✗" in html


def test_panel_escapes_untrusted_text():
    html = brain.brain_panel_html(
        _meta(detail="<script>alert('x')</script>", checks=None)
    )

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_panel_is_self_contained():
    html = brain.brain_panel_html(_meta())

    assert "<script src" not in html.lower()
    assert "<link" not in html.lower()
    assert "@import" not in html.lower()
    assert "http://" not in html.lower()
    assert "https://" not in html.lower()


def test_panel_styles_come_from_the_design_tokens():
    passing = brain.brain_panel_html(_meta())
    failing = brain.brain_panel_html(
        _meta(checks=verify_plan(new_world(), [{"cmd": "forward", "steps": 5}])["checks"])
    )

    for token in (C.SUCCESS, C.TEXT_MUTED, C.BORDER_SUBTLE, C.TELEMETRY_VALUE, C.BG_SURFACE):
        assert token in passing
    assert C.ERROR in failing
    # Design-system parts, not hand-rolled containers.
    assert "gb-panel" in passing
    assert "gb-status-chip" in passing


# ---------------------------------------------------------------------------
# No chain of thought
# ---------------------------------------------------------------------------

THOUGHT = "SECRET-drive-east-then-north-because-of-the-wall"


def _run_result() -> dict:
    """A realistic engine.run_plan() result — transcripts and all."""
    return {
        "actions": PLAN,
        "attempts": 2,
        "latency": 1.25,
        "backend": "api",
        "error": None,
        "history": [
            {
                "attempt": 1,
                "prompt": "go to the goal",
                "reply": json.dumps({"thought": THOUGHT, "actions": []}),
                "actions": [{"cmd": "forward", "steps": 5}],
                "ok": False,
                "feedback": "blocked at [2, 0]",
            },
            {
                "attempt": 2,
                "prompt": "go to the goal\n\nYour previous plan failed.",
                "reply": json.dumps({"thought": THOUGHT, "actions": PLAN}),
                "actions": PLAN,
                "ok": True,
                "feedback": "ok",
            },
        ],
    }


def test_panel_renders_no_part_of_the_model_transcript():
    """The panel is built from structured fields only: a run's raw replies
    (which carry the model's reasoning) cannot reach it."""
    result = _run_result()
    meta = brain.run_metadata(
        backend_label="API (Gemini)",
        model="gemma-4-26b-a4b-it",
        verification={**verify_plan(new_world(), PLAN), "actions": PLAN},
        actions=result["actions"],
        attempts=result["attempts"],
        max_tries=3,
        latency=result["latency"],
        steps=19,
        reached=True,
        error=result["error"],
    )
    html = brain.brain_panel_html(meta)

    assert THOUGHT not in html
    assert "Your previous plan failed" not in html
    assert "prompt" not in html.lower()
    assert "reply" not in html.lower()


def test_run_metadata_reads_only_the_verified_plan():
    result = _run_result()
    meta = brain.run_metadata(
        backend_label="Ollama (local)",
        model="gemma4:e4b",
        verification={**verify_plan(new_world(), PLAN), "actions": PLAN},
        actions=result["actions"],
        attempts=2,
        max_tries=3,
        latency=0.75,
        steps=19,
        reached=True,
    )

    assert meta["plan"]["label"] == "6 actions"
    assert meta["verified"] is True
    assert meta["status"]["key"] == "executing"


def test_run_metadata_without_a_plan_stays_repairing_and_unproven():
    meta = brain.run_metadata(
        backend_label="API (Gemini)",
        model="gemma-4-26b-a4b-it",
        verification=None,
        actions=None,
        attempts=3,
        max_tries=3,
        latency=2.0,
        error="could not parse reply as JSON",
    )

    assert meta["status"]["key"] == "repairing"
    assert "could not parse reply as JSON" in meta["status"]["detail"]
    assert [entry["ok"] for entry in meta["checks"]] == [None] * 4
    assert meta["plan"]["label"] == "—"


def test_metadata_has_no_parameter_that_could_carry_a_reasoning_transcript():
    """The panel cannot leak a transcript: nothing feedable to it holds one."""
    for function in (brain.brain_metadata, brain.run_metadata):
        parameters = set(inspect.signature(function).parameters)
        assert not parameters & {"history", "reply", "thought", "prompt", "raw", "text"}
