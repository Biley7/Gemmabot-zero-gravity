# GemmaBot Final Prototype Audit and Readiness Report

**Audit date:** 5 October 2026  
**Audit type:** Read-only functional, integration, demo-readiness, and security audit  
**Repository:** Gemmabot MLH hackday

## Executive Verdict

**NO-GO for public sharing or a judge demo until the exposed Gemini API credential is revoked and rotated.** The current application does demonstrate its core architecture end to end: a real API response was accepted by Python verification, executed by the simulator, and reached the goal. However, the same working credential is present in the committed `.env.example` and is copied into a Docker image by the current build configuration. The secret value is intentionally omitted from this report.

There is also material live-demo risk: the single successful API planning call took **183.627 seconds**, and no local Ollama model was reachable in the audit environment. After credential containment, the prototype is functionally demonstrable with an available API backend, but the latency and lack of tested live fallback need a rehearsal plan.

No source or configuration files were changed during the audit. This Markdown report was added to the repository root; pre-existing local files and untracked work were left untouched.

## Audit Scope and File Mapping

The repository’s current files are authoritative. Several filenames named in the audit request do not exist at the repository root; the equivalent implementations are:

| Requested name | Actual file or result |
|---|---|
| `robot_sim.py` | Not present; simulator is [gemmabot/simulator.py](gemmabot/simulator.py). |
| `harness.py` | Not present at root; active harness is [gemmabot/harness.py](gemmabot/harness.py). |
| `logger.py` | Not present at root; implementation is [gemmabot/logger.py](gemmabot/logger.py). |
| `benchmark.py` | Not present at root; implementation is [gemmabot/benchmark.py](gemmabot/benchmark.py). |
| `mapvision.py` | Not present; implementation is [gemmabot/map_vision.py](gemmabot/map_vision.py). |
| `pyproject.toml` | Not present; dependencies are in [requirements.txt](requirements.txt). |
| Main application | [app.py](app.py), supported by [engine.py](engine.py) and [ui_helpers.py](ui_helpers.py). |
| Architecture and contracts | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/CONTRACTS.md](docs/CONTRACTS.md), and [docs/WORKFLOW.md](docs/WORKFLOW.md). |

The active text workflow is `app.py → engine.run_plan → gemmabot.harness.plan_with_repair/dry_run → engine.execute → gemmabot.simulator.step`. The documented `gemmabot.service.run_instruction` route is not the path used by the application.

## Verification Summary

| Check | Verdict | Observed evidence |
|---|---|---|
| Full test suite | **PASS with skips** | `pytest`: 72 passed, 4 skipped. The skipped tests are explicit placeholders for planner parsing, repair, verifier, and world validation. |
| Python syntax | **PASS** | All present application, backend, and frontend Python modules compiled under Python 3.14. The requested root-level filenames listed above are absent; their existing equivalents were compiled. |
| Streamlit startup | **PASS** | Streamlit started on `127.0.0.1:8503`; `/_stcore/health` returned `ok`; the browser rendered the GemmaBot title, controls, tabs, and simulator board. The temporary server was stopped after testing. |
| Live API proposal through simulator | **PASS, high latency** | One real API call produced a plan; Python verification accepted it; simulator execution ended at `[6, 5]`; goal check returned true. One attempt, 183.627 seconds. |
| Ollama live connection | **UNAVAILABLE** | Connection check found no reachable Ollama server or models. No real local inference was run. |
| Map vision live inference | **NOT RUN** | Map parsing and validation were exercised with controlled fake model replies; no live vision request or real uploaded-image inference was performed. |
| Source modifications | **NONE** | Audit probes used controlled replies or temporary storage; existing local/untracked work was preserved. |

### Runtime Note

The explicit `.venv/bin/python` points to Python 3.9 and does not have the project dependencies installed. `pytest` and `python3` resolve to the system Python 3.14; the Streamlit launcher wrapper targets `.venv/bin/python3.14`, which successfully served the browser app. Use a consistent Python 3.14 environment when repeating these checks; the `.venv/bin/python` alias is inconsistent and should not be assumed to be the runtime used by the successful app launch.

## Core Workflow: Input to Visible Result

**Live input used:** `Move the robot to the goal using a safe route.`  
**Backend:** API  
**Maximum attempts:** 1

| Stage | Observed result |
|---|---|
| User instruction | Passed to the real configured API planner. |
| AI proposal | Returned a JSON action plan on the first attempt. The plan contained 10 actions. |
| Parse and Python verification | Plan parsed and passed `dry_run` against the current default world, including its walls and goal. |
| Execution | Accepted plan was passed to the simulator; final robot position was `[6, 5]`. |
| Goal check | `reached_goal` returned true. |
| Latency | 183.627 seconds for planning/verification; simulator execution was not the source of the delay. |
| UI evidence | Streamlit browser rendered the active board and controls. UI/AppTest flows were exercised with controlled plans to avoid a second live request and an extra persistent log entry. |

