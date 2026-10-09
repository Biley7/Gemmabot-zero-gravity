# ── GemmaBot — production Dockerfile ──────────────────────────────────────
# Multi-stage: builder installs deps, runner is the slim runtime image.
# Build:  docker build -t gemmabot .
# Run:    docker run -p 8501:8501 -e GEMINI_API_KEY=REPLACE_WITH_YOUR_OWN_KEY gemmabot
# --------------------------------------------------------------------------

# ── Stage 1: dependency builder ────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools needed by some wheels (e.g. grpcio in google-genai)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ───────────────────────────────────────────────────────
FROM python:3.11-slim AS runner

# Non-root user for security
RUN useradd --create-home --shell /bin/bash app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=app:app . .

# Create runtime directories the app writes to
RUN mkdir -p logs benchmarks assets && chown -R app:app logs benchmarks assets

USER app

EXPOSE 8501

# Health-check: Streamlit serves /_stcore/health
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" \
    || exit 1

# Streamlit flags:
#   --server.address=0.0.0.0   → accept external connections
#   --server.headless=true     → no browser auto-open, no CORS warnings
#   --server.fileWatcherType=none → avoids inotify errors in containers
ENTRYPOINT ["python3", "-m", "streamlit", "run", "app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--server.headless=true", \
    "--server.fileWatcherType=none"]
