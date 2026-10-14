"""``runs`` — record a run in the shared log, and read the log back.

    from backend.api import runs

    result = planner.plan("go to the goal", world, planner=my_planner)
    outcome = runtime.execute(result)
    logged = runs.record(result, execution=outcome)   # one record: plan + what ran
    print(logged["run_id"])                           # 12 hex characters
    history = runs.load()                             # oldest first

A record is the run's own facts as the run had them: what was asked, which
planner answered, the plan, the verifier's verdict, and — when the caller passes
``execution=`` — what the simulator did with it.  Nothing is inferred from a
model's reply, a field the run does not have is ``None`` (*not recorded*, never
a plausible default), and secrets are redacted before the write.

The record format is the logger's, shared with the console and RobotBench, and
documented in ``docs/CONTRACTS.md``; ``actions`` and ``world`` together make the
record replayable by the simulator alone, with no model call.
"""
from __future__ import annotations

from typing import Any

from backend.api.contracts import (
    ApprovedPlan,
    ContractError,
    require_input_type,
    require_world,
    resolve_mode,
)
from backend.logger.logger import log_run, load_runs

DEFAULT_PATH = "logs/runs.jsonl"

# The execution summary the run log stores.
_SUMMARY_KEYS = ("ran", "halted", "steps")


def record(
    result: dict,
    *,
    path: str = DEFAULT_PATH,
    input_type: str | None = "text",
    model: str | None = None,
    execution: dict | None = None,
    final_position: list[int] | None = None,
    goal_reached: bool | None = None,
    run_id: str | None = None,
) -> dict:
    """Append one record for *result* to the run log and return it.

    Parameters
    ----------
    result:
        A ``RunResult`` from ``planner.plan`` / ``repair.replan``, or an
        ``ExecutionOutcome`` from ``runtime.execute`` (its approval supplies the
        instruction and plan; its execution is recorded automatically).
    path:
        JSONL file to append to; the parent directory is created as needed.
    input_type:
        ``"text"`` (default), ``"vision"`` or ``"benchmark"`` — how the run was
        asked.  ``None`` records *not recorded*; any other value is a
        :class:`ContractError`.
    model:
        The model id the run would call, or ``None`` when none applies.
    execution:
        What the plan did, when it did something: the ``ExecutionOutcome`` from
        ``runtime.execute``, the bare execution result, or a
        ``{"ran", "halted", "steps"}`` summary.  ``None`` records that the run
        did not execute — never that it failed.
    final_position / goal_reached:
        Where the robot ended up.  Derived from ``execution`` when it ran; pass
        them explicitly to record a fact the execution dict does not carry.
    run_id:
        A caller-supplied id (useful for a test or a reproduce step); one is
        generated when this is not a usable string.

    Returns
    -------
    dict
        The record that was written, carrying its ``run_id``.
    """
    row = _row(result, execution=execution)
    summary, derived_final, derived_reached = _execution_facts(row["execution"])
    if final_position is None:
        final_position = derived_final
    if goal_reached is None:
        goal_reached = derived_reached

    return log_run(
        row["instruction"],
        row["backend"],
        row["actions"],
        row["attempts"],
        row["history"],
        latency=row["latency"],
        path=path,
        world=row["world"],
        mode=row["mode"],
        input_type=require_input_type(input_type),
        model=model,
        verification=row["verification"],
        execution=summary,
        final_position=final_position,
        goal_reached=goal_reached,
        run_id=run_id,
    )


def load(path: str = DEFAULT_PATH) -> list[dict]:
    """All records in the run log at *path*, oldest first.

    Returns ``[]`` when the file does not exist; a line that cannot be parsed is
    skipped, as the logger's own reader does.
    """
    return load_runs(path)


# ---------------------------------------------------------------------------
# Normalising what the caller passed
# ---------------------------------------------------------------------------

