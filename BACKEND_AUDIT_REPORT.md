# Backend Audit & Gap Analysis Report

## 1. Executive Summary

This repository has a functioning prototype for the robot-simulation core, but it is not yet a complete backend implementation of the intended architecture. The core runtime behaves as a single-purpose simulation and AI-planning tool: it can instantiate an 8x8 world, validate action execution using a deep-copy safety check, parse model JSON, call Gemini or Ollama, and log runs. However, the structured backend orchestration layer remains incomplete and the Streamlit UI is directly coupled to low-level backend modules instead of calling a clean service boundary.

The repository does not currently contain `PRD.md`, `PROMPTS.md`, or `Techstack.md` at the project root or anywhere under the workspace. The effective contract source for this codebase is the project documentation in `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `docs/WORKFLOW.md`, plus the archive note in `docs/archive/CODEBASE_AUDIT_starter.md`. That is a documentation gap and should be treated as a specification risk.

Overall backend readiness: 58/100.

Why this score:
- Strong core simulation and model-integration prototype: yes
- Safety and repair loop largely present in `gemmabot/harness.py`: yes
- Logging subsystem is implemented and reasonably hardened: yes
- Benchmarking and dry-run validation exist: yes
- Optional vision validation exists: yes
- Critical orchestration boundary (`gemmabot/service.py`, `verifier.py`, `repair.py`, `world_validation.py`) is still stubbed or not wired: no
- Frontend is still coupled directly to backend internals: yes
- Test suite is incomplete and cannot be executed in the current environment until `pytest` is installed: no

The repository aligns loosely with the "Propose -> Verify -> Execute" loop concept, but the implementation is fragmented: planning logic, validation logic, and execution logic are split across modules without a complete orchestration entrypoint or a fully enforced contract layer.

---

## 2. Specification & Contract Verification Table

### 2.1 Effective specification set found in repo

| File | Type | Notes |
|---|---|---|
| `docs/ARCHITECTURE.md` | Architecture contract | Describes the data flow `World -> world_validation -> planner -> verifier -> repair -> logger -> RunResult` and the backend ownership split. |
| `docs/CONTRACTS.md` | Data contract | Defines `World`, `Action`, `Plan`, `VerifyResult`, `AttemptRecord`, `RunResult` JSON shapes; also states the frontend must call `service.run_instruction()` only. |
| `docs/WORKFLOW.md` | Process contract | Branch and PR workflow for backend/frontend responsibilities. |
| `docs/archive/CODEBASE_AUDIT_starter.md` | Historical audit summary | Useful as a record of earlier assumptions, but not a binding source of truth. |

Important gap: `PRD.md`, `PROMPTS.md`, and `Techstack.md` are not present. This should be treated as missing project-level spec artifacts even though the implementation appears to approximate the intended product.

### 2.2 Contract verification for the moved robot_sim equivalent

The file `robot_sim.py` is not present in the repo. The move map described in the task is reflected in the present module layout:
- `gemmabot/simulator.py` contains the simulation engine
- `gemmabot/planner.py` contains `parse_plan`, `ask_api`, `ask_ollama`
- `gemmabot/prompts.py` contains prompt text
- `gemmabot/config.py` contains constants

| Component | Exact signature / found form | Status | Notes |
|---|---|---|---|
| `new_world()` | `new_world() -> dict` in `gemmabot/simulator.py` | Pass | Creates the default world: `{"robot": [0, 0], "dir": "E", "goal": [6, 5], "walls": [...]}` |
| `step(world, action)` | `step(world, action) -> str` in `gemmabot/simulator.py` | Pass | Applies turn or forward movement; returns status strings like `"turned left"`, `"moved forward 3"`, `"blocked at ..."` |
| `reached_goal(world)` | `reached_goal(world) -> bool` | Pass | Compares `world["robot"] == world["goal"]` |
| `render(world)` | `render(world) -> list[str]` | Pass | Produces per-row emoji renderings with `⬜`, `🧱`, `🎯`, and arrow glyphs |
| `parse_plan(text)` | `parse_plan(text) -> tuple[str, list]` | Pass | Extracts JSON from markdown fence or raw text; returns `(thought, actions)` |
| `ask_api(instruction, world, model=None)` | `ask_api(instruction, world, model=None) -> str` | Pass | Calls Google `genai.Client().models.generate_content(...)` |
| `ask_ollama(instruction, world, model=None)` | `ask_ollama(instruction, world, model=None) -> str` | Pass | Calls `ollama.chat(...)` |
| `dry_run(world, actions)` | `dry_run(world: dict[str, Any], actions: list[dict]) -> tuple[bool, str]` | Pass | Deep-copies and simulates actions without mutating the original world |
| `plan_with_repair(...)` | `plan_with_repair(instruction, world, ask, max_tries=3) -> tuple[list[dict] | None, int, list[dict]]` | Pass | Performs repeated repair loops using the original instruction as the prompt anchor |
| `log_run(...)` | `log_run(instruction, backend, actions, attempts, history, latency=None, path="logs/runs.jsonl") -> dict` | Pass | Writes JSONL and scrubs `GEMINI_API_KEY` |
| `load_runs(...)` | `load_runs(path="logs/runs.jsonl") -> list[dict]` | Pass | Reads JSONL safely, skipping bad lines |
| `summarize_run(record)` | `summarize_run(record) -> str` | Pass | Produces a UI-friendly multi-line summary |
| `check_world(world)` | `check_world(world: Any) -> tuple[bool, str]` | Pass | Structural validation plus BFS path reachability |
| `run_instruction(...)` | `run_instruction(instruction: str, world: World, backend: Literal["api", "ollama", "auto"]) -> RunResult` | Not implemented | Stubbed with `NotImplementedError` |

### 2.3 World schema and action syntax verification

The implemented simulator uses the following runtime contract:

- World object:
  ```python
  {
      "robot": [x, y],
      "dir": "N" | "E" | "S" | "W",
      "goal": [x, y],
      "walls": [[x, y], ...],
  }
  ```

- Action syntax:
  ```python
  {"cmd": "forward", "steps": 3}
  {"cmd": "turn_left"}
  {"cmd": "turn_right"}
  ```

- Exact simulator behavior:
  - `turn_left`: rotates 90° counter-clockwise using `DIRS` order
  - `turn_right`: rotates 90° clockwise
  - `forward`: clamps `steps` to an integer between 1 and `SIZE - 1` (`7` for the default grid), then moves one step at a time, stopping on wall or boundary with a `blocked at ...` return string
  - `render(world)`: returns a list of strings for each row in the grid; robot is rendered as an arrow, goal as 🎯, walls as 🧱, empty cells as ⬜

### 2.4 Discrepancies vs expected project contract

| Gap | Evidence | Impact |
|---|---|---|
| Missing project-level spec docs | `PRD.md`, `PROMPTS.md`, `Techstack.md` are absent | Architecture contract is partially inferred rather than explicitly defined |
| `robot_sim.py` is missing | The task states it was intentionally deleted and moved; only new module structure exists | Historical contract names are out of date, but behavior remains in new module names |
| Frontend/backend contract is broken | `app.py` imports `new_world`, `render`, `step`, `reached_goal`, `ask_api`, `ask_ollama`, `parse_plan` directly; architecture doc requires `service.run_instruction()` only | The app is coupled directly to backend internals and is not future-proof |
| Core orchestration layer is stubbed | `gemmabot/service.py`, `verifier.py`, `repair.py`, `world_validation.py` raise `NotImplementedError` | The intended `Propose -> Verify -> Execute` pipeline is incomplete |
| Test suite is incomplete | Several test files are skipped placeholders | No real verification coverage for planner, verifier, repair, or world validation |

---

## 3. Completed Features (Done)

### 3.1 Core simulation engine

Implemented in `gemmabot/simulator.py`:
- 8x8 grid with standard coordinate system `[x, y]`
- cardinal directions `N`, `E`, `S`, `W`
- `new_world()` default map with start at `[0, 0]`, goal at `[6, 5]`, and fixed wall obstacles
- `step(world, action)` movement engine with boundary and obstacle checks
- `reached_goal(world)` success condition
- `render(world)` emoji output for UI display
- `DIRS` and `DELTA` geometry support for rotation and movement

### 3.2 AI model integration

Implemented in `gemmabot/planner.py`:
- `parse_plan()` extracts valid JSON from model replies, including fenced markdown outputs
- `ask_api()` calls the Gemini API via `google-genai`
- `ask_ollama()` calls a local Ollama model
- Unified world-plus-instruction prompt generation in `gemmabot/prompts.py`
- `SYSTEM` prompt defines the exact contract for the model: `{"thought": "...", "actions": [...]}`

### 3.3 Safety and repair harness

Implemented in `gemmabot/harness.py`:
- `dry_run(world, actions)` deep-copies the world before execution, so the live state is never mutated
- returns `(bool, str)` with exact failure reasons on blocked moves, invalid actions, empty plans, exceeding the max plan length, or not reaching the goal
- hard limit `MAX_PLAN_STEPS = 20`
- `plan_with_repair(instruction, world, ask, max_tries=3)` loops through attempts and reconstructs repair prompts anchored to the original instruction
- preserves the original instruction instead of accidentally letting the prompt drift into a long repeated failure chain

### 3.4 Logging subsystem

Implemented in `gemmabot/logger.py`:
- `log_run(...)` appends JSONL entries to `logs/runs.jsonl`
- `load_runs(...)` reads and returns all run records, skipping corrupt lines
- `summarize_run(record)` builds a human-readable status block for UI panels
- secret redaction scrubs any value matching `GEMINI_API_KEY` before writing to disk

### 3.5 Benchmarking and validation

Implemented in `gemmabot/benchmark.py`:
- 5 world scenarios covering default map, one-turn case, several-turn case, detour wall case, and tricky-pocket case
- test matrix compares `max_tries=1` and `max_tries=3`
- supports CLI flags: `--backend`, `--runs`, `--dry`, and `--delay`
- outputs aggregate and per-case benchmark summaries
- writes results to `benchmarks/results.json` and `benchmarks/results.md`

### 3.6 Vision extension (optional but implemented)

Implemented in `gemmabot/map_vision.py`:
- `check_world(world)` validates world structure and performs BFS reachability analysis to ensure the goal is accessible
- `build_map_prompt()` defines the JSON contract for interpreting a hand-drawn map
- `read_map(...)` parses model output, validates the world, and retries on failure
- includes Google and Ollama vision calls

### 3.7 Streamlit UI prototype

Implemented in `app.py`:
- world reset and instruction input
- backend radio selector for API / Ollama / Auto
- display of current robot state through emoji grid rendering
- action-by-action execution loop
- basic log panel for action history
- API and model fallback handling
- caching by `(instruction, world)` tuple

This is a useful prototype and a strong front-end demonstration, but it is not yet the final architecture contract.

---

## 4. Pending Backend Deliverables (Not Done / In Progress)

### 4.1 Status of required files by name

| File / module | Status | Exact status |
|---|---|---|
| `gemmabot/harness.py` | Completed | Exists and implements `dry_run()` and `plan_with_repair()`. It contains a deep-copy safety check, max action guard, and repair loop using the original instruction. |
| `gemmabot/logger.py` | Completed | Exists and implements `log_run()`, `load_runs()`, and `summarize_run()`. It does secret redaction and JSONL persistence. |
| `gemmabot/benchmark.py` | Completed | Exists and contains the 5 required scenarios plus CLI dry-run support and `max_tries` comparison. |
| `gemmabot/map_vision.py` | Completed (with naming difference) | The repo contains `map_vision.py`, not `mapvision.py`; it includes `check_world()` BFS validation. |

### 4.2 Not done: core orchestration and validation chain

The following modules are not implemented and are blocking the intended backend architecture:

- `gemmabot/service.py`
  - Signature exists but currently raises `NotImplementedError`
  - Intended to be the official frontend/backend entrypoint

- `gemmabot/verifier.py`
  - `verify_plan()` is stubbed
  - The architecture implies this should validate a plan against the world and produce a `VerifyResult`

- `gemmabot/repair.py`
  - `repair_plan()` is stubbed
  - The project intends this to repair failed plans using verification feedback

- `gemmabot/world_validation.py`
  - `validate_world()` is stubbed
  - This is a backend gate before planner or verification execution

- `frontend/state.py`
  - `init_session_state` and `reset_world` remain stubs

- `frontend/components.py`
  - `render_board` and `render_action_log` remain stubs

### 4.3 Runtime-API mismatch vs intended architecture

The architecture doc says the frontend should only call:

```python
from gemmabot.service import run_instruction
result = run_instruction(instruction, world, backend)
```

Current reality in `app.py`:

```python
from gemmabot.simulator import new_world, render, step, reached_goal
from gemmabot.planner import ask_api, ask_ollama, parse_plan
```

This is not a clean service layer and bypasses the designed contract.

---

## 5. Technical Debt & Architectural Risks

### 5.1 Missing orchestration contract

The biggest risk is the incomplete backend service layer. The codebase has strong component-level logic, but no single authoritative orchestrator that composes all of the following:
- world validation
- model planning
- verification
- repair loop
- logging
- final result packaging

### 5.2 Hard-coded values and environment assumptions

The project uses several hard-coded constants across modules:
- `SIZE = 8` in `gemmabot/config.py`
- `STEP_DELAY = 0.5`
- `TEMPERATURE = 0.2`
- default models: `gemma-4-26b-a4b-it` and `gemma4:e4b`
- default world layout in `new_world()`

These are acceptable for a prototype, but they reduce flexibility and make the backend harder to generalize or benchmark cleanly.

### 5.3 Missing validation on API configuration

`ask_api()` assumes `GEMINI_API_KEY` is set and valid. There is no explicit guard or friendly error path before calling `genai.Client()`. The logger redacts keys after the fact, but the runtime should fail fast with a clear message when credentials are missing.

### 5.4 Incomplete test coverage

The repository contains placeholder tests in `tests/test_planner_parse.py`, `tests/test_repair.py`, `tests/test_verifier.py`, and `tests/test_world_validation.py` with `@pytest.mark.skip(...)`. That means the actual backend contract remains weakly verified.

The only active test is the simulator smoke check in `tests/test_simulator.py`. This does not cover the planner, verifier, repair, or service layers.

### 5.5 Model-call robustness

The code relies on parsing JSON from free-text model output by searching for `{` and `}`. This works for many responses, but it is brittle and can fail on malformed or noisy model output. The repair loop is present, but the actual service layer should enforce consistent parser/validation feedback and avoid letting invalid output reach the executor.

### 5.6 Lack of execution guardrails around backend selection

`app.py` chooses backend order manually and falls back to local Ollama if the API call fails, but the backend layer is not formalized with shared policy/enforcement. The same issue appears in the service contract: `backend` supports `api`, `ollama`, and `auto` in type hints, but the service itself is not implemented.

### 5.7 Rate-limit and latency risk

`benchmark.py` has a deliberate delay between calls (`--delay`, default 2.0 seconds), which helps avoid rate-limit issues during benchmarking. However, there is no equivalent safety control in the app/service layer for real-user use. A production service should implement per-user throttling and graceful retry-backoff policies.

---

## 6. Frontend Integration Interface (Handoff for Streamlit)

### 6.1 Recommended backend contract the UI should call

The intended contract is the backend service layer:

```python
from gemmabot.service import run_instruction

