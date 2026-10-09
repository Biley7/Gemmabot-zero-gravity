# GemmaBot

## Final Pre-Production Audit

**Audit date:** 2026-10-08
**Repository:** `/Users/binayakroy/Gemmabot MLH hackday`
**Branch / HEAD audited:** `main` @ `48e9245` (working tree clean)
**Auditor role:** senior architect / QA / security reviewer / product engineer
**Audit type:** READ-ONLY. No code, UI, architecture, tests, benchmark data, credentials or Git history were modified by this audit. The only file created is this document.

---

## 1. Executive Summary

GemmaBot is a **working single-scope prototype** of the "Gemma proposes, code verifies, the simulator executes" concept, wrapped in a genuinely polished Streamlit laboratory UI. The core safety property it claims is real and unit-tested: plans are simulated on a **deep copy**, verified against four explicit checks, repaired a bounded number of times, and only an accepted plan is ever executed. That part is not a veneer.

Everything *after* the demo route is where the gap is. The system has **no programmatic API**, **no timeout or cancellation on any model call**, **no CI**, **no coverage measurement**, and **documentation that describes an architecture whose six files were all deleted five commits ago** (`gemmabot/service.py`, `verifier.py`, `repair.py`, `world_validation.py`, `frontend/components.py`, `frontend/state.py`). Measured evidence in the repository shows real model runs taking **38 s to 252 s**, which is the single largest production blocker for a timed demo or a pilot.

Two claims from prior in-repo audit documents are no longer accurate and are corrected here (see §14 and §21), and one of them (§21.1, the security CRITICAL) does not survive verification at all.

**Overall readiness: RED.** Blocking issues remain (unbounded model latency, unverified live paths, misleading contracts, no API boundary).

---

## 2. Audit Scope

### 2.1 What was inspected

| Area | Inspected | Method |
|---|---|---|
| Directory tree, tracked files, ignore rules | Yes | `git ls-files`, `find`, `git check-ignore` |
| Git history (all 18 commits, all blobs) | Yes | `git rev-list --all` + per-blob content scan |
| Application entry point and runtime path | Yes | `app.py`, `frontend/panels/engine.py` |
| Backend implementation | Yes | `backend/**`, `gemmabot/**` |
| Frontend / UI | Yes | `frontend/**`, `app.py` |
| Tests | Yes | full suite executed |
| Configuration & environment | Yes | `.env`, `.env.example`, `.gitignore`, `.dockerignore`, `.streamlit/config.toml`, `pytest.ini` |
| Deployment | Yes | `Dockerfile`, `render.yaml`, `runtime.txt` |
| Documentation | Yes | `README.md`, `docs/**`, `RUN_AND_DEPLOY.md`, root audit reports |
| Benchmark artefacts | Yes | `benchmarks/results.json`, `results.md`, `dry_run_output.txt` |
| Run log | Yes | `logs/runs.jsonl` (64 records) |
| Live model calls during the audit | **No** | Not executed — no live verification claim is made |
| Docker image build | **No** | Not built (would require Docker + network install) |
| Browser/visual regression | Partially | See §12.4 evidence note |

### 2.2 Environment actually used

| Item | Value | Evidence |
|---|---|---|
| Python (working) | `3.14.7` at `/usr/local/bin/python3.14` | `streamlit` 1.65.0, `pytest` 9.1.1 present |
| Python declared | `runtime.txt` → `python-3.11.9`; `Dockerfile` → `python:3.11-slim` | version drift (see §15.4) |
| Bundled `.venv` | Python **3.9.6**, **no Streamlit installed** | environment trap for a new developer |
| Lint tooling | **none** — `pyflakes`/`ruff` not installed | `python -m pyflakes` → `No module named pyflakes` |

### 2.3 Explicit limitations of this audit

- No live Gemini/Ollama success was produced during the audit. All "live" statements are read from historical records in `logs/runs.jsonl` and are labelled as such.
- No Docker image was built; Docker findings are static review only.
- Screenshot capture of the running UI is not available in this environment; UI/UX findings use DOM geometry, accessibility-tree reads, and computed-style measurement (see §12.4).
- One tracked file is non-UTF-8 (`benchmarks/dry_run_output.txt`) and was excluded from text secret scanning; it is a benchmark console dump, and it is excluded from the Docker build context.

---

## 3. Current Architecture

### 3.1 Actual package layout (files that exist)

```
app.py                              1428 lines   Streamlit entry point + session state
engine.py                            23 lines    compatibility shim -> frontend/panels/engine.py
ui_helpers.py                         9 lines    compatibility shim -> frontend/simulation/ui_helpers.py

backend/                                          9 files, 1980 lines
  planner/planner.py                              ask_api, ask_ollama, parse_plan
  verifier/harness.py                             verify_plan, dry_run, plan_with_repair
  logger/logger.py                                log_run, load_runs, summarize_run (+ redaction)
  vision/map_vision.py                            check_world, check_world_report, read_map, ask_vision_*

frontend/                                        22 files, 6395 lines
  panels/engine.py                                backend selection, run_plan, run_map_vision, execute
  panels/{brain,safety,vision,replay,benchmark}.py the five lab panels
  components/{colors,spacing,typography,theme,animations,components,blocks}.py  design system
  simulation/{ui_helpers,player,player_view}.py   grid + animation player
  state/__init__.py                               EMPTY (docstring only)
  animations/__init__.py                          EMPTY (docstring only)

gemmabot/                                        10 files, 691 lines
  config.py, simulator.py, prompts.py, benchmark.py          real
  planner.py, harness.py, logger.py, map_vision.py            3-9 line re-export shims
  schemas.py                                                   DEAD (imported by nothing)

tests/                                           19 files, 5293 lines
```

### 3.2 Layering as actually built

- **Separation is real where it matters most:** `frontend/panels/engine.py` documents and honours "No Streamlit import here — this module is pure Python and unit-testable" (`frontend/panels/engine.py:3-4`). It has 44 dedicated tests.
- **`backend/` holds the logic**, `gemmabot/` keeps thin compatibility shims for the original import paths, and `frontend/` renders.
- **There is no service/API boundary.** The runtime path is `app.py → frontend/panels/engine.py → backend.verifier.harness`. This is *sound design* but it is **not** the architecture the docs describe.
- **No `__init__.py` exports an SDK-style surface**; consumers would import module functions directly (`gemmabot.simulator.step`, `backend.verifier.harness.verify_plan`).

### 3.3 Architecture findings

| Finding | Severity | Evidence |
|---|---|---|
| `gemmabot/schemas.py` is **dead code that contradicts runtime** | MEDIUM | 6 `TypedDict`s (`World`, `Action`, `Plan`, `VerifyResult`, `AttemptRecord`, `RunResult`); `grep -rn "schemas\|VerifyResult\|RunResult\|AttemptRecord"` finds **zero importers**. Its `VerifyResult` (`reached_goal`, `failed_at_index`, `final_state`, `trace`) and `RunResult` (`world_before`, `world_after`, `latency_s`) describe shapes that **do not exist**: the real `verify_plan` returns `{"ok","reason","checks"}`. |
| `frontend/state/` and `frontend/animations/` are **empty packages** | LOW | 1-line docstring `__init__.py` in both; no modules. "Canonical state" lives in `app.py` session state, not here. |
| Six compatibility shims (4 in `gemmabot/`, plus root `engine.py` 23 lines and `ui_helpers.py` 9 lines) | LOW | Re-export only; duplicated public-surface lists that can drift from the real modules. |
| `backend.verifier.harness` imports `gemmabot.simulator`, `backend` imports `gemmabot` | LOW | A circular-looking dependency direction (`backend → gemmabot shims → backend`) that works only because the shims are re-exports. |

---

## 4. Actual Runtime Flow

Traced in code, not from documentation.

```
USER INPUT (app.py instruction textbox / uploaded image / sidebar map picker)
  │
  ├─ app.py: st.button("Run plan")  [shortcut Mod+Enter]
  │    run_world = copy.deepcopy(st.session_state.world)          # captured for logging
  │    with st.spinner("Asking <backend> — the loop streams above"):
  │        engine.run_plan(instruction, run_world, backend, max_tries, on_attempt=cb)
  │            │
  │            ├─ copy.deepcopy(world)               # engine.run_plan — never mutates caller
  │            ├─ get_ask(backend)                   # api | local(ollama) | auto | dry
  │            │     auto → api_fn first; ANY exception → local_fn   (no timeout)
  │            └─ harness.plan_with_repair(instruction, world, ask, max_tries, on_attempt)
  │                  for attempt in 1..max_tries:
  │                      reply   = ask(instruction, world)        # MODEL CALL (unbounded)
  │                      actions = _parse_plan(reply)             # JSON in a fence-tolerant scan
  │                      ok, reason = dry_run(world, actions)     # → verify_plan → _walk
  │                      on_attempt(record)                       # live UI stream
  │                      if ok: return actions
  │                      instruction = _repair_prompt(ORIGINAL, plan, reason)   # no prompt growth
  │                  return None, max_tries, history              # nothing executable
  │
  ├─ VERIFICATION (inside dry_run → verify_plan)
  │    _input_guard  → dict / required keys / heading / actions-is-list
  │    _scan         → is EVERY action a simulator command?  (whole plan, no simulation)
  │    len == 0      → empty-plan branch
  │    len > 20      → MAX_PLAN_STEPS reject
  │    _walk         → copy.deepcopy(world) + real simulator.step() per action
  │                     checks: valid_actions · in_bounds · no_collisions · goal_reachable
  │
  ├─ GATE:  if result["actions"] is not None:            # app.py:~586
  │            playback.build_timeline(session world, actions)
  │                └→ engine.execute(world, actions, on_step)   # deep copy again
  │            st.session_state.world = replay["final_world"]
  │            st.session_state.replay = replay  (player_view iframe, autoplay once)
  │
  ├─ SIMULATOR: gemmabot/simulator.py step()  — 8×8, DIRS N/E/S/W, walls, goal
  │
  ├─ RESULT: panels/brain.py telemetry, panels/safety.py, panels/replay.py player
  │
  └─ LOGGING: backend/logger/logger.py log_run(..., world=run_world, mode=backend_mode(backend))
                deep-copies actions + world, redacts GEMINI_API_KEY from all string leaves
```

**Vision path** is structurally identical with `map_vision.read_map` + `check_world_report` (3 checks) replacing `plan_with_repair` + `verify_plan` (4 checks).

