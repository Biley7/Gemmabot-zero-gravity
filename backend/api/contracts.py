"""The GemmaBot API contracts — the stable shapes a programmatic caller relies on.

Owner: BACKEND.  Nothing here imports Streamlit, the frontend or a vendor SDK:
the API is the platform's other door, and a caller must not have to know that a
console exists.

    planner.plan(...)     instruction → RunResult     (propose · verify · repair)
    guard.verify(...)     world + actions → VerificationResult
    guard.approve(...)    world + actions → ApprovedPlan | None
    guard.simulate(...)   world + actions → ExecutionResult (verified=False)
    repair.replan(...)    RunResult → RunResult        (one more attempt)
    runtime.execute(...)  ApprovedPlan → ExecutionOutcome
    runs.record(...)      result → the logged run record (with its run_id)

Three rules, and they are the whole point of this layer:

1. **Execution requires an approval.** ``runtime.execute`` accepts only the sealed
   ``ApprovedPlan`` the guard produced, or the ``RunResult`` carrying one.  A plan
   dict, a world, a refused result, a demonstration or a hand-rolled mapping all
   raise :class:`NotApprovedError` — and a hand-built approval whose digest does
   not match is refused by the guard before a step runs.  ``guard.simulate`` is
   the deliberate alternative: it demonstrates any plan and always reports
   ``verified: False``.
2. **A refusal is a result, not an exception.** When the guard refuses a plan the
   caller gets ``approved: None`` and the verifier's own ``reason``.  Exceptions
   are reserved for a malformed request (:class:`ContractError`) or an attempt to
   execute something that was never approved (:class:`NotApprovedError`).
3. **Missing is ``None``, never a guess.** ``mode`` is ``"live"`` when a model
   answered, ``"synthetic"`` when a scripted planner did, and ``None`` when the
   caller did not say — it is never inferred from the numbers.

Versioning: every result carries ``api_version``.  Within a major version the
keys documented here do not disappear and do not change meaning; adding a key is
not a breaking change.
"""
from __future__ import annotations

import copy
from typing import Any, NotRequired, TypedDict

from backend.guard.contracts import (
    Action,
    ApprovedPlan,
    ExecutionResult,
    VerificationResult,
    World,
    canonical_actions,
    canonical_world,
)

# The version of the shapes in this module.  Bumped on a breaking change.
API_VERSION = "1.0"

MODE_LIVE = "live"
MODE_SYNTHETIC = "synthetic"

# A planner whose name says it is scripted never called a model.  This is the
# same convention the benchmark and the run log use, kept here so the API
# reports provenance the same way the rest of the platform does.
_SCRIPTED_MARKERS: tuple[str, ...] = ("dry", "scripted", "fake")

# The input kinds the run log knows (``backend.logger.log_run``).  An API run is
# a text instruction unless the caller says otherwise; a value outside these
# three is refused by ``require_input_type`` rather than stored as a guess.
INPUT_TYPES: tuple[str, ...] = ("text", "vision", "benchmark")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ApiError(Exception):
    """Base class for every error this API raises."""


class ContractError(ApiError, ValueError):
    """The request is not well formed — a bad world, action list or argument.

    Raised before anything runs, so a caller learns about a typo from the
    contract rather than from a puzzling result.
    """


class NotApprovedError(ApiError):
    """Execution was requested for something that is not an approved plan.

    Carries ``got`` — what the caller actually passed — and an optional
    ``detail`` so the message can say what was wrong instead of only that it
    was.
    """

    def __init__(self, got: Any, *, detail: str | None = None):
        self.got = got
        self.detail = detail
        super().__init__(
            "runtime.execute() requires an approved plan produced by "
            "guard.approve() or planner.plan(); got "
            f"{detail or type(got).__name__}. Nothing was executed. Use "
            "guard.simulate() to demonstrate an unapproved plan."
        )


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class PlanRequest(TypedDict):
    """What ``planner.plan`` accepts.  Only ``instruction`` and ``world`` are
    required in practice; every other key has a documented default."""

    instruction: str
    world: World
    backend: NotRequired[str]        # unset = the "auto" policy | "api" | "local" | registered
    max_tries: NotRequired[int]      # repair attempts, default 3, at least 1
    plan: NotRequired[list[Action]]  # a plan you already have; no model is called
    mode: NotRequired[str]           # "live" | "synthetic"; None means unrecorded
    planner: NotRequired[Any]        # a Planner object or ask(instruction, world)
    on_attempt: NotRequired[Any]     # called with each attempt record, live


class RepairRequest(TypedDict):
    """What ``repair.replan`` accepts: a result the guard did not approve."""

    result: dict
    backend: NotRequired[str]
    planner: NotRequired[Any]
    tries: NotRequired[int]          # repair attempts, default 1
    on_attempt: NotRequired[Any]


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

