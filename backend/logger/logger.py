"""Run logger for GemmaBot.

Owner: BACKEND

Public API
----------
log_run(instruction, backend, actions, attempts, history,
        latency=None, path="logs/runs.jsonl", world=None,
        mode=None) -> dict
    Appends one JSONL record to *path* and returns it.

load_runs(path="logs/runs.jsonl") -> list[dict]
    Returns all records from *path*, newest last.  [] if file missing.

summarize_run(record) -> str
    One human-readable paragraph suitable for a UI panel.

Record schema
-------------
timestamp, instruction, backend, success, attempts, latency, actions, world,
mode, history.  ``actions`` is the validated plan and ``world`` the world it was
verified and executed against — together they let a run be replayed by the
simulator alone, with no model call.  ``world`` is ``None`` when the caller did
not supply one, and both keys are absent from records written before they were
added: a reader must treat missing as "not captured", never as a guess.

``mode`` records whether the run really called a model — ``"live"`` — or was
answered by a scripted reader — ``"synthetic"``.  Only the caller knows which,
so it is recorded verbatim and never derived here; anything other than those two
values is stored as ``None``, which a reader must show as *provenance not
recorded* rather than assume either way.  Older records have no ``mode`` key at
all.  This is what lets a benchmark separate live measurements from scripted
ones instead of quietly mixing them.

Security
--------
Any string that matches the value of the GEMINI_API_KEY env-var is
automatically redacted before it reaches disk or the summary string.
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------

def _redact(text: str) -> str:
    """Replace the live API key value with ``<REDACTED>`` if present."""
    key = os.getenv("GEMINI_API_KEY", "")
    if key and key in text:
        text = text.replace(key, "<REDACTED>")
    return text


def redact_secrets(text: str) -> str:
    """Public: scrub the configured API key from *text* before it is shown.

    The logger redacts everything it writes; this is the same scrub for text
    that never touches disk (e.g. an exception message echoed into the UI).
    """
    return _redact(str(text))


def _redact_record(record: dict) -> dict:
    """Return a copy of *record* with API key values scrubbed from strings."""
    r = copy.deepcopy(record)
    _scrub(r)
    return r


def _scrub(obj: Any) -> None:
    """Mutate *obj* in-place, redacting secrets from all string leaves."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                obj[k] = _redact(v)
            else:
                _scrub(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str):
                obj[i] = _redact(v)
            else:
                _scrub(v)


# ---------------------------------------------------------------------------
# log_run
# ---------------------------------------------------------------------------

