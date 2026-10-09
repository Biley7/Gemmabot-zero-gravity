# GemmaBot — Production-Readiness Audit & Safe Fixes

**Date:** 2026-10-09
**Branch / HEAD inspected:** `main` @ `48e9245` (+ the working-tree fixes listed in §12)
**Method:** read the running code first, then apply only safe foundational fixes.
Every claim below was verified against the tree (commands and outputs are quoted);
nothing is inferred from earlier audit documents.

**Overall readiness: RED — not production-ready.** The verification core is real
and now live-verified; productionization (timeouts, auth, CI) is not done.

---

## 0. Executive summary

The provided findings were checked one by one. **One of them does not survive
verification** (no credential was ever committed), **one is already fixed on
HEAD** (map-switch stale results), and the rest are accurate. Along the way a
**new, real provenance bug was found and fixed** (a scripted Safety-Lab run was
logged as `mode="live"`).

| # | Provided finding | Verdict | Evidence |
|---|---|---|---|
| 1 | Working Gemini key in committed `.env.example`, in Docker context | **REFUTED** — never committed | §D, §13.1 |
| 2 | Treat the key as compromised / rotate | **AGREED** — key exists only in local untracked `.env` | §13.1 |
| 3 | Stale-result UI on map switch | **ALREADY FIXED on HEAD**; residual was intentional. Hardened + pinned | §F |
| 4 | Documented stub APIs vs real `engine.py`/`harness` | **CONFIRMED as docs drift** — stubs were deleted, docs were not | §C |
| 5 | Local Ollama not live-verified | **NOW LIVE-VERIFIED** | §13.2 |
| 6 | Auto fallback only verified with mocks | **NOW LIVE-VERIFIED** | §13.2 |
| 7 | Checked-in benchmark results are synthetic | **CONFIRMED** (already labelled). Related provenance bug **found + fixed** | §13.3 |
| 8 | A real API planning call took ~183.6 s | **CONFIRMED RISK** — no timeout; top blocker | §I |
| 9 | MapVision live inference unverified | **NOW LIVE-TESTED** — works, but inaccurate on the sample | §13.2 |
| 10 | Runtime Python environment inconsistent | **CONFIRMED**; normalized in docs/manifest | §E |

---

## A. Actual architecture map

```
app.py                            1428 lines  Streamlit entry point + session state
engine.py                           23 lines  compat shim -> frontend/panels/engine.py
ui_helpers.py                        9 lines  compat shim -> frontend/simulation/ui_helpers.py

frontend/                           22 files   panels + design system + simulation
  panels/engine.py                 590 lines   Streamlit-free orchestration (the real "service")
  panels/{brain,safety,vision,replay,benchmark}.py   the five labs
  components/{colors,spacing,typography,theme,animations,components,blocks}.py
  simulation/{ui_helpers,player,player_view}.py
  state/, animations/                          EMPTY packages (docstring only)

backend/                            9 files    the logic
  planner/planner.py                           ask_api, ask_ollama, parse_plan
  verifier/harness.py                          verify_plan, dry_run, plan_with_repair  ← real verifier
  vision/map_vision.py                         read_map, check_world_report, ask_vision_*
  logger/logger.py                             log_run, load_runs, summarize_run, redaction

gemmabot/                           10 files
  simulator.py, prompts.py, config.py, benchmark.py          real
  planner.py, harness.py, logger.py, map_vision.py           3–9 line re-export shims
  schemas.py                                                 DEAD (imported by nothing)

tests/                              20 files   443 passing tests
```

## B. Active runtime path

```
app.py
  → engine.run_plan()                       (frontend/panels/engine.py)
      → engine.get_ask(backend)             api | local(ollama) | auto | dry
      → backend.verifier.harness.plan_with_repair()
            parse → verify_plan → dry_run → repair (bounded by max_tries)
      → engine.verify_run()                 the four checks, re-reported
  → GATE: engine.verified_actions(result)   present AND verification["ok"] is True
      → frontend.simulation.player.build_timeline()
          → engine.execute() (deep copy) → gemmabot.simulator.step()
  → backend.logger.log_run() (JSONL, redacted, with mode provenance)

Vision:  app → engine.run_map_vision → backend.vision.map_vision.read_map
         → check_world_report (3 checks) → "Load into simulator" gate
```

The documented path is not the runtime path (no `service.py`) — see §C.

## C. Dead / stub architecture

