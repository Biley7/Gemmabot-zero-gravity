"""Engine layer for the GemmaBot frontend.

Owner: FRONTEND.  No Streamlit import here — this module is pure Python and
unit-testable.

This is the UI-facing adapter over the **GemmaBot Guard**
(``backend.guard``): it selects a planner backend, runs the guard's
propose/verify/repair pipeline, and offers the approval-gated execution path.
The guard owns the canonical representations, the parser and the safety
invariant; this layer only selects, calls and packages real results.

Responsibilities
----------------
- pick the AI backend for text planning  (``GeminiPlanner`` / ``OllamaPlanner`` / auto)
- pick the AI backend for map vision     (``ask_vision_api`` / ``ask_vision_ollama`` / auto)
- run the guard loop                     (``backend.guard.pipeline.plan``)
- seal a verified plan                   (``backend.guard.pipeline.approve``)
- execute an approved plan               (``execute_approved`` — re-verified)
- simulate/replay any plan               (``simulate`` — demonstrations only)
- check backend connectivity             (env var + ``ollama.list()``)
"""
from __future__ import annotations

import copy
import json
import time
from typing import Any, Callable

from backend.guard import pipeline as guard
from backend.guard.contracts import ApprovedPlan
from backend.guard.planner import (
    CallablePlanner,
    CallableVisionPlanner,
    build_planner,
    build_vision_planner,
)
from backend.logger.logger import redact_secrets
from gemmabot.config import has_api_key
from gemmabot.simulator import new_world


def _error_text(exc: BaseException) -> str:
    """A readable failure reason with any configured secret scrubbed out.

    An SDK error can embed the request, and therefore the key; the logger
    redacts before writing, and the UI must redact before displaying.
    """
    return redact_secrets(f"{type(exc).__name__}: {exc}")

AskFn = Callable[[str, dict], str]
VisionAskFn = Callable[[str, bytes, str], str]
AttemptFn = Callable[[dict], None]

# ── Dry mode: a scripted planner (same convention as benchmark --dry) ────────
# ``backend="dry"`` never touches a model.  The *replies* are scripted; the
# harness loop, the verifier, the collision and the execution that follow are
# the real pipeline.  The plans are calibrated to new_world() — the default
# world — and labelled as scripted everywhere they surface.
DRY_BACKEND = "dry"
DRY_HAZARD_PLAN: list[dict] = [{"cmd": "forward", "steps": 7}]
DRY_SAFE_PLAN: list[dict] = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]


def dry_ask(safe_on_attempt: int = 2) -> AskFn:
    """Scripted planner for dry mode: a naive plan, then the corrected route.

    Reply 1 walks straight into the wall column at x=3 of the default world so
    the repair loop has a real failure to repair; reply 2 is the verified route
    to the goal.  No model is involved — the UI says so.
    """
    state = {"calls": 0}
    threshold = max(1, int(safe_on_attempt))

    def _ask(instruction: str, world: dict) -> str:
        state["calls"] += 1
        plan = DRY_SAFE_PLAN if state["calls"] >= threshold else DRY_HAZARD_PLAN
        return json.dumps(
            {"thought": "scripted dry-mode planner", "actions": plan},
            ensure_ascii=False,
        )

    return _ask


# ── Dry mode: a scripted map reader (same convention as dry_ask) ────────────
# The *replies* are scripted; the JSON parser, ``check_world``, the retry loop
# and the world that reaches the simulator are the real pipeline.  The image is
# never sent to a model in dry mode, and every surface that shows a dry reading
# says it is scripted.
#
# The first reply is a *misread*: it shifts the goal one column off the grid, a
# real failure mode (the prompt warns about drifting coordinates), so the
# validator really rejects it and the loop really retries with the exact reason.
DRY_VISION_MISREAD: dict = {
    "robot": [0, 0],
    "dir": "E",
    "goal": [7, 8],          # off the 8×8 grid — check_world rejects this
    "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]],
}


def dry_vision_world() -> dict:
    """The world dry mode's corrected reading describes — the default world."""
    return new_world()


