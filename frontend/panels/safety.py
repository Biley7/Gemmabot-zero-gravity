"""Safety Lab — demonstrating the verifier and the repair loop.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

What is real here
-----------------
Everything except the dry-mode reply text.  The stage timeline is built from
the harness's own attempt records, each verdict is ``verify_plan``'s (including
the structured cell a plan was refused entry to), and each replay is the
simulator's own timeline for that plan — so the collision the lab shows is the
simulator blocking a real plan at a real cell, not an illustration.

In dry mode the *plans* are scripted (the same convention as
``python -m gemmabot.benchmark --dry``, see ``engine.dry_ask``): the first
reply walks into a wall, the second fixes it.  The harness loop, the verifier,
the collision and the replay are the real pipeline, and the UI labels the
planner as scripted.

Public surface
--------------
stages(world, history)     the event timeline: proposal / collision / repair / safe
summary(stages)            the four readouts: collision, error, repair, success
replays(world, history)    one real simulator timeline per attempted plan
report_html(stages, summ)  pipeline diagram + timeline chips + readouts + log
pipeline_html()            the loop's five stages, as a diagram
timeline_html(stages)      the chips: ✓ Proposal ✕ Collision ↻ Repair ✓ Safe
"""
from __future__ import annotations

from backend.verifier.harness import verify_plan
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
from frontend.simulation import player as playback

# ── The loop's shape (the pipeline diagram) ───────────────────────────────────
PIPELINE: tuple[str, ...] = (
    "Gemma Plan",
    "Verification",
    "Failure",
    "Repair",
    "New Plan",
)

# ── Stage kinds → what the timeline chip says ────────────────────────────────
# ``mark`` is the glyph the request asks for (✓ / ✕ / ↻), ``state`` is the
# design-system state the chip is coloured with.
_STAGE_STYLE: dict[str, tuple[str, str]] = {
    "proposal": ("✓", "neutral"),
    "collision": ("✕", "error"),
    "bounds": ("✕", "error"),
    "invalid": ("✕", "error"),
    "missed": ("✕", "warning"),
    "repair": ("↻", "warning"),
    "safe": ("✓", "success"),
}

_STAGE_LABELS: dict[str, str] = {
    "proposal": "Proposal",
    "collision": "Collision",
    "bounds": "Out of bounds",
    "invalid": "Invalid reply",
    "missed": "Goal missed",
    "repair": "Repair",
    "safe": "Safe",
}

# The kinds that mean "this attempt failed", and the subset that means a
# move was refused a cell.
_FAILURE_KINDS: tuple[str, ...] = ("collision", "bounds", "invalid", "missed")
_BLOCKED_KINDS: tuple[str, ...] = ("collision", "bounds")

# Which verifier check each failure kind comes from.
_CHECK_KIND: dict[str, str] = {
    "valid_actions": "invalid",
    "in_bounds": "bounds",
    "no_collisions": "collision",
    "goal_reachable": "missed",
}



def _cell_text(cell: list | None) -> str:
    """``[3, 0]`` for a coordinate pair, ``—`` when there is none."""
    if not cell:
        return "—"
    return f"[{int(cell[0])}, {int(cell[1])}]"




# ---------------------------------------------------------------------------
# The event timeline
# ---------------------------------------------------------------------------

def _stage(kind: str, attempt: int, **extra) -> dict:
    mark, state = _STAGE_STYLE[kind]
    stage = {
        "kind": kind,
        "label": _STAGE_LABELS[kind],
        "mark": mark,
        "state": state,
        "attempt": int(attempt),
        "detail": "",
        "error": None,
        "cell": None,
        "action_index": None,
        "actions_count": None,
        "prompt": None,
    }
    stage.update(extra)
    return stage


def stages(world: dict, history: list[dict] | None) -> list[dict]:
    """The event timeline for one run — one record per real event.

    Reads only what the harness and the verifier actually produced: the plans
    each attempt parsed, the verdict on each of them, and the prompt the loop
    sent next.  An attempt whose reply never parsed is a failed proposal with
    no verification, not an invented collision.
    """
    records = [r for r in (history or []) if isinstance(r, dict)]
    out: list[dict] = []

    for position, record in enumerate(records):
        attempt = int(record.get("attempt") or position + 1)
        feedback = str(record.get("feedback") or "no feedback")
        actions = record.get("actions")

        if not isinstance(actions, list) or not actions:
            # The proposal itself failed: nothing exists to verify.
            out.append(_stage(
                "invalid", attempt,
                label=_STAGE_LABELS["proposal"],
                detail="no plan could be parsed from this reply",
                error=feedback,
            ))
        else:
            count = len(actions)
            out.append(_stage(
                "proposal", attempt,
                detail=f"{_plural(count, 'action')} proposed",
                actions_count=count,
            ))
            verdict = verify_plan(world, actions)
            failing = next(
                (check for check in verdict["checks"] if check["ok"] is False), None
            )
            if failing is None:
                out.append(_stage(
                    "safe", attempt,
                    detail="plan accepted — all four checks passed",
                    actions_count=count,
                ))
            else:
                kind = _CHECK_KIND.get(failing["id"], "invalid")
                facts = failing.get("data") or {}
                out.append(_stage(
                    kind, attempt,
                    detail=failing["detail"],
                    error=feedback,
                    cell=facts.get("cell"),
                    action_index=facts.get("action_index"),
                    actions_count=count,
                ))

        # The loop only repairs when there is another attempt to make.
        following = records[position + 1] if position + 1 < len(records) else None
        if following is not None:
            out.append(_stage(
                "repair", attempt,
                detail="failure sent back to the planner as a repair prompt",
                prompt=str(following.get("prompt") or ""),
                error=feedback,
            ))

    return out


