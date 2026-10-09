"""GemmaBot Guard — the verification core of the platform.

    AI MODEL → Planner → Guard (validate · simulate · repair) → Approved Plan
                                                                    │
                                            Simulator  ◄────────────┤
                                            Robot/ROS  (not yet) ───┘

One pipeline, one set of representations:

* ``backend.guard.contracts``  canonical World / Action / Plan /
  VerificationResult / ExecutionResult / ApprovedPlan
* ``backend.guard.planner``    model-agnostic Planner interface + adapters,
  fallback policy and a registry
* ``backend.parsing``          one model-reply parser for plans and worlds
* ``backend.guard.pipeline``   ``plan()`` → ``approve()`` → ``execute()``;
  ``simulate()`` for demonstrations

The invariant: execution requires an ``ApprovedPlan``, and ``execute()``
re-verifies it and checks its digest before the simulator steps.  The UI can
request, display and replay, but it cannot approve or force execution.
"""
from backend.guard.contracts import (
    Action,
    ApprovedPlan,
    ExecutionResult,
    Plan,
    VerificationCheck,
    VerificationResult,
    World,
    approval_digest,
    canonical_actions,
    canonical_world,
)
from backend.guard.pipeline import (
    approve,
    execute,
    last_attempted_actions,
    plan,
    simulate,
    verify,
    verify_run,
)
from backend.guard.planner import (
    CallablePlanner,
    CallableVisionPlanner,
    FallbackPlanner,
    GeminiPlanner,
    GeminiVisionPlanner,
    OllamaPlanner,
    OllamaVisionPlanner,
    Planner,
    VisionPlanner,
    build_planner,
    build_vision_planner,
    register_planner,
    register_vision_planner,
)

__all__ = [
    "Action",
    "ApprovedPlan",
    "CallablePlanner",
    "CallableVisionPlanner",
    "ExecutionResult",
    "FallbackPlanner",
    "GeminiPlanner",
    "GeminiVisionPlanner",
    "OllamaPlanner",
    "OllamaVisionPlanner",
    "Plan",
    "Planner",
    "VerificationCheck",
    "VerificationResult",
    "VisionPlanner",
    "World",
    "approval_digest",
    "approve",
    "build_planner",
    "build_vision_planner",
    "canonical_actions",
    "canonical_world",
    "execute",
    "last_attempted_actions",
    "plan",
    "register_planner",
    "register_vision_planner",
    "simulate",
    "verify",
    "verify_run",
]
