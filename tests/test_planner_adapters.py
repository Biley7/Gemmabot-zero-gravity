"""Model-agnostic planner adapters (Phase 9): one contract, many planners.

The guard must never care which model planned.  These tests pin that claim
end to end on the exact final code: the shipped adapters — Gemma over the
Gemini transport, local Ollama, any OpenAI-compatible endpoint, a mock, a
recorded replay, and a plain callable — all

* answer with reply *text* that one parser (``backend.parsing``) normalises
  into the same ``(thought, actions)`` shape, and
* flow through ``backend.api.planner.plan`` into the *same* ``RunResult``
  contract: every documented key present, same verified plan, same
  approved seal — only the planner's own name, its live/synthetic
  provenance and the wall-clock latency may differ.

Nothing here opens a socket: every transport is injected or scripted, and
the OpenAI-compatible tests patch ``urllib.request.urlopen`` only.
"""
from __future__ import annotations

import io
import json

import pytest

from backend.api import planner as planner_api
from backend.guard.planner import (
    CallablePlanner,
    MockPlanner,
    OllamaPlanner,
    OpenAICompatiblePlanner,
    RecordedPlanner,
    build_planner,
)
from backend.parsing import parse_plan_reply
from backend.verifier.harness import verify_plan
from gemmabot.simulator import new_world

# The reply every adapter gives: the project's plan contract in text form —
# {thought, actions} — not any vendor's format.
PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]
REPLY = json.dumps({"thought": "east then north", "actions": PLAN})
INSTRUCTION = "go to the goal"

RUNRESULT_KEYS = {
    "api_version", "instruction", "world", "planner", "mode", "approved",
    "reason", "actions", "attempts", "repaired", "verification",
    "simulation", "execution", "latency", "history", "run_id", "error",
}


# ---------------------------------------------------------------------------
# The adapters, each scripted to speak the same reply text
# ---------------------------------------------------------------------------

def _gemma_adapter() -> CallablePlanner:
    """flagship Gemma over the Gemini transport, transport scripted."""
    return CallablePlanner("api", lambda instruction, world: REPLY)


def _ollama_adapter() -> CallablePlanner:
    """local Ollama's adapter name, transport scripted.

    (The real ``OllamaPlanner`` lazy-imports the ollama SDK inside ``propose``;
    the transport hook ``build_planner("local", local_fn=...)`` is the tested
    seam, and the adapter *name* is what the contract carries.)
    """
    return CallablePlanner("ollama", lambda instruction, world: REPLY)


def _openai_adapter() -> OpenAICompatiblePlanner:
    """any OpenAI-compatible endpoint, transport injected above the socket."""
    return OpenAICompatiblePlanner(
        "llama3.2",
        base_url="http://127.0.0.1:11434/v1",
        api_key="",
        _chat=lambda messages, model: (
            REPLY
            if model == "llama3.2" and messages[0]["role"] == "system"
            and messages[1]["role"] == "user"
            else "wrong request"
        ),
    )


def _mock_adapter() -> MockPlanner:
    return MockPlanner(REPLY)


def _recorded_adapter() -> RecordedPlanner:
    return RecordedPlanner({INSTRUCTION: REPLY})


def _callable_adapter() -> CallablePlanner:
    return CallablePlanner("custom-callback", lambda instruction, world: REPLY)


def _all_text_adapters() -> list:
    return [
        _gemma_adapter(),
        _ollama_adapter(),
        _openai_adapter(),
        _mock_adapter(),
        _recorded_adapter(),
        _callable_adapter(),
    ]


# Names the RunResult carries for our scripted adapters, in the list order.
ADAPTER_NAMES = ["api", "ollama", "openai", "mock", "recorded", "custom-callback"]


# ---------------------------------------------------------------------------
# Normalisation: every adapter's reply parses into the same contract
# ---------------------------------------------------------------------------

def test_every_adapter_reply_normalises_to_the_same_thought_and_actions():
    parsed = [
        parse_plan_reply(adapter.propose(INSTRUCTION, new_world()))
        for adapter in _all_text_adapters()
    ]
    assert parsed == [("east then north", PLAN)] * len(parsed)


def test_parse_plan_reply_accepts_fenced_replies_like_a_model_emits_them():
    fenced = f"```json\n{REPLY}\n```"
    for adapter in (MockPlanner(fenced), RecordedPlanner({"go": fenced})):
        assert parse_plan_reply(adapter.propose("go", new_world())) == (
            "east then north", PLAN
        )


