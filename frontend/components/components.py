"""
Design system: Component library
All 8 components return HTML strings consumed via st.markdown(unsafe_allow_html=True).
No Streamlit import here — pure Python functions, fully testable.

Components
----------
card(body, *, title)            — surface container with optional header
panel(body, *, title)           — heavier elevated container
badge(text, state)              — inline semantic label
status_chip(text, state)        — animated state indicator with dot
section_title(text)             — all-caps monospace section header with rule
divider()                       — hairline horizontal rule
action_list(actions)            — monospace step-by-step action log
metric_card(label, value, unit) — telemetry readout card

States: "success" | "warning" | "error" | "running" | "thinking" | "neutral"
"""
from __future__ import annotations

import html as _html
from typing import Literal

from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.components import animations as A

State = Literal["success", "warning", "error", "running", "thinking", "neutral"]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _e(text: object) -> str:
    """HTML-escape any value to a safe string."""
    return _html.escape(str(text))


def _state_colors(state: State) -> tuple[str, str, str]:
    """Return (background, border, foreground) for a given state."""
    return {
        "success":  (C.SUCCESS_BG,  C.SUCCESS_BORDER,  C.SUCCESS),
        "warning":  (C.WARNING_BG,  C.WARNING_BORDER,  C.WARNING),
        "error":    (C.ERROR_BG,    C.ERROR_BORDER,    C.ERROR),
        "running":  (C.RUNNING_BG,  C.RUNNING_BORDER,  C.RUNNING),
        "thinking": (C.THINKING_BG, C.THINKING_BORDER, C.THINKING),
        "neutral":  (C.BG_ELEVATED, C.BORDER_DEFAULT,  C.TEXT_SECONDARY),
    }.get(state, (C.BG_ELEVATED, C.BORDER_DEFAULT, C.TEXT_SECONDARY))


def _dot_class(state: State) -> str:
    valid = {"success", "warning", "error", "running", "thinking"}
    return f"gb-dot gb-dot-{state}" if state in valid else "gb-dot gb-dot-neutral"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Card
# ─────────────────────────────────────────────────────────────────────────────

def card(body: str, *, title: str = "") -> str:
    """Surfaced container. body is raw HTML. title is plain text."""
    header = ""
    if title:
        header = (
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"font-weight:{T.WEIGHT_SEMIBOLD};color:{C.TEXT_MUTED};"
            f"letter-spacing:{T.TRACKING_WIDE};text-transform:uppercase;"
            f"margin-bottom:{S.px(S.SM)}'>{_e(title)}</div>"
        )
    return f"<div class='gb-card'>{header}{body}</div>"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Panel
# ─────────────────────────────────────────────────────────────────────────────

def panel(body: str, *, title: str = "") -> str:
    """Elevated container, heavier than card. For major UI sections."""
    header = ""
    if title:
        header = (
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_MD}px;"
            f"font-weight:{T.WEIGHT_SEMIBOLD};color:{C.TEXT_PRIMARY};"
            f"letter-spacing:0.02em;margin-bottom:{S.px(S.LG)};border-bottom:"
            f"1px solid {C.BORDER_SUBTLE};padding-bottom:{S.px(S.SM)}'>"
            f"{_e(title)}</div>"
        )
    return f"<div class='gb-panel'>{header}{body}</div>"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Badge
# ─────────────────────────────────────────────────────────────────────────────

def badge(text: str, state: State = "neutral") -> str:
    """Inline semantic label. Use inside prose or table cells."""
    cls = f"gb-badge gb-badge-{state}"
    return f"<span class='{cls}'>{_e(text)}</span>"


# ─────────────────────────────────────────────────────────────────────────────
# 4. StatusChip
# ─────────────────────────────────────────────────────────────────────────────

def status_chip(text: str, state: State = "neutral") -> str:
    """Animated state indicator with a semantic dot. Use for run status."""
    bg, border, fg = _state_colors(state)
    dot = f"<span class='{_dot_class(state)}'></span>"
    return (
        f"<span class='gb-status-chip' style='"
        f"background-color:{bg};border-color:{border};color:{fg}'>"
        f"{dot}{_e(text)}</span>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. SectionTitle
# ─────────────────────────────────────────────────────────────────────────────

def section_title(text: str, *, icon: str = "") -> str:
    """All-caps monospace section header with a trailing hairline rule."""
    prefix = f"{_e(icon)}&nbsp;" if icon else ""
    return f"<div class='gb-section-title'>{prefix}{_e(text)}</div>"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Divider
# ─────────────────────────────────────────────────────────────────────────────

def divider() -> str:
    """Hairline horizontal rule using the BORDER_SUBTLE token."""
    return "<hr class='gb-divider'>"


# ─────────────────────────────────────────────────────────────────────────────
# 7. ActionList
# ─────────────────────────────────────────────────────────────────────────────

def action_list(actions: list[dict]) -> str:
    """Monospace step-by-step execution log.

    Each action dict must have:
        step    int     — 1-based step index
        action  dict    — {"cmd": str, "steps"?: int}
        message str     — simulator response string

    State is inferred from message: "blocked" → error, else success.
    """
    if not actions:
        return (
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED};padding:{S.px(S.XS)} 0'>"
            "no steps executed</div>"
        )

    rows = []
    for entry in actions:
        step    = entry.get("step", "?")
        action  = entry.get("action", {})
        message = str(entry.get("message", ""))
        cmd     = action.get("cmd", "?")
        detail  = f" ×{action['steps']}" if "steps" in action else ""
        blocked = message.startswith("blocked") or message.startswith("unknown")
        msg_color = C.ERROR if blocked else C.TEXT_MUTED
        state_dot = (
            f"<span class='gb-dot gb-dot-error' style='flex-shrink:0'></span>"
            if blocked else
            f"<span class='gb-dot gb-dot-success' style='flex-shrink:0'></span>"
        )
        rows.append(
            f"<div class='gb-action-row'>"
            f"{state_dot}"
            f"<span class='gb-action-index'>{_e(step)}</span>"
            f"<span class='gb-action-cmd'>{_e(cmd)}</span>"
            f"<span class='gb-action-detail'>{_e(detail)}</span>"
            f"<span class='gb-action-msg' style='color:{msg_color}'>"
            f"{_e(message)}</span>"
            f"</div>"
        )

    body = "".join(rows)
    return f"<div class='gb-action-list'>{body}</div>"


