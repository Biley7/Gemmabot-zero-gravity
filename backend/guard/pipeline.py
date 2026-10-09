"""GemmaBot Guard — propose, verify, repair, approve; execute only approved plans.

Owner: BACKEND.

    AI model
       │  (Planner.propose)
       ▼
    plan()  ── parse (backend.parsing) ── verify_plan ── repair ──► ApprovedPlan
                                                                     │
                                            execute(approved) ───────┘  re-verifies,
                                                                        then simulates

Separation of concerns
----------------------
* planning     ``backend.guard.planner`` (Planner implementations)
* parsing      ``backend.parsing`` (one implementation)
* validation   ``backend.verifier.harness.verify_plan``
* simulation   ``simulate()`` below (the simulator's own step loop)
* repair       ``backend.verifier.harness.plan_with_repair`` (bounded)
* execution    ``execute()`` below (approval required, re-verified)
* logging      ``backend.logger`` (callers log; the guard only returns facts)

Safety invariant
----------------
``execute()`` refuses anything that is not an ``ApprovedPlan`` sealed by
``approve()``, re-runs verification against the approved world snapshot, and
re-computes the approval digest.  A UI bug that mutates a plan, a world or an
approval object cannot reach the simulator: the mismatch is detected and
nothing steps.  ``simulate()`` is the deliberate exception — it is the plain
deterministic simulator used to *demonstrate* plans (including refused ones in
the Safety Lab and the Replay tab); it is not an execution gate.
"""
from __future__ import annotations

import copy
import time
from typing import Any, Callable

from backend.guard.contracts import (
    ApprovedPlan,
    World,
    approval_digest,
    canonical_actions,
    canonical_world,
)
from backend.guard.planner import Planner
from backend.logger.logger import redact_secrets
from backend.verifier.harness import plan_with_repair, verify_plan
from gemmabot.simulator import reached_goal, step

AttemptCallback = Callable[[dict], None]
StepCallback = Callable[[dict, dict], None]


# ---------------------------------------------------------------------------
# Verification helpers (single implementation reused by engine and tests)
# ---------------------------------------------------------------------------

def verify(world: World, actions: list[dict]) -> dict:
    """Canonical structured verification of *actions* against *world*."""
    return verify_plan(world, actions)


def last_attempted_actions(history: list[dict] | None) -> list[dict] | None:
    """The most recent parsed action list in a run's history, if there is one."""
    for record in reversed(history or []):
        candidate = record.get("actions")
        if isinstance(candidate, list) and candidate:
            return candidate
    return None


def verify_run(
    world: dict,
    actions: list[dict] | None,
    history: list[dict] | None,
) -> dict | None:
    """Structured verification of the plan a run produced — or last attempted.

    Returns ``verify_plan``'s result extended with the ``actions`` it verified,
    or ``None`` when no attempt produced anything runnable.
    """
    target = actions if isinstance(actions, list) and actions else None
    if target is None:
        target = last_attempted_actions(history or [])
    if not target:
        return None

    outcome = dict(verify_plan(world, target))
    outcome["actions"] = target
    return outcome


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------

def approve(
    world: dict,
    actions: list[dict] | None,
    *,
    instruction: str = "",
    planner: str = "",
) -> ApprovedPlan | None:
    """Re-verify *actions* against *world* and seal an ``ApprovedPlan``.

    Returns ``None`` unless every check passes; the returned object carries the
    world snapshot, the canonical actions, the verification result and a digest
    of both.  This is the only way an ``ApprovedPlan`` is produced.
    """
    if not isinstance(actions, list) or not actions:
        return None
    try:
        snapshot = canonical_world(world)
        sealed = canonical_actions(actions)
    except ValueError:
        return None

    result = verify_plan(snapshot, sealed)
    if result.get("ok") is not True:
        return None

    return ApprovedPlan(
        instruction=instruction,
        planner=planner,
        world=snapshot,
        actions=tuple(sealed),
        verification=result,
        approval_id=approval_digest(snapshot, sealed),
    )


# ---------------------------------------------------------------------------
# The guard loop: propose → parse → verify → repair → approve
# ---------------------------------------------------------------------------