def test_the_verified_plan_is_identical_across_adapters():
    verdicts = [
        verify_plan(
            new_world(),
            parse_plan_reply(adapter.propose(INSTRUCTION, new_world()))[1],
        )
        for adapter in _all_text_adapters()
    ]
    assert verdicts[0]["ok"] is True
    assert all(verdict == verdicts[0] for verdict in verdicts)


# ---------------------------------------------------------------------------
# The RunResult contract: one shape through backend.api.planner.plan
# ---------------------------------------------------------------------------

def _plan_with(adapter) -> dict:
    return planner_api.plan(INSTRUCTION, new_world(), planner=adapter, max_tries=3)


@pytest.mark.parametrize("make,name", [
    (_gemma_adapter, "api"),
    (_ollama_adapter, "ollama"),
    (_openai_adapter, "openai"),
    (_mock_adapter, "mock"),
    (_recorded_adapter, "recorded"),
    (_callable_adapter, "custom-callback"),
])
def test_plan_returns_the_same_contract_for_every_adapter(make, name):
    result = _plan_with(make())
    assert RUNRESULT_KEYS <= set(result), "every documented RunResult key is present"
    assert result["planner"] == name
    assert result["approved"] is not None
    assert result["actions"] == PLAN
    assert result["attempts"] == 1
    assert result["verification"]["ok"] is True
    # The approval seals exactly this plan for exactly this instruction.
    assert result["approved"].action_list() == PLAN


def _normalised(result: dict) -> dict:
    """The RunResult with only adapter-specific fields dropped.

    ``planner`` / ``mode`` name who answered and how honestly, ``latency`` is
    wall-clock, and an ``ApprovedPlan`` embeds the planner's own name — so the
    contract comparison reads the sealed *plan*, not the capability object.
    """
    out = {
        key: value
        for key, value in result.items()
        if key not in {"planner", "mode", "latency", "approved"}
    }
    if result.get("approved") is not None:
        out["sealed_plan"] = result["approved"].action_list()
    return out


def test_normalised_contract_is_identical_once_naming_provenance_and_time_dropped():
    results = [_plan_with(adapter) for adapter in _all_text_adapters()]
    assert [r["planner"] for r in results] == ADAPTER_NAMES
    canonical = _normalised(results[0])
    expected_keys = (
        {key for key in RUNRESULT_KEYS
         if key not in {"planner", "mode", "latency", "approved"}}
        | {"sealed_plan"}
    )
    assert set(canonical) == expected_keys
    for result in results[1:]:
        assert _normalised(result) == canonical


def test_provenance_is_honest_per_planner_kind():
    """A named model endpoint is live; mock and recorded are synthetic."""
    live = _plan_with(_openai_adapter())
    synthetic = _plan_with(_mock_adapter())
    assert live["mode"] == "live"
    assert synthetic["mode"] == "synthetic"


def test_a_registered_planner_name_runs_the_same_loop():
    from backend.guard.planner import register_planner

    registered = CallablePlanner("deployment-gemma", lambda instruction, world: REPLY)
    register_planner("deployment-gemma", lambda: registered)
    result = planner_api.plan(INSTRUCTION, new_world(), backend="deployment-gemma")
    assert result["planner"] == "deployment-gemma"
    assert result["actions"] == PLAN
    assert result["verification"]["ok"] is True


# ---------------------------------------------------------------------------
# Registry and construction
# ---------------------------------------------------------------------------

def test_build_planner_resolves_registered_non_model_planners():
    assert build_planner("openai").name == "openai"
    assert build_planner("mock").name == "mock"
    assert build_planner("recorded").name == "recorded"


def test_build_planner_still_resolves_the_flagship_and_local():
    assert build_planner("api").name == "api"
    assert build_planner("local").name == "ollama"


# ---------------------------------------------------------------------------
# MockPlanner semantics
# ---------------------------------------------------------------------------

def test_mock_planner_replies_in_order_then_repeats_the_last():
    mock = MockPlanner(["first", "second"])
    assert mock.propose("a", {}) == "first"
    assert mock.propose("b", {}) == "second"
    assert mock.propose("c", {}) == "second"
    assert mock.calls == 3


def test_mock_planner_with_no_reply_answers_the_empty_plan():
    reply = MockPlanner().propose("go to the goal", new_world())
    thought, actions = parse_plan_reply(reply)
    assert thought == "mock planner"
    assert actions == []
    assert verify_plan(new_world(), actions)["ok"] is False


def test_mock_planner_records_its_calls_for_a_test_to_assert_on():
    mock = MockPlanner(REPLY)
    mock.propose("x", {})
    mock.propose("y", {})
    assert mock.calls == 2


# ---------------------------------------------------------------------------
# RecordedPlanner semantics
# ---------------------------------------------------------------------------

