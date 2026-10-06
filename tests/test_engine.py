"""Tests for engine.py — backend selection, planning, vision, execution.

No network: every model call is a fake.
"""
import copy
import json

import pytest

import engine
from gemmabot.map_vision import check_world

# A tiny solvable world: robot [0,0] facing East, open row to the goal [3,0].
SIMPLE_WORLD = {"robot": [0, 0], "dir": "E", "goal": [3, 0], "walls": []}
SIMPLE_PLAN = [{"cmd": "forward", "steps": 3}]

# A verified route through engine.SAMPLE_WORLD (see test_end_to_end_*).
SAMPLE_PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 4},   # [0,0] -> [0,4]
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},   # -> [2,4]
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 2},   # -> [2,6]
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},   # -> [4,6]
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 1},   # -> [4,7]
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 3},   # -> [7,7] goal
]


def _plan_reply(actions):
    return json.dumps({"thought": "test", "actions": actions})


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def test_get_ask_returns_injected_backends():
    api = lambda instruction, world: "A"
    local = lambda instruction, world: "L"
    assert engine.get_ask("api", api_fn=api, local_fn=local) is api
    assert engine.get_ask("local", api_fn=api, local_fn=local) is local


def test_get_ask_rejects_unknown_backend():
    with pytest.raises(ValueError):
        engine.get_ask("telepathy")


def test_ask_auto_falls_back_to_local_and_reports_it():
    def broken_api(instruction, world):
        raise RuntimeError("no key")

    local = lambda instruction, world: "local reply"
    reply = engine.ask_auto("go", SIMPLE_WORLD, api_fn=broken_api, local_fn=local)
    assert reply == "local reply"

    ask = engine.get_ask("auto", api_fn=broken_api, local_fn=local)
    assert ask("go", SIMPLE_WORLD) == "local reply"
    assert engine._used_backend_label("auto", ask) == "ollama"


def test_get_vision_ask_is_separate_from_text_and_falls_back():
    vision_api = lambda prompt, image, mime: "V"
    vision_local = lambda prompt, image, mime: "VL"
    assert engine.get_vision_ask("api", api_fn=vision_api, local_fn=vision_local) is vision_api

    def broken(image_prompt, image, mime):
        raise RuntimeError("vision down")

    ask = engine.get_vision_ask("auto", api_fn=broken, local_fn=vision_local)
    assert ask("p", b"x", "image/png") == "VL"
    assert engine._used_backend_label("auto", ask) == "ollama"


# ---------------------------------------------------------------------------
# run_plan
# ---------------------------------------------------------------------------

def test_run_plan_success_returns_verified_actions_and_metrics():
    world_before = copy.deepcopy(SIMPLE_WORLD)
    ask = lambda instruction, world: _plan_reply(SIMPLE_PLAN)

    result = engine.run_plan("go to the goal", SIMPLE_WORLD, backend="api", max_tries=3, ask=ask)

    assert result["actions"] == SIMPLE_PLAN
    assert result["attempts"] == 1
    assert result["history"][0]["ok"] is True
    assert result["error"] is None
    assert result["backend"] == "api"
    assert result["latency"] >= 0.0
    assert SIMPLE_WORLD == world_before, "run_plan must not mutate the caller's world"


def test_run_plan_repairs_then_succeeds_and_keeps_history():
    calls = {"n": 0}

    def ask(instruction, world):
        calls["n"] += 1
        if calls["n"] == 1:
            return _plan_reply([{"cmd": "forward", "steps": 7}])  # overshoots the grid
        return _plan_reply(SIMPLE_PLAN)

    result = engine.run_plan("go", SIMPLE_WORLD, backend="local", max_tries=3, ask=ask)

    assert result["actions"] == SIMPLE_PLAN
    assert result["attempts"] == 2
    assert [record["ok"] for record in result["history"]] == [False, True]
    assert result["backend"] == "ollama"
    assert result["error"] is None


