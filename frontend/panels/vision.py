"""Vision Lab — a hand-drawn environment becomes a validated, executable world.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

The product story the lab tells, in order:

    Hand-drawn environment
        ↓
    Vision model
        ↓
    World representation
        ↓
    Deterministic validation
        ↓
    Simulation
        ↓
    Robot execution

Left is the image, the middle is the world that was read out of it, the right is
the validator's five checks, and loading a validated world into Mission is what
finishes the story.  The model never decides anything: it proposes a world, and
``map_vision.check_world_report`` accepts or refuses it in code.

What is real here
-----------------
The reading, the validation and the load.  ``map_vision.read_map`` makes the
call and parses the reply; each verdict is ``map_vision.check_world_report``'s
(✓ 8×8 bounds · ✓ Robot valid · ✓ Goal valid · ✓ No overlaps · ✓ Reachable); the
sentence under ✕ WORLD REJECTED is that report's own ``reason``, unedited; and
the world that reaches the simulator is the very one the validator was shown.
Every stage of the story is driven by state rather than by a timer: a stage is
lit because the thing itself happened — an image is in hand, a reply came back, a
world was parsed, all five checks passed, that world is the active map, a plan
has run on it.

Honesty rules, enforced here rather than trusted
------------------------------------------------
* **No live-accuracy claim without a live request.**  The reader's status says
  *scripted — no image left this app* only when the reply really was scripted,
  and *live request* only when a real model call was made.  Neither is inferred
  from the outcome of the reading.
* **The verdict is the validator's.**  :func:`world_verdict` reads the same
  report the checklist is drawn from, so ✕ WORLD REJECTED can never disagree
  with the rows under it, and an unproven check is never a tick.

Public surface
--------------
STORY / STAGES                      the six steps of the product story
COLUMN_TITLES                       headings for the three columns
REPLY_TITLE                         the expander that holds the raw reply
WORLD_CHECKS                        the validator's five checks
validation(world)                   the report, the rows and the verdict
checks(world)                       the five verdict rows for a proposed world
world_verdict(result)               ✓ WORLD ACCEPTED / ✕ WORLD REJECTED
world_rows(world)                   robot, heading, goal, walls
readings(history)                   one record per attempted reading
reader_status(...)                  what the reader really did, from real state
flow_stages(...)                    the story's per-stage state, from real facts
sample_image_bytes(world)           a PNG of a world, in the prompt's own terms
image_rows(...)                     metadata for the uploaded-image column
checks_html(rows)                   the validation list
verdict_html(decision)              the world verdict banner
facts_html(rows)                    the readout grid (world or image metadata)
readings_html(items)                the raw reply, the world it proposed, the verdict
flow_html(stages)                   the animated six-step story diagram
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

# ── The product story the lab tells, in order ────────────────────────────────
STORY: tuple[str, ...] = (
    "Hand-drawn environment",
    "Vision model",
    "World representation",
    "Deterministic validation",
    "Simulation",
    "Robot execution",
)

# The flow diagram's stages — the same six steps, in the same order.  ``STAGES``
# is kept as the name the rest of the app and the tests already read.
STAGES: tuple[str, ...] = STORY

# Headings for the three columns, left to right.
COLUMN_TITLES: dict[str, str] = {
    "image": "Input image",
    "world": "Detected world",
    "validation": "Validation",
}

# The expander that holds the model's own reply and the world it proposed.
REPLY_TITLE: str = "Gemma Vision"

# What the button that finishes the story says.
LOAD_LABEL: str = "Load into Mission"

_STAGE_KEYS: tuple[str, ...] = (
    "image", "vision", "world", "validation", "simulation", "execution",
)

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
# Validation — the five verdicts, straight from the validator
# ---------------------------------------------------------------------------

def _row(check: dict) -> dict:
    """One validator check record as a display row."""
    ok = check["ok"]
    return {
        "id": check["id"],
        "label": check["label"],
        "ok": ok,
        "mark": _MARKS[ok],
        "state": _MARK_STATES[ok],
        "detail": check["detail"],
        "data": check.get("data") or {},
        "passed": ok is True,
    }


def validation(world: dict | None) -> dict:
    """The whole validation of a proposed world: rows, reason and verdict.

    One call, one source.  The rows, the sentence under ✕ WORLD REJECTED and the
    banner's own state all come from this dict, so they cannot disagree: the
    reason is ``check_world_report``'s ``reason`` verbatim — the first problem it
    found, in its own words.

    ``world=None`` means no reading has passed validation yet, which is a
    different statement from a failed check:
    ``{"rows": [...], "reason": "", "ok": None, "evaluated": False}``.
    """
    if not isinstance(world, dict):
        return {
            "rows": [
                {
                    "id": check_id, "label": label, "ok": None,
                    "mark": _MARKS[None], "state": "neutral",
                    "detail": "no reading to check yet", "data": {}, "passed": False,
                }
                for check_id, label in WORLD_CHECKS
            ],
            "reason": "",
            "ok": None,
            "evaluated": False,
        }

    report = check_world_report(world)
    return {
        "rows": [_row(check) for check in report["checks"]],
        "reason": report["reason"],
        "ok": report["ok"],
        "evaluated": True,
    }


def checks(world: dict | None) -> list[dict]:
    """The five validation verdicts for a proposed world.

    Straight from ``map_vision.check_world_report``.  A check the validator could
    not evaluate is ``ok=None`` and is reported as unproven ("–") with the reason
    it could not be asked — never as a pass.  ``world=None`` means no reading has
    passed validation yet, which is a different statement from a failed check.
    """
    return validation(world)["rows"]


def world_verdict(result: dict) -> dict:
    """✓ WORLD ACCEPTED / ✕ WORLD REJECTED / NOT VALIDATED.

    Read off :func:`validation`.  REJECTED carries ``reason`` — the validator's
    own first problem, unedited — which is what the panel prints as the exact
    deterministic cause.  A reading that was never evaluated is not a rejection:
    nothing was refused, because nothing was checked.
    """
    rows = result["rows"]
    failing = [row for row in rows if row["ok"] is False]
    if failing:
        return {
            "key": "rejected",
            "label": "✕ WORLD REJECTED",
            "state": "error",
            "reason": result["reason"],
            "check": failing[0]["id"],
            "check_label": failing[0]["label"],
            "detail": f"refused by the {failing[0]['label'].lower()} check",
        }
    if result["ok"] is True:
        return {
            "key": "accepted",
            "label": "✓ WORLD ACCEPTED",
            "state": "success",
            "reason": "",
            "check": "",
            "check_label": "",
            "detail": f"all {len(rows)} checks passed — this world may be loaded",
        }
    if not result["evaluated"]:
        return {
            "key": "none",
            "label": "NOT VALIDATED",
            "state": "neutral",
            "reason": "",
            "check": "",
            "check_label": "",
            "detail": "no reading has been validated yet",
        }
    return {
        "key": "unproven",
        "label": "✕ NOT PROVEN",
        "state": "error",
        "reason": result["reason"],
        "check": "",
        "check_label": "",
        "detail": "the validator could not prove every check — nothing was accepted",
    }


def world_rows(world: dict | None) -> list[dict]:
    """The four things the detected world displays: robot, heading, goal, walls.

    Values are the world's own; nothing is inferred.  With no validated reading
    yet every row says so instead of showing a default map's numbers.  The grid
    coordinates are the map itself — ``world_grid_html`` labels both axes.
    """
    if not isinstance(world, dict):
        return [
            {"id": key, "label": label, "value": "—", "detail": "not read yet",
             "state": "neutral"}
            for key, label in (
                ("robot", "Robot"), ("heading", "Heading"),
                ("goal", "Goal"), ("walls", "Walls"),
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
            "id": "heading", "label": "Heading",
            "value": f"{heading} {arrow}".strip(),
            "detail": "from the robot's own arrow", "state": "neutral",
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
    replied: bool = False,
    parsed: bool = False,
    world_ok: bool,
    loaded: bool,
    executed: bool = False,
    image_detail: str = "",
    vision_detail: str = "",
    world_detail: str = "",
    validation_detail: str = "",
    sim_detail: str = "",
    execution_detail: str = "",
) -> list[dict]:
    """The story's six stages, from the real state of each one.

    A stage is ``done`` when the thing itself happened, ``active`` when it is the
    next piece of real work, ``pending`` after that.  Every argument is a fact
    the caller reads off the pipeline — an image in hand, a reply that came back,
    a world that was parsed out of it, a reading that passed all five checks, a
    world that is the active map, a plan that actually ran on it.  Lateness is
    enforced (a stage cannot be done while an earlier one is not), so the diagram
    can never claim the robot executed a plan on a world that was never read.
    """
    image_done = bool(has_image)
    vision_done = image_done and bool(replied)
    world_done = vision_done and bool(parsed)
    validation_done = world_done and bool(world_ok)
    sim_done = validation_done and bool(loaded)
    execution_done = sim_done and bool(executed)
    done = (image_done, vision_done, world_done, validation_done, sim_done,
            execution_done)

    defaults = (
        (image_detail or "image in hand", "waiting for an image"),
        (vision_detail or "the model answered", "no request has been made yet"),
        (world_detail or "a world was parsed from the reply",
         "no world has been parsed yet"),
        (validation_detail or "reading passed all five checks",
         "no reading has passed validation yet"),
        (sim_detail or "this world is the active map",
         "load the validated world to finish"),
        (execution_detail or "a plan ran on this world",
         "run a plan in Mission to finish"),
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


# What the reader really did, in three states.  "none" means no request has been
# made at all, which is not the same claim as a request that came back scripted.
REQUEST_KINDS: tuple[str, ...] = ("none", "scripted", "live")
_REQUEST_LABELS: dict[str, str] = {
    "none": "no request yet — the image has not been read",
    "scripted": "scripted reader — no image left this app, so this is not a "
                "live vision result",
    "live": "live vision request — a real model call was made for this reading",
}
_REQUEST_STATES: dict[str, str] = {
    "none": "neutral", "scripted": "warning", "live": "success",
}


def request_kind(*, ran: bool, backend: str | None, dry_backend: str | None) -> str:
    """``none`` / ``scripted`` / ``live`` — from the run that really happened.

    A live claim requires both a reading that ran and a backend that is not the
    dry reader; anything else is scripted or has not happened yet.  ``dry_backend``
    is the caller's own name for the scripted reader, passed in rather than
    imported so this module stays UI-only.
    """
    if not ran:
        return "none"
    return "scripted" if dry_backend is not None and backend == dry_backend else "live"


def reader_status(kind: str) -> dict:
    """The model/backend status line's verdict, from real runtime state."""
    kind = kind if kind in REQUEST_KINDS else "none"
    return {
        "kind": kind,
        "label": _REQUEST_LABELS[kind],
        "state": _REQUEST_STATES[kind],
        "live": kind == "live",
    }


