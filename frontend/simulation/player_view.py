"""Execution player — self-contained HTML/CSS/JS replay of a timeline.

Owner: FRONTEND.  Pure string building: no Streamlit import, no network.

``player_html()`` returns one complete HTML document that
``st.iframe`` renders into an iframe.  It is the only animation
runtime in the app: vanilla CSS + ~4 kB of plain JavaScript, no external
script, no CDN, no library.

It replays ``frontend.simulation.player.build_timeline()`` exactly as the
backend simulator produced it — the robot interpolates one cell per 300 ms
step, turns rotate smoothly, the trail is drawn in behind it and the active
step is highlighted in the step list.  Transport: play / pause / **step** /
reset and 0.5x / 1x / 2x / 4x playback speed.  Step advances the playhead to
the end of exactly one action and stops, which is one *verified* action: the
timeline is the guard's own approved execution, and stepping never asks the
simulator for anything new.

The stage is drawn at a fixed cell size (the geometry the animation
interpolates in), then scaled down by ``fit()`` when the frame it was given is
narrower than that — a console viewport is whatever width the operator's
window is, and the drawing must neither overflow nor be clipped.

``show_steps=False`` drops the built-in step list for the hosts that render
their own action timeline next to it (the Mission console does); the transport
and the live step readout stay either way.

Outcome row
-----------
Under the transport sits one fixed-height line stating what the run really did:
the goal reached, with the duration, the action count and where the robot
finished — or exactly why it stopped, in the simulator's own words.  Every
string is built in Python (:func:`outcome_copy`) from the timeline, so the
JavaScript chooses between verdicts it was handed and never composes one.

Provenance
----------
A timeline carries both an ``approved`` and a ``refused`` key, taken from the
guard's own result.  Only a verified execution says *executed*; a demonstrated
plan (the Safety Lab's preview of a refused plan) says *simulated*, and a
refused approval says nothing ran at all.  Nothing on screen may imply an
execution that did not happen.

Host timeline
-------------
``st.iframe`` is same-origin with the app, so when a host hands the player a
``timeline_scope`` the player marks *the action being shown right now* on that
host's own action timeline — ``.gb-tl[data-timeline=<scope>] .gb-tl-row`` gets
``data-live="true"`` while the playhead is on it, and the mark is cleared when
the playhead moves on and the moment the run finishes.

It writes that one attribute and nothing else: every row's state and verdict is
the console's, rendered from the backend, and at rest the timeline reads exactly
as the server drew it.  A host on another origin, or one that rendered no
timeline with that scope, is simply never marked — and the scope is also what
keeps two players on one page from marking each other's timelines.

Public surface
--------------
player_html(timeline, *, cell_px, autoplay, speed, show_steps, timeline_scope) -> str
player_height(cell_px) -> int      # iframe height that avoids scrolling
outcome_copy(timeline) -> dict     # the outcome row's words, all of them
"""
from __future__ import annotations

import html
import json

from gemmabot.config import SIZE
from frontend.components import animations as A
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.simulation import player
from frontend.simulation.ui_helpers import (
    GOAL_SVG,
    PATH_SVG,
    ROBOT_SVG,
    WALL_SVG,
)

# ── Layout constants (derived from the design-system scale) ──────────────────
CELL_GAP = 2                  # 1px border + 1px divider, like the hero grid
LABEL_W = S.CELL_LABEL_HERO   # row-label gutter
LABEL_H = 20                  # column-label band
HEAD_H = 30                   # header row
TRANSPORT_H = 30              # transport row
OUTCOME_H = 24                # the run's verdict, under the transport


def pitch(cell_px: int) -> int:
    """Distance in px between two neighbouring cell origins."""
    return int(cell_px) + CELL_GAP


def stage_px(cell_px: int) -> int:
    """Side length of the cell area (no axis labels)."""
    return (SIZE - 1) * pitch(cell_px) + int(cell_px)


def player_height(cell_px: int = S.CELL_SIZE) -> int:
    """Iframe height that shows the whole player without scrolling."""
    return (
        S.MD                       # top padding
        + HEAD_H
        + S.MD                     # header → body gap
        + LABEL_H + stage_px(cell_px) + S.XS
        + S.MD                     # body → transport gap
        + TRANSPORT_H
        + S.SM                     # transport → outcome gap
        + OUTCOME_H
        + S.MD                     # bottom padding
        + S.SM                     # safety
    )


# ── Markup builders ──────────────────────────────────────────────────────────

def _icon_svg(kind: str) -> str:
    if kind == "goal":
        return GOAL_SVG.format(fg=C.SUCCESS)
    if kind == "wall":
        return WALL_SVG.format(fg=C.TEXT_MUTED)
    return ""


def _cells_html(world: dict, cell_px: int) -> str:
    """One absolutely-positioned cell per grid coordinate."""
    walls = {tuple(int(v) for v in w) for w in world.get("walls", [])}
    goal = world.get("goal")
    goal_cell = tuple(int(v) for v in goal) if goal else None
    cs = int(cell_px)
    step = pitch(cs)
    parts: list[str] = []
    for y in range(SIZE):
        for x in range(SIZE):
            kind = "wall" if (x, y) in walls else ("goal" if (x, y) == goal_cell else "empty")
            inner = ""
            icon = _icon_svg(kind)
            if icon:
                inner += f"<span class='gb-pc-icon'>{icon}</span>"
            if kind == "empty":
                inner += (
                    "<span class='gb-pc-dot'>"
                    + PATH_SVG.format(fg=C.RUNNING)
                    + "</span>"
                )
            parts.append(
                f"<div class='gb-pc gb-pc-{kind}' id='pc-{x}-{y}' "
                f"data-x='{x}' data-y='{y}' "
                f"style='left:{x * step}px;top:{y * step}px;"
                f"width:{cs}px;height:{cs}px'>{inner}</div>"
            )
    return "".join(parts)


def _col_labels_html(cell_px: int) -> str:
    """Column numbers, one per column.

    Every label is as wide as the pitch except the last, which is only a cell
    wide: that makes the band exactly ``stage_px()`` across, so the numbers sit
    over their own columns and the frame height the caller computed still
    matches what the browser lays out.
    """
    cs = int(cell_px)
    step = pitch(cs)
    return "".join(
        f"<div class='gb-axis col' "
        f"style='width:{cs if x == SIZE - 1 else step}px;height:{LABEL_H}px'>"
        f"{x}</div>"
        for x in range(SIZE)
    )


def _row_labels_html(cell_px: int) -> str:
    """Row numbers, sized like the columns so the stack never grows past the
    stage it labels."""
    cs = int(cell_px)
    step = pitch(cs)
    return "".join(
        f"<div class='gb-axis row' "
        f"style='width:{LABEL_W}px;height:{cs if y == SIZE - 1 else step}px'>"
        f"{y}</div>"
        for y in range(SIZE)
    )


