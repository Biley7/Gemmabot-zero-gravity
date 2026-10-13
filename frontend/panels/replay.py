"""Run History + Replay — the log, and a replay that never calls a model.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

Run History
-----------
Every run this app logs carries its own structured metadata — run id,
timestamp, input type, model, backend, attempts, plan length, the verifier's
verdict, the execution outcome, latency, final position and whether the goal was
reached — and this module turns a log record into the display model for it.
Nothing is filled in from the app's current state and nothing is invented for a
record that does not carry a field: a missing value is shown as *not recorded*.

Three provenances, and they are never mixed:

    LIVE RUN            a real model call, made in this session
    RECORDED RUN        read back out of the log file
    SYNTHETIC BENCHMARK a scripted reader replied — not a live measurement

The label is decided by :func:`provenance` from the record's own ``mode`` plus
whether this session produced it.  A scripted run is never called live, and a
run whose provenance was not recorded is shown as such rather than assumed.

Replay
------
A logged record carries the world a run was verified against plus the plans it
produced, so re-running it is nothing but ``simulator.step`` on that world: the
movement, the cells, the turns and the messages the player animates are the
simulator's own results, produced again here rather than replayed from a
recording.  No planner, no vision model and no network call is involved —
``timeline()`` cannot reach a model even by accident (``playback.build_timeline``
→ ``engine.execute`` → ``simulator.step``).

:func:`reproduce` goes further: it re-runs the *deterministic* verifier on the
recorded world and plan as well, and puts its verdict, the plan's steps, the
final position and the goal-reached flag side by side with what the run recorded
at the time.  A replay that reproduces a run is evidence; one that disagrees
with the log says so loudly instead of quietly showing the newer numbers.

What is deliberately *not* shown: a record whose world was never captured, or
that has no plan, is listed with the reason it cannot be replayed instead of
being replayed against something guessed.  Records written before ``world`` and
``actions`` were added to the log are exactly that case.

Public surface
--------------
PROVENANCE / FILTERS                 the vocabulary
runs(records, ...)                   newest-first display models for a whole log
run(record, number, ...)             one record's display model
provenance(record, ...)              LIVE RUN / RECORDED RUN / SYNTHETIC BENCHMARK
matches(model, ...)                  the six filters, as a predicate
model_key(model)                     the model/backend a filter selects on
metadata_rows(model)                 the twelve structured fields
replayable(record)                   (bool, reason) — can this be replayed at all
plans(record)                        the recorded plans that can be replayed
start_world(record)                  the world the run recorded, or None
timeline(record, plan)               the simulator's own replay timeline
reproduce(record, plan)              the replay, plus the recorded-vs-reproduced rows
provenance_html(model)               the provenance chip
metadata_html(model)                 the twelve fields as readouts
reproduction_html(repro)             what the replay reproduced, and what it did not
facts_rows(run)                      run, backend, latency, attempts
attempts_html(run)                   the run's attempt log
timeline_html(run, plan)             the run's timeline strip
runs_html(runs)            the log table
meta_html(run, plan)       the selected run's header
facts_html(rows)           the four readouts
source_html(...)           where this replay came from
"""
from __future__ import annotations

from backend.verifier.harness import verify_plan
from backend.vision.map_vision import check_world_report
from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.components.blocks import (
    empty_state,
    escape as _e,
    fact_cards,
    plural as _plural,
    scroll_x,
)
from frontend.panels.engine import backend_label
from frontend.simulation import player as playback

# Verdict marks for a logged run: it succeeded, or it did not.
_MARKS: dict[bool, str] = {True: "✓", False: "✕"}

# Distinguishes "the run recorded nothing here" from "the run recorded the value
# None" when a replay is compared against the record.
_MISSING: object = object()

_STATE_COLORS: dict[str, str] = {
    "success": C.SUCCESS,
    "error": C.ERROR,
    "warning": C.WARNING,
    "neutral": C.TEXT_SECONDARY,
    "running": C.RUNNING,
}

# The world checks a logged run must have passed for the simulator to re-run it:
# a world the validator refused is not replayable, and these are the four that
# establish the world itself.  (``reachable`` is about the plan's world being
# solvable, not about the simulator being able to move in it.)
_REPLAY_CHECKS: tuple[str, ...] = ("bounds", "robot", "goal", "overlaps")

# ── Provenance ───────────────────────────────────────────────────────────────
# The three kinds of run this console shows, and the words for them.  A scripted
# run is never described as a live one: ``mode`` is written by the caller that
# knew, and a record without it is shown as unrecorded rather than assumed.
PROVENANCE: dict[str, str] = {
    "live": "LIVE RUN",
    "recorded": "RECORDED RUN",
    "synthetic": "SYNTHETIC BENCHMARK",
}
_PROVENANCE_STATES: dict[str, str] = {
    "live": "success", "recorded": "neutral", "synthetic": "warning",
}

