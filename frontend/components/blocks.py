"""Design system: shared HTML blocks.

Owner: FRONTEND.  No Streamlit import, no network, no AI.

These blocks had grown a copy per panel: five ``_e`` helpers, three ``_plural``
helpers, four fact-card grids that differed only in a class name and a column
width, and six empty states written six ways.  They live here once, so a readout
looks the same in the Safety Lab, the Vision Lab, Replay and the Benchmark Lab —
and so the styling is a class the theme owns instead of an inline style each
panel repeats.  A panel keeps its own class name (``gb-safety-fact`` and friends)
purely as a hook for its own layout and tests.

Public surface
--------------
escape(value)                    -> str — HTML-escaped text, always
plural(count, noun)              -> str — ``1 action`` / ``6 actions``
sub_title(text)                  -> str — small caps label above a block
shell(body)                      -> str — the surface a panel's sections sit on
empty_state(title, hint, dense)  -> str — what a panel shows before it has data
fact_cards(rows, ...)            -> str — the readout cards every panel uses
scroll_x(body, min_width)        -> str — a dense table that scrolls instead of
                                          overflowing a narrow window
"""
from __future__ import annotations

import html as _html

from frontend.components import colors as C
from frontend.components import spacing as S

# States a readout can carry, in the order the theme colours them.
STATES: tuple[str, ...] = (
    "success", "warning", "error", "running", "thinking", "neutral",
)


def escape(value: object) -> str:
    """HTML-escape any value.  Everything a panel prints goes through this."""
    return _html.escape(str(value))


def plural(count: int, noun: str) -> str:
    """``1 action`` / ``6 actions`` — used for every count in the UI."""
    count = int(count)
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def sub_title(text: str) -> str:
    """A small-caps label introducing the block under it."""
    return f"<div class='gb-sub-title'>{escape(text)}</div>"


def shell(body: str) -> str:
    """The surface a panel's sections sit on (distinct from the outer panel)."""
    return f"<div class='gb-shell'>{body}</div>"


def empty_state(title: str, hint: str = "", *, dense: bool = False) -> str:
    """What a panel shows when it has nothing to show.

    One wording rule for the whole app: say what is missing, then what would
    produce it.  *dense* drops the border and the padding for the sidebar, where
    space is tight but the reader still deserves the same answer.
    """
    hint_html = (
        f"<div class='gb-empty-hint'>{escape(hint)}</div>" if hint else ""
    )
    css_class = "gb-empty gb-empty-dense" if dense else "gb-empty"
    return (
        f"<div class='{css_class}'>"
        f"<div class='gb-empty-title'>{escape(title)}</div>"
        f"{hint_html}</div>"
    )


def fact_cards(
    rows: list[dict] | None,
    *,
    css_class: str,
    column_min: int = 160,
    value_size: int | None = None,
) -> str:
    """The readout cards: label, value, detail, one per row.

    *rows* is the shape every panel already builds —
    ``{"id", "label", "value", "detail", "state"}``.  The value's colour comes
    from ``data-state`` through the theme, so ``success`` means the same colour
    in all four panels; *value_size* is the one legitimate difference between
    them (a benchmark headline reads larger than a per-run readout).

    Every card carries ``data-fact``, ``data-value`` and a ``title`` tooltip, so
    a truncated detail can still be read on hover.
    """
    cards: list[str] = []
    size_attr = (
        f" style='--gb-fact-value-size:{int(value_size)}px'" if value_size else ""
    )
    for row in rows or []:
        state = row.get("state", "neutral")
        detail = row.get("detail") or ""
        title = f"{row.get('label', '')}: {row.get('value', '')}"
        if detail:
            title = f"{title} — {detail}"
        cards.append(
            f"<div class='gb-fact {escape(css_class)}' "
            f"data-fact='{escape(row.get('id', ''))}' "
            f"data-value='{escape(row.get('value', ''))}' "
            f"data-state='{escape(state if state in STATES else 'neutral')}' "
            f"title='{escape(title)}'"
            f"{size_attr}>"
            f"<span class='gb-fact-label'>{escape(row.get('label', ''))}</span>"
            f"<span class='gb-fact-value'>{escape(row.get('value', ''))}</span>"
            f"<span class='gb-fact-detail'>{escape(detail)}</span>"
            f"</div>"
        )
    return (
        f"<div class='gb-fact-grid' style='grid-template-columns:"
        f"repeat(auto-fit,minmax({S.px(column_min)},1fr))'>"
        + "".join(cards) + "</div>"
    )


def scroll_x(body: str, *, min_width: int = 720) -> str:
    """A dense table that scrolls sideways instead of breaking the layout.

    *min_width* keeps the columns at a readable size: below it the reader
    scrolls the table, rather than the app squeezing eight columns into a phone
    and ellipsing every one of them.
    """
    return (
        f"<div class='gb-scroll-x'>"
        f"<div style='min-width:{S.px(min_width)}'>{body}</div>"
        f"</div>"
    )


def state_color(state: str) -> str:
    """The token colour for a state — for callers that need it in Python."""
    return {
        "success": C.SUCCESS,
        "warning": C.WARNING,
        "error": C.ERROR,
        "running": C.RUNNING,
        "thinking": C.THINKING,
        "neutral": C.TEXT_SECONDARY,
    }.get(state, C.TEXT_SECONDARY)
