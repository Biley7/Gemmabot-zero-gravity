"""Tests for backend/logger/logger.py — the run log's schema.

Every test writes to a temp file: the real ``logs/runs.jsonl`` is never touched.
"""
import json

import pytest

from gemmabot import logger as run_logger
from gemmabot.simulator import new_world

PLAN = [{"cmd": "turn_right"}, {"cmd": "forward", "steps": 7}]
HISTORY = [
    {"attempt": 1, "prompt": "p", "reply": "r", "ok": False, "feedback": "blocked"},
    {"attempt": 2, "prompt": "p2", "reply": "r2", "ok": True, "feedback": "ok",
     "actions": PLAN},
]


@pytest.fixture
def log_path(tmp_path):
    return str(tmp_path / "runs.jsonl")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_a_record_carries_everything_a_replay_needs(log_path):
    record = run_logger.log_run(
        "Move to the goal", "dry", PLAN, 2, HISTORY,
        latency=0.5, path=log_path, world=new_world(),
    )
    assert set(record) == {
        "timestamp", "instruction", "backend", "success", "attempts", "latency",
        "actions", "world", "history",
    }
    assert record["actions"] == PLAN
    assert record["world"] == new_world()
    assert record["success"] is True
    assert record["history"] == HISTORY


def test_the_plan_and_world_are_captured_by_value(log_path):
    """The caller can keep mutating its copies; the log does not follow."""
    world = new_world()
    actions = [{"cmd": "forward", "steps": 1}]
    record = run_logger.log_run("i", "dry", actions, 1, [], path=log_path,
                               world=world)
    world["robot"][0] = 7
    actions[0]["cmd"] = "turn_left"
    assert record["world"]["robot"] == [0, 0]
    assert record["actions"] == [{"cmd": "forward", "steps": 1}]
    # And that is what a reader gets back off disk.
    on_disk = run_logger.load_runs(path=log_path)[0]
    assert on_disk["world"]["robot"] == [0, 0]


def test_a_run_with_no_plan_records_none(log_path):
    record = run_logger.log_run("i", "api", None, 3, HISTORY[:1], latency=1.0,
                               path=log_path)
    assert record["success"] is False
    assert record["actions"] is None
    assert record["world"] is None


def test_a_world_that_is_not_a_dict_is_recorded_as_none(log_path):
    for value in ("not a world", [], 7, None):
        record = run_logger.log_run("i", "api", PLAN, 1, [], path=log_path,
                                   world=value)
        assert record["world"] is None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_runs_load_back_in_file_order(log_path):
    run_logger.log_run("first", "api", PLAN, 1, [], path=log_path, world=new_world())
    run_logger.log_run("second", "dry", PLAN, 1, [], path=log_path, world=new_world())
    loaded = run_logger.load_runs(path=log_path)
    assert [record["instruction"] for record in loaded] == ["first", "second"]
    assert all(record["world"] == new_world() for record in loaded)


def test_a_missing_log_reads_as_no_runs(tmp_path):
    assert run_logger.load_runs(path=str(tmp_path / "absent.jsonl")) == []


def test_a_corrupt_line_is_skipped_not_guessed(log_path, capsys):
    run_logger.log_run("good", "api", PLAN, 1, [], path=log_path)
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write("THIS IS NOT JSON\n")
    loaded = run_logger.load_runs(path=log_path)
    assert len(loaded) == 1
    assert loaded[0]["instruction"] == "good"
    assert "skipping corrupt line" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Redaction — the new fields must not open a leak
# ---------------------------------------------------------------------------

def test_a_key_in_any_string_field_is_redacted_before_disk(
    log_path, monkeypatch
):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
    record = run_logger.log_run(
        "use super-secret-key please",
        "api",
        PLAN,
        1,
        [{"attempt": 1, "prompt": "key super-secret-key", "reply": "super-secret-key",
          "ok": True, "feedback": "ok"}],
        path=log_path,
        world={"robot": [0, 0], "dir": "super-secret-key", "goal": [1, 1],
               "walls": []},
    )
    on_disk = open(log_path, encoding="utf-8").read()
    assert "super-secret-key" not in on_disk
    assert "<REDACTED>" in on_disk
    assert "super-secret-key" not in json.dumps(record)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_the_summary_still_reads_a_record_written_before_these_fields(log_path):
    """A log line without ``world``/``actions`` must summarize exactly as before."""
    legacy = {
        "timestamp": "2026-10-04T10:00:00+00:00",
        "instruction": "navigate to the goal",
        "backend": "api",
        "success": False,
        "attempts": 2,
        "latency": 3.07,
        "history": [
            {"attempt": 1, "prompt": "p", "reply": "r", "ok": False,
             "feedback": "blocked at [2, 0]"},
            {"attempt": 2, "prompt": "p", "reply": "r", "ok": False,
             "feedback": "blocked at [2, 0]"},
        ],
    }
    summary = run_logger.summarize_run(legacy)
    assert "Failed" in summary
    assert "api" in summary
    assert "3.07 s" in summary
    assert summary.count("Attempt") == 2


def test_the_summary_reports_a_successful_run_with_its_retry(log_path):
    record = run_logger.log_run("i", "ollama", PLAN, 2, HISTORY, latency=1.42,
                               path=log_path, world=new_world())
    summary = run_logger.summarize_run(record)
    assert "Succeeded" in summary
    assert "1.42 s" in summary
    assert "blocked" in summary          # the failed attempt is still reported
