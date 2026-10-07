"""Replay — replaying a logged run with the simulator, never a model.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

What is real here
-----------------
The replay itself.  A logged record carries the world a run was verified and
executed against plus the plans it produced, so re-running it is nothing but
``simulator.step`` on that world: the movement, the cells, the turns and the
messages the player animates are the simulator's own results, produced again
here rather than replayed from a recording.  No planner, no vision model and no
network call is involved — ``timeline()`` cannot reach a model even by accident
(``playback.build_timeline`` → ``engine.execute`` → ``simulator.step``).

What is deliberately *not* shown: a record whose world was never captured, or
that has no plan, is listed with the reason it cannot be replayed instead of
being replayed against something guessed.  Records written before ``world`` and
``actions`` were added to the log are exactly that case.

Public surface
--------------
runs(records)              newest-first display models for a whole log
run(record, number)        one record's display model
replayable(record)         (bool, reason) — can this be replayed at all
plans(record)              the recorded plans that can be replayed
start_world(record)        the world the run recorded, or None
timeline(record, plan)     the simulator's own replay timeline
facts_rows(run)            run, backend, latency, attempts
attempts_html(run)         the run's attempt log
timeline_html(run, plan)   the run's timeline strip
runs_html(runs)            the log table
meta_html(run, plan)       the selected run's header
facts_html(rows)           the four readouts
source_html(...)           where this replay came from
"""
from __future__ import annotations

import html as _html

from backend.vision.map_vision import check_world_report
from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.panels.engine import backend_label
from frontend.simulation import player as playback

# Verdict marks for a logged run: it succeeded, or it did not.
_MARKS: dict[bool, str] = {True: "✓", False: "✕"}

_STATE_COLORS: dict[str, str] = {
    "success": C.SUCCESS,
    "error": C.ERROR,
    "warning": C.WARNING,
    "neutral": C.TEXT_SECONDARY,
    "running": C.RUNNING,
}

# The two world checks a world must pass to be *runnable*.  Reachability is not
# a precondition for replaying a plan that already ran, so it is not required.
_REPLAY_CHECKS: tuple[str, ...] = ("valid", "in_bounds")


def _e(value: object) -> str:
    """HTML-escape any value to a safe string."""
    return _html.escape(str(value))


def _plural(count: int, noun: str) -> str:
    """``1 action`` / ``6 actions``."""
    return f"{count} {noun}" if int(count) == 1 else f"{int(count)} {noun}s"


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


def run(record: object, number: int) -> dict:
    """Display model for one log record, oldest being run 1.

    Every value comes from the record; nothing is filled in from the app's
    current state, which is what makes the replay the *run's* replay.
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

    return {
        "number": int(number),
        "id": f"run-{int(number)}",
        "label": f"Run {int(number)}",
        "when": _when(record.get("timestamp")),
        "timestamp": record.get("timestamp"),
        "instruction": str(record.get("instruction") or ""),
        "backend": backend,
        "backend_label": backend_label(backend),
        "latency": latency_value,
        "latency_label": f"{latency_value:.2f} s" if latency_value is not None else "—",
        "attempts": attempts_value,
        "attempts_label": str(attempts_value),
        "history_length": len(history),
        "failed_attempts": len(failed),
        "success": success,
        "state": "success" if success else "error",
        "mark": _MARKS[success],
        "world": start_world(record),
        "replayable": can_replay,
        "reason": reason,
        "plans": plan_options,
        "record": record,
    }


def runs(records: list[dict] | None) -> list[dict]:
    """Display models for a whole log, newest first (run numbers stay stable).

    The run number counts from the start of the log, so it does not change when
    the log grows; the list is simply reversed for display.
    """
    records = [record for record in (records or [])]
    models = [run(record, index) for index, record in enumerate(records, start=1)]
    return list(reversed(models))


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
    return playback.build_timeline(world, actions)


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
        return (
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED}'>No runs have been logged yet.</div>"
        )

    header = (
        f"<div style='display:flex;gap:{S.px(S.SM)};padding:{S.px(S.XS)} 0;"
        f"border-bottom:1px solid {C.BORDER_DEFAULT};font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};"
        f"letter-spacing:{T.TRACKING_WIDE};text-transform:uppercase'>"
        f"<span style='width:{S.px(46)}'>run</span>"
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
        rows.append(
            f"<div class='gb-replay-run' data-run='{model['number']}' "
            f"data-backend='{_e(model['backend'])}' "
            f"data-latency='{_e(model['latency_label'])}' "
            f"data-attempts='{model['attempts']}' "
            f"data-replayable='{str(model['replayable']).lower()}' "
            f"style='display:flex;gap:{S.px(S.SM)};align-items:baseline;"
            f"padding:{S.px(S.XS)} 0;border-bottom:1px solid {C.BORDER_SUBTLE};"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px'>"
            f"<span style='width:{S.px(46)};color:{color}'>{model['mark']} "
            f"#{model['number']}</span>"
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
    return header + "".join(rows)


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
    cards: list[str] = []
    for row in rows:
        color = _STATE_COLORS.get(row.get("state", "neutral"), C.TEXT_PRIMARY)
        cards.append(
            f"<div class='gb-replay-fact' data-fact='{_e(row['id'])}' "
            f"data-state='{_e(row.get('state', 'neutral'))}' "
            f"style='display:flex;flex-direction:column;gap:{S.px(S.XS)};"
            f"padding:{S.px(S.SM)} {S.px(S.MD)};background:{C.BG_SURFACE};"
            f"border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_MD)}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
            f"text-transform:uppercase'>{_e(row['label'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
            f"color:{color}'>{_e(row['value'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED}'>{_e(row.get('detail', ''))}</span>"
            f"</div>"
        )
    return (
        f"<div style='display:grid;"
        f"grid-template-columns:repeat(auto-fit,minmax({S.px(160)},1fr));"
        f"gap:{S.px(S.SM)}'>" + "".join(cards) + "</div>"
    )


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
