# GemmaBot API

The platform's other door: the GemmaBot Guard, driven from Python instead of
the Streamlit console.  A caller provides a world and an instruction (or a plan
they already have), asks for validation, gets a structured result, and executes
only what was approved.

```python
from backend.api import guard, planner, repair, runs, runtime

result = planner.plan("go to the goal", world, planner=my_planner, max_tries=3)
if result["approved"] is not None:
    outcome = runtime.execute(result)                  # approved plans only
    runs.record(result, execution=outcome)
```

The API imports no Streamlit and no vendor SDK: a script, a service or a CI job
needs Python and the world, nothing else.  The console is one caller of the
same guard — it has no privileged path.

> **Status: stable contracts under test, not yet a "production SDK."**  The
> shapes below are versioned and every one has tests, and execution is gated by
> the same approval invariant the console uses.  What is *not* here yet: cloud
> infrastructure, authentication or metering, per-call time budgets and
> cancellation, and CI enforcing the suite on every push.  It is a developer
> interface, not a hosted service.

## The six calls

| Call | Input | Output |
|---|---|---|
| `planner.plan(instruction, world, ...)` | an instruction (a planner answers), or a plan you already have | `RunResult` |
| `guard.verify(world, actions)` | world + plan | `VerificationResult` |
| `guard.approve(world, actions, ...)` | world + plan | `ApprovedPlan` or `None` |
| `guard.simulate(world, actions)` | world + plan (even a refused one) | `ExecutionResult` |
| `repair.replan(result, ...)` | a refused `RunResult` | `RunResult` |
| `runtime.execute(approved, ...)` | an `ApprovedPlan`, or the result carrying one | `ExecutionOutcome` |
| `runs.record(result, ...)` / `runs.load(path)` | a result / a log path | the written record / the records |

### `planner.plan` — instruction to sealed plan

Runs the same bounded **propose → parse → verify → repair** loop the console
runs, and seals a passing plan.  It never executes and never mutates the world
you pass.

```python
result = planner.plan(
    "go to the goal",        # required, non-empty
    world,                   # required: {"robot": ..., "dir": ..., "goal": ..., "walls": [...]}
    backend="api",           # "api" | "local" | "auto" | a registered planner; default auto
    max_tries=3,             # repair attempts, at least 1
    mode=None,               # "live" | "synthetic" | None (unrecorded) — see Provenance
    on_attempt=print,        # called with each attempt record as it is made
)
```

Three ways to ask:

* **`planner=`** — a `Planner` object or any `ask(instruction, world) -> str`
  callable.  This is how a test, a script or a tool runs the loop with no
  network at all, and it is how the examples in this file work.
* **`backend=`** — one of the shipped adapters (`api` Gemini, `local` Ollama,
  `auto` fallback policy) or a name a deployment registered with
  `backend.guard.planner.register_planner`.
* **`plan=[...]`** — a plan you already have, from anything.  No planner is
  consulted; the plan is verified and sealed exactly as a model's answer would
  be, and `planner` reports `"supplied"`.  Passing `backend=`/`planner=` with
  `plan=` is a `ContractError` — two different answers to "who plans this?".

### `guard.verify` — the structured verdict

```python
verdict = guard.verify(world, actions)
# {"ok": False, "reason": "action 1 ({'cmd': 'forward', 'steps': 7}) failed: …",
#  "checks": [{"id": "valid_actions", "label": ..., "ok": True, "detail": ...}, …]}
```

Four checks — `valid_actions`, `in_bounds`, `no_collisions`, `goal_reachable` —
in the order the simulator hits them; `ok` is `True` only when every check is.
A refusal is a result, not an exception: read `reason`.  Malformed input (an
invalid world, an empty plan) is a `ContractError`.

### `guard.approve` — the seal

```python
approved = guard.approve(world, actions, instruction=..., planner=...)
```

Re-runs verification and returns an immutable `ApprovedPlan` — the world
snapshot, the canonical actions and a SHA-256 digest of both — or `None` when
the verifier refuses.  This is the only door to the execution gate.

### `guard.simulate` — demonstration, never approval

```python
shown = guard.simulate(world, actions)      # for any plan, refused ones too
```

The deterministic simulator with `verified: False` and `approval_id: None`,
always.  Use it to show what a plan would do; its result can never execute.
An empty plan is allowed (the world stands still).

### `repair.replan` — one more attempt, told why it failed

```python
refused = planner.plan("go to the goal", world, planner=my_planner, max_tries=1)
if refused["approved"] is None:
    fixed = repair.replan(refused, planner=my_planner, tries=2)
```

Re-asks the *same instruction in the same world*, with the first prompt seeded
by the previous refusal in the exact format the guard's own repair loop uses:
the verifier's feedback and the refused plan — never a model transcript.  The
planner is the one you pass, or the shipped adapter the refused result came
from (`api` / `local` / `auto`); a result produced by a supplied plan or a
scripted reader needs `planner=` or `backend=`, because replan never silently
picks a model the previous run did not use.  `repaired` is `True` on a result
whose plan came from repair rather than a first try.

### `runtime.execute` — approved plans only

