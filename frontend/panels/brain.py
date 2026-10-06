"""Gemma Brain panel — structured run metadata for one planning run.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

What the panel shows
--------------------
Only facts a run actually produced: which backend answered, the model id
``gemmabot.config`` holds for it, how many attempts the repair loop made, the
measured latency, the size of the plan, and the four checks
``backend.verifier.harness.verify_plan`` evaluated.  Model reasoning is
deliberately absent: the panel renders metadata, never a transcript, so there
is no chain of thought in it.

A check that was never proven (``ok is None``) is drawn as "—" with the reason
it is unproven — an unproven check is never shown as a pass.

Public surface
--------------
brain_metadata(...)        -> dict   display model for one run
brain_panel_html(meta)     -> str    the panel, built from design-system parts
model_family(model_id)     -> str    "gemma-4-26b-a4b-it" -> "Gemma 4"
"""
from __future__ import annotations

import html as _html
from typing import Any

from backend.verifier.harness import VERIFICATION_CHECKS
from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T

# The three loop states the panel reports.  They are not invented: the app
# moves through them from real events (an attempt in flight, an attempt that
# failed and is being repaired, a plan that was verified and is executing).
STATUS_LABELS: dict[str, str] = {
    "thinking": "Thinking",
    "repairing": "Repairing",
    "executing": "Executing",
}

# StatusChip states from the design system.
STATUS_STATES: dict[str, str] = {
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


def _e(value: object) -> str:
    """HTML-escape any value to a safe string."""
    return _html.escape(str(value))


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
    error: str | None = None,
    detail: str | None = None,
) -> dict:
    """Display model for the Brain panel — one run's structured metadata.

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
    error: str | None = None,
) -> dict:
    """Brain metadata for a finished run: the verified plan and its checks.

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
        error=error,
    )


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _field(field_id: str, label: str, value: str, detail: str = "") -> str:
    """One labelled metadata cell in the panel grid."""
    detail_html = (
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};letter-spacing:0.02em;word-break:break-all'>"
        f"{_e(detail)}</span>"
        if detail else ""
    )
    return (
        f"<div data-field='{_e(field_id)}' style='display:flex;flex-direction:column;"
        f"gap:{S.px(S.XS)};padding:{S.px(S.SM)} {S.px(S.MD)};"
        f"background:{C.BG_SURFACE};border:1px solid {C.BORDER_SUBTLE};"
        f"border-radius:{S.px(S.RADIUS_MD)}'>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
        f"text-transform:uppercase'>{_e(label)}</span>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
        f"color:{C.TELEMETRY_VALUE};letter-spacing:0.02em'>{_e(value)}</span>"
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

    fields = (
        f"<div style='display:grid;"
        f"grid-template-columns:repeat(auto-fit,minmax({S.px(148)},1fr));"
        f"gap:{S.px(S.SM)}'>"
        + _field(
            "model",
            "Model",
            model.get("family", "—"),
            model.get("id") or "backend not resolved",
        )
        + _field("backend", "Backend", meta.get("backend", {}).get("label", "—"))
        + _field(
            "status",
            "Status",
            status.get("label", "—"),
            status.get("detail", ""),
        )
        + _field("attempts", "Attempts", meta.get("attempts", {}).get("label", "—"))
        + _field("latency", "Latency", meta.get("latency", {}).get("label", "—"))
        + _field("plan", "Plan", meta.get("plan", {}).get("label", "—"))
        + "</div>"
    )

    verification = (
        f"<div style='margin-top:{S.px(S.MD)}'>"
        + DS.section_title("Verification")
        + "".join(_check_row(check) for check in meta.get("checks", []))
        + "</div>"
    )

    return DS.panel(header + fields + verification, title="Gemma Brain")
