"""Pure-Python presentation helpers for the GemmaBot Streamlit frontend.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

Every function takes real backend values (simulator ``render()`` rows,
``harness.plan_with_repair()`` / ``map_vision.read_map()`` history, measured
run results) and turns them into display-ready data.  Nothing here invents
success or timing.

Public surface
--------------
grid_html(rows)
    Compat grid used by tests and map-vision scan tab.
    Accepts the list[str] from simulator.render().

world_grid_html(world, path=[], current_step=-1)
    Hero grid. Accepts the full world dict, an optional executed-path cell
    list, and an optional 1-based step index being animated.

grid_legend_html()
    Returns the HTML legend block for the hero grid.
"""
from __future__ import annotations

import html
import json
import re
from typing import Any

from gemmabot.simulator import ARROW
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.components import animations as A

# ── Glyph constants (from simulator) ─────────────────────────────────────────
WALL_CELL   = "🧱"
GOAL_CELL   = "🎯"
EMPTY_CELL  = "⬜"
ROBOT_CELLS = set(ARROW.values())

# ── Compat grid dimensions (tests rely on these) ──────────────────────────────
CELL_SIZE  = S.CELL_SIZE          # 40 px
LABEL_SIZE = S.CELL_LABEL_WIDTH   # 24 px

# ── Compat color map ──────────────────────────────────────────────────────────
_CELL_BG = {
    WALL_CELL:  C.GRID_WALL,
    GOAL_CELL:  C.GRID_GOAL,
    EMPTY_CELL: C.GRID_EMPTY,
}
_ROBOT_BG    = C.GRID_ROBOT
_BORDER_COL  = C.GRID_BORDER
_LABEL_COLOR = C.GRID_LABEL


# ─────────────────────────────────────────────────────────────────────────────
# Compat grid helpers (unchanged — tests pass rows here)
# ─────────────────────────────────────────────────────────────────────────────

def _split_cells(row: str) -> list[str]:
    """Split one ``render()`` row into per-cell glyphs.

    ``render()`` writes exactly one glyph per cell with no separator.  Emoji
    such as "⬆️" are a base codepoint plus a variation selector, so a naive
    character split would tear them apart; the selector is appended to the
    glyph it belongs to.
    """
    cells: list[str] = []
    for ch in row:
        if ch == "\ufe0f" and cells:
            cells[-1] += ch
        else:
            cells.append(ch)
    return cells


def _cell_html(glyph: str) -> str:
    if glyph in ROBOT_CELLS:
        background = _ROBOT_BG
    else:
        background = _CELL_BG.get(glyph, "transparent")
    font_size = int(CELL_SIZE * 0.55)
    return (
        "<div class='gb-cell' style='"
        f"width:{CELL_SIZE}px;height:{CELL_SIZE}px;display:flex;"
        f"align-items:center;justify-content:center;font-size:{font_size}px;"
        f"border:1px solid {_BORDER_COL};box-sizing:border-box;background:{background}'>"
        f"{html.escape(glyph)}</div>"
    )


def _label_html(text: str, height: int) -> str:
    return (
        "<div class='gb-label' style='"
        f"width:{LABEL_SIZE}px;height:{height}px;"
        f"font-size:{T.SIZE_XS}px;font-family:{T.FONT_MONO};color:{_LABEL_COLOR};"
        "display:flex;align-items:center;justify-content:center'>"
        f"{html.escape(text)}</div>"
    )


def grid_html(rows: list[str]) -> str:
    """Compat grid from ``simulator.render(world)`` rows.

    The simulator renderer is the source of truth for glyphs; this helper only
    adds the 8x8 structure and zero-based x/y coordinate labels so the UI
    matches the JSON coordinates.
    """
    grid    = [_split_cells(str(row)) for row in (rows or [])]
    columns = max((len(row) for row in grid), default=0)

    parts = [
        "<div class='gb-grid' style='display:inline-block;"
        f"font-family:{T.FONT_MONO}'>"
    ]

    # Column coordinate labels (x grows right).
    parts.append("<div class='gb-row' style='display:flex'>")
    parts.append(_label_html("", 20))
    for x in range(columns):
        parts.append(
            "<div class='gb-label' style='"
            f"width:{CELL_SIZE}px;height:20px;"
            f"font-size:{T.SIZE_XS}px;font-family:{T.FONT_MONO};color:{_LABEL_COLOR};"
            "display:flex;align-items:center;justify-content:center'>"
            f"{x}</div>"
        )
    parts.append("</div>")

    # One flex row per grid row, with its y coordinate label.
    for y, cells in enumerate(grid):
        parts.append("<div class='gb-row' style='display:flex'>")
        parts.append(_label_html(str(y), CELL_SIZE))
        for x in range(columns):
            parts.append(_cell_html(cells[x] if x < len(cells) else ""))
        parts.append("</div>")

    parts.append("</div>")
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Hero grid — world_grid_html
# ─────────────────────────────────────────────────────────────────────────────

