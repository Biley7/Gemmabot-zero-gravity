"""Console shell — product header, console status and the simulator viewport.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

The shell is what makes five labs read as one robotics console: a product
header (the wordmark, what the product *is*, and the backend it is configured
with), one status vocabulary the whole app speaks, and the framed viewport the
simulator is drawn in.

Status vocabulary
-----------------
    READY       nothing is running
    THINKING    a model is proposing
    VERIFYING   the verifier is judging an attempt
    EXECUTING   an approved plan is stepping through the simulator
    COMPLETE    the run finished with something real to show
    FAILED      the run finished with nothing runnable

``console_status()`` is the only place a status is derived, and it derives from
events that really happened — a run in flight, a verification verdict, an
execution — never from a timer.  The caller passes the phase it is in and the
verdicts it holds; everything else falls out of them.

Public surface
--------------
PRODUCT / TAGLINE / NAV / STATUSES     the console's own vocabulary
console_status(...) -> (key, text)     the status key and its activity line
header_html(...)    -> str             the product header
status_bar_html(...)-> str             the live console status bar
viewport_html(...)  -> str             the framed simulator viewport
zone_bar_html(...)  -> str             one zone's label (Pipeline, Execution…)
"""
from __future__ import annotations

from frontend.components.blocks import escape as _e

PRODUCT = "GemmaBot"
TAGLINE = "AI Robotics Validation Platform"

# ``key`` -> (label, design-system state).  The keys are the console's own
# states; the state names are the ones the theme colours (badge/chip/dot).
STATUSES: dict[str, tuple[str, str]] = {
    "ready":     ("READY",     "neutral"),
    "thinking":  ("THINKING",  "thinking"),
    "verifying": ("VERIFYING", "running"),
    "executing": ("EXECUTING", "running"),
    "complete":  ("COMPLETE",  "success"),
    "failed":    ("FAILED",    "error"),
}

# The primary navigation, in order.  app.py opens exactly these tabs, so the
# console's navigation has one definition instead of a list per screen.
NAV: tuple[str, ...] = (
    "Mission",
    "Safety Lab",
    "Vision Lab",
    "Run History",
    "Benchmark",
)

# The guard console's loop states, and the console phase each one puts the app
# in.  One mapping, so the header and the console can never disagree about what
# the run is doing.
LOOP_PHASES: dict[str, str] = {
    "thinking": "plan",
    "repairing": "verify",
    "executing": "execute",
}


def phase_for(loop_status: str) -> str | None:
    """The console phase for a guard-console loop state (or ``None``)."""
    return LOOP_PHASES.get(loop_status)


def console_status(
    *,
    phase: str | None = None,
    verified: bool | None = None,
    executed: bool | None = None,
) -> tuple[str, str]:
    """The console's status and the activity behind it.

    ``phase`` is what the console is doing right now (``"plan"``,
    ``"verify"``, ``"execute"``) or ``None`` when nothing is running.
    ``verified`` says whether a plan passed the verifier, ``executed`` whether
    an approved plan really ran.  An unknown (``None``) is reported as such:
    the console never claims a verdict nothing produced.
    """
    if phase == "plan":
        return "thinking", "The model is proposing a plan."
    if phase == "verify":
        return "verifying", "The verifier judged an attempt — repairing if it was refused."
    if phase == "execute":
        return "executing", "An approved plan is stepping through the simulator."
    if executed is True:
        return "complete", "The approved plan executed on the simulator."
    if executed is False:
        return "failed", "The plan was approved but execution was refused."
    if verified is True:
        return "complete", "The plan passed verification — nothing executed yet."
    if verified is False:
        return "failed", "No attempt passed verification."
    return "ready", "No run in this session — the console is idle."


def status_chip_html(key: str, detail: str = "") -> str:
    """The status chip alone, for a header or a row that needs just this.

    A key the console does not know is drawn as READY rather than echoing the
    unknown word: nothing else may claim a state the console cannot explain.
    """
    resolved = key if key in STATUSES else "ready"
    label, _ = STATUSES[resolved]
    title = f"{label} — {detail}" if detail else label
    return (
        f"<span class='gb-console-chip' data-status='{_e(resolved)}' "
        f"title='{_e(title)}'>{_e(label)}</span>"
    )


def header_html(*, backend_label: str = "", model: str | None = None) -> str:
    """The product header: wordmark, what the product is, the configured model.

    *backend_label* / *model* are the values the app is configured with (the
    same ones the guard panel reports) — configuration, not a measurement.
    """
    model_html = ""
    if backend_label or model:
        model_html = (
            f"<span class='gb-head-meta' data-backend='{_e(backend_label)}'>"
            f"{_e(backend_label)}"
            + (f" · <span class='gb-head-model'>{_e(model)}</span>" if model else "")
            + "</span>"
        )
    return (
        f"<div class='gb-console-head'>"
        f"<span class='gb-wordmark'>{_e(PRODUCT)}</span>"
        f"<span class='gb-tagline'>{_e(TAGLINE)}</span>"
        f"<span class='gb-head-rule'></span>"
        f"{model_html}"
        f"</div>"
    )


def status_bar_html(*, key: str, activity: str = "", meta: str = "") -> str:
    """The live status bar under the header.

    *key* is a :data:`STATUSES` key that the caller derived from real state;
    *activity* is the sentence explaining it; *meta* is an optional right-hand
    readout (coordinates, steps — technical data, so mono).
    """
    resolved = key if key in STATUSES else "ready"
    return (
        f"<div class='gb-console-bar' data-status='{_e(resolved)}'>"
        f"{status_chip_html(resolved, activity)}"
        f"<span class='gb-console-activity'>{_e(activity)}</span>"
        + (
            f"<span class='gb-console-meta'>{_e(meta)}</span>" if meta else ""
        )
        + "</div>"
    )


def zone_bar_html(title: str, meta: str = "") -> str:
    """One zone's label — ``PIPELINE``, ``EXECUTION``… — with an optional
    right-hand readout of the numbers behind it."""
    return (
        "<div class='gb-zone-bar'>"
        f"<span class='gb-zone-title'>{_e(title)}</span>"
        + (f"<span class='gb-zone-meta'>{_e(meta)}</span>" if meta else "")
        + "</div>"
    )


def viewport_html(
    body: str,
    *,
    title: str = "Simulator",
    meta: str = "",
    foot: str = "",
) -> str:
    """The framed viewport: a technical bar, the drawing, a readout foot.

    The board is the hero of the console, so it gets a frame with the same
    grammar as the rest of the product — a title, mono metadata about the world
    it is showing, the drawing itself, and a legend/readout strip.
    """
    return (
        "<div class='gb-viewport'>"
        "<div class='gb-viewport-bar'>"
        f"<span class='gb-viewport-title'>{_e(title)}</span>"
        + (f"<span class='gb-viewport-meta'>{_e(meta)}</span>" if meta else "")
        + "</div>"
        f"<div class='gb-viewport-body'>{body}</div>"
        + (f"<div class='gb-viewport-foot'>{foot}</div>" if foot else "")
        + "</div>"
    )