def dry_vision_ask(correct_on_attempt: int = 2) -> VisionAskFn:
    """Scripted vision reader for dry mode: a misread, then the corrected map.

    Reply 1 puts the goal outside the grid so ``map_vision.check_world`` really
    rejects it and ``read_map`` really retries with that failure reason in the
    prompt; reply 2 is the default world.  No model is involved and the image
    bytes are ignored — the UI labels this reader as scripted.
    """
    state = {"calls": 0}
    threshold = max(1, int(correct_on_attempt))

    def _ask(prompt: str, image_bytes: bytes, mime_type: str) -> str:
        state["calls"] += 1
        reading = (
            dry_vision_world() if state["calls"] >= threshold
            else dict(DRY_VISION_MISREAD)
        )
        return json.dumps(reading, ensure_ascii=False)

    return _ask


# ---------------------------------------------------------------------------
# Backend selection — text planning
# ---------------------------------------------------------------------------

def _normalise(backend_name: str) -> str:
    """Map UI/CLI backend names onto ``api`` / ``local`` / ``auto`` / ``dry``."""
    name = (backend_name or "auto").strip().lower()
    if name in ("api", "gemini", "google"):
        return "api"
    if name in ("local", "ollama", "gemma"):
        return "local"
    if name in ("auto", DRY_BACKEND):
        return name
    raise ValueError(
        f"unknown backend {backend_name!r}; expected one of "
        f"('api', 'local', 'auto', '{DRY_BACKEND}')"
    )


def _planner_functions() -> tuple[Callable, Callable]:
    """Import the real text planners lazily so imports stay optional."""
    try:
        from backend.planner.planner import ask_api, ask_ollama
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "Text planning is unavailable: backend.planner could not be "
            "imported (install google-genai and ollama). "
            f"Underlying error: {exc}"
        ) from exc
    return ask_api, ask_ollama


def _vision_functions() -> tuple[Callable, Callable]:
    """Import the vision callables lazily; map_vision is optional."""
    from backend.vision import map_vision

    return map_vision.ask_vision_api, map_vision.ask_vision_ollama


def _as_ask(planner: Any, requested: str) -> AskFn:
    """Wrap a Planner as the ``ask(instruction, world) -> str`` callable.

    ``auto`` also exposes the planner object as ``backend_state`` so the UI
    can report which backend actually answered (``FallbackPlanner.used``).
    """

    def _ask(instruction: str, world: dict) -> str:
        return planner.propose(instruction, world)

    if requested == "auto":
        _ask.backend_state = planner  # type: ignore[attr-defined]
    return _ask


def _make_auto_ask(api_fn: Callable | None, local_fn: Callable | None) -> AskFn:
    """Back-compat name for the auto planner selection (guard fallback policy)."""
    return get_ask("auto", api_fn=api_fn, local_fn=local_fn)


def ask_auto(
    instruction: str,
    world: dict,
    api_fn: Callable | None = None,
    local_fn: Callable | None = None,
) -> str:
    """Try the Gemini API first; fall back to local Ollama on any exception."""
    return get_ask("auto", api_fn=api_fn, local_fn=local_fn)(instruction, world)


def get_ask(
    backend_name: str,
    api_fn: Callable | None = None,
    local_fn: Callable | None = None,
) -> AskFn:
    """Return the text-planning callable for *backend_name*.

    ``api`` → Gemini, ``local`` → Ollama, ``auto`` → API first then Ollama.
    The fallback policy is one implementation
    (``backend.guard.planner.FallbackPlanner``); the optional ``api_fn`` /
    ``local_fn`` hooks exist for tests and never touch the network.
    """
    name = _normalise(backend_name)
    if name == DRY_BACKEND:
        return dry_ask()

    # An injected callable is returned as-is (its identity is the contract for
    # tests and embedders); real transports are wrapped as planners.
    if name == "api":
        return (
            api_fn
            if api_fn is not None
            else _as_ask(CallablePlanner("api", _planner_functions()[0]), name)
        )
    if name == "local":
        return (
            local_fn
            if local_fn is not None
            else _as_ask(CallablePlanner("ollama", _planner_functions()[1]), name)
        )

    if api_fn is None or local_fn is None:
        default_api, default_local = _planner_functions()
        api_fn = api_fn or default_api
        local_fn = local_fn or default_local
    return _as_ask(build_planner("auto", api_fn=api_fn, local_fn=local_fn), name)