# Robot directional SVG arrows — crisp geometric icons, no emoji.
# Public: shared with the execution player (frontend/simulation/player_view.py).
ROBOT_SVG: dict[str, str] = {
    # North — arrow pointing up
    "N": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M12 4L20 18H4L12 4Z" fill="{fg}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>'
        '</svg>'
    ),
    # East — arrow pointing right
    "E": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M20 12L6 4V20L20 12Z" fill="{fg}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>'
        '</svg>'
    ),
    # South — arrow pointing down
    "S": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M12 20L4 6H20L12 20Z" fill="{fg}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>'
        '</svg>'
    ),
    # West — arrow pointing left
    "W": (
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M4 12L18 4V20L4 12Z" fill="{fg}" stroke="{stroke}" stroke-width="1.5" stroke-linejoin="round"/>'
        '</svg>'
    ),
}

# Goal SVG — a clean target crosshair
GOAL_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="12" r="8" stroke="{fg}" stroke-width="1.5"/>'
    '<circle cx="12" cy="12" r="4" stroke="{fg}" stroke-width="1.5"/>'
    '<circle cx="12" cy="12" r="1.5" fill="{fg}"/>'
    '<line x1="12" y1="2" x2="12" y2="6" stroke="{fg}" stroke-width="1.5" stroke-linecap="round"/>'
    '<line x1="12" y1="18" x2="12" y2="22" stroke="{fg}" stroke-width="1.5" stroke-linecap="round"/>'
    '<line x1="2" y1="12" x2="6" y2="12" stroke="{fg}" stroke-width="1.5" stroke-linecap="round"/>'
    '<line x1="18" y1="12" x2="22" y2="12" stroke="{fg}" stroke-width="1.5" stroke-linecap="round"/>'
    '</svg>'
)

# Wall inner texture — 3 horizontal hash marks
WALL_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<line x1="6" y1="8"  x2="18" y2="8"  stroke="{fg}" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>'
    '<line x1="6" y1="12" x2="18" y2="12" stroke="{fg}" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>'
    '<line x1="6" y1="16" x2="18" y2="16" stroke="{fg}" stroke-width="1.2" stroke-linecap="round" opacity="0.5"/>'
    '</svg>'
)

# Path dot — small centred circle
PATH_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="12" cy="12" r="3" fill="{fg}" opacity="0.55"/>'
    '</svg>'
)