---

## 5. Feature Completion Matrix

Status vocabulary: **IMPLEMENTED** · **PARTIALLY IMPLEMENTED** · **PLACEHOLDER/STUB** · **DOCUMENTED BUT NOT IMPLEMENTED** · **TESTED** · **NOT TESTED** · **BROKEN** · **UNKNOWN**

| # | Capability | Status | Evidence | Tests | Notes |
|---|---|---|---|---|---|
| 1 | Natural-language robot instructions | IMPLEMENTED + TESTED | `app.py` instruction textbox; `prompts.world_prompt(world, instruction)` | `tests/test_app_smoke.py` | Works with any backend |
| 2 | AI-generated action plans | IMPLEMENTED, **LIVE UNVERIFIED** | `backend/planner/planner.py:ask_api` / `ask_ollama`; `harness._parse_plan` | `tests/test_engine.py` (fakes), `tests/test_verifier.py` | No network call made in this audit |
| 3 | Deterministic verification | IMPLEMENTED + TESTED | `backend/verifier/harness.py:verify_plan`, 4 checks | `tests/test_verifier.py` — 22 tests | Strongest part of the system |
| 4 | Dry-run simulation before execution | IMPLEMENTED + TESTED | `harness._walk` deep-copies; `harness.dry_run` wraps `verify_plan` | `test_verify_plan_never_mutates_the_world`, `test_dry_run_and_verify_plan_agree_on_every_case` | Verifier and executor share `step()` |
| 5 | Automatic repair of invalid plans | IMPLEMENTED + TESTED | `harness.plan_with_repair` + `_repair_prompt` | `tests/test_verifier.py` | Prompt rebased on the original instruction each attempt |
| 6 | Bounded retries | IMPLEMENTED + TESTED | `max_tries` in `plan_with_repair`; sidebar "Max tries" 1–5 | `test_...` in `test_verifier.py`, `test_engine.py` | Hard cap, returns `None` when exhausted |
| 7 | Robot simulation | IMPLEMENTED + TESTED | `gemmabot/simulator.py:step/reached_goal/render` | `tests/test_simulator.py` — **only 3 tests** | Covered indirectly by many others |
| 8 | Map / world validation | IMPLEMENTED + TESTED | `backend/vision/map_vision.py:check_world_report` (valid · in_bounds · reachable, BFS) | `tests/test_map_vision.py` — 48 tests | Deterministic, AI-independent |
| 9 | Vision-to-grid mapping | **PARTIALLY IMPLEMENTED**, live path NOT TESTED | `map_vision.read_map`, `ask_vision_api`, `ask_vision_ollama`, `build_map_prompt` | `tests/test_vision.py` (46), `test_map_vision.py` (48) — all scripted | Dry/scripted reader is real pipeline; **no evidence a real image was ever read by a live model** |
| 10 | Logging | IMPLEMENTED + TESTED | `backend/logger/logger.py:log_run/load_runs/summarize_run`; JSONL | `tests/test_logger.py` — 13 tests | Includes API-key redaction on all string leaves |
| 11 | Benchmarking | IMPLEMENTED + TESTED (synthetic only) | `gemmabot/benchmark.py` CLI; `frontend/panels/benchmark.py` | `tests/test_benchmark.py` — 51 tests | Live column legitimately empty; see §10 |
| 12 | Cloud/local model options | IMPLEMENTED, **LIVE UNVERIFIED** | `api` / `local` / `auto` / `dry`; `engine._make_auto_ask` fallback | `tests/test_engine.py` | `auto` falls back on *any* exception — including a timeout-free hang |
| 13 | Transparent verification/execution telemetry | IMPLEMENTED + TESTED | `frontend/panels/brain.py`, `blocks.fact_cards`, `data-state` semantics; unproven shown as `ok=None`, never a pass | `tests/test_brain.py` (25), `test_blocks.py` (34) | Honesty rules are enforced in code |
| 14 | Polished robotics simulation UI | IMPLEMENTED, partially verified | `frontend/components/theme.py` (678 lines), 5 tabs, `player_view.py` iframe player | `tests/test_theme.py` (15), `test_player.py` (19) | See §12 |

**Score: 14 capabilities present, 0 missing. 8 fully tested, 3 implemented-but-live-unverified, 3 implemented with verification gaps.**

---

## 6. Phase Completion Matrix

| Phase (as previously planned) | Claimed | Actual status | Evidence |
|---|---|---|---|
| Foundation — clean architecture, canonical state, UI/backend separation, dead-code removal | Done | **PARTIAL** | `8b11a1f "refactor: clean architecture before UI pass"` deleted the 6-file scaffold (`service.py`, `verifier.py`, `repair.py`, `world_validation.py`, `frontend/components.py`, `frontend/state.py` — 117 lines, all stubs). Separation achieved: `frontend/panels/engine.py` is Streamlit-free. But `schemas.py` is still dead, `frontend/state/` + `frontend/animations/` are empty packages, and the docs were never updated to match the deletion. |
| Design system — tokens, typography, spacing, colours, reusable components | Done | **IMPLEMENTED + TESTED** | `frontend/components/{colors,spacing,typography,animations,theme,components,blocks}.py`; 7 test files reference the design-system modules; 347 token references vs 3 legitimate `0` literals |
| Simulator — 8×8, coordinates, walls, orientation, goal, path, active cell | Done | **IMPLEMENTED + TESTED** | `gemmabot/simulator.py`; `frontend/simulation/ui_helpers.py` grid markup (19 tests) |
| Animation — movement, turning, trail, highlight, play/pause/reset/step/speed | Done | **IMPLEMENTED + TESTED** | `player.py:build_timeline` (pure), `player_view.py` (783 lines, self-contained iframe). Timeline is derived from real `execute()` steps, not staged. |
| Brain panel — model, backend, status, attempts, latency, action count, no hidden CoT | Done | **IMPLEMENTED + TESTED** | `frontend/panels/brain.py` (25 tests). `thought` is parsed and discarded; the panel prints "structured metadata · no chain of thought". |
| Safety Lab — invalid plan, rejection, repair, verification, replay | Done | **IMPLEMENTED + TESTED** | `frontend/panels/safety.py` (27 tests) |
| Vision Lab — upload, processing, extraction, validation, load, stale-state | Done | **PARTIAL** | `frontend/panels/vision.py` (46 tests). Pipeline real; **live model path never exercised**. |
| Run history — persistence, timestamps, model, backend, attempts, result, latency, replay | Done | **PARTIAL** | `logs/runs.jsonl` 64 records, 0 corrupt, 31 replayable. **No run IDs**; 33 legacy records not replayable (no `actions`/`world`). |
| Benchmark Lab — live vs synthetic, metrics, reproducibility, sample size, provenance | Done | **IMPLEMENTED + TESTED (synthetic)** | `frontend/panels/benchmark.py` (907 lines, 51 tests); `benchmarks/results.json` 30 rows all `mode=synthetic`, `backend=dry` |
| SDK / API | Not claimed as done | **DOCUMENTED BUT NOT IMPLEMENTED** | `docs/ARCHITECTURE.md` + `docs/CONTRACTS.md` promise `gemmabot.service.run_instruction()`; `grep` finds no `service.py`. |
| Model agnosticism | Claimed | **PARTIAL** | Backend selection is a real abstraction (`api`/`local`/`auto`/`dry`), but model IDs are Gemma-specific constants in `gemmabot/config.py` and prompts name Gemma; vision has a separate parallel abstraction. |
| Final production polish | Done | **IMPLEMENTED + TESTED** | `85cf80e`, `48e9245`; 424 tests pass |

---

## 7. Backend Audit

| Component | Status | Evidence | Notes |
|---|---|---|---|
| `backend/planner/planner.py` | IMPLEMENTED | `ask_api` (google-genai), `ask_ollama`, `parse_plan` | **`genai.Client()` is constructed on every single call** (line 29). No timeout, no retry policy, no model fallback inside the function. |
| `backend/verifier/harness.py` | IMPLEMENTED + TESTED | `verify_plan`, `dry_run`, `plan_with_repair`, `MAX_PLAN_STEPS=20`, `VALID_COMMANDS` | 687 lines, of which ~200 are an in-module `__main__` self-test |
| `backend/logger/logger.py` | IMPLEMENTED + TESTED | `log_run`, `load_runs`, `summarize_run`, `_redact` | 437 lines; redaction keyed on `GEMINI_API_KEY` env value; skips corrupt lines |
| `backend/vision/map_vision.py` | IMPLEMENTED + TESTED (scripted) | `check_world_report`, `read_map`, `build_map_prompt`, `ask_vision_*` | 777 lines; validation includes type guards, key/shape checks, bounds, wall overlap, robot==goal, BFS reachability |
| Service/orchestration layer | **ABSENT** | no `backend/service.py` | `frontend/panels/engine.py` plays this role for the UI only |
| Structured logging framework | **ABSENT** | `print()` used in `harness.plan_with_repair` (`f"  [attempt {n}/{max_tries}] ..."`) and `map_vision.read_map` | Console noise in production; no log levels |
| Dependency injection | PARTIAL | `ask`/`ask_vision`/`ollama_client` injectable | Good testability; used widely in tests |
| Error handling | GOOD | `run_plan`/`run_map_vision` wrap everything in `except Exception` and return a readable `error` string | Never crashes the UI |

**Duplication found:** `parse_plan` logic exists twice — `backend/planner/planner.py:parse_plan` and `harness.py:_parse_plan` (a private copy). A third variant `_parse_world_json` exists in `map_vision.py`. Three fence-tolerant JSON extractors.

---

## 8. Simulator Audit

`gemmabot/simulator.py` — 60 lines, pure data + `step`.