class RunResult(TypedDict):
    """The result of ``planner.plan`` and ``repair.replan``.

    ``approved`` is the only value in the API that is not a plain dict: it is a
    capability, not data.  Keep it if you intend to execute the plan; a refusal
    is ``None`` and ``reason`` says why.
    """

    api_version: str
    instruction: str
    world: World                     # the canonical world the run was about
    planner: str                     # which planner answered ("scripted", "api", …)
    mode: str | None                 # live | synthetic | None (not recorded)
    approved: ApprovedPlan | None    # only ever produced by the guard
    reason: str                      # why it was approved, or why it was not
    actions: list[Action] | None     # the verified plan, or None
    attempts: int                    # attempts this call made
    repaired: bool                   # the plan came from repair, not a first try
    verification: VerificationResult | None
    simulation: ExecutionResult | None  # None: planning does not simulate
    execution: ExecutionResult | None   # None: planning never executes
    latency: float
    history: list[dict]              # one record per attempt (no prompt/reply)
    run_id: str | None               # set by runs.record
    error: str | None                # a readable error, or None


class ExecutionOutcome(TypedDict):
    """The result of ``runtime.execute`` — an approved plan that stepped.

    ``attempts`` is carried over when the caller passed the ``RunResult`` that
    produced the plan, and ``None`` when they passed an ``ApprovedPlan``
    directly — the planning loop's attempt count only exists on the result.
    ``simulation`` is ``None`` because this is an execution: read ``execution``,
    whose ``verified`` is ``True`` only for an approved plan that stepped.
    ``verification`` is the verdict the runtime recomputed for the sealed plan
    immediately before stepping — the same check execution itself ran.
    """

    api_version: str
    approved: ApprovedPlan
    reason: str
    actions: list[Action]
    attempts: int | None
    verification: VerificationResult
    simulation: ExecutionResult | None
    execution: ExecutionResult


# ---------------------------------------------------------------------------
# Request validation — one place, so every entry point refuses the same way
# ---------------------------------------------------------------------------

def require_instruction(value: Any) -> str:
    """A non-empty instruction string, or :class:`ContractError`."""
    if not isinstance(value, str) or not value.strip():
        raise ContractError(
            f"instruction must be a non-empty string, got {type(value).__name__}"
        )
    return value


def require_world(value: Any) -> World:
    """A canonical world, or :class:`ContractError` (never a partial world)."""
    try:
        return canonical_world(value)
    except ValueError as exc:
        raise ContractError(f"world is not a valid world: {exc}") from exc


def require_plan(value: Any) -> list[Action]:
    """A canonical action list with at least one action, or :class:`ContractError`."""
    try:
        return canonical_actions(value)
    except ValueError as exc:
        raise ContractError(f"plan is not a valid plan: {exc}") from exc


def require_actions(value: Any, *, allow_empty: bool = False) -> list[Action]:
    """A canonical action list, or :class:`ContractError`.

    ``allow_empty=True`` accepts ``[]`` — meaningful when the request is to
    *demonstrate* a plan (simulate a world standing still), never when it is to
    verify or approve one.
    """
    try:
        return canonical_actions(value, allow_empty=allow_empty)
    except ValueError as exc:
        raise ContractError(f"actions are not a valid action list: {exc}") from exc


