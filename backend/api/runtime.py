"""``runtime`` — execute an approved plan.  Nothing else executes.

    from backend.api import runtime

    result = planner.plan("go to the goal", world, planner=my_planner)
    outcome = runtime.execute(result)          # refuses anything unapproved
    print(outcome["execution"]["log"])

``execute`` accepts exactly two things: the sealed ``ApprovedPlan`` the guard
produced, or the ``RunResult`` that carries one.  A plan list, a world, a
refused result, a demonstration from ``guard.simulate``, or a hand-rolled
mapping all raise :class:`NotApprovedError` before the simulator is touched —
there is no code path through this module that executes an unapproved plan.

Nothing runs on trust either.  For an accepted plan the guard re-verifies the
sealed world snapshot and recomputes the approval digest first; a plan whose
actions or world were edited after approval (or whose digest was tampered with)
returns ``execution.verified: False`` with an empty log, and ``reason`` says
what happened — a refusal is reported, never disguised as an execution.
"""
from __future__ import annotations

from typing import Any, Callable

from backend.api.contracts import (
    API_VERSION,
    ApprovedPlan,
    ExecutionOutcome,
    NotApprovedError,
    execution_reason,
)
from backend.guard import pipeline as guard_pipeline

StepCallback = Callable[[dict, dict], None]


def execute(
    approved: Any,
    on_step: StepCallback | None = None,
) -> ExecutionOutcome:
    """Step the simulator with an approved plan — and with nothing else.

    Parameters
    ----------
    approved:
        An ``ApprovedPlan`` from ``planner.plan`` / ``guard.approve``, or the
        ``RunResult`` that carries one (its ``attempts`` are carried into the
        outcome).  Anything else raises :class:`NotApprovedError`.
    on_step:
        Called with each step record and the world as it stands, so a caller
        can stream an execution.

    Returns
    -------
    ExecutionOutcome
        The full structured result: ``approved``, ``reason``, ``actions``,
        ``attempts``, ``verification``, ``simulation`` (always ``None`` — this
        is an execution) and ``execution``, whose ``verified`` is ``True`` only
        for an approved plan that stepped.
    """
    plan, attempts = _approved_plan(approved)
    execution = guard_pipeline.execute(plan, on_step=on_step)
    # The verdict the runtime recomputed for the sealed plan before stepping —
    # the same check ``execute`` itself ran, reported so a refusal and a success
    # are both explained by the plan's own facts.
    verification = guard_pipeline.verify(plan.world, plan.action_list())
    return {
        "api_version": API_VERSION,
        "approved": plan,
        "reason": execution_reason(execution),
        "actions": plan.action_list(),
        "attempts": attempts,
        "verification": verification,
        "simulation": None,
        "execution": execution,
    }


def _approved_plan(value: Any) -> tuple[ApprovedPlan, int | None]:
    """The ``ApprovedPlan`` in *value* (with the run's attempts), or raise."""
    if isinstance(value, ApprovedPlan):
        return value, None
    if isinstance(value, dict):
        if "approved" not in value:
            raise NotApprovedError(
                value, detail="a dict that is not an approved run result"
            )
        carried = value.get("approved")
        if isinstance(carried, ApprovedPlan):
            attempts = value.get("attempts")
            if isinstance(attempts, bool) or not isinstance(attempts, int):
                attempts = None
            return carried, attempts
        if carried is None:
            raise NotApprovedError(
                value,
                detail="a run result the guard refused (its approved is None)",
            )
    raise NotApprovedError(value)
