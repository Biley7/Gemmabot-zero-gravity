# Contracts

The canonical data shapes. They are defined in **`backend/guard/contracts.py`**
and produced by the running system; verify any change here against that module,
`backend/verifier/harness.py`, `backend/vision/map_vision.py`,
`backend/guard/pipeline.py` and `backend/logger/logger.py`.

## World

```json
{
  "robot": [0, 0],
  "dir": "E",
  "goal": [6, 5],
  "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]]
}
```

`canonical_world(world)` structurally checks the four keys, the heading and the
coordinate pairs, and deep-copies into this shape. Bounds, wall overlap and
reachability are semantic findings owned by `check_world_report`.

## Action / Plan

```json
{"cmd": "forward", "steps": 3}
```
```json
{"cmd": "turn_left"}
```
```json
{"thought": "head east around the wall", "actions": [ {"cmd": "forward", "steps": 2} ]}
```

`cmd` is one of `turn_left`, `turn_right`, `forward`; `steps` is only read for
`forward`. `canonical_actions(actions)` requires dicts carrying a non-empty
`cmd`; *which* commands exist is the validator's contract.

## Verification result — `verify_plan(world, actions)`

```json
{
  "ok": true,
  "reason": "ok",
  "checks": [
    {"id": "valid_actions",  "label": "Valid actions",  "ok": true, "detail": "6 actions, all simulator commands", "data": {}},
    {"id": "in_bounds",      "label": "In bounds",      "ok": true, "detail": "no move left the 8×8 grid",        "data": {}},
    {"id": "no_collisions",  "label": "No collisions",  "ok": true, "detail": "no move entered an obstacle (7 wall cells)", "data": {}},
    {"id": "goal_reachable", "label": "Goal reachable", "ok": true, "detail": "the plan ends on the goal at [6, 5]", "data": {}}
  ]
}
```

`ok` is `True` only when every check is `True`. A check that was never proven
carries `"ok": null` and is never rendered as a pass. `dry_run(world, actions)`
is a thin `(bool, str)` wrapper. `check_world_report` uses the same shape for
worlds with checks `valid`, `in_bounds`, `reachable`.

## Attempt history record

Produced by `plan_with_repair` and `read_map`:

```json
{
  "attempt": 1,
  "prompt": "...",
  "reply": "raw model text",
  "actions": [{"cmd": "forward", "steps": 7}],
  "ok": false,
  "feedback": "action 1 failed: blocked at [2, 0]."
}
```

`actions` is `null` when the reply could not be parsed. `feedback` is the
verifier's own sentence (secrets redacted at the source).

## Guard result — `backend.guard.pipeline.plan(...)`

```json
{
  "actions": [{"cmd": "forward", "steps": 3}],
  "attempts": 2,
  "history": [ "…attempt records…" ],
  "latency": 2.41,
  "backend": "api",
  "error": null,
  "verification": { "ok": true, "reason": "ok", "checks": [ "…" ], "actions": [ "…" ] },
  "approved": "…ApprovedPlan or null…"
}
```

`actions` is `null` exactly when the loop produced nothing executable;
`verification` is `null` when nothing runnable was produced; `approved` is
`null` unless every check passed.

## Approved plan — `approve(world, actions)`

An immutable dataclass produced only by `backend.guard.pipeline.approve()`:

| Field | Meaning |
|---|---|
| `instruction`, `planner` | what was asked and which adapter answered |
| `world` | a deep-copied snapshot of the verified world |
| `actions` | immutable tuple of canonical actions |
| `verification` | the `VerificationResult` that passed |
| `approval_id` | SHA-256 digest of the world + actions (`digest()` recomputes it) |

## Execution result — `execute(approved)` / `simulate(world, actions)`

```json
{
  "ok": true,
  "reached": true,
  "world": { "…the world after the steps…" },
  "log": [{"step": 1, "action": {"cmd": "turn_right"}, "message": "turned right"}],
  "verified": true,
  "approval_id": "b0f1…"
}
```

- `verified` is `true` only for an approved execution; `simulate()` always
  reports `false` with `approval_id: null` — it is a demonstration, not a gate.
- A refusal returns `ok=false`, `verified=false`, an empty `log` and a
  `refused` reason string; a refused plan never steps the simulator.

## Execution gate (the safety invariant)

`execute()` accepts **only** an `ApprovedPlan`, then re-runs `verify_plan`
against the approved world snapshot and re-computes `approval_digest` before
stepping. A UI bug that mutates a plan, a world or an approval object is
detected and refused. `engine.verified_actions(result)` is only a UI
pre-check ("is this worth approving?"); it is *not* the gate.

## Interface

```python
from backend.guard import build_planner, plan, approve, execute, simulate

planner = build_planner("auto")                 # api | local | auto | registered name
result = plan(instruction, world, planner)      # propose → parse → verify → repair → approve
if (approved := result["approved"]) is not None:
    outcome = execute(approved)                 # re-verified, digest-checked, then steps
```

The Streamlit app uses the same pipeline through `frontend/panels/engine.py`
(`import engine` → `run_plan`, `approve`, `execute_approved`, `run_map_vision`,
`simulate`). There is no `gemmabot.service.run_instruction()`; a versioned
programmatic API is a known gap.

## Run-log record — `logs/runs.jsonl`

```json
{
  "timestamp": "2026-10-09T00:00:00+00:00",
  "instruction": "Move to the goal",
  "backend": "dry",
  "success": true,
  "attempts": 2,
  "latency": 0.0001,
  "actions": [ "…the verified plan…" ],
  "world": { "…the world it ran on…" },
  "mode": "synthetic",
  "history": [ "…attempt records…" ]
}
```

`mode` is `"live"` (a model answered), `"synthetic"` (a scripted planner did),
or `null` (provenance not recorded). `actions` and `world` are what make a
record replayable; legacy records without them are listed but cannot be
replayed.

## Compatibility shims

`gemmabot/{planner,harness,logger,map_vision}.py`, root `engine.py` and
`ui_helpers.py` re-export the real modules for older import paths. They contain
no logic; new code imports the `backend.*` modules directly. `gemmabot/schemas.py`
was deleted — `backend/guard/contracts.py` is the one definition per concept.