def meta_html(
    reader: str,
    *,
    attempts: int = 0,
    max_tries: int = 0,
    latency: float | None = None,
    scripted: bool = False,
    request: str | None = None,
) -> str:
    """One line describing the reading run (escaped, token-styled).

    ``request`` is the honest status of this reading — ``none`` / ``scripted`` /
    ``live``; it is derived by :func:`request_kind` from the run that happened,
    never from whether the reading was a good one.  ``scripted`` is kept as the
    older boolean flag and is honoured when ``request`` is not given.
    """
    kind = request if request in REQUEST_KINDS else (
        "scripted" if scripted else "live"
    )
    status = reader_status(kind)
    latency_label = f"{latency:.2f} s" if latency is not None else "—"
    bits = [
        _meta_line("reader", "Reader", reader),
        _meta_line("attempts", "attempts", f"{int(attempts)} / {int(max_tries)}"),
        _meta_line("latency", "latency", latency_label),
        f"<span data-meta='request' data-kind='{_e(status['kind'])}' "
        f"style='color:{_STATE_COLORS[status['state']]}'>{_e(status['label'])}</span>",
    ]
    return (
        f"<div class='gb-vision-meta' style='font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_SM}px;color:{C.TEXT_SECONDARY};display:flex;"
        f"flex-wrap:wrap;gap:{S.px(S.XS)} {S.px(S.MD)};"
        f"margin-bottom:{S.px(S.MD)}'>" + "".join(bits) + "</div>"
    )


def verdict_html(decision: dict) -> str:
    """The world verdict banner: ✓ WORLD ACCEPTED / ✕ WORLD REJECTED + the cause.

    REJECTED always carries the validator's own ``reason`` — the exact
    deterministic problem — and never a paraphrase.
    """
    reason = decision.get("reason") or ""
    cause = (
        f"<div class='gb-vision-reason' data-check='{_e(decision.get('check', ''))}'>"
        f"{_e(reason)}</div>"
        if reason else ""
    )
    return (
        f"<div class='gb-vision-verdict' data-verdict='{_e(decision['key'])}' "
        f"title='{_e(decision.get('detail', ''))}'>"
        f"<span class='gb-vision-verdict-label'>{_e(decision['label'])}</span>"
        f"<span class='gb-vision-verdict-detail'>{_e(decision.get('detail', ''))}</span>"
        f"</div>" + cause
    )


def checks_html(rows: list[dict]) -> str:
    """The validation list: the five checks, each with its own verdict."""
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
