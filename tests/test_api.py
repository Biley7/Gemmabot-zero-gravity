"""Tests for the programmatic API (``backend.api``) — the contracts a caller
builds on, and the one invariant they all serve.

What is pinned here:

* **Every public call has a shape.** ``planner.plan``, ``guard.verify``,
  ``guard.approve``, ``guard.simulate``, ``repair.replan``, ``runtime.execute``
  and ``runs.record`` each return the documented keys, every time, for a
  refusal as much as for an approval.
* **Execution requires an approval.** No value reaches the simulator through
  ``runtime.execute`` except a plan the guard sealed and re-verified; a refused
  result, a demonstration, a bare action list and a tampered seal are all
  refused before a step runs.
* **A refusal is a result.** A plan the verifier rejects comes back with its
  reason and no exception; exceptions belong to malformed requests.
* **The API knows nothing of the console.** It is importable without
  Streamlit, and no result carries a prompt or a model reply.

No network and no Streamlit: every planner here is a scripted callable.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import backend.api as api
from backend.api import ContractError, NotApprovedError, guard, planner, repair, runs, runtime
from backend.api.contracts import API_VERSION, ApprovedPlan
from backend.guard.contracts import approval_digest
from gemmabot.simulator import new_world

ROOT = Path(__file__).resolve().parents[1]

# The world every test plans in: robot at [0, 0] facing E, goal at [6, 5],
# wall column at x=3.  HAZARD walks straight into the wall; SAFE is the route
# the verifier proves.
HAZARD = [{"cmd": "forward", "steps": 7}]
SAFE = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]

RUN_KEYS = {
    "api_version", "instruction", "world", "planner", "mode", "approved",
    "reason", "actions", "attempts", "repaired", "verification", "simulation",
    "execution", "latency", "history", "run_id", "error",
}
EXECUTION_KEYS = {
    "api_version", "approved", "reason", "actions", "attempts",
    "verification", "simulation", "execution",
}


def reply(plan: list[dict]) -> str:
    """The JSON body a planner replies with for *plan*."""
    return json.dumps({"thought": "scripted", "actions": plan}, ensure_ascii=False)


def scripted_ask(*replies: str):
    """An ``ask(instruction, world)`` answering with *replies*, one per call.

    The function's name says it is scripted, which is what the API reads to
    report this run's provenance as ``synthetic``.  ``.prompts`` records the
    instruction of every call, for tests about what the planner was told.
    """
    prompts: list[str] = []

    def scripted_ask(instruction: str, world: dict) -> str:
        prompts.append(instruction)
        return replies[min(len(prompts), len(replies)) - 1]

    scripted_ask.prompts = prompts
    return scripted_ask


# ---------------------------------------------------------------------------
# The package boundary
# ---------------------------------------------------------------------------

def test_the_api_exposes_one_namespace_per_documented_call():
    for name in ("planner", "guard", "repair", "runtime", "runs"):
        assert hasattr(api, name)
    assert api.API_VERSION == "1.0"
    assert api.ContractError is ContractError
    assert api.NotApprovedError is NotApprovedError
    assert api.ApprovedPlan is ApprovedPlan


def test_the_api_imports_without_streamlit_or_a_vendor_sdk():
    """The first promise of this layer: a caller needs Python, not the console."""
    code = (
        "import sys, backend.api\n"
        "leaked = [m for m in ('streamlit', 'google', 'ollama') if m in sys.modules]\n"
        "print(' '.join(leaked) or 'clean')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "clean", f"import pulled in: {proc.stdout.strip()}"


# ---------------------------------------------------------------------------
# planner.plan — instruction in, structured result out
# ---------------------------------------------------------------------------

def test_a_run_carries_every_documented_key_and_the_contract_version():
    result = planner.plan("go to the goal", new_world(), planner=scripted_ask(reply(SAFE)))
    assert set(result) == RUN_KEYS
    assert result["api_version"] == API_VERSION


def test_an_approved_plan_is_sealed_but_never_executed_by_planning():
    world = new_world()
    result = planner.plan("go to the goal", world, planner=scripted_ask(reply(SAFE)))
    assert isinstance(result["approved"], ApprovedPlan)
    assert result["approved"].instruction == "go to the goal"
    assert result["actions"] == SAFE
    assert result["verification"]["ok"] is True
    assert result["attempts"] == 1
    assert result["repaired"] is False
    assert result["simulation"] is None       # planning does not simulate
    assert result["execution"] is None        # and it never executes
    assert result["run_id"] is None           # until runs.record
    assert result["error"] is None
    assert "sealed for execution" in result["reason"]
    assert world["robot"] == [0, 0]           # the caller's world never moved


def test_a_repaired_plan_says_it_came_from_repair():
    result = planner.plan(
        "go to the goal", new_world(),
        planner=scripted_ask(reply(HAZARD), reply(SAFE)), max_tries=3,
    )
    assert result["attempts"] == 2
    assert result["repaired"] is True
    assert [record["ok"] for record in result["history"]] == [False, True]
    assert result["approved"] is not None


def test_the_attempt_history_carries_no_prompt_or_reply():
    result = planner.plan(
        "go to the goal", new_world(),
        planner=scripted_ask(reply(HAZARD), reply(SAFE)), max_tries=3,
    )
    assert result["history"]
    for record in result["history"]:
        assert set(record) == {"attempt", "ok", "feedback", "actions"}


def test_a_refusal_is_a_result_not_an_exception():
    result = planner.plan(
        "go to the goal", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1
    )
    assert result["approved"] is None
    assert result["actions"] is None
    assert result["verification"]["ok"] is False
    assert "blocked at [2, 0]" in result["verification"]["reason"]
    assert "no plan was approved" in result["reason"]
    assert result["error"] is not None        # the loop's own redacted feedback


def test_on_attempt_streams_each_record_the_moment_it_is_made():
    seen: list[dict] = []
    planner.plan(
        "go to the goal", new_world(),
        planner=scripted_ask(reply(HAZARD), reply(SAFE)), max_tries=3,
        on_attempt=seen.append,
    )
    assert [record["attempt"] for record in seen] == [1, 2]
    assert [record["ok"] for record in seen] == [False, True]


def test_a_scripted_planner_is_reported_as_synthetic_provenance():
    result = planner.plan("go", new_world(), planner=scripted_ask(reply(SAFE)))
    assert result["mode"] == "synthetic"


def test_a_declared_provenance_is_believed_over_the_planner_name():
    result = planner.plan(
        "go", new_world(), planner=scripted_ask(reply(SAFE)), mode="live"
    )
    assert result["mode"] == "live"


def test_an_unnamed_planner_reports_unrecorded_provenance():
    def ask(instruction: str, world: dict) -> str:   # no marker in the name
        return reply(SAFE)

    result = planner.plan("go", new_world(), planner=ask)
    assert result["mode"] is None


def test_a_supplied_plan_is_validated_not_asked_for():
    result = planner.plan("go to the goal", new_world(), plan=SAFE)
    assert result["planner"] == "supplied"
    assert result["attempts"] == 1
    assert result["approved"] is not None
    assert result["mode"] is None             # a plan is not a provenance


def test_a_refused_supplied_plan_reports_its_reason_and_echoes_no_actions():
    result = planner.plan("go to the goal", new_world(), plan=HAZARD)
    assert result["approved"] is None
    assert result["actions"] is None          # the caller already has the plan
    assert result["verification"]["ok"] is False


BAD_PLAN_REQUESTS = [
    ("empty instruction", lambda world, ask: planner.plan("", world, planner=ask)),
    ("blank instruction", lambda world, ask: planner.plan("   ", world, planner=ask)),
    ("world missing keys", lambda world, ask: planner.plan("go", {"robot": [0, 0]}, planner=ask)),
    ("world is not a dict", lambda world, ask: planner.plan("go", "8x8", planner=ask)),
    ("unknown backend", lambda world, ask: planner.plan("go", world, backend="no-such-model")),
    ("backend and planner", lambda world, ask: planner.plan("go", world, backend="api", planner=ask)),
    ("zero tries", lambda world, ask: planner.plan("go", world, planner=ask, max_tries=0)),
    ("boolean tries", lambda world, ask: planner.plan("go", world, planner=ask, max_tries=True)),
    ("unknown mode", lambda world, ask: planner.plan("go", world, planner=ask, mode="maybe")),
    ("supplied plan and backend", lambda world, ask: planner.plan("go", world, plan=SAFE, backend="api")),
]


@pytest.mark.parametrize(
    "call", [call for _, call in BAD_PLAN_REQUESTS], ids=[name for name, _ in BAD_PLAN_REQUESTS]
)
def test_a_malformed_plan_request_is_answered_by_the_contract(call):
    with pytest.raises(ContractError):
        call(new_world(), scripted_ask(reply(SAFE)))


# ---------------------------------------------------------------------------
# guard.verify — the verdict gate.verify never raises for a refusal
# ---------------------------------------------------------------------------

def test_verify_returns_the_structured_four_check_verdict():
    verdict = guard.verify(new_world(), SAFE)
    assert verdict["ok"] is True
    assert verdict["reason"] == "ok"
    assert [check["id"] for check in verdict["checks"]] == [
        "valid_actions", "in_bounds", "no_collisions", "goal_reachable",
    ]
    assert all(check["ok"] is True for check in verdict["checks"])


def test_verify_never_mutates_what_it_was_given():
    world = new_world()
    actions = copy.deepcopy(SAFE)
    world_before, actions_before = copy.deepcopy(world), copy.deepcopy(actions)
    guard.verify(world, actions)
    assert world == world_before
    assert actions == actions_before


def test_verify_answers_a_refusal_with_facts():
    verdict = guard.verify(new_world(), HAZARD)
    assert verdict["ok"] is False
    assert "blocked at [2, 0]" in verdict["reason"]
    assert any(check["ok"] is False for check in verdict["checks"])
    assert any(check["ok"] is True for check in verdict["checks"])


def test_verify_rejects_a_malformed_request():
    for world, actions in (
        ({"robot": [0, 0]}, SAFE),
        (new_world(), []),
        (new_world(), None),
        (new_world(), [{"steps": 2}]),
    ):
        with pytest.raises(ContractError):
            guard.verify(world, actions)


# ---------------------------------------------------------------------------
# guard.approve — the only door to an ApprovedPlan
# ---------------------------------------------------------------------------

def test_approve_seals_a_verified_plan_with_a_digest_of_its_contents():
    approved = guard.approve(new_world(), SAFE, instruction="go", planner="test")
    assert isinstance(approved, ApprovedPlan)
    assert approved.instruction == "go"
    assert approved.planner == "test"
    assert approved.action_list() == SAFE
    assert approved.approval_id == approval_digest(approved.world, approved.action_list())


def test_approve_returns_none_for_a_plan_the_verifier_refuses():
    assert guard.approve(new_world(), HAZARD) is None


def test_approve_rejects_a_malformed_request():
    for world, actions in (({"robot": [0, 0]}, SAFE), (new_world(), []), (new_world(), "go")):
        with pytest.raises(ContractError):
            guard.approve(world, actions)


# ---------------------------------------------------------------------------
# guard.simulate — demonstration, never approval
# ---------------------------------------------------------------------------

def test_simulate_is_never_an_approval():
    result = guard.simulate(new_world(), SAFE)
    assert result["verified"] is False
    assert result["approval_id"] is None
    assert result["ok"] is True
    assert result["reached"] is True
    assert len(result["log"]) == len(SAFE)


def test_simulate_demonstrates_even_a_refused_plan():
    result = guard.simulate(new_world(), HAZARD)
    assert result["ok"] is False
    assert result["verified"] is False
    assert result["log"][0]["message"].startswith("blocked")


def test_simulate_allows_an_empty_plan():
    result = guard.simulate(new_world(), [])
    assert result["log"] == []
    assert result["verified"] is False


def test_simulate_streams_each_step():
    steps: list[int] = []
    guard.simulate(new_world(), SAFE[:2], on_step=lambda entry, world: steps.append(entry["step"]))
    assert steps == [1, 2]


def test_simulate_rejects_a_malformed_request():
    with pytest.raises(ContractError):
        guard.simulate({"robot": [0, 0]}, SAFE)
    with pytest.raises(ContractError):
        guard.simulate(new_world(), "go")


# ---------------------------------------------------------------------------
# repair.replan — one more attempt, told why the last one failed
# ---------------------------------------------------------------------------

def test_replan_asks_again_with_the_previous_failure_in_the_prompt():
    refused = planner.plan(
        "go to the goal", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1
    )
    ask = scripted_ask(reply(SAFE))
    result = repair.replan(refused, planner=ask)

    prompt = ask.prompts[0]
    assert "go to the goal" in prompt
    assert "Your previous plan failed." in prompt
    assert '"actions":[{"cmd":"forward","steps":7}]' in prompt.replace(" ", "")
    assert "blocked at [2, 0]" in prompt

    assert result["approved"] is not None
    assert result["instruction"] == "go to the goal"   # the original ask, not the seed
    assert result["attempts"] == 1
    assert result["repaired"] is True                  # repaired by construction


def test_replan_can_stack_attempts_until_the_planner_fixes_it():
    refused = planner.plan(
        "go to the goal", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1
    )
    result = repair.replan(refused, planner=scripted_ask(reply(HAZARD), reply(SAFE)), tries=2)
    assert result["attempts"] == 2
    assert [record["ok"] for record in result["history"]] == [False, True]
    assert result["approved"] is not None


def test_a_replan_that_fails_again_is_still_a_result():
    refused = planner.plan(
        "go to the goal", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1
    )
    result = repair.replan(refused, planner=scripted_ask(reply(HAZARD)))
    assert result["approved"] is None
    assert result["repaired"] is False
    assert "no plan was approved" in result["reason"]


def test_replan_refuses_to_repair_an_approved_result():
    approved = planner.plan("go", new_world(), planner=scripted_ask(reply(SAFE)))
    with pytest.raises(ContractError, match="already approved"):
        repair.replan(approved, planner=scripted_ask(reply(SAFE)))


def test_replan_needs_a_planner_for_a_result_that_names_none():
    refused = planner.plan(
        "go", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1
    )
    with pytest.raises(ContractError, match="needs a planner"):
        repair.replan(refused)


def test_replan_seeds_a_run_that_never_produced_a_plan_with_its_error():
    minimal = {
        "instruction": "go to the goal",
        "world": new_world(),
        "approved": None,
        "history": [],
        "error": "ask() raised an error: the model is unreachable",
    }
    ask = scripted_ask(reply(SAFE))
    result = repair.replan(minimal, planner=ask)
    assert "the model is unreachable" in ask.prompts[0]
    assert result["approved"] is not None


def test_replan_rejects_a_malformed_request():
    for value in (None, "go", {}, {"instruction": "go", "approved": None}):
        with pytest.raises(ContractError):
            repair.replan(value, planner=scripted_ask(reply(SAFE)))
    refused = planner.plan("go", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1)
    with pytest.raises(ContractError):
        repair.replan(refused, planner=scripted_ask(reply(SAFE)), tries=0)


# ---------------------------------------------------------------------------
# runtime.execute — approved plans only, re-verified before any step
# ---------------------------------------------------------------------------

def test_execute_runs_an_approved_run_and_reports_what_happened():
    plan = planner.plan(
        "go to the goal", new_world(),
        planner=scripted_ask(reply(HAZARD), reply(SAFE)), max_tries=3,
    )
    outcome = runtime.execute(plan)
    assert set(outcome) == EXECUTION_KEYS
    assert outcome["api_version"] == API_VERSION
    assert outcome["approved"] is plan["approved"]
    assert outcome["attempts"] == 2                 # carried from the run
    assert outcome["actions"] == SAFE
    assert outcome["verification"]["ok"] is True
    assert outcome["simulation"] is None            # this is an execution
    assert outcome["execution"]["verified"] is True
    assert outcome["execution"]["ok"] is True
    assert outcome["execution"]["reached"] is True
    assert len(outcome["execution"]["log"]) == len(SAFE)
    assert "reached the goal" in outcome["reason"]


def test_execute_accepts_a_sealed_plan_directly():
    approved = guard.approve(new_world(), SAFE, instruction="go")
    outcome = runtime.execute(approved)
    assert outcome["attempts"] is None              # no planning run to carry one
    assert outcome["execution"]["ok"] is True
    assert outcome["execution"]["approval_id"] == approved.approval_id


def test_execution_is_impossible_without_an_approved_plan():
    world = new_world()
    refused = planner.plan("go", world, planner=scripted_ask(reply(HAZARD)), max_tries=1)
    demonstration = guard.simulate(world, SAFE)
    for value in (None, SAFE, world, "go", refused, demonstration,
                  {"approved": None}, {"approved": SAFE}):
        with pytest.raises(NotApprovedError):
            runtime.execute(value)


def test_a_refused_approval_steals_no_steps():
    refused = planner.plan("go", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1)
    steps: list[int] = []
    with pytest.raises(NotApprovedError):
        runtime.execute(refused, on_step=lambda entry, world: steps.append(entry["step"]))
    assert steps == []


def test_a_tampered_seal_executes_nothing_and_says_so():
    approved = guard.approve(new_world(), SAFE, instruction="go")
    approved.world["goal"] = [0, 0]                 # the seal covers the snapshot
    steps: list[int] = []
    outcome = runtime.execute(approved, on_step=lambda entry, world: steps.append(entry["step"]))
    assert outcome["execution"]["verified"] is False
    assert outcome["execution"]["ok"] is False
    assert outcome["execution"]["log"] == []
    assert steps == []
    assert "refused" in outcome["reason"]


def test_a_tampered_plan_executes_nothing():
    approved = guard.approve(new_world(), SAFE, instruction="go")
    approved.actions[1]["steps"] = 99               # forward 99 leaves the grid
    outcome = runtime.execute(approved)
    assert outcome["execution"]["verified"] is False
    assert outcome["execution"]["log"] == []


def test_a_fabricated_digest_executes_nothing():
    approved = guard.approve(new_world(), SAFE, instruction="go")
    forged = replace(approved, approval_id="f" * 64)
    outcome = runtime.execute(forged)
    assert outcome["execution"]["verified"] is False
    assert outcome["execution"]["log"] == []
    assert "digest does not match" in outcome["reason"]


def test_execution_mutates_neither_the_caller_world_nor_the_sealed_plan():
    world = new_world()
    actions = copy.deepcopy(SAFE)
    world_before, actions_before = copy.deepcopy(world), copy.deepcopy(actions)
    approved = guard.approve(world, actions, instruction="go")
    runtime.execute(approved)
    assert world == world_before
    assert actions == actions_before
    assert approved.action_list() == SAFE


# ---------------------------------------------------------------------------
# runs.record — the run's own facts, written where the platform reads them
# ---------------------------------------------------------------------------

def test_record_writes_a_replayable_run_and_returns_its_id(tmp_path):
    plan = planner.plan(
        "go to the goal", new_world(),
        planner=scripted_ask(reply(HAZARD), reply(SAFE)), max_tries=3,
    )
    outcome = runtime.execute(plan)
    path = tmp_path / "nested" / "runs.jsonl"
    record = runs.record(plan, path=str(path), execution=outcome, run_id="run000000001")

    assert record["run_id"] == "run000000001"
    assert record["instruction"] == "go to the goal"
    assert record["backend"] == "scripted_ask"
    assert record["mode"] == "synthetic"
    assert record["input_type"] == "text"
    assert record["success"] is True
    assert record["actions"] == SAFE
    assert record["world"] == new_world()
    assert record["verification"]["ok"] is True
    assert record["execution"] == {"ran": True, "halted": None, "steps": len(SAFE)}
    assert record["final_position"] == [6, 5]
    assert record["goal_reached"] is True
    assert path.exists()
    assert runs.load(str(path)) == [record]


def test_record_reports_a_refused_run_without_inventing_an_execution(tmp_path):
    refused = planner.plan(
        "go to the goal", new_world(), planner=scripted_ask(reply(HAZARD)), max_tries=1
    )
    record = runs.record(refused, path=str(tmp_path / "runs.jsonl"))
    assert record["success"] is False
    assert record["actions"] is None
    assert record["execution"] is None
    assert record["verification"]["ok"] is False
    assert record["plan_length"] == 1               # the plan the run is about
    assert record["final_position"] is None
    assert record["goal_reached"] is None


def test_record_accepts_the_execution_outcome_alone(tmp_path):
    plan = planner.plan("go to the goal", new_world(), planner=scripted_ask(reply(SAFE)))
    outcome = runtime.execute(plan)
    record = runs.record(outcome, path=str(tmp_path / "runs.jsonl"))
    assert record["instruction"] == "go to the goal"
    assert record["actions"] == SAFE
    assert record["execution"]["steps"] == len(SAFE)
    assert record["final_position"] == [6, 5]


def test_record_never_writes_a_prompt_or_reply(tmp_path):
    plan = planner.plan(
        "go to the goal", new_world(),
        planner=scripted_ask(reply(HAZARD), reply(SAFE)), max_tries=3,
    )
    record = runs.record(plan, path=str(tmp_path / "runs.jsonl"))
    for entry in record["history"]:
        assert "prompt" not in entry
        assert "reply" not in entry


def test_record_lets_a_caller_name_the_input_type_and_model(tmp_path):
    plan = planner.plan("go", new_world(), planner=scripted_ask(reply(SAFE)))
    record = runs.record(
        plan, path=str(tmp_path / "runs.jsonl"), input_type="benchmark",
        model="gemma-test-1",
    )
    assert record["input_type"] == "benchmark"
    assert record["model"] == "gemma-test-1"
    # "None" is a statement (not recorded), and is written as such.
    unrecorded = runs.record(plan, path=str(tmp_path / "runs.jsonl"), input_type=None)
    assert unrecorded["input_type"] is None


def test_record_fills_in_the_end_position_from_a_refused_execution(tmp_path):
    plan = planner.plan("go", new_world(), planner=scripted_ask(reply(SAFE)))
    approved = plan["approved"]
    approved.world["walls"] = [approved.world["robot"]]      # break the seal
    outcome = runtime.execute(approved)
    record = runs.record(plan, path=str(tmp_path / "runs.jsonl"), execution=outcome)
    assert record["execution"] == {"ran": False, "halted": None, "steps": 0}
    assert record["final_position"] is None


def test_load_returns_nothing_for_a_missing_log(tmp_path):
    assert runs.load(str(tmp_path / "never-written.jsonl")) == []


def test_record_rejects_a_malformed_request(tmp_path):
    plan = planner.plan("go", new_world(), planner=scripted_ask(reply(SAFE)))
    path = str(tmp_path / "runs.jsonl")
    bad_calls = [
        lambda: runs.record("nope", path=path),
        lambda: runs.record({}, path=path),
        lambda: runs.record({"instruction": 5, "world": new_world()}, path=path),
        lambda: runs.record({"instruction": "go", "world": {"robot": [0, 0]}}, path=path),
        lambda: runs.record(plan, path=path, input_type="nonsense"),
        lambda: runs.record(plan, path=path, execution=42),
        lambda: runs.record(plan, path=path, execution={"anything": True}),
    ]
    for call in bad_calls:
        with pytest.raises(ContractError):
            call()


# ---------------------------------------------------------------------------
# The documented pipeline, end to end, through the public API only
# ---------------------------------------------------------------------------

def test_the_documented_pipeline_runs_end_to_end(tmp_path):
    """world → instruction → plan → verify → execute if approved → record."""
    world = new_world()
    ask = scripted_ask(reply(HAZARD), reply(SAFE))     # fails once, then fixes it

    result = planner.plan("go to the goal", world, planner=ask, max_tries=3)
    assert result["verification"]["ok"] is True
    assert result["approved"] is not None

    outcome = runtime.execute(result)
    assert outcome["execution"]["reached"] is True

    path = str(tmp_path / "runs.jsonl")
    record = runs.record(result, path=path, execution=outcome)

    loaded = runs.load(path)
    assert [row["run_id"] for row in loaded] == [record["run_id"]]
    assert loaded[0]["execution"]["ran"] is True
    assert loaded[0]["goal_reached"] is True


def test_the_documented_pipeline_refuses_to_execute_what_was_never_approved(tmp_path):
    """The other half of the pipeline: a refusal ends in a record, not a run."""
    world = new_world()
    result = planner.plan("go to the goal", world, planner=scripted_ask(reply(HAZARD)), max_tries=1)
    assert result["approved"] is None
    with pytest.raises(NotApprovedError):
        runtime.execute(result)

    path = str(tmp_path / "runs.jsonl")
    record = runs.record(result, path=path)
    assert record["success"] is False
    assert record["execution"] is None
    assert runs.load(path)[0]["verification"]["ok"] is False
