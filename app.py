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
from gemmabot.simulator import render

import engine
import ui_helpers

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

MAP_LABELS = {
    "default": "Default world (new_world())",
    "sample": "Sample 8×8 maze (dev map)",
    "scanned": "Scanned map (MapVision)",
}
ENGINE_BACKENDS = {"API": "api", "Local": "local", "Auto": "auto"}


def _map_label(name: str) -> str:
    return MAP_LABELS.get(name, name)


# ---------------------------------------------------------------------------
# Session state (spec §26) — initialised once
# ---------------------------------------------------------------------------

def _init_state() -> None:
    """Set defaults for any missing session key (safe across code updates)."""
    st.session_state.initialized = True
    if "map_source" not in st.session_state:
        st.session_state.map_source = engine.default_maps()
    st.session_state.setdefault("map_name", "default")
    if "world" not in st.session_state:
        st.session_state.world = copy.deepcopy(
            st.session_state.map_source.get("default", next(iter(st.session_state.map_source.values())))
        )
    st.session_state.setdefault("logs", [])
    st.session_state.setdefault("last_run", None)       # sidebar telemetry summary
    st.session_state.setdefault("text_result", None)    # full Text command result
    st.session_state.setdefault("mapvision_meta", None)
    st.session_state.setdefault("mapvision_result", None)
    st.session_state.setdefault("mapvision_history", [])
    st.session_state.setdefault("uploaded_map", None)
    st.session_state.setdefault("connections", None)


_init_state()


# ---------------------------------------------------------------------------
# Callbacks (run before the rerun, so widget keys can be written safely)
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
# Rendering helpers
# ---------------------------------------------------------------------------

def _draw_board(placeholder, world: dict) -> None:
    """Render the world through the simulator renderer (source of truth)."""
    placeholder.markdown(
        ui_helpers.grid_html(render(world)), unsafe_allow_html=True
    )


def _render_attempt_cards(cards: list[dict], reply_label: str, ok_message: str) -> None:
    """Show the propose → verify loop for every attempt, from real history."""
    if not cards:
        st.info("No model attempt was recorded.")
        return
    for card in cards:
        title = f"{card['label']} — {card['status']}"
        with st.expander(title, expanded=not card["ok"]):
            st.markdown("**Prompt sent to the model**")
            st.code(card["prompt"] or "(none)", language="text")
            st.markdown(f"**{reply_label}**")
            st.code(card["reply"] or "(empty)", language="text")
            if card["parsed"] is not None:
                st.markdown("**Parsed JSON**")
                st.json(card["parsed"])
            st.markdown("**Verification**")
            if card["ok"]:
                st.success(ok_message)
            else:
                st.error(f"✗ {card['feedback']}")


def _render_telemetry(summary: dict) -> None:
    """Show measured run metrics; missing keys degrade to em dashes."""
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Attempts", summary.get("attempts_label", "—"))
    col2.metric("Latency", summary.get("latency_label", "—"))
    col3.metric("Backend", summary.get("backend", "—"))
    col4.metric("Status", summary.get("status", "—"))


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.header("Control")

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
    "Animation speed (seconds per move)", 0.0, 1.5, float(STEP_DELAY), 0.05
)

st.sidebar.button("Reset world", on_click=_reset_world)

if st.sidebar.button("Check connections"):
    st.session_state.connections = engine.check_connections()
connections = st.session_state.connections
if connections:
    st.sidebar.markdown(
        f"**Connections**  \n"
        f"API key set: {'yes' if connections['api_key_set'] else 'no'}  \n"
        f"Ollama reachable: {'yes' if connections['ollama_reachable'] else 'no'}"
    )
    st.sidebar.caption(
        "Ollama models: " + (", ".join(connections["ollama_models"]) or "—")
    )

st.sidebar.subheader("Telemetry")
summary = st.session_state.last_run
if summary:
    st.sidebar.write(f"Attempts: {summary['attempts_label']}")
    st.sidebar.write(f"Latency: {summary['latency_label']}")
    st.sidebar.write(f"Backend: {summary['backend']}")
    st.sidebar.write(f"Status: {summary['status']}")
else:
    st.sidebar.caption("No runs yet.")

if HAVE_LOGGER:
    with st.sidebar.expander("Run logs (last 10)"):
        try:
            runs = run_logger.load_runs(path=str(LOG_PATH))
        except Exception as exc:  # noqa: BLE001 - logs never break the app
            runs = []
            st.caption(f"Could not read logs: {exc}")
        if not runs:
            st.caption("No runs logged yet.")
        for record in list(reversed(runs))[:10]:
            try:
                st.text(run_logger.summarize_run(record))
            except Exception as exc:  # noqa: BLE001
                st.text(f"(unreadable run: {exc})")


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------

st.title("🤖 GemmaBot")
st.caption("Propose (Gemma) → Verify (code) → Execute (simulator)")