def require_max_tries(value: Any, *, key: str = "max_tries") -> int:
    """An attempt count of at least 1, or :class:`ContractError`.

    A bound is not a preference: silently clamping 0 to 1 would run an attempt
    the caller did not ask for.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{key} must be an integer of at least 1, got {value!r}")
    return value


def require_mode(value: Any = None) -> str | None:
    """A declared provenance — ``"live"``, ``"synthetic"`` or ``None``.

    Validated before anything runs, so a typo is answered by the contract and
    not after a model was already asked.
    """
    if value is None or value in (MODE_LIVE, MODE_SYNTHETIC):
        return value
    raise ContractError(
        f"mode must be {MODE_LIVE!r}, {MODE_SYNTHETIC!r} or None, got {value!r}"
    )


def require_input_type(value: Any = None) -> str | None:
    """One of the run log's input kinds, or ``None`` (recorded as unrecorded).

    A word outside the three kinds is a :class:`ContractError` rather than a
    silent ``None``: the run log stores what it is given, so a caller who meant
    ``"text"`` learns about the typo here and not from a record that has no
    input type.
    """
    if value is None or value == "":
        return None
    name = str(value).strip().lower()
    if name not in INPUT_TYPES:
        raise ContractError(
            f"input_type must be one of {', '.join(INPUT_TYPES)} or None, "
            f"got {value!r}"
        )
    return name


def resolve_mode(planner_name: Any, declared: Any = None) -> str | None:
    """``"live"``, ``"synthetic"`` or ``None`` for the planner that answered.

    A stated mode is believed — only the caller knows.  Otherwise a planner
    whose name says it is scripted is synthetic, a built-in model planner is
    live, and anything else (a caller's own planner, an unknown name) is
    ``None``: unrecorded, never guessed.
    """
    if declared in (MODE_LIVE, MODE_SYNTHETIC):
        return declared
    if declared is not None:
        raise ContractError(
            f"mode must be {MODE_LIVE!r}, {MODE_SYNTHETIC!r} or None, got {declared!r}"
        )
    name = str(planner_name or "").strip().lower()
    if any(marker in name for marker in _SCRIPTED_MARKERS):
        return MODE_SYNTHETIC
    if name in ("api", "ollama", "local", "auto", "gemini"):
        return MODE_LIVE
    return None


def was_repaired(history: Any) -> bool:
    """True when a refused attempt was followed by an approved one.

    That is what makes a plan "repaired": the loop refused an attempt and a
    later attempt passed verification.  One attempt that passed first is not a
    repair, however the run was asked for.
    """
    records = [r for r in (history or []) if isinstance(r, dict)]
    return len(records) > 1 and any(r.get("ok") is True for r in records[1:])


def approval_reason(approved: ApprovedPlan | None, verification: dict | None,
                   error: str | None, attempts: int) -> str:
    """One honest sentence saying what happened, from the run's own facts.

    Nothing here is composed from a model's reply: an approval or a refusal is
    the verifier's verdict, and an error is the redacted error the loop caught.
    """
    if approved is not None:
        count = len(approved.action_list())
        return (
            f"the guard approved {count} action(s) after "
            f"{attempts} attempt(s); the plan is sealed for execution"
        )
    if error:
        return f"no plan was approved: {error}"
    reason = ""
    if isinstance(verification, dict):
        reason = str(verification.get("reason") or "")
    return (
        f"the verifier refused every attempt ({reason})" if reason
        else "the verifier refused every attempt"
    )


def run_result(
    *,
    instruction: str,
    world: World,
    planner: str,
    mode: str | None,
    approved: ApprovedPlan | None,
    actions: list[Action] | None,
    attempts: int,
    verification: VerificationResult | None,
    latency: float,
    history: list[dict],
    repaired: bool = False,
    error: str | None = None,
    simulation: ExecutionResult | None = None,
    execution: ExecutionResult | None = None,
    run_id: str | None = None,
) -> RunResult:
    """Assemble a :class:`RunResult` — every key, always present, in one place.

    A caller can therefore read any documented key without a ``.get`` and a
    default: an absent fact is ``None`` here, never a missing key.  The prompt
    and reply of each attempt are dropped from ``history`` as it is copied in,
    so a result can be logged, printed or sent on without carrying a model
    transcript (and without the secret a reply might embed).
    """
    return {
        "api_version": API_VERSION,
        "instruction": instruction,
        "world": copy.deepcopy(world),
        "planner": planner,
        "mode": mode,
        "approved": approved,
        "reason": approval_reason(approved, verification, error, attempts),
        "actions": copy.deepcopy(actions) if isinstance(actions, list) else None,
        "attempts": int(attempts),
        "repaired": bool(repaired),
        "verification": copy.deepcopy(verification),
        "simulation": simulation,
        "execution": execution,
        "latency": float(latency),
        "history": attempt_history(history),
        "run_id": run_id,
        "error": error,
    }


def attempt_history(history: Any) -> list[dict]:
    """The attempt records without their prompt and reply.

    A caller needs to know that attempt 1 was refused for a collision, not what
    the model was asked or what it wrote back.  Keeping transcripts out of the
    public result is what lets a result be logged or shared safely.
    """
    out: list[dict] = []
    for record in history or []:
        if not isinstance(record, dict):
            continue
        kept = {
            "attempt": int(record.get("attempt") or len(out) + 1),
            "ok": record.get("ok") if isinstance(record.get("ok"), bool) else None,
            "feedback": str(record.get("feedback") or ""),
            "actions": copy.deepcopy(record["actions"])
            if isinstance(record.get("actions"), list) else None,
        }
        out.append(kept)
    return out


def execution_reason(result: dict) -> str:
    """One honest sentence about an execution result, refusal included.

    A refused execution and a halted one are different statements, and each is
    composed from the result's own log: nothing here invents a success.
    """
    log = result.get("log") or []
    steps = len(log)
    if result.get("verified") is True:
        if result.get("ok") is True:
            ended = (
                "reached the goal" if result.get("reached")
                else "did not reach the goal"
            )
            return f"the approved plan executed {steps} action(s) and {ended}"
        halted = next(
            (
                str(entry.get("message") or "")
                for entry in log
                if str(entry.get("message") or "").startswith(("blocked", "unknown"))
            ),
            "",
        )
        return (
            f"the approved plan executed {steps} action(s) and halted: "
            f"{halted or 'the simulator refused a step'}"
        )
    refused = str(result.get("refused") or "").strip()
    if refused:
        return f"the guard refused the approved plan: {refused}"
    return "the approved plan did not execute"
