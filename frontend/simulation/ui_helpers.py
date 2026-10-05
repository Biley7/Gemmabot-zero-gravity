"""Pure-Python presentation helpers for the GemmaBot Streamlit frontend.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

Every function takes real backend values (simulator ``render()`` rows,
``harness.plan_with_repair()`` / ``map_vision.read_map()`` history, measured
run results) and turns them into display-ready data.  Nothing here invents
success or timing.
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

# Glyphs produced by gemmabot.simulator.render().
WALL_CELL  = "🧱"
GOAL_CELL  = "🎯"
EMPTY_CELL = "⬜"
ROBOT_CELLS = set(ARROW.values())

CELL_SIZE   = S.CELL_SIZE          # 40px — from spacing token
LABEL_SIZE  = S.CELL_LABEL_WIDTH   # 24px — from spacing token

_CELL_BG = {
    WALL_CELL:  C.GRID_WALL,
    GOAL_CELL:  C.GRID_GOAL,
    EMPTY_CELL: C.GRID_EMPTY,
}
_ROBOT_BG    = C.GRID_ROBOT
_BORDER_COL  = C.GRID_BORDER
_LABEL_COLOR = C.GRID_LABEL


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
    """Lay out ``simulator.render(world)`` rows as an HTML grid.

    The simulator renderer is the source of truth for glyphs; this helper only
    adds the 8x8 structure and zero-based x/y coordinate labels so the UI
    matches the JSON coordinates.
    """
    grid = [_split_cells(str(row)) for row in (rows or [])]
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
        attempt = record.get("attempt", index)
        ok = bool(record.get("ok"))
        reply = record.get("reply") or ""
        feedback = record.get("feedback") or ""
        cards.append(
            {
                "attempt": attempt,
                "label": f"Attempt {attempt}",
                "status": "OK" if ok else "FAIL",
                "ok": ok,
                "prompt": record.get("prompt") or "",
                "reply": reply,
                "parsed": _parse_json_maybe(reply),
                "feedback": feedback,
                "error": None if ok else (feedback or "no feedback"),
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
    """Display-ready metrics for one planning/vision run.

    Values are measured (attempts/latency come from the real run); nothing
    is estimated.
    """
    n_actions = len(actions) if isinstance(actions, list) else 0
    ok = actions is not None
    return {
        "attempts": attempts,
        "max_tries": max_tries,
        "attempts_label": f"{attempts} / {max_tries}",
        "latency": latency,
        "latency_label": f"{latency:.2f} s" if latency is not None else "n/a",
        "actions": n_actions,
        "actions_label": str(n_actions),
        "status": "Verified safe" if ok else "No valid plan",
        "ok": ok,
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
