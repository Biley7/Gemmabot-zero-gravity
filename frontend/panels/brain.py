"""GemmaBot Guard console — structured run metadata for one planning run.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

What the console shows
----------------------
Only facts a run actually produced: which backend answered, the model id
``gemmabot.config`` holds for it, how many attempts the repair loop made, the
measured latency, the size of the plan, the verdicts the run reached
(VERIFICATION · SIMULATION · EXECUTION) and the four checks
``backend.verifier.harness.verify_plan`` evaluated.  Model reasoning is
deliberately absent: the console renders metadata, never a transcript, so there
is no chain of thought in it.

Two rules the console never breaks:

* a check that was never proven (``ok is None``) is drawn as "–" with the
  reason it is unproven — an unproven check is never shown as a pass;
* a verdict nothing produced is drawn as "—" — SIMULATION without a timeline
  is *not run*, not *passed*.

Public surface
--------------
brain_metadata(...)        -> dict   display model for one run
brain_panel_html(meta)     -> str    the console, built from design-system parts
model_family(model_id)     -> str    "gemma-4-26b-a4b-it" -> "Gemma 4"
"""
from __future__ import annotations

from typing import Any

from backend.verifier.harness import VERIFICATION_CHECKS
from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.components.blocks import escape as _e, state_color as _state_color

# The loop states the console reports.  They are not invented: the app moves
# through them from real events (an attempt in flight, an attempt that failed
# and is being repaired, a plan that was verified and is executing), plus
# ``ready`` — the session that has not run anything at all, which is where the
# console starts.
STATUS_LABELS: dict[str, str] = {
    "ready": "Ready",
    "thinking": "Thinking",
    "repairing": "Repairing",
    "executing": "Executing",
}

# StatusChip states from the design system.
STATUS_STATES: dict[str, str] = {
    "ready": "neutral",
    "thinking": "thinking",
    "repairing": "warning",
    "executing": "running",
}

# Check marks: True / False / unproven (None).
_MARKS: dict[Any, str] = {True: "✓", False: "✗", None: "–"}
_MARK_COLORS: dict[Any, str] = {
    True: C.SUCCESS,
    False: C.ERROR,
    None: C.TEXT_MUTED,
}

# Verdict vocabulary for the three console rows.  A verdict is only ever
# claimed by the artifact that produced it; "unknown" is drawn as "—".
_VERDICT_LABELS: dict[str, str] = {
    "passed": "PASSED",
    "failed": "FAILED",
    "unknown": "—",
}
_VERDICT_STATES: dict[str, str] = {
    "passed": "success",
    "failed": "error",
    "unknown": "neutral",
}
_EXECUTION_LABELS: dict[str, str] = {
    "approved": "APPROVED",
    "refused": "REFUSED",
    "unknown": "—",
}
_EXECUTION_STATES: dict[str, str] = {
    "approved": "success",
    "refused": "error",
    "unknown": "neutral",
}




def attempt_status(record: dict, max_tries: int) -> tuple[str, str]:
    """The loop state one harness attempt record moves the panel into.

    ``(status_key, detail)``.  A failed attempt means the loop is repairing
    (the next prompt carries that failure); an accepted attempt means the
    verified plan is about to execute.  Both come straight from the record the
    harness emitted, so the live status is never assumed.
    """
    attempt = int(record.get("attempt") or 0)
    feedback = str(record.get("feedback") or "no feedback")
    if record.get("ok"):
        return (
            "executing",
            f"attempt {attempt}/{int(max_tries)} verified — executing the plan",
        )
    return (
        "repairing",
        f"attempt {attempt}/{int(max_tries)} failed: {feedback}",
    )


def _count(count: int, noun: str) -> str:
    """``1 action`` / ``10 actions``."""
    return f"{count} {noun}" if int(count) == 1 else f"{int(count)} {noun}s"


# ---------------------------------------------------------------------------
# Model naming
# ---------------------------------------------------------------------------

def model_family(model_id: str | None) -> str:
    """Human name for a configured model id.

    ``"gemma-4-26b-a4b-it"`` → ``"Gemma 4"``, ``"gemma4:e4b"`` → ``"Gemma 4"``.
    Reads the id only: an unrecognised id is shown verbatim rather than guessed.
    """
    if not model_id:
        return "—"
    name = str(model_id).strip()
    lowered = name.lower()
    for family in ("gemma-4", "gemma-3", "gemma-2", "gemma-1"):
        if family in lowered or family.replace("-", "") in lowered:
            return family.replace("-", " ").title()
    if "gemma" in lowered:
        return "Gemma"
    return name


