"""Canonical representations for the GemmaBot Guard.

Owner: BACKEND.  One definition per concept, so every layer — planner,
validator, simulator, repair loop, execution, logger, UI — speaks the same
shapes:

    World              {"robot", "dir", "goal", "walls"}
    Action             {"cmd": str, "steps": int?}
    Plan               {"thought": str, "actions": [Action, ...]}
    VerificationResult {"ok", "reason", "checks": [...]}
    ExecutionResult    {"ok", "reached", "world", "log", "verified", "approval_id"}
    ApprovedPlan       a plan that passed verification, sealed with a digest

These are the shapes the runtime already produces (see docs/CONTRACTS.md for
examples); this module is where they are defined, structurally checked and
copied.  Semantic validation is deliberately *not* here: which commands are
valid belongs to ``backend.verifier.harness.verify_plan``, and whether a world
is well-formed/robot-reachable belongs to
``backend.vision.map_vision.check_world_report``.

Safety note
-----------
``ApprovedPlan`` is only produced by ``backend.guard.pipeline.approve()``,
which re-runs verification and seals the world snapshot + actions into
``approval_id``.  ``execute()`` re-verifies and re-computes the digest, so a
tampered or hand-built plan cannot be executed even if a caller constructs an
``ApprovedPlan`` by hand.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

from gemmabot.simulator import DIRS


class World(TypedDict):
    """The canonical robot world (8x8 grid coordinates, x=column, y=row)."""

    robot: list[int]           # [x, y]
    dir: str                   # "N" | "E" | "S" | "W"
    goal: list[int]            # [x, y]
    walls: list[list[int]]     # [[x, y], ...]


class Action(TypedDict):
    """One simulator command: ``turn_left``, ``turn_right`` or ``forward``."""

    cmd: str
    steps: NotRequired[int]    # read only by "forward"


class Plan(TypedDict):
    """A model's proposed plan, before verification."""

    thought: str
    actions: list[Action]


class VerificationCheck(TypedDict):
    """One check's verdict.  ``ok`` is ``None`` when it was never proven."""

    id: str
    label: str
    ok: bool | None
    detail: str
    data: dict


class VerificationResult(TypedDict):
    """``verify_plan``'s verdict: ok only when every check is ``True``."""

    ok: bool
    reason: str
    checks: list[VerificationCheck]


class ExecutionResult(TypedDict):
    """The outcome of a simulation or an approved execution."""

    ok: bool                   # the simulator applied every action
    reached: bool              # the robot stands on the goal
    world: World               # the world after the steps
    log: list[dict]            # {step, action, message} per applied action
    verified: bool             # True only for an approved execution
    approval_id: str | None    # the sealed digest, or None for simulation


def _cell(value: Any, what: str) -> list[int]:
    """Return ``[x, y]`` for a coordinate pair, or raise a readable error."""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(isinstance(v, bool) or not isinstance(v, int) for v in value)
    ):
        raise ValueError(f"{what} must be an [x, y] pair of integers, got {value!r}")
    return [int(value[0]), int(value[1])]


def canonical_world(world: Any) -> World:
    """Structural check + deep copy of *world* into the canonical shape.

    Checks the four required keys, the heading, and the coordinate shapes.
    Does not check bounds, wall overlap, robot==goal or reachability — those
    are semantic findings owned by ``check_world_report``.
    """
    if not isinstance(world, dict):
        raise ValueError(f"world must be a dict, got {type(world).__name__}")
    missing = [key for key in ("robot", "dir", "goal", "walls") if key not in world]
    if missing:
        raise ValueError(f"world is missing required key(s): {', '.join(missing)}")
    if world["dir"] not in DIRS:
        raise ValueError(f"world has invalid heading: {world['dir']!r}")

    walls = world["walls"]
    if not isinstance(walls, list):
        raise ValueError(
            f"world walls must be a list of [x, y] cells, got {type(walls).__name__}"
        )

    return {
        "robot": _cell(world["robot"], "world robot"),
        "dir": world["dir"],
        "goal": _cell(world["goal"], "world goal"),
        "walls": [_cell(cell, f"wall {i}") for i, cell in enumerate(walls, start=1)],
    }


def canonical_actions(actions: Any, *, allow_empty: bool = False) -> list[Action]:
    """Structural check + deep copy of an action list.

    Requires dicts carrying a non-empty string ``cmd``.  Which commands exist
    is the validator's contract, not this function's.
    """
    if not isinstance(actions, list):
        raise ValueError(f"plan must be a list of actions, got {type(actions).__name__}")
    if not actions and not allow_empty:
        raise ValueError("plan must contain at least one action")
    checked: list[Action] = []
    for index, action in enumerate(actions, start=1):
        if (
            not isinstance(action, dict)
            or not isinstance(action.get("cmd"), str)
            or not action["cmd"]
        ):
            raise ValueError(f"action {index} is not a valid action dict: {action!r}")
        checked.append(copy.deepcopy(action))
    return checked


def approval_digest(world: World, actions: list[Action]) -> str:
    """A stable digest of the exact world + actions an approval covers.

    Key order and tuple/list differences cannot change the digest, so a
    re-computed digest matches exactly when nothing was tampered with.
    """
    payload = json.dumps(
        {"world": world, "actions": list(actions)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovedPlan:
    """A verified plan, bound to the world it was verified against.

    Produced only by ``backend.guard.pipeline.approve()``.  ``execute()``
    re-verifies the actions and recomputes :meth:`digest`, so an instance that
    was tampered with — or hand-built — is refused.
    """

    instruction: str
    planner: str
    world: World
    actions: tuple[Action, ...]
    verification: VerificationResult
    approval_id: str

    def action_list(self) -> list[Action]:
        """The actions as a fresh list (the tuple stays immutable)."""
        return [copy.deepcopy(dict(action)) for action in self.actions]

    def digest(self) -> str:
        """Recompute the approval digest from the current contents."""
        return approval_digest(self.world, [dict(action) for action in self.actions])