def _used_backend_label(requested: str, ask_fn: Callable) -> str:
    """Report which backend actually produced replies (auto resolves itself)."""
    name = _normalise(requested)
    if name == "api":
        return "api"
    if name == "local":
        return "ollama"
    if name == DRY_BACKEND:
        return DRY_BACKEND
    state = getattr(ask_fn, "backend_state", None)
    if isinstance(state, dict):  # legacy/test shape
        return state.get("used") or "auto"
    return getattr(state, "used", None) or "auto"


# Display name per backend label.  ``local`` is the UI alias of ``ollama``
# (see ``_normalise``) and shares its label so the two never diverge.
BACKEND_DISPLAY = {
    "api": "API (Gemini)",
    "ollama": "Ollama (local)",
    "local": "Ollama (local)",
    "auto": "Auto (API → Ollama)",
    "dry": "Scripted (dry mode)",
}


def backend_label(backend: str) -> str:
    """Display name for a resolved backend label — ``'ollama'`` → ``'Ollama (local)'``.

    ``'local'`` is the UI alias of ``'ollama'`` and shares its label.  An
    unrecognised label is shown verbatim: this never guesses.
    """
    name = (backend or "").strip().lower()
    return BACKEND_DISPLAY.get(name, backend or "—")


# The two provenances a run can have.  ``live`` means a model produced the
# replies; ``synthetic`` means a scripted reader did.  Nothing in between: a
# benchmark that mixes them without saying so is measuring nothing.
MODE_LIVE = "live"
MODE_SYNTHETIC = "synthetic"

def backend_mode(backend_name: str) -> str:
    """``"live"`` or ``"synthetic"`` for the backend the caller is about to use.

    Only the scripted dry reader is synthetic; every other selection calls a real
    model endpoint.  Callers record this on the run so the benchmark never has to
    infer provenance from a run's numbers.
    """
    return MODE_SYNTHETIC if _normalise(backend_name) == DRY_BACKEND else MODE_LIVE


def backend_model(backend: str) -> str | None:
    """The model id ``gemmabot.config`` holds for *backend*, or ``None``.

    The ids are the real configuration values.  ``auto`` is only resolved once
    a reply has arrived, so an unresolved ``auto`` claims no model, and dry
    mode uses no model at all.
    """
    from gemmabot.config import GEMMA_API_MODEL, OLLAMA_MODEL

    name = (backend or "").strip().lower()
    if name == "api":
        return GEMMA_API_MODEL
    if name in ("ollama", "local"):
        return OLLAMA_MODEL
    return None


# ---------------------------------------------------------------------------
# Vision backend selection — deliberately separate from text planning
# ---------------------------------------------------------------------------

def _as_vision_ask(planner: Any, requested: str) -> VisionAskFn:
    """Wrap a vision planner as ``ask(prompt, image_bytes, mime) -> str``."""

    def _ask(prompt: str, image_bytes: bytes, mime_type: str) -> str:
        return planner.read(prompt, image_bytes, mime_type)

    if requested == "auto":
        _ask.backend_state = planner  # type: ignore[attr-defined]
    return _ask


def _make_auto_vision_ask(
    api_fn: VisionAskFn | None,
    local_fn: VisionAskFn | None,
) -> VisionAskFn:
    """Back-compat name for the auto vision planner selection."""
    return get_vision_ask("auto", api_fn=api_fn, local_fn=local_fn)


def get_vision_ask(
    backend_name: str,
    api_fn: VisionAskFn | None = None,
    local_fn: VisionAskFn | None = None,
) -> VisionAskFn:
    """Return the *multimodal* ask callable for ``map_vision.read_map()``.

    This is intentionally not ``get_ask``: passing a text planner into the map
    reader would send no image.  Like text planning, the fallback policy is
    the guard's single implementation.
    """
    name = _normalise(backend_name)
    if name == DRY_BACKEND:
        return dry_vision_ask()

    # Same identity contract as get_ask: an injected callable is returned as-is.
    if name == "api":
        return (
            api_fn
            if api_fn is not None
            else _as_vision_ask(
                CallableVisionPlanner("api", _vision_functions()[0]), name
            )
        )
    if name == "local":
        return (
            local_fn
            if local_fn is not None
            else _as_vision_ask(
                CallableVisionPlanner("ollama", _vision_functions()[1]), name
            )
        )

    if api_fn is None or local_fn is None:
        default_api, default_local = _vision_functions()
        api_fn = api_fn or default_api
        local_fn = local_fn or default_local
    return _as_vision_ask(
        build_vision_planner("auto", api_fn=api_fn, local_fn=local_fn), name
    )


