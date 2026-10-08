"""Vision Lab — image → world model → simulator.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

What is real here
-----------------
The reading, the validation and the load.  ``map_vision.read_map`` makes the
call and parses the reply; each verdict is ``map_vision.check_world_report``'s
(✓ Valid · ✓ Inside bounds · ✓ Reachable); and the world that reaches the
simulator is the very one the validator was shown.  The flow
(Image ↓ World ↓ Simulator) is driven by that state rather than by a timer: a
stage is lit because the thing itself happened — an image is in hand, a reading
really passed all three checks, a world really is the active map.

In dry mode the *reply* is scripted (``engine.dry_vision_ask``): the image is
never sent anywhere and the reader is labelled scripted everywhere it surfaces.
The parser, the retry with the failure reason in the prompt, the three checks and
the load into the simulator are the real pipeline.

Public surface
--------------
STAGES                              the flow: Image, World, Simulator
COLUMN_TITLES                       headings for the three columns
WORLD_CHECKS                        the validator's three checks
checks(world)                       three verdict rows for a proposed world
world_rows(world)                   robot, goal, walls, direction
readings(history)                   one record per attempted reading
flow_stages(...)                    the flow's per-stage state, from real facts
sample_image_bytes(world)           a PNG of a world, in the prompt's own terms
image_rows(...)                     metadata for the uploaded-image column
checks_html(rows)                   the validation list
facts_html(rows)                    the readout grid (world or image metadata)
readings_html(items)                the Gemma Vision column
flow_html(stages)                   the animated Image ↓ World ↓ Simulator diagram
meta_html(...)                      one line describing the reading run
column_html(kind, body)             frames one lab column as a panel
"""
from __future__ import annotations

import io
from typing import Any

from backend.vision.map_vision import WORLD_CHECKS, check_world_report
from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.components.blocks import (
    empty_state,
    escape as _e,
    fact_cards,
    plural as _plural,
)
from frontend.simulation.ui_helpers import attempt_cards, short_json

# ── The flow the lab animates ────────────────────────────────────────────────
STAGES: tuple[str, ...] = ("Image", "World", "Simulator")

# Headings for the three columns, left to right.
COLUMN_TITLES: dict[str, str] = {
    "image": "Uploaded image",
    "vision": "Gemma Vision",
    "world": "World model",
}

_STAGE_KEYS: tuple[str, ...] = ("image", "world", "simulator")

# Per-stage glyphs.  A done stage has really happened, an active one is the next
# piece of real work, a pending one is waiting on it.
_STAGE_MARKS: dict[str, str] = {"done": "✓", "active": "●", "pending": "○"}
_STAGE_STATES: dict[str, str] = {
    "done": "success",
    "active": "running",
    "pending": "neutral",
}
_STAGE_BORDERS: dict[str, str] = {
    "done": C.SUCCESS_BORDER,
    "active": C.RUNNING_BORDER,
    "pending": C.BORDER_SUBTLE,
}
_STAGE_COLORS: dict[str, str] = {
    "done": C.SUCCESS,
    "active": C.RUNNING,
    "pending": C.TEXT_MUTED,
}

# Check marks: pass / fail / unproven.  Unproven is never drawn as a pass.
_MARKS: dict[Any, str] = {True: "✓", False: "✕", None: "–"}
_MARK_STATES: dict[Any, str] = {True: "success", False: "error", None: "neutral"}
_STATE_COLORS: dict[str, str] = {
    "success": C.SUCCESS,
    "error": C.ERROR,
    "warning": C.WARNING,
    "neutral": C.TEXT_MUTED,
    "running": C.RUNNING,
}

# Direction arrows, mirroring the simulator's own heading glyphs.
_DIR_ARROWS: dict[str, str] = {"N": "⬆️", "E": "➡️", "S": "⬇️", "W": "⬅️"}




def _cell_text(cell: Any) -> str:
    """``[3, 0]`` for a coordinate pair, ``—`` when there is none."""
    if isinstance(cell, list) and len(cell) == 2:
        return f"[{int(cell[0])}, {int(cell[1])}]"
    return "—"




def _bytes_label(size: int | None) -> str:
    """Human size for a byte count, or ``—`` when unknown."""
    if not size or size < 0:
        return "—"
    if size < 1024:
        return f"{int(size)} B"
    return f"{size / 1024:.1f} kB"