| Property | Verdict | Evidence |
|---|---|---|
| Grid | 8×8 | `config.SIZE = 8`; imported by simulator, verifier, map_vision, prompts |
| Coordinate system | x = column (east+), y = row (south+) | `DELTA = {"N": (0,-1), "E": (1,0), "S": (0,1), "W": (-1,0)}`; documented in `prompts.SYSTEM` and `build_map_prompt` — **prompt and code agree** |
| Orientation | `DIRS = ["N","E","S","W"]` clockwise | `turn_left` = `index-1 mod 4`, `turn_right` = `index+1 mod 4` |
| Movement | Per-step loop, early return on block | `forward`: `n = max(1, min(int(steps), SIZE-1))` |
| Collision detection | Walls are cells, checked per step | `if [nx,ny] in world["walls"]: return "blocked at ..."` |
| Boundary handling | Rejected, not clamped | `if not (0 <= nx < SIZE and 0 <= ny < SIZE)` |
| Goal detection | Equality on `[x, y]` | `reached_goal(world)` |
| World mutation | **Only when the caller passes its own dict** | `step()` mutates in place by design; every caller deep-copies first |
| Dry-run vs execution semantics | **IDENTICAL** | Both `_walk` (verify) and `engine.execute` (execute) call the same `simulator.step()` on a `copy.deepcopy(world)`. `test_dry_run_and_verify_plan_agree_on_every_case` pins this. |
| **Can a rejected plan alter the live world?** | **NO — verified** | `engine.run_plan` deep-copies before calling the harness; `harness._walk` deep-copies again; `engine.execute` deep-copies third. `test_verify_plan_never_mutates_the_world` and `test_engine.py` `run_plan/execute must not mutate the caller's world` assert it. |

### Semantic quirk worth knowing

`forward` clamps with `max(1, min(int(steps), 7))`. Therefore:

- `{"cmd":"forward","steps":-5}` silently becomes **1 step**, not a rejection.
- `{"cmd":"forward","steps":999}` silently becomes **7 steps**.
- `{"cmd":"forward","steps":"abc"}` raises inside `step()`, and `_walk`'s `try/except` converts it to a `fault` (correctly *not* a pass).

The verifier and executor agree because they share `step()`, so this is **not a safety hole** — but a plan containing a nonsense step count is quietly reinterpreted rather than refused. Recorded as a LOW finding.

---

## 9. Verification / Safety Audit

**Claim under test:** `AI output → parser → verifier → dry run → approval → execution` is enforced, with no bypass.

**Verdict: ENFORCED. No bypass path was found in the UI or the engine.**

| Scenario the audit asks about | Handled? | Evidence |
|---|---|---|
| Invalid action | Yes | `_scan` rejects non-`VALID_COMMANDS`; `test_an_invalid_action_reports_which_action_failed` |
| Malformed plan / non-dict action | Yes | `_scan` + `_walk` `fault` branch; `test_malformed_actions_are_reported_as_invalid` |
| Empty plan | Yes | Dedicated branch: 3 checks pass, `goal_reachable` = true only if already on goal; `test_empty_plan_cannot_reach_the_goal_but_passes_the_other_checks`, `test_empty_plan_on_the_goal_is_accepted` |
| Oversized plan | Yes | `MAX_PLAN_STEPS = 20`; `test_plan_over_the_step_limit_is_rejected` |
| Wall collision | Yes | `blocked` outcome → `no_collisions=False` with cell + action index; `test_a_collision_reports_the_cell_and_action_it_refused`, `test_wall_hit_fails_collisions_and_the_goal_only` |
| Boundary violation | Yes | `test_an_out_of_bounds_move_reports_its_own_cell`, `test_leaving_the_grid_fails_bounds_and_not_collisions` |
| Unreachable goal | Yes | `test_an_unreachable_goal_reports_where_the_robot_stopped`, `test_short_plan_fails_only_the_goal` |
| Invalid robot state / invalid goal | Yes (world validator) | `map_vision._world_findings` covers heading, shapes, bounds, wall overlap, robot==goal |
| A command that raises | Yes | `fault` outcome, never a pass: `test_a_valid_command_that_raises_is_a_fault_not_a_pass` |
| Repeated failures | Yes | `plan_with_repair` returns `None` after `max_tries` |
| Model exception | Yes | `except Exception` around `ask()` → recorded, loop continues |
| Repair exception | Yes | Same guard; no state corruption |
| Max retry count | Yes | `max_tries` hard cap, no off-by-one (`attempts == max_tries` asserted in `test_verifier.py` self-test and `test_engine.py`) |
| **Unproven ≠ pass** | Yes | `_blank_checks` uses `ok=None`; `_pack` requires `is True` for all four. `test_a_passing_result_means_every_check_passed`, `test_an_unproven_check_carries_no_failure_data` |
| Execution gate | Yes | `app.py:~586` only executes when `result["actions"] is not None`; `run_plan` only returns actions that passed `dry_run` |
| Any path that bypasses verification? | **None found** | `app.py` never calls `harness.plan_with_repair` or `simulator.step` directly. `engine.execute` is called only from `frontend/simulation/player.py:build_timeline`, which is reached only after the gate. |

**Test depth:** `tests/test_verifier.py` — 22 tests, all of the above named explicitly. This is the best-covered subsystem in the repository.

**Gap:** there is no test that asserts the *UI* gate (`if result["actions"] is not None`) cannot be removed or inverted. The invariant is structural, not pinned by a test at the `app.py` level.

---

## 10. Vision Audit

Precise separation of what is real, what is mocked, and what is unverified.

| Layer | Status | Evidence |
|---|---|---|
| **Image ingestion** | IMPLEMENTED | `st.file_uploader` (PNG/JPG, 10 MB cap via `.streamlit/config.toml`); a built-in sample PNG is generated from `new_world()` when nothing is uploaded |
| **LIVE VISION (real model)** | **IMPLEMENTED BUT NEVER EXERCISED** | `map_vision.ask_vision_api` (google-genai inline bytes) and `ask_vision_ollama` exist and are wired to `get_vision_ask("api"/"local"/"auto")`. **No evidence in the repository that either was ever called successfully.** No record in `logs/runs.jsonl` has `backend` from a vision run; no test calls them. |
| **MOCKED / SCRIPTED VISION** | IMPLEMENTED + TESTED | `engine.dry_vision_ask` → reply 1 is `DRY_VISION_MISREAD` (goal `[7,8]`, off-grid, a genuine rejection), reply 2 is `new_world()`. The parser, `check_world`, the retry and the simulator load are the real pipeline. Labelled "Scripted (dry mode)" in the UI. |
| **Structured output** | IMPLEMENTED | `build_map_prompt()` — 14 numbered rules, zero-based coordinates, "do not shift coordinates because of image margins", "do not perform pathfinding", "do not modify the map to make it solvable", JSON-only reply |
| **Parsing** | IMPLEMENTED + TESTED | `_parse_world_json` (fence-tolerant, first `{` … last `}`) |
| **World validation** | IMPLEMENTED + TESTED | `check_world_report` → `valid` · `in_bounds` · `reachable` (4-way BFS), with per-check `ok=None` when unproven |
| **Retry behaviour** | IMPLEMENTED + TESTED | `read_map(max_tries=2)`, failure reason appended via `_repair_map_prompt` |
| **Error handling** | IMPLEMENTED | `ask_vision` exception → recorded, retried, then `world=None` with a readable `error` |
| **Simulator loading** | IMPLEMENTED | "Load into simulator" (disabled until validation passes) → `_adopt_world("scanned")` |

**Conclusion:** the vision *pipeline* is genuinely implemented and validated; **real-world vision support must not be claimed**, because no live image→world call has been demonstrated. Score reflects this (§17).

---

## 11. Model / Backend Audit

| Backend | Implemented | Live tested (evidence) | Fallback tested | Notes |
|---|---|---|---|---|
| **Gemini API** (`api`) | Yes — `planner.ask_api`, `map_vision.ask_vision_api` | **Historically yes, not in this audit.** 6 records in `logs/runs.jsonl` with `backend="api"` (2026-10-04 → 10-06): 4 successes, 0 failures, latencies 0.10 s, 0.10 s, 2.41 s ×3, **248.33 s** | N/A (primary) | No timeout. `genai.Client()` re-created per call. Model id from `GEMMA_API_MODEL` (`gemma-4-26b-a4b-it`). |
| **Ollama / local** (`local`) | Yes — `planner.ask_ollama`, `map_vision.ask_vision_ollama` | **Historically yes, not in this audit.** 5 records, `backend="ollama"`: 3 successes, **2 failures after 3 attempts**. Latencies 38.37 s, 102.43 s, 105.38 s, 148.88 s, **251.87 s** | N/A | Model id `OLLAMA_MODEL` (`gemma4:e4b`). Availability on the audit machine: **not verified**. |
| **Auto / fallback** (`auto`) | Yes — `_make_auto_ask` / `_make_auto_vision_ask` | **NOT TESTED live** | Unit-tested with fakes only (`test_engine.py`) | Falls back on *any* exception — which includes the case where the API call would have hung forever. `_used_backend_label` reports which one actually answered. |
| **Scripted planner** (`dry`) | Yes — `engine.dry_ask`, `engine.dry_vision_ask` | Exercised in this audit (dry-mode vision run reproduced the misread → retry → validated load) | N/A | Accurately labelled "Scripted (dry mode)" everywhere |
| **Recorded planner** | **DOES NOT EXIST** | — | — | "Replay" replays *plans* through the simulator; it does **not** replay model replies |

### Measured latency — the honest picture

All 64 latencies in `logs/runs.jsonl`:

- min `1.33e-05 s`, median `5.95e-05 s`, max `251.87 s`.
- The median is meaningless for performance: **53 of 64 records are scripted** (dry/preview/dry_model).
- The **11 model-backed records** measure `0.10 s → 251.87 s`.

> **Do not use the checked-in benchmark numbers to claim live performance.** `benchmarks/results.json` is 30 rows, every one `mode=synthetic`, `backend=dry`, avg latency `0.000 s`, and `benchmarks/results.md` states this in a block quote: *"Synthetic runs only. Every row below was answered by the scripted reader (`--dry`), not by a model."* That labelling is correct and must be preserved.

---

## 12. UI / UX Audit

### 12.1 Information architecture

Five tabs, rendered from `app.py:495` `st.tabs(tab_names)`:

| Tab | Panel title | Answers |
|---|---|---|
| Text command | "⬛ Text command · Default world (new_world())" | What does the robot do? |
| Safety Lab | `DS.panel(..., title="Safety lab")` | What happens when the plan is wrong? |
| Vision Lab | `DS.panel(...)` with stages | How does an image become a world? |
| Replay | `DS.panel(body, title="Replay")` | What happened last time? |
| Benchmark | `DS.panel(body, title="Benchmark Lab")` | How does the loop behave over many runs? |

**Can a new user understand within ~10 seconds?** Partially.

