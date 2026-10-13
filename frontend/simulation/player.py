"""Execution timeline — the data behind the Phase 3 animation player.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

``build_timeline()`` really executes the verified plan with the backend
simulator (``simulator.step`` through ``frontend.panels.engine.execute``) on a
deep copy of the world.  Everything the player shows therefore comes from the
simulator itself: the cells the robot visits, the direction it faces, the log
message of every action and whether it was blocked.  Nothing here invents a
frame or a success.

Timeline shape
--------------
    {
      "world":       world dict before execution (grid source of truth),
      "start":       [x, y]  robot start cell,
      "start_dir":   "N" | "E" | "S" | "W",
      "steps":       [{index, action, label, message, halted, start_ms, end_ms}],
      "events":      [{type: "move" | "turn" | "hold", step, start, ms, ...}],
      "path":        [[x, y], ...]  cells the robot occupies, in order,
      "duration_ms": 1x playback length of the whole execution,
      "cells":       number of cells traversed,
      "ok":          bool  — the simulator applied every action,
      "halted":      None | "blocked" | "unknown",
      "reached":     bool  — the robot stands on the goal,
      "final_world": world after execution,
      "log":         raw simulator entries ({step, action, message}),
      "kind":        "execution" | "preview" | "replay" (what this playback is),
      "approved":    bool  — the guard reported a verified execution,
      "refused":     the execution gate's reason, or None (nothing ran),
      "final":       [x, y]  where the robot ended up,
      "final_dir":   the direction it ended facing,
      "planned":     actions the plan contains,
      "actions_run": actions the simulator processed (incl. a halted one),
      "halted_step": index of the action that stopped the run, or None,
      "halted_label":  that action's label,
      "halted_message": the simulator's own reason ("blocked at [2, 0]"),
      "halted_at":     [x, y]  the cell the run stopped on, or None,
      "unexecuted":  planned actions the run never reached,
    }

The terminal keys are read off the same outcome as the events, so the player can
state where a run ended, why it stopped and how many actions it never reached
without guessing any of it.  ``approved`` and ``refused`` are the provenance,
and they come from the guard's own result rather than from the caller: only
``execute()`` reports ``verified``, and a refused approval reports why instead.
Both exist so a preview, and an approved plan whose gate refused it, can never
read on screen as an execution that happened.

``events`` are the animation keyframes: one 300 ms ``move`` per traversed
cell, one ``turn`` for a direction change and a short ``hold`` beat where the
simulator reported a problem.  ``start`` is an absolute 1x offset in ms, so the
player only has to interpolate — it never re-simulates anything.
"""
from __future__ import annotations

import copy
from typing import Callable

from backend.guard.contracts import ApprovedPlan
from gemmabot.simulator import DELTA, SIZE
from frontend.components import animations as A
from frontend.panels.engine import execute_approved, simulate

CELL_STEP_MS = A.CELL_STEP_MS
TURN_MS = A.TURN_MS
STEP_GAP_MS = A.STEP_GAP_MS
HALT_MS = A.HALT_MS

# What a playback *is* — the provenance the player words itself from.
# ``execution``   a guard-verified plan really stepped the simulator;
# ``preview``     an unapproved plan demonstrated in a lab (a "what if");
# ``replay``      a plan from the run log, run through the simulator again.
# A timeline that is not an execution must never read as one, and a replay must
# not be described as an unapproved plan: the log says nothing about approval.
KIND_EXECUTION = "execution"
KIND_PREVIEW = "preview"
KIND_REPLAY = "replay"
KINDS: tuple[str, ...] = (KIND_EXECUTION, KIND_PREVIEW, KIND_REPLAY)


def kind_of(timeline: dict) -> str:
    """A timeline's playback kind, defaulting to the cautious one."""
    kind = str((timeline or {}).get("kind") or KIND_PREVIEW)
    return kind if kind in KINDS else KIND_PREVIEW


# What stopped an execution — the two failures the benchmark counts separately.
# The simulator reports both as "blocked", so which one it was has to be worked
# out from the cell the robot was about to enter.
HALT_COLLISION = "collision"   # a wall stands in the way
HALT_BOUNDARY = "boundary"     # the next cell is off the grid