# ---------------------------------------------------------------------------
# Display model
# ---------------------------------------------------------------------------

def _normalise_checks(checks: list[dict] | None) -> list[dict]:
    """Exactly the harness checks, in the harness order, as display records.

    Anything the caller did not supply — or supplied with a non-boolean
    verdict — stays unproven (``ok=None``) instead of becoming a pass.
    """
    known = {check_id for check_id, _ in VERIFICATION_CHECKS}
    provided: dict[str, dict] = {}
    for entry in checks or []:
        if isinstance(entry, dict) and entry.get("id") in known:
            provided[entry["id"]] = entry

    out: list[dict] = []
    for check_id, label in VERIFICATION_CHECKS:
        entry = provided.get(check_id) or {}
        verdict = entry.get("ok")
        ok = verdict if (verdict is True or verdict is False) else None
        out.append({
            "id": check_id,
            "label": label,
            "ok": ok,
            "detail": str(entry.get("detail") or "not evaluated"),
        })
    return out


def _verification_verdict(checks: list[dict]) -> dict:
    """PASSED / FAILED / — for the four checks, from the checks themselves."""
    proven = [entry for entry in checks if entry["ok"] is not None]
    if not proven:
        return {
            "key": "unknown",
            "label": _VERDICT_LABELS["unknown"],
            "state": _VERDICT_STATES["unknown"],
            "detail": "no check was evaluated",
        }
    failed = [entry for entry in proven if entry["ok"] is False]
    if failed:
        return {
            "key": "failed",
            "label": _VERDICT_LABELS["failed"],
            "state": _VERDICT_STATES["failed"],
            "detail": f"{len(failed)} of {len(proven)} checks failed: "
                      f"{failed[0]['label'].lower()}",
        }
    return {
        "key": "passed",
        "label": _VERDICT_LABELS["passed"],
        "state": _VERDICT_STATES["passed"],
        "detail": f"all {len(proven)} checks passed",
    }


def _simulation_verdict(executed: bool | None, halted: str | None) -> dict:
    """PASSED / FAILED / — for the simulator's own run of the approved plan."""
    if executed is None:
        return {
            "key": "unknown",
            "label": _VERDICT_LABELS["unknown"],
            "state": _VERDICT_STATES["unknown"],
            "detail": "nothing was simulated",
        }
    if not executed:
        return {
            "key": "failed",
            "label": _VERDICT_LABELS["failed"],
            "state": _VERDICT_STATES["failed"],
            "detail": "the simulator refused the approved plan",
        }
    if halted:
        return {
            "key": "failed",
            "label": _VERDICT_LABELS["failed"],
            "state": _VERDICT_STATES["failed"],
            "detail": f"the simulator halted: {halted}",
        }
    return {
        "key": "passed",
        "label": _VERDICT_LABELS["passed"],
        "state": _VERDICT_STATES["passed"],
        "detail": "every action was applied by the simulator",
    }


def _execution_verdict(
    approved: bool | None,
    executed: bool | None,
    reached: bool | None,
) -> dict:
    """APPROVED / REFUSED / — for the execution gate."""
    if approved is None:
        return {
            "key": "unknown",
            "label": _EXECUTION_LABELS["unknown"],
            "state": _EXECUTION_STATES["unknown"],
            "detail": "no approved plan",
        }
    if approved is False:
        return {
            "key": "refused",
            "label": _EXECUTION_LABELS["refused"],
            "state": _EXECUTION_STATES["refused"],
            "detail": "the execution gate refused the plan",
        }
    detail = "the execution gate sealed the plan"
    if executed is True and reached is True:
        detail += " — the robot reached the goal"
    elif executed is True:
        detail += " — the robot stopped short of the goal"
    return {
        "key": "approved",
        "label": _EXECUTION_LABELS["approved"],
        "state": _EXECUTION_STATES["approved"],
        "detail": detail,
    }


def _default_detail(
    key: str,
    *,
    attempts: int,
    max_tries: int,
    steps: int | None,
    reached: bool | None,
    error: str | None,
) -> str:
    """The status line, derived from the run's own numbers."""
    if key == "ready":
        return "no run in this session — the guard is idle"
    if key == "executing":
        if reached and steps:
            return f"goal reached after {steps} simulator steps"
        if reached:
            return "the plan ends on the goal"
        if steps:
            return f"{steps} simulator steps executed — the robot stopped short"
        return "plan verified — executing it on a copy of the world"
    if key == "repairing":
        detail = f"no verified plan after {attempts} of {max_tries} attempts"
        return f"{detail}: {error}" if error else detail
    return f"attempt {max(attempts, 1)} of {max_tries} — waiting for the model"