| Item | Status | Evidence |
|---|---|---|
| `gemmabot/schemas.py` | **DEAD, contradicts runtime** | 6 TypedDicts, zero importers; its `VerifyResult`/`RunResult` shapes do not match `verify_plan` | 
| `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md` | **were outdated** | both named `service.py`, `verifier.py`, `repair.py`, `world_validation.py`, `frontend/components.py`, `frontend/state.py` — six stubs deleted in `8b11a1f` |
| `frontend/state/`, `frontend/animations/` | empty packages | 1-line docstring `__init__.py`, no modules |
| 6 compatibility shims | re-export only | `gemmabot/{planner,harness,logger,map_vision}.py`, root `engine.py`, `ui_helpers.py` |
| `tests/test_{planner_parse,repair,world_validation}.py` | **assert nothing** | `@pytest.mark.skip(reason="not implemented yet")` |
| tracked 0-byte file with a corrupted path | hygiene | `[gemmabot-final-prototype-audit.canvas.tsx](http:/_vscodecontentref_/19)` + two stray dirs |

**Fixed here:** `docs/ARCHITECTURE.md` and `docs/CONTRACTS.md` now describe the real
tree and real shapes. `gemmabot/schemas.py` and the placeholder tests are left in
place (removal is a change the user should authorize); both are flagged as blockers.

## D. Security issues

| Finding | Severity | Evidence |
|---|---|---|
| **No committed credential** | — | `git log --all -p` scanned: `.env.example` held an *empty* value before `083e652` and `your_api_key_here` after; no `.env` blob ever; no `AIza`/`AQ.`/`sk-` shape in any blob |
| Live key in local `.env` (53-char `AQ.` style), untracked | **rotate if ever shared** | `git check-ignore .env` → ignored; it is not in history |
| `.gitignore`/`.dockerignore` ignored only the exact name `.env` | **MEDIUM → FIXED** | now `.env`, `.env.*`, `!.env.example`, `**/.env*`, `**/*.pem`, `**/*.key`, `**/*.p12`, `**/credentials.json`, `**/service-account*.json` |
| Raw exception text shown in the UI (could embed the key) | **MEDIUM → FIXED** | found a real leak: `harness.plan_with_repair` put `ask() raised an error: <exc>` into history/UI. Now redacted at source in `harness`, `map_vision`, `benchmark`, and the engine |
| Unauthenticated, CORS-open, unmetered public surface | **HIGH (open)** | `.streamlit/config.toml` `enableCORS=false`; no auth/rate limit |
| No lock file / hashes; `pytest` shipped in runtime requirements | **LOW → FIXED (pytest split out)** | `requirements-dev.txt` added |
| Docker build context | static review | `.dockerignore` hardened; **image not built** (Docker daemon not running) |

## E. Environment / configuration issues

* Interpreters disagreed: `runtime.txt` 3.11.9, Docker `python:3.11-slim`, dev
  machine `/usr/local/bin/python3.14` (3.14.7), bundled `.venv` **3.9.6 with no
  Streamlit** (a trap — gitignored).
* `MAX_REPAIRS` in `.env` was **ignored** (hardcoded 2); `load_dotenv()` ran in
  `app.py` *after* `gemmabot.config` was imported, so env overrides didn't apply.
* **Fixed:** `gemmabot/config.py` is now self-contained (loads `.env` once, reads
  `MAX_REPAIRS`/model ids from the environment with safe fallbacks), exposes
  `api_key()` / `has_api_key()` / `missing_api_key_message()`, and `.python-version`
  (3.11) + README document the supported range (3.11–3.14).

## F. State-management issues

The old report's defect ("previous `text_result` remained visible after switching
maps") is **fixed on HEAD**: `_adopt_world()` calls a clear on every map move. I
re-verified it with an AppTest probe (text run → switch map → `text_result`,
`replay`, `last_run`, `logs`, `safety_result` all cleared, "Goal reached"
disappeared).

Residual gaps, now closed or documented:

* `_clear_results()` did not clear `log_replay`/`log_replay_autoplay` or the
  autoplay flag → renamed to **`_clear_run_state()`** and extended; a rendered
  log replay is now dropped on a map switch (new test).
* **Reset world** now provably clears every run result (new test).
* The Vision Lab keeps its validated reading across map changes **by design** — the
  reading describes the uploaded image, not the map; `vision_loaded` is derived
  from the active map name (documented in the docstring).

## G. Testing gaps

* Baseline: **424 passed / 3 skipped**. The 3 skips are `assert True` placeholders
  whose filenames imply coverage of planner parsing, repair and world validation.
* 100 % of tests are mocked; there is no CI, no coverage measurement, no Docker
  test and (before this session) no live test.
* **Added here:** 19 tests (config fail-safe, the execution gate, error redaction,
  honest failure telemetry, full reset, log replay clearing, log provenance) →
  **443 passed / 3 skipped / 0 failed**.

## H. Deployment issues

