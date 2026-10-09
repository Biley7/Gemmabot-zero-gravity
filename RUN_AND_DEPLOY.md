# GemmaBot — Run Locally & Deploy

> **TL;DR** — set `GEMINI_API_KEY`, install deps, run `streamlit run app.py`.

---

## 1. Codebase Health (Audit Summary)

| Area | Status | Notes |
|---|---|---|
| `harness.py` — `dry_run` + `plan_with_repair` | ✅ Fully working | Core propose-verify-repair loop |
| `simulator.py` — `step`, `render`, `reached_goal` | ✅ Fully working | Physics source of truth |
| `planner.py` — `ask_api`, `ask_ollama` | ✅ Fully working | Calls Gemini API or local Ollama |
| `engine.py` — backend selection, `run_plan`, `execute` | ✅ Fully working | Auto-fallback Gemini → Ollama |
| `map_vision.py` — `read_map`, `check_world` (BFS) | ✅ Fully working | Sketch → grid with repair loop |
| `logger.py` — `log_run`, `load_runs`, `summarize_run` | ✅ Fully working | JSONL, secrets redacted |
| `app.py` + `ui_helpers.py` | ✅ Fully working | Streamlit UI; 424 tests pass |
| `backend/verifier/harness.py` | ✅ Fully working | The real verifier: `verify_plan`, `dry_run`, `plan_with_repair` |
| `backend/vision/map_vision.py` | ✅ Fully working | `read_map` + `check_world_report` (3 checks, BFS) |
| `backend/logger/logger.py` | ✅ Fully working | `log_run`, `load_runs`, `summarize_run`, secrets redacted |
| `frontend/panels/engine.py` | ✅ Fully working | Backend selection, `run_plan`, `run_map_vision`, approval + execution |
| `frontend/panels/*` + `frontend/components/*` | ✅ Fully working | The five labs and the design system |
| `backend/guard/*` | ✅ Fully working | Planner adapters, canonical contracts, `plan`/`approve`/`execute` |
| `backend/parsing.py` | ✅ Fully working | The one model-reply parser every layer uses |

**The product pipeline is the GemmaBot Guard**: an AI model proposes, the guard
validates, simulates and repairs, and only an `ApprovedPlan` may execute
(`backend/guard/pipeline.py`). `gemmabot/repair.py`, `verifier.py`,
`world_validation.py`, `service.py` and `frontend/components.py`/`frontend/state.py`
no longer exist — they were empty scaffolding stubs, deleted in `8b11a1f`. The real
verifier is `backend/verifier/harness.py`; the UI-facing interface is
`frontend/panels/engine.py`. `gemmabot/schemas.py` was deleted in the Phase-1
refactor; `backend/guard/contracts.py` is the canonical contract module.**

---

## 2. Run Locally

### 2.1 Prerequisites