def _steps_html(steps: list[dict]) -> str:
    """One row per action; the player highlights the active one."""
    if not steps:
        return (
            "<div class='gb-step gb-step-empty'>"
            "<span class='gb-step-body'>no actions to execute</span></div>"
        )
    rows: list[str] = []
    for step in steps:
        halted = bool(step.get("halted"))
        dot = "gb-step-dot err" if halted else "gb-step-dot"
        rows.append(
            f"<div class='gb-step' data-step='{int(step['index'])}'>"
            f"<span class='{dot}'></span>"
            f"<span class='gb-step-idx'>{int(step['index']):02d}</span>"
            f"<span class='gb-step-body'>"
            f"<span class='gb-step-label'>{html.escape(str(step.get('label', '')))}</span>"
            f"<span class='gb-step-msg'>{html.escape(str(step.get('message', '')))}</span>"
            f"</span></div>"
        )
    return "".join(rows)


def _speed_buttons_html(speed: float) -> str:
    buttons: list[str] = []
    for option in A.SPEED_OPTIONS:
        on = " on" if abs(float(option) - float(speed)) < 1e-9 else ""
        active = "true" if on else "false"
        label = f"{option:g}×"
        buttons.append(
            f"<button type='button' class='gb-speed-btn{on}' data-speed='{option:g}' "
            f"aria-pressed='{active}' title='Playback speed {label}'>{label}</button>"
        )
    return "".join(buttons)


def _robot_html(cell_px: int) -> str:
    cs = int(cell_px)
    arrow = ROBOT_SVG["E"].format(fg=C.ACCENT_BLUE, stroke=C.ACCENT_BLUE_DIM)
    return (
        f"<div class='gb-robot' id='gb-robot' style='width:{cs}px;height:{cs}px'>"
        f"<div class='gb-robot-rotor' id='gb-rotor'>{arrow}</div></div>"
    )


# ── Outcome wording ─────────────────────────────────────────────────────────

# How each playback kind introduces itself: (heading, the action word its Step
# button may use, what its Play button replays).  A preview demonstrates an
# unapproved plan, a replay re-runs a logged one and an execution is the guard's
# own verified run — three different things, and the reader is told which.
_KIND_WORDS: dict[str, tuple[str, str, str]] = {
    player.KIND_EXECUTION: (
        "Execution playback",
        "verified action",
        "the recorded execution",
    ),
    player.KIND_REPLAY: (
        "Run replay",
        "action of this replay",
        "the logged plan again",
    ),
    player.KIND_PREVIEW: (
        "Simulation preview",
        "action of this preview",
        "this preview of an unverified plan",
    ),
}


def kind_words(timeline: dict) -> tuple[str, str, str]:
    """The heading and button words for a timeline's playback kind."""
    return _KIND_WORDS[player.kind_of(timeline)]


def _seconds(ms: int | float) -> str:
    """A timeline length as the console prints it: ``5.70 s``."""
    return f"{max(0.0, float(ms)) / 1000:.2f} s"


def _cell_text(coord) -> str:
    """A cell as the rest of the console prints it: ``(6, 5)``."""
    pair = list(coord or [])
    x = int(pair[0]) if len(pair) > 0 else 0
    y = int(pair[1]) if len(pair) > 1 else 0
    return f"({x}, {y})"


def _count(number: int, word: str) -> str:
    """``1 action`` / ``3 actions``."""
    return f"{number} {word}" if number == 1 else f"{number} {word}s"


def outcome_copy(timeline: dict) -> dict:
    """The words the outcome row shows — all of them, written in one place.

    Returns ``state`` (how the row is coloured: ``refused`` / ``halted`` /
    ``reached`` / ``short`` / ``none``), ``ready`` (nothing played yet) and
    ``terminal`` (the run finished).  The player's JavaScript picks between the
    two lines and never composes a verdict of its own.

    Provenance decides the verb.  A guard-verified execution says *executed*;
    a demonstrated plan says *simulated*; a refused approval says outright that
    no action ran, because none did — the simulator breaks at the first
    refusal and every action after it is still pending.
    """
    steps = timeline.get("steps") or []
    planned = int(timeline.get("planned") or len(steps))
    run = int(timeline.get("actions_run") or 0)
    approved = bool(timeline.get("approved"))
    refused = str(timeline.get("refused") or "")
    kind = player.kind_of(timeline)
    verb = "executed" if approved else "simulated"
    took = f"{_seconds(timeline.get('duration_ms') or 0)} at 1×"
    where = (
        f"final {_cell_text(timeline.get('final'))} "
        f"facing {timeline.get('final_dir') or 'E'}"
    )

    # The execution gate refused the approval: nothing stepped, nothing ran.
    if refused:
        text = (
            f"Refused — {refused} · no action ran · the robot never left "
            f"{_cell_text(timeline.get('final'))}"
        )
        return {"state": "refused", "ready": text, "terminal": text}

    if not steps:
        text = "no actions — nothing to play back"
        return {"state": "none", "ready": text, "terminal": text}

    if approved:
        ready = f"verified plan · {_count(planned, 'action')} · {took} · press Play or Step"
    elif kind == player.KIND_REPLAY:
        # A logged plan says nothing about approval, so this line must not claim
        # anything about it — only what the replay is.
        ready = (
            f"replay of a logged run · {_count(planned, 'action')} · the recorded "
            f"plan run through the simulator again, not the original session"
        )
    else:
        ready = (
            f"unverified preview · {_count(planned, 'action')} · the guard did not "
            f"approve this plan, so nothing was executed"
        )

    halted = timeline.get("halted")
    if halted:
        what = (
            f"action {int(timeline.get('halted_step') or 0):02d} "
            f"{timeline.get('halted_label') or ''}"
        ).strip()
        missed = int(timeline.get("unexecuted") or 0)
        # "never reached" rather than "never executed": the simulator stopped,
        # so those actions were neither executed nor simulated, and the line
        # should not say which of the two it was.
        tail = f" · {_count(missed, 'action')} never reached" if missed else ""
        return {
            "state": "halted",
            "ready": ready,
            "terminal": (
                f"Stopped ({halted}) · {what} · "
                f"{timeline.get('halted_message') or 'the simulator refused it'} · "
                f"{run} of {planned} {verb} · stopped on "
                f"{_cell_text(timeline.get('halted_at'))}{tail}"
            ),
        }

    if timeline.get("reached"):
        return {
            "state": "reached",
            "ready": ready,
            "terminal": f"Goal reached · {run} of {planned} {verb} · {took} · {where}",
        }

    return {
        "state": "short",
        "ready": ready,
        "terminal": (
            f"Finished short of the goal · {run} of {planned} {verb} · {took} · {where}"
        ),
    }