- **What GemmaBot does** — yes. Title, "Propose Verify Execute" strip, and a world grid are visible immediately.
- **What the AI does** — yes, but only after reading the Brain panel's caption (`structured metadata · no chain of thought`) or the page-level captions.
- **What GemmaBot verifies** — yes, the four checklist labels (`Valid actions`, `In bounds`, `No collisions`, `Goal reachable`) are on the first tab.
- **When the robot is allowed to execute** — **weak.** This is the product's core promise and it is explained in *tooltips and captions*, not in the primary visual hierarchy. There is no persistent "verified before executing" indicator at the top level.
- **What happened during the last run** — yes, sidebar LAST RUN + the player.

**Verdict:** needs one line of prose before the tabs that states the contract ("nothing moves until code verifies it"). That is a *recommendation*, not a defect.

### 12.2 Visual design

Evidence: `frontend/components/theme.py` (678 lines of CSS), `colors.py`, `spacing.py`, `typography.py`, `animations.py`; measured live: **20,588 bytes** of injected CSS, 245 `S.px(` token calls, 347 typography/spacing token references, **3** remaining numeric literals in panels (all `padding:0 <token>`, i.e. legitimate zeros).

| Aspect | Finding |
|---|---|
| Hierarchy | Clear: panel titles → stage/section labels → mono telemetry → muted definitions |
| Typography | Two families used deliberately: mono for telemetry/numbers/keys, sans for prose. `text-transform:uppercase` on labels |
| Spacing | Token-driven (`S.XS…S.XL`), consistent gaps inside cards |
| Colour | Dark control-room palette; `data-state` drives success/warning/error/neutral so a state means the same colour in all labs |
| Borders / shadows | Subtle 1px borders, minimal shadow use — reads as instrumentation, not SaaS |
| Icons | Material symbols (`keyboard_arrow_right`, `upload`) + emoji legends; slightly mixed |
| Density | Dense but readable; `gb-scroll-x` prevents squeeze |
| **Simulator prominence** | The world grid is on the first tab and in the player, but the *player* (the animation) is the most prominent element while the verification checklist is smaller. Arguably inverted for a "verification-first" product. |

**What does it look like?** Primary classification: **simulation / robotics tooling with a developer-tool density**, not generic AI SaaS and not a hackathon prototype. Reasons: mono telemetry readouts, explicit check states with `ok=None` "not evaluated" (rather than green ticks), a trace-style event list, speed controls, and a dark instrumentation palette. The one place it slips toward "game" is the emoji legend (🤖🎯🧱) — charming at prototype scale, limiting at product scale.

### 12.3 UX states

| State | Implemented | Evidence |
|---|---|---|
| Initial | Yes | Empty states via shared `blocks.empty_state`; sidebar "No run in this session yet. / Run plan fills this in." |
| Loading | Yes | `st.spinner(f"Asking {label} — the loop streams above")` around `engine.run_plan`; `st.spinner("Verifying plans and repairing failures…")`; `st.spinner("Gemma Vision is reading the map…")` |
| Thinking | Yes | `brain.py` status chip: "Thinking / attempt 1/3 — asking the model", attempts `0 / 3` |
| Verification | Yes | Per-check rows with ✓/✕/– and `not evaluated` details |
| Repair | Yes | Attempt cards from `on_attempt` records; repair rate metric |
| Executing | Yes | Player autoplay, step rows, trace path, progress bar, `gb-step-dot err` on a halted step |
| Success | Yes | On-goal end state + success-rate readout |
| Failure | Yes | Blocked/fault reason with cell + action index; `data-state='error'` |
| Empty | Yes | 7 `empty_state()` call sites, 4 distinct messages, one implementation |
| Error | Yes | `st.warning` / `st.error` for read failures and missing input, styled via `[data-testid="stAlert"]` |
| Reset | Yes | "Reset world" re-adopts the map and clears results |
| Map change | Yes | Sidebar map picker → `_adopt_world()` clears `logs`, `text_result`, `replay`, `last_run`, `safety_result`, `safety_autoplay` |
| Replay | Yes | `player_view` iframe, autoplay once (`replay_autoplay = True`) so a rerun does not silently replay |

**Stale/misleading information:** one class remains and is *by design*: the Vision Lab keeps a validated reading when the simulator's map changes, because the reading is about the uploaded image, not the map. `vision_loaded` is derived (`name == "scanned"`) rather than remembered. This is defensible but should be stated in UI copy.

### 12.4 Evidence note on visual verification

Live DOM verification was performed against this same UI code during the final-polish phase (commit `85cf80e`; `48e9245` changed only a test file):

- 5 tabs present and switchable; 7 `st.button`s; all 7 and all 3 sidebar widgets carry tooltips.
- Keyboard focus: the theme's `:focus-visible` rule **is** in the live CSSOM with `!important`, and applying its declarations yields `solid 2px rgb(74,143,255)` with `2px` offset on a real button.
- Responsive: at **420 px** the document does not scroll sideways, zero elements overflow the viewport, and all wide content (760 px Replay rows, 640 px Benchmark cells) sits inside working `.gb-scroll-x` scrollers. At **1440 px** LIVE/SYNTHETIC columns render side-by-side at equal width.
- **Screenshots could not be captured in this environment**, so no pixel-level regression evidence exists. Any "looks right" claim beyond geometry is unverified.

---

## 13. Animation Audit

| Requirement | Status | Evidence |
|---|---|---|
| Cell-to-cell movement | IMPLEMENTED | `player.py:build_timeline` derives per-step position changes; `player_view.py` animates the robot element |
| Robot turning | IMPLEMENTED | Direction changes captured per step; arrow glyph from `simulator.ARROW` |
| Path trail | IMPLEMENTED | `<svg class='gb-trace' id='gb-trace'>` with `--gb-trace-len` |
| Action highlighting | IMPLEMENTED | `.gb-step` rows with `data-step='N'`; active row `.gb-step.active`; halted step `gb-step-dot err` |
| Play | IMPLEMENTED | `#gb-play` button |
| Pause | IMPLEMENTED | Same transport control toggles; `#gb-stepnow` readout |
| Reset | IMPLEMENTED | `#gb-reset` |
| Step mode | IMPLEMENTED | Step rows are addressable; `window.__TL__` timeline drives each step |
| Speed controls | IMPLEMENTED | `_speed_buttons_html(speed)` — a `role="group"` labelled "Playback speed" (0.5×/1×/2×/4×) |
| Reduced motion | IMPLEMENTED | Theme ships a `prefers-reduced-motion` block (animation/transition neutralised); `player_view.py` honours it for its own CSS transitions too |
| **Is it actually used by the UI?** | **Yes** | `player_html` is rendered through `st.components.v1.html`; measured live, `.gb-step` rows and `window.__TL__` are present in the DOM, and a real dry-mode run produced a genuine 2-attempt execution timeline |

**Rendering honesty:** the timeline is produced by `engine.execute()` on a deep copy and captured via `on_step`; every cell, turn and message is a real `simulator.step` result. `player.py` docstring states "The caller's world is never mutated". Nothing is staged for the animation.

**Limit:** the player renders inside an iframe (separate document), so the main page's design system does not reach it and it duplicates a CSS layer (`_css(cs)` in `player_view.py`). Accessibility of the iframe's internal controls is not asserted by any test.

---

## 14. Security Audit

### 14.1 Credential exposure — the definitive finding

**Instruction-mandated check: is a real credential present anywhere in the repository / history / build context?**

| Question | Answer | Evidence |
|---|---|---|
| Is there a live-looking key on disk? | **Yes** — `GEMINI_API_KEY` in `.env`, 53 characters, Google `AQ.`-style format | `sed 's/=.*/=<redacted>/' .env` |
| Is `.env` tracked? | **No** | `git check-ignore -v .env` → `.gitignore:1:.env` |
| Has `.env` **ever** been committed? | **No** | `git rev-list --all --objects \| grep -E "(^\|/)\.env$"` → empty; all 18 commits × all blobs scanned |
| Does the current `.env` value appear in any commit? | **No** | Verbatim search of every text blob across every commit: `NONE` |
| Any `AIza…` / `sk-…` credential in history? | **No** | Pattern scan of every text blob: `NONE` |
| Does `.env.example` contain a key? | **No** | Before `083e652`: `GEMINI_API_KEY=` (empty). After: `your_api_key_here`. Delta is 1 line. |
| Is `.env` excluded from the Docker build context? | **Yes** | `.dockerignore` has `.env` and `.streamlit/secrets.toml` under "Secrets — NEVER bake these into an image" |
| Could Docker copy it anyway? | **No** | `COPY --chown=app:app . .` respects `.dockerignore` |

**Conclusion:** the repository, its full history, and its image build context are **clean of credentials**. The key exists only in the untracked local `.env`.

**Residual actions (recommended, not performed):**

1. **If this directory has ever been zipped, shared, screen-shared, or uploaded anywhere, then: credential detected — treat as compromised and rotate.** The conservative posture costs one key rotation; the alternative is a leaked billing identity.
2. **Secret scanners tuned to the `AIza` prefix will not match a 53-character `AQ.`-style key.** Any "no secrets found" conclusion drawn from an `AIza`-only pattern is unsound. Add the `AQ\.[A-Za-z0-9_\-]{20,}` shape to whatever scanner is used.
3. `.gitignore` ignores the exact name `.env` only. `.env.local`, `.env.production`, `.env.*` are **not** ignored and would be committed silently. Add `.env*` with `!.env.example`.

### 14.2 Injection / dangerous constructs

| Check | Result | Evidence |
|---|---|---|
| `eval()` | **0 occurrences** | repo-wide grep |
| `exec()` | **0 occurrences** | repo-wide grep |
| `subprocess` / `os.system` / `os.popen` / `shell=True` | **0 occurrences** | repo-wide grep (source and tests) |
| `pickle` / unsafe deserialisation | none found | — |
| `unsafe_allow_html=True` | **59 sites** | All render strings built with the shared escaper (`blocks._e` / `html.escape`); 12 escape definition/use sites |
| Raw `<script>` sink | **1 site** — `player_view.py:781` | Payload is `json.dumps(...).replace("</", "<\\/")` — the correct `</script>` breakout mitigation, and the payload derives from simulator output |
| SQL / template injection | not applicable | no database, no templating engine |
| File uploads | bounded | Streamlit `maxUploadSize = 10` MB; PNG/JPG; bytes passed to the model only in live mode |
| Path traversal | not found | Only fixed paths (`logs/runs.jsonl`, `benchmarks/results.{json,md}`) |

### 14.3 Error messages / logs and secret leakage

