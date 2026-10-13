# Gemmabot

A virtual 8x8 grid robot planned by Gemma, shown in a Streamlit app.

**AI proposes. GemmaBot verifies. Only approved actions execute.**

## Setup

1. Create a virtual environment with a supported interpreter
   (3.11–3.14; `.python-version` and the Docker image pin 3.11):

   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies (add `-r requirements-dev.txt` to run the tests):

   ```bash
   pip install -r requirements-dev.txt
   ```

3. Configure environment variables:

   ```bash
   cp .env.example .env
   # Replace the placeholder in .env — never commit a real key
   ```

## Run

Start the Streamlit app:

```bash
streamlit run app.py
```

Without a Gemini key the app still runs Local (Ollama) and the scripted dry
modes; the API engine fails with a readable message before any network call.

## RobotBench

The **Benchmark** tab is RobotBench: it evaluates AI-generated robot plans
against deterministic simulation scenarios, and it measures nine things —
success rate, verification rejection rate, repair rate, repair success rate,
average actions, average attempts, latency, collision rate and boundary
violation rate.  Every metric shows its denominator, its definition (as a
tooltip and as a line on the card) and how many runs it rests on.

```bash
python3 -m gemmabot.benchmark --dry                 # scripted reader, no network
python3 -m gemmabot.benchmark --backend both        # real models
```

The runner writes `benchmarks/results.json` (one record per run, each naming its
dataset, scenario, timestamp and the `run_id` it logged) and
`benchmarks/report.json` / `report.md` (one **result** per comparable cell:
dataset, model, backend, mode, timestamp, run count, success and failure counts
and latency statistics).  A `--dry` run is recorded as `mode: synthetic` and is
never displayed as model performance.  Below 30 runs a result is marked as too
small a sample to compare, because it is.

## Test

Run the test suite (no network required):

```bash
pytest
```

The verifier self-test also runs standalone:

```bash
python3 -m gemmabot.harness
```

## Architecture

```
AI model → Planner adapter → GemmaBot Guard → Approved plan → Simulator
                             (validate · simulate · repair)      (Robot/ROS: not yet)
```

The guard is importable without Streamlit:

```python
from backend.guard import build_planner, plan, execute

result = plan("go to the goal", world, build_planner("auto"))
if (approved := result["approved"]) is not None:   # set only when verification passed
    outcome = execute(approved)                    # re-verified + digest-checked
```

The running architecture — `app.py` → `frontend/panels/engine.py` →
`backend/guard` → `backend/{planner,verifier,vision,logger}` →
`gemmabot/simulator.py` — is documented in `docs/ARCHITECTURE.md`; the canonical
shapes are defined in `backend/guard/contracts.py` and described in
`docs/CONTRACTS.md`.

## Run History

Every run is logged to `logs/runs.jsonl` with its structured metadata (run id,
timestamp, input type, model, backend, attempts, plan length, verification and
execution results, latency, final position, goal reached). The **Run History**
tab filters those records (Success / Failed / Repaired / Vision / Text /
Model/backend), opens any one as **VIEW RUN**, and **REPLAY**s it by feeding the
recorded plan and world back through the simulator and the verifier alone — no
model is called. Records are labelled **LIVE RUN**, **RECORDED RUN** or
**SYNTHETIC BENCHMARK**, and no run is ever fabricated. A record written before
these fields existed still lists, marked *not recorded*.
