"""GemmaBot — Streamlit frontend.

Propose (Gemma) → Verify (code) → Execute (simulator).

Owner: FRONTEND.  No fake results live here: every number, status, world and
action shown comes from a real backend result — ``harness.plan_with_repair``
history, ``map_vision.read_map`` history, ``simulator.render``/``step``,
``logger`` summaries and the benchmark files.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from gemmabot.config import MAX_REPAIRS, STEP_DELAY

import engine
import ui_helpers

# Design system
from frontend.components.theme import inject_theme
from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T

ROOT = Path(__file__).parent
LOG_PATH = ROOT / "logs" / "runs.jsonl"
BENCHMARK_PATH = ROOT / "benchmarks" / "results.md"

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
    "scanned": "Scanned map (MapVision)",
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
    st.session_state.setdefault("mapvision_meta", None)
    st.session_state.setdefault("mapvision_result", None)
    st.session_state.setdefault("mapvision_history", [])
    st.session_state.setdefault("uploaded_map", None)
    st.session_state.setdefault("connections", None)


_init_state()


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

def _reset_world() -> None:
    name = st.session_state.map_name
    st.session_state.world = copy.deepcopy(st.session_state.map_source[name])
    st.session_state.logs = []
    st.session_state.text_result = None


def _use_scanned_map() -> None:
    scanned = copy.deepcopy(st.session_state.mapvision_result)
    if scanned is None:
        return
    st.session_state.map_source["scanned"] = scanned
    st.session_state.map_name = "scanned"
    st.session_state.map_picker = "scanned"
    st.session_state.world = copy.deepcopy(scanned)
    st.session_state.logs = []
    st.session_state.text_result = None


# ---------------------------------------------------------------------------
# Rendering helpers (design-system backed)
# ---------------------------------------------------------------------------

def _draw_board(placeholder, world: dict, path: list | None = None, current_step: list | None = None) -> None:
    """Render the hero grid from the world dict (source of truth)."""
    placeholder.markdown(
        ui_helpers.world_grid_html(
            world,
            path=path or [],
            current_step=current_step if current_step is not None else -1,
        ),
        unsafe_allow_html=True,
    )


def _render_telemetry(summary: dict) -> None:
    """Four native st.metric widgets, styled by the design-system CSS."""
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Attempts", summary.get("attempts_label", "—"))
    col2.metric("Latency",  summary.get("latency_label",  "—"))
    col3.metric("Backend",  summary.get("backend",        "—"))
    col4.metric("Status",   summary.get("status",         "—"))


def _run_status_chip(summary: dict) -> None:
    """Animated StatusChip showing the outcome of the last run."""
    status = summary.get("status", "")
    state: DS.State
    if "safe" in status.lower() or "valid" in status.lower():
        state = "success"
    elif "failed" in status.lower() or "rejected" in status.lower():
        state = "error"
    elif "plan" in status.lower() and "no" in status.lower():
        state = "warning"
    else:
        state = "neutral"
    st.markdown(DS.status_chip(status, state), unsafe_allow_html=True)


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
    DS.section_title("Control Panel"), unsafe_allow_html=True
)

engine_choice = st.sidebar.radio("Engine", list(ENGINE_BACKENDS.keys()))
backend = ENGINE_BACKENDS[engine_choice]

max_tries = int(
    st.sidebar.number_input(
        "Max tries (plan & vision)",
        min_value=1,
        max_value=5,
        value=max(1, MAX_REPAIRS + 1),
        step=1,
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
)
if chosen_map != st.session_state.map_name:
    st.session_state.map_name = chosen_map
    st.session_state.world = copy.deepcopy(st.session_state.map_source[chosen_map])
    st.session_state.logs = []
    st.session_state.text_result = None
    st.session_state.last_run = None

animation_speed = st.sidebar.slider(
    "Animation speed (s / step)", 0.0, 1.5, float(STEP_DELAY), 0.05
)

st.sidebar.button("Reset world", on_click=_reset_world)

if st.sidebar.button("Check connections"):
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
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
        f"color:{C.TEXT_MUTED};padding:{S.px(S.XS)} 0'>No runs yet.</div>",
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
            st.caption("No runs logged yet.")
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


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

st.title("🤖 GemmaBot")
st.markdown(
    DS.badge("Propose", "running") + "&nbsp;" +
    DS.badge("Verify", "neutral") + "&nbsp;" +
    DS.badge("Execute", "neutral"),
    unsafe_allow_html=True,
)

tab_names = ["Text command"]
if HAVE_MAPVISION:
    tab_names.append("Scan map")
if HAVE_BENCHMARK:
    tab_names.append("Benchmark")
tabs = dict(zip(tab_names, st.tabs(tab_names)))


# ── Text command ──────────────────────────────────────────────────────────
with tabs["Text command"]:
    st.markdown(
        DS.section_title(
            f"Text command · {_map_label(st.session_state.map_name)}", icon="⬛"
        ),
        unsafe_allow_html=True,
    )

    # Legend above the grid
    st.markdown(ui_helpers.grid_legend_html(), unsafe_allow_html=True)

    board = st.empty()
    _draw_board(board, st.session_state.world)

    instruction = st.text_input(
        "Instruction", "Move to the goal using the safest route."
    )

    if st.button("Run plan", type="primary"):
        if not instruction.strip():
            st.warning("Enter an instruction first.")
        else:
            result = engine.run_plan(
                instruction,
                st.session_state.world,
                backend=backend,
                max_tries=max_tries,
            )
            metrics = ui_helpers.run_metrics(
                result["actions"], result["attempts"], max_tries, result["latency"]
            )
            outcome = None

            if result["actions"] is not None:
                exec_placeholder = st.empty()
                executed_log: list[dict] = []
                executed_text: list[str] = []
                executed_path: list[list[int]] = []

                def _on_step(entry: dict, sim_world: dict) -> None:
                    executed_log.append(entry)
                    executed_text.append(
                        f"step {entry['step']}: "
                        f"{entry['action']} -> {entry['message']}"
                    )
                    # Track path: the robot's current position is the new step
                    current_pos = list(sim_world["robot"])
                    if executed_path and executed_path[-1] != current_pos:
                        executed_path.append(list(executed_path[-1]))  # previous pos → path
                    executed_path.append(current_pos)
                    exec_placeholder.markdown(
                        DS.action_list(executed_log), unsafe_allow_html=True
                    )
                    _draw_board(board, sim_world,
                                path=executed_path[:-1],
                                current_step=current_pos)
                    if animation_speed > 0:
                        time.sleep(animation_speed)

                outcome = engine.execute(
                    st.session_state.world, result["actions"], on_step=_on_step
                )
                st.session_state.world = outcome["world"]
                st.session_state.logs.extend(executed_text)

            st.session_state.text_result = {
                **result,
                "instruction": instruction,
                "max_tries": max_tries,
                "metrics": metrics,
                "outcome": outcome,
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
                    )
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Run log could not be written: {exc}")

    # Persisted result — survives reruns
    stored = st.session_state.text_result
    if stored:
        st.markdown(DS.divider(), unsafe_allow_html=True)

        # Instruction echo
        st.markdown(
            DS.card(
                f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                f"color:{C.TEXT_SECONDARY}'>{stored['instruction']}</span>",
                title="Instruction",
            ),
            unsafe_allow_html=True,
        )

        # Telemetry row
        _render_telemetry({**stored["metrics"], "backend": stored["backend"]})

        # Outcome status
        outcome = stored["outcome"]
        if stored["actions"] is None:
            st.error(
                f"Planning failed after {stored['attempts']} attempt(s): "
                f"{stored['error']}"
            )
        else:
            n = len(stored["actions"])
            if outcome and outcome["reached"]:
                st.markdown(
                    DS.status_chip("🎯  Goal reached", "success"),
                    unsafe_allow_html=True,
                )
            elif outcome and not outcome["ok"]:
                st.markdown(
                    DS.status_chip("Execution blocked", "error"),
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    DS.status_chip(f"{n} action(s) executed", "warning"),
                    unsafe_allow_html=True,
                )

        # Attempt cards (propose → verify loop)
        st.markdown(DS.section_title("Planning loop"), unsafe_allow_html=True)
        _render_attempt_cards(
            ui_helpers.attempt_cards(stored["history"]),
            reply_label="Raw Gemma reply",
            ok_message="✓ Plan accepted (verified by dry_run)",
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


# ── Scan map ──────────────────────────────────────────────────────────────
if HAVE_MAPVISION:
    with tabs["Scan map"]:
        st.markdown(
            DS.section_title("Map scanner", icon="📷"), unsafe_allow_html=True
        )
        st.markdown(
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED};margin-bottom:{S.px(S.LG)}'>"
            "Upload a photo of an 8×8 maze. "
            "R = robot (arrow = facing direction), G = goal, "
            "X / dark cells = walls.</div>",
            unsafe_allow_html=True,
        )

        uploaded = st.file_uploader(
            "Maze image (PNG / JPG)", type=["png", "jpg", "jpeg"]
        )
        if uploaded is not None:
            st.image(uploaded, caption=uploaded.name)
            st.session_state.uploaded_map = {
                "name": uploaded.name,
                "bytes": uploaded.getvalue(),
                "mime": uploaded.type or "image/png",
            }

        if st.button("Read map", type="primary", disabled=uploaded is None):
            payload = st.session_state.uploaded_map
            if payload is None:
                st.warning("Upload an image first.")
            else:
                with st.spinner("Gemma Vision is parsing the map…"):
                    vision = engine.run_map_vision(
                        payload["bytes"],
                        payload["mime"],
                        backend=backend,
                        max_tries=max_tries,
                    )
                st.session_state.mapvision_meta = vision
                st.session_state.mapvision_result = vision["world"]
                st.session_state.mapvision_history = vision["history"]
                st.session_state.last_run = {
                    "source": "vision",
                    "backend": vision["backend"],
                    "attempts": vision["attempts"],
                    "max_tries": vision["max_tries"],
                    "latency": vision["latency"],
                    "attempts_label": f"{vision['attempts']} / {vision['max_tries']}",
                    "latency_label": f"{vision['latency']:.2f} s",
                    "status": "Valid map" if vision["world"] is not None else "Map rejected",
                }

        vision_meta    = st.session_state.mapvision_meta
        vision_world   = st.session_state.mapvision_result
        vision_history = st.session_state.mapvision_history

        if vision_meta is not None:
            st.markdown(DS.divider(), unsafe_allow_html=True)
            st.markdown(
                DS.section_title("Map analysis"), unsafe_allow_html=True
            )
            _render_telemetry(
                {
                    "attempts_label": f"{vision_meta['attempts']} / {vision_meta['max_tries']}",
                    "latency_label":  f"{vision_meta['latency']:.2f} s",
                    "backend":        vision_meta["backend"],
                    "status": "Valid map" if vision_world is not None else "Map rejected",
                }
            )

            if vision_world is not None:
                world_rows = [
                    ("Robot",      str(vision_world["robot"])),
                    ("Direction",  vision_world["dir"]),
                    ("Goal",       str(vision_world["goal"])),
                    ("Walls",      str(len(vision_world["walls"]))),
                ]
                col1, col2 = st.columns(2)
                col1.markdown(
                    DS.telemetry_block(world_rows[:2]), unsafe_allow_html=True
                )
                col2.markdown(
                    DS.telemetry_block(world_rows[2:]), unsafe_allow_html=True
                )
                st.markdown(
                    DS.status_chip("World accepted", "success"),
                    unsafe_allow_html=True,
                )
                st.markdown(DS.section_title("Parsed grid"), unsafe_allow_html=True)
                st.markdown(ui_helpers.grid_legend_html(), unsafe_allow_html=True)
                st.markdown(
                    ui_helpers.world_grid_html(vision_world),
                    unsafe_allow_html=True,
                )
                st.button("Use this map", on_click=_use_scanned_map)
            else:
                reason = (
                    vision_meta.get("error")
                    or (
                        vision_history[-1]["feedback"]
                        if vision_history
                        else "the backend provided no further detail"
                    )
                )
                st.markdown(
                    DS.status_chip("Map rejected", "error"), unsafe_allow_html=True
                )
                st.error(reason)

            st.markdown(DS.section_title("Vision attempts"), unsafe_allow_html=True)
            _render_attempt_cards(
                ui_helpers.attempt_cards(vision_history),
                reply_label="Vision response",
                ok_message="✓ Valid world",
            )


# ── Benchmark ─────────────────────────────────────────────────────────────
if HAVE_BENCHMARK:
    with tabs["Benchmark"]:
        st.markdown(
            DS.section_title("Benchmark results"), unsafe_allow_html=True
        )
        if BENCHMARK_PATH.exists():
            st.caption(f"Source: {BENCHMARK_PATH.relative_to(ROOT)}")
            st.markdown(BENCHMARK_PATH.read_text(encoding="utf-8"))
        else:
            st.markdown(
                DS.card(
                    f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                    f"color:{C.TEXT_SECONDARY}'>"
                    "No benchmark results yet. Generate them with:<br><br>"
                    f"<code style='color:{C.ACCENT_BLUE}'>"
                    "python -m gemmabot.benchmark --dry</code><br><br>"
                    "Dry mode uses fake models — no network, no API credits. "
                    "Drop <code>--dry</code> to benchmark real backends.<br><br>"
                    f"<span style='color:{C.TEXT_MUTED}'>Results are written to "
                    "benchmarks/results.md and benchmarks/results.json.</span>"
                    "</div>",
                    title="No results",
                ),
                unsafe_allow_html=True,
            )
