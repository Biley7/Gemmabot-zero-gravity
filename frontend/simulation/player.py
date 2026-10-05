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
    }

``events`` are the animation keyframes: one 300 ms ``move`` per traversed
cell, one ``turn`` for a direction change and a short ``hold`` beat where the
simulator reported a problem.  ``start`` is an absolute 1x offset in ms, so the
player only has to interpolate — it never re-simulates anything.
"""
from __future__ import annotations

import copy

from frontend.components import animations as A
from frontend.panels.engine import execute

CELL_STEP_MS = A.CELL_STEP_MS
TURN_MS = A.TURN_MS
STEP_GAP_MS = A.STEP_GAP_MS
HALT_MS = A.HALT_MS


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

def build_timeline(world: dict, actions: list[dict]) -> dict:
    """Execute *actions* on a copy of *world* and return the replay timeline.

    The caller's world is never mutated; ``final_world`` carries the outcome.
    """
    initial = copy.deepcopy(world)
    captured: list[tuple[dict, dict]] = []

    def _capture(entry: dict, sim_world: dict) -> None:
        captured.append((entry, copy.deepcopy(sim_world)))

    outcome = execute(world, actions or [], on_step=_capture)

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
        "halted": next((step["halted"] for step in steps if step["halted"]), None),
        "reached": bool(outcome["reached"]),
        "final_world": outcome["world"],
        "log": outcome["log"],
    }


def log_lines(timeline: dict) -> list[str]:
    """The execution log lines for the sidebar/expander, as before Phase 3."""
    return [
        f"step {entry['step']}: {entry['action']} -> {entry['message']}"
        for entry in timeline.get("log", [])
    ]
