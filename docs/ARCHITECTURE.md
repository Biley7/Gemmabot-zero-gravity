# Architecture

**GemmaBot is an AI robotics validation platform**: AI-generated robot actions
are proposed, deterministically validated, simulated, repaired when possible,
and only then approved for execution. This document describes the code that
actually runs (Phase-1 architecture, 2026-10-09), not a future scaffold.

## The product pipeline

```
                AI MODEL
                   │  raw text replies
                   ▼
            Planner Adapter            backend/guard/planner.py
                   │  Planner.propose(instruction, world) -> str
                   ▼
          GemmaBot Guard               backend/guard/pipeline.py
          /      │       \
         /       │        \
    Validator  Simulator  Repair       verify_plan() · simulate() · plan_with_repair()
         \       │       /
          \      │      /
                ▼
          Approved Plan                backend/guard/contracts.py  (sealed, digest-bound)
                │
      ┌─────────┴─────────┐
      │                   │
   Simulator           Robot/ROS
  (shipped)           (not yet — no ROS 2, no hardware)
```

The guard never trusts a caller's claim that a plan is fine. `plan()` runs the
bounded propose → parse → verify → repair loop and returns an `ApprovedPlan`
**only** when verification passed; `execute()` refuses anything that is not a
sealed `ApprovedPlan`, re-verifies it against the sealed world snapshot and
re-computes the approval digest before a single simulator step runs.

## Layers

| Layer | Module | Responsibility |
|---|---|---|
| Planner adapters | `backend/guard/planner.py` | model-agnostic `Planner`/`VisionPlanner` protocols; Gemini, Ollama, fallback and callable adapters; registry |
| Parsing | `backend/parsing.py` | one model-reply parser for plan and world replies |
| Validation | `backend/verifier/harness.py` (`verify_plan`), `backend/vision/map_vision.py` (`check_world_report`) | deterministic per-check verdicts; unproven is `None`, never a pass |
| Simulation | `backend/guard/pipeline.py` (`simulate`), `gemmabot/simulator.py` | step loop and grid physics (single source of truth) |
| Repair | `backend/verifier/harness.py` (`plan_with_repair`) | bounded retries; every failure fed back once, original instruction preserved |
| Approval | `backend/guard/pipeline.py` (`approve`), `backend/guard/contracts.py` | re-verify, deep-copy world, canonicalize actions, seal digest |
| Execution | `backend/guard/pipeline.py` (`execute`) | approval required, re-verified, digest-checked, then simulates |
| Logging | `backend/logger/logger.py` | JSONL run records, provenance mode, secret redaction |
| Contracts | `backend/guard/contracts.py` | canonical World / Action / Plan / VerificationResult / ExecutionResult / ApprovedPlan |
| Programmatic API | `backend/api/*` | the caller-facing, versioned contracts over the guard — `planner`, `guard`, `repair`, `runtime`, `runs` — with no Streamlit import |

There are no duplicate implementations: the planner, the repair loop and map
vision all parse through `backend.parsing`; the UI, the logs and the tests all
read the same verification result shape.

## Streamlit application

```
app.py  (Streamlit entry point, session state, five labs)
  │
  ├─ Text command / Safety Lab
  │    engine.run_plan(instruction, world, backend, max_tries)
  │      └─ backend.guard.pipeline.plan(...)        propose → verify → repair → approve
  │    engine.approve(world, engine.verified_actions(result))   ← the UI may only request
  │      └─ engine.execute_approved(approved)       re-verified, digest-checked, then steps
  │
  ├─ Vision Lab
  │    engine.run_map_vision(image, mime, backend, max_tries)
  │      └─ backend.vision.map_vision.read_map → check_world_report (3 checks)
  │    GATE: a world must pass every check before "Load into simulator"
  │
  ├─ Run History
  │    backend.logger.logger.load_runs(logs/runs.jsonl)
  │      └─ frontend.panels.replay  filter → VIEW RUN → REPLAY
  │    Filters: Success · Failed · Repaired · Vision · Text · Model/backend
  │    VIEW RUN   the record's twelve metadata fields + its timeline
  │    REPLAY      player.build_timeline(record['world'], record['actions'])
  │                 → simulator.step + verify_plan alone — NO model is called
  │    Each record is labelled LIVE RUN / RECORDED RUN / SYNTHETIC BENCHMARK
  │
  └─ Benchmark — RobotBench
       gemmabot.benchmark (runner) → benchmarks/{results,report}.{json,md}
       frontend.panels.benchmark reads both sources and never adds them up
       (a scripted reply is SYNTHETIC, and never shown as model performance)
```

### RobotBench — the benchmark

**RobotBench** evaluates AI-generated robot plans against deterministic
simulation scenarios.  `gemmabot/benchmark.py` runs the matrix (dataset ×
backend × repair setting × runs) and writes two artifacts: `results.json`, one
record per run, and `report.json`/`report.md`, one **result** per comparable
cell — same dataset, model, backend, mode and repair setting — carrying the
scenario identifiers, the model, the mode, a timestamp, the run count, the
success and failure counts, the latency statistics (mean, median, p95, min,
max), the ids of the runs it summarizes and a sample-size verdict.

`frontend/panels/benchmark.py` renders nine metrics — success rate, verification
rejection rate, repair rate, repair success rate, average actions, average
attempts, latency, collision rate and boundary violation rate — each with its
own denominator, its definition, a tooltip and the sample size behind it.  Two
rules hold everywhere in that view:

* **No number is fabricated.** A missing measurement is `None` (rendered *no
data*), never a zero; a run that was never judged is excluded, not counted as a
failure.
* **Live and synthetic are never merged.** The headline numbers are computed
over one mode and say which; the run log and the stored artifact overlap, so
they are measured separately and never summed.

