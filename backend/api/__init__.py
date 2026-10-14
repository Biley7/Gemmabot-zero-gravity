"""GemmaBot's programmatic API — the platform without the console.

    from backend.api import guard, planner, repair, runs, runtime

    result = planner.plan("go to the goal", world, planner=my_planner)
    if result["approved"] is not None:
        outcome = runtime.execute(result)          # approved plans only
        runs.record(result, execution=outcome)

One namespace per public contract, each returned as a plain mapping:

    planner.plan(...)     instruction (+ world) → RunResult     propose·verify·repair
    guard.verify(...)     world + actions       → VerificationResult
    guard.approve(...)    world + actions       → ApprovedPlan | None
    guard.simulate(...)   world + actions       → ExecutionResult   (never approved)
    repair.replan(...)    refused RunResult     → RunResult         one more attempt
    runtime.execute(...)  approved plan         → ExecutionOutcome
    runs.record(...)      result                → the logged record (with run_id)

The three rules this layer exists to keep:

* **Execution requires an approval.** ``runtime.execute`` steps the simulator
  only for a digest-sealed ``ApprovedPlan``, and re-verifies it before stepping;
  everything else is refused.  ``guard.simulate`` is the deliberate way to
  demonstrate an unapproved plan, and its results can never execute.
* **A refusal is a result, not an exception.** A plan the verifier rejects comes
  back with ``approved: None`` and the verifier's own ``reason``; exceptions are
  reserved for a malformed request or an attempted unapproved execution.
* **Missing is ``None``, never a guess.** An unknown fact is unrecorded, not
  filled in with a plausible default.

The API imports no Streamlit and no vendor SDK: a caller needs Python and the
world, nothing else.  Versioned by ``contracts.API_VERSION``; the shapes are
defined in :mod:`backend.api.contracts` and described in ``docs/API.md``.
"""
from backend.api import guard, planner, repair, runs, runtime
from backend.api.contracts import (
    API_VERSION,
    ApiError,
    ApprovedPlan,
    ContractError,
    ExecutionOutcome,
    NotApprovedError,
    PlanRequest,
    RepairRequest,
    RunResult,
)

__all__ = [
    "API_VERSION",
    "ApiError",
    "ApprovedPlan",
    "ContractError",
    "ExecutionOutcome",
    "NotApprovedError",
    "PlanRequest",
    "RepairRequest",
    "RunResult",
    "guard",
    "planner",
    "repair",
    "runs",
    "runtime",
]
