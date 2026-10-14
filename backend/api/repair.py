"""``repair`` — one honest attempt to fix a result the guard refused.

    from backend.api import repair

    result = planner.plan("go to the goal", world, max_tries=1)
    if result["approved"] is None:
        result = repair.replan(result, planner=my_planner)   # one more attempt

``replan`` re-asks the *same instruction in the same world* and shows the
planner exactly why the previous attempt failed: the verifier's own feedback and
the plan it refused — never a model transcript.  The first prompt of a replan is
the same repair prompt the guard's own loop uses between attempts, so a replanned
attempt is the same kind of repair as a repaired one, just asked for from
outside.

The planner that answers is the one the caller supplies, or the shipped adapter
the refused result came from (``api`` / ``local`` / ``auto``).  A result without
an answerable planner — a plan the caller supplied, a scripted reader — needs
``planner=`` or ``backend=``: replan never silently picks a model the previous
run did not use.
"""
from __future__ import annotations

import json
from typing import Any

from backend.api.contracts import (
    ApprovedPlan,
    ContractError,
    RunResult,
    require_instruction,
    require_max_tries,
    require_world,
    resolve_mode,
    run_result,
    was_repaired,
)
from backend.api.planner import SHIPPED_BACKENDS, build
from backend.guard import pipeline as guard_pipeline
from backend.verifier.harness import repair_prompt


def replan(
    result: dict,
    *,
    planner: Any = None,
    backend: str | None = None,
    tries: int = 1,
    on_attempt: Any = None,
) -> RunResult:
    """One more attempt at a result the guard refused, told why it failed.

    Parameters
    ----------
    result:
        A ``RunResult`` whose ``approved`` is ``None`` (``planner.plan`` output
        for a run the guard refused).  An approved result is a
        :class:`ContractError`: there is nothing to repair.
    planner / backend:
        Who asks this time — a ``Planner``, an ``ask(instruction, world)``
        callable, or a registered backend name.  Without either, the shipped
        planner the refused result names is used.
    tries:
        How many new attempts this call may make (at least 1, default 1).  A
        failed replan can be replanned again with the new result.
    on_attempt:
        Called with each new attempt record the moment it is made.

    Returns
    -------
    RunResult
        The same shape ``planner.plan`` returns, carrying the run's original
        instruction, this call's attempt history and — when the new attempts
        verify — a sealed ``ApprovedPlan``.
    """
    instruction, world = _refused_inputs(result)
    attempts = require_max_tries(tries, key="tries")
    adapter = _adapter_for(result, planner=planner, backend=backend)
    seeded = _seeded_instruction(instruction, result)

    outcome = guard_pipeline.plan(
        seeded,
        world,
        adapter,
        max_tries=attempts,
        on_attempt=on_attempt,
    )
    name = str(getattr(adapter, "name", "") or "planner")
    return run_result(
        # The result reports what the caller asked for, not the seeded prompt.
        instruction=instruction,
        world=world,
        planner=name,
        mode=resolve_mode(name),
        approved=outcome["approved"],
        actions=outcome["actions"],
        attempts=int(outcome["attempts"]),
        verification=outcome["verification"],
        latency=float(outcome["latency"]),
        history=outcome["history"],
        repaired=(
            # An approved replan is repaired by construction; a refused one only
            # if its own loop got there.
            outcome["approved"] is not None or was_repaired(outcome["history"])
        ),
        error=outcome["error"] or None,
    )


def _refused_inputs(result: dict) -> tuple[str, dict]:
    """The original instruction and world of a refused ``RunResult``."""
    if not isinstance(result, dict):
        raise ContractError(
            "replan() takes the RunResult planner.plan() returned, got "
            f"{type(result).__name__}"
        )
    if isinstance(result.get("approved"), ApprovedPlan):
        raise ContractError(
            "this result is already approved — replan() is for a result the "
            "guard refused, and there is nothing to repair"
        )
    instruction = require_instruction(result.get("instruction"))
    world = require_world(result.get("world"))
    return instruction, world


def _adapter_for(result: dict, *, planner: Any, backend: str | None) -> Any:
    """The planner for this replan: the caller's, or the refused run's own."""
    if planner is not None or backend is not None:
        return build(backend, planner=planner)
    carried = str(result.get("planner") or "").strip().lower()
    if carried in SHIPPED_BACKENDS:
        return build(carried)
    raise ContractError(
        "replan() needs a planner: this result was produced by "
        f"{carried or 'an unnamed planner'!r}, which is not a shipped backend "
        "— pass planner= (or backend=)"
    )


def _seeded_instruction(instruction: str, result: dict) -> str:
    """The original instruction plus the previous refusal, in the loop's format.

    The failure reported is the last attempt's own feedback when there is one,
    else the run's error.  The refused plan travels with it so the next planner
    can see exactly what was refused — the attempt history has no prompt or
    reply to leak.
    """
    record = _last_failure(result)
    if record is not None:
        refused = record.get("actions")
        failed_plan = ""
        if isinstance(refused, list) and refused:
            failed_plan = json.dumps({"actions": refused}, separators=(",", ":"))
        return repair_prompt(instruction, failed_plan, str(record.get("feedback") or ""))
    reason = str(result.get("error") or "").strip()
    return repair_prompt(
        instruction, "", reason or "the previous run produced no plan"
    )


def _last_failure(result: dict) -> dict | None:
    """The most recent attempt record that failed with feedback, or ``None``."""
    history = result.get("history")
    for record in reversed(history if isinstance(history, list) else []):
        if (
            isinstance(record, dict)
            and record.get("ok") is not True
            and record.get("feedback")
        ):
            return record
    return None
