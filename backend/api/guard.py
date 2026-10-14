"""``guard`` — verify a plan, seal it, or demonstrate it.  Never execute.

    from backend.api import guard

    verdict = guard.verify(world, actions)            # structured, current facts
    if verdict["ok"]:
        approved = guard.approve(world, actions, instruction="go to the goal")
    shown = guard.simulate(world, actions)            # verified is always False

``approve`` is the only door to an ``ApprovedPlan``: it re-runs verification and
returns the sealed capability, or ``None`` when the verifier refuses.  A refusal
is a result — read ``verdict["reason"]`` (or a ``RunResult``'s ``reason``) to
explain it.  ``simulate`` demonstrates any plan, including a refused one, and is
deliberately unable to approve: its result is always ``verified: False``.

Every entry point canonicalises its inputs first, so the caller's dicts are
never stored or mutated — the guard works on its own copies.
"""
from __future__ import annotations

from typing import Callable

from backend.api.contracts import (
    ApprovedPlan,
    ExecutionResult,
    VerificationResult,
    require_actions,
    require_plan,
    require_world,
)
from backend.guard import pipeline as guard_pipeline

StepCallback = Callable[[dict, dict], None]


def verify(world: dict, actions: list[dict]) -> VerificationResult:
    """Structured verification of *actions* against *world*.

    Returns the check-by-check verdict the rest of the platform uses; a plan
    the verifier refuses is a result with ``ok: False`` and its reason, never
    an exception.  :class:`ContractError` is raised only when the request
    itself is malformed — an invalid world or an empty/invalid action list —
    so a typo is answered by the contract rather than by a puzzling verdict.
    """
    return guard_pipeline.verify(require_world(world), require_plan(actions))


def approve(
    world: dict,
    actions: list[dict],
    *,
    instruction: str = "",
    planner: str = "",
) -> ApprovedPlan | None:
    """Seal a verified plan — the only way to obtain an ``ApprovedPlan``.

    Returns ``None`` when the verifier refuses (call :func:`verify` for the
    reason there is no exception to catch).  The returned plan carries the
    world snapshot, the canonical actions and a digest of the two; execution
    re-verifies all three, so editing the actions or the world after approval
    breaks the seal and nothing steps.

    * ``instruction`` and ``planner`` are provenance for the sealed plan — the
      caller's own labels, recorded so an execution can say what it is running.
    """
    return guard_pipeline.approve(
        require_world(world),
        require_plan(actions),
        instruction=str(instruction or ""),
        planner=str(planner or ""),
    )


def simulate(
    world: dict,
    actions: list[dict] | None = None,
    on_step: StepCallback | None = None,
) -> ExecutionResult:
    """Deterministic simulation of *any* plan — demonstration, never approval.

    ``verified`` is always ``False``: a simulated plan is not an approved plan
    and cannot be executed (``runtime.execute`` refuses the result).  An empty
    action list is allowed and demonstrates the world standing still.

    ``on_step(entry, world)`` is called after each applied action with the
    simulator's step record and the world as it stands, so a caller can stream
    a demonstration.
    """
    return guard_pipeline.simulate(
        require_world(world),
        require_actions(actions if actions is not None else [], allow_empty=True),
        on_step=on_step,
    )
