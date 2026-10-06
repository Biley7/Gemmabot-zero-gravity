"""Engine layer for the GemmaBot frontend.

Owner: FRONTEND.  No Streamlit import here — this module is pure Python and
unit-testable.

Responsibilities
----------------
- pick the AI backend for text planning  (``ask_api`` / ``ask_ollama`` / auto)
- pick the AI backend for map vision     (``ask_vision_api`` / ``ask_vision_ollama`` / auto)
- run the verified planning loop         (``harness.plan_with_repair``)
- execute accepted actions safely        (``simulator.step`` on a deep copy)
- check backend connectivity             (env var + ``ollama.list()``)

The backend modules stay the source of truth: this layer only selects,
calls, times and packages their real results.
"""
from __future__ import annotations

import copy
import json
import os
import time
from typing import Any, Callable

from backend.verifier.harness import plan_with_repair, verify_plan
from gemmabot.simulator import new_world, reached_goal, step

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


def _make_auto_ask(api_fn: Callable | None, local_fn: Callable | None) -> AskFn:
    """Build a text ask that tries the API, then falls back to local Ollama."""
    if api_fn is None or local_fn is None:
        default_api, default_local = _planner_functions()
        api_fn = api_fn or default_api
        local_fn = local_fn or default_local

    state: dict[str, str | None] = {"used": None}

    def _ask(instruction: str, world: dict) -> str:
        try:
            reply = api_fn(instruction, world)
            state["used"] = "api"
            return reply
        except Exception:  # noqa: BLE001 - any API failure falls back
            reply = local_fn(instruction, world)
            state["used"] = "ollama"
            return reply

    _ask.backend_state = state  # type: ignore[attr-defined]
    return _ask


def ask_auto(
    instruction: str,
    world: dict,
    api_fn: Callable | None = None,
    local_fn: Callable | None = None,
) -> str:
    """Try the Gemini API first; fall back to local Ollama on any exception."""
    return _make_auto_ask(api_fn, local_fn)(instruction, world)


def get_ask(
    backend_name: str,
    api_fn: Callable | None = None,
    local_fn: Callable | None = None,
) -> AskFn:
    """Return the text-planning callable for *backend_name*.

    ``api`` → robot_sim-equivalent ``ask_api``, ``local`` → ``ask_ollama``,
    ``auto`` → API first then Ollama.  The optional ``api_fn`` / ``local_fn``
    hooks exist for tests and never touch the network.
    """
    name = _normalise(backend_name)
    if name == "api":
        return api_fn or _planner_functions()[0]
    if name == "local":
        return local_fn or _planner_functions()[1]
    if name == DRY_BACKEND:
        return dry_ask()
    return _make_auto_ask(api_fn, local_fn)


def _used_backend_label(requested: str, ask_fn: Callable) -> str:
    """Report which backend actually produced replies (auto resolves itself)."""
    name = _normalise(requested)
    if name == "api":
        return "api"
    if name == "local":
        return "ollama"
    if name == DRY_BACKEND:
        return DRY_BACKEND
    state = getattr(ask_fn, "backend_state", None) or {}
    return state.get("used") or "auto"


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

def _make_auto_vision_ask(
    api_fn: VisionAskFn | None,
    local_fn: VisionAskFn | None,
) -> VisionAskFn:
    if api_fn is None or local_fn is None:
        default_api, default_local = _vision_functions()
        api_fn = api_fn or default_api
        local_fn = local_fn or default_local

    state: dict[str, str | None] = {"used": None}

    def _ask(prompt: str, image_bytes: bytes, mime_type: str) -> str:
        try:
            reply = api_fn(prompt, image_bytes, mime_type)
            state["used"] = "api"
            return reply
        except Exception:  # noqa: BLE001 - any API failure falls back
            reply = local_fn(prompt, image_bytes, mime_type)
            state["used"] = "ollama"
            return reply

    _ask.backend_state = state  # type: ignore[attr-defined]
    return _ask


def get_vision_ask(
    backend_name: str,
    api_fn: VisionAskFn | None = None,
    local_fn: VisionAskFn | None = None,
) -> VisionAskFn:
    """Return the *multimodal* ask callable for ``map_vision.read_map()``.

    This is intentionally not ``get_ask``: passing a text planner into the map
    reader would send no image.
    """
    name = _normalise(backend_name)
    if name == "api":
        return api_fn or _vision_functions()[0]
    if name == "local":
        return local_fn or _vision_functions()[1]
    if name == DRY_BACKEND:
        return dry_vision_ask()
    return _make_auto_vision_ask(api_fn, local_fn)


