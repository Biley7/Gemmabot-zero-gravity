"""``planner`` — turn an instruction into a plan, and prove it before returning.

    from backend.api import planner

    result = planner.plan("go to the goal", world, backend="api", max_tries=3)
    if result["approved"] is not None:
        print("sealed:", result["approved"].approval_id)
    else:
        print("refused:", result["reason"], result["verification"])

``plan`` runs the same bounded propose → parse → verify → repair loop the console
runs, and returns a :class:`RunResult`.  It never executes: an ``ApprovedPlan``
handed back here is sealed for execution, and only ``runtime.execute`` steps the
simulator.

Two ways in, one contract out
-----------------------------
* **An instruction** — a planner answers it.  ``backend`` selects one of the
  shipped adapters (``api``, ``local``, ``auto``) or any name a deployment
  registered; ``planner=`` takes a ``Planner`` object or a plain
  ``ask(instruction, world) -> str`` callable, which is how a test or a tool runs
  the loop with no network at all.
* **A plan you already have** — pass ``plan=[...]`` (whatever produced it) and no
  planner is consulted: the supplied plan is verified and approved exactly as a
  model's answer would be, and ``planner`` reports ``"supplied"``.
"""
from __future__ import annotations

import time
from typing import Any

from backend.api.contracts import (
    ContractError,
    RunResult,
    require_instruction,
    require_max_tries,
    require_mode,
    require_plan,
    require_world,
    resolve_mode,
    run_result,
    was_repaired,
)
from backend.guard import pipeline as guard_pipeline
from backend.guard.planner import CallablePlanner, build_planner

# What a supplied plan is attributed to.  A caller's plan is not a model's.
SUPPLIED = "supplied"

# The planner names the shipped adapters answer to.  Anything else is either a
# name a deployment registered with ``guard.planner.register_planner`` or not a
# planner at all — :func:`build` resolves both by asking the registry.
SHIPPED_BACKENDS: tuple[str, ...] = ("api", "local", "auto")


def _planner_from(value: Any) -> Any:
    """Adapt ``planner=`` into something with ``.propose(instruction, world)``."""
    if value is None:
        return None
    if hasattr(value, "propose"):
        return value
    if callable(value):
        name = str(getattr(value, "__name__", "") or "callable")
        return CallablePlanner(name, value)
    raise ContractError(
        "planner= must be a Planner (a .propose(instruction, world)) or an "
        f"ask(instruction, world) callable, got {type(value).__name__}"
    )


def build(backend: str | None = "auto", *, planner: Any = None) -> Any:
    """The planner adapter for *backend*, or the one the caller supplied.

    ``backend=None`` (or an empty string) means "no backend was named": the
    supplied ``planner`` wins, and without one the default ``auto`` policy
    applies.  Raises :class:`ContractError` when both are given (which would
    mean two different answers to "who plans this?") or when the backend is
    not a registered one.
    """
    supplied = _planner_from(planner)
    named = str(backend or "").strip()
    if supplied is not None and named:
        raise ContractError(
            "pass either backend= or planner=, not both: backend names a "
            "registered planner and planner= supplies one"
        )
    if supplied is not None:
        return supplied
    try:
        return build_planner(named or "auto")
    except ValueError as exc:
        raise ContractError(f"unknown backend: {exc}") from exc


def plan(
    instruction: str,
    world: dict,
    *,
    backend: str | None = None,
    max_tries: int = 3,
    plan: list[dict] | None = None,
    mode: str | None = None,
    planner: Any = None,
    on_attempt: Any = None,
) -> RunResult:
    """Plan *instruction* in *world* and return the run's structured result.

    ``backend`` selects a shipped adapter (``api`` / ``local`` / ``auto``) or a
    name a deployment registered; the default applies the ``auto`` policy.
    ``planner=`` supplies a planner directly instead — a ``Planner`` object or
    a plain ``ask(instruction, world) -> str`` callable.

    ``max_tries`` bounds the repair loop (at least 1).  ``on_attempt`` is called
    with each attempt record the moment it is made, so a caller can stream
    progress without this module knowing what a display is.

    Raises :class:`ContractError` for a malformed request; a plan the guard
    refuses is a returned result with ``approved: None``, not an exception.
    """
    text = require_instruction(instruction)
    canonical = require_world(world)
    tries = require_max_tries(max_tries)
    declared = require_mode(mode)

    if plan is not None:
        return _validate_supplied(text, canonical, plan, mode=declared,
                                  backend=backend, planner=planner)

    adapter = build(backend, planner=planner)
    outcome = guard_pipeline.plan(text, canonical, adapter, max_tries=tries,
                                  on_attempt=on_attempt)
    return run_result(
        instruction=text,
        world=canonical,
        planner=str(getattr(adapter, "name", "") or "planner"),
        mode=resolve_mode(getattr(adapter, "name", ""), declared),
        approved=outcome["approved"],
        actions=outcome["actions"],
        attempts=int(outcome["attempts"]),
        verification=outcome["verification"],
        latency=float(outcome["latency"]),
        history=outcome["history"],
        error=outcome["error"] or None,
        repaired=was_repaired(outcome["history"]),
    )


def _validate_supplied(
    text: str,
    world: dict,
    plan: list[dict],
    *,
    mode: str | None,
    backend: str | None,
    planner: Any,
) -> RunResult:
    """Verify and approve a plan the caller already has — no model is called."""
    if backend is not None or planner is not None:
        raise ContractError(
            "a supplied plan= is validated, not asked for: drop backend= and "
            "planner=, or omit plan= and let a planner propose one"
        )
    actions = require_plan(plan)
    started = time.perf_counter()
    verification = guard_pipeline.verify(world, actions)
    approved = (
        guard_pipeline.approve(world, actions, instruction=text, planner=SUPPLIED)
        if verification.get("ok") is True
        else None
    )
    latency = time.perf_counter() - started
    return run_result(
        instruction=text,
        world=world,
        planner=SUPPLIED,
        mode=resolve_mode(SUPPLIED, mode),
        approved=approved,
        # A refused supplied plan is not echoed back: the caller has it, and
        # ``actions`` in this contract means the plan the guard verified.
        actions=actions if approved is not None else None,
        attempts=1,
        verification=verification,
        latency=latency,
        history=[{
            "attempt": 1,
            "ok": verification.get("ok") is True,
            "feedback": str(verification.get("reason") or ""),
            "actions": actions,
        }],
    )