def test_recorded_planner_replays_captured_replies_exactly():
    recorder = RecordedPlanner()
    recorder.record(INSTRUCTION, REPLY)
    assert recorder.propose(INSTRUCTION, new_world()) == REPLY


def test_recorded_planner_raises_on_an_unrecorded_instruction():
    recorder = RecordedPlanner({INSTRUCTION: REPLY})
    with pytest.raises(ValueError, match="no recorded reply"):
        recorder.propose("a different instruction", new_world())


# ---------------------------------------------------------------------------
# OpenAI-compatible transport (stdlib; patched at the socket boundary)
# ---------------------------------------------------------------------------

_KEYLESS_BODY = json.dumps(
    {"choices": [{"message": {"content": REPLY}}]}
).encode()


def test_openai_adapter_requires_a_key_only_for_the_hosted_endpoint():
    adapter = OpenAICompatiblePlanner("gpt-4o-mini", base_url="https://api.openai.com/v1")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        adapter.propose(INSTRUCTION, new_world())


def test_openai_adapter_sends_a_chat_completions_request_and_reads_the_reply(
    monkeypatch,
):
    import urllib.request

    captured: dict = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode())
        captured["auth"] = request.headers.get("Authorization")
        assert isinstance(timeout, float)
        return io.BytesIO(_KEYLESS_BODY)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    adapter = OpenAICompatiblePlanner(
        "llama3.2", base_url="http://127.0.0.1:11434/v1", api_key=""
    )
    assert adapter.propose(INSTRUCTION, new_world()) == REPLY
    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["payload"]["model"] == "llama3.2"
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert captured["payload"]["messages"][1]["role"] == "user"
    # A keyless self-hosted endpoint sends no Authorization header.
    assert captured["auth"] is None


def test_openai_adapter_surfaces_an_unexpected_reply_shape_readably(monkeypatch):
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda request, timeout=None: io.BytesIO(json.dumps({"weird": "shape"}).encode()),
    )
    adapter = OpenAICompatiblePlanner("m", base_url="http://127.0.0.1:9/v1", api_key="")
    with pytest.raises(RuntimeError, match="unexpected reply shape"):
        adapter.propose(INSTRUCTION, new_world())


# ---------------------------------------------------------------------------
# The UI never hard-codes a vendor
# ---------------------------------------------------------------------------

def test_the_model_row_reads_the_planner_not_a_vendor():
    from frontend.panels.brain import model_display

    # One honest title per kind of planner.
    assert model_display("gemma-4-26b-a4b-it", "api") == "Gemma 4"
    assert model_display("gemma4:e4b", "ollama") == "Gemma 4"      # Gemma stays flagship
    assert model_display("llama3.2", "ollama") == "Local Model"
    assert model_display(None, "ollama") == "Local Model"          # id unresolved
    assert model_display("llama3.2", "openai") == "llama3.2"       # the endpoint's model
    assert model_display(None, "mock") == "Custom Planner"
    assert model_display(None, "recorded") == "Custom Planner"
    assert model_display(None, "my-deployment") == "Custom Planner"
    assert model_display("llama3.2", None) == "llama3.2"
    assert model_display(None, None) == "—"
    assert model_display(None, "api") == "—"
    assert model_display(None, "auto") == "—"     # unresolved fallback claims nothing


def test_the_guard_panel_shows_custom_planner_for_a_model_free_planner():
    from backend.verifier.harness import verify_plan
    from frontend.console import guard as guard_console
    from frontend.panels import brain

    meta = brain.brain_metadata(
        backend="Custom Planner",
        model=None,
        planner="mock",
        status="thinking",
        attempts=1,
        max_tries=3,
        plan_actions=None,
        checks=verify_plan(new_world(), PLAN)["checks"],
    )
    html = guard_console.metadata_html(meta)
    assert "Custom Planner" in html
    assert "Gemma" not in html


def test_a_run_made_by_the_flagship_still_reads_gemma():
    """Gemma stays the flagship: the MODEL row keeps its family label."""
    from backend.verifier.harness import verify_plan
    from frontend.console import guard as guard_console
    from frontend.panels import brain

    meta = brain.brain_metadata(
        backend="API (Gemini)",
        model="gemma-4-26b-a4b-it",
        planner="api",
        status="executing",
        attempts=1,
        max_tries=3,
        plan_actions=PLAN,
        checks=verify_plan(new_world(), PLAN)["checks"],
    )
    assert meta["model"]["family"] == "Gemma 4"
    assert "Gemma 4" in guard_console.metadata_html(meta)
