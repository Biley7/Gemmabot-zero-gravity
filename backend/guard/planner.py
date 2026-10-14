"""Model-agnostic planner interface — Gemma is one implementation, not the assumption.

Owner: BACKEND.

The guard talks to a ``Planner`` object, never to a vendor SDK.  The shipped
implementations are adapters over the existing transports:

    GeminiPlanner / GeminiVisionPlanner      Google Gemini (google-genai) — Gemma, the flagship
    OllamaPlanner / OllamaVisionPlanner      local Ollama
    OpenAICompatiblePlanner                  any OpenAI-compatible chat-completions endpoint
    MockPlanner                              scripted replies, no network (tests, demos)
    RecordedPlanner                          replays replies captured from a real planner
    FallbackPlanner                          try primary, fall back on any exception
    CallablePlanner                          any ask(instruction, world) -> str (tests, tools)

``build_planner(name, ...)`` / ``build_vision_planner(name, ...)`` resolve
``api``, ``local``, ``openai``, ``mock``, ``recorded`` and ``auto``;
``register_planner`` lets a deployment add its own backend without touching
the guard or the UI.  Which adapter produced a plan is never the verifier's
concern: every adapter answers with reply *text*, one parser normalises it,
and the plan contract a run sees is identical.

Transport imports are lazy inside ``propose``/``read`` so importing this module
never requires google-genai, ollama or a network endpoint to be installed.
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

class OpenAICompatiblePlanner:
    """Any OpenAI-compatible chat-completions endpoint.

    OpenAI itself, vLLM, LM Studio, Ollama's OpenAI mode, OpenRouter — one
    transport, configured by *model* / *base_url* / *api_key* rather than
    hard-coded to a vendor.  Without arguments the values come from
    ``gemmabot.config`` (``OPENAI_MODEL``, ``OPENAI_BASE_URL``,
    ``OPENAI_API_KEY``).  A hosted OpenAI base URL requires a key before any
    request is built; a self-hosted endpoint legitimately does not.

    *_chat* is an injection point for tests: ``_chat(messages, model) -> str``
    stands in for the HTTP call, so no test in this project opens a socket.
    """

    name = "openai"

    def __init__(
        self,
        model: str | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        _chat: Any = None,
    ):
        self._model = model
        self._base_url = base_url
        self._api_key = api_key
        self._timeout = timeout
        self._chat = _chat

    def propose(self, instruction: str, world: dict) -> str:
        from gemmabot.config import (
            OPENAI_MODEL, OPENAI_TIMEOUT, openai_missing_key_message,
            openai_needs_key,
        )
        from gemmabot.prompts import SYSTEM, world_prompt

        if self._model:
            model = self._model
        else:
            model = OPENAI_MODEL
        if self._base_url:
            base_url = self._base_url.rstrip("/")
        else:
            base_url = _openai_base_url()
        api_key = self._api_key
        if api_key is None:
            api_key = _openai_api_key()
        if openai_needs_key(base_url) and not api_key and self._api_key is None:
            raise RuntimeError(openai_missing_key_message())

        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": world_prompt(world, instruction)},
        ]
        if self._chat is not None:
            return self._chat(messages, model=model)
        return _openai_chat(
            messages,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=self._timeout if self._timeout is not None else OPENAI_TIMEOUT,
        )


class MockPlanner:
    """A scripted planner: deterministic replies, no model, no network.

    *replies* are reply *texts* — the ``{thought, actions}`` JSON a model would
    return — given back in order, the last one repeating once the list runs
    out, so a repair loop gets a scripted second attempt it can rely on.
    ``calls`` counts every proposal a test wants to assert on.  A mock built
    with no replies answers the empty plan, which the verifier honestly
    refuses: a mock never fakes a passing ratio.
    """

    name = "mock"

    def __init__(self, replies: str | list[str] | None = None, *, name: str = "mock"):
        self.name = name
        self._replies: list[str] = (
            [replies] if isinstance(replies, str) else list(replies or [])
        )
        self.calls = 0

    def propose(self, instruction: str, world: dict) -> str:
        self.calls += 1
        if not self._replies:
            return '{"thought": "mock planner", "actions": []}'
        index = min(self.calls - 1, len(self._replies) - 1)
        return self._replies[index]


class RecordedPlanner:
    """Replay the replies a real planner gave — a recorded backend.

    *records* maps an instruction to the reply captured for it.  A replan seeds
    the instruction with the previous refusal's feedback, so an exact match can
    miss; fall back to recording replies by the plan they must produce is the
    caller's job — this adapter replays honestly or raises.  An instruction
    with no recorded reply raises ``ValueError``, which the guard loop reads
    like any planner failure, never a silent guess.
    """

    name = "recorded"

    def __init__(
        self, records: dict[str, str] | None = None, *, name: str = "recorded"
    ):
        self.name = name
        self._records: dict[str, str] = dict(records or {})

    def record(self, instruction: str, reply: str) -> None:
        """Capture one instruction → reply pair (how a transcript is built)."""
        self._records[str(instruction)] = str(reply)

    def propose(self, instruction: str, world: dict) -> str:
        reply = self._records.get(str(instruction))
        if reply is None:
            raise ValueError(
                f"no recorded reply for instruction {instruction[:80]!r}"
            )
        return reply


# ── OpenAI-compatible transport — stdlib only, importable without the SDK ──

def _openai_chat(
    messages: list[dict],
    *,
    model: str,
    base_url: str,
    api_key: str,
    timeout: float,
) -> str:
    """One POST to ``{base_url}/chat/completions``; the first reply text back.

    An unexpected reply shape is a readable ``RuntimeError`` — the guard loop
    reports it like any planner failure, and the logger redacts it like any
    error that could otherwise carry the key.
    """
    import json as _json
    import urllib.request

    payload = _json.dumps({
        "model": model,
        "messages": messages,
        "temperature": _temperature(),
    }).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = _json.load(response)
    try:
        return body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"unexpected reply shape from {base_url}: {exc!r}"
        ) from exc


def _temperature() -> float:
    from gemmabot.config import TEMPERATURE

    return TEMPERATURE


def _openai_api_key() -> str:
    from gemmabot.config import openai_api_key

    return openai_api_key()


def _openai_base_url() -> str:
    from gemmabot.config import OPENAI_BASE_URL

    return OPENAI_BASE_URL


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
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
register_planner("openai", OpenAICompatiblePlanner)
register_planner("mock", MockPlanner)
register_planner("recorded", lambda: RecordedPlanner({}))
register_vision_planner("api", GeminiVisionPlanner)
register_vision_planner("local", OllamaVisionPlanner)
