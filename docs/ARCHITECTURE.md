# Architecture

## Data Flow

```
World -> world_validation -> planner -> verifier -> repair -> logger -> RunResult
```

1. **world_validation**: Validates the initial world state
2. **planner**: Calls Gemma to generate a plan from the instruction
3. **verifier**: Simulates the plan and checks if it reaches the goal
4. **repair**: If verification fails, attempts to repair the plan (up to MAX_REPAIRS)
5. **logger**: Logs the attempt and result to persistent storage
6. **RunResult**: Final result returned to the frontend

## File Responsibility Table

| File | Owner | Responsibility |
|------|-------|----------------|
| `gemmabot/config.py` | BACKEND | Configuration constants |
| `gemmabot/simulator.py` | BACKEND | World simulation (step, render, reached_goal) |
| `gemmabot/prompts.py` | BACKEND | AI model prompts |
| `gemmabot/planner.py` | BACKEND | AI model interaction (ask_api, ask_ollama, parse_plan) |
| `gemmabot/schemas.py` | SHARED | Data contracts (TypedDicts) |
| `gemmabot/world_validation.py` | BACKEND | World state validation |
| `gemmabot/verifier.py` | BACKEND | Plan verification |
| `gemmabot/repair.py` | BACKEND | Plan repair logic |
| `gemmabot/logger.py` | BACKEND | Logging infrastructure |
| `gemmabot/benchmark.py` | BACKEND | Benchmarking and metrics |
| `gemmabot/map_vision.py` | BACKEND | Multimodal map vision |
| `gemmabot/service.py` | BACKEND | Frontend-backend service layer |
| `frontend/components.py` | FRONTEND | Streamlit UI components |
| `frontend/state.py` | FRONTEND | Session state management |
| `app.py` | FRONTEND | Main Streamlit application |

## Ownership Rule

- **BACKEND** owns all files in `gemmabot/` except `schemas.py`
- **FRONTEND** owns `app.py` and all files in `frontend/`
- **SHARED**: `schemas.py` and `docs/CONTRACTS.md` can only be changed with agreement from both BACKEND and FRONTEND

## Frontend-Backend Contract

The frontend calls ONLY `service.run_instruction(instruction, world, backend)` and must not import planner, verifier, repair, or logger directly.