def _hero_cell(
    x: int,
    y: int,
    is_robot: bool,
    is_goal: bool,
    is_wall: bool,
    is_path: bool,
    is_current: bool,
    direction: str = "E",
    cell_px: int = S.CELL_SIZE_HERO,
    is_danger: bool = False,
) -> str:
    """Return one hero-grid cell div with full styling.

    *is_danger* marks the cell a plan was refused entry to (the Safety Lab's
    collision location).  It outranks the wall style so the obstacle that
    blocked the plan is unmistakable.
    """
    cs = cell_px
    icon_px = int(cs * 0.52)
    r = S.RADIUS_SM

    # ── Determine background, border, box-shadow ──────────────────────────
    if is_robot:
        bg      = C.GRID_ROBOT
        border  = C.GRID_CURRENT_BORDER
        shadow  = f"0 0 0 1.5px {C.GRID_ROBOT_GLOW}40, inset 0 0 8px {C.GRID_ROBOT_GLOW}18"
        extra   = ""
    elif is_goal:
        bg      = C.GRID_GOAL
        border  = C.SUCCESS_BORDER
        shadow  = "none"
        extra   = f"animation:gb-goal-glow 2.8s {A.EASE_INOUT} infinite;"
    elif is_danger:
        bg      = C.ERROR_BG
        border  = C.ERROR
        shadow  = f"0 0 0 1px {C.ERROR}55, inset 0 0 10px {C.ERROR}22"
        extra   = f"animation:{A.animation_danger_pulse()};"
    elif is_wall:
        bg      = C.GRID_WALL
        border  = C.GRID_WALL_EDGE
        shadow  = f"inset 0 1px 0 {C.GRID_WALL_SURFACE}60, inset 0 -1px 0 {C.GRID_WALL_EDGE}"
        extra   = ""
    elif is_current:
        bg      = C.GRID_CURRENT
        border  = C.GRID_CURRENT_BORDER
        shadow  = "none"
        extra   = f"animation:gb-step-flash 0.7s {A.EASE_OUT} both;"
    elif is_path:
        bg      = C.GRID_PATH
        border  = C.GRID_PATH_BORDER
        shadow  = "none"
        extra   = ""
    else:
        bg      = C.GRID_EMPTY
        border  = C.GRID_BORDER
        shadow  = "none"
        extra   = ""

    # ── Hover class — injected via CSS, not inline (no JS needed) ─────────
    hover_cls = "" if (is_wall or is_danger) else " gb-hero-cell-hover"

    base_style = (
        f"width:{cs}px;height:{cs}px;"
        f"display:flex;align-items:center;justify-content:center;"
        f"box-sizing:border-box;position:relative;"
        f"background:{bg};"
        f"border:1px solid {border};"
        f"border-radius:{r}px;"
        f"box-shadow:{shadow};"
        f"transition:background 150ms ease, box-shadow 150ms ease;"
        f"{extra}"
    )

    # ── Icon ──────────────────────────────────────────────────────────────
    if is_robot:
        svg_tmpl = ROBOT_SVG.get(direction, ROBOT_SVG["E"])
        icon_svg = svg_tmpl.format(fg=C.ACCENT_BLUE, stroke=C.ACCENT_BLUE_DIM)
    elif is_goal:
        icon_svg = GOAL_SVG.format(fg=C.SUCCESS)
    elif is_danger:
        # Keep the obstacle's own texture, tinted red: you see exactly which
        # wall the plan was refused entry to.
        icon_svg = (WALL_SVG if is_wall else PATH_SVG).format(fg=C.ERROR)
    elif is_wall:
        icon_svg = WALL_SVG.format(fg=C.TEXT_MUTED)
    elif is_path or is_current:
        icon_svg = PATH_SVG.format(fg=C.RUNNING)
    else:
        icon_svg = ""

    icon_html = (
        f"<div style='width:{icon_px}px;height:{icon_px}px;flex-shrink:0'>"
        f"{icon_svg}</div>"
        if icon_svg else ""
    )

    return (
        f"<div class='gb-hero-cell{hover_cls}' "
        f"data-x='{x}' data-y='{y}' "
        f"style='{base_style}'>"
        f"{icon_html}"
        f"</div>"
    )


def _hero_css(cell_px: int) -> str:
    """Inline <style> block scoped to the hero grid."""
    return (
        "<style>"
        ".gb-hero-cell-hover:hover {"
        f"  background:{C.GRID_HOVER} !important;"
        f"  border-color:{C.BORDER_DEFAULT} !important;"
        f"  box-shadow:inset 0 0 0 1px {C.BORDER_STRONG} !important;"
        "}"
        ".gb-hero-grid {"
        "  display:inline-block;"
        f"  background:{C.BG_BASE};"
        f"  padding:{S.px(S.SM)};"
        f"  border-radius:{S.RADIUS_LG}px;"
        "}"
        "</style>"
    )