result = run_instruction(
    instruction="Go to the goal around the walls",
    world=world_state,
    backend="auto",  # "api" | "ollama" | "auto"
)
```

The result should be a `RunResult` dict with the shape defined in `gemmabot/schemas.py`:

```python
{
    "status": "success" | "failed" | "error",
    "instruction": "...",
    "backend_used": "api" | "ollama" | "auto",
    "world_before": {...},
    "world_after": {...},
    "attempts": [...],
    "final_plan": {"thought": "...", "actions": [...]},
    "latency_s": 2.5,
    "error": null | "...",
}
```

### 6.2 Current UI coupling that should be removed

The current app directly imports and executes:
- `new_world`, `render`, `step`, `reached_goal`
- `ask_api`, `ask_ollama`, `parse_plan`

This should be replaced by:
- `world = st.session_state["world"]`
- `result = run_instruction(...)`
- `st.session_state["last_result"] = result`
- `st.session_state["run_history"] = load_runs(...)`

### 6.3 Recommended `st.session_state` keys

The actual UI can be structured cleanly using the following keys:

```python
st.session_state["world"]              # current world dict
st.session_state["instruction"]        # latest user instruction
st.session_state["backend"]            # "api" / "ollama" / "auto"
st.session_state["log"]               # temporary action log (display-only)
st.session_state["cache"]             # optional memoization of identical prompt+world results
st.session_state["last_result"]       # dict returned by run_instruction
st.session_state["run_history"]       # list of JSONL records from logger.load_runs()
st.session_state["repair_history"]    # per-run attempt records for a detailed panel
st.session_state["error"]             # latest user-visible error text
```

The current app already sets `world`, `log`, and `cache`, but the rest of the state model is missing. The frontend should treat `logger.py` and the repair loop as UI data sources, not as direct execution dependencies.

### 6.4 How UI panels should consume logs and repair feedback

The UI should render:
- Board display: from `world_after` or direct `render(world)`
- Execution log: from `result["attempts"]` and the per-attempt `verify`/`reason` details
- Summary panel: from `logger.summarize_run(record)`
- Failure detail panel: from `history[i]["feedback"]` or the final `error` field

Recommended display pattern:

```python
history = st.session_state.get("run_history", [])
for record in history:
    st.markdown(logger.summarize_run(record))