- `backend/logger/logger.py:_redact` replaces any string leaf containing the `GEMINI_API_KEY` value before writing to disk **and** in `summarize_run`. Verified by `tests/test_logger.py` (13 tests).
- `engine.check_connections` returns only booleans (`api_key_set`, `ollama_reachable`) and a model-name list — never the key.
- `planner.ask_api` relies on ambient `GEMINI_API_KEY`; a raised SDK error could embed request details. Not observed, but there is **no outbound redaction on exception text** shown in the UI (`run_plan` stores `f"{type(exc).__name__}: {exc}"` into `error`, displayed in the panel). **MEDIUM.**

### 14.4 Deployment security

| Item | Status | Evidence |
|---|---|---|
| Runs as non-root | Yes | `RUN useradd --create-home --shell /bin/bash app` … `USER app` |
| Multi-stage build | Yes | `python:3.11-slim` builder → slim runner |
| Health check | Yes | `HEALTHCHECK` against `/_stcore/health` |
| Secrets in image | No | `.dockerignore` |
| **Authentication on the app** | **ABSENT** | Any visitor reaching the port gets the full app. No login, no token, no allow-list. |
| **CORS** | **Disabled** (`enableCORS = false`) and Streamlit itself warns: *"Streamlit also accepts a WebSocket connection from any origin"* | Observed in server stderr at startup |
| Rate limiting / cost controls | **ABSENT** | A public deploy allows unbounded model spend per click |
| Dependency integrity | **ABSENT** | No lock file, no hashes, no scanning |

**Security verdict: no credential leak and no dangerous constructs, but the deployed surface is unauthenticated, CORS-open and unmetered.** For a public URL that spends money per request, that is the dominant risk after latency.

---

## 15. Dependency / Build Audit

### 15.1 Declared dependencies

`requirements.txt` (pinned):

```
google-genai==2.28.0
python-dotenv==1.2.4
streamlit==1.65.0
ollama==0.6.3
pytest==9.1.1        # dev/test only, despite living in the runtime file
```

| Finding | Severity | Evidence |
|---|---|---|
| No lock file, no hashes | MEDIUM | Only `requirements.txt`; `pip` resolves transitively at build time |
| `pytest` in the production requirements | LOW | `.dockerignore` excludes `tests/`, so the image installs a test runner it cannot use |
| Unused dependency? | None found | `google-genai`, `ollama`, `python-dotenv` are all imported; `streamlit` is the UI |
| Missing dependency? | None found | Full suite imports cleanly under 3.14.7 |

### 15.2 Reproducibility for a new developer

| Step | Works? | Evidence |
|---|---|---|
| Clone + `pip install -r requirements.txt` | **Probably** | All pins available; not re-verified in a clean venv during this audit |
| `streamlit run app.py` | **Yes** | Server started and served `/_stcore/health` → 200 during the final-polish phase |
| `pytest` | **Yes** | 424 passed / 3 skipped, exit 0, 1.85 s |
| Follow `RUN_AND_DEPLOY.md` §2.4 | **NO — broken** | `python3 -m gemmabot.harness` **prints nothing and exits 0** (verified). The documented "verify the pipeline without an API key" step is a silent no-op because `gemmabot/harness.py` is a 3-line re-export and the `__main__` self-test lives in `backend/verifier/harness.py`. The real command works and prints "All tests passed." |

### 15.3 Version drift (a real trap)

| Source | Python |
|---|---|
| `runtime.txt` | `3.11.9` |
| `Dockerfile` | `python:3.11-slim` |
| `RUN_AND_DEPLOY.md` | "3.11+ (tested on 3.11 and 3.14)" |
| Working environment used for this audit | `3.14.7` |
| Bundled `.venv` | **`3.9.6` — has no Streamlit** |

A developer who activates the committed `.venv` gets an environment in which the app cannot start. `.venv/` is gitignored, so this is a local-machine trap rather than a repository defect, but it is worth documenting explicitly.

### 15.4 Docker runtime

Not built during this audit. Static review: entrypoint sets `--server.port=8501 --server.address=0.0.0.0 --server.headless=true --server.fileWatcherType=none`; `logs`, `benchmarks`, `assets` are created and chowned; EXPOSE 8501 matches. `render.yaml` points at the Dockerfile with `healthCheckPath: /_stcore/health` and `GEMINI_API_KEY` marked `sync: false` (set in dashboard). Internally consistent.

---

## 16. Testing Audit

### 16.1 Exact results

Command: `/usr/local/bin/python3.14 -m pytest -q -rs`

```
SKIPPED [1] tests/test_planner_parse.py:5: not implemented yet
SKIPPED [1] tests/test_repair.py:5:         not implemented yet
SKIPPED [1] tests/test_world_validation.py:5: not implemented yet
424 passed, 3 skipped in 1.85s          exit status: 0
427 tests collected
```

| Metric | Value |
|---|---|
| Passed | **424** |
| Failed | **0** |
| Errors | **0** |
| Skipped | **3** |
| Collected | 427 |
| Wall time | 1.85 s |
| Network calls made by the suite | **0** (verified: no test imports or invokes a live client) |

### 16.2 The 3 skips are not environmental

They are **unimplemented placeholders**:

```python
# tests/test_planner_parse.py, tests/test_repair.py, tests/test_world_validation.py
@pytest.mark.skip(reason="not implemented yet")
def test_....():
    assert True
```

**Three test files carry names implying coverage of planner parsing, repair and world validation, and assert nothing.** Their filenames must not be counted as validation of anything. (Real coverage for those areas lives elsewhere — `tests/test_verifier.py` covers repair and parsing indirectly, `tests/test_map_vision.py` covers world validation — but the *named* files are empty shells.)

### 16.3 Per-file distribution

| File | Tests | Category |
|---|---|---|
| `test_benchmark.py` | 51 | UNIT |
| `test_map_vision.py` | 48 | UNIT |
| `test_vision.py` | 46 | UNIT (panel rendering) |
| `test_engine.py` | 44 | UNIT (fakes; no network) |
| `test_replay.py` | 42 | UNIT |
| `test_blocks.py` | 34 | UNIT (HTML/CSS strings) |
| `test_safety.py` | 27 | UNIT |
| `test_brain.py` | 25 | UNIT |
| `test_verifier.py` | 22 | UNIT (safety-critical) |
| `test_ui_helpers.py` | 19 | UNIT |
| `test_player.py` | 19 | UNIT |
| `test_app_smoke.py` | 16 | **INTEGRATION/E2E** (Streamlit `AppTest` runs the real `app.py` headlessly, backends patched) |
| `test_theme.py` | 15 | UNIT (CSS) |
| `test_logger.py` | 13 | UNIT |
| `test_simulator.py` | **3** | UNIT |
| `test_planner_parse.py` / `test_repair.py` / `test_world_validation.py` | 1 each | **PLACEHOLDER (skipped)** |

### 16.4 Categorization (UNIT / INTEGRATION / END-TO-END / MOCKED / LIVE)

| Category | Count | Files | What it means here |
|---|---|---|---|
| **UNIT** | **408** | 14 files (`benchmark` 51, `map_vision` 48, `vision` 46, `engine` 44, `replay` 42, `blocks` 34, `safety` 27, `brain` 25, `verifier` 22, `ui_helpers` 19, `player` 19, `theme` 15, `logger` 13, `simulator` 3) | Pure functions and HTML/CSS string assertions. No Streamlit server, no network. |
| **INTEGRATION** | **16** | `test_app_smoke.py` (408 + 16 = 424 passed) | Drives the real `app.py` headlessly through Streamlit's `AppTest` (widgets wiring, session state, tabs, stale-state clearing, shortcuts, tooltips, theme injection). |
| **END-TO-END** | **0** | — | No test exercises a full user journey *including* a model backend, a browser, or the Docker image. `test_app_smoke.py` is the closest thing but every backend is patched. |
| **MOCKED** | **424 (every test that could reach a model)** | all files | Every test that touches a model uses fakes, scripted readers or injected callables: `engine.dry_ask`/`dry_vision_ask`, `monkeypatch`-ed `ask_api`/`ask_ollama`/`run_plan`, and `no_model` fixtures that raise if a model is reached. `tests/test_engine.py` (44) and `tests/test_vision.py` (46) are explicitly built this way. |
| **LIVE** | **0** | — | **No test performs a real network, model or Docker call.** Verified: no test file invokes a live client; the strings `api`/`ollama` in `test_benchmark.py` are log-record *data*, not calls. |

> The distinction that matters for production: **100 % of the suite is mocked, and 0 % is live.** The suite proves the loop and the verifier are self-consistent and honest; it proves nothing about a real model, a real image, or a real container.

### 16.5 Coverage gaps (important functionality with no test)

| Untested area | Risk |
|---|---|
| **Live model integration** (api / ollama / auto, text and vision) | HIGH — the product's core promise |
| **`Dockerfile` build + run** | HIGH — the deployment artifact is never exercised |
| **The `app.py` execution gate** (`if result["actions"] is not None`) | MEDIUM — the safety invariant is structural, not pinned |
| **Simulator `step()` edge cases** | MEDIUM — only 3 direct tests through `test_simulator.py` |
| **Animation semantics** (timing, trail geometry, speed changes) | MEDIUM — the player's JS is not unit-testable and never tested |
| **Vision with a real image** | HIGH |
| **Concurrent sessions / session-state isolation** | MEDIUM |
| **Load / stress** | LOW at current scope |

### 16.6 No CI

`ls -a` for `conftest.py`, `.github/`, `.gitlab-ci.yml`, `.circleci/`, `tox.ini`, `Makefile`, `.pre-commit-config.yaml` → **none exist**. The suite only runs when a human runs it.

---

## 17. Performance Audit