# ── Filters ──────────────────────────────────────────────────────────────────
# The three groups the Run History can be narrowed by.  Inside a group the
# choices are OR-ed; the groups are AND-ed together, so "Repaired + Vision"
# means a repaired run whose input was an image.  An empty group is no
# constraint at all.
FILTERS: tuple[tuple[str, str], ...] = (
    ("success", "Success"),
    ("failed", "Failed"),
    ("repaired", "Repaired"),
    ("vision", "Vision"),
    ("text", "Text"),
    ("models", "Model/backend"),
)

# The input types a record can carry, and how they are shown.  A record without
# one is *not recorded* — it matches neither Text nor Vision.
INPUT_TYPES: dict[str, str] = {
    "text": "Text",
    "vision": "Vision",
    "benchmark": "Benchmark",
}

# Status filters and the input filters they are checked against.
_STATUS_KEYS: tuple[str, ...] = ("success", "failed", "repaired")
_INPUT_KEYS: tuple[str, ...] = ("vision", "text")
_ABSENT: str = "not recorded"






def _record_text(record: dict, key: str) -> str | None:
    """A non-empty string field of *record*, or ``None`` when it carries none.

    A record written before a field existed lacks the key, and a record whose
    value was unusable carries ``None``: both mean the same thing here.
    """
    value = record.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _record_cell(record: dict, key: str) -> list | None:
    """A ``[x, y]`` field of *record*, or ``None``."""
    value = record.get(key)
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
    ):
        return list(value)
    return None


def _record_bool(record: dict, key: str) -> bool | None:
    """A boolean field of *record*, or ``None`` — never a coercion."""
    value = record.get(key)
    return value if value is True or value is False else None


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def provenance(record: dict, *, session_run_id: str | None = None) -> dict:
    """LIVE RUN / RECORDED RUN / SYNTHETIC BENCHMARK for one record.

    A scripted run is a **synthetic benchmark** wherever it is shown: it is not a
    measurement a live model produced, whatever it looks like.  A record this
    session produced from a real model call is a **live run**; anything else read
    out of the log is a **recorded run**.  ``mode`` absent or unrecognised means
    the provenance was not recorded, which is reported as such — the label never
    guesses in either direction.
    """
    record = record if isinstance(record, dict) else {}
    recorded = record.get("mode")
    # Only the two modes this console knows are ever carried forward; anything
    # else (including a value a future build wrote) is *not recorded* here, so
    # no reader can mistake an unknown string for a known provenance.
    mode = recorded if recorded in PROVENANCE else None
    run_id = _record_text(record, "run_id")
    wanted = session_run_id if isinstance(session_run_id, str) else ""
    in_session = bool(run_id) and bool(wanted) and run_id == wanted

    if mode == "synthetic":
        key = "synthetic"
        detail = (
            "a scripted reader replied — this is not a live model measurement, "
            "whatever its numbers say"
        )
    elif mode == "live" and in_session:
        key = "live"
        detail = "a real model call, made in this session"
    elif mode == "live":
        key = "recorded"
        detail = "a real model call, read back from the log"
    else:
        key = "recorded"
        detail = (
            "provenance was not recorded for this run — it is neither proven live "
            "nor proven scripted"
        )
    return {
        "key": key,
        "label": PROVENANCE[key],
        "state": _PROVENANCE_STATES[key],
        "detail": detail,
        "mode": mode,
        "in_session": in_session,
    }


def model_key(model: dict) -> str:
    """The label the Model/backend filter selects on, e.g. ``"API · gemma-…"``."""
    backend = model.get("backend_label") or _ABSENT
    name = model.get("model") or "no model recorded"
    return f"{backend} · {name}"


def matches(
    model: dict,
    *,
    statuses: tuple[str, ...] | list[str] = (),
    inputs: tuple[str, ...] | list[str] = (),
    models: tuple[str, ...] | list[str] = (),
) -> bool:
    """Whether *model* passes the three filter groups.

    Inside a group the selections are OR-ed and the groups are AND-ed, which is
    what makes "Repaired + Vision" mean *a repaired run whose input was an
    image*.  An empty group is no constraint.  ``inputs`` matches on the
    recorded input type, so a record that never recorded one (every record
    written before this field existed) passes neither Vision nor Text — it is
    not evidence of either.
    """
    statuses = tuple(statuses or ())
    inputs = tuple(inputs or ())
    models = tuple(models or ())

    if statuses:
        flags = {
            "success": bool(model.get("success")),
            "failed": not bool(model.get("success")),
            "repaired": bool(model.get("repaired")),
        }
        if not any(flags.get(key, False) for key in statuses):
            return False

    if inputs:
        recorded = model.get("input_type")
        wanted = {
            "vision": "vision",
            "text": "text",
        }
        if recorded not in {wanted[key] for key in inputs if key in wanted}:
            return False

    if models and model_key(model) not in models:
        return False
    return True