# ---------------------------------------------------------------------------
# Planning (propose → verify → repair → approve) — delegated to the guard
# ---------------------------------------------------------------------------

def verify_run(
    world: dict,
    actions: list[dict] | None,
    history: list[dict] | None,
) -> dict | None:
    """Structured verification of the plan a run produced — or last attempted.

    The implementation is ``backend.guard.pipeline.verify_run`` (one
    canonical layer); this wrapper keeps the engine's public surface for
    existing callers and tests.
    """
    return guard.verify_run(world, actions, history)


def run_plan(
    instruction: str,
    world: dict,
    backend: str = "api",
    max_tries: int = 3,
    ask: Callable | None = None,
    on_attempt: AttemptFn | None = None,
) -> dict:
    """Run one instruction through the GemmaBot Guard.

    Proposes with the selected planner, verifies with the harness, repairs up
    to *max_tries* times, and seals a passing plan into an ``ApprovedPlan``.
    Never executes anything and never mutates *world* (everything runs on deep
    copies).

    Parameters
    ----------
    on_attempt:
        Optional callback invoked with each history record the moment the
        repair loop produces it, so a UI can stream the loop live.

    Returns
    -------
    dict
        ``{"actions", "attempts", "history", "latency", "backend", "error",
        "verification", "approved"}``.  *actions* is the verified plan or
        ``None``; *latency* is measured inside the guard with
        ``time.perf_counter()``; *verification* is the structured four-check
        report (or ``None`` when nothing was runnable); *approved* is the
        sealed ``ApprovedPlan`` the execution layer requires, or ``None``.
    """
    tries = max(1, int(max_tries))
    ask_fn = ask if ask is not None else get_ask(backend)
    planner = CallablePlanner(_normalise(backend), ask_fn)

    result = guard.plan(
        instruction, world, planner, max_tries=tries, on_attempt=on_attempt
    )
    result["backend"] = _used_backend_label(backend, ask_fn)
    return result


# ---------------------------------------------------------------------------
# Map vision (propose → verify → repair) — real image in, world out
# ---------------------------------------------------------------------------

def run_map_vision(
    image_bytes: bytes,
    mime_type: str,
    backend: str = "api",
    max_tries: int = 2,
    ask_vision: VisionAskFn | None = None,
) -> dict:
    """Run ``map_vision.read_map`` with the selected vision backend.

    Returns
    -------
    dict
        ``{"world", "history", "attempts", "max_tries", "latency", "backend",
        "error"}``.  *world* is the validated simulator world or ``None``;
        *error* is the final verification failure reason when rejected.
    """
    tries = max(1, int(max_tries))
    try:
        from backend import vision as map_vision
    except ImportError as exc:  # pragma: no cover - depends on environment
        return {
            "world": None,
            "history": [],
            "attempts": 0,
            "max_tries": tries,
            "latency": 0.0,
            "backend": backend,
            "error": f"map vision is unavailable: {exc}",
        }

    vision = ask_vision if ask_vision is not None else get_vision_ask(backend)
    error: str | None = None
    world: dict | None = None
    history: list[dict] = []

    start = time.perf_counter()
    try:
        world, history = map_vision.read_map(image_bytes, mime_type, vision, max_tries=tries)
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never fatal
        error = _error_text(exc)
    latency = time.perf_counter() - start

    if world is None and error is None:
        error = redact_secrets(
            str(history[-1].get("feedback")) if history
            else "vision produced no valid world"
        )

    return {
        "world": world,
        "history": history,
        "attempts": len(history),
        "max_tries": tries,
        "latency": latency,
        "backend": _used_backend_label(backend, vision),
        "error": error,
    }


# ---------------------------------------------------------------------------
# Execution gate
# ---------------------------------------------------------------------------

def verified_actions(result: dict[str, Any] | None) -> list[dict] | None:
    """UI-side pre-check: a result that *looks* executable — present + verified.

    This only answers "is there a plan worth approving?".  It is **not** the
    execution gate: the authoritative gate is ``approve()`` (which re-runs
    verification and seals the plan) plus ``execute_approved()`` (which
    re-verifies and checks the approval digest).
    """
    if not isinstance(result, dict):
        return None
    actions = result.get("actions")
    verification = result.get("verification")
    if not isinstance(actions, list) or not actions:
        return None
    if not isinstance(verification, dict) or verification.get("ok") is not True:
        return None
    return actions