# ---------------------------------------------------------------------------
# Validation — the three verdicts, straight from the validator
# ---------------------------------------------------------------------------

def checks(world: dict | None) -> list[dict]:
    """The three validation verdicts for a proposed world.

    Straight from ``map_vision.check_world_report``.  A check the validator could
    not evaluate is ``ok=None`` and is reported as unproven ("–") with the reason
    it could not be asked — never as a pass.  ``world=None`` means no reading has
    passed validation yet, which is a different statement from a failed check.
    """
    if not isinstance(world, dict):
        return [
            {
                "id": check_id,
                "label": label,
                "ok": None,
                "mark": _MARKS[None],
                "state": "neutral",
                "detail": "no validated reading yet",
                "data": {},
                "passed": False,
            }
            for check_id, label in WORLD_CHECKS
        ]

    report = check_world_report(world)
    rows: list[dict] = []
    for check in report["checks"]:
        ok = check["ok"]
        rows.append({
            "id": check["id"],
            "label": check["label"],
            "ok": ok,
            "mark": _MARKS[ok],
            "state": _MARK_STATES[ok],
            "detail": check["detail"],
            "data": check.get("data") or {},
            "passed": ok is True,
        })
    return rows


def world_rows(world: dict | None) -> list[dict]:
    """The four things the world model displays: robot, goal, walls, direction.

    Values are the world's own; nothing is inferred.  With no validated reading
    yet every row says so instead of showing a default map's numbers.
    """
    if not isinstance(world, dict):
        return [
            {"id": key, "label": label, "value": "—", "detail": "not read yet",
             "state": "neutral"}
            for key, label in (
                ("robot", "Robot"), ("goal", "Goal"),
                ("walls", "Walls"), ("direction", "Direction"),
            )
        ]

    heading = str(world.get("dir") or "—")
    arrow = _DIR_ARROWS.get(heading, "")
    walls = world.get("walls") or []
    return [
        {
            "id": "robot", "label": "Robot",
            "value": _cell_text(world.get("robot")),
            "detail": "start cell", "state": "neutral",
        },
        {
            "id": "goal", "label": "Goal",
            "value": _cell_text(world.get("goal")),
            "detail": "target cell", "state": "success",
        },
        {
            "id": "walls", "label": "Walls",
            "value": str(len(walls)),
            "detail": _plural(len(walls), "obstacle cell"),
            "state": "neutral",
        },
        {
            "id": "direction", "label": "Direction",
            "value": f"{heading} {arrow}".strip(),
            "detail": "robot heading", "state": "neutral",
        },
    ]


def readings(history: list[dict] | None) -> list[dict]:
    """One record per attempted reading — the Gemma Vision column's data.

    Reuses ``ui_helpers.attempt_cards`` (the same view model the rest of the app
    uses for a propose → verify loop), keeping the reply, the parsed JSON of that
    reply and the verdict on it.
    """
    out: list[dict] = []
    for card in attempt_cards(history or []):
        out.append({
            "attempt": card["attempt"],
            "label": card["label"],
            "status": card["status"],
            "ok": card["ok"],
            "mark": _MARKS[bool(card["ok"])],
            "state": "success" if card["ok"] else "error",
            "reply": card["reply"],
            "world": card["parsed"],
            "error": card["error"],
        })
    return out


# ---------------------------------------------------------------------------
# The flow: Image ↓ World ↓ Simulator
# ---------------------------------------------------------------------------

def flow_stages(
    *,
    has_image: bool,
    world_ok: bool,
    loaded: bool,
    image_detail: str = "",
    world_detail: str = "",
    sim_detail: str = "",
) -> list[dict]:
    """The flow's three stages, from the real state of each one.

    A stage is ``done`` when the thing itself happened, ``active`` when it is the
    next piece of real work, ``pending`` after that.  ``has_image``, ``world_ok``
    and ``loaded`` are facts the caller reads off the pipeline — an image in
    hand, a reading that passed all three checks, a world that is the active map.
    Lateness is enforced (a stage cannot be done while an earlier one is not), so
    the diagram can never claim the simulator holds a world that was never read.
    """
    image_done = bool(has_image)
    world_done = image_done and bool(world_ok)
    sim_done = world_done and bool(loaded)
    done = (image_done, world_done, sim_done)

    defaults = (
        (image_detail or "image in hand", "waiting for an image"),
        (world_detail or "reading passed all three checks",
         "no reading has passed validation yet"),
        (sim_detail or "this world is the active map",
         "load the validated world to finish"),
    )

    stages: list[dict] = []
    for index, (key, label) in enumerate(zip(_STAGE_KEYS, STAGES)):
        is_done = done[index]
        is_active = not is_done and all(done[:index])
        state = "done" if is_done else ("active" if is_active else "pending")
        detail = defaults[index][0] if is_done else defaults[index][1]
        stages.append({
            "key": key,
            "label": label,
            "state": state,
            "mark": _STAGE_MARKS[state],
            "chip_state": _STAGE_STATES[state],
            "done": is_done,
            "detail": detail,
        })
    return stages