def test_run_plan_failure_reports_last_verification_error():
    # A wall at [1, 0] makes this plan genuinely blocked.
    walled_world = {"robot": [0, 0], "dir": "E", "goal": [3, 0], "walls": [[1, 0]]}
    ask = lambda instruction, world: _plan_reply([{"cmd": "forward", "steps": 3}])

    result = engine.run_plan("go", walled_world, backend="api", max_tries=2, ask=ask)

    assert result["actions"] is None
    assert result["attempts"] == 2
    assert result["error"]
    assert "blocked" in result["error"].lower()
    assert all(record["ok"] is False for record in result["history"])


def test_run_plan_survives_ask_exceptions():
    def ask(instruction, world):
        raise RuntimeError("boom: API key rejected")

    result = engine.run_plan("go", SIMPLE_WORLD, backend="api", max_tries=2, ask=ask)

    assert result["actions"] is None
    assert "boom" in result["error"]
    assert len(result["history"]) == 2
    assert result["backend"] == "api"


def test_run_plan_streams_every_attempt_to_on_attempt():
    calls = {"n": 0}

    def ask(instruction, world):
        calls["n"] += 1
        if calls["n"] == 1:
            return "no json at all"
        return _plan_reply(SIMPLE_PLAN)

    seen: list[dict] = []
    result = engine.run_plan(
        "go", SIMPLE_WORLD, backend="api", max_tries=3, ask=ask, on_attempt=seen.append
    )

    assert [record["attempt"] for record in seen] == [1, 2]
    assert [record["ok"] for record in seen] == [False, True]
    # The callback sees the records the harness really wrote, in order.
    assert seen == result["history"]
    # A parse failure recorded no actions; the accepted attempt did.
    assert seen[0]["actions"] is None
    assert seen[1]["actions"] == SIMPLE_PLAN


def test_run_plan_returns_the_structured_verification_of_its_plan():
    ask = lambda instruction, world: _plan_reply(SIMPLE_PLAN)

    result = engine.run_plan("go", SIMPLE_WORLD, backend="api", max_tries=1, ask=ask)
    verification = result["verification"]

    assert verification["ok"] is True
    assert verification["actions"] == SIMPLE_PLAN
    assert [entry["ok"] for entry in verification["checks"]] == [True] * 4
    assert SIMPLE_WORLD == {"robot": [0, 0], "dir": "E", "goal": [3, 0], "walls": []}


def test_a_failed_run_still_verifies_the_last_plan_it_attempted():
    walled_world = {"robot": [0, 0], "dir": "E", "goal": [3, 0], "walls": [[1, 0]]}
    ask = lambda instruction, world: _plan_reply([{"cmd": "forward", "steps": 3}])

    result = engine.run_plan("go", walled_world, backend="api", max_tries=2, ask=ask)
    verification = result["verification"]

    assert result["actions"] is None
    assert verification is not None, "the last attempted plan is still verifiable"
    assert verification["actions"] == [{"cmd": "forward", "steps": 3}]
    checks = {entry["id"]: entry for entry in verification["checks"]}
    assert checks["valid_actions"]["ok"] is True
    assert checks["no_collisions"]["ok"] is False
    assert "[1, 0]" in checks["no_collisions"]["detail"]


def test_a_run_with_nothing_parsable_has_no_verification():
    def ask(instruction, world):
        raise RuntimeError("boom")

    result = engine.run_plan("go", SIMPLE_WORLD, backend="api", max_tries=2, ask=ask)

    assert result["verification"] is None


def test_verify_run_reports_none_without_actions():
    assert engine.verify_run(SIMPLE_WORLD, None, []) is None
    assert engine.verify_run(SIMPLE_WORLD, None, [{"attempt": 1, "actions": None}]) is None


def test_verify_run_never_mutates_the_world():
    world = copy.deepcopy(SIMPLE_WORLD)

    engine.verify_run(SIMPLE_WORLD, SIMPLE_PLAN, [])

    assert SIMPLE_WORLD == world