| Area | Finding | Evidence | Severity |
|---|---|---|---|
| **Model latency** | **Unbounded and highly variable.** Measured model-backed runs span **0.10 s → 251.87 s** (4 min 12 s). One observed live run in this project's own history hung in "Thinking" for several minutes with no resolution. | `logs/runs.jsonl` (11 model-backed records) | **CRITICAL** |
| **No timeout anywhere** | `genai.Client()` and `ollama.chat()` are called with no timeout; `auto` fallback triggers only on an *exception*, so a hang never falls back | `backend/planner/planner.py:29,42`; `map_vision.py:545,605`; `engine._make_auto_ask` | **CRITICAL** |
| **No cancellation** | Once `Run plan` is pressed, the Streamlit run thread is blocked. There is no cancel/abort control. | `app.py` spinner block around `engine.run_plan` | **CRITICAL** |
| **Client re-creation** | A new `genai.Client()` per call — extra TLS/handshake work on every attempt | `planner.py:29`, `map_vision.py:545` | MEDIUM |
| **Blocking UI** | All model calls are synchronous on the script run thread. Spinner is the only feedback; the page cannot be interacted with mid-run | `app.py` | HIGH |
| **Repeated model calls** | `max_tries` (default 3, UI max 5) means up to 3–5 sequential model calls per click, each unbounded | `harness.plan_with_repair` | HIGH |
| **Benchmark execution** | Synthetic runs are instant; a live benchmark matrix would multiply the above by (cases × settings × runs) | `gemmabot/benchmark.py` | HIGH |
| **Image processing** | No in-app image processing — bytes are forwarded to the model as-is; 10 MB cap | `.streamlit/config.toml` | LOW |
| **Logging overhead** | Negligible: append-only JSONL, deep copy per run, in-memory redaction. UI caps the log at `LOG_LINE_CAP = 200` lines | `app.py` | LOW |
| **Unnecessary computation** | `verify_run` re-runs `verify_plan` on the accepted plan after the harness already verified it — a cheap, deliberate re-render for telemetry | `engine.verify_run` | LOW |
| **Cold start** | Streamlit boot + 20 KB CSS injection + 8×8 grid render; measured responsive in the final-polish phase | prior measurement | LOW |

**Production bottleneck, ranked:** the unbounded, uncancellable, synchronous model call. Nothing else is close.

---

## 18. Documentation Audit

| Document | Verdict | Evidence |
|---|---|---|
| `README.md` (42 lines) | **ACCURATE BUT MINIMAL** | Setup/run/test instructions match reality. Does not mention the five labs, replay, benchmark, Docker, or the honesty model. Retains the two-team "BACKEND/FRONTEND ownership" framing. |
| `docs/ARCHITECTURE.md` (44 lines) | **MISLEADING / OUTDATED** | Data flow `World -> world_validation -> planner -> verifier -> repair -> logger -> RunResult` is **not the runtime path** — those modules were 16–25-line stubs. File table lists `gemmabot/world_validation.py`, `verifier.py`, `repair.py`, `service.py`, `frontend/components.py`, `frontend/state.py` — **six paths deleted in `8b11a1f` `(2026-10-05)`** which these docs were never updated to drop. States "The frontend calls ONLY `service.run_instruction(...)` and must not import planner, verifier, repair, or logger directly" — `service.py` is absent and `frontend/panels/engine.py` imports `backend.verifier.harness` directly. |
| `docs/CONTRACTS.md` (131 lines) | **MISLEADING** | Defines `VerifyResult` (`reached_goal`, `failed_at_index`, `final_state`, `trace`), `AttemptRecord` (`raw_reply`, `plan`, `verify`) and `RunResult` (`world_before`, `world_after`, `latency_s`). **None of these shapes exist at runtime**; the real verifier returns `{"ok","reason","checks"}`. Documents `service.run_instruction` as the only interface — a 22-line stub that was deleted in `8b11a1f`. |
| `docs/WORKFLOW.md` (36 lines) | **OUTDATED / ASPIRATIONAL** | Requires feature branches and "No direct pushes to `main` are allowed". All 18 commits are direct commits to `main`; no `backend/*` or `frontend/*` branch ever existed. |
| `gemmabot/schemas.py` | **DEAD + MISLEADING** | Claims to be "the shared data structures used between frontend and backend"; imported by nothing; its docstrings assert an ownership rule that no longer applies. |
| `RUN_AND_DEPLOY.md` (252 lines) | **MOSTLY ACCURATE, ONE BROKEN COMMAND** | Line 71 `python3 -m gemmabot.harness` → **no output, exit 0** (verified). Also shows `-e GEMINI_API_KEY=sk-...` (an OpenAI-style prefix for a Google key) in the Dockerfile comment. Docker/Render sections are internally consistent. |
| `BACKEND_AUDIT_REPORT.md` (398 lines) | **TRUE WHEN WRITTEN, NOW OBSOLETE** | Claims `gemmabot/service.py`, `verifier.py`, `repair.py`, `world_validation.py` "raise `NotImplementedError`". Verified accurate for its date: those files did exist as 16–25-line stubs, created in `dc0ddab` and **deleted** in `8b11a1f` (`git show --stat --diff-filter=D 8b11a1f` → 6 files, 117 deletions). The report describes a scaffold that no longer exists and was never re-written. |
| `FINAL_PROTOTYPE_AUDIT_REPORT.md` (164 lines) | **CONTAINS A FALSE CRITICAL CLAIM** | §Security: "A non-placeholder `GEMINI_API_KEY` is present in the committed `.env.example`." **Not reproducible** — see §21.1. Also states "the four skipped tests are placeholders … planner parsing, repair, verifier, and world validation"; now **three** (verifier has 22 real tests and no stub file). |
| `docs/archive/CODEBASE_AUDIT_starter.md` (189 lines) | **ARCHIVED / SUPERSEDED** | Describes `robot_sim.py`, which no longer exists. Correctly filed under `archive/`. |

**Overall documentation verdict: the docs describe an older, four-module, service-oriented architecture that was never built, and omit the architecture that *was* built.** This is the second-largest production blocker because it will mislead every new contributor.

---

## 19. Repository Hygiene

### 19.1 Git state

| Item | Value |
|---|---|
| Branch | `main` only; **no other branches, local or remote-tracking** |
| Commits | 18 |
| Authors | 2 (`Biley7`, `Dighal Saha`) — note the mailmap is not configured, so one human may appear twice |
| Date range | 2026-10-04 → 2026-10-08 |
| Working tree | **clean** |
| Merge commits / PRs | 0 — all commits are linear on `main` |
| Secrets in history | **none found** (§14.1) |

### 19.2 Tracked-file problems

| Problem | Severity | Evidence |
|---|---|---|
| **A 0-byte file with a corrupted path is tracked** | LOW (cosmetic/professional) | `git ls-files` contains `[gemmabot-final-prototype-audit.canvas.tsx](http:/_vscodecontentref_/19)` — an empty blob (`e69de29`) inside two accidentally-created directories named after a VS Code markdown link. Introduced by commit `083e652`. It pollutes every `git ls-files` and will confuse tooling. |
| Duplicate/stale root reports | LOW | `BACKEND_AUDIT_REPORT.md` and `FINAL_PROTOTYPE_AUDIT_REPORT.md` sit at the repo root (not `docs/`) and contain claims that no longer hold. |
| `benchmarks/dry_run_output.txt` | LOW | Non-UTF-8 console dump; tracked. Excluded from the Docker context. |
| `.freebuff/project-id` tracked | LOW | Tool metadata committed to the repository. |
| `.vscode/settings.json` tracked | LOW | Editor config committed (was touched in `083e652`). |

### 19.3 Ignore coverage

| Path | Ignored by | Verdict |
|---|---|---|
| `.env` | `.gitignore:1` | Correct |
| `__pycache__/` | `.gitignore:2` | Correct |
| `.venv/` | `.gitignore:3` | Correct |
| `logs/`, `logs/*.jsonl` | `.gitignore:5,6` | Correct — `logs/runs.jsonl` is untracked |
| `.streamlit/secrets.toml` | `.gitignore:7` | Correct |
| `.pytest_cache/` | **only** its own auto-generated `.pytest_cache/.gitignore` (`*`) | Works today; add an explicit rule for robustness |
| `.env.local`, `.env.production`, `.env.*` | **NOT IGNORED** | Real gap — see §14.1 action 3 |
| `docs/` in the Docker context | `.dockerignore` | Intentional |

### 19.4 Generated files committed

`benchmarks/results.json`, `benchmarks/results.md`, `benchmarks/dry_run_output.txt` are tracked outputs of `python -m gemmabot.benchmark`. This is a **deliberate, documented choice** and the artefacts are honestly labelled synthetic — not reported as a defect, but they will drift from the code they were generated by.

---

## 20. Production Readiness Scorecard

Scale: 0 = absent · 1 = prototype · 2 = early implementation · 3 = functional · 4 = production-oriented · 5 = production-ready.

| Category | Score | Justification |
|---|---|---|
| **Architecture** | **3** | Genuine layering with a Streamlit-free engine layer (44 tests), and the refactor that deleted a 6-file stub scaffold was the right call. Held back by dead `schemas.py`, two empty packages, 6 compatibility shim files, and docs still describing the deleted scaffold. |
| **Backend** | **3** | Real, tested verifier/planner/logger/vision. No service boundary, no structured logging, `print()` debugging in production paths, client re-created per call. |
| **Verification / Safety** | **4** | The strongest subsystem: deep-copy isolation proven, whole-plan scan, 20-step cap, empty/malformed/oversized/raising cases all covered, `ok=None` never rendered as a pass, 22 targeted tests, dry-run and executor share `step()`. Not 5: the UI-level gate is not pinned by a test. |
| **Simulator** | **4** | Deterministic, shared with the verifier, coordinate system consistent between prompt and code. Not 5: only 3 direct tests; nonsense `steps` silently coerced. |
| **Animation** | **4** | Full transport (play/pause/reset/step/speed), timeline derived from real executions, reduced-motion honoured. Not 5: iframe isolates it from the design system; no automated semantic coverage. |
| **UI / UX** | **3** | Coherent, token-driven, information-dense instrumentation with real empty/loading/error states and consistent state colours. Not higher: the core "nothing executes until verified" promise is buried in captions, and no visual regression evidence exists. |
| **Vision** | **2** | Pipeline, prompt, parser, validation, retry and load are all real and tested — but **the live model path has never been demonstrated**. Deliberately not scored 3. |
| **Model Integration** | **2** | Two backends + auto fallback implemented and unit-tested with fakes; historical live records exist but no timeout, no cancel, no live verification in this audit. |
| **SDK / API** | **1** | Importable functions exist, but there is no supported interface: no `service.py`, no versioned entry point, no documented callable contract that matches reality. `schemas.py` is dead. |
| **Testing** | **3** | 424 fast, deterministic, network-free tests; safety-critical paths well covered. Held back by 3 placeholder skips, no CI, no coverage measurement, no live/vision/Docker tests, no browser automation. |
| **Security** | **3** | No credential in Git or the image, correct script-payload escaping, non-root container, redaction in logs, zero `eval`/`exec`/`subprocess`. Held back by an unauthenticated, CORS-open, unmetered public surface; `.env*` ignore gap; raw exception text reaching the UI. |
| **Performance** | **1** | Measured 0.10 s → 251.87 s per model run, no timeout, no cancellation, synchronous blocking, sequential retries. This is the defining production defect. |
| **Documentation** | **1** | README accurate but minimal; ARCHITECTURE/CONTRACTS describe a scaffold deleted in `8b11a1f`, WORKFLOW describes a process never followed; one documented command is a silent no-op; one root report carries a security CRITICAL that does not survive verification and another is obsolete. |
| **Deployment** | **3** | Solid Dockerfile (multi-stage, non-root, healthcheck, good `.dockerignore`) + Render blueprint. Not higher: image never built in this audit, version drift 3.11 image vs 3.14 dev vs 3.9 venv, no lock file, no CI. |
| **Observability** | **2** | JSONL run log with redaction, replayable records, honest mode provenance. No structured logging, no metrics, no tracing, no run IDs, no alerting, no health dashboard. |