# ---------------------------------------------------------------------------
# Approval + execution (execution requires an ApprovedPlan)
# ---------------------------------------------------------------------------

def approve(
    world: dict,
    actions: list[dict] | None,
    *,
    instruction: str = "",
    planner: str = "",
) -> ApprovedPlan | None:
    """Seal a verified plan — the only way to obtain an ``ApprovedPlan``.

    Delegates to ``backend.guard.pipeline.approve``, which re-verifies
    *actions* against *world* and returns ``None`` unless every check passes.
    The returned object carries the world snapshot, the canonical actions and
    a digest; execution re-checks all three, so a UI bug cannot mint an
    approval or force an unverified plan to run.
    """
    return guard.approve(world, actions, instruction=instruction, planner=planner)


def execute_approved(
    approved: ApprovedPlan,
    on_step: Callable[[dict, dict], None] | None = None,
) -> dict:
    """Execute an ``ApprovedPlan``; the guard re-verifies before stepping.

    Returns an ``ExecutionResult``.  A refused approval returns ``ok=False``
    with ``verified=False`` and an empty log — never a successful-looking
    result.  The caller's world is never mutated.
    """
    return guard.execute(approved, on_step=on_step)


def simulate(
    world: dict,
    actions: list[dict] | None,
    on_step: Callable[[dict, dict], None] | None = None,
) -> dict:
    """Deterministic simulation of any plan — demonstrations and replays.

    Marks the result ``verified=False``: this is **not** an approval gate.
    Use :func:`approve` + :func:`execute_approved` for approved execution.
    """
    return guard.simulate(world, actions, on_step=on_step)


def execute(
    world: dict,
    actions: list[dict],
    on_step: Callable[[dict, dict], None] | None = None,
) -> dict:
    """Compatibility alias of :func:`simulate` — simulation, not approval.

    Kept because the player and existing callers reach the simulator bridge by
    this name.  It performs no approval and no re-verification; approved
    execution is :func:`execute_approved`.
    """
    return simulate(world, actions, on_step=on_step)


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------

def check_connections(ollama_client: Any | None = None) -> dict:
    """Check API key presence and Ollama reachability.  Never exposes secrets.

    ``ollama_client`` is injectable for tests; by default the real
    ``ollama.list()`` is used when the package and server are available.
    """
    api_key_set = has_api_key()
    ollama_reachable = False
    ollama_models: list[str] = []

    try:
        client = ollama_client
        if client is None:
            import ollama as client  # noqa: PLC0415
        listing = client.list()
        models = (
            listing.get("models", [])
            if isinstance(listing, dict)
            else getattr(listing, "models", [])
        )
        for model in models or []:
            if isinstance(model, dict):
                name = model.get("model") or model.get("name")
            else:
                name = getattr(model, "model", None) or getattr(model, "name", None)
            if name:
                ollama_models.append(str(name))
        ollama_reachable = True
    except Exception:  # noqa: BLE001 - unreachable is the honest answer
        ollama_reachable = False

    return {
        "api_key_set": api_key_set,
        "ollama_reachable": ollama_reachable,
        "ollama_models": ollama_models,
    }


# ---------------------------------------------------------------------------
# Maps offered by the sidebar map picker
# ---------------------------------------------------------------------------

# Development/test convention from the project spec: a simple standardised
# 8x8 maze.  Pure data — not a model result and not a fake success.
SAMPLE_WORLD: dict = {
    "robot": [0, 0],
    "dir": "E",
    "goal": [7, 7],
    "walls": [
        [3, 1], [4, 1],
        [1, 2], [4, 2],
        [1, 3], [4, 3], [6, 3],
        [3, 4], [6, 4],
        [0, 5], [1, 5], [3, 5],
        [5, 6], [6, 6],
    ],
}


def sample_world() -> dict:
    """Fresh copy of the standardised test maze."""
    return copy.deepcopy(SAMPLE_WORLD)


def default_maps() -> dict[str, dict]:
    """Named worlds for the sidebar map picker (MapVision adds ``scanned``)."""
    return {"default": new_world(), "sample": sample_world()}