def test_backend_labels_and_models_come_from_the_real_configuration():
    from gemmabot.config import GEMMA_API_MODEL, OLLAMA_MODEL

    assert engine.backend_label("api") == "API (Gemini)"
    assert engine.backend_label("ollama") == "Ollama (local)"
    assert engine.backend_label("auto") == "Auto (API → Ollama)"
    assert engine.backend_model("api") == GEMMA_API_MODEL
    assert engine.backend_model("local") == OLLAMA_MODEL
    # An unresolved auto backend must not claim a model.
    assert engine.backend_model("auto") is None
    # 'local' is the UI alias of 'ollama': label and model must agree with it.
    assert engine.backend_label("local") == engine.backend_label("ollama")
    assert engine.backend_label("LOCAL ") == "Ollama (local)"
    # Anything else is shown verbatim rather than guessed at.
    assert engine.backend_label("weird") == "weird"


def test_run_plan_auto_reports_backend_that_actually_answered():
    def broken_api(instruction, world):
        raise RuntimeError("api down")

    local = lambda instruction, world: _plan_reply(SIMPLE_PLAN)
    ask = engine.get_ask("auto", api_fn=broken_api, local_fn=local)

    result = engine.run_plan("go", SIMPLE_WORLD, backend="auto", max_tries=1, ask=ask)

    assert result["actions"] == SIMPLE_PLAN
    assert result["backend"] == "ollama"


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

def test_execute_reaches_goal_without_mutating_the_input_world():
    world_before = copy.deepcopy(SIMPLE_WORLD)
    seen = []

    outcome = engine.execute(
        SIMPLE_WORLD,
        SIMPLE_PLAN,
        on_step=lambda entry, sim: seen.append((entry["step"], list(sim["robot"]))),
    )

    assert outcome["ok"] is True
    assert outcome["reached"] is True
    assert outcome["world"]["robot"] == [3, 0]
    assert [entry["message"] for entry in outcome["log"]] == ["moved forward 3"]
    assert seen == [(1, [3, 0])]
    assert SIMPLE_WORLD == world_before, "execute must not mutate the caller's world"


def test_execute_stops_on_blocked_action():
    world = {"robot": [0, 0], "dir": "E", "goal": [7, 0], "walls": [[1, 0]]}
    outcome = engine.execute(world, [{"cmd": "forward", "steps": 3}])

    assert outcome["ok"] is False
    assert outcome["reached"] is False
    assert outcome["world"]["robot"] == [0, 0]
    assert outcome["log"][0]["message"].startswith("blocked")


def test_execute_handles_empty_action_list():
    outcome = engine.execute(SIMPLE_WORLD, [])
    assert outcome["log"] == []
    assert outcome["ok"] is True
    assert outcome["reached"] is False


# ---------------------------------------------------------------------------
# run_map_vision
# ---------------------------------------------------------------------------

def test_run_map_vision_with_fake_vision_success():
    image = b"fake-image-bytes"
    world_json = json.dumps(engine.sample_world())
    fake_vision = lambda prompt, image_bytes, mime: world_json

    result = engine.run_map_vision(image, "image/png", backend="api", max_tries=2, ask_vision=fake_vision)

    assert result["world"] == engine.SAMPLE_WORLD
    assert result["attempts"] == 1
    assert result["error"] is None
    assert result["backend"] == "api"
    assert result["latency"] >= 0.0
    assert result["history"][0]["ok"] is True


def test_run_map_vision_reports_final_failure_reason():
    fake_vision = lambda prompt, image_bytes, mime: "Here is the map, no JSON."

    result = engine.run_map_vision(b"x", "image/png", backend="api", max_tries=2, ask_vision=fake_vision)

    assert result["world"] is None
    assert len(result["history"]) == 2
    assert "json" in result["error"].lower()