### Weighted summary

| Band | Average | Categories |
|---|---|---|
| Strongest (4) | **4.0** | Verification/Safety, Simulator, Animation |
| Middle (3) | **3.0** | Architecture, Backend, UI/UX, Testing, Security, Deployment |
| Weakest (1–2) | **1.5** | Vision, Model Integration, SDK/API, Performance, Documentation, Observability |

### Overall readiness level

# 🔴 RED

**Meaning:** blocking issues remain.

The blocker is not correctness of what exists — the verification core is genuinely production-shaped. The blockers are the things a production system cannot ship without:

1. **An unbounded, uncancellable model call** that has measured 251.87 s and blocked the UI indefinitely in this project's own history.
2. **Live paths that have never been verified in the current tree** (API success, Ollama, real-image vision).
3. **Documentation that describes a different system than the one that runs.**
4. **No programmatic interface** — nothing can integrate with GemmaBot except by driving Streamlit.
5. **No automated safety net** — no CI, and 3 test files that assert nothing while implying coverage.

---

## 21. Critical Findings

### 21.1 Previous audit claims that did not survive verification

**Claim:** *"A non-placeholder `GEMINI_API_KEY` is present in the committed `.env.example`… A value-free comparison confirmed it matches the local `.env` credential… the committed credential is included in the Docker build context/image."*
Source: `FINAL_PROTOTYPE_AUDIT_REPORT.md` §Security Findings.

**Finding: NOT REPRODUCIBLE.** Evidence:

```
$ git show 083e652 -- .env.example
- GEMINI_API_KEY=                     ← empty value, before the "secrets removed" commit
+ GEMINI_API_KEY=your_api_key_here    ← placeholder, after it

$ git rev-list --all --objects | grep -E "(^|/)\.env$"     → empty (no .env blob ever)
$ scan of every text blob in all 18 commits for the live key → NONE
$ scan of every text blob for AIza… / sk-…                  → NONE
$ git check-ignore -v .env → .gitignore:1:.env   (untracked)
$ .dockerignore → ".env" and ".streamlit/secrets.toml" listed under "NEVER bake these into an image"
```

`.env.example` **never contained a credential** — it held an empty value before commit `083e652` and a placeholder after it. No key exists in any commit. The prior report's CRITICAL rating was based on the *working tree*, not the repository, or on a misreading of the file's value.

**What is still true and still actionable:** a live 53-character `AQ.`-style key sits in the local `.env`. Because Google's newer keys do not start with `AIza`, naive secret scanners would miss it. If this directory has ever been shared as an archive, rotate. And `.gitignore` only covers the exact name `.env`.

**Claim:** *"`gemmabot/service.py`, `verifier.py`, `repair.py`, `world_validation.py` raise `NotImplementedError`."* (`BACKEND_AUDIT_REPORT.md`)

**Finding: TRUE FOR ITS DATE, BUT OBSOLETE — AND IT IS THE SOURCE OF THE DOC DRIFT.** Those files were not imaginary: they were 16–25-line scaffold stubs created in `dc0ddab` and **deleted** in `8b11a1f` "refactor: clean architecture before UI pass" (`6 files changed, 117 deletions(-)`, no replacements):

```
frontend/components.py       | 25 -------------------------
frontend/state.py            | 14 --------------
gemmabot/repair.py           | 20 --------------------
gemmabot/service.py          | 22 ----------------------
gemmabot/verifier.py         | 20 --------------------
gemmabot/world_validation.py | 16 ----------------
```

The deletion was correct. The defect is that `docs/ARCHITECTURE.md` and `docs/CONTRACTS.md` still describe the deleted scaffold, so the documentation now contradicts a refactor made five commits ago. **This is documentation drift, not a fabrication in the prior report.**

**Claim:** *"The four skipped tests are placeholders for planner parsing, repair, verifier, and world validation."* (`FINAL_PROTOTYPE_AUDIT_REPORT.md`) — now **three**; `tests/test_verifier.py` holds 22 real tests and there is no verifier stub file.

### 21.2 Findings in the current repository