The two execution metrics are the only place the lab touches the simulator: it
replays every plan a run recorded — the accepted one *and* each attempt the
repair loop refused — on the recorded world through `player.build_timeline`,
and asks what stopped it (`player.halt_kind`: a wall is a collision, the grid
edge a boundary violation).  A verified plan cannot collide, so measuring the
accepted plan alone would always read 0%; the refused attempts are the
measurement.  No model is called.  Below `config.BENCH_MIN_SAMPLE` runs a
metric says so on its own card: those numbers describe those runs, not the
model.

### The run record

Every logged run is a JSONL line holding the twelve structured metadata fields
the Run History shows — `run_id`, `timestamp`, `input_type`, `instruction`,
`model`, `backend`, `attempts`, `plan_length`, `verification`, `execution`,
`latency`, `final_position`, `goal_reached` — plus the `actions` and `world` a
replay needs, and the `mode`/`history` provenance. A field that was not
recorded is written `null` and shown as *not recorded*; a record written before
a field existed omits the key, which means the same thing. Secrets are redacted
before the write, and no run is ever fabricated: the table, the metadata and
every replay read this file and nothing else.

A replay is deterministic simulation, not a re-run: it feeds the recorded world
and plan back into `player.build_timeline` (which calls `simulator.step`) and
`verify_plan`. The reproduced timeline *is* the world, the robot movement and the
actions; the recorded results — verification, steps applied, halt, final position,
goal reached — are then compared field by field against what the record says and
reported as *match* / *mismatch* / *unrecorded*, so a log that disagrees with the
current code is a visible finding rather than a silent pass. The player offers
PLAY, PAUSE, STEP and RESET.

`frontend/panels/engine.py` is the UI-facing adapter over the guard; it is
deliberately Streamlit-free and unit-testable, and it selects backends without
owning any validation logic.

## File responsibility

| Path | Role |
|---|---|
| `app.py` | Streamlit entry point, session state, tabs, the five labs |
| `frontend/panels/engine.py` | backend selection, guard orchestration, approval/execution wrapper |
| `frontend/panels/{brain,safety,vision,replay,benchmark}.py` | the lab panels (pure HTML builders) |
| `frontend/components/*` | design system (colours, spacing, typography, theme, components, blocks, animations) |
| `frontend/simulation/{ui_helpers,player,player_view}.py` | grid rendering, execution timeline, iframe player |
| `backend/guard/{contracts,planner,pipeline}.py` | the guard: contracts, planner interface, pipeline |
| `backend/parsing.py` | canonical reply parsing |
| `backend/planner/planner.py` | `ask_api` (Gemini), `ask_ollama` transports |
| `backend/verifier/harness.py` | `verify_plan`, `dry_run`, `plan_with_repair` |
| `backend/vision/map_vision.py` | `read_map`, `check_world_report`, `ask_vision_api`, `ask_vision_ollama` |
| `backend/logger/logger.py` | `log_run` (the twelve-field run record + `actions`/`world`/`mode`), `load_runs`, `summarize_run`, secret redaction |
| `backend/api/{contracts,planner,guard,repair,runtime,runs}.py` | the programmatic API: request validation, the six namespaces, the execution gate, run recording |
| `gemmabot/simulator.py` | 8×8 world, `step`, `render`, `reached_goal` (physics source of truth) |
| `gemmabot/{config,prompts,benchmark}.py` | configuration, prompts, the RobotBench runner (metrics, result records, report) |
| `gemmabot/{planner,harness,logger,map_vision}.py`, root `engine.py`, `ui_helpers.py` | 3–9 line compatibility shims that re-export the real modules |

## Ownership

- **BACKEND**: `backend/**`, `gemmabot/**`
- **FRONTEND**: `app.py`, `frontend/**`

## Not part of the runtime

An earlier version of this file described `gemmabot/service.py`,
`gemmabot/verifier.py`, `gemmabot/repair.py`, `gemmabot/world_validation.py`,
`frontend/components.py` and `frontend/state.py`. Those six scaffold stubs were
created in `dc0ddab` and **deleted** in `8b11a1f`; nothing imports them and they
do not exist today.

`gemmabot/schemas.py` (an unreferenced TypedDict set that contradicted the
runtime shapes) was **deleted in the Phase-1 refactor**. The canonical
contracts now live in `backend/guard/contracts.py`; `docs/CONTRACTS.md`
describes them.

## Interfaces

Two doors, one guard.  The programmatic API is the caller-facing one:

```python
from backend.api import planner, runtime, runs

result = planner.plan("go to the goal", world, backend="auto")
if result["approved"] is not None:
    outcome = runtime.execute(result)            # re-verified, digest-checked
    runs.record(result, execution=outcome)
```

The guard package is the same pipeline one level down, unversioned internals
included:

```python
from backend.guard import build_planner, plan, execute

result = plan("go to the goal", world, build_planner("auto"))
if (approved := result["approved"]) is not None:
    outcome = execute(approved)
```

The Streamlit app reaches the same pipeline through `frontend/panels/engine.py`
(`import engine`). There is no `service.py` and no `run_instruction()`: the
versioned interface is `backend.api`, documented in `docs/API.md`, and both it
and the console execute only through the same sealed `ApprovedPlan`.

## Deliberately absent (Phase 1 scope)

- ROS 2 and hardware support — the execution layer terminates at the simulator.
- Any redesign of the UI.
- Authentication, metering, and per-call timeouts/cancellation (tracked in
  `docs/PRODUCTION_READINESS_2026-10-09.md`).