# ---------------------------------------------------------------------------
# A sample map image — drawn in the terms the vision prompt describes
# ---------------------------------------------------------------------------

def sample_image_bytes(
    world: dict,
    cell: int = 56,
    margin: int = 26,
) -> bytes | None:
    """A PNG of *world*, drawn the way ``build_map_prompt`` describes a maze.

    ``R`` with a direction arrow, ``G`` for the goal, dark cells marked ``X`` for
    walls — so the built-in sample is a real raster image that a real vision call
    can read, and dry mode has something to show without a photo.  This is a
    drawing of a world, not a photograph, and the UI says so.

    Returns the PNG bytes, or ``None`` when Pillow is unavailable.
    """
    try:  # Pillow ships with Streamlit; the lab still works without it.
        from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415
    except ImportError:  # pragma: no cover - depends on environment
        return None

    from gemmabot.config import SIZE  # noqa: PLC0415

    side = margin * 2 + cell * SIZE
    image = Image.new("RGB", (side, side), (244, 245, 247))
    draw = ImageDraw.Draw(image)

    def _font(size: int):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:  # pragma: no cover - older Pillow
            return ImageFont.load_default()

    glyph_font = _font(int(cell * 0.62))

    def _cell(value: Any, fallback: tuple[int, int]) -> tuple[int, int]:
        """A drawable cell, or *fallback* when the value is not one."""
        if (isinstance(value, (list, tuple)) and len(value) == 2
                and all(isinstance(v, int) and 0 <= v < SIZE for v in value)):
            return (int(value[0]), int(value[1]))
        return fallback

    def _in_grid(value: Any) -> bool:
        return (isinstance(value, (list, tuple)) and len(value) == 2
                and all(isinstance(v, int) for v in value)
                and 0 <= value[0] < SIZE and 0 <= value[1] < SIZE)

    walls = {tuple(w) for w in (world.get("walls") or []) if _in_grid(w)}
    robot = _cell(world.get("robot"), (0, 0))
    goal = _cell(world.get("goal"), (SIZE - 1, SIZE - 1))
    heading = world.get("dir") if world.get("dir") in _DIR_ARROWS else "E"

    for y in range(SIZE):
        for x in range(SIZE):
            left, top = margin + x * cell, margin + y * cell
            right, bottom = left + cell, top + cell
            fill = (255, 255, 255)
            if (x, y) in walls:
                fill = (43, 46, 53)          # dark filled cell
            elif (x, y) == goal:
                fill = (223, 245, 234)
            elif (x, y) == robot:
                fill = (226, 238, 255)
            draw.rectangle([left, top, right, bottom], fill=fill,
                           outline=(190, 194, 202), width=1)

            centre = (left + cell / 2, top + cell / 2)
            if (x, y) in walls:
                draw.text(centre, "X", font=glyph_font, fill=(150, 154, 162),
                          anchor="mm")
            elif (x, y) == goal:
                draw.text(centre, "G", font=glyph_font, fill=(24, 120, 78),
                          anchor="mm")
            elif (x, y) == robot:
                draw.text(centre, "R", font=glyph_font, fill=(30, 84, 170),
                          anchor="mm")

    # Direction arrow inside the robot's cell — the heading the prompt asks for.
    left, top = margin + robot[0] * cell, margin + robot[1] * cell
    cx, cy = left + cell / 2, top + cell / 2
    reach = cell * 0.34
    tips = {
        "N": ((cx, cy - reach * 0.1), (cx - reach * 0.62, cy + reach * 0.62),
              (cx + reach * 0.62, cy + reach * 0.62)),
        "S": ((cx, cy + reach * 0.1), (cx - reach * 0.62, cy - reach * 0.62),
              (cx + reach * 0.62, cy - reach * 0.62)),
        "E": ((cx + reach * 0.1, cy), (cx - reach * 0.62, cy - reach * 0.62),
              (cx - reach * 0.62, cy + reach * 0.62)),
        "W": ((cx - reach * 0.1, cy), (cx + reach * 0.62, cy - reach * 0.62),
              (cx + reach * 0.62, cy + reach * 0.62)),
    }
    draw.polygon(tips[heading], fill=(30, 84, 170))

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def _meta_line(field_id: str, label: str, value: str) -> str:
    """One ``label value`` pair for the panel meta lines."""
    return (
        f"<span data-meta='{_e(field_id)}' style='white-space:nowrap'>"
        f"{_e(label)} "
        f"<span style='color:{C.TELEMETRY_VALUE}'>{_e(value)}</span></span>"
    )