def log_run(
    instruction: str,
    backend: str,
    actions: list[dict] | None,
    attempts: int,
    history: list[dict],
    latency: float | None = None,
    path: str = "logs/runs.jsonl",
    world: dict | None = None,
    mode: str | None = None,
) -> dict:
    """Build and persist one run record.

    Parameters
    ----------
    instruction:
        The original plain-English instruction given to the planner.
    backend:
        Model backend used, e.g. ``"ollama"`` or ``"api"``.
    actions:
        The validated action list on success, or ``None`` on failure.
    attempts:
        Number of planning attempts made (from ``plan_with_repair``).
    history:
        List of attempt dicts from ``plan_with_repair``.  Each dict must
        have keys: ``attempt``, ``prompt``, ``reply``, ``ok``, ``feedback``.
    latency:
        Total wall-clock time in seconds, or ``None`` if not measured.
    path:
        JSONL file path to append to.  Parent directory is created if needed.
    world:
        The world the plan was verified and executed against, captured before
        execution moved the robot.  Recorded so the run can be replayed later by
        the simulator alone — passing it is what makes a record replayable.
        ``None`` when the caller does not have one to hand.
    mode:
        ``"live"`` when a model really produced the replies, ``"synthetic"``
        when a scripted reader did.  Stored only if it is one of those two —
        anything else (including ``None``) is stored as ``None`` so a reader
        can report the run's provenance as unrecorded instead of guessing.

    Returns
    -------
    dict
        The record that was written (or built, if the write failed).
    """
    record: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "instruction": instruction,
        "backend": backend,
        "success": actions is not None,
        "attempts": attempts,
        "latency": latency,
        # The plan and the world it ran on: a replay needs both, and neither can
        # be reconstructed from the replies afterwards.
        "actions": copy.deepcopy(actions) if isinstance(actions, list) else None,
        "world": copy.deepcopy(world) if isinstance(world, dict) else None,
        # Provenance, stated by the caller.  Never inferred from the result:
        # a scripted run and a live one can produce the same plan.
        "mode": mode if mode in ("live", "synthetic") else None,
        "history": history,
    }

    # Scrub secrets before touching disk.
    safe = _redact_record(record)

    log_path = Path(path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(safe, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[logger] WARNING: could not write to {path}: {exc}")

    return safe


# ---------------------------------------------------------------------------
# load_runs
# ---------------------------------------------------------------------------

def load_runs(path: str = "logs/runs.jsonl") -> list[dict]:
    """Load all run records from *path*, newest last.

    Parameters
    ----------
    path:
        JSONL file to read.

    Returns
    -------
    list[dict]
        All valid records in file order (oldest first, newest last).
        Returns ``[]`` if the file does not exist.
        Silently skips any line that cannot be parsed as JSON.
    """
    log_path = Path(path)
    if not log_path.exists():
        return []

    records: list[dict] = []
    with log_path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[logger] WARNING: skipping corrupt line {lineno} in {path}")

    return records


# ---------------------------------------------------------------------------
# summarize_run
# ---------------------------------------------------------------------------

def summarize_run(record: dict) -> str:
    """Return a short human-readable summary of one run record.

    Parameters
    ----------
    record:
        A dict as returned by ``log_run`` / ``load_runs``.

    Returns
    -------
    str
        Multi-line summary suitable for a UI panel.  Example::

            ✓ Succeeded on attempt 2 of 3 (api) — 1.23 s
              Attempt 1 failed: action 1 failed: blocked at [2, 0]...
    """
    success   = record.get("success", False)
    attempts  = record.get("attempts", "?")
    backend   = record.get("backend", "unknown")
    latency   = record.get("latency")
    history   = record.get("history", [])
    instr     = record.get("instruction", "")

    # Header line
    status_icon = "✓" if success else "✗"
    outcome     = "Succeeded" if success else "Failed"
    lat_str     = f" — {latency:.2f} s" if latency is not None else ""

    # Find the successful attempt number (last ok=True, or max)
    success_attempt = attempts
    for rec in history:
        if rec.get("ok"):
            success_attempt = rec.get("attempt", attempts)
            break

    lines = [
        f'{status_icon} {outcome} on attempt {success_attempt} of {attempts} '
        f'({backend}){lat_str}',
        f'  Instruction: {instr}',
    ]

    # One line per failed attempt showing what went wrong
    for rec in history:
        if not rec.get("ok"):
            att = rec.get("attempt", "?")
            fb  = rec.get("feedback", "no feedback")
            lines.append(f"  Attempt {att} failed: {fb}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-test (no AI, no network)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile
    import os as _os

    SEP = "-" * 60

    # Use a temp file so the test never touches the real logs/ folder.
    tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    tmp.close()
    TEST_PATH = tmp.name

    try:
        # ── Fake history shapes (matching harness.plan_with_repair output) ──
        history_success = [
            {
                "attempt": 1,
                "prompt": "navigate to the goal",
                "reply": '{"thought":"try east","actions":[{"cmd":"forward","steps":5}]}',
                "ok": False,
                "feedback": "action 1 failed: blocked at [2, 0]. Robot is at [2, 0] facing E",
            },
            {
                "attempt": 2,
                "prompt": "navigate to the goal\n\nYour previous plan failed...",
                "reply": '{"thought":"go around","actions":[{"cmd":"turn_right"},{"cmd":"forward","steps":7}]}',
                "ok": True,
                "feedback": "ok",
            },
        ]

        history_failure = [
            {
                "attempt": i,
                "prompt": "navigate to the goal",
                "reply": '{"thought":"try east","actions":[{"cmd":"forward","steps":5}]}',
                "ok": False,
                "feedback": "action 1 failed: blocked at [2, 0]. Robot is at [2, 0] facing E",
            }
            for i in range(1, 4)
        ]

        # ── Log a successful run ──────────────────────────────────────────
        print(SEP)
        print("Logging run 1: SUCCESS (2 attempts, ollama backend)")
        rec1 = log_run(
            instruction="navigate to the goal",
            backend="ollama",
            actions=[{"cmd": "turn_right"}, {"cmd": "forward", "steps": 7}],
            attempts=2,
            history=history_success,
            latency=1.42,
            path=TEST_PATH,
        )
        print(f"  record keys   : {sorted(rec1.keys())}")
        print(f"  success       : {rec1['success']}")
        print(f"  attempts      : {rec1['attempts']}")
        print(f"  backend       : {rec1['backend']}")
        print(f"  latency       : {rec1['latency']}")
        print(f"  history items : {len(rec1['history'])}")
        assert rec1["success"] is True
        assert rec1["attempts"] == 2
        assert rec1["backend"] == "ollama"
        assert rec1["latency"] == 1.42
        assert len(rec1["history"]) == 2
        assert "timestamp" in rec1

        # ── The plan and the world are recorded for replay ───────────────
        # Written to their own file so the record counts below stay exact.
        print(SEP)
        print("Replay fields: plan + world")
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as _fh:
            REPLAY_PATH = _fh.name
        try:
            REPLAY_WORLD = {"robot": [0, 0], "dir": "E", "goal": [6, 5],
                            "walls": [[3, 0]]}
            rec_w = log_run(
                instruction="navigate to the goal",
                backend="dry",
                actions=[{"cmd": "forward", "steps": 2}],
                attempts=1,
                history=[{"attempt": 1, "prompt": "p", "reply": "r",
                          "ok": True, "feedback": "ok"}],
                latency=0.0,
                path=REPLAY_PATH,
                world=REPLAY_WORLD,
                mode="synthetic",
            )
            print(f"  actions       : {rec_w['actions']}")
            print(f"  world captured: {rec_w['world'] == REPLAY_WORLD}")
            print(f"  mode recorded : {rec_w['mode']}")
            assert rec_w["actions"] == [{"cmd": "forward", "steps": 2}]
            assert rec_w["world"] == REPLAY_WORLD
            assert rec_w["mode"] == "synthetic"
            # An unknown or missing mode is stored as None, never guessed at.
            assert log_run("i", "api", None, 1, [], path=REPLAY_PATH)["mode"] is None
            assert log_run("i", "api", None, 1, [], path=REPLAY_PATH,
                           mode="reviewed")["mode"] is None
            REPLAY_WORLD["robot"][0] = 9    # caller's copy must not alias
            assert rec_w["world"]["robot"] == [0, 0], \
                "world must be captured by value"
            assert load_runs(path=REPLAY_PATH)[0]["world"]["robot"] == [0, 0]
            rec_bare = log_run("i", "api", None, 1, [], path=REPLAY_PATH)
            assert rec_bare["world"] is None and rec_bare["actions"] is None
        finally:
            _os.unlink(REPLAY_PATH)

        # A record written before these keys existed still summarizes fine.
        legacy = {"timestamp": "t", "instruction": "i", "backend": "api",
                  "success": False, "attempts": 2, "latency": 1.0,
                  "history": [{"attempt": 1, "prompt": "p", "reply": "r",
                               "ok": False, "feedback": "nope"}]}
        assert "Failed" in summarize_run(legacy)

        # ── Log a failed run ──────────────────────────────────────────────
        print(SEP)
        print("Logging run 2: FAILURE (3 attempts, api backend)")
        rec2 = log_run(
            instruction="navigate to the goal",
            backend="api",
            actions=None,          # failure → None
            attempts=3,
            history=history_failure,
            latency=3.07,
            path=TEST_PATH,
        )
        print(f"  success       : {rec2['success']}")
        print(f"  attempts      : {rec2['attempts']}")
        assert rec2["success"] is False
        assert rec2["attempts"] == 3

        # ── Reload from disk ──────────────────────────────────────────────
        print(SEP)
        print("Reloading runs from disk")
        runs = load_runs(path=TEST_PATH)
        print(f"  records loaded: {len(runs)}  (expected 2)")
        assert len(runs) == 2, f"FAIL: expected 2 records, got {len(runs)}"
        # Newest last — rec2 is index 1
        assert runs[0]["success"] is True
        assert runs[1]["success"] is False

        # ── summarize_run for each ────────────────────────────────────────
        print(SEP)
        print("Summary of run 1 (success):")
        s1 = summarize_run(runs[0])
        print(s1)
        assert "Succeeded" in s1
        assert "ollama" in s1
        assert "Attempt 1 failed" in s1     # one failed attempt in history

        print(SEP)
        print("Summary of run 2 (failure):")
        s2 = summarize_run(runs[1])
        print(s2)
        assert "Failed" in s2
        assert "api" in s2
        assert s2.count("Attempt") == 3     # three failed attempts

        # ── Corrupt-line tolerance ────────────────────────────────────────
        print(SEP)
        print("Testing corrupt-line tolerance")
        with open(TEST_PATH, "a", encoding="utf-8") as fh:
            fh.write("THIS IS NOT JSON\n")
        runs_after = load_runs(path=TEST_PATH)
        print(f"  records after corrupt line: {len(runs_after)}  (expected 2)")
        assert len(runs_after) == 2, "FAIL: corrupt line should be skipped"

        # ── Missing-file tolerance ────────────────────────────────────────
        print(SEP)
        print("Testing missing-file returns []")
        empty = load_runs(path="logs/__nonexistent__.jsonl")
        print(f"  result: {empty}  (expected [])")
        assert empty == []

        print(SEP)
        print("All logger tests passed.")

    finally:
        _os.unlink(TEST_PATH)