| # | Finding | Severity | Evidence |
|---|---|---|---|
| C1 | **No timeout, no cancellation, no client reuse on any model call.** A click can block the Streamlit thread indefinitely; measured up to **251.87 s**; `auto` cannot fall back from a hang because it only catches exceptions. | **CRITICAL** | `backend/planner/planner.py:29,42`; `map_vision.py:545,605`; `engine._make_auto_ask`; `logs/runs.jsonl` |
| C2 | **The documented architecture describes a scaffold deleted five commits ago.** `service.py`, `verifier.py`, `repair.py`, `world_validation.py`, `frontend/components.py`, `frontend/state.py` are all named in `docs/ARCHITECTURE.md` and `docs/CONTRACTS.md`; all six were removed in `8b11a1f`. New contributors will build against a layout that no longer exists. | **CRITICAL** (for a team) | `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, `git show --stat --diff-filter=D 8b11a1f` |
| C3 | **No programmatic interface.** Nothing can use GemmaBot's verification without driving Streamlit. `gemmabot/schemas.py` describes contracts that do not match runtime. | **HIGH** | `grep` for `service`/`schemas` importers → none |
| C4 | **Live paths unverified.** API success, Ollama reachability, auto-fallback and real-image vision have no evidence in the current tree; only historical log records predate the current commits. | **HIGH** | `logs/runs.jsonl` (records end 2026-10-07, all `mode=None`); no test touches the network |
| C5 | **No CI, no coverage, 3 no-op test files named as if they test something.** `test_planner_parse.py`, `test_repair.py`, `test_world_validation.py` assert `True` and skip. | **HIGH** | `pytest -rs` output; no `.github/`, no `conftest.py` |
| C6 | **A documented verification command is a silent no-op.** `python3 -m gemmabot.harness` exits 0 and prints nothing. | **HIGH** (developer trust) | verified by execution; `RUN_AND_DEPLOY.md:71` |
| C7 | **Unauthenticated, CORS-open, unmetered deployment surface.** No login, `enableCORS=false`, no rate limiting, cost is per click. | **HIGH** | `.streamlit/config.toml`; `Dockerfile`; observed Streamlit CORS warning |
| C8 | **`.env*` is not ignored**, only the exact name `.env`. `.env.local`/`.env.production` would be committed silently. | **MEDIUM** | `.gitignore` |
| C9 | **Raw exception text is shown in the UI** (`f"{type(exc).__name__}: {exc}"`) with no redaction pass, unlike the logger which redacts. | **MEDIUM** | `engine.run_plan`, `engine.run_map_vision` |
| C10 | **`print()`-based diagnostics in production paths** (`harness.plan_with_repair`, `map_vision.read_map`) — no log levels, no structured logging. | **MEDIUM** | source |
| C11 | **Three separate fence-tolerant JSON parsers** (`planner.parse_plan`, `harness._parse_plan`, `map_vision._parse_world_json`). | **LOW** | source |
| C12 | **Nonsense `steps` values are silently coerced** (`-5` → 1, `999` → 7) rather than refused. Verifier and executor agree, so it is not a safety hole. | **LOW** | `simulator.step` |
| C13 | **Tracked 0-byte file with a corrupted VS Code path** and two stray directories. | **LOW** | `git ls-files` |
| C14 | **Version drift:** Docker 3.11 / declared 3.11.9 / dev 3.14.7 / bundled `.venv` 3.9.6 (no Streamlit). | **LOW–MEDIUM** | files + measured runtime |
| C15 | **No lock file or dependency hashes**; `pytest` shipped in runtime requirements. | **LOW–MEDIUM** | `requirements.txt` |
| C16 | **The player iframe duplicates its own CSS layer**, bypassing the design system. | **LOW** | `player_view._css` |
| C17 | **No run IDs** — records are identified by timestamp; 33 legacy records are not replayable (no `actions`/`world`), and **all 64 records lack `requested_backend`**. | **LOW** | `logs/runs.jsonl` analysis |

---

## 22. Gap Analysis

| Gap | Severity | Current State | Required State | Work Estimate | Dependency |
|---|---|---|---|---|---|
| Model calls have no time budget | **CRITICAL** | Unbounded; measured 0.10–251.87 s; no cancel | Timeout + explicit cancel + a "the model did not answer in N s" UI state | 2–4 days | None |
| `auto` cannot fall back from a hang | **CRITICAL** | Falls back only on exception | Fall back on timeout too; report which backend answered | 0.5 day | Timeout work above |
| Documentation describes a deleted scaffold | **CRITICAL** | 6 deleted-file references in `ARCHITECTURE.md`/`CONTRACTS.md`; 3 contract shapes that were never the runtime's | Rewrite both docs from the real tree; fix the no-op command | 2–3 days | None |
| No programmatic interface | **HIGH** | Only Streamlit | A documented `service`/SDK entry point over the existing engine functions | 3–5 days | Decide the contract first |
| Live paths unverified | **HIGH** | Historical records only | Scripted live smoke test (API + Ollama + real image), captured and reported | 2–3 days | Working credentials/hardware |
| No CI | **HIGH** | Manual runs only | GitHub Actions: install, pytest, Docker build, smoke-start the app | 1–2 days | None |
| 3 no-op test files | **HIGH** | `assert True` + skip | Implement them or delete them | 1–3 days | None |
| Unauthenticated / unmetered public surface | **HIGH** | Open | Auth gate + rate limit + cost ceiling before any public URL | 3–5 days | Deployment target |
| UI cannot be driven headlessly | **MEDIUM** | AppTest only | Browser smoke tests (tab render, run plan, replay) in CI | 2–4 days | CI |
| Progress + cancel in the UI | **MEDIUM** | Spinner only, UI blocked | Streaming status with an abort control | 2–3 days | Timeout work |
| `.env*` ignore gap, raw exceptions in UI | **MEDIUM** | Partial | Widen ignore rules; add a redaction pass on displayed errors | 0.5 day | None |
| Config/model agnosticism | **MEDIUM** | Gemma-specific constants, parallel vision abstraction | One backend registry with declared capabilities | 3–5 days | After the service contract |
| No coverage measurement | **MEDIUM** | Unknown coverage | `pytest --cov` with a floor agreed from the real baseline | 1 day | CI |
| No run IDs / replay of legacy records | **LOW** | Timestamp identity | Stable run id in the log schema; keep back-compat | 1–2 days | None |
| Tracked junk file, duplicated parsers, version drift | **LOW** | Present | Remove the artifact; one JSON extractor; pin one Python version | 1 day | None |
| Structured logging + metrics | **LOW–MEDIUM** | `print()` + JSONL | `logging` with levels; timers exposed as metrics | 2–3 days | None |
| Docker image never built in CI | **MEDIUM** | Static review only | Build + healthcheck in CI | 1 day | CI |

---

## 23. Recommended Roadmap

Derived from the audit above, **not** from the previous roadmap. "PHASE A — MUST FIX BEFORE PRODUCTION" is the only phase that should start now.

### PHASE A — MUST FIX BEFORE PRODUCTION *(blocking; do these first)*

| # | Work | Why it is blocking | Done when |
|---|---|---|---|
| A1 | **Bound every model call.** Timeout on `genai` + `ollama`; treat a timeout as a first-class failure; make `auto` fall back on timeout, not just exception; reuse one client per backend. | A click can currently block the app forever; the fastest observed real run is still ~38 s. | A live call that exceeds the budget surfaces a clear failure and the UI stays responsive. |
| A2 | **Cancellation.** An operator-visible Stop/Abort that ends the run without leaving partial state. | There is no way out of a hung call today. | Pressing Stop returns the UI to a usable state with no stale result. |
| A3 | **Truth pass on the documentation.** Rewrite `ARCHITECTURE.md` and `CONTRACTS.md` from the actual tree; fix or delete `python3 -m gemmabot.harness` in `RUN_AND_DEPLOY.md`; delete dead `schemas.py` or make it real. | Docs name six files deleted in `8b11a1f` and a service boundary never wired to the UI. | Every path and contract in the docs resolves in the repo; the documented self-test command actually prints its assertions. |
| A4 | **Live-path verification with captured evidence.** One successful API run, one Ollama run (or an explicit "not available on this machine"), one real-image vision read — recorded with latency and outcome. | The product's core claim is currently unevidenced in the current tree. | A captured transcript/report showing real model → real verification → real execution. |
| A5 | **CI + kill the no-op tests.** Actions running `pytest`, a Docker build, and a headless app-start smoke test. Implement or delete the 3 placeholder test files. | Nothing currently prevents regressions, and 3 files imply coverage they do not provide. | CI is required to merge; skips are 0 or explicitly justified. |
| A6 | **Widen secret hygiene.** `.env*` in `.gitignore`; redact exception text before display; add the `AQ.` key shape to scanner patterns. | Prevents the one leak class this audit did not find but that the ignore rules would allow. | Ignore rules cover all env variants; displayed errors carry no key material. |

**Exit criteria for PHASE A:** the app can be left unattended for a live demo, a new contributor can read the docs and find every file they name, and CI proves the suite + image build on every push.

### PHASE B — REQUIRED FOR PILOT

| # | Work | Rationale |
|---|---|---|
| B1 | A real service/API boundary (`run_instruction`, `verify_plan`, `read_map`) with a stable, documented contract | The single thing that turns a Streamlit app into something a robotics team can integrate |
| B2 | Auth + rate limiting + spend ceiling on the deployed app | Without it, any public URL is an open wallet |
| B3 | Streaming progress and cancel in the UI (server-sent stages instead of a spinner) | Matches the "AI laboratory" claim; makes long runs tolerable |
| B4 | Coverage measurement with a floor; tests for the `app.py` execution gate and the simulator's step edges | Pins the safety invariant that is currently only structural |
| B5 | Run IDs + a documented log schema; make legacy records explicitly non-replayable in the UI | Enables audit trails, the prerequisite for any pilot |
| B6 | Backend registry (one abstraction for text + vision, declared capabilities, per-backend timeout) | Current model-agnosticism is partial and duplicated across two code paths |

### PHASE C — PRODUCTIZATION

| # | Work |
|---|---|
| C1 | Replace the free-text planner prompt contract with a versioned, schema-validated plan protocol |
| C2 | Real-world vision hardening: a labeled image corpus, accuracy reporting per rule, and a published "we do not claim general vision" statement |
| C3 | Multi-tenant session isolation and per-session budgets |
| C4 | Observability: structured logs, latency histograms, per-backend success/repair metrics, alerting on failure rate |
| C5 | Live benchmark matrix with provenance enforced in CI (live rows only from recorded live runs) |
| C6 | Deployment hardening: pinned lock file with hashes, image scanning, SBOM, rollback strategy |

### PHASE D — FUTURE / OPTIONAL

| # | Work |
|---|---|
| D1 | A second grid size / non-square world, and non-point goals (the coordinate system is already parameterised by `SIZE`) |
| D2 | Pluggable verifiers (user-supplied invariants) — the four-check contract is a natural extension point |
| D3 | ROS / hardware bridge (only after the service boundary exists; explicitly **not** a Phase A–C concern) |
| D4 | Recorded-reply replay of *model* interactions (distinct from the existing plan replay) for deterministic demos |
| D5 | Multi-robot worlds |

**Deliberately not recommended now:** ROS integration, non-grid physics, any new UI lab, or a rewrite of the simulator. The audit found no evidence that these are the constraint.

---

## 24. Product Readiness Assessment

1. **What is the product today?** A single-user Streamlit laboratory that turns a natural-language instruction into a robot plan, **proves the plan against a real simulator before anything moves**, animates the result, and keeps an honest run log and benchmark. It is a *verification-first demo bench*, not a robotics product.

2. **Strongest real capability.** The **verification loop**. It is deterministic, deep-copy isolated, whole-plan scanned, bounded, and covered by 22 named tests. The `ok=None` "not evaluated, never a pass" convention is a genuine integrity design choice that most AI demos get wrong. It is also the one thing competitors would not have.

3. **Merely a demo feature.** The **Benchmark Lab** (30 synthetic rows, 0.000 s latency — it measures the loop, not a model); the **dry-mode scripted planner**; the emoji legend; the "Max tries" slider once timeouts exist.

4. **Strongest differentiator.** *"The model proposes; code disposes, and you can see the check."* The four-check checklist with per-check unproven states, plus a replayable trace, is a credible mechanism for *trust* in an LLM-driven robot. Nothing in this repo's UI is more valuable than that chain: propose → verify → repair → execute → replay.

5. **Missing for a sellable developer product.** A programmatic API (§14/§22), authentication and metering, timeouts and cancellation, CI with coverage, a versioned plan protocol, deployment lock file, and documentation that matches the system. Roughly everything in PHASE A + B.

6. **What can be demonstrated today.** A fully offline, deterministic demo (dry mode) showing: an instruction → a plan that hits a real wall → deterministic rejection with the exact offending cell → automatic repair → verified plan → animated execution to the goal → replay → honest benchmark. Also the Vision Lab's scripted misread → validator rejection → retry → validated world load. Also, on a machine with working credentials and patience, a live model run.

7. **Claims that should NOT be made yet.** *(These are the specific over-claims to avoid.)*
   - "Production-ready" or "reliable" — no timeout; measured live runs up to **252 s**.
   - "Works with Gemma/Gemini at scale" — one backend has never been verified in the current tree and the other has 2 recorded failures.
   - "Computer-vision map reading works" — the live vision path has never been exercised.
   - "Benchmarks show X% success" — the checked-in benchmark is **synthetic**; the LIVE column is empty on purpose.
   - "An SDK / API is available" — there is none.
   - "Multi-user" or "deployable publicly" — no auth; CORS open; per-click spend.

8. **Likely target user.** *(Recommendation, no market validation claimed.)* An ML/robotics engineer or researcher who needs to trust an LLM's action plan before it reaches hardware — i.e. someone building "LLM proposes, code verifies" pipelines for grid/waypoint navigation. Secondary: educators demonstrating safe LLM-to-actuator gating.

9. **What a robotics startup would need before piloting.** Six things, in order: (a) a supported API to call verification from their own stack; (b) a time budget on every model call with a clear failure mode; (c) auth and per-run cost control; (d) evidence that the live model path works on *their* inputs — with their world representation, not only `new_world()`; (e) a log schema with stable IDs they can audit; (f) proof the verifier matches their safety rules, plus the ability to add rules. All six are scheduled in PHASE A/B above.

---

## 25. Final Verdict

GemmaBot has a **genuinely well-built core wrapped in over-confident documentation**.

The honest summary of the previously planned work: **~90 % of the prototype scope is implemented** (14/14 capabilities present; design system, simulator, animation, brain, safety, vision pipeline, run history, replay and benchmark labs all exist), and **~65 % of it is verified by tests** (8 capabilities fully tested; 3 are implemented but unverified live). What is **0 % complete** is the productionization surface: no SDK, no timeouts, no auth, no CI, no coverage, no accurate architecture docs, no observability.

Three things make the readiness level **RED** rather than YELLOW:

1. A model call can hang the application indefinitely, and has measured 252 s.
2. The documentation describes a scaffold that was deleted five commits ago and never re-documented.
3. Nothing outside Streamlit can use the verification engine, which is the actual asset.

None of those is a deep engineering problem — each is days of work, not months. Which is the good news: the hard part (a trustworthy, tested, deterministic verification loop with honest states) has already been done and is the reason this project is worth productionizing at all.

**This document is the baseline. Every future GemmaBot phase should be measured against §22 (Gap Analysis) and §23 (Roadmap).**

---

*Audit performed read-only. No source, test, benchmark, credential, or Git history was modified. The only artifact created is this file.*