def _outcome_html(copy: dict, *, autoplay: bool) -> str:
    """The outcome row, already filled in for the state the player boots in.

    A fresh run starts at the beginning, so the row shows the plan line; a run
    opened without autoplay boots on its finished frame, so the row shows the
    verdict.  The runtime corrects either one on its first render.
    """
    state = str(copy.get("state") or "none")
    playing_from_start = bool(autoplay) and state != "none"
    text = str(copy.get("ready") if playing_from_start else copy.get("terminal") or "")
    look = "ready" if playing_from_start else state
    return (
        f"<div class='gb-outcome' id='gb-outcome' data-state='{html.escape(look, quote=True)}' "
        f"role='status' aria-live='polite' title='{html.escape(text, quote=True)}'>"
        f"{html.escape(text)}</div>"
    )


# ── Stylesheet ───────────────────────────────────────────────────────────────

def _css(cell_px: int) -> str:
    """Player CSS, scoped to the iframe and built from design tokens."""
    cs = int(cell_px)
    step = pitch(cs)
    return f"""
<style>
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0; padding: 0; background: {C.BG_BASE}; color: {C.TEXT_PRIMARY};
  font-family: {T.FONT_SANS}; font-size: {T.SIZE_BASE}px; line-height: {T.LEADING_BASE};
}}
{A.ALL_KEYFRAMES}
.gb-exec {{ padding: {S.px(S.MD)}; }}

/* ── Header ───────────────────────────────────────────────────────────── */
/* The head row never wraps (its height is fixed and the frame height is
   computed from it), so every text item must be able to give width back: the
   rule collapses, the words ellipsise and the state chip keeps its box.  A
   narrow host column therefore truncates instead of overflowing the frame. */
.gb-head {{
  display: flex; align-items: center; gap: {S.px(S.SM)};
  height: {HEAD_H}px; margin-bottom: {S.px(S.MD)};
  font-family: {T.FONT_MONO}; overflow: hidden;
}}
.gb-head > * {{ min-width: 0; }}
.gb-head-title {{
  font-size: {T.SIZE_SM}px; color: {C.TEXT_MUTED}; letter-spacing: {T.TRACKING_WIDE};
  text-transform: uppercase; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.gb-rule {{ flex: 1 1 0; height: 1px; background: {C.BORDER_SUBTLE}; }}
.gb-stepnow {{
  font-size: {T.SIZE_SM}px; color: {C.TEXT_SECONDARY};
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.gb-readout {{
  font-size: {T.SIZE_SM}px; color: {C.ACCENT_BLUE};
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.gb-chip {{
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_SM}px; letter-spacing: {T.TRACKING_WIDE};
  padding: 2px {S.px(S.SM)}; border-radius: {S.RADIUS_SM}px; white-space: nowrap;
  flex: 0 0 auto;
  border: 1px solid {C.BORDER_DEFAULT}; background: {C.BG_ELEVATED}; color: {C.TEXT_SECONDARY};
}}
.gb-chip.ok {{ background: {C.SUCCESS_BG}; border-color: {C.SUCCESS_BORDER}; color: {C.SUCCESS}; }}
.gb-chip.err {{ background: {C.ERROR_BG}; border-color: {C.ERROR_BORDER}; color: {C.ERROR}; }}
.gb-chip.warn {{ background: {C.WARNING_BG}; border-color: {C.WARNING_BORDER}; color: {C.WARNING}; }}
.gb-chip.run {{
  background: {C.RUNNING_BG}; border-color: {C.RUNNING_BORDER}; color: {C.RUNNING};
  animation: gb-pulse 1.8s {A.EASE_INOUT} infinite;
}}

/* ── Body: grid stage + step list ───────────────────────────────────────
   One row, always.  The stage keeps its width (its geometry is what the
   animation interpolates, and fit() scales it), and the step rail is the item
   that gives width back — so the frame height the caller computed is the height
   the browser lays out, at any host width.  Wrapping the rail under the stage
   would make the document grow by a step-dependent amount nobody can predict. */
.gb-body {{
  display: flex; flex-wrap: nowrap; align-items: flex-start;
  gap: {S.px(S.LG)};
}}
.gb-stage-wrap {{ display: flex; flex-direction: column; flex: 0 0 auto; }}
/* Compact: the host draws its own action timeline, so the stage is centred in
   whatever width the frame gives it. */
.gb-exec-compact .gb-stage-wrap {{ margin: 0 auto; }}
.gb-colrow {{ display: flex; margin-left: {LABEL_W}px; }}
.gb-rowwrap {{ display: flex; }}
.gb-rows {{ display: flex; flex-direction: column; }}
.gb-axis {{
  display: flex; align-items: center; justify-content: center;
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_XS}px; color: {C.GRID_LABEL};
  letter-spacing: 0.04em;
}}
.gb-stage {{ position: relative; }}

/* ── Cells ────────────────────────────────────────────────────────────── */
.gb-pc {{
  position: absolute; display: flex; align-items: center; justify-content: center;
  border: 1px solid {C.GRID_BORDER}; border-radius: {S.RADIUS_SM}px;
  background: {C.GRID_EMPTY};
  transition: background 200ms {A.EASE_OUT}, border-color 200ms {A.EASE_OUT},
              box-shadow 200ms {A.EASE_OUT};
}}
.gb-pc-wall {{
  background: {C.GRID_WALL}; border-color: {C.GRID_WALL_EDGE};
  box-shadow: inset 0 1px 0 {C.GRID_WALL_SURFACE}60, inset 0 -1px 0 {C.GRID_WALL_EDGE};
}}
.gb-pc-goal {{
  background: {C.GRID_GOAL}; border-color: {C.SUCCESS_BORDER};
  animation: gb-goal-glow 2.8s {A.EASE_INOUT} infinite;
}}
.gb-pc-icon {{ display: flex; width: 52%; height: 52%; }}
.gb-pc-dot {{ display: flex; width: 26%; height: 26%; opacity: 0; transition: opacity 220ms {A.EASE_OUT}; }}
.gb-pc-dot svg, .gb-pc-icon svg {{ width: 100%; height: 100%; }}
.gb-pc-trail {{ background: {C.GRID_PATH}; border-color: {C.GRID_PATH_BORDER}; }}
.gb-pc-trail .gb-pc-dot {{ opacity: 1; }}
.gb-pc-target {{
  border-color: {C.GRID_CURRENT_BORDER};
  box-shadow: inset 0 0 0 1px {C.GRID_CURRENT_BORDER}, 0 0 10px {C.GRID_CURRENT_GLOW}33;
}}
.gb-pc-halt {{
  border-color: {C.ERROR_BORDER};
  box-shadow: inset 0 0 0 1px {C.ERROR_BORDER};
}}

/* ── Robot + path trace ───────────────────────────────────────────────── */
.gb-trace {{ position: absolute; left: 0; top: 0; z-index: 2; overflow: visible; pointer-events: none; }}
.gb-trace line {{ stroke: {C.RUNNING}; stroke-width: 1.5; stroke-linecap: round; opacity: 0.32; }}
.gb-trace line.seg {{
  stroke-dasharray: var(--gb-trace-len, 42px);
  stroke-dashoffset: var(--gb-trace-len, 42px);
  animation-name: gb-trace-draw; animation-timing-function: linear;
  animation-fill-mode: forwards;
}}
.gb-robot {{
  position: absolute; left: 0; top: 0; z-index: 3;
  display: flex; align-items: center; justify-content: center;
  border: 1px solid {C.GRID_CURRENT_BORDER}; border-radius: {S.RADIUS_SM}px;
  background: {C.GRID_ROBOT};
  box-shadow: 0 0 0 1.5px {C.GRID_ROBOT_GLOW}40, inset 0 0 8px {C.GRID_ROBOT_GLOW}26;
  will-change: transform;
}}
.gb-robot-rotor {{ display: flex; align-items: center; justify-content: center; width: 100%; height: 100%; }}
.gb-robot-rotor svg {{ width: 52%; height: 52%; }}

/* ── Step list ────────────────────────────────────────────────────────── */
.gb-steps {{
  display: flex; flex-direction: column; flex: 1 1 232px; min-width: 0;
  max-width: 232px;
  max-height: {stage_px(cs)}px; overflow-y: auto;
  border: 1px solid {C.BORDER_SUBTLE}; border-radius: {S.RADIUS_MD}px;
  background: {C.BG_SURFACE};
}}
.gb-step {{
  display: flex; align-items: baseline; gap: {S.px(S.SM)};
  padding: {S.px(S.XS)} {S.px(S.MD)}; border-bottom: 1px solid {C.BORDER_SUBTLE};
  border-left: 2px solid transparent;
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_SM}px; color: {C.TEXT_SECONDARY};
  transition: background 150ms {A.EASE_OUT}, color 150ms {A.EASE_OUT},
              border-color 150ms {A.EASE_OUT};
}}
.gb-step:last-child {{ border-bottom: none; }}
.gb-step.active {{ background: {C.RUNNING_BG}; border-left-color: {C.ACCENT_BLUE}; color: {C.TEXT_PRIMARY}; }}
.gb-step.done {{ color: {C.TEXT_MUTED}; }}
.gb-step.halted {{ border-left-color: {C.ERROR}; }}
.gb-step-empty {{ color: {C.TEXT_MUTED}; border-left-color: transparent; }}
.gb-step-dot {{ width: 6px; height: 6px; border-radius: 50%; background: {C.BORDER_STRONG}; flex-shrink: 0; }}
.gb-step-dot.err {{ background: {C.ERROR}; }}
.gb-step.done .gb-step-dot {{ background: {C.SUCCESS}; }}
.gb-step.halted .gb-step-dot {{ background: {C.ERROR}; }}
.gb-step.active .gb-step-dot {{ background: {C.ACCENT_BLUE}; animation: gb-pulse 1.6s {A.EASE_INOUT} infinite; }}
.gb-step-idx {{ color: {C.TEXT_MUTED}; flex-shrink: 0; }}
.gb-step-body {{ display: flex; flex-direction: column; gap: 1px; min-width: 0; }}
.gb-step-label {{ color: inherit; white-space: nowrap; }}
.gb-step-msg {{
  color: {C.TEXT_MUTED}; font-size: {T.SIZE_XS}px;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}

/* ── Transport ──────────────────────────────────────────────────────────
   One row: play/pause, step, reset, the speed group, the progress bar and the
   clock.  The bar is the only stretchy item, so the row gives width back by
   shortening the bar rather than by pushing the clock out of the frame; wrap
   is the last resort for a host too narrow for even that. */
.gb-transport {{
  display: flex; flex-wrap: nowrap; align-items: center;
  gap: {S.px(S.SM)}; margin-top: {S.px(S.MD)};
}}
/* Dense by design: the transport is three controls, a speed group and a bar, and
   it has to fit the narrowest console column (~360px) on one row.  nowrap keeps
   every control at its natural width, so the row height is the same at every
   host width and the frame height the caller computed stays correct. */
.gb-btn {{
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_SM}px; letter-spacing: {T.TRACKING_WIDE};
  padding: 5px {S.px(S.SM)}; border-radius: {S.RADIUS_SM}px;
  border: 1px solid {C.BORDER_DEFAULT}; background: {C.BG_ELEVATED}; color: {C.TEXT_PRIMARY};
  cursor: pointer; white-space: nowrap;
  transition: background 150ms {A.EASE_OUT}, border-color 150ms {A.EASE_OUT};
}}
.gb-btn:hover {{ background: {C.BG_OVERLAY}; border-color: {C.BORDER_STRONG}; }}
.gb-btn:focus-visible {{ outline: 2px solid {C.ACCENT_BLUE}; outline-offset: 2px; }}
.gb-btn-primary {{ background: {C.ACCENT_BLUE}; border-color: {C.ACCENT_BLUE}; color: {C.BG_BASE}; font-weight: {T.WEIGHT_SEMIBOLD}; }}
.gb-btn:disabled {{
  background: {C.BG_SURFACE}; border-color: {C.BORDER_SUBTLE}; color: {C.TEXT_MUTED};
  cursor: not-allowed;
}}
.gb-speed {{ display: flex; border: 1px solid {C.BORDER_DEFAULT}; border-radius: {S.RADIUS_SM}px; overflow: hidden; }}
.gb-speed-btn {{
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_SM}px; padding: 5px {S.px(S.XS)};
  border: none; border-right: 1px solid {C.BORDER_SUBTLE}; background: transparent;
  color: {C.TEXT_MUTED}; cursor: pointer; white-space: nowrap;
  transition: background 150ms {A.EASE_OUT}, color 150ms {A.EASE_OUT};
}}
.gb-speed-btn:last-child {{ border-right: none; }}
.gb-speed-btn:hover {{ background: {C.BG_OVERLAY}; color: {C.TEXT_PRIMARY}; }}
.gb-speed-btn.on {{ background: {C.ACCENT_BLUE}; color: {C.BG_BASE}; font-weight: {T.WEIGHT_SEMIBOLD}; }}
.gb-progress {{
  flex: 1 1 0; height: 3px; min-width: 0; background: {C.BG_OVERLAY};
  border-radius: 2px; overflow: hidden;
}}
.gb-progress span {{ display: block; height: 100%; width: 0; background: {C.ACCENT_BLUE}; transition: width 100ms linear; }}
.gb-speed-btn:focus-visible {{
  outline: 2px solid {C.ACCENT_BLUE}; outline-offset: 2px;
}}

/* ── Outcome ────────────────────────────────────────────────────────────
   Fixed height, one line: the verdict the timeline itself carries.  Green
   only for a verified run that reached the goal; red carries the reason it
   stopped; a preview keeps the neutral border so it never reads as an
   execution.  The full sentence lives in the title, because the line
   ellipsises in a narrow frame. */
.gb-outcome {{
  display: block; height: {OUTCOME_H}px; line-height: {OUTCOME_H - 2}px;
  margin-top: {S.px(S.SM)}; padding: 0 {S.px(S.SM)};
  border: 1px solid transparent; border-radius: {S.RADIUS_SM}px;
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_XS}px; color: {C.TEXT_MUTED};
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.gb-outcome[data-state='paused'] {{ border-color: {C.BORDER_DEFAULT}; color: {C.TEXT_SECONDARY}; }}
.gb-outcome[data-state='running'] {{ border-color: {C.RUNNING_BORDER}; color: {C.TEXT_SECONDARY}; }}
.gb-outcome[data-state='reached'] {{
  background: {C.SUCCESS_BG}; border-color: {C.SUCCESS_BORDER}; color: {C.SUCCESS};
}}
.gb-outcome[data-state='short'] {{
  background: {C.WARNING_BG}; border-color: {C.WARNING_BORDER}; color: {C.WARNING};
}}
.gb-outcome[data-state='halted'],
.gb-outcome[data-state='refused'] {{
  background: {C.ERROR_BG}; border-color: {C.ERROR_BORDER}; color: {C.ERROR};
}}
/* The player lives in its own document, so it repeats the app's reduced-motion
   rule for its own transitions.  The script checks the same media query before
   it autoplays, so nothing moves the robot either. */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }}
}}
</style>
"""