def meta_html(
    reader: str,
    *,
    attempts: int = 0,
    max_tries: int = 0,
    latency: float | None = None,
    scripted: bool = False,
) -> str:
    """One line describing the reading run (escaped, token-styled)."""
    latency_label = f"{latency:.2f} s" if latency is not None else "—"
    bits = [
        _meta_line("reader", "Reader", reader),
        _meta_line("attempts", "attempts", f"{int(attempts)} / {int(max_tries)}"),
        _meta_line("latency", "latency", latency_label),
    ]
    if scripted:
        bits.append(
            f"<span data-meta='scripted' style='color:{C.WARNING}'>"
            "scripted replies — the image is not sent to a model</span>"
        )
    return (
        f"<div class='gb-vision-meta' style='font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_SM}px;color:{C.TEXT_SECONDARY};display:flex;"
        f"flex-wrap:wrap;gap:{S.px(S.XS)} {S.px(S.MD)};"
        f"margin-bottom:{S.px(S.MD)}'>" + "".join(bits) + "</div>"
    )


def checks_html(rows: list[dict]) -> str:
    """The validation list: ✓ Valid · ✓ Inside bounds · ✓ Reachable."""
    out: list[str] = []
    for row in rows:
        color = _STATE_COLORS[row["state"]]
        out.append(
            f"<div data-check='{_e(row['id'])}' "
            f"data-ok='{str(row['ok']).lower()}' "
            f"style='display:flex;align-items:baseline;gap:{S.px(S.SM)};"
            f"padding:{S.px(S.XS)} 0;border-bottom:1px solid {C.BORDER_SUBTLE}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
            f"color:{color};flex-shrink:0;width:{S.px(S.MD)};text-align:center'>"
            f"{row['mark']}</span>"
            f"<span style='font-family:{T.FONT_SANS};font-size:{T.SIZE_BASE}px;"
            f"color:{C.TEXT_PRIMARY};white-space:nowrap'>{_e(row['label'])}</span>"
            f"<span style='margin-left:auto;font-family:{T.FONT_MONO};"
            f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};text-align:right'>"
            f"{_e(row['detail'])}</span>"
            f"</div>"
        )
    return "".join(out)


def facts_html(rows: list[dict]) -> str:
    """The readout grid — robot / goal / walls / direction, or image metadata."""
    return fact_cards(rows, css_class="gb-vision-fact", column_min=132)