- Python 3.11+ (tested on 3.11 and 3.14)
- A [Google AI Studio](https://aistudio.google.com/app/apikey) API key (free tier is fine)
- *(Optional)* [Ollama](https://ollama.com) running locally for the offline/edge mode

### 2.2 One-time setup

```bash
# Clone (or cd into the repo)
cd "Gemmabot MLH hackday"

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install runtime dependencies
pip install -r requirements.txt
# ...and, to run the test suite, the dev extras (adds pytest)
pip install -r requirements-dev.txt

# Copy the env template and fill in your API key
cp .env.example .env
```

Open `.env` and set:

```
GEMINI_API_KEY=REPLACE_WITH_YOUR_OWN_KEY
```

The placeholder is not a credential. `.env` and every `.env.*` variant are
gitignored and excluded from the Docker build context; never commit a real key.

### 2.3 Start the app

```bash
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

### 2.4 Verify the pipeline without an API key (dry run)

```bash
# Runs the harness self-test — wall hit, bad JSON, correct plan, etc.
python3 -m gemmabot.harness

# Full test suite (424 tests, no network required)
python3 -m pytest tests/ -q
```

### 2.5 Optional: enable local Ollama (offline mode)

```bash
# Install Ollama from https://ollama.com, then:
ollama pull gemma4:e4b

# The app will auto-detect it — pick "Local" or "Auto" in the sidebar.
```

---

## 3. Deploy to Render.com (recommended — easiest)

Render's free tier is enough for a hackathon demo. Cold starts take ~30 s on the free plan after 15 min idle.

### Steps

1. Push the repo to GitHub (or GitLab).

2. Go to [render.com](https://render.com) → **New → Blueprint**.

3. Connect your repository. Render reads `render.yaml` automatically.

4. In the **Environment** section that appears, set the one required secret:

   | Key | Value |
   |---|---|
   | `GEMINI_API_KEY` | your Google AI Studio key |

5. Click **Apply** → Render builds the Docker image and deploys.

6. Your live URL will be `https://gemmabot.onrender.com` (or similar).

### What `render.yaml` does

- Uses the `Dockerfile` already in the repo (no extra build command needed).
- Sets the health-check path to `/_stcore/health` so Render knows when the app is ready.
- Declares `GEMINI_API_KEY` as a `sync: false` secret (you fill it in the dashboard, it never touches the YAML file).
- Enables `autoDeploy: true` — every push to `main` redeploys automatically.

---

## 4. Deploy to Digital Ocean App Platform

### Option A — Docker (recommended)

1. Push the repo to GitHub.

2. In the DigitalOcean dashboard → **Apps → Create App → GitHub**.

3. Select your repo and branch.

4. When asked for the **Dockerfile path**, leave it as `./Dockerfile`.

5. Set the **HTTP port** to `8501`.

6. Under **Environment Variables**, add:

   | Key | Value | Encrypted |
   |---|---|---|
   | `GEMINI_API_KEY` | your key | ✅ Yes |
   | `GEMMA_API_MODEL` | `gemma-4-26b-a4b-it` | No |

7. Choose the **Basic / $5 plan** (512 MB RAM is enough; the app has no GPU requirement).

8. Click **Create Resource**. DigitalOcean builds the image and gives you a `.ondigitalocean.app` URL.

### Option B — `doctl` CLI

```bash
# Install doctl: https://docs.digitalocean.com/reference/doctl/how-to/install/
doctl auth init

# Create the app from the spec file (create this once via the dashboard,
# then export it with `doctl apps spec get <app-id>`)
doctl apps create --spec .do/app.yaml   # if you export and save the spec
```

### Health check

DigitalOcean App Platform supports HTTP health checks. Point it at:

```
Path:  /_stcore/health
Port:  8501
```

---

## 5. Deploy via Docker (any host — VPS, EC2, Fly.io, Railway, etc.)

```bash
# Build
docker build -t gemmabot .

# Run locally to test the image before pushing
docker run --rm -p 8501:8501 \
  -e GEMINI_API_KEY=REPLACE_WITH_YOUR_OWN_KEY \
  gemmabot

# Push to Docker Hub (replace <user> with your Docker Hub username)
docker tag gemmabot <user>/gemmabot:latest
docker push <user>/gemmabot:latest
```

On your VPS / server:

```bash
docker pull <user>/gemmabot:latest
docker run -d --restart=unless-stopped \
  -p 8501:8501 \
  -e GEMINI_API_KEY=REPLACE_WITH_YOUR_OWN_KEY \
  --name gemmabot \
  <user>/gemmabot:latest
```

Put Nginx or Caddy in front to terminate HTTPS:

```nginx
# /etc/nginx/sites-available/gemmabot
server {
    listen 443 ssl;
    server_name yourdomain.com;

    location / {
        proxy_pass         http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";  # required for Streamlit WebSocket
        proxy_set_header   Host $host;
    }
}
```

---

## 6. Environment Variable Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | **Yes** (for API mode) | — | Google AI Studio key |
| `GEMMA_API_MODEL` | No | `gemma-4-26b-a4b-it` | Cloud model name |
| `OLLAMA_MODEL` | No | `gemma4:e4b` | Local Ollama model name |
| `MAX_REPAIRS` | No | `2` | Repair loop cap (total tries = MAX_REPAIRS + 1) |

---

## 7. Files Added by This Setup

```
Dockerfile              # Multi-stage Docker build (python:3.11-slim)
.dockerignore           # Excludes .env, tests, __pycache__, etc.
render.yaml             # Render.com blueprint (one-click deploy)
runtime.txt             # python-3.11.9 (for Render/Heroku-style platforms)
requirements.txt        # Pinned dependency versions
.streamlit/config.toml  # Headless server, dark theme, XSRF protection
```

---

## 8. Troubleshooting

**`ModuleNotFoundError: No module named 'google'`**
→ Run `pip install -r requirements.txt` inside your virtual environment.

**`No Gemini API key configured` / 429 rate limit**
→ The API backend fails before any network call when no key is set; in `Auto`
the engine then falls back to Ollama. Make sure Ollama is running
(`ollama serve`) and the model is pulled (`ollama pull gemma4:e4b`), or set
`GEMINI_API_KEY` in `.env` (never commit it).

**Streamlit blank page on Render / DO**
→ Wait 30–45 s for the container to start. Check the deploy logs for Python import errors. The `/_stcore/health` endpoint returns 200 when the app is ready.

**`blocked at [x, y]` on every plan attempt**
→ This is expected behaviour — the model proposed a route that hits a wall. The repair loop will retry up to `MAX_REPAIRS + 1` times automatically. If it keeps failing, try rephrasing the instruction to be more explicit ("go south first, then east").

**Image upload not working on Render free tier**
→ Free tier containers are stateless and have limited memory. The map vision tab works but large images (> 5 MB) may be slow. Keep maze photos under 2 MB.