def halt_kind(timeline: dict | None) -> str | None:
    """What stopped a run that the simulator halted: a wall or the grid edge.

    Read off the halted step itself: the cell the robot was about to enter is
    the cell it stopped on plus its facing, and that cell is compared with the
    world's walls and the grid.  A run the simulator never stopped — or one that
    stopped for a reason other than a block — returns ``None``: it is neither a
    collision nor a boundary violation, and counting it as either would invent
    an event that did not happen.
    """
    if not isinstance(timeline, dict) or timeline.get("halted") != "blocked":
        return None
    world = timeline.get("world") if isinstance(timeline.get("world"), dict) else {}
    position = timeline.get("halted_at") or timeline.get("final")
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        return None
    direction = str(timeline.get("final_dir") or world.get("dir") or "E")
    dx, dy = DELTA.get(direction, (0, 0))
    try:
        cell = [int(position[0]) + dx, int(position[1]) + dy]
    except (TypeError, ValueError):
        return None
    if not (0 <= cell[0] < SIZE and 0 <= cell[1] < SIZE):
        return HALT_BOUNDARY
    walls = world.get("walls") if isinstance(world.get("walls"), list) else []
    return HALT_COLLISION if cell in walls else None


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def action_label(action: dict) -> str:
    """Readable label for one plan action: ``forward ×2``, ``turn right``."""
    data = action or {}
    cmd = str(data.get("cmd", "?"))
    if cmd == "forward":
        raw = data.get("steps", 1)
        try:
            steps = int(raw)
        except (TypeError, ValueError):
            steps = 1
        return f"forward ×{steps}" if steps != 1 else "forward"
    return cmd.replace("_", " ")


def _cells_between(start: list[int], end: list[int]) -> list[list[int]]:
    """Cells entered when moving in a straight line from *start* to *end*.

    The simulator moves one cell at a time along the robot's axis, so the
    partial progress of a blocked ``forward`` is recovered exactly.  Returns
    an empty list when the robot did not move.
    """
    sx, sy = int(start[0]), int(start[1])
    ex, ey = int(end[0]), int(end[1])
    if sx == ex and sy == ey:
        return []
    if sx != ex and sy != ey:  # never produced by the simulator; stay safe
        return []
    if sx == ex:
        direction = 1 if ey > sy else -1
        return [[sx, y] for y in range(sy + direction, ey + direction, direction)]
    direction = 1 if ex > sx else -1
    return [[x, sy] for x in range(sx + direction, ex + direction, direction)]


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

def _capture_steps() -> tuple[list, Callable[[dict, dict], None]]:
    """A step collector plus the callback that fills it, for one timeline."""
    captured: list[tuple[dict, dict]] = []

    def _capture(entry: dict, sim_world: dict) -> None:
        captured.append((entry, copy.deepcopy(sim_world)))

    return captured, _capture


def build_timeline(
    world: dict,
    actions: list[dict],
    *,
    kind: str = KIND_PREVIEW,
) -> dict:
    """Simulate *actions* on a copy of *world* and return the replay timeline.

    Simulation/demonstration path: it may replay any plan, including one the
    verifier refused (the Safety Lab demonstrates exactly that).  Approved
    execution uses :func:`build_approved_timeline`, which the guard
    re-verifies before stepping.  The caller's world is never mutated;
    ``final_world`` carries the outcome.

    *kind* says what the playback is, and the player words itself from it: the
    Safety Lab demonstrates a plan (``KIND_PREVIEW``), the Run History replays
    one out of the log (``KIND_REPLAY``).  Neither may be described as the
    other, and neither is an execution.
    """
    initial = copy.deepcopy(world)
    captured, capture = _capture_steps()
    outcome = simulate(initial, actions or [], on_step=capture)
    return _timeline(
        initial, outcome, captured, planned=len(actions or []), kind=kind
    )


def build_approved_timeline(approved: ApprovedPlan) -> dict:
    """The same timeline for a guard-approved plan; the guard re-verifies it.

    The approval carries the world snapshot it was verified against, so the
    timeline starts from exactly that world.
    """
    initial = copy.deepcopy(approved.world)
    captured, capture = _capture_steps()
    outcome = execute_approved(approved, on_step=capture)
    return _timeline(
        initial,
        outcome,
        captured,
        planned=len(approved.action_list()),
        kind=KIND_EXECUTION,
    )