def _is_action_list(value: object) -> bool:
    """True for a non-empty list of action dicts — what the simulator accepts."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, dict) for item in value)
    )


def _when(timestamp: object) -> str:
    """``2026-10-06T19:15:20.94+00:00`` → ``2026-10-06 19:15:20 UTC``.

    The log is written in UTC; an unreadable timestamp is shown verbatim rather
    than reformatted into a guess.
    """
    text = str(timestamp or "").strip()
    if not text:
        return "no timestamp"
    if "T" not in text:
        return text
    date, _, rest = text.partition("T")
    clock = rest.split(".")[0].split("+")[0].replace("Z", "")
    suffix = "UTC" if ("+00:00" in rest or rest.endswith("Z")) else ""
    return f"{date} {clock} {suffix}".strip()


def _world_usable(world: object) -> tuple[bool, str]:
    """Whether the simulator could run this world, and why not when it cannot.

    Reuses the real validator.  An unproven check counts as unusable: a replay
    never assumes a world it could not check.
    """
    report = check_world_report(world)
    by_id = {check["id"]: check for check in report["checks"]}
    for check_id in _REPLAY_CHECKS:
        check = by_id[check_id]
        if check["ok"] is not True:
            return False, (
                f"the recorded world fails {check['label'].lower()}: "
                f"{check['detail']}"
            )
    return True, ""


# ---------------------------------------------------------------------------
# Record → display model
# ---------------------------------------------------------------------------

def plans(record: dict) -> list[dict]:
    """Every plan in *record* that can be replayed, in attempt order.

    Reads only ``history[i]["actions"]`` and the record's own ``actions`` — the
    exact lists the run parsed.  A plan-free record yields ``[]``.
    """
    out: list[dict] = []
    history = record.get("history") if isinstance(record, dict) else None
    for position, attempt in enumerate(history or []):
        if not isinstance(attempt, dict):
            continue
        actions = attempt.get("actions")
        if not _is_action_list(actions):
            continue
        number = int(attempt.get("attempt") or position + 1)
        accepted = bool(attempt.get("ok"))
        out.append({
            "id": f"attempt-{number}",
            "attempt": number,
            "ok": accepted,
            "actions": actions,
            "count": len(actions),
            "label": (
                f"Attempt {number} — {'accepted' if accepted else 'rejected'} · "
                f"{_plural(len(actions), 'action')}"
            ),
            "source": f"attempt {number} of the recorded history",
        })

    if not out and isinstance(record, dict) and _is_action_list(record.get("actions")):
        accepted = record["actions"]
        out.append({
            "id": "logged-plan",
            "attempt": None,
            "ok": True,
            "actions": accepted,
            "count": len(accepted),
            "label": f"Logged plan · {_plural(len(accepted), 'action')}",
            "source": "the plan this run recorded",
        })
    return out


def replayable(record: object) -> tuple[bool, str]:
    """``(can_replay, reason)`` for one log record.

    A replay needs both halves of a run: the world it ran on and a plan to run.
    Anything missing is reported as a reason, never worked around.
    """
    if not isinstance(record, dict):
        return False, "the log line is not a run record"
    if "world" not in record:
        return False, "logged before the world was captured — nothing to replay it on"
    if record.get("world") is None:
        return False, "no world was captured for this run"
    usable, why = _world_usable(record.get("world"))
    if not usable:
        return False, why
    if not plans(record):
        return False, "no plan was recorded for this run, so there is nothing to replay"
    return True, ""


def start_world(record: dict) -> dict | None:
    """The world the run recorded, or ``None`` when it was not captured."""
    world = record.get("world") if isinstance(record, dict) else None
    return world if isinstance(world, dict) else None


def run(record: object, number: int, *, session_run_id: str | None = None) -> dict:
    """Display model for one log record, oldest being run 1.

    Every value comes from the record; nothing is filled in from the app's
    current state, which is what makes the replay the *run's* replay.  The one
    thing the caller supplies is ``session_run_id`` — the id of the run this
    session just made — and it is used only to label that record a LIVE RUN.
    """
    record = record if isinstance(record, dict) else {}
    history = [item for item in (record.get("history") or []) if isinstance(item, dict)]
    failed = [item for item in history if not item.get("ok")]
    attempts = record.get("attempts")
    try:
        attempts_value = int(attempts)
    except (TypeError, ValueError):
        attempts_value = len(history)
    latency = record.get("latency")
    try:
        latency_value = float(latency)
    except (TypeError, ValueError):
        latency_value = None

    backend = str(record.get("backend") or "unknown")
    success = bool(record.get("success"))
    can_replay, reason = replayable(record)
    plan_options = plans(record)
    input_type = record.get("input_type")
    if input_type not in INPUT_TYPES:
        input_type = None

    return {
        "number": int(number),
        "id": f"run-{int(number)}",
        "run_id": _record_text(record, "run_id"),
        "label": f"Run {int(number)}",
        "when": _when(record.get("timestamp")),
        "timestamp": record.get("timestamp"),
        "instruction": str(record.get("instruction") or ""),
        "input_type": input_type,
        "input_label": INPUT_TYPES.get(input_type, _ABSENT),
        "model": _record_text(record, "model"),
        "backend": backend,
        "backend_label": backend_label(backend),
        "latency": latency_value,
        "latency_label": f"{latency_value:.2f} s" if latency_value is not None else "—",
        "attempts": attempts_value,
        "attempts_label": str(attempts_value),
        "history_length": len(history),
        "failed_attempts": len(failed),
        # A run that failed at least once and then passed is one the loop
        # repaired — the fact the Repaired filter selects on.
        "repaired": success and len(failed) > 0,
        "plan_length": (
            int(record["plan_length"])
            if isinstance(record.get("plan_length"), int)
            and not isinstance(record.get("plan_length"), bool)
            else None
        ),
        "verification": (
            record.get("verification")
            if isinstance(record.get("verification"), dict) else None
        ),
        "execution": (
            record.get("execution")
            if isinstance(record.get("execution"), dict) else None
        ),
        "final_position": _record_cell(record, "final_position"),
        "goal_reached": _record_bool(record, "goal_reached"),
        "provenance": provenance(record, session_run_id=session_run_id),
        "success": success,
        "state": "success" if success else "error",
        "mark": _MARKS[success],
        "world": start_world(record),
        "replayable": can_replay,
        "reason": reason,
        "plans": plan_options,
        "record": record,
    }


def runs(
    records: list[dict] | None, *, session_run_id: str | None = None
) -> list[dict]:
    """Display models for a whole log, newest first (run numbers stay stable).

    The run number counts from the start of the log, so it does not change when
    the log grows; the list is simply reversed for display.  Nothing is dropped
    or repaired: a record that cannot be replayed is still a run, and is listed
    with the reason it cannot be.
    """
    records = [record for record in (records or [])]
    models = [
        run(record, index, session_run_id=session_run_id)
        for index, record in enumerate(records, start=1)
    ]
    return list(reversed(models))


def metadata_rows(model: dict) -> list[dict]:
    """The twelve structured fields of a run, display-ready.

    Every row says what the record holds, and ``not recorded`` when it holds
    nothing — a legacy record is never back-filled with a plausible value.
    """
    record = model.get("record") or {}
    actions = record.get("actions")
    plan_length = model.get("plan_length")
    plan_detail = (
        "the accepted plan" if isinstance(actions, list)
        else "the last plan the run parsed" if plan_length is not None
        else "no plan was parsed"
    )
    verification = model.get("verification")
    if isinstance(verification, dict):
        ok = verification.get("ok")
        verified_label = (
            "✓ verified" if ok is True else "✕ refused" if ok is False
            else _ABSENT
        )
        verified_detail = str(verification.get("reason") or "") or _ABSENT
        verified_state = "success" if ok is True else "error" if ok is False else "neutral"
    else:
        verified_label, verified_detail, verified_state = _ABSENT, _ABSENT, "neutral"

    execution = model.get("execution")
    if isinstance(execution, dict):
        ran = execution.get("ran")
        halted = execution.get("halted")
        steps = execution.get("steps")
        executed_label = (
            "executed" if ran is True else "not executed" if ran is False else _ABSENT
        )
        executed_detail = (
            f"halted: {halted}" if halted
            else f"{steps} step(s) applied" if isinstance(steps, int)
            # ``ran: False`` is itself the record — the run says it never
            # applied its plan, which is not the same as an absent field.
            else "the run recorded no execution" if ran is False
            else _ABSENT
        )
        executed_state = "success" if ran is True else "error" if ran is False else "neutral"
    else:
        executed_label, executed_detail, executed_state = _ABSENT, _ABSENT, "neutral"

    reached = model.get("goal_reached")
    return [
        {"id": "run_id", "label": "Run ID",
         "value": model.get("run_id") or _ABSENT,
         "detail": "the run's own id, not its line number", "state": "neutral"},
        {"id": "timestamp", "label": "Timestamp",
         "value": model["when"], "detail": "UTC, as recorded", "state": "neutral"},
        {"id": "input_type", "label": "Input type",
         "value": model["input_label"],
         "detail": "how the run was asked", "state": "neutral"},
        {"id": "model", "label": "Model",
         "value": model.get("model") or _ABSENT,
         "detail": "the model id the backend would use", "state": "neutral"},
        {"id": "backend", "label": "Backend",
         "value": model["backend_label"],
         "detail": f"logged as {model['backend']}", "state": "neutral"},
        {"id": "attempts", "label": "Attempts",
         "value": model["attempts_label"],
         "detail": (
             f"{model['failed_attempts']} failed · "
             f"{model['history_length']} recorded"
             if model["history_length"] else "no attempt records"
         ),
         "state": "error" if model["failed_attempts"] else "success"},
        {"id": "plan_length", "label": "Plan length",
         "value": (
             f"{plan_length} action{'s' if plan_length != 1 else ''}"
             if plan_length is not None else _ABSENT
         ),
         "detail": plan_detail, "state": "neutral"},
        {"id": "verification", "label": "Verification",
         "value": verified_label, "detail": verified_detail,
         "state": verified_state},
        {"id": "execution", "label": "Execution",
         "value": executed_label, "detail": executed_detail,
         "state": executed_state},
        {"id": "latency", "label": "Latency",
         "value": model["latency_label"],
         "detail": "measured when the run happened", "state": "neutral"},
        {"id": "final_position", "label": "Final position",
         "value": (
             f"[{model['final_position'][0]}, {model['final_position'][1]}]"
             if model.get("final_position") else _ABSENT
         ),
         "detail": "where the robot ended up", "state": "neutral"},
        {"id": "goal_reached", "label": "Goal reached",
         "value": (
             "✓ yes" if reached is True else "✕ no" if reached is False
             else _ABSENT
         ),
         "detail": (
             "the simulator's own outcome" if reached is not None
             else "the run did not record an outcome"
         ),
         "state": "success" if reached is True else "error" if reached is False
                  else "neutral"},
    ]


def reproduce(record: dict, plan: dict) -> dict | None:
    """Re-run a recorded plan: the simulator's timeline, and the verifier's verdict.

    Both halves are pure code — ``verify_plan`` and ``simulator.step`` — so a
    replay never calls a model, however the run was originally produced.  The
    returned ``agreement`` rows set what the run recorded beside what the replay
    reproduced, one row per fact, each marked ``match`` / ``mismatch`` /
    ``unrecorded``.  A mismatch is reported, never smoothed over: it means the
    log and the current code disagree.
    """
    replayed = timeline(record, plan)
    if replayed is None:
        return None

    world = start_world(record or {})
    actions = (plan or {}).get("actions")
    report = verify_plan(world, actions)
    steps = len(replayed["steps"])

    recorded_verification = record.get("verification")
    recorded_verification = (
        recorded_verification if isinstance(recorded_verification, dict) else None
    )
    recorded_execution = record.get("execution")
    recorded_execution = (
        recorded_execution if isinstance(recorded_execution, dict) else None
    )

    def _row(field, label, recorded, reproduced, *, blank: str = _ABSENT) -> dict:
        """One fact: what the run recorded beside what the replay reproduced.

        ``blank`` is the word for a fact the run did not record — a run that
        says it never executed has a more precise one than ``not recorded``.
        """
        if recorded is _MISSING:
            state = "unrecorded"
        elif recorded == reproduced:
            state = "match"
        else:
            state = "mismatch"
        return {
            "id": field, "label": label,
            "recorded": blank if recorded is _MISSING else str(recorded),
            "reproduced": str(reproduced),
            "state": state,
        }

    final = replayed.get("final")
    final_label = f"[{final[0]}, {final[1]}]" if isinstance(final, list) else _ABSENT
    recorded_final = _record_cell(record, "final_position")
    recorded_final_label = (
        f"[{recorded_final[0]}, {recorded_final[1]}]" if recorded_final else _MISSING
    )
    # A run that recorded ``ran: False`` never applied its plan, so there is no
    # step count, halt or final position to compare: those facts are *not
    # recorded*, and the panel says the run did not execute rather than leaving
    # a blank that would read as a missing field.
    never_ran = bool(recorded_execution) and recorded_execution.get("ran") is False
    blank = "not executed" if never_ran else _ABSENT
    recorded_steps = (
        _MISSING if never_ran or not recorded_execution
        else recorded_execution.get("steps")
    )
    # ``halted`` is recorded as None when the plan never halted, which is a
    # fact — so an execution record exists means the field is recorded, whatever
    # its value, and it is compared as the word the panel shows.
    recorded_halted = (
        _MISSING if never_ran or not recorded_execution
        else (recorded_execution.get("halted") or "—")
    )
    recorded_goal = _record_bool(record, "goal_reached")

    agreement = [
        _row(
            "verification", "Verification",
            (recorded_verification or {}).get("ok", _MISSING) if recorded_verification
            else _MISSING,
            report["ok"],
        ),
        _row(
            "execution_steps", "Steps applied",
            recorded_steps if recorded_steps is not None else _MISSING,
            steps, blank=blank,
        ),
        _row(
            "execution_halted", "Halted",
            recorded_halted,
            replayed.get("halted") or "—", blank=blank,
        ),
        _row(
            "final_position", "Final position", recorded_final_label, final_label,
            blank=blank,
        ),
        _row(
            "goal_reached", "Goal reached",
            recorded_goal if recorded_goal is not None else _MISSING,
            bool(replayed.get("reached")), blank=blank,
        ),
    ]

    return {
        "timeline": replayed,
        "verification": {"ok": report["ok"], "reason": report["reason"]},
        "execution": {
            "ran": True, "halted": replayed.get("halted"), "steps": steps,
        },
        "final_position": final,
        "goal_reached": bool(replayed.get("reached")),
        "agreement": agreement,
        "mismatches": [row for row in agreement if row["state"] == "mismatch"],
        "unrecorded": [row for row in agreement if row["state"] == "unrecorded"],
    }


def timeline(record: dict, plan: dict) -> dict | None:
    """The simulator's own replay of *plan* on the world the run recorded.

    Pure simulator: ``build_timeline`` calls ``engine.execute``, which calls
    ``simulator.step``.  Nothing here can reach a model.
    """
    world = start_world(record or {})
    if world is None or not isinstance(plan, dict):
        return None
    actions = plan.get("actions")
    if not _is_action_list(actions):
        return None
    return playback.build_timeline(world, actions, kind=playback.KIND_REPLAY)


# ---------------------------------------------------------------------------
# Readouts
# ---------------------------------------------------------------------------

def facts_rows(run_model: dict) -> list[dict]:
    """The four readouts a replay shows: run, backend, latency, attempts."""
    failed = int(run_model.get("failed_attempts") or 0)
    recorded = int(run_model.get("history_length") or 0)
    return [
        {
            "id": "run",
            "label": "Run",
            "value": f"#{run_model['number']}",
            "detail": run_model["when"],
            "state": "neutral",
        },
        {
            "id": "backend",
            "label": "Backend",
            "value": run_model["backend_label"],
            "detail": f"logged as {run_model['backend']}",
            "state": "neutral",
        },
        {
            "id": "latency",
            "label": "Latency",
            "value": run_model["latency_label"],
            "detail": "measured when the run happened",
            "state": "neutral",
        },
        {
            "id": "attempts",
            "label": "Attempts",
            "value": run_model["attempts_label"],
            "detail": (
                f"{failed} failed · {recorded} recorded"
                if recorded else "no attempt records"
            ),
            "state": "error" if failed else "success",
        },
    ]


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def runs_html(run_models: list[dict]) -> str:
    """The log table: one row per run, newest first."""
    if not run_models:
        return empty_state(
            "No runs have been logged yet.",
            "Run a plan in Text command, or the benchmark runner, and it lands here.",
        )

    header = (
        f"<div style='display:flex;gap:{S.px(S.SM)};padding:{S.px(S.XS)} 0;"
        f"border-bottom:1px solid {C.BORDER_DEFAULT};font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};"
        f"letter-spacing:{T.TRACKING_WIDE};text-transform:uppercase'>"
        f"<span style='width:{S.px(46)}'>run</span>"
        f"<span style='width:{S.px(150)}'>provenance</span>"
        f"<span style='width:{S.px(96)}'>backend</span>"
        f"<span style='width:{S.px(60)}'>latency</span>"
        f"<span style='width:{S.px(48)}'>attempts</span>"
        f"<span style='flex:1'>instruction</span>"
        f"<span style='width:{S.px(74)};text-align:right'>replay</span>"
        f"</div>"
    )

    rows: list[str] = []
    for model in run_models:
        color = _STATE_COLORS[model["state"]]
        replay_text = "ready" if model["replayable"] else "not replayable"
        replay_color = C.SUCCESS if model["replayable"] else C.TEXT_MUTED
        info = model.get("provenance") or provenance({})
        rows.append(
            f"<div class='gb-replay-run' data-run='{model['number']}' "
            f"data-provenance='{_e(info['key'])}' "
            f"data-run-id='{_e(model.get('run_id') or '')}' "
            f"data-input='{_e(model.get('input_type') or '')}' "
            f"data-backend='{_e(model['backend'])}' "
            f"data-latency='{_e(model['latency_label'])}' "
            f"data-attempts='{model['attempts']}' "
            f"data-replayable='{str(model['replayable']).lower()}' "
            f"style='display:flex;gap:{S.px(S.SM)};align-items:baseline;"
            f"padding:{S.px(S.XS)} 0;border-bottom:1px solid {C.BORDER_SUBTLE};"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px'>"
            f"<span style='width:{S.px(46)};color:{color}'>{model['mark']} "
            f"#{model['number']}</span>"
            f"<span style='width:{S.px(150)};color:"
            f"{_STATE_COLORS[info['state']]};white-space:nowrap;"
            f"overflow:hidden;text-overflow:ellipsis' "
            f"title='{_e(info['detail'])}'>{_e(info['label'])}</span>"
            f"<span style='width:{S.px(96)};color:{C.TEXT_SECONDARY}'>"
            f"{_e(model['backend_label'])}</span>"
            f"<span style='width:{S.px(60)};color:{C.TELEMETRY_VALUE}'>"
            f"{_e(model['latency_label'])}</span>"
            f"<span style='width:{S.px(48)};color:{C.TELEMETRY_VALUE}'>"
            f"{_e(model['attempts_label'])}</span>"
            f"<span style='flex:1;color:{C.TEXT_SECONDARY};overflow:hidden;"
            f"text-overflow:ellipsis;white-space:nowrap'>"
            f"{_e(model['instruction'])}</span>"
            f"<span style='width:{S.px(74)};text-align:right;"
            f"color:{replay_color}'>{_e(replay_text)}</span>"
            f"</div>"
        )
    return scroll_x(header + "".join(rows), min_width=760)


def _segment(label, detail, state, mark, *, kind, attrs=""):  # noqa: ANN001
    """One box in the run timeline."""
    color = _STATE_COLORS[state]
    return (
        f"<span class='gb-replay-seg' data-kind='{_e(kind)}' {attrs}"
        f"style='display:inline-flex;align-items:baseline;gap:{S.px(S.XS)};"
        f"padding:{S.px(S.XS)} {S.px(S.SM)};background:{C.BG_SURFACE};"
        f"border:1px solid {C.BORDER_SUBTLE};"
        f"border-radius:{S.px(S.RADIUS_MD)};font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_XS}px;color:{color}'>"
        f"<span>{_e(mark)}</span>"
        f"<span>{_e(label)}</span>"
        f"<span style='color:{C.TEXT_MUTED}'>{_e(detail)}</span>"
        f"</span>"
    )


def timeline_html(run_model: dict, plan: dict | None) -> str:
    """The run's timeline: each attempt, the retries, and the replay itself.

    Built from the record's own history, so it shows what really happened in the
    run being replayed — not a reconstruction of the plan's steps, which the
    player already animates.
    """
    arrow = (
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
        f"color:{C.TEXT_MUTED};padding:0 {S.px(S.XS)}'>→</span>"
    )
    parts: list[str] = [
        _segment(
            run_model["label"], run_model["backend_label"], "neutral", "●",
            kind="run", attrs=f"data-run='{run_model['number']}'",
        )
    ]

    history = [
        item for item in (run_model["record"].get("history") or [])
        if isinstance(item, dict)
    ]
    for position, attempt in enumerate(history):
        number = int(attempt.get("attempt") or position + 1)
        ok = bool(attempt.get("ok"))
        actions = attempt.get("actions")
        detail = (
            _plural(len(actions), "action") if _is_action_list(actions)
            else "no plan parsed"
        )
        parts.append(arrow)
        parts.append(_segment(
            f"Attempt {number}",
            detail,
            "success" if ok else "error",
            "✓" if ok else "✕",
            kind="attempt",
            attrs=f"data-attempt='{number}' data-ok='{str(ok).lower()}'",
        ))
        if not ok and position + 1 < len(history):
            parts.append(arrow)
            parts.append(_segment(
                "Repair", "failure sent back to the planner", "warning", "↻",
                kind="repair", attrs=f"data-attempt='{number}'",
            ))

    if plan is not None:
        parts.append(arrow)
        parts.append(_segment(
            "Replay",
            f"{_plural(int(plan.get('count') or 0), 'action')} · "
            f"{plan.get('source', '')}",
            "running", "▶",
            kind="replay", attrs=f"data-plan='{_e(plan.get('id', ''))}'",
        ))
    return (
        f"<div class='gb-replay-timeline' style='display:flex;align-items:center;"
        f"flex-wrap:wrap;gap:{S.px(S.XS)} {S.px(S.XS)}'>"
        + "".join(parts) + "</div>"
    )


def meta_html(run_model: dict, plan: dict | None) -> str:
    """The selected run's header: outcome, the four facts, and what is replayed."""
    chip = DS.status_chip(
        f"{'Succeeded' if run_model['success'] else 'Failed'} · "
        f"attempt {run_model['attempts']} of {run_model['attempts']}",
        run_model["state"],
    )
    facts = " · ".join(
        f"{_e(row['label'])} "
        f"<span style='color:{C.TELEMETRY_VALUE}'>{_e(row['value'])}</span>"
        for row in facts_rows(run_model)
    )
    replay_line = (
        f"Replaying <span style='color:{C.RUNNING}'>{_e(plan['label'])}</span>"
        f" — {_e(plan['source'])}"
        if plan is not None
        else f"<span style='color:{C.TEXT_MUTED}'>Not replayable: "
             f"{_e(run_model['reason'])}</span>"
    )
    return (
        f"<div class='gb-replay-meta' data-run='{run_model['number']}' "
        f"style='margin-bottom:{S.px(S.MD)}'>"
        f"<div style='margin-bottom:{S.px(S.SM)}'>{chip}</div>"
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
        f"color:{C.TEXT_SECONDARY};margin-bottom:{S.px(S.XS)}'>{facts}</div>"
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
        f"color:{C.TEXT_SECONDARY};margin-bottom:{S.px(S.XS)}'>"
        f"instruction “{_e(run_model['instruction'])}”</div>"
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px'>"
        f"{replay_line}</div>"
        f"</div>"
    )