def summary(stage_list: list[dict]) -> dict:
    """The four readouts the lab displays, all read off the timeline."""
    failures = [s for s in stage_list if s["kind"] in _FAILURE_KINDS]
    collisions = [s for s in failures if s["kind"] in _BLOCKED_KINDS]
    repairs = [s for s in stage_list if s["kind"] == "repair"]
    safe = next((s for s in stage_list if s["kind"] == "safe"), None)
    proposals = [s for s in stage_list if s["kind"] == "proposal"]
    first_failure = failures[0] if failures else None
    first_hit = collisions[0] if collisions else None

    return {
        "collision": (
            {
                "cell": first_hit["cell"],
                "text": _cell_text(first_hit["cell"]),
                "attempt": first_hit["attempt"],
                "label": first_hit["label"],
            }
            if first_hit else None
        ),
        "error": (
            {
                "message": first_failure["detail"],
                "reason": first_failure["error"],
                "attempt": first_failure["attempt"],
            }
            if first_failure else None
        ),
        "repairs": {
            "count": len(repairs),
            "attempts": [s["attempt"] for s in repairs],
            "label": _plural(len(repairs), "repair") if repairs else "no repair",
        },
        "success": {
            "ok": safe is not None,
            "attempt": safe["attempt"] if safe else None,
            "label": f"Safe — accepted on attempt {safe['attempt']}" if safe
                     else "Not resolved within the repair budget",
        },
        "attempts": len(proposals),
        "failures": len(failures),
    }


def facts_rows(summary_data: dict) -> list[dict]:
    """The four requested readouts, display-ready: (label, value, detail, state)."""
    collision = summary_data.get("collision")
    error = summary_data.get("error")
    repairs = summary_data.get("repairs") or {}
    success = summary_data.get("success") or {}
    return [
        {
            "id": "collision",
            "label": "Collision location",
            "value": collision["text"] if collision else "none",
            "detail": (
                f"{collision['label'].lower()} on attempt {collision['attempt']}"
                if collision else "no plan was refused a cell"
            ),
            "state": "error" if collision else "success",
        },
        {
            "id": "error",
            "label": "Error",
            "value": (
                f"attempt {error['attempt']} rejected" if error else "none"
            ),
            "detail": error["message"] if error else "every plan verified",
            "state": "error" if error else "success",
        },
        {
            "id": "repair",
            "label": "Repair attempt",
            "value": repairs.get("label", "no repair"),
            "detail": (
                "failures sent back to the planner: "
                + ", ".join(str(a) for a in repairs.get("attempts", []))
                if repairs.get("count") else "the first plan verified"
            ),
            "state": "warning" if repairs.get("count") else "success",
        },
        {
            "id": "success",
            "label": "Success",
            "value": "✓ Safe" if success.get("ok") else "✕ Not resolved",
            "detail": success.get("label", ""),
            "state": "success" if success.get("ok") else "error",
        },
    ]


def replays(world: dict, history: list[dict] | None) -> list[dict]:
    """One real simulator timeline per attempted plan, in attempt order.

    The timeline is exactly the Phase 3 replay data: a rejected plan replays as
    the robot walking to the wall and being halted there.
    """
    out: list[dict] = []
    for position, record in enumerate(history or []):
        if not isinstance(record, dict):
            continue
        actions = record.get("actions")
        if not isinstance(actions, list) or not actions:
            continue
        attempt = int(record.get("attempt") or position + 1)
        accepted = bool(record.get("ok"))
        timeline = playback.build_timeline(world, actions)
        out.append({
            "attempt": attempt,
            "ok": accepted,
            "label": f"Attempt {attempt} — {'accepted' if accepted else 'rejected'}",
            "timeline": timeline,
            "halted": timeline["halted"],
            "reached": timeline["reached"],
            "steps": len(timeline["steps"]),
        })
    return out


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def pipeline_html() -> str:
    """The loop as a diagram: Gemma Plan → Verification → Failure → Repair → New Plan."""
    arrow = (
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
        f"color:{C.TEXT_MUTED};padding:0 {S.px(S.XS)}'>→</span>"
    )
    boxes = []
    for index, name in enumerate(PIPELINE):
        boxes.append(
            f"<div style='background:{C.BG_SURFACE};border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_MD)};padding:{S.px(S.SM)} {S.px(S.MD)};"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;color:{C.TEXT_SECONDARY};"
            f"letter-spacing:{T.TRACKING_WIDE};text-transform:uppercase;"
            f"white-space:nowrap'>{_e(name)}</div>"
        )
        if index < len(PIPELINE) - 1:
            boxes.append(arrow)
    return (
        f"<div class='gb-safety-pipeline' style='display:flex;align-items:center;"
        f"flex-wrap:wrap;gap:{S.px(S.XS)}'>" + "".join(boxes) + "</div>"
    )