* Dockerfile is sound (multi-stage, non-root, healthcheck); `render.yaml` is
  consistent. **The image was never built here** — the Docker daemon isn't running.
* `RUN_AND_DEPLOY.md` described a no-op self-test and a deleted-stub table; both
  are corrected, and `python -m gemmabot.harness` now really runs the verifier
  self-test (verified: prints `All tests passed.`, exit 0).
* No auth, no rate limiting, no per-run cost ceiling. CORS is disabled.

## I. Performance risks

* **No timeout and no cancellation on any model call.** Historical runs measured
  0.10 s → 251.87 s; the user reports a real API planning call at ~183.6 s.
* `auto` falls back only on an *exception*, so a hang cannot fall back.
* `genai.Client()` is re-created on every call.
* This session's live local measurements: single Ollama plan call **52.2 s**;
  auto-fallback call **79.7 s**; a 2-attempt local loop **121.6 s**; live vision
  **26.8 s**.
* **Not fixed:** bounding model calls and adding cancellation is a design change
  beyond "safe foundational fixes" and was deliberately left out (top blocker).

## J. UI / UX risks

* The core promise ("nothing executes until code verifies it") is only in
  captions/tooltips; the animation is more prominent than the checklist.
* The player iframe duplicates a CSS layer and bypasses the design system.
* No visual regression evidence (screenshots are not capturable in this environment).
* Not redesigned, per instruction.

---

## 12. Fixes implemented (safe, foundational)