def _timeline(
    initial: dict,
    outcome: dict,
    captured: list[tuple[dict, dict]],
    *,
    planned: int,
    kind: str,
) -> dict:
    """Derive the player timeline from one simulated/executed outcome.

    *planned* is how many actions the plan held.  The simulator stops at the
    first refusal, so only the plan's own length can say how many actions the
    run never reached — counting the captured steps would report zero.
    """
    events: list[dict] = []
    steps: list[dict] = []
    clock = 0
    previous = initial

    for index, (entry, sim_world) in enumerate(captured, start=1):
        action = entry.get("action") or {}
        message = str(entry.get("message", ""))
        blocked = message.startswith("blocked")
        unknown = message.startswith("unknown")
        halted = "blocked" if blocked else ("unknown" if unknown else None)

        before_dir = previous.get("dir", "E")
        after_dir = sim_world.get("dir", before_dir)
        before_robot = list(previous.get("robot", [0, 0]))
        after_robot = list(sim_world.get("robot", before_robot))
        cells = _cells_between(before_robot, after_robot)

        start_ms = clock

        if after_dir != before_dir:
            events.append({
                "type": "turn",
                "step": index,
                "start": clock,
                "ms": TURN_MS,
                "from_dir": before_dir,
                "to_dir": after_dir,
            })
            clock += TURN_MS

        from_cell = list(before_robot)
        for cell in cells:
            events.append({
                "type": "move",
                "step": index,
                "start": clock,
                "ms": CELL_STEP_MS,
                "from": list(from_cell),
                "to": list(cell),
                "dir": before_dir,
            })
            clock += CELL_STEP_MS
            from_cell = list(cell)

        if halted is not None:
            events.append({
                "type": "hold",
                "step": index,
                "start": clock,
                "ms": HALT_MS,
                "at": list(after_robot),
                "dir": after_dir,
                "halted": halted,
            })
            clock += HALT_MS
        elif not cells and after_dir == before_dir:
            # An action that changed nothing still deserves a beat on screen.
            events.append({
                "type": "hold",
                "step": index,
                "start": clock,
                "ms": HALT_MS,
                "at": list(after_robot),
                "dir": after_dir,
                "halted": None,
            })
            clock += HALT_MS

        steps.append({
            "index": index,
            "action": action,
            "label": action_label(action),
            "message": message,
            "halted": halted,
            "start_ms": start_ms,
            "end_ms": clock,
        })

        previous = sim_world
        if index < len(captured):
            clock += STEP_GAP_MS

    final_world = outcome["world"]
    halted_step = next((step for step in steps if step["halted"]), None)

    return {
        "world": initial,
        "start": list(initial.get("robot", [0, 0])),
        "start_dir": initial.get("dir", "E"),
        "goal": list(initial.get("goal", [])),
        "steps": steps,
        "events": events,
        "path": [list(initial.get("robot", [0, 0]))]
                + [event["to"] for event in events if event["type"] == "move"],
        "duration_ms": clock,
        "cells": sum(1 for event in events if event["type"] == "move"),
        "ok": bool(outcome["ok"]),
        "halted": halted_step["halted"] if halted_step else None,
        "reached": bool(outcome["reached"]),
        "final_world": final_world,
        "log": outcome["log"],
        # Provenance + terminal facts, all read off the run's own outcome.
        "kind": kind if kind in KINDS else KIND_PREVIEW,
        "approved": outcome.get("verified") is True,
        "refused": str(outcome.get("refused") or "") or None,
        "final": list(final_world.get("robot", initial.get("robot", [0, 0]))),
        "final_dir": final_world.get("dir", initial.get("dir", "E")),
        "planned": max(int(planned), len(steps)),
        "actions_run": len(steps),
        "halted_step": int(halted_step["index"]) if halted_step else None,
        "halted_label": str(halted_step["label"]) if halted_step else "",
        "halted_message": str(halted_step["message"]) if halted_step else "",
        "halted_at": list(final_world.get("robot", [0, 0])) if halted_step else None,
        "unexecuted": max(int(planned), len(steps)) - len(steps),
    }


def log_lines(timeline: dict) -> list[str]:
    """The execution log lines for the sidebar/expander, as before Phase 3."""
    return [
        f"step {entry['step']}: {entry['action']} -> {entry['message']}"
        for entry in timeline.get("log", [])
    ]
