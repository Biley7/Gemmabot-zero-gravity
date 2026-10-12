"""GemmaBot Guard console — structured run metadata for one planning run.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

What the console shows
----------------------
Only facts a run actually produced: which backend answered, the model id
``gemmabot.config`` holds for it, how many attempts the repair loop made, the
measured latency, the size of the plan and the four checks
``backend.verifier.harness.verify_plan`` evaluated.  Model reasoning is
deliberately absent: the console renders metadata, never a transcript, so there
is no chain of thought in it.

Each check is carried with the structured facts the verifier recorded behind it
(``data``: the action index it refused, the command, the cell it refused to
enter) so the interface can name a failure without quoting anything a model
wrote.  ``refusal`` carries the same thing for the *first attempt the guard
refused*, which is what makes ATTEMPT and REPAIR truthful on a run that was
repaired and then approved.

Two rules the console never breaks:

* a check that was never proven (``ok is None``) stays unproven — an unproven
  check is never shown as a pass;
* a verdict nothing produced is drawn as "—" — SIMULATION without a timeline
  is *not run*, not *passed*.

The interface the console is read through — the verdict, the seven-stage chain,
the six outcomes, a refusal and its explanation — is
``frontend.console.guard``; this module is the display model behind it.

Public surface
--------------
brain_metadata(...)        -> dict   display model for one run
run_metadata(...)          -> dict   the same, from a finished loop run
brain_panel_html(meta)     -> str    the GemmaBot Guard interface
model_family(model_id)     -> str    "gemma-4-26b-a4b-it" -> "Gemma 4"
attempt_status(record, n)  -> tuple  the loop state one attempt record moves to
"""
from __future__ import annotations

from backend.verifier.harness import VERIFICATION_CHECKS
from frontend.console import guard as guard_console

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
            # The structured facts behind a failing check: the action index, the
            # command and the cell.  Carried through so the interface can name a
            # refusal from data rather than from a detail string, which can quote
            # whatever a model put in an action dict.
            "data": entry.get("data") if isinstance(entry.get("data"), dict) else {},
        })
    return out


def _normalise_refusal(refusal: dict | None) -> dict | None:
    """The first refused attempt as a display record, or ``None``.

    *refusal* arrives from the guard as ``{"attempt": int, "verification":
    verify_plan(...)}`` — a number and the verifier's own records, never a
    prompt or a reply.  The checks are normalised exactly like the run's own, so
    a refusal and a verdict are read the same way.
    """
    if not isinstance(refusal, dict):
        return None
    checks = _normalise_checks((refusal.get("verification") or {}).get("checks"))
    if all(entry["ok"] is not False for entry in checks):
        return None
    return {
        "attempt": max(int(refusal.get("attempt") or 1), 1),
        "checks": checks,
    }


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
    refusal: dict | None = None,
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
    refusal:
        ``engine.first_refusal()`` — the first attempt the verifier refused,
        re-verified: ``{"attempt", "verification"}``.  Structured facts only (a
        number and the verifier's records), which is what lets the interface
        report a refusal without a transcript.  ``None`` when nothing was
        refused, including a run that passed first time.
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
        "refusal": _normalise_refusal(refusal),
        "verified": all(entry["ok"] is True for entry in check_records),
        "verification": _verification_verdict(check_records),
        "simulation": _simulation_verdict(executed, halted),
        "execution": _execution_verdict(approved, executed, reached),
        # The tri-states the three verdicts above are derived from, kept as the
        # run reported them: the guard interface reads these rather than
        # re-deriving them from prose, so a shared "—" can never be mistaken for
        # a measurement.  (None = nothing produced it.)
        "steps": steps,
        "reached": reached,
        "executed": executed,
        "halted": halted,
        "approved": approved,
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
    refusal: dict | None = None,
) -> dict:
    """Guard metadata for a finished run: the verified plan and its checks.

    Reads only structured fields — the plan, the verifier's checks and the run
    numbers.  ``verification`` is ``engine.verify_run()``'s report when a plan
    was verified, and ``None`` when nothing runnable came out of the loop (the
    four checks then stay unproven).  A run that produced no plan is still
    ``repairing``: the loop ended while repairing.

    ``refusal`` is ``engine.first_refusal()``'s record for the first attempt the
    guard refused, or ``None``; like every other input here it holds a plan and
    a verdict, never a prompt or a reply.
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
        refusal=refusal,
    )


# ---------------------------------------------------------------------------
# HTML — the panel is the guard interface
# ---------------------------------------------------------------------------

def brain_panel_html(meta: dict) -> str:
    """Render *meta* (from :func:`brain_metadata`) as the GemmaBot Guard panel.

    The interface — the verdict, the seven-stage chain, the six outcomes, a
    refusal and its explanation, and the muted metadata footer — lives in
    ``frontend.console.guard``, next to the rest of the console's vocabulary.
    This panel supplies the display model and nothing else, which is what keeps
    structured facts the only input: a run's transcript cannot reach the markup.
    """
    return guard_console.panel_html(meta)
