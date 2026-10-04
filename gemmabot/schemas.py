"""Data contracts and TypedDict schemas for the Gemmabot project.

This file defines the shared data structures used between frontend and backend.
Changes to this file require agreement from both BACKEND and FRONTEND owners.
"""
from typing import TypedDict, List, Optional, Literal


class World(TypedDict):
    """The state of the robot world."""
    robot: List[int]           # [x, y] position
    dir: Literal["N", "E", "S", "W"]  # current heading
    goal: List[int]            # [x, y] target position
    walls: List[List[int]]     # list of [x, y] wall positions


class Action(TypedDict):
    """A single action the robot can take."""
    cmd: Literal["forward", "turn_left", "turn_right"]
    steps: Optional[int]       # only for "forward", 1-7


class Plan(TypedDict):
    """A complete plan with reasoning and actions."""
    thought: str
    actions: List[Action]


class VerifyResult(TypedDict):
    """Result of verifying a plan against the world."""
    ok: bool
    reached_goal: bool
    failed_at_index: Optional[int]
    reason: str
    final_state: World
    trace: List[str]


class AttemptRecord(TypedDict):
    """Record of a single planning attempt."""
    attempt: int
    raw_reply: str
    plan: Optional[Plan]
    verify: Optional[VerifyResult]
    error: Optional[str]


class RunResult(TypedDict):
    """Result of running an instruction through the full pipeline."""
    status: Literal["success", "failed", "error"]
    instruction: str
    backend_used: str
    world_before: World
    world_after: World
    attempts: List[AttemptRecord]
    final_plan: Optional[Plan]
    latency_s: float
    error: Optional[str]