def _row(result: dict, *, execution: dict | None) -> dict:
    """The logger arguments for a ``RunResult`` or an ``ExecutionOutcome``."""
    if not isinstance(result, dict):
        raise ContractError(
            "record() takes a RunResult from planner.plan() or an "
            f"ExecutionOutcome from runtime.execute(), got {type(result).__name__}"
        )

    if "instruction" in result:
        return _run_row(result, execution=execution)

    approved = result.get("approved")
    if isinstance(approved, ApprovedPlan):
        return _outcome_row(result, approved, execution=execution)

    raise ContractError(
        "record() takes a RunResult from planner.plan() or an "
        "ExecutionOutcome from runtime.execute(); this dict is neither"
    )


def _run_row(result: dict, *, execution: dict | None) -> dict:
    """A planning run: its own facts, plus an execution when one was passed."""
    instruction = result.get("instruction")
    if not isinstance(instruction, str):
        raise ContractError(
            f"result instruction must be a string, got {type(instruction).__name__}"
        )
    approved = result.get("approved")
    carried = result.get("execution")
    if execution is None and isinstance(carried, dict):
        execution = carried

    return {
        "instruction": instruction,
        "backend": str(result.get("planner") or ""),
        "actions": approved.action_list() if isinstance(approved, ApprovedPlan) else None,
        "attempts": _count(result.get("attempts")),
        "history": result.get("history") if isinstance(result.get("history"), list) else [],
        "latency": result.get("latency") if isinstance(result.get("latency"), (int, float)) else None,
        "world": require_world(result.get("world")),
        "mode": result.get("mode"),
        "verification": result.get("verification") if isinstance(result.get("verification"), dict) else None,
        "execution": execution,
    }


def _outcome_row(outcome: dict, approved: ApprovedPlan, *, execution: dict | None) -> dict:
    """An execution outcome: the approval tells the record what ran."""
    return {
        "instruction": approved.instruction,
        "backend": approved.planner,
        "actions": approved.action_list(),
        "attempts": _count(outcome.get("attempts")),
        "history": [],
        "latency": None,
        "world": require_world(approved.world),
        "mode": resolve_mode(approved.planner),
        "verification": outcome.get("verification") if isinstance(outcome.get("verification"), dict) else None,
        "execution": execution if execution is not None else outcome,
    }


def _count(value: Any) -> int:
    """An attempt count for the record; a non-count is recorded as 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _execution_facts(
    execution: Any,
) -> tuple[dict | None, list[int] | None, bool | None]:
    """``(summary, final_position, goal_reached)`` from what the caller passed.

    An ``ExecutionOutcome`` is unwrapped to its ``execution``; an execution
    result is summarised into the log's ``{"ran", "halted", "steps"}``.  The
    position and goal are derived only when the simulation really stepped —
    a refused execution has no end position to record.
    """
    if execution is None:
        return None, None, None
    if not isinstance(execution, dict):
        raise ContractError(
            "execution= must be an ExecutionOutcome, an execution result or a "
            f"summary dict, got {type(execution).__name__}"
        )

    if isinstance(execution.get("execution"), dict):
        execution = execution["execution"]

    if "log" in execution or "verified" in execution:
        log = execution.get("log") if isinstance(execution.get("log"), list) else []
        halted = None
        for entry in log:
            message = str(entry.get("message") or "") if isinstance(entry, dict) else ""
            if message.startswith(("blocked", "unknown")):
                halted = message
                break
        world = execution.get("world")
        robot = world.get("robot") if isinstance(world, dict) else None
        final = list(robot) if isinstance(robot, list) and len(robot) == 2 else None
        reached = execution.get("reached") if isinstance(execution.get("reached"), bool) else None
        ran = bool(log)
        return (
            {"ran": ran, "halted": halted, "steps": len(log)},
            final if ran else None,
            reached if ran else None,
        )

    if any(key in execution for key in _SUMMARY_KEYS):
        return (
            {key: execution.get(key) for key in _SUMMARY_KEYS},
            None,
            None,
        )

    raise ContractError(
        "execution= is not an execution this API produced: expected an "
        "ExecutionOutcome, an execution result or a "
        '{"ran", "halted", "steps"} summary'
    )