def world_grid_html(
    world: dict,
    path: list[list[int]] | None = None,
    current_step: int = -1,
    cell_px: int = S.CELL_SIZE_HERO,
    danger_cell: list[int] | None = None,
) -> str:
    """Hero grid rendered from the full world dict.

    Parameters
    ----------
    world:
        Simulator world: robot [x,y], dir, goal [x,y], walls [[x,y]…].
    path:
        Optional list of [x, y] cells on the executed path (not including
        robot's current position). Shown as faint path dots.
    current_step:
        Optional [x, y] of the cell the robot just moved to in the current
        animation frame. Gets the step-flash animation.
    cell_px:
        Override cell size in pixels.
    danger_cell:
        Optional [x, y] the verifier refused a plan entry to (a collision or
        grid edge). Marked in the error colour with a slow red pulse.
    """
    path = path or []
    danger = tuple(int(v) for v in danger_cell) if danger_cell else None
    robot   = world.get("robot", [0, 0])
    goal    = world.get("goal",  [7, 7])
    walls   = world.get("walls", [])
    dirn    = world.get("dir",   "E")
    from gemmabot.config import SIZE

    wall_set    = {tuple(w) for w in walls}
    path_set    = {tuple(p) for p in path}

    cs    = cell_px
    lw    = S.CELL_LABEL_HERO   # label gutter width
    lh    = 24                  # label row height

    parts: list[str] = [_hero_css(cs)]

    parts.append(
        f"<div class='gb-hero-grid' style='"
        f"display:inline-block;background:{C.BG_BASE};"
        f"padding:{S.px(S.SM)};border-radius:{S.RADIUS_LG}px'>"
    )

    # ── Column coordinate labels ──────────────────────────────────────────
    parts.append(
        f"<div style='display:flex;margin-bottom:2px'>"
        f"<div style='width:{lw}px;height:{lh}px'></div>"
    )
    for x in range(SIZE):
        parts.append(
            f"<div style='width:{cs}px;height:{lh}px;display:flex;"
            f"align-items:center;justify-content:center;"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.GRID_LABEL};letter-spacing:0.04em'>{x}</div>"
        )
    parts.append("</div>")

    # ── Grid rows ─────────────────────────────────────────────────────────
    for y in range(SIZE):
        parts.append(
            f"<div style='display:flex;margin-bottom:1px'>"
            # Row label
            f"<div style='width:{lw}px;height:{cs}px;display:flex;"
            f"align-items:center;justify-content:center;"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.GRID_LABEL};letter-spacing:0.04em;margin-right:1px'>{y}</div>"
        )
        for x in range(SIZE):
            coord = (x, y)
            is_robot   = [x, y] == robot
            is_goal    = [x, y] == goal
            is_wall    = coord in wall_set
            is_path    = coord in path_set and not is_robot and not is_goal
            is_current = (
                isinstance(current_step, list)
                and [x, y] == current_step
                and not is_robot
            )
            is_danger = coord == danger and not is_robot and not is_goal
            parts.append(
                _hero_cell(
                    x, y,
                    is_robot=is_robot,
                    is_goal=is_goal,
                    is_wall=is_wall,
                    is_path=is_path,
                    is_current=is_current,
                    direction=dirn,
                    cell_px=cs,
                    is_danger=is_danger,
                )
            )
            if x < SIZE - 1:
                parts.append(f"<div style='width:1px;background:{C.GRID_BORDER}'></div>")
        parts.append("</div>")

    parts.append("</div>")   # .gb-hero-grid
    return "".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Legend
# ─────────────────────────────────────────────────────────────────────────────