| Area | Change |
|---|---|
| Secrets | `.env.example` rewritten with clearly fake `REPLACE_WITH_YOUR_OWN_KEY` placeholders and a warning; malformed `[TEMPLATE]` line removed |
| Ignore rules | `.gitignore`: `.env*` + `!.env.example` + `*.pem/*.key/*.p12/credentials.json/service-account*.json`; `.dockerignore`: same at any depth (`**/.env*`, `**/*.pem`, …) |
| Docker/docs key shapes | `Dockerfile`, `RUN_AND_DEPLOY.md` no longer show an `sk-…` Google key example |
| Fail-safe config | `gemmabot/config.py`: env-driven `MAX_REPAIRS`, `api_key()/has_api_key()/missing_api_key_message()`; one `load_dotenv()` for every entry point |
| Fail-safe calls | `ask_api` / `ask_vision_api` raise a readable error **before** any client/network call when no key is configured |
| Redaction | `logger.redact_secrets()`; harness/vision/benchmark/engine scrub exception text before it reaches history, the UI or a log; the UI's error fallback is redacted too |
| Execution gate | `engine.verified_actions()` — a plan must be present + non-empty **and** `verification["ok"] is True`; `app.py` uses it for both execution and for the success/failure outcome branch |
| State | `_clear_run_state()` clears logs, text_result, replay, both autoplay flags, last_run, safety_result, log_replay; called by map switch, Reset world and vision load |
| Provenance | **Bug fix:** a dry Safety-Lab run was logged with `mode=live` (it used the sidebar engine's mode); it now logs `mode=synthetic`, matching the planner that really ran |
| Self-test | `python -m gemmabot.harness` forwards to the real verifier self-test (was a silent no-op, exit 0) |
| Docs | `docs/ARCHITECTURE.md` + `docs/CONTRACTS.md` rewritten from the real tree; `RUN_AND_DEPLOY.md` stub table, test count and key examples corrected |
| Environment | `requirements.txt` (runtime) / `requirements-dev.txt` (adds pytest) split; `.python-version` (3.11); README updated |

## 13. Verification evidence

### 13.1 Security

```
$ git log --all -p | grep -oE "GEMINI_API_KEY=[^ \"']+"   → 4× your_…, 1× sk-..  (placeholders only)
$ git log --all -S "Ab8RN6IOrm" --oneline                 → (empty; key never committed)
$ git check-ignore -v .env .env.local .env.production …   → all ignored; .env.example NOT ignored
```

### 13.2 Live model paths (previously unverified)

```
live_ollama: OK in 52.2s; parsed actions = 7
live_auto_fallback: backend='ollama' latency=79.7s  (API pre-check raised; Ollama answered;
                    that reply was malformed JSON → actions=none, i.e. nothing executed)
live_local_loop: attempts=2 latency=121.6s actions=present
                 verification.ok=True {valid_actions,in_bounds,no_collisions,goal_reachable}=True
                 gate=ACCEPTED execute ok=True reached=True (goal [6,5])
live_vision (Ollama + built-in sample image): world=yes, check_world=True, latency=26.8s
                 but the reading differed from the drawn world (dir S vs E, goal [7,6] vs [6,5])
```

**Conclusion:** the local backend, the auto fallback and the live vision path all
work end-to-end. Live perception **accuracy** is not established — on a sample drawn
from `new_world()` the model returned a different (valid) world.

### 13.3 Browser smoke (live Streamlit at 127.0.0.1:8501)

* App starts, `/_stcore/health` → 200; all five tabs render; no console errors from the app.
* "Check connections" → API key *set*, Ollama *reachable*.
* Dry "Run safety check" → timeline `✓ Proposal 1 → ✕ Collision 1 → ↻ Repair → ✓ Proposal 2 → ✓ Safe`,
  collision cell `[3, 0]`, LAST RUN `2 / 3 · 0.00 s · dry · Verified safe`.
* The run was logged `backend='dry' mode='synthetic'` **after** the provenance fix
  (before the fix it was `mode='live'` — the bug this session found).

## 14. Test results (final)

```
$ /usr/local/bin/python3.14 -m pytest -q -rs
443 passed, 3 skipped in 2.56s        exit status: 0
```

| Metric | Value |
|---|---|
| Tests passed | **443** |
| Tests skipped | **3** (`test_planner_parse`, `test_repair`, `test_world_validation` — pre-existing placeholders) |
| Tests failed | **0** |
| Tests added this session | 19 |

## 15. Security status

* **No credential in Git history or in `.env.example`.** The previously reported
  "committed working key" is not reproducible.
* A live 53-character `AQ.`-style key sits in the **untracked, ignored** local
  `.env`. **Recommendation: rotate it** (it cannot be ruled out that the directory
  was shared, and `AQ.` keys defeat `AIza`-only scanners).
* `.env`, every `.env.*`, `secrets.toml` and common credential file shapes are now
  excluded from both Git and the Docker build context; the image build itself is
  **unverified** (Docker daemon down).
* Displayed error text is now redacted; a real leak path through harness history
  was found and closed.
* **Open:** the deployment surface is unauthenticated, CORS-open and unmetered.

## 16. Remaining production blockers (not fixed — by design)

1. **Unbounded, uncancellable model calls** (~52–252 s measured; user reports
   ~183.6 s). No timeout, no Stop, `auto` cannot fall back from a hang.
2. **No authentication / rate limiting / spend ceiling** on any deployment.
3. **No CI, no coverage**, and 3 no-op test files still imply coverage.
4. **Docs drift partly persists** at the repo root (`BACKEND_AUDIT_REPORT.md`,
   `FINAL_PROTOTYPE_AUDIT_REPORT.md` still carry obsolete claims; the latter has a
   false CRITICAL about the committed key). `gemmabot/schemas.py` was still dead
   at audit time — **since resolved, see §17**.
5. **No programmatic API** — only Streamlit drives the engine.
6. **Docker image never built** in an audit; version drift remains local.
7. **Vision perception accuracy unverified** on real photos (the live path runs).
8. Run log has **no run IDs**, and it now contains one legacy record mislabelled
   `mode: live` from before the provenance fix (local, untracked file only).
9. Tracked 0-byte file with a corrupted VS Code path plus two stray directories.

## 17. Phase-1 architecture update (same day, after this audit)

A product-architecture refactor landed after the audit above. It changes
structure, not the verdict:

* **GemmaBot Guard** (`backend/guard/`) is now the verification core:
  `plan()` → `approve()` → `execute()`, with model-agnostic planner adapters
  (`api` / `local` / `auto` / registry) in `planner.py` and the canonical
  contracts in `contracts.py`.
* **Execution requires an approved plan.** `execute()` refuses anything that is
  not a digest-sealed `ApprovedPlan`, re-verifies it against the sealed world
  snapshot and re-checks the digest before stepping — the UI cannot force a
  plan through (`tests/test_guard.py`).
* **One parser** (`backend/parsing.py`) serves the planner, repair loop and map
  vision; the previous per-call parsing is gone.
* **Blocker 3 partly closed:** the 3 placeholder test files are now real
  (planner parsing, repair loop, world validation) and the guard has its own
  suite.
* **Blocker 4 partly closed:** `gemmabot/schemas.py` was deleted; live docs
  (`ARCHITECTURE`, `CONTRACTS`, `README`, `RUN_AND_DEPLOY`) describe the guard.
  Root audit reports remain historical and were not rewritten.
* Blockers 1, 2, 5 and the unauthenticated deployment surface are unchanged.

## 18. Not claimed

* Not "production-ready" — blockers 1–3 alone preclude it.
* Not "vision works" — a live reading was produced and validated, but it did not
  match the ground-truth world.
* Not "secure deployment" — no auth, no metering.
* Not "benchmarks prove performance" — the stored artifact is synthetic
  (`mode=synthetic`, `backend=dry`, 0.000 s), and its own header says so.