# ─────────────────────────────────────────────────────────────────────────────
# 8. MetricCard
# ─────────────────────────────────────────────────────────────────────────────

def metric_card(label: str, value: str, unit: str = "") -> str:
    """Single telemetry readout. label / value / optional unit suffix."""
    unit_span = (
        f"<span class='gb-metric-unit'>{_e(unit)}</span>" if unit else ""
    )
    return (
        f"<div class='gb-metric-card'>"
        f"<div class='gb-metric-label'>{_e(label)}</div>"
        f"<div class='gb-metric-value'>{_e(value)}{unit_span}</div>"
        f"</div>"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Composite: TelemetryRow (sidebar helper)
# ─────────────────────────────────────────────────────────────────────────────

def telemetry_row(key: str, value: str) -> str:
    """Single key/value pair for the sidebar telemetry block."""
    return (
        f"<div class='gb-telem-row'>"
        f"<span class='gb-telem-key'>{_e(key)}</span>"
        f"<span class='gb-telem-val'>{_e(value)}</span>"
        f"</div>"
    )


def telemetry_block(rows: list[tuple[str, str]]) -> str:
    """Render a sequence of (key, value) pairs as a telemetry block."""
    return "".join(telemetry_row(k, v) for k, v in rows)


# ─────────────────────────────────────────────────────────────────────────────
# Composite: AttemptCard (propose → verify loop)
# ─────────────────────────────────────────────────────────────────────────────

def attempt_card_html(card_data: dict) -> str:
    """Render one attempt record from ui_helpers.attempt_cards() as HTML.

    card_data shape:
        label, status ("OK"|"FAIL"), ok (bool),
        prompt (str), reply (str), feedback (str)
    """
    ok       = card_data.get("ok", False)
    state    = "success" if ok else "error"
    label    = card_data.get("label", "Attempt")
    status   = card_data.get("status", "FAIL")
    prompt   = card_data.get("prompt") or ""
    reply    = card_data.get("reply") or ""
    feedback = card_data.get("feedback") or ""

    chip = status_chip(status, state)
    bg, border, _ = _state_colors(state)

    prompt_block = (
        f"<div style='margin-top:{S.px(S.SM)}'>"
        f"{section_title('Prompt')}"
        f"<pre style='background:{C.BG_ELEVATED};border:1px solid {C.BORDER_SUBTLE};"
        f"border-radius:{S.px(S.RADIUS_SM)};padding:{S.px(S.SM)};font-size:{T.SIZE_SM}px;"
        f"font-family:{T.FONT_MONO};color:{C.TEXT_SECONDARY};white-space:pre-wrap;"
        f"word-break:break-word;margin:0'>{_e(prompt)}</pre></div>"
    )
    reply_block = (
        f"<div style='margin-top:{S.px(S.SM)}'>"
        f"{section_title('Model reply')}"
        f"<pre style='background:{C.BG_ELEVATED};border:1px solid {C.BORDER_SUBTLE};"
        f"border-radius:{S.px(S.RADIUS_SM)};padding:{S.px(S.SM)};font-size:{T.SIZE_SM}px;"
        f"font-family:{T.FONT_MONO};color:{C.TEXT_PRIMARY};white-space:pre-wrap;"
        f"word-break:break-word;margin:0'>{_e(reply)}</pre></div>"
    )
    verify_block = (
        f"<div style='margin-top:{S.px(S.SM)}'>"
        f"{section_title('Verification')}"
        f"<div style='background:{bg};border:1px solid {border};"
        f"border-radius:{S.px(S.RADIUS_SM)};padding:{S.px(S.SM)};font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_SM}px;color:{C.SUCCESS if ok else C.ERROR}'>"
        f"{'✓ Plan accepted — verified by dry_run' if ok else _e(feedback)}</div></div>"
    )

    header = (
        f"<div style='display:flex;align-items:center;gap:{S.px(S.SM)};margin-bottom:{S.px(S.SM)}'>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
        f"color:{C.TEXT_SECONDARY};letter-spacing:{T.TRACKING_WIDE}'>{_e(label)}</span>"
        f"{chip}</div>"
    )

    body = header + prompt_block + reply_block + verify_block
    return card(body)
