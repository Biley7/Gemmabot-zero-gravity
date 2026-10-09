"""Model-agnostic planner interface — Gemma is one implementation, not the assumption.

Owner: BACKEND.

The guard talks to a ``Planner`` object, never to a vendor SDK.  The shipped
implementations are adapters over the existing transports:

    GeminiPlanner / GeminiVisionPlanner      Google Gemini (google-genai)
    OllamaPlanner / OllamaVisionPlanner      local Ollama
    FallbackPlanner                          try primary, fall back on any exception
    CallablePlanner                          any ask(instruction, world) -> str (tests, tools)

``build_planner(name, ...)`` / ``build_vision_planner(name, ...)`` resolve
``api``, ``local`` and ``auto``; ``register_planner`` lets a deployment add its
own backend without touching the guard or the UI.

Transport imports are lazy inside ``propose``/``read`` so importing this module
never requires google-genai or ollama to be installed.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

AskFn = Callable[[str, dict], str]
VisionAskFn = Callable[[str, bytes, str], str]


@runtime_checkable
class Planner(Protocol):
    """A text planner: propose a reply for an instruction + world."""

    name: str

    def propose(self, instruction: str, world: dict) -> str:  # pragma: no cover
        ...


@runtime_checkable
class VisionPlanner(Protocol):
    """A vision planner: read an image + prompt into a raw reply."""

    name: str

    def read(self, prompt: str, image_bytes: bytes, mime_type: str) -> str:  # pragma: no cover
        ...


class CallablePlanner:
    """Adapt any ``ask(instruction, world) -> str`` callable into a Planner."""

    def __init__(self, name: str, ask: AskFn):
        self.name = name
        self._ask = ask

    def propose(self, instruction: str, world: dict) -> str:
        return self._ask(instruction, world)


class CallableVisionPlanner:
    """Adapt any ``ask(prompt, image_bytes, mime_type) -> str`` callable."""

    def __init__(self, name: str, ask: VisionAskFn):
        self.name = name
        self._ask = ask

    def read(self, prompt: str, image_bytes: bytes, mime_type: str) -> str:
        return self._ask(prompt, image_bytes, mime_type)


class GeminiPlanner:
    """Google Gemini text planner (the google-genai transport)."""

    name = "api"

    def __init__(self, model: str | None = None):
        self._model = model

    def propose(self, instruction: str, world: dict) -> str:
        from backend.planner.planner import ask_api  # noqa: PLC0415

        return ask_api(instruction, world, model=self._model)


class OllamaPlanner:
    """Local Ollama text planner."""

    name = "ollama"

    def __init__(self, model: str | None = None):
        self._model = model

    def propose(self, instruction: str, world: dict) -> str:
        from backend.planner.planner import ask_ollama  # noqa: PLC0415

        return ask_ollama(instruction, world, model=self._model)


class GeminiVisionPlanner:
    """Google Gemini multimodal planner."""

    name = "api"

    def __init__(self, model: str | None = None):
        self._model = model

    def read(self, prompt: str, image_bytes: bytes, mime_type: str) -> str:
        from backend.vision import map_vision  # noqa: PLC0415

        return map_vision.ask_vision_api(prompt, image_bytes, mime_type, model=self._model)


class OllamaVisionPlanner:
    """Local Ollama multimodal planner."""

    name = "ollama"

    def __init__(self, model: str | None = None):
        self._model = model

    def read(self, prompt: str, image_bytes: bytes, mime_type: str) -> str:
        from backend.vision import map_vision  # noqa: PLC0415

        return map_vision.ask_vision_ollama(prompt, image_bytes, mime_type, model=self._model)


class FallbackPlanner:
    """Try the primary planner, then the fallback on any exception.

    Implements both ``propose`` and ``read`` so one fallback policy serves text
    planning and map vision.  ``used`` records which planner actually answered
    (``None`` until one does) — the UI and the run log read it instead of
    guessing.
    """

    def __init__(self, primary: Any, fallback: Any):
        self.primary = primary
        self.fallback = fallback
        self.used: str | None = None

    @property
    def name(self) -> str:
        return "auto"

    def _try(self, method: str, args: tuple) -> str:
        try:
            reply = getattr(self.primary, method)(*args)
            self.used = getattr(self.primary, "name", None)
            return reply
        except Exception:  # noqa: BLE001 - any primary failure falls back
            reply = getattr(self.fallback, method)(*args)
            self.used = getattr(self.fallback, "name", None)
            return reply

    def propose(self, instruction: str, world: dict) -> str:
        return self._try("propose", (instruction, world))

    def read(self, prompt: str, image_bytes: bytes, mime_type: str) -> str:
        return self._try("read", (prompt, image_bytes, mime_type))


# ── Registry ────────────────────────────────────────────────────────────────
# A deployment can add a planner without touching the guard or the UI:
#     register_planner("my-model", lambda: CallablePlanner("my-model", my_ask))

PlannerFactory = Callable[[], Any]
_PLANNER_FACTORIES: dict[str, PlannerFactory] = {}
_VISION_FACTORIES: dict[str, PlannerFactory] = {}


def register_planner(name: str, factory: PlannerFactory) -> None:
    """Register a text planner factory under *name*."""
    _PLANNER_FACTORIES[name] = factory


def register_vision_planner(name: str, factory: PlannerFactory) -> None:
    """Register a vision planner factory under *name*."""
    _VISION_FACTORIES[name] = factory


def build_planner(
    name: str,
    *,
    api_fn: AskFn | None = None,
    local_fn: AskFn | None = None,
) -> Any:
    """Resolve a text planner for ``api`` / ``local`` / ``auto``.

    ``api_fn`` / ``local_fn`` let a caller (or test) substitute transports;
    without them the real adapters are used.
    """
    key = (name or "auto").strip().lower()
    if key == "api":
        return CallablePlanner("api", api_fn) if api_fn else _factory(_PLANNER_FACTORIES, key)()
    if key == "local":
        return (
            CallablePlanner("ollama", local_fn)
            if local_fn
            else _factory(_PLANNER_FACTORIES, key)()
        )
    if key == "auto":
        return FallbackPlanner(
            CallablePlanner("api", api_fn) if api_fn else _factory(_PLANNER_FACTORIES, "api")(),
            CallablePlanner("ollama", local_fn)
            if local_fn
            else _factory(_PLANNER_FACTORIES, "local")(),
        )
    return _factory(_PLANNER_FACTORIES, key)()


def build_vision_planner(
    name: str,
    *,
    api_fn: VisionAskFn | None = None,
    local_fn: VisionAskFn | None = None,
) -> Any:
    """Resolve a vision planner for ``api`` / ``local`` / ``auto``."""
    key = (name or "auto").strip().lower()
    if key == "api":
        return (
            CallableVisionPlanner("api", api_fn)
            if api_fn
            else _factory(_VISION_FACTORIES, key)()
        )
    if key == "local":
        return (
            CallableVisionPlanner("ollama", local_fn)
            if local_fn
            else _factory(_VISION_FACTORIES, key)()
        )
    if key == "auto":
        return FallbackPlanner(
            CallableVisionPlanner("api", api_fn)
            if api_fn
            else _factory(_VISION_FACTORIES, "api")(),
            CallableVisionPlanner("ollama", local_fn)
            if local_fn
            else _factory(_VISION_FACTORIES, "local")(),
        )
    return _factory(_VISION_FACTORIES, key)()


def _factory(registry: dict[str, PlannerFactory], key: str) -> PlannerFactory:
    factory = registry.get(key)
    if factory is None:
        known = ", ".join(sorted(registry)) or "none"
        raise ValueError(f"unknown planner {key!r}; registered: {known}")
    return factory


register_planner("api", GeminiPlanner)
register_planner("local", OllamaPlanner)
register_vision_planner("api", GeminiVisionPlanner)
register_vision_planner("local", OllamaVisionPlanner)