tab_names = ["Text command"]
if HAVE_MAPVISION:
    tab_names.append("Scan map")
if HAVE_BENCHMARK:
    tab_names.append("Benchmark")
tabs = dict(zip(tab_names, st.tabs(tab_names)))


# ── Text command ─────────────────────────────────────────────────────────
with tabs["Text command"]:
    st.subheader("Text command")
    st.markdown(f"**Active map:** {_map_label(st.session_state.map_name)}")

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
                exec_line = st.empty()
                executed: list[str] = []

                def _on_step(entry: dict, sim_world: dict) -> None:
                    executed.append(
                        f"step {entry['step']}: {entry['action']} -> {entry['message']}"
                    )
                    exec_line.text("\n".join(executed))
                    _draw_board(board, sim_world)
                    if animation_speed > 0:
                        time.sleep(animation_speed)

                outcome = engine.execute(
                    st.session_state.world, result["actions"], on_step=_on_step
                )
                st.session_state.world = outcome["world"]
                st.session_state.logs.extend(executed)

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

    # Render the stored result so it survives reruns and human inspection.
    stored = st.session_state.text_result
    if stored:
        st.markdown(f"**Instruction:** {stored['instruction']}")
        _render_telemetry({**stored["metrics"], "backend": stored["backend"]})
        _render_attempt_cards(
            ui_helpers.attempt_cards(stored["history"]),
            reply_label="Raw Gemma reply",
            ok_message="✓ Plan accepted (verified by dry_run)",
        )
        if stored["actions"] is None:
            st.error(
                f"Planning failed after {stored['attempts']} attempt(s): "
                f"{stored['error']}"
            )
        else:
            st.markdown(
                f"**Accepted plan:** {len(stored['actions'])} action(s) — "
                "executed on the simulator"
            )
            outcome = stored["outcome"]
            if outcome and outcome["reached"]:
                st.success("🎯 Goal reached!")
            elif outcome and not outcome["ok"]:
                st.error("Execution stopped: the simulator blocked an action.")
            elif outcome:
                st.warning("Plan finished without reaching the goal.")

    with st.expander("Execution log"):
        if st.session_state.logs:
            st.text("\n".join(st.session_state.logs))
        else:
            st.caption("No actions executed yet.")


# ── Scan map ─────────────────────────────────────────────────────────────
if HAVE_MAPVISION:
    with tabs["Scan map"]:
        st.subheader("Scan map")
        st.caption(
            "Upload a photo or scan of an 8×8 maze: R = robot (arrow = facing), "
            "G = goal, X / dark cells = walls."
        )

        uploaded = st.file_uploader("Maze image (PNG/JPG)", type=["png", "jpg", "jpeg"])
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
                with st.spinner("Gemma Vision is proposing a world…"):
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

        # Always render the stored vision result (persists across reruns).
        vision_meta = st.session_state.mapvision_meta
        vision_world = st.session_state.mapvision_result
        vision_history = st.session_state.mapvision_history

        if vision_meta is not None:
            st.markdown("### Map analysis")
            _render_telemetry(
                {
                    "attempts_label": f"{vision_meta['attempts']} / {vision_meta['max_tries']}",
                    "latency_label": f"{vision_meta['latency']:.2f} s",
                    "backend": vision_meta["backend"],
                    "status": "Valid map" if vision_world is not None else "Map rejected",
                }
            )
            if vision_world is not None:
                col1, col2 = st.columns(2)
                col1.write(f"Robot: {vision_world['robot']}")
                col1.write(f"Direction: {vision_world['dir']}")
                col2.write(f"Goal: {vision_world['goal']}")
                col2.write(f"Walls: {len(vision_world['walls'])}")
                st.success("✓ World accepted")
                st.markdown("**Simulator render of the parsed world**")
                st.markdown(
                    ui_helpers.grid_html(render(vision_world)),
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
                st.error(f"Map rejected.\n\nReason: {reason}")

            st.markdown("### Vision attempts")
            _render_attempt_cards(
                ui_helpers.attempt_cards(vision_history),
                reply_label="Vision response",
                ok_message="✓ Valid world",
            )


# ── Benchmark ────────────────────────────────────────────────────────────
if HAVE_BENCHMARK:
    with tabs["Benchmark"]:
        st.subheader("Benchmark")
        if BENCHMARK_PATH.exists():
            st.caption(f"Source: {BENCHMARK_PATH.relative_to(ROOT)}")
            st.markdown(BENCHMARK_PATH.read_text(encoding="utf-8"))
        else:
            st.info(
                "No benchmark results yet. Generate them with:\n\n"
                "`python -m gemmabot.benchmark --dry`\n\n"
                "(dry mode uses fake models — no network, no API credits. Drop "
                "`--dry` to benchmark the real backends.)"
            )
            st.caption(
                "Results are written to benchmarks/results.md and "
                "benchmarks/results.json."
            )