```python
outcome = runtime.execute(result)          # or guard.approve(...) directly
```

Accepts exactly two things: the sealed `ApprovedPlan`, or the `RunResult` that
carries one.  A plan list, a world, a refused result, a `guard.simulate`
demonstration, a hand-rolled mapping — each raises `NotApprovedError` before
the simulator is touched.

Nothing runs on trust either: the guard re-verifies the sealed world snapshot
and recomputes the approval digest first.  A plan whose actions or world were
edited after approval (or whose `approval_id` was replaced) returns
`execution.verified: False` with an empty log, and `reason` says what happened.

### `runs.record` — the run's own facts, written where the platform reads them

```python
record = runs.record(result, execution=outcome)      # → logs/runs.jsonl by default
print(record["run_id"])                              # 12 hex characters
history = runs.load()                                # oldest first, [] when no file
```

One JSONL line per call, in the same schema the console's Run History and
RobotBench write (see `docs/CONTRACTS.md`): a field the run does not have is
`null` — *not recorded*, never a plausible default — and secrets are redacted
before the write.  `actions` and `world` together make the record replayable by
the simulator alone.  `result` may also be an `ExecutionOutcome` on its own:
its approval supplies the instruction and plan, and its execution is recorded
automatically.  `execution=` accepts the outcome, the bare execution result, or
a `{"ran", "halted", "steps"}` summary; the end position is derived from it
when the simulation really stepped.

## Result shapes

Every result is a plain mapping.  Within the current major version these keys
do not disappear and do not change meaning; adding a key is not a breaking
change.

### `RunResult` — from `planner.plan` and `repair.replan`

| Key | Meaning |
|---|---|
| `api_version` | `"1.0"` — the contract version every result carries |
| `instruction` | the instruction this run was asked (the original one, on a replan) |
| `world` | the canonical world the run was about |
| `planner` | which planner answered: `"api"`, `"supplied"`, a registered name, … |
| `mode` | `"live"`, `"synthetic"`, or `None` — see Provenance |
| `approved` | the sealed `ApprovedPlan`, or `None` when the guard refused |
| `reason` | one sentence saying what happened, from the run's own facts |
| `actions` | the verified plan, or `None` |
| `attempts` | attempts this call made |
| `repaired` | the plan came from repair, not a first try |
| `verification` | the `VerificationResult` (or `None` when nothing was runnable) |
| `simulation` | always `None`: planning does not simulate |
| `execution` | always `None`: planning never executes |
| `latency` | wall-clock seconds measured inside the guard |
| `history` | one record per attempt — `attempt`, `ok`, `feedback`, `actions`, and no prompt or reply |
| `run_id` | `None` until `runs.record` |
| `error` | a readable, redacted error, or `None` |

### `ExecutionOutcome` — from `runtime.execute`

| Key | Meaning |
|---|---|
| `api_version` | `"1.0"` |
| `approved` | the plan that was executed (or refused) |
| `reason` | one sentence: executed + reached/halted, or refused and why |
| `actions` | the sealed plan |
| `attempts` | carried from the `RunResult` when one was passed; `None` for a bare `ApprovedPlan` |
| `verification` | the verdict recomputed for the sealed plan before stepping |
| `simulation` | always `None`: this is an execution |
| `execution` | `ExecutionResult`: `{"ok", "reached", "world", "log", "verified", "approval_id"}`, plus `refused` when it was refused |

`execution.verified` is `True` only for an approved plan that stepped.

## Errors

| Error | Raised when | What it means |
|---|---|---|
| `ContractError` (a `ValueError`) | the request is malformed: an invalid world, an empty plan, a non-string instruction, `max_tries < 1`, an unknown backend, an unknown `mode`/`input_type`, `backend=` together with `planner=`, replanning an already-approved result | a typo, answered by the contract |
| `NotApprovedError` | `runtime.execute` was given anything but an approved plan | nothing executed; use `guard.simulate` to demonstrate an unapproved plan |

A **refusal is a result, not an exception**: a plan the verifier rejects comes
back with `approved: None` and the verifier's own `reason`, and a refused
execution comes back with an empty log and `verified: False`.

## Provenance: live vs synthetic

`mode` says whether a model really answered:

* `"live"` — a real model call (`api`, `local`, `auto` planners);
* `"synthetic"` — a scripted planner answered (its name says so: `dry`,
  `scripted`, `fake`);
* `None` — not recorded.  A caller's own planner, or an unknown name, is never
  guessed to be either, and a supplied plan is not a provenance at all.

Pass `mode=` to state it yourself when you know better — only the caller can.
The run log stores the same two values and `null` for unrecorded, so a
benchmark can separate live measurements from scripted ones.

## Versioning

`backend.api.contracts.API_VERSION` is the version of every shape in this
document, and every result carries it as `api_version`.  Within a major version
the documented keys do not disappear and do not change meaning; a new key is
not a breaking change, and callers should read only the keys they need.

## Reaching the guard without the API

`backend.guard` is the same pipeline one level down — the unversioned
internals the API wraps, documented in `docs/CONTRACTS.md`.  New code should
use `backend.api`; the console keeps using `backend.guard` through
`frontend/panels/engine.py`.