def test_run_map_vision_repairs_on_second_attempt():
    calls = {"n": 0}
    good = json.dumps(engine.sample_world())
    bad = json.dumps({"robot": [0, 0], "dir": "E", "goal": [3, 1], "walls": [[3, 1]]})

    def fake_vision(prompt, image_bytes, mime):
        calls["n"] += 1
        return good if calls["n"] > 1 else bad

    result = engine.run_map_vision(b"x", "image/png", backend="local", max_tries=2, ask_vision=fake_vision)

    assert calls["n"] == 2
    assert result["world"] == engine.SAMPLE_WORLD
    assert [record["ok"] for record in result["history"]] == [False, True]
    assert result["backend"] == "ollama"


# ---------------------------------------------------------------------------
# check_connections
# ---------------------------------------------------------------------------

class _FakeOllamaDict:
    def list(self):
        return {"models": [{"name": "gemma4:e4b"}, {"name": "llama3"}]}


class _FakeOllamaObject:
    def list(self):
        class Model:
            def __init__(self, name):
                self.model = name

        return type("Listing", (), {"models": [Model("gemma4:e4b")]})()


class _BrokenOllama:
    def list(self):
        raise ConnectionError("ollama not running")


def test_check_connections_reports_key_and_models_without_leaking(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    result = engine.check_connections(ollama_client=_FakeOllamaDict())

    assert result["api_key_set"] is True
    assert result["ollama_reachable"] is True
    assert result["ollama_models"] == ["gemma4:e4b", "llama3"]
    assert "super-secret-value" not in json.dumps(result)


def test_check_connections_handles_object_shaped_ollama_listing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = engine.check_connections(ollama_client=_FakeOllamaObject())

    assert result["api_key_set"] is False
    assert result["ollama_models"] == ["gemma4:e4b"]


def test_check_connections_reports_unreachable_ollama(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    result = engine.check_connections(ollama_client=_BrokenOllama())

    assert result["api_key_set"] is True
    assert result["ollama_reachable"] is False
    assert result["ollama_models"] == []


# ---------------------------------------------------------------------------
# Maps
# ---------------------------------------------------------------------------

def test_default_maps_are_fresh_copies():
    first = engine.default_maps()
    second = engine.default_maps()
    assert set(first) == {"default", "sample"}
    first["default"]["robot"][0] = 99
    assert second["default"]["robot"] == [0, 0]


def test_sample_world_is_valid_and_solvable():
    ok, reason = check_world(engine.sample_world())
    assert ok is True, reason
    assert engine.sample_world()["goal"] == [7, 7]


# ---------------------------------------------------------------------------
# End-to-end: scanned world -> verified plan -> execution (no network)
# ---------------------------------------------------------------------------

def test_end_to_end_mapvision_world_flows_into_text_execution():
    """The exact §36 pipeline: image -> read_map -> check_world -> render ->
    plan_with_repair -> step, with the same world surviving every stage."""
    image_bytes = b"fake-maze-photo"
    scanned_json = json.dumps(engine.sample_world())
    vision = lambda prompt, image, mime: scanned_json

    # 1. MapVision proposes -> pure Python verifies.
    vision_result = engine.run_map_vision(image_bytes, "image/png", backend="api", ask_vision=vision)
    scanned_world = vision_result["world"]
    assert scanned_world is not None
    ok, reason = check_world(scanned_world)
    assert ok is True, reason

    # 2. The accepted world is rendered by the simulator itself.
    from gemmabot.simulator import render

    rows = render(scanned_world)
    assert len(rows) == 8 and all(len(row) > 0 for row in rows)

    # 3. Text command plans on exactly that world.
    ask = lambda instruction, world: _plan_reply(SAMPLE_PLAN)
    plan = engine.run_plan("go to the goal", scanned_world, backend="api", max_tries=2, ask=ask)
    assert plan["actions"] == SAMPLE_PLAN, plan["error"]

    # 4. Execute the accepted plan; world keeps its identity all the way through.
    before = copy.deepcopy(scanned_world)
    outcome = engine.execute(scanned_world, plan["actions"])
    assert outcome["reached"] is True
    assert outcome["world"]["goal"] == [7, 7]
    assert outcome["world"]["walls"] == before["walls"]
    assert scanned_world == before, "the scanned world must not be rebuilt or mutated"