def facts_html(rows: list[dict]) -> str:
    """The four readouts: run, backend, latency, attempts."""
    return fact_cards(rows, css_class="gb-replay-fact", column_min=160)


def metadata_html(model: dict) -> str:
    """The twelve structured fields of a run, as a labelled grid."""
    rows: list[str] = []
    for row in metadata_rows(model):
        color = _STATE_COLORS[row["state"]]
        rows.append(
            f"<div class='gb-history-field' data-field='{_e(row['id'])}' "
            f"data-value='{_e(row['value'])}' title='{_e(row['detail'])}' "
            f"style='display:flex;align-items:baseline;gap:{S.px(S.SM)};"
            f"padding:{S.px(S.XS)} 0;border-bottom:1px solid {C.BORDER_SUBTLE}'>"
            f"<span style='width:{S.px(112)};flex-shrink:0;"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
            f"text-transform:uppercase'>{_e(row['label'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{color};white-space:nowrap'>{_e(row['value'])}</span>"
            f"<span style='margin-left:auto;font-family:{T.FONT_MONO};"
            f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};text-align:right;"
            f"overflow:hidden;text-overflow:ellipsis'>"
            f"{_e(row['detail'])}</span>"
            f"</div>"
        )
    return "".join(rows)


def provenance_html(model: dict) -> str:
    """The provenance chip: LIVE RUN / RECORDED RUN / SYNTHETIC BENCHMARK."""
    info = model.get("provenance") or provenance({})
    return (
        f"<span class='gb-history-provenance' "
        f"data-provenance='{_e(info['key'])}' "
        f"data-run-id='{_e(model.get('run_id') or '')}' "
        f"title='{_e(info['detail'])}'>"
        f"{DS.status_chip(info['label'], info['state'])}"
        f"</span>"
    )