def brain_metadata(
    *,
    backend: str,
    model: str | None = None,
    status: str = "thinking",
    attempts: int = 0,
    max_tries: int = 3,
    latency: float | None = None,
    plan_actions: list | None = None,
    checks: list[dict] | None = None,
    steps: int | None = None,
    reached: bool | None = None,
    executed: bool | None = None,
    halted: str | None = None,
    approved: bool | None = None,
    error: str | None = None,
    detail: str | None = None,
) -> dict:
    """Display model for the Guard console — one run's structured metadata.

    Parameters
    ----------
    backend:
        Display name of the backend that answered, e.g. ``"API (Gemini)"``.
    model:
        The model id configured for that backend (``None`` when unresolved).
    status:
        ``"thinking"``, ``"repairing"`` or ``"executing"``; anything else falls
        back to ``"thinking"``.
    plan_actions:
        The plan ``verify_plan`` verified, or ``None`` when nothing was runnable.
    checks:
        ``harness.verify_plan()["checks"]`` — the four real check records.
    steps / reached:
        Simulator facts about the executed plan, when it was executed.
    executed:
        Whether the simulator applied the whole plan (``None`` when nothing ran).
    halted:
        ``"blocked"`` / ``"unknown"`` when the simulator stopped early.
    approved:
        Whether the execution gate sealed the plan (``None`` when it never got
        that far).
    detail:
        Status line override; derived from the run's numbers when omitted.
    """
    key = status if status in STATUS_LABELS else "thinking"
    count = len(plan_actions) if isinstance(plan_actions, list) else None
    check_records = _normalise_checks(checks)

    return {
        "model": {
            "family": model_family(model),
            "id": str(model) if model else None,
        },
        "backend": {"label": backend or "—"},
        "status": {
            "key": key,
            "label": STATUS_LABELS[key],
            "state": STATUS_STATES[key],
            "detail": detail or _default_detail(
                key,
                attempts=int(attempts),
                max_tries=int(max_tries),
                steps=steps,
                reached=reached,
                error=error,
            ),
        },
        "attempts": {
            "count": int(attempts),
            "max": int(max_tries),
            "label": f"{int(attempts)} / {int(max_tries)}",
        },
        "latency": {
            "seconds": latency,
            "label": f"{latency:.2f} s" if latency is not None else "—",
        },
        "plan": {
            "count": count,
            "label": "—" if count is None else _count(count, "action"),
        },
        "checks": check_records,
        "verified": all(entry["ok"] is True for entry in check_records),
        "verification": _verification_verdict(check_records),
        "simulation": _simulation_verdict(executed, halted),
        "execution": _execution_verdict(approved, executed, reached),
        "steps": steps,
        "reached": reached,
    }


def run_metadata(
    *,
    backend_label: str,
    model: str | None,
    verification: dict | None,
    actions: list | None,
    attempts: int,
    max_tries: int,
    latency: float | None,
    steps: int | None = None,
    reached: bool | None = None,
    executed: bool | None = None,
    halted: str | None = None,
    approved: bool | None = None,
    error: str | None = None,
) -> dict:
    """Guard metadata for a finished run: the verified plan and its checks.

    Reads only structured fields — the plan, the verifier's checks and the run
    numbers.  ``verification`` is ``engine.verify_run()``'s report when a plan
    was verified, and ``None`` when nothing runnable came out of the loop (the
    four checks then stay unproven).  A run that produced no plan is still
    ``repairing``: the loop ended while repairing.
    """
    verification = verification or {}
    plan = verification.get("actions") or actions
    return brain_metadata(
        backend=backend_label,
        model=model,
        status="executing" if actions is not None else "repairing",
        attempts=attempts,
        max_tries=max_tries,
        latency=latency,
        plan_actions=plan,
        checks=verification.get("checks"),
        steps=steps,
        reached=reached,
        executed=executed,
        halted=halted,
        approved=approved,
        error=error,
    )


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _field(
    field_id: str,
    label: str,
    value: str,
    detail: str = "",
    state: str = "neutral",
) -> str:
    """One labelled console cell: what it is, what it reads, why.

    *state* colours the value the way the rest of the app colours a verdict
    (success / error / running / thinking); a neutral value keeps the telemetry
    colour, so a plain number never looks like a verdict.
    """
    detail_html = (
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};letter-spacing:0.02em;word-break:break-all'>"
        f"{_e(detail)}</span>"
        if detail else ""
    )
    colour = C.TELEMETRY_VALUE if state == "neutral" else _state_color(state)
    return (
        f"<div data-field='{_e(field_id)}' data-value='{_e(value)}' "
        f"data-state='{_e(state)}' "
        f"title='{_e(f'{label}: {value}' + (f' — {detail}' if detail else ''))}' "
        f"style='display:flex;flex-direction:column;"
        f"gap:{S.px(S.XS)};padding:{S.px(S.SM)} {S.px(S.MD)};"
        f"background:{C.BG_SURFACE};border:1px solid {C.BORDER_SUBTLE};"
        f"border-radius:{S.px(S.RADIUS_MD)}'>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
        f"text-transform:uppercase'>{_e(label)}</span>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
        f"color:{colour};letter-spacing:0.02em'>{_e(value)}</span>"
        f"{detail_html}</div>"
    )


