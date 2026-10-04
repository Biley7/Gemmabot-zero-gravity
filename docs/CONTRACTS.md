# Contracts

This document defines the data contracts between frontend and backend. Changes require agreement from both BACKEND and FRONTEND.

## Data Types

### World
```json
{
  "robot": [0, 0],
  "dir": "E",
  "goal": [6, 5],
  "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]]
}
```

### Action
```json
{
  "cmd": "forward",
  "steps": 3
}
```
or
```json
{
  "cmd": "turn_left"
}
```

### Plan
```json
{
  "thought": "Head east then south around the wall",
  "actions": [
    {"cmd": "forward", "steps": 3},
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 5}
  ]
}
```

### VerifyResult
```json
{
  "ok": true,
  "reached_goal": true,
  "failed_at_index": null,
  "reason": "Plan executed successfully",
  "final_state": {
    "robot": [6, 5],
    "dir": "S",
    "goal": [6, 5],
    "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]]
  },
  "trace": ["moved forward 3", "turned right", "moved forward 5"]
}
```

### AttemptRecord
```json
{
  "attempt": 1,
  "raw_reply": "{\"thought\":\"...\",\"actions\":[...]}",
  "plan": {
    "thought": "...",
    "actions": [...]
  },
  "verify": {
    "ok": true,
    "reached_goal": true,
    "failed_at_index": null,
    "reason": "...",
    "final_state": {...},
    "trace": [...]
  },
  "error": null
}
```

### RunResult
```json
{
  "status": "success",
  "instruction": "Go to the goal around the walls",
  "backend_used": "api",
  "world_before": {
    "robot": [0, 0],
    "dir": "E",
    "goal": [6, 5],
    "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]]
  },
  "world_after": {
    "robot": [6, 5],
    "dir": "S",
    "goal": [6, 5],
    "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]]
  },
  "attempts": [
    {
      "attempt": 1,
      "raw_reply": "...",
      "plan": {...},
      "verify": {...},
      "error": null
    }
  ],
  "final_plan": {
    "thought": "...",
    "actions": [...]
  },
  "latency_s": 2.5,
  "error": null
}
```

## Frontend-Backend Interface

The frontend calls ONLY:

```python
from gemmabot.service import run_instruction

result = run_instruction(
    instruction="Go to the goal around the walls",
    world=world_state,
    backend="api"  # or "ollama" or "auto"
)
```

The frontend must NOT import planner, verifier, repair, or logger directly.