```

If the UI is showing attempt-by-attempt repair data, it should read the `history` entries generated by `plan_with_repair()` rather than trying to parse raw model responses directly.

---

## 7. Actionable Next Steps

### Priority 1 — Backend completion

- [ ] Implement `gemmabot/service.py` as the only official frontend entrypoint.
- [ ] Implement `gemmabot/verifier.py` to turn a plan and world into a `VerifyResult` contract.
- [ ] Implement `gemmabot/repair.py` to produce a corrected plan from failure feedback.
- [ ] Implement `gemmabot/world_validation.py` to validate world dicts before simulation.
- [ ] Unify planner/repair/verification under a single `run_instruction()` orchestration flow.

### Priority 2 — Contract and test hardening

- [ ] Add real unit tests for `parse_plan()`, `dry_run()`, `plan_with_repair()`, `check_world()`, and the service layer.
- [ ] Remove `@pytest.mark.skip` placeholders and add CI gating.
- [ ] Validate the runtime contract against `docs/CONTRACTS.md` and ensure all modules conform to the shared TypedDicts.

### Priority 3 — Frontend decoupling and dashboard handoff

- [ ] Replace direct imports in `app.py` with `gemmabot.service.run_instruction`.
- [ ] Add `frontend/state.py` session state helpers and `frontend/components.py` UI renderers.
- [ ] Separate board rendering, action log rendering, and run-history ingestion into the frontend package.
- [ ] Ensure `st.session_state` holds clean, typed values for world, logs, last result, and history.

### Priority 4 — Runtime robustness

- [ ] Add explicit `GEMINI_API_KEY` and Ollama availability checks before model usage.
- [ ] Add a uniform error envelope for API failures, parse failures, and verification failures.
- [ ] Enforce consistent max-attempt and rate-limit policy across app and benchmark flows.

### Priority 5 — Documentation cleanup

- [ ] Restore or add the missing `PRD.md`, `PROMPTS.md`, and `Techstack.md` spec files.
- [ ] Align naming between `map_vision.py` and any external references to `mapvision.py`.
- [ ] Update README and documentation to reflect the final architecture and service entrypoint.

---

## Final assessment

The codebase has a strong prototype and a credible simulation engine, but it is not yet at the level of a complete backend contract implementation. The project already contains the key nouns of the system (simulator, planner, logger, benchmark, map validation), but several of the orchestration modules and the frontend/backend boundary remain incomplete. The repository should be considered a promising prototype, not a finished productionized backend.
