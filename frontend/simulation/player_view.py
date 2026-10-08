"""Execution player — self-contained HTML/CSS/JS replay of a timeline.

Owner: FRONTEND.  Pure string building: no Streamlit import, no network.

``player_html()`` returns one complete HTML document that
``st.components.v1.html`` renders into an iframe.  It is the only animation
runtime in the app: vanilla CSS + ~4 kB of plain JavaScript, no external
script, no CDN, no library.

It replays ``frontend.simulation.player.build_timeline()`` exactly as the
backend simulator produced it — the robot interpolates one cell per 300 ms
step, turns rotate smoothly, the trail is drawn in behind it and the active
step is highlighted in the step list.  Transport: play / pause / reset and
0.5x / 1x / 2x / 4x playback speed.

Public surface
--------------
player_html(timeline, *, cell_px, autoplay, speed) -> str
player_height(cell_px) -> int      # iframe height that avoids scrolling
"""
from __future__ import annotations

import html
import json

from gemmabot.config import SIZE
from frontend.components import animations as A
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
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
    step = pitch(cell_px)
    return "".join(
        f"<div class='gb-axis col' style='width:{step}px;height:{LABEL_H}px'>"
        f"{x}</div>"
        for x in range(SIZE)
    )


def _row_labels_html(cell_px: int) -> str:
    step = pitch(cell_px)
    return "".join(
        f"<div class='gb-axis row' style='width:{LABEL_W}px;height:{step}px'>"
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
.gb-head {{
  display: flex; align-items: center; gap: {S.px(S.SM)};
  height: {HEAD_H}px; margin-bottom: {S.px(S.MD)};
  font-family: {T.FONT_MONO};
}}
.gb-head-title {{
  font-size: {T.SIZE_SM}px; color: {C.TEXT_MUTED}; letter-spacing: {T.TRACKING_WIDE};
  text-transform: uppercase; white-space: nowrap;
}}
.gb-rule {{ flex: 1; height: 1px; background: {C.BORDER_SUBTLE}; }}
.gb-stepnow {{ font-size: {T.SIZE_SM}px; color: {C.TEXT_SECONDARY}; white-space: nowrap; }}
.gb-readout {{ font-size: {T.SIZE_SM}px; color: {C.ACCENT_BLUE}; white-space: nowrap; }}
.gb-chip {{
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_SM}px; letter-spacing: {T.TRACKING_WIDE};
  padding: 2px {S.px(S.SM)}; border-radius: {S.RADIUS_SM}px; white-space: nowrap;
  border: 1px solid {C.BORDER_DEFAULT}; background: {C.BG_ELEVATED}; color: {C.TEXT_SECONDARY};
}}
.gb-chip.ok {{ background: {C.SUCCESS_BG}; border-color: {C.SUCCESS_BORDER}; color: {C.SUCCESS}; }}
.gb-chip.err {{ background: {C.ERROR_BG}; border-color: {C.ERROR_BORDER}; color: {C.ERROR}; }}
.gb-chip.warn {{ background: {C.WARNING_BG}; border-color: {C.WARNING_BORDER}; color: {C.WARNING}; }}
.gb-chip.run {{
  background: {C.RUNNING_BG}; border-color: {C.RUNNING_BORDER}; color: {C.RUNNING};
  animation: gb-pulse 1.8s {A.EASE_INOUT} infinite;
}}

/* ── Body: grid stage + step list ─────────────────────────────────────── */
.gb-body {{
  display: flex; flex-wrap: wrap; align-items: flex-start;
  gap: {S.px(S.LG)};
}}
.gb-stage-wrap {{ display: flex; flex-direction: column; }}
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
  display: flex; flex-direction: column; width: 232px;
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

