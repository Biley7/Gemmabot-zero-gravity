"""Configuration constants for the Gemmabot project.

Owner: BACKEND

Every value can be overridden from the environment.  ``.env`` is loaded here
once so every entry point (the app, the benchmark CLI, a direct import) reads
the same configuration.  Nothing here stores or prints a credential:
``api_key()`` returns the value the SDK needs, ``has_api_key()`` reports only
its presence, and callers use them to fail with a readable message instead of
an opaque SDK error.
"""
import os

try:  # python-dotenv is a declared runtime dependency
    from dotenv import load_dotenv

    # A missing .env is normal (containers pass real environment variables),
    # and load_dotenv never overrides variables already set in the process.
    load_dotenv()
except ImportError:  # pragma: no cover - only when dotenv is not installed
    pass


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    """Read an int >= *minimum* from the environment, else *default*.

    A malformed or out-of-range value is not fatal: an operator typo must not
    stop the app from starting, and the default is the documented behaviour.
    """
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


# Grid configuration
SIZE = 8

# Simulation timing
STEP_DELAY = 0.5

# AI model parameters
TEMPERATURE = 0.2

# Repair loop configuration (overridable, bounded to at least 1)
DEFAULT_MAX_REPAIRS = 2
MAX_REPAIRS = _int_env("MAX_REPAIRS", DEFAULT_MAX_REPAIRS)

# RobotBench: the smallest sample whose numbers may be compared.  Below this
# many runs, a difference between two series is noise, so the benchmark report
# and the lab both say so rather than letting the numbers read as a verdict
# about a model.  Overridable for a larger dataset; never lowered silently.
BENCH_MIN_SAMPLE = _int_env("BENCH_MIN_SAMPLE", 30)

# Model names (read from environment, with defaults)
GEMMA_API_MODEL = os.getenv("GEMMA_API_MODEL", "gemma-4-26b-a4b-it")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")

# The environment variable the Google GenAI SDK reads for the API backend.
API_KEY_ENV = "GEMINI_API_KEY"

# OpenAI-compatible planner — any endpoint speaking the chat-completions shape
# (OpenAI, vLLM, LM Studio, Ollama's OpenAI mode, OpenRouter).  The planner is
# configured, not hard-coded: a deployment points OPENAI_MODEL at whatever the
# endpoint serves and the plan contract stays the project's.
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
try:
    OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "120"))
except ValueError:
    OPENAI_TIMEOUT = 120.0


def api_key() -> str:
    """The configured API key value, or ``""`` when unset.

    Never log, display or persist the return value.
    """
    return os.getenv(API_KEY_ENV, "").strip()


def has_api_key() -> bool:
    """True when an API key is present.  Reports presence, never the value."""
    return bool(api_key())


# ---------------------------------------------------------------------------
# OpenAI-compatible credential helpers — same policy as api_key(): presence
# only, never a value in a log or a display surface.
# ---------------------------------------------------------------------------

def openai_api_key() -> str:
    """The configured OpenAI-compatible key value, or ``""`` when unset.

    Keyless local endpoints (vLLM, LM Studio, Ollama) are legitimate: the key
    is required only when the base URL is the hosted OpenAI API.
    """
    return os.getenv(OPENAI_API_KEY_ENV, "").strip()


def openai_needs_key(base_url: str | None = None) -> bool:
    """True when *base_url* is the hosted OpenAI API and no key is set."""
    url = (base_url or OPENAI_BASE_URL).lower()
    return "api.openai.com" in url and not openai_api_key()


def openai_missing_key_message() -> str:
    """A readable failure for callers about to make an OpenAI-compatible call."""
    return (
        "No OpenAI-compatible API key configured (OPENAI_API_KEY). The hosted "
        "OpenAI endpoint requires one; a self-hosted endpoint should set "
        "OPENAI_BASE_URL instead. Nothing was sent anywhere."
    )


def missing_api_key_message() -> str:
    """A readable failure for callers about to make an API-backed call."""
    return (
        "No Gemini API key configured (GEMINI_API_KEY). Copy .env.example to "
        ".env and replace the placeholder, set GEMINI_API_KEY in the "
        "environment, or switch the engine to 'Local' (Ollama) or a scripted "
        "dry mode. Nothing was sent anywhere."
    )
