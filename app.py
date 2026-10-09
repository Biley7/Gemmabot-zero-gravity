"""GemmaBot — Streamlit frontend: the AI robotics validation console.

Propose (Gemma) → Verify (code) → Execute (simulator).

Owner: FRONTEND.  No fake results live here: every number, status, world and
action shown comes from a real backend result — ``harness.plan_with_repair``
history, ``map_vision.read_map`` history, ``simulator.render``/``step``,
``logger`` summaries and the benchmark files.

The console shell (``frontend.console``) supplies the product header, the
status vocabulary and the six-stage pipeline.  The Mission screen is laid out
the way the product works: the command on the left, the simulator viewport in
the centre, the GemmaBot Guard console on the right, and the pipeline plus the
execution timeline underneath — AI proposes, the guard verifies, the robot
executes.

The Execute stage is animated by ``frontend.simulation.player`` (the
simulator's own timeline) and drawn by ``player_view`` — the player only
replays those steps, it never re-simulates or re-times them.

The GemmaBot Guard console (``frontend.panels.brain``) reports the run's
structured metadata — model, backend, attempt, plan, the verification /
simulation / execution verdicts, latency and the four checks
``harness.verify_plan`` evaluated.  It never shows model reasoning: it is
metadata, not a transcript.

The Vision Lab (``frontend.panels.vision``) reads an image into a world model,
shows the reading next to the world it proposes, validates that world
(✓ Valid · ✓ Inside bounds · ✓ Reachable) and loads it into the simulator.  The
verdicts are ``map_vision.check_world_report``'s; the world the simulator adopts
is the one the validator accepted.

The Benchmark Lab (``frontend.panels.benchmark``) measures runs that already
happened.  It keeps live runs (a model answered) apart from synthetic ones (the
scripted reader did), reports the denominator behind every rate, and shows a
metric with no measurement as no data rather than as a zero.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from gemmabot.config import MAX_REPAIRS
from gemmabot.simulator import new_world

import engine
import ui_helpers

# Design system
from frontend.components.theme import inject_theme
from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.components.blocks import empty_state, fact_cards
from frontend.console import pipeline as console
from frontend.console import shell as console_shell
from frontend.panels import benchmark as benchmark_panel
from frontend.panels import brain
from frontend.panels import replay as replay_panel
from frontend.panels import safety
from frontend.panels import vision
from frontend.simulation import player as playback
from frontend.simulation import player_view

ROOT = Path(__file__).parent
LOG_PATH = ROOT / "logs" / "runs.jsonl"
BENCHMARK_PATH = ROOT / "benchmarks" / "results.md"

# ── Keyboard shortcuts ──────────────────────────────────────────────────────
# Defined once, then used for both the buttons and the reference list in the
# sidebar, so the help can never document a key that is not wired.
#
# "Mod" is not a key: it is Streamlit's name for the reader's primary modifier.
# Verified in the shipped frontend (static/js/index.*.js): the button hint renders
# the token `ctrl` through Ld={ctrl:`Ctrl`, cmd:`⌘`, mod:`Mod`} selected by an
# is-Mac check, and the handler binds the platform form (`command+enter` on macOS).
# So on a Mac the button paints "⌘ + Enter" and ⌘+Enter is what fires; elsewhere
# it is Ctrl.  That is why the labels below stay modifier-neutral and the sidebar
# spells out which physical key that is.
#
# The server-side proto for all four stays `ctrl+...` (Streamlit maps "mod" to
# "ctrl" unconditionally in shortcut_utils.py) - an internal token, not the key.
SHORTCUTS: dict[str, str] = {
    "plan": "Mod+Enter",
    "safety": "Mod+Shift+Enter",
    "read_map": "Mod+Shift+M",
    "replay": "Mod+Shift+L",
}
# A run the app is waiting on for this many log lines; the sidebar shows the
# last ten and nothing reads the older ones.
LOG_LINE_CAP = 200
BENCHMARK_JSON = ROOT / "benchmarks" / "results.json"

# ── Optional backend modules: the app must start without them ─────────────
try:
    import gemmabot.map_vision  # noqa: F401 — presence check only
    HAVE_MAPVISION = True
except ImportError:  # pragma: no cover - depends on environment
    HAVE_MAPVISION = False

try:
    from gemmabot import logger as run_logger
    HAVE_LOGGER = True
except ImportError:  # pragma: no cover - depends on environment
    run_logger = None
    HAVE_LOGGER = False

try:
    import gemmabot.benchmark  # noqa: F401 — presence check only
    HAVE_BENCHMARK = True
except ImportError:  # pragma: no cover - depends on environment
    HAVE_BENCHMARK = False

load_dotenv()

st.set_page_config(page_title="GemmaBot", page_icon="🤖", layout="wide")
inject_theme()

MAP_LABELS = {
    "default": "Default world (new_world())",
    "sample":  "Sample 8×8 maze (dev map)",
    "scanned": "Scanned map (Vision Lab)",
}
ENGINE_BACKENDS = {"API": "api", "Local": "local", "Auto": "auto"}


def _map_label(name: str) -> str:
    return MAP_LABELS.get(name, name)


# ---------------------------------------------------------------------------
# Session state — initialised once
# ---------------------------------------------------------------------------

def _init_state() -> None:
    """Set defaults for any missing session key (safe across code updates)."""
    st.session_state.initialized = True
    if "map_source" not in st.session_state:
        st.session_state.map_source = engine.default_maps()
    st.session_state.setdefault("map_name", "default")
    if "world" not in st.session_state:
        st.session_state.world = copy.deepcopy(
            st.session_state.map_source.get(
                "default", next(iter(st.session_state.map_source.values()))
            )
        )
    st.session_state.setdefault("logs", [])
    st.session_state.setdefault("last_run", None)
    st.session_state.setdefault("text_result", None)
    st.session_state.setdefault("uploaded_map", None)
    st.session_state.setdefault("connections", None)
    st.session_state.setdefault("replay", None)
    st.session_state.setdefault("replay_autoplay", False)
    st.session_state.setdefault("safety_result", None)
    st.session_state.setdefault("safety_autoplay", False)
    st.session_state.setdefault("vision_result", None)
    st.session_state.setdefault("vision_loaded", False)
    st.session_state.setdefault("log_replay", None)
    st.session_state.setdefault("log_replay_autoplay", False)
    st.session_state.setdefault("replay_run", None)
    st.session_state.setdefault("replay_auto_run", None)
    st.session_state.setdefault("replay_plan_run", None)


_init_state()


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _clear_run_state() -> None:
    """Drop every result a session run produced for the active world.

    A console that keeps showing the last run's verdict after the map changed is
    worse than one showing nothing: the numbers still look live.  Called by
    anything that moves the simulator to another world or resets it.

    The Vision Lab's reading is deliberately kept: it describes the uploaded
    image, not the active map.  ``vision_loaded`` is derived from the map name
    instead of remembered, so it can never claim the wrong world.
    """
    st.session_state.logs = []
    st.session_state.text_result = None
    st.session_state.replay = None
    st.session_state.replay_autoplay = False
    st.session_state.last_run = None
    st.session_state.safety_result = None
    st.session_state.safety_autoplay = False
    # A replay rendered from the run log is still a session result; the record
    # stays on disk and the Replay tab rebuilds it on demand.
    st.session_state.log_replay = None
    st.session_state.log_replay_autoplay = False


def _adopt_world(name: str) -> None:
    """Point the simulator at map *name* and clear what belonged to the old one."""
    st.session_state.world = copy.deepcopy(st.session_state.map_source[name])
    _clear_run_state()
    # Derived, not remembered: the simulator is on the scanned map exactly when
    # the scanned map is the active one.
    st.session_state.vision_loaded = name == "scanned"


def _reset_world() -> None:
    _adopt_world(st.session_state.map_name)


def _shortcut_rows() -> list[tuple[str, str]]:
    """The shortcut reference, read from the same dict the buttons use."""
    return [
        ("Run plan", SHORTCUTS["plan"]),
        ("Run safety check", SHORTCUTS["safety"]),
        ("Read map", SHORTCUTS["read_map"]),
        ("Replay", SHORTCUTS["replay"]),
    ]


def _load_vision_into_simulator() -> None:
    """Adopt the validated reading as the active map (the lab's last stage).

    Runs as the button's ``on_click`` callback, i.e. before the widget tree is
    rebuilt — the sidebar's map picker can only be moved from there.  Only ever
    called with a world the validator accepted; the simulator gets a deep copy,
    so executing a plan later cannot write back into the lab's result.
    """
    lab = st.session_state.get("vision_result") or {}
    scanned = lab.get("world")
    if not isinstance(scanned, dict):
        return
    st.session_state.map_source["scanned"] = copy.deepcopy(scanned)
    st.session_state.map_name = "scanned"
    st.session_state.map_picker = "scanned"
    st.session_state.world = copy.deepcopy(scanned)
    st.session_state.vision_loaded = True
    # Whatever was measured on the old map is not about this one.
    _clear_run_state()


def _render_replay(replay: dict) -> None:
    """The execution player *is* the Mission viewport: the simulator's own run.

    Compact (no built-in step list): the console draws the action timeline
    beside it, so the viewport keeps the stage, the live step readout
    (``02/06 · forward ×7``), the transport and the speed selector.
    """
    autoplay = bool(st.session_state.pop("replay_autoplay", False))
    st.components.v1.html(
        player_view.player_html(
            replay,
            autoplay=autoplay,
            cell_px=S.CELL_SIZE,
            show_steps=False,
        ),
        height=player_view.player_height(S.CELL_SIZE),
        scrolling=False,
    )


def _draw_viewport(world: dict) -> None:
    """The simulator viewport: the framed 8×8 board with its legend."""
    st.markdown(
        console_shell.viewport_html(
            ui_helpers.world_grid_html(world),
            title="Simulator",
            meta=_viewport_meta(world, None),
            foot=ui_helpers.grid_legend_html(),
        ),
        unsafe_allow_html=True,
    )


def _render_safety_replay(attempt: dict) -> None:
    """The same player, pointed at one attempt of the safety lab."""
    autoplay = bool(st.session_state.pop("safety_autoplay", False))
    st.components.v1.html(
        player_view.player_html(attempt["timeline"], autoplay=autoplay),
        height=player_view.player_height(),
        scrolling=False,
    )


def _safety_pick_changed() -> None:
    """Replay the attempt that was just selected (one shot)."""
    st.session_state.safety_autoplay = True


def _render_log_replay(timeline: dict) -> None:
    """The same player, pointed at a run replayed from the log.

    Nothing is asked of a model: *timeline* was built by ``replay.timeline``
    from the recorded world and plan, i.e. by ``simulator.step`` alone.
    """
    autoplay = bool(st.session_state.pop("log_replay_autoplay", False))
    st.components.v1.html(
        player_view.player_html(timeline, autoplay=autoplay),
        height=player_view.player_height(),
        scrolling=False,
    )


# ---------------------------------------------------------------------------
# Rendering helpers (design-system backed)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Console shell helpers
# ---------------------------------------------------------------------------

def _paint_status(slot, key: str, activity: str = "", meta: str = "") -> None:
    """Draw the console status bar into its slot."""
    slot.markdown(
        console_shell.status_bar_html(key=key, activity=activity, meta=meta),
        unsafe_allow_html=True,
    )


def _resting_status() -> tuple[str, str]:
    """The console's status when nothing is running.

    Derived from the last run in this session and from nothing else: the
    verifier's verdict for the plan, and whether an approved plan really
    executed.  A session with no run at all is READY.
    """
    text = st.session_state.get("text_result")
    if text:
        ok = (text.get("verification") or {}).get("ok")
        verified = ok if ok is True or ok is False else None
        return console_shell.console_status(
            verified=verified,
            executed=bool(text.get("replay")) if text.get("actions") is not None else None,
        )
    safety = st.session_state.get("safety_result")
    if safety:
        success = (safety.get("summary") or {}).get("success") or {}
        verified = bool(success.get("ok"))
        key, _ = console_shell.console_status(verified=verified)
        return key, (
            "The Safety Lab's last plan passed verification." if verified
            else "No plan passed verification in the Safety Lab."
        )
    vision = st.session_state.get("vision_result")
    if vision:
        world = vision.get("world")
        key, _ = console_shell.console_status(verified=bool(world))
        return key, (
            "The last reading passed the world checks." if world
            else "No reading passed the world checks."
        )
    return console_shell.console_status()


def _world_facts(world: dict) -> str:
    """The active world's real geometry, as console readouts."""
    robot = world.get("robot") or [0, 0]
    goal = world.get("goal") or [0, 0]
    walls = world.get("walls") or []
    rows = [
        {"id": "map", "label": "Map", "value": _map_label(st.session_state.map_name),
         "detail": "selected in the sidebar", "state": "neutral"},
        {"id": "robot", "label": "Robot", "value": f"[{robot[0]}, {robot[1]}]",
         "detail": f"facing {world.get('dir', '?')}", "state": "neutral"},
        {"id": "goal", "label": "Goal", "value": f"[{goal[0]}, {goal[1]}]",
         "detail": "the cell a plan must end on", "state": "neutral"},
        {"id": "obstacles", "label": "Obstacles", "value": str(len(walls)),
         "detail": "blocked cells the verifier refuses", "state": "neutral"},
    ]
    return fact_cards(rows, css_class="gb-mission-fact", column_min=104)


def _paint_guard(slot, meta: dict) -> None:
    """Draw the GemmaBot Guard console into its slot."""
    slot.markdown(brain.brain_panel_html(meta), unsafe_allow_html=True)


def _guard_meta(*, backend: str, model: str | None, max_tries: int) -> dict:
    """The guard console for a session that has not run anything yet.

    The model and the backend are the configured values; every verdict is
    unproven, which is exactly what the session has to show.
    """
    return brain.brain_metadata(
        backend=engine.backend_label(backend),
        model=model,
        status="ready",
        attempts=0,
        max_tries=max_tries,
    )


def _viewport_meta(world: dict | None, replay: dict | None) -> str:
    """The viewport bar's mono readout: what the drawing is showing."""
    if replay is not None:
        return (
            f"playback · {len(replay.get('steps') or [])} steps · "
            f"{int(replay.get('cells') or 0)} cells"
        )
    if not world:
        return ""
    return (
        f"{len(world.get('walls') or [])} obstacles · "
        f"robot [{world.get('robot', [0, 0])[0]}, {world.get('robot', [0, 0])[1]}]"
    )


def _run_zones(stored: dict) -> None:
    """The pipeline, the execution timeline and the verification status.

    Every state here is read off the stored run: the plan the loop produced,
    ``verify_plan``'s checks, whether the execution gate sealed the plan and the
    simulator timeline that executed it.  Nothing is inferred from a timer.
    """
    stages = console.pipeline_stages(
        instruction=stored.get("instruction", ""),
        actions=stored.get("actions"),
        verification=stored.get("verification"),
        approved=stored.get("approved") is not None,
        timeline=stored.get("replay"),
        error=stored.get("error"),
    )
    st.markdown(
        console_shell.zone_bar_html(
            "Pipeline", "input → plan → verify → simulate → approve → execute"
        )
        + console.pipeline_html(stages),
        unsafe_allow_html=True,
    )

    timeline = stored.get("replay")
    rows = console.timeline_rows(stored.get("actions"), timeline=timeline)
    steps = len(timeline.get("steps") or []) if timeline else 0
    cells = int(timeline.get("cells") or 0) if timeline else 0

    exec_col, status_col = st.columns([2.1, 1.0], gap="medium")
    with exec_col:
        st.markdown(
            console_shell.zone_bar_html(
                "Execution timeline",
                f"{len(rows)} action(s) · {steps} step(s) · {cells} cell(s)"
                + (
                    f" · halted: {timeline.get('halted')}"
                    if timeline and timeline.get("halted") else ""
                ),
            )
            + console.timeline_html(rows),
            unsafe_allow_html=True,
        )
    with status_col:
        st.markdown(
            console_shell.zone_bar_html("Status"),
            unsafe_allow_html=True,
        )
        st.markdown(
            console.status_strip_html(console.status_checks(stored.get("verification"))),
            unsafe_allow_html=True,
        )


def _run_brain_meta(
    *,
    backend: str,
    verification: dict | None,
    actions: list | None,
    attempts: int,
    max_tries: int,
    latency: float | None,
    steps: int | None,
    reached: bool | None,
    error: str | None,
    approved: bool | None = None,
    executed: bool | None = None,
    halted: str | None = None,
) -> dict:
    """Post-run Guard metadata: the verified plan plus its real four checks."""
    return brain.run_metadata(
        backend_label=engine.backend_label(backend),
        model=engine.backend_model(backend),
        verification=verification,
        actions=actions,
        attempts=attempts,
        max_tries=max_tries,
        latency=latency,
        steps=steps,
        reached=reached,
        approved=approved,
        executed=executed,
        halted=halted,
        error=error,
    )


def _render_attempt_cards(
    cards: list[dict],
    reply_label: str,  # kept for API compatibility; label shown in HTML
    ok_message: str,   # noqa: ARG001 — used inside attempt_card_html
) -> None:
    """Design-system attempt cards inside native Streamlit expanders."""
    if not cards:
        st.info("No model attempt was recorded.")
        return
    for card_data in cards:
        title = f"{card_data['label']} — {card_data['status']}"
        with st.expander(title, expanded=not card_data["ok"]):
            st.markdown(DS.attempt_card_html(card_data), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.markdown(
    DS.section_title("Configuration"), unsafe_allow_html=True
)

engine_choice = st.sidebar.radio(
    "Engine",
    list(ENGINE_BACKENDS.keys()),
    help="API is Gemini, Local is Ollama on this machine, Auto tries the API "
         "and falls back to Ollama. Dry mode is chosen per lab, not here.",
)
backend = ENGINE_BACKENDS[engine_choice]

max_tries = int(
    st.sidebar.number_input(
        "Max tries (plan & vision)",
        min_value=1,
        max_value=5,
        value=max(1, MAX_REPAIRS + 1),
        step=1,
        help="How many planning attempts the loop may make: one proposal plus "
             "this many repairs. Applies to planning and to map vision.",
    )
)

map_names = list(st.session_state.map_source.keys())
current_map = st.session_state.get("map_picker", st.session_state.map_name)
map_index = map_names.index(current_map) if current_map in map_names else 0
chosen_map = st.sidebar.selectbox(
    "Map",
    map_names,
    index=map_index,
    format_func=_map_label,
    key="map_picker",
    help="The world the simulator is on. Changing it clears the results that "
         "were measured on the previous map.",
)
if chosen_map != st.session_state.map_name:
    st.session_state.map_name = chosen_map
    _adopt_world(chosen_map)

st.sidebar.button(
    "Reset world",
    on_click=_reset_world,
    help="Restores the selected map and clears the results measured on it.",
)

if st.sidebar.button(
    "Check connections",
    help="Looks for a Gemini key in the environment and asks Ollama whether it "
         "is running. Nothing is sent anywhere.",
):
    st.session_state.connections = engine.check_connections()
connections = st.session_state.connections
if connections:
    rows = [
        ("API key", "set" if connections["api_key_set"] else "not set"),
        ("Ollama",  "reachable" if connections["ollama_reachable"] else "offline"),
    ]
    if connections["ollama_models"]:
        rows.append(("Models", ", ".join(connections["ollama_models"])))
    st.sidebar.markdown(DS.telemetry_block(rows), unsafe_allow_html=True)

# Sidebar telemetry
st.sidebar.markdown(
    DS.section_title("Last run"), unsafe_allow_html=True
)
summary = st.session_state.last_run
if summary:
    rows = [
        ("Attempts", summary["attempts_label"]),
        ("Latency",  summary["latency_label"]),
        ("Backend",  summary["backend"]),
        ("Status",   summary["status"]),
    ]
    st.sidebar.markdown(DS.telemetry_block(rows), unsafe_allow_html=True)
else:
    st.sidebar.markdown(
        empty_state("No run in this session yet.", "Run plan fills this in.", dense=True),
        unsafe_allow_html=True,
    )

if HAVE_LOGGER:
    with st.sidebar.expander("Run logs (last 10)"):
        try:
            runs = run_logger.load_runs(path=str(LOG_PATH))
        except Exception as exc:  # noqa: BLE001
            runs = []
            st.caption(f"Could not read logs: {exc}")
        if not runs:
            st.markdown(
                empty_state(
                    "No runs logged yet.",
                    "Plans, safety checks and benchmark runs all land here.",
                    dense=True,
                ),
                unsafe_allow_html=True,
            )
        for record in list(reversed(runs))[:10]:
            try:
                st.markdown(
                    f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
                    f"color:{C.TEXT_SECONDARY};padding:{S.px(S.XS)} 0;"
                    f"border-bottom:1px solid {C.BORDER_SUBTLE}'>"
                    f"{run_logger.summarize_run(record)}</div>",
                    unsafe_allow_html=True,
                )
            except Exception as exc:  # noqa: BLE001
                st.text(f"(unreadable run: {exc})")

with st.sidebar.expander("Keyboard"):
    st.markdown(
        DS.telemetry_block(_shortcut_rows()), unsafe_allow_html=True
    )
    st.caption(
        "“Mod” is Streamlit's name for your primary modifier: ⌘ Command on "
        "macOS, Ctrl on Windows and Linux. Each button prints the key it "
        "actually listens for."
    )


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

# ── Console shell: product header and live status ─────────────────────────
# The header is the product; the bar under it is the console's own state
# (READY / THINKING / VERIFYING / EXECUTING / COMPLETE / FAILED).  While a run is
# in flight the loop repaints this slot with the phase it is really in.
st.markdown(
    console_shell.header_html(
        backend_label=engine.backend_label(backend),
        model=engine.backend_model(backend),
    ),
    unsafe_allow_html=True,
)
status_slot = st.empty()
_status_key, _status_text = _resting_status()
_paint_status(status_slot, _status_key, _status_text)

# ── Primary navigation ────────────────────────────────────────────────────
_available = {
    "Mission": True,
    "Safety Lab": True,
    "Vision Lab": HAVE_MAPVISION,
    "Run History": HAVE_LOGGER,
    "Benchmark": HAVE_BENCHMARK,
}
tab_names = [name for name in console_shell.NAV if _available[name]]
tabs = dict(zip(tab_names, st.tabs(tab_names)))


# ── Mission ───────────────────────────────────────────────────────────────
with tabs["Mission"]:
    command_col, viewport_col, guard_col = st.columns([1.05, 2.0, 1.3], gap="medium")

    # The guard console is created before the command column so the planning
    # loop can stream its real states (Thinking → Repairing → Executing) into it
    # while the run is still in flight: Streamlit paints an element where it was
    # created, not where it was last written.
    with guard_col:
        guard_slot = st.empty()
        stored_brain = (st.session_state.text_result or {}).get("brain")
        _paint_guard(
            guard_slot,
            stored_brain
            or _guard_meta(
                backend=backend,
                model=engine.backend_model(backend),
                max_tries=max_tries,
            ),
        )

    # The viewport is the hero: the world, or the execution playback of the last
    # run (the player owns play / pause / reset and the speed selector).
    with viewport_col:
        playing = (
            st.session_state.get("replay")
            if st.session_state.get("text_result") else None
        )
        if playing:
            _render_replay(playing)
        else:
            _draw_viewport(st.session_state.world)

    # ── Mission command ───────────────────────────────────────────────────
    with command_col:
        st.markdown(
            console_shell.zone_bar_html(
                "Mission command", _map_label(st.session_state.map_name)
            ),
            unsafe_allow_html=True,
        )
        instruction = st.text_input(
            "Instruction",
            "Move to the goal using the safest route.",
            help="What the robot should do. The model proposes a plan for it; the "
                 "guard decides whether that plan may run.",
        )
        run_clicked = st.button(
            "Run plan",
            type="primary",
            disabled=not instruction.strip(),
            shortcut=SHORTCUTS["plan"],
            help="Propose with the model, verify with the harness, repair what "
                 "fails and execute the accepted plan. "
                 f"Shortcut: {SHORTCUTS['plan']}.",
        )
        st.markdown(
            console_shell.zone_bar_html("Active world"), unsafe_allow_html=True
        )
        st.markdown(_world_facts(st.session_state.world), unsafe_allow_html=True)

    if run_clicked:
        if not instruction.strip():
            st.warning("Enter an instruction first.")
        else:
            live = {"attempt": 0}

            def _live_status(status_key: str, status_detail: str) -> None:
                """Stream the loop's real state into the console and the header.

                ``status_key`` is the loop's own state — ``thinking`` /
                ``repairing`` / ``executing`` — taken from the harness's attempt
                records.  The header speaks the console's vocabulary, which is
                derived from that same key, so the two can never disagree.
                """
                _paint_guard(
                    guard_slot,
                    brain.brain_metadata(
                        backend=engine.backend_label(backend),
                        model=engine.backend_model(backend),
                        status=status_key,
                        attempts=live["attempt"],
                        max_tries=max_tries,
                        detail=status_detail,
                    ),
                )
                key, _ = console_shell.console_status(
                    phase=console_shell.phase_for(status_key)
                )
                _paint_status(
                    status_slot,
                    key,
                    status_detail,
                    meta=f"attempt {live['attempt']}/{max_tries}",
                )

            def _on_attempt(record: dict) -> None:
                """Drive the panel from the harness's own attempt records."""
                live["attempt"] = int(record.get("attempt") or 0)
                status_key, status_detail = brain.attempt_status(record, max_tries)
                _live_status(status_key, status_detail)

            # The world this run is planned against, captured before execution
            # moves the robot: it is what the run is logged with, so the run can
            # later be replayed from the log alone.
            run_world = copy.deepcopy(st.session_state.world)

            _live_status("thinking", f"attempt 1/{max_tries} — asking the model")
            with st.spinner(
                f"Asking {engine.backend_label(backend)} — the loop streams above"
            ):
                result = engine.run_plan(
                    instruction,
                    run_world,
                    backend=backend,
                    max_tries=max_tries,
                    on_attempt=_on_attempt,
                )
            metrics = ui_helpers.run_metrics(
                result["actions"], result["attempts"], max_tries, result["latency"]
            )
            replay = None

            # The execution gate requires an approved plan.  ``run_plan``
            # returns the guard's sealed ``ApprovedPlan``; if a result arrives
            # without one, approving it re-verifies from scratch and only a
            # genuinely valid plan can succeed.  ``execute_approved`` verifies
            # again before the simulator steps, so nothing in the UI can bypass
            # validation.
            approved = result.get("approved")
            executable = engine.verified_actions(result)
            if approved is None and executable is not None:
                approved = engine.approve(
                    st.session_state.world,
                    executable,
                    instruction=instruction,
                    planner=result["backend"],
                )
            if approved is not None:
                # Phase 3: execute on the approved snapshot and keep the
                # simulator's own timeline.  Every cell, turn and message the
                # player replays is a real ``simulator.step`` result — nothing
                # is staged here.
                replay = playback.build_approved_timeline(approved)
                st.session_state.world = replay["final_world"]
                st.session_state.logs.extend(playback.log_lines(replay))
                del st.session_state.logs[:-LOG_LINE_CAP]
                st.session_state.replay = replay
                st.session_state.replay_autoplay = True   # animate this run once
            else:
                st.session_state.replay = None

            # Brain metadata: the plan this run verified (or last attempted)
            # plus the four checks harness.verify_plan really evaluated.
            brain_meta = _run_brain_meta(
                backend=result["backend"],
                verification=result.get("verification"),
                actions=result["actions"],
                attempts=result["attempts"],
                max_tries=max_tries,
                latency=result["latency"],
                steps=len(replay["steps"]) if replay else None,
                reached=replay["reached"] if replay else None,
                approved=approved is not None,
                executed=replay is not None,
                halted=replay.get("halted") if replay else None,
                error=result["error"],
            )
            _live_status(
                brain_meta["status"]["key"], brain_meta["status"]["detail"]
            )

            st.session_state.text_result = {
                **result,
                "instruction": instruction,
                "max_tries": max_tries,
                "metrics": metrics,
                "replay": replay,
                "approved": approved,
                "brain": brain_meta,
            }
            st.session_state.last_run = {
                "source": "text",
                "backend": result["backend"],
                "attempts": result["attempts"],
                "max_tries": max_tries,
                "latency": result["latency"],
                "attempts_label": metrics["attempts_label"],
                "latency_label": metrics["latency_label"],
                "status": metrics["status"],
            }
            if HAVE_LOGGER:
                try:
                    run_logger.log_run(
                        instruction,
                        result["backend"],
                        result["actions"],
                        result["attempts"],
                        result["history"],
                        latency=result["latency"],
                        path=str(LOG_PATH),
                        world=run_world,
                        # Provenance, recorded while we still know it: the
                        # benchmark cannot guess it afterwards.
                        mode=engine.backend_mode(backend),
                    )
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Run log could not be written: {exc}")

            # Re-render so the board slot shows the player and it plays the run
            # we just recorded instead of waiting for the next interaction.
            st.rerun()

    # ── Pipeline, execution timeline and verification status ──────────────
    # Persisted, so the zones survive every rerun.  Every state in them is read
    # off the stored run: nothing is inferred from a timer.
    stored = st.session_state.text_result
    if stored:
        _run_zones(stored)

        # Outcome — from the simulator timeline the player replays.  A result may
        # be shown as successful only when an approved plan really executed and
        # produced a timeline; anything else takes the failure path.
        replay = stored.get("replay")
        if replay is None:
            st.error(
                f"Planning failed after {stored['attempts']} attempt(s): "
                f"{stored.get('error') or 'the plan did not pass verification'}"
            )
        else:
            n = len(stored["actions"])
            if replay["reached"]:
                st.markdown(
                    DS.status_chip("Goal reached", "success"),
                    unsafe_allow_html=True,
                )
            elif not replay["ok"]:
                st.markdown(
                    DS.status_chip("Execution blocked", "error"),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    DS.status_chip(f"{n} action(s) executed", "warning"),
                    unsafe_allow_html=True,
                )

        # The loop's own attempt records (propose → verify → repair)
        with st.expander("Planning loop — propose, verify, repair"):
            _render_attempt_cards(
                ui_helpers.attempt_cards(stored["history"]),
                reply_label="Raw model reply",
                ok_message="✓ Plan accepted (verified by the guard)",
            )

        # Execution log
        with st.expander("Execution log"):
            if st.session_state.logs:
                st.markdown(
                    f"<pre style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                    f"color:{C.TEXT_SECONDARY};background:{C.BG_ELEVATED};"
                    f"border:1px solid {C.BORDER_SUBTLE};"
                    f"border-radius:{S.px(S.RADIUS_SM)};padding:{S.px(S.MD)};"
                    f"white-space:pre-wrap;margin:0'>"
                    + "\n".join(st.session_state.logs)
                    + "</pre>",
                    unsafe_allow_html=True,
                )
            else:
                st.caption("No actions executed yet.")
    else:
        st.markdown(
            console_shell.zone_bar_html("Pipeline"),
            unsafe_allow_html=True,
        )
        st.markdown(
            empty_state(
                "No run in this session.",
                "Enter a mission and run a plan — the pipeline, the execution "
                "timeline and the verification status appear here.",
            ),
            unsafe_allow_html=True,
        )


# ── Safety Lab ────────────────────────────────────────────────────────────
with tabs["Safety Lab"]:
    st.markdown(
        console_shell.zone_bar_html(
            "Safety lab", "the verifier refuses, the loop repairs"
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
        f"color:{C.TEXT_MUTED};margin-bottom:{S.px(S.LG)}'>"
        "The verifier refuses a plan, the loop repairs it. Every verdict, "
        "collision cell and replay below comes from the real pipeline — only "
        "dry mode's reply text is scripted, and it says so."
        "</div>",
        unsafe_allow_html=True,
    )

    safety_instruction = st.text_input(
        "Safety check instruction",
        "Move to the goal using the safest route.",
        key="safety_instruction",
    )
    dry_label = engine.backend_label("dry")
    planner_choice = st.radio(
        "Planner", [dry_label, "Live model"], key="safety_planner", horizontal=True
    )
    dry_mode = planner_choice == dry_label
    if dry_mode:
        st.caption(
            f"Dry mode: scripted replies on the default world (new_world()) — "
            f"the loop, the verifier and the replay are real. Live mode uses "
            f"the sidebar engine ({engine.backend_label(backend)})."
        )

    if st.button(
        "Run safety check",
        type="primary",
        shortcut=SHORTCUTS["safety"],
        help="Walks one plan through the real verifier: proposal, refusal, "
             f"repair, then the accepted plan. Shortcut: {SHORTCUTS['safety']}.",
    ):
        # Dry mode demonstrates on the default world its scripted plans are
        # calibrated to; live mode uses whatever map is loaded.
        lab_world = (
            copy.deepcopy(new_world()) if dry_mode
            else copy.deepcopy(st.session_state.world)
        )
        # The planner this lab actually uses: dry mode scripts the replies even
        # when the sidebar engine is API/Local, and the logged provenance must
        # follow the lab, not the sidebar.
        lab_backend = "dry" if dry_mode else backend
        with st.spinner("Verifying plans and repairing failures…"):
            result = engine.run_plan(
                safety_instruction,
                lab_world,
                backend=lab_backend,
                max_tries=max_tries,
            )
        stage_list = safety.stages(lab_world, result["history"])
        st.session_state.safety_result = {
            "world": lab_world,
            "instruction": safety_instruction,
            "planner": engine.backend_label(result["backend"]),
            "max_tries": max_tries,
            "attempts": result["attempts"],
            "latency": result["latency"],
            "actions": result["actions"],
            "error": result["error"],
            "stages": stage_list,
            "summary": safety.summary(stage_list),
            "replays": safety.replays(lab_world, result["history"]),
        }
        st.session_state.safety_autoplay = True
        st.session_state.last_run = {
            "source": "safety",
            "backend": result["backend"],
            "attempts": result["attempts"],
            "max_tries": max_tries,
            "latency": result["latency"],
            "attempts_label": f"{result['attempts']} / {max_tries}",
            "latency_label": f"{result['latency']:.2f} s",
            "status": (
                "Verified safe" if result["actions"] is not None
                else "No valid plan"
            ),
        }
        if HAVE_LOGGER:
            try:
                run_logger.log_run(
                    safety_instruction,
                    result["backend"],
                    result["actions"],
                    result["attempts"],
                    result["history"],
                    latency=result["latency"],
                    path=str(LOG_PATH),
                    world=lab_world,
                    mode=engine.backend_mode(lab_backend),
                )
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Run log could not be written: {exc}")
        st.rerun()

    lab = st.session_state.safety_result
    if lab:
        st.markdown(
            safety.meta_html(
                lab["planner"], lab["instruction"], lab["attempts"], lab["latency"]
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            safety.report_html(lab["stages"], lab["summary"]),
            unsafe_allow_html=True,
        )

        # ── Replay: the simulator's own run of one attempt ────────────────
        st.markdown(DS.section_title("Replay"), unsafe_allow_html=True)
        attempts = lab["replays"]
        if not attempts:
            st.markdown(
                DS.card(
                    f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                    f"color:{C.TEXT_SECONDARY}'>No attempt produced a runnable "
                    "plan, so there is nothing to replay.</span>",
                    title="Nothing to replay",
                ),
                unsafe_allow_html=True,
            )
        else:
            labels = [
                f"{item['label']} · {item['steps']} action(s)"
                + (" · halted" if item["halted"] else "")
                for item in attempts
            ]
            chosen_label = st.radio(
                "Attempt to replay",
                labels,
                key="safety_replay_pick",
                horizontal=True,
                on_change=_safety_pick_changed,
            )
            chosen = attempts[labels.index(chosen_label)]
            collision = lab["summary"].get("collision")
            if collision:
                st.markdown(
                    f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                    f"color:{C.TEXT_SECONDARY};margin-bottom:{S.px(S.SM)}'>"
                    f"Collision location "
                    f"<span style='color:{C.ERROR}'>{collision['text']}</span>"
                    f" — refused on attempt {collision['attempt']}. The map below "
                    f"shows {chosen['label'].lower()} with its real path and the "
                    f"refused cell marked.</div>",
                    unsafe_allow_html=True,
                )
            st.markdown(ui_helpers.grid_legend_html(), unsafe_allow_html=True)
            st.markdown(
                ui_helpers.world_grid_html(
                    chosen["timeline"]["final_world"],
                    path=chosen["timeline"]["path"],
                    danger_cell=collision["cell"] if collision else None,
                    cell_px=S.CELL_SIZE,
                ),
                unsafe_allow_html=True,
            )
            _render_safety_replay(chosen)


# ── Vision Lab ────────────────────────────────────────────────────────────
if HAVE_MAPVISION:
    with tabs["Vision Lab"]:
        st.markdown(
            console_shell.zone_bar_html(
                "Vision lab", "an image becomes a world, and the world is checked"
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED};margin-bottom:{S.px(S.LG)}'>"
            "An image becomes a world, and the world is checked before it can "
            "reach the simulator. Every verdict below is the validator's "
            "(<code>map_vision.check_world_report</code>), the same one the retry "
            "loop uses. Dry mode scripts the reply only: the image is not sent to "
            "a model, and the parse, the retry, the three checks and the load are "
            "the real pipeline."
            "</div>",
            unsafe_allow_html=True,
        )

        uploaded = st.file_uploader(
            "Maze image (PNG / JPG)",
            type=["png", "jpg", "jpeg"],
            key="vision_upload",
        )
        if uploaded is not None:
            st.session_state.uploaded_map = {
                "name": uploaded.name,
                "bytes": uploaded.getvalue(),
                "mime": uploaded.type or "image/png",
            }

        dry_label = engine.backend_label("dry")
        reader_choice = st.radio(
            "Reader",
            [dry_label, "Live model"],
            key="vision_reader",
            horizontal=True,
        )
        scripted = reader_choice == dry_label

        # The image in hand: your upload if there is one, otherwise the built-in
        # sample — a drawing of the default world in exactly the terms
        # build_map_prompt describes (R with a heading arrow, G, dark X walls), so
        # the lab demonstrates end to end without a photo and a live model still
        # gets a real raster to read.
        held = st.session_state.uploaded_map
        sample_bytes = vision.sample_image_bytes(new_world())
        if held is not None:
            held_image = {
                "name": held["name"],
                "bytes": held["bytes"],
                "mime": held["mime"],
                "source": "uploaded",
            }
        elif sample_bytes is not None:
            held_image = {
                "name": "built-in-sample.png",
                "bytes": sample_bytes,
                "mime": "image/png",
                "source": "built-in sample",
            }
        else:
            held_image = None

        if scripted:
            st.caption(
                f"Dry mode: the reader is scripted ({dry_label}), the image never "
                f"leaves the app, the first reply is a deliberate off-grid misread "
                f"and the second is the corrected map. Live mode reads the image "
                f"with the sidebar engine ({engine.backend_label(backend)})."
            )

        if st.button(
            "Read map",
            type="primary",
            key="vision_read",
            disabled=held_image is None,
            shortcut=SHORTCUTS["read_map"],
            help="Asks Gemma Vision to turn the image into a world model, then "
                 "validates it before anything can be loaded. "
                 f"Shortcut: {SHORTCUTS['read_map']}.",
        ):
            if held_image is None:
                st.warning("Upload an image first.")
            else:
                with st.spinner("Gemma Vision is reading the map…"):
                    result = engine.run_map_vision(
                        held_image["bytes"],
                        held_image["mime"],
                        backend="dry" if scripted else backend,
                        max_tries=max_tries,
                    )
                st.session_state.vision_result = {
                    "world": result["world"],
                    "history": result["history"],
                    "attempts": result["attempts"],
                    "max_tries": result["max_tries"],
                    "latency": result["latency"],
                    "backend": result["backend"],
                    "reader": engine.backend_label(result["backend"]),
                    "error": result["error"],
                    "image": {
                        "name": held_image["name"],
                        "size": len(held_image["bytes"]),
                        "mime": held_image["mime"],
                        "source": held_image["source"],
                    },
                }
                st.session_state.vision_loaded = False
                st.session_state.last_run = {
                    "source": "vision",
                    "backend": result["backend"],
                    "attempts": result["attempts"],
                    "max_tries": result["max_tries"],
                    "latency": result["latency"],
                    "attempts_label": f"{result['attempts']} / {result['max_tries']}",
                    "latency_label": f"{result['latency']:.2f} s",
                    "status": (
                        "Valid world" if result["world"] is not None
                        else "Map rejected"
                    ),
                }
                st.rerun()

        lab = st.session_state.vision_result
        world = lab["world"] if lab else None
        loaded = bool(st.session_state.get("vision_loaded"))
        checks_rows = vision.checks(world)
        passed = sum(1 for row in checks_rows if row["passed"])

        col_image, col_vision, col_world = st.columns(3, gap="large")

        # ── Left: the image the reading is made from ──────────────────────
        with col_image:
            st.markdown(
                DS.section_title(vision.COLUMN_TITLES["image"]),
                unsafe_allow_html=True,
            )
            if held_image is None:
                st.markdown(
                    vision.column_html(
                        "image",
                        empty_state(
                            "No image in hand.",
                            "Upload a maze photo. The built-in sample needs "
                            "Pillow, which is not installed here.",
                        ),
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.image(held_image["bytes"], width="stretch")
                if lab is not None and lab["image"]["name"] != held_image["name"]:
                    st.caption(
                        f"The reading shown was made from {lab['image']['name']} — "
                        "read the image in hand to replace it."
                    )
                st.markdown(
                    vision.column_html(
                        "image",
                        vision.facts_html(
                            vision.image_rows(
                                name=held_image["name"],
                                size=len(held_image["bytes"]),
                                mime=held_image["mime"],
                                source=(
                                    "uploaded photo"
                                    if held_image["source"] == "uploaded"
                                    else "drawn from the default world — not a photo"
                                ),
                            )
                        )
                        + f"<div style='margin-top:{S.px(S.SM)};"
                        f"font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
                        f"color:{C.TEXT_MUTED}'>"
                        + (
                            "Dry mode never sends these bytes to a model."
                            if scripted
                            else "Live mode sends these exact bytes to the model."
                        )
                        + "</div>",
                    ),
                    unsafe_allow_html=True,
                )

        # ── Middle: what Gemma Vision returned, verbatim ──────────────────
        with col_vision:
            st.markdown(
                DS.section_title(vision.COLUMN_TITLES["vision"]),
                unsafe_allow_html=True,
            )
            if lab is None:
                body = (
                    f"<div style='font-family:{T.FONT_MONO};"
                    f"font-size:{T.SIZE_SM}px;color:{C.TEXT_MUTED}'>"
                    "No reading yet — the raw reply, the world it proposes and the "
                    "verdict on it appear here.</div>"
                )
            else:
                body = vision.meta_html(
                    lab["reader"],
                    attempts=lab["attempts"],
                    max_tries=lab["max_tries"],
                    latency=lab["latency"],
                    scripted=lab["backend"] == engine.DRY_BACKEND,
                ) + vision.readings_html(vision.readings(lab["history"]))
                body += (
                    f"<div style='margin-top:{S.px(S.SM)}'>"
                    + (
                        DS.status_chip("World accepted", "success")
                        if world is not None
                        else DS.status_chip("Map rejected", "error")
                    )
                    + "</div>"
                )
            st.markdown(vision.column_html("vision", body), unsafe_allow_html=True)
            if lab is not None and world is None and lab["error"]:
                st.error(lab["error"])

        # ── Right: the world model the reading proposes ───────────────────
        with col_world:
            st.markdown(
                DS.section_title(vision.COLUMN_TITLES["world"]),
                unsafe_allow_html=True,
            )
            body = (
                DS.section_title("Validation")
                + vision.checks_html(checks_rows)
                + f"<div style='height:{S.px(S.LG)}'></div>"
                + vision.facts_html(vision.world_rows(world))
            )
            if world is not None:
                # The grid is drawn at its designed cell size; in a narrow column
                # it scrolls inside its own box rather than stretching the row.
                body += (
                    f"<div style='height:{S.px(S.LG)}'></div>"
                    + ui_helpers.grid_legend_html()
                    + "<div style='overflow-x:auto'>"
                    + ui_helpers.world_grid_html(world, cell_px=S.CELL_SIZE)
                    + "</div>"
                )
            st.markdown(vision.column_html("world", body), unsafe_allow_html=True)

        # ── Load into simulator ───────────────────────────────────────────
        if world is None:
            st.button(
                "Load into simulator",
                key="vision_load",
                disabled=True,
                help="Disabled until a reading has passed every world check.",
            )
            st.caption(
                "Nothing to load: no reading has passed validation yet."
            )
        else:
            # A callback, not an inline call: the sidebar's map picker is already
            # instantiated by the time this renders, and only a callback may
            # move it.
            st.button(
                "Load into simulator",
                key="vision_load",
                type="primary",
                on_click=_load_vision_into_simulator,
                help="Adopts the validated world as the active map and clears "
                     "the results measured on the previous one.",
            )
            if loaded:
                st.markdown(
                    DS.status_chip(
                        f"Loaded — the simulator is on {_map_label('scanned')}",
                        "success",
                    ),
                    unsafe_allow_html=True,
                )
            else:
                st.caption(
                    "The reading is validated but not loaded: the simulator is "
                    f"still on {_map_label(st.session_state.map_name)}."
                )

        # ── Animate: Image → World → Simulator ────────────────────────────
        st.markdown(DS.section_title("Pipeline"), unsafe_allow_html=True)
        st.caption(
            "Each stage lights because the step itself happened, not on a timer: "
            "an image is in hand, a reading passed the checks, that world is the "
            "active map."
        )
        st.markdown(
            vision.flow_html(
                vision.flow_stages(
                    has_image=held_image is not None,
                    world_ok=world is not None,
                    loaded=loaded,
                    image_detail=(
                        f"{held_image['name']} · "
                        f"{len(held_image['bytes']) / 1024:.1f} kB"
                        if held_image else ""
                    ),
                    world_detail=(
                        f"reading passed {passed} of {len(checks_rows)} checks "
                        f"on attempt {lab['attempts']}"
                        if lab is not None and world is not None else ""
                    ),
                    sim_detail=f"active map: {_map_label(st.session_state.map_name)}",
                )
            ),
            unsafe_allow_html=True,
        )

        # ── Every attempt, with the prompt the retry carried ──────────────
        if lab is not None:
            with st.expander("Vision attempts"):
                _render_attempt_cards(
                    ui_helpers.attempt_cards(lab["history"]),
                    reply_label="Vision response",
                    ok_message="✓ Valid world",
                )

# ── Replay ────────────────────────────────────────────────────────────────
if HAVE_LOGGER:
    with tabs["Run History"]:
        st.markdown(
            console_shell.zone_bar_html(
                "Replay", "pure simulation — no planner, no vision, no network"
            ),
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED};margin-bottom:{S.px(S.LG)}'>"
            "Every run the app logs records the world it ran on and the plans it "
            "produced, so a run can be re-run here by the simulator alone. Pure "
            "replay: no planner, no vision, no network — the movement, the steps "
            "and the messages are <code>simulator.step</code>'s own output."
            "</div>",
            unsafe_allow_html=True,
        )

        try:
            records = run_logger.load_runs(path=str(LOG_PATH))
        except Exception as exc:  # noqa: BLE001 - a broken log must not kill the tab
            records = []
            st.warning(f"Could not read {LOG_PATH.name}: {exc}")

        log_runs = replay_panel.runs(records)
        ready = [item for item in log_runs if item["replayable"]]

        if not log_runs:
            st.markdown(
                DS.card(
                    f"<div style='font-family:{T.FONT_MONO};"
                    f"font-size:{T.SIZE_SM}px;color:{C.TEXT_SECONDARY}'>"
                    "No runs logged yet. Run a plan in <b>Text command</b>, or "
                    "run a <b>Safety Lab</b> check in dry mode — that one needs "
                    "no API key and still logs a replayable run. Each run is "
                    "appended to "
                    f"<code>{LOG_PATH.relative_to(ROOT)}</code> with the world it "
                    "ran on, and it can be replayed here.<br><br>"
                    f"<span style='color:{C.TEXT_MUTED}'>A record logged before "
                    "worlds were captured is listed but cannot be replayed — "
                    "there is nothing to run its plan on.</span></div>",
                    title="Nothing to replay",
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(replay_panel.runs_html(log_runs), unsafe_allow_html=True)
            st.caption(
                f"{len(log_runs)} run(s) in {LOG_PATH.relative_to(ROOT)} · "
                f"{len(ready)} replayable · newest first"
            )

            run_labels = [
                f"{item['label']} · {item['backend_label']} · "
                f"{item['latency_label']} · {item['attempts_label']} attempt(s)"
                for item in log_runs
            ]
            # Default the picker to the newest run that can actually be
            # replayed, so a run logged a moment ago is the one selected rather
            # than a legacy record that would only leave Replay disabled.  A run
            # the user picked by hand is never overridden: a pick is told apart
            # from a default by remembering what the default was last time.
            auto_label = ready[0]["label"] if ready else run_labels[0]
            if (
                st.session_state.get("replay_run") not in run_labels
                or st.session_state.get("replay_run")
                == st.session_state.get("replay_auto_run")
            ):
                st.session_state.replay_run = auto_label
            st.session_state.replay_auto_run = auto_label

            picked_label = st.selectbox("Run", run_labels, key="replay_run")
            picked = log_runs[run_labels.index(picked_label)]

            # A plan is only offered for a run that can actually be replayed:
            # picking a plan for a record with no world would be a dead end.
            plan = None
            plan_labels = (
                [option["label"] for option in picked["plans"]]
                if picked["replayable"] else []
            )
            # A plan belongs to one run, so switching runs drops the old pick.
            if st.session_state.get("replay_plan_run") != picked_label:
                st.session_state.pop("replay_plan", None)
                st.session_state.replay_plan_run = picked_label
            if plan_labels:
                plan_label = st.selectbox(
                    "Plan to replay", plan_labels, key="replay_plan"
                )
                plan = picked["plans"][plan_labels.index(plan_label)]

            if picked["replayable"]:
                if st.button(
                    "Replay",
                    type="primary",
                    key="replay_start",
                    shortcut=SHORTCUTS["replay"],
                    help="Re-executes the recorded plan in the simulator. No "
                         f"model is called. Shortcut: {SHORTCUTS['replay']}.",
                ):
                    timeline = replay_panel.timeline(picked["record"], plan)
                    if timeline is None:
                        st.warning(
                            "This record has no runnable plan to replay."
                        )
                    else:
                        st.session_state.log_replay = {
                            "run": picked,
                            "plan": plan,
                            "timeline": timeline,
                        }
                        st.session_state.log_replay_autoplay = True
                        st.rerun()
            else:
                st.button(
                    "Replay",
                    key="replay_start",
                    type="primary",
                    disabled=True,
                    help="This record cannot be replayed; the reason is below.",
                )
                st.caption(f"Not replayable — {picked['reason']}.")

        shown = st.session_state.log_replay
        if shown:
            st.markdown(DS.divider(), unsafe_allow_html=True)
            st.markdown(
                replay_panel.meta_html(shown["run"], shown["plan"]),
                unsafe_allow_html=True,
            )
            st.markdown(
                replay_panel.facts_html(replay_panel.facts_rows(shown["run"])),
                unsafe_allow_html=True,
            )

            st.markdown(DS.section_title("Timeline"), unsafe_allow_html=True)
            st.markdown(
                replay_panel.timeline_html(shown["run"], shown["plan"]),
                unsafe_allow_html=True,
            )

            st.markdown(
                DS.section_title("Robot movement"), unsafe_allow_html=True
            )
            st.markdown(
                f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                f"color:{C.TEXT_SECONDARY};margin-bottom:{S.px(S.SM)}'>"
                f"{shown['run']['label']} · {shown['plan']['label']} — the player "
                "highlights the action it is on, and the trace behind the robot is "
                "the path the simulator took.</div>",
                unsafe_allow_html=True,
            )
            _render_log_replay(shown["timeline"])
            st.markdown(
                replay_panel.source_html(str(LOG_PATH.relative_to(ROOT)), shown["run"]),
                unsafe_allow_html=True,
            )

# ── Benchmark ─────────────────────────────────────────────────────────────
def _benchmark_sources() -> list[dict]:
    """The Benchmark Lab's two sources, each measured on its own.

    The run log is everything this app has ever run; the stored artifact is what
    the benchmark runner wrote.  They overlap -- the runner logs every run it
    makes -- so the lab never adds them together, and each is labelled with the
    file it was read from.  A source that cannot be read is reported and skipped
    rather than replaced with an empty chart.
    """
    sections: list[dict] = []

    records: list[dict] = []
    if HAVE_LOGGER:
        try:
            records = run_logger.load_runs(str(LOG_PATH))
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Run log could not be read: {exc}")
    sections.append({
        "id": "log",
        "title": "Run log - every run this app has made",
        "source": "appended by the app and by the benchmark runner",
        "path": str(LOG_PATH.relative_to(ROOT)),
        "note": "a run's mode is recorded when it is logged",
        "rows": benchmark_panel.rows(records, "run log"),
    })

    stored: list[dict] = []
    if BENCHMARK_JSON.exists():
        try:
            data = json.loads(BENCHMARK_JSON.read_text(encoding="utf-8"))
            stored = data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError) as exc:
            st.warning(f"benchmarks/results.json could not be read: {exc}")
    sections.append({
        "id": "artifact",
        "title": "Stored benchmark artifact - benchmarks/results.json",
        "source": "written by python -m gemmabot.benchmark",
        "path": str(BENCHMARK_JSON.relative_to(ROOT)),
        "note": "the runner also appends to the run log, so these runs appear above too",
        "rows": benchmark_panel.rows(stored, "stored benchmark artifact"),
    })
    return sections


if HAVE_BENCHMARK:
    with tabs["Benchmark"]:
        _sections = _benchmark_sources()
        st.markdown(
            benchmark_panel.panel(
                benchmark_panel.intro_html(_sections)
                + f"<div style='height:{S.px(S.MD)}'></div>"
                + benchmark_panel.caveats_html(_sections)
                + f"<div style='height:{S.px(S.LG)}'></div>"
                + "".join(
                    benchmark_panel.section_html(section) for section in _sections
                )
            ),
            unsafe_allow_html=True,
        )
        if BENCHMARK_PATH.exists():
            with st.expander("Raw stored artifact - benchmarks/results.md"):
                st.caption(
                    "Written by python -m gemmabot.benchmark and shown verbatim. "
                    "The lab above is the measured view of the same runs; each "
                    "row there carries the mode it was run in."
                )
                st.markdown(BENCHMARK_PATH.read_text(encoding="utf-8"))