def plan(
    instruction: str,
    world: dict,
    planner: Planner,
    max_tries: int = 3,
    on_attempt: AttemptCallback | None = None,
) -> dict:
    """Run one instruction through the bounded propose/verify/repair loop.

    Never executes and never mutates *world*: the harness only simulates deep
    copies.  Returns the run facts plus ``approved`` — an ``ApprovedPlan`` when
    a plan passed verification, else ``None``.
    """
    tries = max(1, int(max_tries))
    start = time.perf_counter()
    error: str | None = None
    actions: list[dict] | None = None
    attempts = 0
    history: list[dict] = []

    try:
        actions, attempts, history = plan_with_repair(
            instruction,
            copy.deepcopy(world),
            planner.propose,
            max_tries=tries,
            on_attempt=on_attempt,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, never fatal
        error = redact_secrets(f"{type(exc).__name__}: {exc}")
    latency = time.perf_counter() - start

    if actions is None and error is None:
        # The harness redacts model-error feedback at the source; repeat it
        # here so a custom planner cannot smuggle a secret into the result.
        error = redact_secrets(
            str(history[-1].get("feedback")) if history
            else "planning produced no valid plan"
        )

    verification = verify_run(world, actions, history)
    approved = (
        approve(
            world,
            actions,
            instruction=instruction,
            planner=getattr(planner, "name", ""),
        )
        if actions is not None
        else None
    )

    return {
        "actions": actions,
        "attempts": attempts,
        "history": history,
        "latency": latency,
        "backend": getattr(planner, "name", "auto"),
        "error": error,
        "verification": verification,
        "approved": approved,
    }


# ---------------------------------------------------------------------------
# Execution (approval required) and simulation (demonstration)
# ---------------------------------------------------------------------------

def _step_loop(
    world: World,
    actions: list[dict],
    on_step: StepCallback | None,
) -> tuple[dict, list[dict], bool]:
    """Apply each action in order with the simulator; stop at the first refusal."""
    sim = copy.deepcopy(world)
    log: list[dict] = []
    ok = True

    for index, action in enumerate(actions, start=1):
        message = step(sim, action)
        entry = {"step": index, "action": action, "message": message}
        log.append(entry)
        if on_step is not None:
            on_step(entry, sim)
        if message.startswith("blocked") or message.startswith("unknown"):
            ok = False
            break

    return sim, log, ok


def _refused(approved: ApprovedPlan, reason: str) -> dict:
    """A refusal result that carries no execution and no telemetry success."""
    world = canonical_world(approved.world)
    return {
        "ok": False,
        "reached": reached_goal(world),
        "world": world,
        "log": [],
        "verified": False,
        "approval_id": approved.approval_id,
        "refused": reason,
    }


def execute(
    approved: ApprovedPlan,
    on_step: StepCallback | None = None,
) -> dict:
    """Execute an approved plan — only an approved plan.

    Re-verifies the actions against the approved world snapshot and re-computes
    the approval digest before a single step runs.  Returns
    ``ok=False`` with ``verified=False`` and an empty log when the plan,
    world or digest does not match, so a caller can never show a refusal as a
    successful execution.
    """
    if not isinstance(approved, ApprovedPlan):
        raise TypeError(
            "execute() requires an ApprovedPlan produced by guard.approve(); "
            "use simulate() to demonstrate an unapproved plan."
        )

    world = canonical_world(approved.world)
    actions = approved.action_list()

    result = verify_plan(world, actions)
    if result.get("ok") is not True:
        return _refused(approved, f"verification failed: {result.get('reason', '')}")
    if approval_digest(world, actions) != approved.approval_id:
        return _refused(approved, "approval digest does not match its world + actions")

    sim, log, ok = _step_loop(world, actions, on_step)
    return {
        "ok": ok,
        "reached": reached_goal(sim),
        "world": sim,
        "log": log,
        "verified": True,
        "approval_id": approved.approval_id,
    }


def simulate(
    world: dict,
    actions: list[dict] | None,
    on_step: StepCallback | None = None,
) -> dict:
    """Deterministic simulation of *any* plan — demonstration, never approval.

    Used by the Safety Lab and the Replay tab to replay plans (including the
    ones the verifier refused) and by the player to build timelines.  It marks
    the result ``verified=False`` so a simulated plan can never be mistaken for
    an approved execution.
    """
    canonical = canonical_world(world)
    checked = canonical_actions(actions or [], allow_empty=True)
    sim, log, ok = _step_loop(canonical, checked, on_step)
    return {
        "ok": ok,
        "reached": reached_goal(sim),
        "world": sim,
        "log": log,
        "verified": False,
        "approval_id": None,
    }