# ── Player runtime ───────────────────────────────────────────────────────────
#
# Plain JavaScript, no dependencies.  It only interpolates the timeline the
# Python side already produced; it never re-simulates and never invents an
# outcome.  All dynamic text is written with textContent — model-supplied
# action labels stay inert.

_JS = r"""
(function () {
  'use strict';
  var TL = window.__TL__;
  var ANGLE = { N: 270, E: 0, S: 90, W: 180 };
  var CELL = TL.cell_px;
  var PITCH = TL.pitch;
  var stage = document.getElementById('gb-stage');
  var robotEl = document.getElementById('gb-robot');
  var rotorEl = document.getElementById('gb-rotor');
  var traceEl = document.getElementById('gb-trace');
  var barEl = document.getElementById('gb-bar');
  var chipEl = document.getElementById('gb-chip');
  var stepNowEl = document.getElementById('gb-stepnow');
  var readoutEl = document.getElementById('gb-readout');
  var playBtn = document.getElementById('gb-play');
  var stepBtn = document.getElementById('gb-step');
  var outEl = document.getElementById('gb-outcome');
  var resetBtn = document.getElementById('gb-reset');
  var stepEls = Array.prototype.slice.call(document.querySelectorAll('.gb-step'));
  var speedBtns = Array.prototype.slice.call(document.querySelectorAll('.gb-speed-btn'));

  var speed = TL.speed;
  var playing = false;
  var t = 0;                // playhead in 1x timeline ms
  var doneCursor = 0;       // events already applied to the DOM
  var enteredCursor = 0;    // events whose beat has started
  var targetCoord = null;
  var lastActive = 0;
  var lastPosted = 'unset'; // sentinel: forces the first sync to clear the host
  var lastTs = 0;
  var frameId = 0;
  var reduced = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

  // ── Geometry ──────────────────────────────────────────────────────────
  function cellEl(x, y) { return document.getElementById('pc-' + x + '-' + y); }
  function centerOf(coord) { return [coord[0] * PITCH + CELL / 2, coord[1] * PITCH + CELL / 2]; }
  function clamp01(x) { return x < 0 ? 0 : (x > 1 ? 1 : x); }
  function easeMove(p) { return 0.5 - 0.5 * Math.cos(Math.PI * p); }
  function easeTurn(p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function seconds(ms) { return (ms / 1000).toFixed(2) + ' s'; }
  function dirOf(deg) {
    var d = ((deg % 360) + 360) % 360;
    if (d < 45 || d >= 315) { return 'E'; }
    if (d < 135) { return 'S'; }
    if (d < 225) { return 'W'; }
    return 'N';
  }

  // ── Interpolation: where is the robot at timeline time ms? ────────────
  function stateAt(ms) {
    var origin = centerOf(TL.start);
    var x = origin[0], y = origin[1];
    var angle = ANGLE[TL.start_dir] || 0;
    for (var i = 0; i < TL.events.length; i++) {
      var ev = TL.events[i];
      if (ms <= ev.start) { break; }
      if (ms >= ev.start + ev.ms) {
        if (ev.type === 'move') {
          var done = centerOf(ev.to);
          x = done[0]; y = done[1]; angle = ANGLE[ev.dir] || 0;
        } else if (ev.type === 'turn') {
          angle = ANGLE[ev.to_dir] || 0;
        }
        continue;
      }
      var p = clamp01((ms - ev.start) / ev.ms);
      if (ev.type === 'move') {
        var a = centerOf(ev.from), b = centerOf(ev.to), e = easeMove(p);
        x = a[0] + (b[0] - a[0]) * e;
        y = a[1] + (b[1] - a[1]) * e;
        angle = ANGLE[ev.dir] || 0;
      } else if (ev.type === 'turn') {
        var from = ANGLE[ev.from_dir] || 0;
        var to = ANGLE[ev.to_dir] || 0;
        var delta = ((to - from + 540) % 360) - 180;
        angle = from + delta * easeTurn(p);
      }
      return { x: x, y: y, angle: angle, index: i };
    }
    return { x: x, y: y, angle: angle, index: -1 };
  }

  // ── DOM state: trail, trace, step highlight ───────────────────────────
  function resetDynamic() {
    var marked = document.querySelectorAll('.gb-pc-trail, .gb-pc-target, .gb-pc-halt');
    for (var i = 0; i < marked.length; i++) {
      marked[i].classList.remove('gb-pc-trail', 'gb-pc-target', 'gb-pc-halt');
    }
    while (traceEl && traceEl.firstChild) { traceEl.removeChild(traceEl.firstChild); }
    for (var s = 0; s < stepEls.length; s++) {
      stepEls[s].classList.remove('done', 'active');
    }
    doneCursor = 0; enteredCursor = 0; targetCoord = null; lastActive = 0;
    lastPosted = 'unset';
  }

  function markTrail(coord) {
    var el = cellEl(coord[0], coord[1]);
    if (el) { el.classList.add('gb-pc-trail'); }
  }

  function markHalt(coord) {
    var el = cellEl(coord[0], coord[1]);
    if (el) { el.classList.add('gb-pc-halt'); }
  }

  function addTrace(from, to) {
    if (!traceEl) { return; }
    var a = centerOf(from), b = centerOf(to);
    var line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', a[0]);
    line.setAttribute('y1', a[1]);
    line.setAttribute('x2', b[0]);
    line.setAttribute('y2', b[1]);
    line.setAttribute('class', 'seg');
    line.style.animationDuration = Math.max(40, TL.trace_draw_ms / speed) + 'ms';
    traceEl.appendChild(line);
  }

  function setTarget(coord) {
    var nextKey = coord ? coord[0] + ',' + coord[1] : null;
    var currentKey = targetCoord ? targetCoord[0] + ',' + targetCoord[1] : null;
    if (nextKey === currentKey) { return; }
    if (targetCoord) {
      var old = cellEl(targetCoord[0], targetCoord[1]);
      if (old) { old.classList.remove('gb-pc-target'); }
    }
    targetCoord = coord ? [coord[0], coord[1]] : null;
    if (targetCoord) {
      var el = cellEl(targetCoord[0], targetCoord[1]);
      if (el) { el.classList.add('gb-pc-target'); }
    }
  }

  function applyStatic(ms) {
    while (doneCursor < TL.events.length &&
           TL.events[doneCursor].start + TL.events[doneCursor].ms <= ms) {
      var ev = TL.events[doneCursor];
      if (ev.type === 'move') {
        markTrail(ev.from);
        addTrace(ev.from, ev.to);
      }
      doneCursor += 1;
    }
    while (enteredCursor < TL.events.length && TL.events[enteredCursor].start < ms) {
      var started = TL.events[enteredCursor];
      if (started.type === 'hold' && started.halted) { markHalt(started.at); }
      enteredCursor += 1;
    }
  }

  function syncSteps(ms) {
    var active = -1;
    for (var i = 0; i < TL.steps.length; i++) {
      var spec = TL.steps[i], el = stepEls[i];
      if (!el) { continue; }
      var done = ms >= spec.end_ms;
      var isActive = !done && ms >= spec.start_ms;
      el.classList.toggle('done', done);
      el.classList.toggle('active', isActive);
      if (isActive) { active = spec.index; }
    }
    if (active !== lastActive && active > 0 && stepEls[active - 1]) {
      lastActive = active;
      if (stepEls[active - 1].scrollIntoView) {
        stepEls[active - 1].scrollIntoView({ block: 'nearest' });
      }
    }
    lastActive = active;
    return active;
  }

  // The action the player is *showing*: the last one that has begun.  The step
  // list already calls an action done the moment its end is reached, so the
  // readouts need their own rule — at an exact step boundary nothing is active,
  // and a step would otherwise announce the action before the one it stepped
  // to.  Every readout and the host mark go through this one function.
  function shownStep(ms) {
    var at = 0;
    for (var i = 0; i < TL.steps.length; i++) {
      if (TL.steps[i].start_ms <= ms + 0.5) { at = i + 1; }
    }
    return at;
  }

  function syncChrome(ms, st) {
    var finished = TL.duration_ms > 0 && ms >= TL.duration_ms;
    var shown = shownStep(ms);
    var chip = 'READY', cls = 'gb-chip';
    if (finished) {
      if (TL.reached) { chip = 'GOAL REACHED'; cls = 'gb-chip ok'; }
      else if (TL.halted === 'blocked') { chip = 'BLOCKED'; cls = 'gb-chip err'; }
      else if (TL.halted) { chip = 'FAILED'; cls = 'gb-chip err'; }
      else { chip = 'EXECUTED'; cls = 'gb-chip warn'; }
    } else if (playing) { chip = 'RUNNING'; cls = 'gb-chip run'; }
    else if (t > 0 && TL.duration_ms > 0) { chip = 'PAUSED'; }
    else { chip = 'READY'; }
    if (chipEl) { chipEl.textContent = chip; chipEl.className = cls; }

    var label;
    if (finished) {
      label = TL.steps.length + ' steps · ' + TL.cells + ' cells';
    } else if (shown > 0 && TL.steps[shown - 1]) {
      label = pad(shown) + '/' + pad(TL.steps.length) + ' · ' + TL.steps[shown - 1].label;
    } else if (TL.steps.length) {
      label = pad(1) + '/' + pad(TL.steps.length) + ' · ' + TL.steps[0].label;
    } else {
      label = 'no actions';
    }
    if (stepNowEl) { stepNowEl.textContent = label; }
    if (readoutEl) {
      var cx = Math.round((st.x - CELL / 2) / PITCH);
      var cy = Math.round((st.y - CELL / 2) / PITCH);
      readoutEl.textContent = '(' + cx + ',' + cy + ') ' + dirOf(st.angle);
    }
    if (barEl) {
      barEl.style.width = (TL.duration_ms > 0 ? (Math.min(ms, TL.duration_ms) / TL.duration_ms) * 100 : 100) + '%';
      // The bar's own tooltip is the clock: how far the playhead has come of the
      // run's length.  A separate readout cost ~44px the narrowest console
      // column does not have, and the outcome line states the duration anyway.
      barEl.parentNode.setAttribute('title', seconds(Math.min(ms, TL.duration_ms)) +
        ' of ' + seconds(TL.duration_ms) + ' at 1×');
    }
  }

  function render() {
    var st = stateAt(t);
    applyStatic(t);
    syncSteps(t);
    var index = st.index;
    if (index >= 0 && TL.events[index] && TL.events[index].type === 'move') {
      setTarget(TL.events[index].to);
    } else {
      setTarget(null);
    }
    if (robotEl) {
      robotEl.style.transform = 'translate(' + (st.x - CELL / 2) + 'px,' + (st.y - CELL / 2) + 'px)';
    }
    if (rotorEl) { rotorEl.style.transform = 'rotate(' + st.angle + 'deg)'; }
    syncChrome(t, st);
    syncOutcome();
    syncStepBtn();
    syncHost();
  }

  // ── Outcome: the run's own verdict ────────────────────────────────────
  // Every sentence comes from TL.copy, which Python built out of the timeline.
  // This function only chooses between them, so the animation can never
  // announce a result the execution did not produce.
  function syncOutcome() {
    if (!outEl) { return; }
    var finished = TL.duration_ms > 0 && t >= TL.duration_ms;
    var state = 'ready';
    var text = TL.copy.ready;
    if (TL.duration_ms <= 0 || finished) {
      state = TL.copy.state;
      text = TL.copy.terminal;
    } else if (t > 0) {
      var index = shownStep(t);
      if (index <= 0) { index = 1; }
      var spec = TL.steps[index - 1];
      var at = 'action ' + pad(index) + '/' + pad(TL.steps.length) +
        (spec ? ' \u00b7 ' + spec.label : '');
      state = playing ? 'running' : 'paused';
      text = playing ? ((TL.approved ? 'Executing ' : 'Simulating ') + at)
                     : ('Paused at ' + at);
    }
    if (outEl.textContent !== text) { outEl.textContent = text; }
    if (outEl.getAttribute('data-state') !== state) { outEl.setAttribute('data-state', state); }
    if (outEl.getAttribute('title') !== text) { outEl.setAttribute('title', text); }
  }

  function syncStepBtn() {
    if (!stepBtn) { return; }
    var off = !(TL.duration_ms > 0 && TL.steps.length > 0);
    if (stepBtn.disabled !== off) { stepBtn.disabled = off; }
  }

  // ── Step: exactly one action, then stop ───────────────────────────────
  // The playhead moves to the end of the next action of the plan the guard
  // re-verified before the simulator stepped it, so a step can never show an
  // unverified action.  It only moves the playhead; nothing is stepped again.
  function nextStepEnd(ms) {
    for (var i = 0; i < TL.steps.length; i++) {
      if (TL.steps[i].end_ms > ms + 0.5) { return TL.steps[i].end_ms; }
    }
    return -1;
  }

  function stepOnce() {
    if (TL.duration_ms <= 0 || !TL.steps.length) { return; }
    pause();
    var end = nextStepEnd(t);
    if (end < 0) {                     // past the last action: replay it again
      t = 0;
      resetDynamic();
      end = nextStepEnd(0);
    }
    if (end < 0) { return; }
    t = Math.min(TL.duration_ms, end);
    render();
    syncPlayLabel();
  }

  // ── Host timeline ─────────────────────────────────────────────────────
  // The player is a same-origin iframe, so when the host named a timeline to
  // follow it can mark the action being shown right now on that timeline's own
  // rows.  One attribute, set and cleared: the rows' state and verdict belong
  // to the host, and are never written from here.  A host that named nothing,
  // or sits on another origin, is simply never marked.
  function hostRows() {
    if (!TL.timeline_scope || window.parent === window) { return []; }
    try {
      return window.parent.document.querySelectorAll(
        '.gb-tl[data-timeline="' + TL.timeline_scope + '"] .gb-tl-row[data-action]'
      );
    } catch (err) {
      return [];   // not same-origin with the host: nothing to mark
    }
  }

  function markHost(action) {
    var found = hostRows();
    for (var i = 0; i < found.length; i++) {
      if (action > 0 && parseInt(found[i].getAttribute('data-action'), 10) === action) {
        found[i].setAttribute('data-live', 'true');
      } else {
        found[i].removeAttribute('data-live');
      }
    }
  }

  function syncHost() {
    var finished = TL.duration_ms > 0 && t >= TL.duration_ms;
    var shown = finished ? 0 : shownStep(t);
    if (shown === lastPosted) { return; }
    lastPosted = shown;
    markHost(shown);
  }

  // ── Playback loop ─────────────────────────────────────────────────────
  function syncPlayLabel() {
    if (!playBtn) { return; }
    if (playing) { playBtn.textContent = '⏸ Pause'; }
    else if (TL.duration_ms > 0 && t >= TL.duration_ms) { playBtn.textContent = '▶ Replay'; }
    else { playBtn.textContent = '▶ Play'; }
  }

  function stopFrames() {
    if (frameId) { window.cancelAnimationFrame(frameId); frameId = 0; }
    lastTs = 0;
  }

  function frame(ts) {
    frameId = 0;
    if (!playing) { return; }
    if (!lastTs) { lastTs = ts; }
    var dt = Math.min(120, ts - lastTs);   // clamp after tab switches
    lastTs = ts;
    t = Math.min(TL.duration_ms, t + dt * speed);
    render();
    if (t >= TL.duration_ms) {
      playing = false;
      syncPlayLabel();
      return;
    }
    frameId = window.requestAnimationFrame(frame);
  }

  function play() {
    if (TL.duration_ms <= 0 || playing) { return; }
    if (t >= TL.duration_ms) { t = 0; resetDynamic(); }   // replay from the start
    playing = true;
    lastTs = 0;
    render();
    syncPlayLabel();
    if (!frameId) { frameId = window.requestAnimationFrame(frame); }
  }

  function pause() {
    if (!playing) { return; }
    playing = false;
    stopFrames();
    render();
    syncPlayLabel();
  }

  function reset() {
    playing = false;
    stopFrames();
    t = 0;
    resetDynamic();
    render();
    syncPlayLabel();
  }

  function setSpeed(value) {
    speed = value > 0 ? value : 1;
    for (var i = 0; i < speedBtns.length; i++) {
      var on = parseFloat(speedBtns[i].getAttribute('data-speed')) === speed;
      speedBtns[i].classList.toggle('on', on);
      speedBtns[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }

  // ── Fit: the stage is drawn in fixed pixels, so scale it into the frame ─
  // The console viewport is whatever width the operator's window is.  The
  // geometry the animation interpolates must not change, so the whole stage is
  // scaled with a CSS transform instead — never re-laid-out, never clipped.
  var wrapEl = document.querySelector('.gb-stage-wrap');

  function fit() {
    if (!wrapEl) { return; }
    var body = document.querySelector('.gb-body');
    if (!body) { return; }
    var avail = body.clientWidth;
    var sideBySide = false;
    if (stepsEl) {
      sideBySide = stepsEl.offsetTop < wrapEl.offsetTop + 8;
      if (sideBySide) { avail -= stepsEl.offsetWidth + 16; }
    }
    var natural = wrapEl.offsetWidth;
    var scale = (natural > 0 && avail > 0) ? Math.min(1, avail / natural) : 1;
    wrapEl.style.transformOrigin = 'top left';
    wrapEl.style.transform = scale < 0.999 ? 'scale(' + scale + ')' : 'none';
    // The scaled box keeps its layout height, so give the gap back.
    wrapEl.style.marginBottom = scale < 0.999
      ? ((scale - 1) * wrapEl.offsetHeight) + 'px'
      : '0';
  }

  // ── Controls ──────────────────────────────────────────────────────────
  var stepsEl = document.querySelector('.gb-steps');
  if (playBtn) {
    playBtn.addEventListener('click', function () { if (playing) { pause(); } else { play(); } });
  }
  if (stepBtn) { stepBtn.addEventListener('click', stepOnce); }
  if (resetBtn) { resetBtn.addEventListener('click', reset); }
  for (var b = 0; b < speedBtns.length; b++) {
    speedBtns[b].addEventListener('click', function (event) {
      setSpeed(parseFloat(event.currentTarget.getAttribute('data-speed')) || 1);
    });
  }
  window.addEventListener('keydown', function (event) {
    var key = event.key;
    if (key === ' ' || key === 'Spacebar') {
      event.preventDefault();
      if (playing) { pause(); } else { play(); }
    } else if (key === 'r' || key === 'R') {
      reset();
    } else if (key === 's' || key === 'S' || key === 'ArrowRight') {
      event.preventDefault();
      stepOnce();
    }
  });

  // ── Boot: autoplay the fresh run, otherwise show the finished execution ─
  setSpeed(speed);
  fit();
  window.addEventListener('resize', fit);
  resetDynamic();
  if (TL.duration_ms > 0 && TL.autoplay && !reduced) {
    playing = true;
  } else {
    t = TL.duration_ms;
  }
  render();
  syncPlayLabel();
  if (playing) { frameId = window.requestAnimationFrame(frame); }
})();
"""