def grid_legend_html() -> str:
    """Returns a compact horizontal legend for the hero grid."""
    dot_size = 12
    icon_size = 18

    def _swatch(bg: str, border: str, icon_svg: str = "", label: str = "") -> str:
        swatch = (
            f"<div style='width:{dot_size * 2}px;height:{dot_size * 2}px;"
            f"background:{bg};border:1px solid {border};"
            f"border-radius:{S.RADIUS_SM}px;display:flex;"
            f"align-items:center;justify-content:center;flex-shrink:0'>"
            f"<div style='width:{icon_size}px;height:{icon_size}px'>{icon_svg}</div>"
            f"</div>"
        )
        lbl = (
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_SECONDARY};letter-spacing:0.04em;white-space:nowrap'>"
            f"{html.escape(label)}</span>"
        )
        return (
            f"<div style='display:flex;align-items:center;"
            f"gap:{S.px(S.XS)}'>{swatch}{lbl}</div>"
        )

    robot_icon  = ROBOT_SVG["E"].format(fg=C.ACCENT_BLUE, stroke=C.ACCENT_BLUE_DIM)
    goal_icon   = GOAL_SVG.format(fg=C.SUCCESS)
    wall_icon   = WALL_SVG.format(fg=C.TEXT_MUTED)
    path_icon   = PATH_SVG.format(fg=C.RUNNING)
    empty_icon  = ""

    danger_icon = WALL_SVG.format(fg=C.ERROR)

    items = [
        _swatch(C.GRID_ROBOT,  C.GRID_CURRENT_BORDER, robot_icon, "Robot"),
        _swatch(C.GRID_GOAL,   C.SUCCESS_BORDER,       goal_icon,  "Goal"),
        _swatch(C.GRID_WALL,   C.GRID_WALL_EDGE,        wall_icon,  "Obstacle"),
        _swatch(C.ERROR_BG,    C.ERROR,                 danger_icon, "Collision"),
        _swatch(C.GRID_PATH,   C.GRID_PATH_BORDER,      path_icon,  "Path"),
        _swatch(C.GRID_EMPTY,  C.GRID_BORDER,           empty_icon, "Empty"),
    ]

    return (
        f"<div style='display:flex;flex-wrap:wrap;align-items:center;"
        f"gap:{S.px(S.LG)};padding:{S.px(S.SM)} 0'>"
        + "".join(items)
        + "</div>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json_maybe(text: Any) -> Any:
    """Best-effort JSON parse of a model reply.  Never raises."""
    if not isinstance(text, str) or not text.strip():
        return None
    stripped = re.sub(r"```(?:json)?", "", text).strip()
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(stripped[start : end + 1])
    except (ValueError, TypeError):
        return None


def attempt_cards(history: list[dict]) -> list[dict]:
    """Build one display card per verification attempt.

    Accepts the history shape produced by ``harness.plan_with_repair()`` and
    ``gemmabot.map_vision.read_map()``::

        {"attempt": 1, "prompt": "...", "reply": "...", "ok": False,
         "feedback": "..."}

    Returns a list of view-model dicts with pre-formatted, display-ready
    fields (no Streamlit involved): ``attempt``, ``label``, ``status``, ``ok``,
    ``prompt``, ``reply``, ``parsed`` (best-effort JSON or ``None``),
    ``feedback`` and ``error`` (the failure reason or ``None``).
    """
    cards: list[dict] = []
    for index, record in enumerate(history or [], start=1):
        if not isinstance(record, dict):
            continue
        attempt  = record.get("attempt", index)
        ok       = bool(record.get("ok"))
        reply    = record.get("reply") or ""
        feedback = record.get("feedback") or ""
        cards.append(
            {
                "attempt": attempt,
                "label":   f"Attempt {attempt}",
                "status":  "OK" if ok else "FAIL",
                "ok":      ok,
                "prompt":  record.get("prompt") or "",
                "reply":   reply,
                "parsed":  _parse_json_maybe(reply),
                "feedback": feedback,
                "error":   None if ok else (feedback or "no feedback"),
            }
        )
    return cards


def accepted_reply(history: list[dict]) -> dict | None:
    """Return the card for the first accepted attempt, or ``None``."""
    for card in attempt_cards(history):
        if card["ok"]:
            return card
    return None


def run_metrics(
    actions: list[dict] | None,
    attempts: int,
    max_tries: int,
    latency: float | None,
) -> dict:
    """Display-ready metrics for one planning/vision run."""
    n_actions = len(actions) if isinstance(actions, list) else 0
    ok        = actions is not None
    return {
        "attempts":       attempts,
        "max_tries":      max_tries,
        "attempts_label": f"{attempts} / {max_tries}",
        "latency":        latency,
        "latency_label":  f"{latency:.2f} s" if latency is not None else "n/a",
        "actions":        n_actions,
        "actions_label":  str(n_actions),
        "status":         "Verified safe" if ok else "No valid plan",
        "ok":             ok,
    }


def short_json(obj: Any, limit: int = 300) -> str:
    """Compact JSON for display, truncated to *limit* characters."""
    try:
        text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        text = repr(obj)
    limit = max(0, int(limit))
    if len(text) > limit:
        return text[:limit] + "…"
    return text