This proves the **AI proposes → Python verifies → simulator executes** architecture for the current `engine`/`harness` route. A second live prompt using the exact wording “Reach the goal while avoiding the walls” was not separately sent; the successful live world and plan did contain walls, and the controlled tests exercised wall avoidance.

## Simulator and Plan-Safety Tests

The simulator creates an 8×8 world with a valid robot position, direction, goal, and walls. The automated simulator and engine tests cover turning, movement, goal detection, safe execution, and copy isolation. The audit also exercised both turn directions as part of valid execution.

| Input / case | Expected behavior | Observed verdict |
|---|---|---|
| Valid route to default goal | Verify, execute, reach goal | **PASS**; reached `[6, 5]`. |
| Invalid action `{"cmd":"fly"}` | Reject; no accepted plan | **PASS**; harness returned failure, original world unchanged. |
| Malformed model response `not json` | Reject; no accepted plan | **PASS**; bounded retries ended in failure, original world unchanged. |
| Forward into a wall | Reject plan; preserve live world | **PASS**; dry-run rejected and its source world remained unchanged. |
| Forward beyond the 8×8 boundary | Reject plan | **PASS**; eastward move from `[7, 0]` was rejected. |
| Empty action list away from goal | Reject | **PASS**. |
| More than 20 actions | Reject under configured plan-length guard | **PASS**; 21-action plan was rejected before simulation. |
| Invalid plan then valid repair response | Retry with verification feedback; accept only corrected plan | **PASS** in controlled fake-response tests. |
| Every attempt invalid | Stop at configured attempt limit | **PASS** in controlled tests; no unbounded loop and no invalid execution. |
| Model/API exception | Surface failure; do not execute | **PASS** in controlled tests; `run_plan` returns no actions and leaves the input world unchanged. |

The app only calls `engine.execute` when `result["actions"]` is not `None`. `dry_run` operates on a deep copy and uses the same simulator step function as execution. The separate public `engine.execute` function itself does not independently enforce that its caller supplied a verified plan; the demonstrated UI call path provides that gate.

## Backends

| Backend mode | Test performed | Verdict |
|---|---|---|
| API | Real single-attempt request, verified and executed | **PASS**, 183.627 seconds. |
| Local | Connectivity check and controlled function-dispatch tests | **LIVE UNAVAILABLE**; no Ollama server/model reachable. Function selection is covered by fakes. |
| Auto | API-failure → local-fallback controlled test | **PASS WITH MOCKS**; fallback reply was reported as `ollama`, not silently as API. A live fallback was not possible because Ollama was offline. |
| API exception / malformed result | Controlled failure tests | **PASS**; the harness reports failure and does not return executable actions. |

Do not describe Local or Auto fallback as live-verified in this environment.

## MapVision and Map Continuity

The `gemmabot.map_vision` test suite uses fake vision responses and covers valid map acceptance, invalid JSON retry, robot-on-wall rejection, goal-on-wall rejection, out-of-bounds coordinates, robot equal to goal, unreachable goals, and a failed first attempt followed by a valid second attempt. Those checks passed as part of the 72-test suite.

The engine-level image-to-world-to-plan-to-execution continuity test passed with fake vision and planning responses. A Streamlit state test also activated a validated scanned world and confirmed that robot position, direction, goal, and walls were copied unchanged into the active world. The audit did **not** verify perception accuracy on a real uploaded photograph or with a live vision model.

## UI, State, and Result Realism

The browser showed the actual simulator render and Streamlit controls. The board is rendered from `simulator.render`; attempt history and planning latency/backend/status are populated from the engine result, not invented by the UI. The separate Benchmark tab displays the checked-in Markdown artifact, not a benchmark run triggered by the UI.

| State action | Observed result |
|---|---|
| Run a controlled valid text plan | Board moved to the goal; result and telemetry rendered. |
| Switch from a completed run to another map | Active world changed, but the previous `text_result` remained visible. **Stale-result UI defect.** |
| Reset world | Restored the selected map and cleared `text_result` and execution log. The prior sidebar `last_run` telemetry remained. |
| Use scanned map | Promoted the validated scanned world without changing its coordinates, heading, goal, or walls. |
| Tabs and upload | Text, Scan Map, and Benchmark tabs were present in the browser. Separate tab-switch persistence and a real file upload/live Scan Map model flow were not performed. |