# ── Document ─────────────────────────────────────────────────────────────────

def _payload(
    timeline: dict,
    cell_px: int,
    autoplay: bool,
    speed: float,
    timeline_scope: str | None,
) -> dict:
    """Compact JSON state handed to the player runtime."""
    events = []
    for event in timeline.get("events", []):
        events.append({key: value for key, value in event.items() if value is not None})
    steps = []
    for step in timeline.get("steps", []):
        steps.append({
            "index": int(step.get("index", 0)),
            "label": str(step.get("label", "")),
            "start_ms": int(step.get("start_ms", 0)),
            "end_ms": int(step.get("end_ms", 0)),
            "halted": step.get("halted"),
        })
    return {
        "start": list(timeline.get("start", [0, 0])),
        "start_dir": timeline.get("start_dir", "E"),
        "events": events,
        "steps": steps,
        "duration_ms": int(timeline.get("duration_ms", 0)),
        "cells": int(timeline.get("cells", 0)),
        "ok": bool(timeline.get("ok", False)),
        "halted": timeline.get("halted"),
        "reached": bool(timeline.get("reached", False)),
        "cell_px": int(cell_px),
        "pitch": pitch(cell_px),
        "speed": float(speed),
        "autoplay": bool(autoplay),
        "trace_draw_ms": A.TRACE_DRAW_MS,
        # Provenance, the outcome row's own words, and the host timeline this
        # playhead may mark — the runtime reads all three, and decides nothing.
        "approved": bool(timeline.get("approved")),
        "copy": outcome_copy(timeline),
        "timeline_scope": str(timeline_scope or ""),
    }