/* ── Transport ────────────────────────────────────────────────────────── */
.gb-transport {{ display: flex; align-items: center; gap: {S.px(S.SM)}; margin-top: {S.px(S.MD)}; }}
.gb-btn {{
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_SM}px; letter-spacing: {T.TRACKING_WIDE};
  padding: 5px {S.px(S.MD)}; border-radius: {S.RADIUS_SM}px;
  border: 1px solid {C.BORDER_DEFAULT}; background: {C.BG_ELEVATED}; color: {C.TEXT_PRIMARY};
  cursor: pointer; transition: background 150ms {A.EASE_OUT}, border-color 150ms {A.EASE_OUT};
}}
.gb-btn:hover {{ background: {C.BG_OVERLAY}; border-color: {C.BORDER_STRONG}; }}
.gb-btn:focus-visible {{ outline: 2px solid {C.ACCENT_BLUE}; outline-offset: 2px; }}
.gb-btn-primary {{ background: {C.ACCENT_BLUE}; border-color: {C.ACCENT_BLUE}; color: {C.BG_BASE}; font-weight: {T.WEIGHT_SEMIBOLD}; }}
.gb-btn-primary:hover {{ background: {C.ACCENT_BLUE_DIM}; border-color: {C.ACCENT_BLUE_DIM}; }}
.gb-speed {{ display: flex; border: 1px solid {C.BORDER_DEFAULT}; border-radius: {S.RADIUS_SM}px; overflow: hidden; }}
.gb-speed-btn {{
  font-family: {T.FONT_MONO}; font-size: {T.SIZE_SM}px; padding: 5px {S.px(S.SM)};
  border: none; border-right: 1px solid {C.BORDER_SUBTLE}; background: transparent;
  color: {C.TEXT_MUTED}; cursor: pointer; transition: background 150ms {A.EASE_OUT}, color 150ms {A.EASE_OUT};
}}
.gb-speed-btn:last-child {{ border-right: none; }}
.gb-speed-btn:hover {{ background: {C.BG_OVERLAY}; color: {C.TEXT_PRIMARY}; }}
.gb-speed-btn.on {{ background: {C.ACCENT_BLUE}; color: {C.BG_BASE}; font-weight: {T.WEIGHT_SEMIBOLD}; }}
.gb-progress {{ flex: 1; height: 3px; min-width: 60px; background: {C.BG_OVERLAY}; border-radius: 2px; overflow: hidden; }}
.gb-progress span {{ display: block; height: 100%; width: 0; background: {C.ACCENT_BLUE}; transition: width 100ms linear; }}
.gb-time {{ font-family: {T.FONT_MONO}; font-size: {T.SIZE_XS}px; color: {C.TEXT_MUTED}; white-space: nowrap; }}
.gb-speed-btn:focus-visible {{
  outline: 2px solid {C.ACCENT_BLUE}; outline-offset: 2px;
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
  var timeEl = document.getElementById('gb-time');
  var chipEl = document.getElementById('gb-chip');
  var stepNowEl = document.getElementById('gb-stepnow');
  var readoutEl = document.getElementById('gb-readout');
  var playBtn = document.getElementById('gb-play');
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

  function syncChrome(ms, st, activeStep) {
    var finished = TL.duration_ms > 0 && ms >= TL.duration_ms;
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
    if (activeStep > 0 && TL.steps[activeStep - 1]) {
      label = pad(activeStep) + '/' + pad(TL.steps.length) + ' · ' + TL.steps[activeStep - 1].label;
    } else if (finished) {
      label = TL.steps.length + ' steps · ' + TL.cells + ' cells';
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
    }
    if (timeEl) {
      timeEl.textContent = seconds(Math.min(ms, TL.duration_ms)) + ' / ' + seconds(TL.duration_ms);
    }
  }

  function render() {
    var st = stateAt(t);
    applyStatic(t);
    var activeStep = syncSteps(t);
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
    syncChrome(t, st, activeStep);
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

  // ── Controls ──────────────────────────────────────────────────────────
  if (playBtn) {
    playBtn.addEventListener('click', function () { if (playing) { pause(); } else { play(); } });
  }
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
    }
  });

  // ── Boot: autoplay the fresh run, otherwise show the finished execution ─
  setSpeed(speed);
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
    }


def player_html(
    timeline: dict,
    *,
    cell_px: int = S.CELL_SIZE,
    autoplay: bool = True,
    speed: float = A.DEFAULT_SPEED,
) -> str:
    """Complete HTML document replaying one execution *timeline*.

    ``autoplay`` starts the run from the first cell; ``autoplay=False`` opens
    on the finished execution so a Streamlit rerun never replays by surprise —
    the Play button then acts as Replay.
    """
    cs = int(cell_px)
    side = stage_px(cs)
    payload = json.dumps(
        _payload(timeline, cs, autoplay, speed),
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")
    world = timeline.get("world", {})
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        f"{_css(cs)}"
        "</head><body>"
        "<div class='gb-exec'>"
        "<div class='gb-head'>"
        "<span class='gb-head-title'>Execution playback</span>"
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
        f"<div class='gb-steps'>{_steps_html(timeline.get('steps', []))}</div>"
        "</div>"
        "<div class='gb-transport'>"
        "<button type='button' class='gb-btn gb-btn-primary' id='gb-play'>&#9654; Play</button>"
        "<button type='button' class='gb-btn' id='gb-reset'>&#10226; Reset</button>"
        "<span class='gb-speed' role='group' aria-label='Playback speed'>"
        f"{_speed_buttons_html(speed)}</span>"
        "<span class='gb-progress'><span id='gb-bar'></span></span>"
        "<span class='gb-time' id='gb-time'>0.00 s / 0.00 s</span>"
        "</div>"
        "</div>"
        f"<script>window.__TL__ = {payload};{_JS}</script>"
        "</body></html>"
    )