def readings_html(items: list[dict]) -> str:
    """The Gemma Vision column: what each reading returned and how it was judged.

    The reply is shown verbatim (escaped) — it is the model's own output — with
    the parsed JSON under it and the validator's verdict on that reading.
    """
    if not items:
        return empty_state(
            "No reading has been attempted yet.",
            "Read map asks Gemma Vision to turn the image into a world model.",
        )

    blocks: list[str] = []
    for item in items:
        state_color = _STATE_COLORS[item["state"]]
        parsed = item.get("world")
        parsed_text = (
            short_json(parsed) if parsed is not None else "no JSON object found"
        )
        world_block = (
            f"<div style='margin-top:{S.px(S.SM)}'>"
            f"{DS.section_title('World it proposed')}"
            f"<pre style='background:{C.BG_ELEVATED};"
            f"border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_SM)};padding:{S.px(S.SM)};"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_SECONDARY};white-space:pre-wrap;"
            f"word-break:break-word;margin:0'>{_e(parsed_text)}</pre></div>"
            if parsed is not None else ""
        )
        reply_block = (
            f"<div style='margin-top:{S.px(S.SM)}'>"
            f"{DS.section_title('Reply')}"
            f"<pre style='background:{C.BG_ELEVATED};"
            f"border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_SM)};padding:{S.px(S.SM)};"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_PRIMARY};white-space:pre-wrap;word-break:break-word;"
            f"margin:0'>{_e(item['reply'])}</pre></div>"
        )
        verdict = (
            "✓ validator accepted this reading" if item["ok"]
            else f"✕ {_e(item['error'] or 'rejected')}"
        )
        blocks.append(
            f"<div class='gb-vision-reading' data-attempt='{item['attempt']}' "
            f"data-ok='{str(item['ok']).lower()}' "
            f"style='margin-bottom:{S.px(S.LG)}'>"
            f"<div style='display:flex;align-items:center;gap:{S.px(S.SM)};"
            f"margin-bottom:{S.px(S.SM)}'>"
            f"{DS.status_chip(item['label'] + ' · ' + item['status'], item['state'])}"
            f"<span style='margin-left:auto;font-family:{T.FONT_MONO};"
            f"font-size:{T.SIZE_XS}px;color:{state_color};text-align:right'>"
            f"{verdict}</span></div>"
            f"{reply_block}{world_block}</div>"
        )
    return "".join(blocks)


def flow_html(stages: list[dict]) -> str:
    """The animated Image ↓ World ↓ Simulator diagram.

    Vertical, because that is the direction information travels: the image is
    read into a world, and the world is loaded into the simulator.  Each stage
    fades in on a staggered delay and the active one pulses, so the sequence
    reads as a pipeline moving downward; the states themselves come from
    :func:`flow_stages`.
    """
    from frontend.components import animations as A  # noqa: PLC0415

    parts: list[str] = []
    for index, stage in enumerate(stages):
        delay = index * 120
        state = stage["state"]
        border = _STAGE_BORDERS[state]
        color = _STAGE_COLORS[state]
        pulse = (
            f"animation:{A.animation_pulse()};"
            if state == "active" else ""
        )
        parts.append(
            f"<div class='gb-vision-stage' data-stage='{_e(stage['key'])}' "
            f"data-state='{_e(state)}' style='display:flex;align-items:center;"
            f"gap:{S.px(S.SM)};padding:{S.px(S.SM)} {S.px(S.MD)};"
            f"background:{C.BG_SURFACE};border:1px solid {border};"
            f"border-radius:{S.px(S.RADIUS_MD)};"
            f"animation:{A.animation_fade_in(A.DURATION_MODERATE, delay)};"
            f"{pulse}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
            f"color:{color};flex-shrink:0;width:{S.px(S.MD)};text-align:center'>"
            f"{stage['mark']}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_PRIMARY};letter-spacing:{T.TRACKING_WIDE};"
            f"text-transform:uppercase;white-space:nowrap'>"
            f"{_e(stage['label'])}</span>"
            f"<span style='margin-left:auto;font-family:{T.FONT_MONO};"
            f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};text-align:right'>"
            f"{_e(stage['detail'])}</span>"
            f"</div>"
        )
        if index < len(stages) - 1:
            parts.append(
                f"<div class='gb-vision-arrow' "
                f"style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
                f"color:{C.TEXT_MUTED};text-align:center;"
                f"padding:{S.px(S.XS)} 0;"
                f"animation:{A.animation_fade_in(A.DURATION_MODERATE, delay + 60)}'>"
                f"↓</div>"
            )
    return (
        f"<div class='gb-vision-flow' style='display:flex;flex-direction:column'>"
        + "".join(parts) + "</div>"
    )


def column_html(kind: str, body: str) -> str:
    """Frame one lab column (``image`` / ``vision`` / ``world``) as a panel.

    Titleless on purpose: the three columns are headed by the same section titles
    the rest of the app uses, so the lab reads as one row of equals.
    """
    return DS.panel(f"<div data-column='{_e(kind)}'>{body}</div>")


def image_rows(
    *,
    name: str,
    size: int | None,
    mime: str,
    source: str,
) -> list[dict]:
    """Metadata readouts for the uploaded-image column."""
    return [
        {"id": "name", "label": "File", "value": name, "detail": source,
         "state": "neutral"},
        {"id": "size", "label": "Size", "value": _bytes_label(size),
         "detail": "bytes on disk", "state": "neutral"},
        {"id": "type", "label": "Type", "value": mime, "detail": "media type",
         "state": "neutral"},
    ]