# ---------------------------------------------------------------------------
# Planning (propose → verify → repair)
# ---------------------------------------------------------------------------

def _last_attempted_actions(history: list[dict]) -> list[dict] | None:
    """The most recent parsed action list in a run's history, if there is one."""
    for record in reversed(history or []):
        candidate = record.get("actions")
        if isinstance(candidate, list) and candidate:
            return candidate
    return None


def verify_run(
    world: dict,
    actions: list[dict] | None,
    history: list[dict] | None,
) -> dict | None:
    """Structured verification of the plan a run produced — or last attempted.

    Uses the accepted plan when there is one, otherwise the newest attempt that
    got as far as a parsed action list.  Returns ``harness.verify_plan``'s
    result extended with the ``actions`` it verified, or ``None`` when no
    attempt produced anything runnable (an ask or parse failure) — in which
    case there is nothing real to verify.
    """
    target = actions if isinstance(actions, list) and actions else None
    if target is None:
        target = _last_attempted_actions(history or [])
    if not target:
        return None

    outcome = dict(verify_plan(world, target))
    outcome["actions"] = target
    return outcome


def run_plan(
    instruction: str,
    world: dict,
    backend: str = "api",
    max_tries: int = 3,
    ask: Callable | None = None,
    on_attempt: AttemptFn | None = None,
) -> dict:
    """Run one instruction through ``harness.plan_with_repair``.

    Never executes anything and never mutates *world*: the world is deep-copied
    before it is handed to the harness, which itself only simulates copies.

    Parameters
    ----------
    on_attempt:
        Optional callback invoked with each history record the moment the
        repair loop produces it, so a UI can stream the loop live.

    Returns
    -------
    dict
        ``{"actions", "attempts", "history", "latency", "backend", "error",
        "verification"}``.  *actions* is the verified plan or ``None``;
        *latency* is measured with ``time.perf_counter()``; *error* is the
        readable failure reason; *verification* is ``verify_run()``'s
        structured four-check report (or ``None`` when nothing was runnable).
    """
    tries = max(1, int(max_tries))
    ask_fn = ask if ask is not None else get_ask(backend)
    error: str | None = None
    actions: list[dict] | None = None
    attempts = 0
    history: list[dict] = []

    start = time.perf_counter()
    try:
        actions, attempts, history = plan_with_repair(
            instruction,
            copy.deepcopy(world),
            ask_fn,
            max_tries=tries,
            on_attempt=on_attempt,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never fatal
        error = f"{type(exc).__name__}: {exc}"
    latency = time.perf_counter() - start

    if actions is None and error is None:
        error = history[-1].get("feedback") if history else "planning produced no valid plan"

    return {
        "actions": actions,
        "attempts": attempts,
        "history": history,
        "latency": latency,
        "backend": _used_backend_label(backend, ask_fn),
        "error": error,
        "verification": verify_run(world, actions, history),
    }


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
        error = f"{type(exc).__name__}: {exc}"
    latency = time.perf_counter() - start

    if world is None and error is None:
        error = history[-1].get("feedback") if history else "vision produced no valid world"

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
# Execution (only ever called with a verified plan)
# ---------------------------------------------------------------------------

def execute(
    world: dict,
    actions: list[dict],
    on_step: Callable[[dict, dict], None] | None = None,
) -> dict:
    """Execute validated *actions* on a deep copy of *world*.

    The caller's world is never mutated; the returned dict carries the new
    world so the UI decides when to adopt it.  Stops early if the simulator
    blocks an action (returns ``ok=False``).

    Parameters
    ----------
    on_step:
        Optional callback ``on_step(entry, sim_world)`` invoked after every
        step so a UI can render the world between actions.
    """
    sim = copy.deepcopy(world)
    log: list[dict] = []
    ok = True

    for index, action in enumerate(actions or [], start=1):
        message = step(sim, action)
        entry = {"step": index, "action": action, "message": message}
        log.append(entry)
        if on_step is not None:
            on_step(entry, sim)
        if message.startswith("blocked") or message.startswith("unknown"):
            ok = False
            break

    return {"world": sim, "log": log, "ok": ok, "reached": reached_goal(sim)}


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------

def check_connections(ollama_client: Any | None = None) -> dict:
    """Check API key presence and Ollama reachability.  Never exposes secrets.

    ``ollama_client`` is injectable for tests; by default the real
    ``ollama.list()`` is used when the package and server are available.
    """
    api_key_set = bool(os.getenv("GEMINI_API_KEY", "").strip())
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