The stale result after map selection is a non-blocking demo UX issue, but it can make the board and displayed plan refer to different worlds. Reset currently clears the full text result but leaves the previous telemetry summary.

## Logging and Benchmarking

### Logging

`logger.load_runs()` loaded 15 existing JSONL records: 13 marked successful and 2 failed. Records were in newest-last order. Isolated tests in a temporary directory verified success/failure writes, load order, summaries, and redaction of a synthetic API-key marker. A value-free scan found the configured key was not present in the existing run log.

Text command attempts are appended through `logger.log_run`. MapVision attempts are held in Streamlit session state but are not sent to this run logger, so they are not persisted by the same run-history mechanism. The live API test was run directly through the engine to avoid adding an audit-generated record to the repository log.

### Benchmark

The stored `benchmarks/results.md` reports 100% success for both `api` and `ollama` with near-zero latency. The benchmark implementation’s `--dry` mode uses hard-coded fake plans and produces synthetic results of this shape. An isolated 30-run dry benchmark passed all cases and wrote its output only to a temporary directory.

The checked-in results do not identify whether they came from dry mode. Treat them as **synthetic/non-live evidence**, not measured API or Ollama performance. No real-model benchmark was run during this audit.

## Architecture and Test Gaps

The current active path works, but it is not the architecture path described in the repository contracts. `app.py` calls `engine.py`; the documented `gemmabot.service.run_instruction` API raises `NotImplementedError`. `gemmabot.verifier.verify_plan`, `gemmabot.repair.repair_plan`, `gemmabot.world_validation.validate_world`, and the `frontend/state.py` and `frontend/components.py` APIs are also stubs. The working verification/retry implementation is `gemmabot.harness.dry_run` and `plan_with_repair`; MapVision has its own `check_world` validator.

The four skipped tests are placeholders for planner parsing, repair, verifier, and world validation. Their existence must not be counted as passing validation of those stubs. These gaps do not block the current engine/harness demo route, but the documented service boundary and standalone APIs are not operational.

## Security Findings

### Critical: working credential committed and included in Docker context

A non-placeholder `GEMINI_API_KEY` is present in the committed `.env.example`. A value-free comparison confirmed it matches the local `.env` credential, and that configured credential successfully authenticated the live API call. The exact value is redacted here.

The Dockerfile uses `COPY . .`. `.dockerignore` excludes `.env` but does not exclude `.env.example` or all `.env`-prefixed files. Therefore the committed credential is included in the Docker build context/image. `.gitignore` also ignores only the exact `.env` name; an additional local environment-like file is untracked and not ignored. The key should be treated as compromised.

**Required before sharing/demo:** revoke the exposed key and create a replacement; ensure the replacement is not stored in tracked templates or build contexts; correct ignore/build exclusion patterns; remove the exposed value from repository history and any distributed images; then rebuild and verify the image. These are recommendations only; no remediation was performed during this audit.

### Additional security and deployment notes

- Search of Python source found no `eval()` or `exec()` usage. The UI does use `unsafe_allow_html=True` for the simulator grid; generated cell text is HTML-escaped by `ui_helpers.grid_html` and the glyphs come from the simulator renderer.
- Streamlit started with `enableCORS=false` and emitted a warning about broad cross-origin access, including WebSockets. Restrict trusted origins before exposing the app publicly.
- The API key was not found in the existing run log. The logger’s exact-value redaction was separately verified in isolated temporary storage.

## Final Readiness Decision

| Dimension | Verdict |
|---|---|
| Core proposal → verify → execute workflow | **WORKS**, demonstrated once with a real API response and simulator goal success. |
| Invalid-plan safety and repair bounds | **WORKS** on the active harness path with controlled failure cases. |
| Streamlit app and visible result rendering | **WORKS**; browser load, health endpoint, and controlled UI flow passed. |
| Live API reliability for a timed demo | **RISKY**; one successful request took over three minutes. |
| Local/Auto live fallback | **NOT READY/UNVERIFIED**; Ollama unavailable. |
| Security for public sharing | **BLOCKED** until the committed working credential is revoked and removed from source/build outputs. |
| Full documented architecture contract | **INCOMPLETE**; service and scaffold APIs remain stubs. |

**Recommendation:** Do not publish, push, or build/share the current repository/image with the exposed key. After rotating and containing the credential, rehearse the API path with a strict time budget and prepare a fallback/demo recording because local Ollama was unavailable and the measured live call was unusually slow. Clearly label the checked-in benchmark as dry/synthetic unless replaced by a recorded real-model benchmark.