def player_html(
    timeline: dict,
    *,
    cell_px: int = S.CELL_SIZE,
    autoplay: bool = True,
    speed: float = A.DEFAULT_SPEED,
    show_steps: bool = True,
    timeline_scope: str | None = None,
) -> str:
    """Complete HTML document replaying one execution *timeline*.

    ``autoplay`` starts the run from the first cell; ``autoplay=False`` opens
    on the finished execution so a Streamlit rerun never replays by surprise —
    the Play button then acts as Replay.  ``show_steps=False`` leaves the step
    list out for a host that renders its own action timeline.

    ``timeline_scope`` names a timeline on the host page
    (``console.timeline_html(rows, scope=...)``) that this playhead should mark
    as it moves: the action being shown gets ``data-live`` while the player is
    on it, and the mark clears at the end of the run.  Pass ``None`` (the
    default) for a host with no timeline to follow.  A timeline the guard did
    not verify is drawn as a *preview*: its heading, its tooltips and its
    outcome line say simulated, never executed.
    """
    cs = int(cell_px)
    side = stage_px(cs)
    approved = bool(timeline.get("approved"))
    copy = outcome_copy(timeline)
    payload = json.dumps(
        _payload(timeline, cs, autoplay, speed, timeline_scope),
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    world = timeline.get("world", {})
    heading, step_word, play_word = kind_words(timeline)
    # The controls follow the provenance: a preview has no verified action to
    # offer, so its Step button must not promise one.
    play_tip = f"Replay {play_word} (&amp;space)"
    step_tip = f"Advance one {step_word} (&amp;S)"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"{_css(cs)}"
        "</head><body>"
        f"<div class='gb-exec{' gb-exec-compact' if not show_steps else ''}'>"
        "<div class='gb-head'>"
        f"<span class='gb-head-title'>{heading}</span>"
        "<span class='gb-rule'></span>"
        "<span class='gb-stepnow' id='gb-stepnow'>ready</span>"
        "<span class='gb-readout' id='gb-readout'></span>"
        "<span class='gb-chip' id='gb-chip'>READY</span>"
        "</div>"
        "<div class='gb-body'>"
        "<div class='gb-stage-wrap'>"
        f"<div class='gb-colrow'>{_col_labels_html(cs)}</div>"
        "<div class='gb-rowwrap'>"
        f"<div class='gb-rows'>{_row_labels_html(cs)}</div>"
        f"<div class='gb-stage' id='gb-stage' style='width:{side}px;height:{side}px'>"
        f"{_cells_html(world, cs)}"
        f"<svg class='gb-trace' id='gb-trace' width='{side}' height='{side}' "
        f"viewBox='0 0 {side} {side}' style='--gb-trace-len:{pitch(cs)}px'></svg>"
        f"{_robot_html(cs)}"
        "</div></div></div>"
        + (
            f"<div class='gb-steps'>{_steps_html(timeline.get('steps', []))}</div>"
            if show_steps else ""
        )
        + "</div>"
        "<div class='gb-transport'>"
        f"<button type='button' class='gb-btn gb-btn-primary' id='gb-play' "
        f"title='{play_tip}'>&#9654; Play</button>"
        f"<button type='button' class='gb-btn' id='gb-step' "
        f"title='{step_tip}'>&#9197; Step</button>"
        "<button type='button' class='gb-btn' id='gb-reset' "
        "title='Return to the first cell (&amp;R)'>&#10226; Reset</button>"
        "<span class='gb-speed' role='group' aria-label='Playback speed'>"
        f"{_speed_buttons_html(speed)}</span>"
        "<span class='gb-progress' title='Playback progress at the selected speed'>"
        "<span id='gb-bar'></span></span>"
        "</div>"
        f"{_outcome_html(copy, autoplay=autoplay)}"
        "</div>"
        f"<script>window.__TL__ = {payload};{_JS}</script>"
        "</body></html>"
    )