def reproduction_html(repro: dict | None) -> str:
    """What the replay reproduced, field by field, against what the run recorded.

    Three states, and the difference matters: ``match`` is the log confirmed by
    re-running it, ``mismatch`` is the log disagreeing with the code (shown in
    error colour — it is a finding, not a detail), and ``unrecorded`` means the
    run never wrote that field, so there is nothing to confirm.
    """
    if repro is None:
        return empty_state(
            "Nothing to reproduce.",
            "This run recorded no world or no plan, so there is nothing to re-run.",
        )

    row_states = {
        "match": ("success", "✓"),
        "mismatch": ("error", "✕"),
        "unrecorded": ("neutral", "–"),
    }
    rows: list[str] = []
    for row in repro["agreement"]:
        state, mark = row_states[row["state"]]
        color = _STATE_COLORS[state]
        rows.append(
            f"<div class='gb-history-agree' data-field='{_e(row['id'])}' "
            f"data-state='{_e(row['state'])}' "
            f"style='display:flex;align-items:baseline;gap:{S.px(S.SM)};"
            f"padding:{S.px(S.XS)} 0;border-bottom:1px solid {C.BORDER_SUBTLE};"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px'>"
            f"<span style='width:{S.px(S.MD)};color:{color}'>{mark}</span>"
            f"<span style='width:{S.px(120)};color:{C.TEXT_SECONDARY}'>"
            f"{_e(row['label'])}</span>"
            f"<span style='flex:1;color:{C.TEXT_MUTED}'>as recorded "
            f"<span style='color:{C.TELEMETRY_VALUE}'>{_e(row['recorded'])}</span>"
            f"</span>"
            f"<span style='color:{C.TEXT_MUTED}'>replayed "
            f"<span style='color:{C.TELEMETRY_VALUE}'>{_e(row['reproduced'])}</span>"
            f"</span>"
            f"</div>"
        )

    mismatches = repro["mismatches"]
    unrecorded = repro["unrecorded"]
    if mismatches:
        headline = (
            f"<div class='gb-history-agree-summary' data-agrees='false' "
            f"style='color:{C.ERROR};margin-top:{S.px(S.SM)}'>"
            f"✕ The replay disagrees with the log on "
            f"{_plural(len(mismatches), 'field')}: "
            f"{_e(', '.join(row['label'].lower() for row in mismatches))}. "
            "The re-run is the newer answer, but the difference is real and is "
            "not hidden.</div>"
        )
    else:
        confirmed = len(repro["agreement"]) - len(unrecorded)
        headline = (
            f"<div class='gb-history-agree-summary' data-agrees='true' "
            f"style='color:{C.SUCCESS};margin-top:{S.px(S.SM)}'>"
            f"✓ The replay reproduced every recorded result "
            f"({_plural(confirmed, 'field')} confirmed)"
            + (
                f" · {len(unrecorded)} not recorded by this run"
                if unrecorded else ""
            )
            + "</div>"
        )
    return "".join(rows) + headline


def source_html(path: str, run_model: dict) -> str:
    """Where this replay came from — and the fact that no model was involved."""
    return (
        f"<div class='gb-replay-source' style='font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};"
        f"margin-top:{S.px(S.SM)}'>"
        f"Replayed from <span style='color:{C.TEXT_SECONDARY}'>{_e(path)}</span> · "
        f"world and plan as recorded by {run_model['label']} on "
        f"{_e(run_model['when'])} · the simulator re-runs the recorded plan and no "
        f"model is called</div>"
    )


def panel(body: str) -> str:
    """The Replay tab's container."""
    return DS.panel(body, title="Replay")
