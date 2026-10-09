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
  └─ Replay / Benchmark
       backend.logger.logger.load_runs(logs/runs.jsonl) → player / benchmark panel
       (replays run through engine.simulate — demonstrations, marked unverified)
```

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
| `backend/logger/logger.py` | `log_run`, `load_runs`, `summarize_run`, secret redaction |
| `gemmabot/simulator.py` | 8×8 world, `step`, `render`, `reached_goal` (physics source of truth) |
| `gemmabot/{config,prompts,benchmark}.py` | configuration, prompts, benchmark CLI |
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

## Interface

The guard is importable without Streamlit:

```python
from backend.guard import build_planner, plan, execute

result = plan("go to the goal", world, build_planner("auto"))
if (approved := result["approved"]) is not None:
    outcome = execute(approved)
```

The Streamlit app reaches the same pipeline through `frontend/panels/engine.py`
(`import engine`). There is no `service.py` and no `run_instruction()`; a
versioned programmatic API is a known gap, and the guard package is the
foundation it will be built on.

## Deliberately absent (Phase 1 scope)

- ROS 2 and hardware support — the execution layer terminates at the simulator.
- Any redesign of the UI.
- Authentication, metering, and per-call timeouts/cancellation (tracked in
  `docs/PRODUCTION_READINESS_2026-10-09.md`).