def _check_row(check: dict) -> str:
    """One verification row: mark, label, and the fact behind the verdict."""
    ok = check.get("ok")
    return (
        f"<div data-check='{_e(check.get('id', ''))}' "
        f"data-ok='{str(ok).lower()}' "
        f"style='display:flex;align-items:baseline;gap:{S.px(S.SM)};"
        f"padding:{S.px(S.XS)} 0;border-bottom:1px solid {C.BORDER_SUBTLE}'>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
        f"color:{_MARK_COLORS[ok]};flex-shrink:0;width:{S.px(S.MD)};"
        f"text-align:center'>{_MARKS[ok]}</span>"
        f"<span style='font-family:{T.FONT_SANS};font-size:{T.SIZE_BASE}px;"
        f"color:{C.TEXT_PRIMARY}'>{_e(check.get('label', ''))}</span>"
        f"<span style='margin-left:auto;font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};text-align:right'>"
        f"{_e(check.get('detail', ''))}</span>"
        f"</div>"
    )


def brain_panel_html(meta: dict) -> str:
    """Render *meta* (from :func:`brain_metadata`) as the Gemma Brain panel.

    Structured metadata only — no prompt, no reply, no reasoning.
    """
    status = meta.get("status", {})
    model = meta.get("model", {})
    header = (
        f"<div style='display:flex;align-items:center;justify-content:space-between;"
        f"gap:{S.px(S.SM)};flex-wrap:wrap;margin-bottom:{S.px(S.MD)}'>"
        f"{DS.status_chip(status.get('label', '—'), status.get('state', 'neutral'))}"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
        f"text-transform:uppercase'>structured metadata · no chain of thought</span>"
        f"</div>"
    )

    verification = meta.get("verification", {})
    simulation = meta.get("simulation", {})
    execution = meta.get("execution", {})
    fields = (
        f"<div style='display:grid;"
        f"grid-template-columns:repeat(auto-fit,minmax({S.px(140)},1fr));"
        f"gap:{S.px(S.SM)}'>"
        + _field(
            "model",
            "Model",
            model.get("family", "—"),
            model.get("id") or "backend not resolved",
        )
        + _field("backend", "Backend", meta.get("backend", {}).get("label", "—"))
        + _field("attempts", "Attempt", meta.get("attempts", {}).get("label", "—"))
        + _field("plan", "Plan", meta.get("plan", {}).get("label", "—"))
        + _field(
            "verification",
            "Verification",
            verification.get("label", "—"),
            verification.get("detail", ""),
            state=verification.get("state", "neutral"),
        )
        + _field(
            "simulation",
            "Simulation",
            simulation.get("label", "—"),
            simulation.get("detail", ""),
            state=simulation.get("state", "neutral"),
        )
        + _field(
            "execution",
            "Execution",
            execution.get("label", "—"),
            execution.get("detail", ""),
            state=execution.get("state", "neutral"),
        )
        + _field(
            "status",
            "Status",
            status.get("label", "—"),
            status.get("detail", ""),
        )
        + _field("latency", "Latency", meta.get("latency", {}).get("label", "—"))
        + "</div>"
    )

    # A console that has not run anything shows no verdict rows at all: four
    # unproven marks would read as four things the guard looked at.  The reader
    # gets one line saying nothing has been evaluated instead.
    if status.get("key") == "ready":
        checks_block = (
            f"<div style='margin-top:{S.px(S.MD)}'>"
            + DS.section_title("Verification checks")
            + f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED}'>– no check has been evaluated yet — "
            "run a plan</div>"
            + "</div>"
        )
    else:
        checks_block = (
            f"<div style='margin-top:{S.px(S.MD)}'>"
            + DS.section_title("Verification checks")
            + "".join(_check_row(check) for check in meta.get("checks", []))
            + "</div>"
        )

    return DS.panel(header + fields + checks_block, title="GemmaBot Guard")