def timeline_html(stage_list: list[dict]) -> str:
    """The visual timeline: one chip per event, joined by arrows."""
    if not stage_list:
        return (
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED}'>No safety check has run yet.</div>"
        )

    parts: list[str] = []
    arrow = (
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
        f"color:{C.TEXT_MUTED};padding:0 {S.px(S.XS)}'>→</span>"
    )
    for index, stage in enumerate(stage_list):
        label = f"{stage['mark']} {stage['label']}"
        if stage["kind"] != "repair":
            label += f" {stage['attempt']}"
        cell_attr = f" data-cell='{_e(_cell_text(stage['cell']))}'" if stage["cell"] else ""
        parts.append(
            f"<span class='gb-safety-chip' data-kind='{_e(stage['kind'])}' "
            f"data-attempt='{stage['attempt']}'{cell_attr}>"
            f"{DS.status_chip(label, stage['state'])}</span>"
        )
        if index < len(stage_list) - 1:
            parts.append(arrow)
    return (
        f"<div class='gb-safety-timeline' style='display:flex;align-items:center;"
        f"flex-wrap:wrap;gap:{S.px(S.XS)} {S.px(S.XS)}'>" + "".join(parts) + "</div>"
    )


def events_html(stage_list: list[dict]) -> str:
    """The event log: what each stage actually reported, in order."""
    rows = []
    for stage in stage_list:
        color = {
            "success": C.SUCCESS, "error": C.ERROR,
            "warning": C.WARNING, "neutral": C.TEXT_SECONDARY,
        }[stage["state"]]
        # Point at the refused cell; the action number is already spelled out
        # in the verifier's own sentence, so it is not repeated here.
        extra_bits = []
        if stage["cell"]:
            extra_bits.append(f"cell {_cell_text(stage['cell'])}")
        suffix = (
            f"<span style='color:{C.TEXT_MUTED};font-family:{T.FONT_MONO};"
            f"font-size:{T.SIZE_XS}px'> · {' · '.join(_e(b) for b in extra_bits)}</span>"
            if extra_bits else ""
        )
        rows.append(
            f"<div class='gb-safety-event' data-kind='{_e(stage['kind'])}' "
            f"data-attempt='{stage['attempt']}' "
            f"style='display:flex;align-items:baseline;gap:{S.px(S.SM)};"
            f"padding:{S.px(S.XS)} 0;border-bottom:1px solid {C.BORDER_SUBTLE}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_BASE}px;"
            f"color:{color};flex-shrink:0;width:{S.px(S.MD)};text-align:center'>"
            f"{stage['mark']}</span>"
            f"<span style='font-family:{T.FONT_SANS};font-size:{T.SIZE_BASE}px;"
            f"color:{C.TEXT_PRIMARY};white-space:nowrap'>"
            f"{_e(stage['label'])} {stage['attempt']}{suffix}</span>"
            f"<span style='margin-left:auto;font-family:{T.FONT_MONO};"
            f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};text-align:right'>"
            f"{_e(stage['detail'])}</span>"
            f"</div>"
        )
    return "".join(rows)


def facts_html(summary_data: dict) -> str:
    """The four readouts: collision location, error, repair attempt, success."""
    return fact_cards(
        facts_rows(summary_data), css_class="gb-safety-fact", column_min=190
    )


def meta_html(
    planner: str,
    instruction: str,
    attempts: int,
    latency: float | None,
) -> str:
    """One line describing the run the lab is showing (escaped, token-styled)."""
    latency_label = f"{latency:.2f} s" if latency is not None else "—"
    return (
        f"<div class='gb-safety-meta' style='font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_SM}px;color:{C.TEXT_SECONDARY};"
        f"margin:{S.px(S.SM)} 0 {S.px(S.MD)}'>"
        f"Planner <span style='color:{C.TELEMETRY_VALUE}'>{_e(planner)}</span> · "
        f"{int(attempts)} attempt(s) · "
        f"<span style='color:{C.TELEMETRY_VALUE}'>{_e(latency_label)}</span> · "
        f"instruction “{_e(instruction)}”</div>"
    )


def report_html(stage_list: list[dict], summary_data: dict) -> str:
    """Pipeline diagram, timeline chips, readouts and event log, in one panel."""
    body = (
        DS.section_title("Loop")
        + pipeline_html()
        + f"<div style='height:{S.px(S.LG)}'></div>"
        + DS.section_title("Safety timeline")
        + timeline_html(stage_list)
        + f"<div style='height:{S.px(S.LG)}'></div>"
        + facts_html(summary_data)
        + f"<div style='height:{S.px(S.LG)}'></div>"
        + DS.section_title("Events")
        + events_html(stage_list)
    )
    return DS.panel(body, title="Safety lab")
