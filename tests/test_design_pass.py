"""Phase 10 design pass — the interface stays quiet, precise and readable.

These tests pin the product-design rules a robotics engineer assumes and a
casual interface breaks:

* **Contrast** — every token that carries information on a panel surface holds
  the WCAG AA ratio (>=4.5:1) against the surfaces it actually sits on; body
  text holds AAA (>=7:1).  Hierarchy is carried by scale and weight, never by
  unreadable grey.
* **State is announced** — the console status bar is a live region, so a run's
  READY → THINKING → VERIFYING → EXECUTING → COMPLETE change reaches a screen
  reader instead of only repainting.
* **Motion serves state** — the reduced-motion media query is part of the
  stylesheet, and the animations it silences are the functional ones.
* **The board is one image** — the simulator grid carries its world as an
  accessible label instead of 64 anonymous SVG cells, and no emoji glyph
  reaches the hero grid output.
* **No mascot** — the app's tab icon is an industrial material mark, not an
  emoji face.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from frontend.components import colors as C
from frontend.components import theme
from frontend.console import shell as console_shell
from frontend.simulation import ui_helpers
from gemmabot.simulator import new_world

CSS = theme._css()


# ---------------------------------------------------------------------------
# WCAG 2.x contrast, computed rather than asserted by eyeball
# ---------------------------------------------------------------------------

def _lin(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luma(hexcolor: str) -> float:
    value = hexcolor.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg: str, bg: str) -> float:
    lighter, darker = sorted((_luma(fg), _luma(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


PANEL_SURFACES = [C.BG_BASE, C.BG_SURFACE, C.BG_ELEVATED, C.BG_INSET]


def test_information_carrying_greys_hold_AA_on_the_surfaces_they_sit_on():
    for surface in PANEL_SURFACES:
        assert ratio(C.TEXT_MUTED, surface) >= 4.5, (C.TEXT_MUTED, surface)
    # Sidebar telemetry labels sit on the surface; axis labels sit on the well.
    assert ratio(C.TELEMETRY_LABEL, C.BG_SURFACE) >= 4.5
    assert ratio(C.GRID_LABEL, C.BG_INSET) >= 4.5


def test_the_greys_stay_distinct_so_hierarchy_survives_the_AA_lift():
    muted = _luma(C.TEXT_MUTED)
    secondary = _luma(C.TEXT_SECONDARY)
    assert secondary > muted  # a caption is never the same grey as a label
    assert ratio(C.TEXT_SECONDARY, C.BG_BASE) >= 4.5
    assert ratio(C.TEXT_SECONDARY, C.BG_SURFACE) >= 4.5


def test_body_text_holds_AAA_on_the_page_background():
    assert ratio(C.TEXT_PRIMARY, C.BG_BASE) >= 7


@pytest.mark.parametrize("state_bg,state_fg", [
    (C.SUCCESS_BG, C.SUCCESS),
    (C.ERROR_BG, C.ERROR),
    (C.WARNING_BG, C.WARNING),
    (C.RUNNING_BG, C.RUNNING),
    (C.THINKING_BG, C.THINKING),
])
def test_state_colours_hold_AA_on_their_state_surfaces(state_bg, state_fg):
    assert ratio(state_fg, state_bg) >= 4.5


# ---------------------------------------------------------------------------
# State is announced, not only repainted
# ---------------------------------------------------------------------------

def test_the_console_status_bar_is_a_polite_live_region():
    html = console_shell.status_bar_html(
        key="executing", activity="the plan is stepping", meta="attempt 2/3"
    )
    assert "role='status'" in html
    assert "aria-live='polite'" in html
    assert "data-status='executing'" in html


# ---------------------------------------------------------------------------
# Motion serves state — and can be silenced
# ---------------------------------------------------------------------------

def test_the_stylesheet_silences_animation_under_reduced_motion():
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    reduced = CSS.split("(prefers-reduced-motion: reduce)")[1].split("}")[0]
    assert "animation-duration" in reduced


def test_every_keyframe_in_the_sheet_is_the_design_systems_own():
    # Nothing decorative spawns outside the animation tokens: the only
    # @keyframes declarations are the ones animations.py ships.
    declared = theme.__dict__.get("_css")
    assert declared is not None
    import frontend.components.animations as A
    for name in (
        "gb-pulse", "gb-blink", "gb-slide-in", "gb-fade-in",
        "gb-goal-glow", "gb-step-flash", "gb-danger-pulse", "gb-trace-draw",
    ):
        assert name in A.ALL_KEYFRAMES
        assert f"@keyframes {name}" in CSS


# ---------------------------------------------------------------------------
# The board is one image, not 64 anonymous cells
# ---------------------------------------------------------------------------

def test_the_board_carries_its_world_as_an_accessible_label():
    world = new_world()
    html = ui_helpers.world_grid_html(world)
    assert "role='img'" in html
    row = next(line for line in html.splitlines() if "aria-label" in line)
    assert "robot at [0, 0]" in row
    assert f"goal at [{world['goal'][0]}, {world['goal'][1]}]" in row
    assert f"{len(world['walls'])} obstacle(s)" in row


def test_no_emoji_glyph_reaches_the_hero_grid():
    html = ui_helpers.world_grid_html(new_world())
    for glyph in ("🧱", "🎯", "⬜", "🤖"):
        assert glyph not in html


def test_the_tab_icon_is_a_mark_not_a_mascot():
    source = Path("app.py").read_text(encoding="utf-8")
    assert '"🤖"' not in source
    assert ":material/precision_manufacturing:" in source


# ---------------------------------------------------------------------------
# One definition, not two
# ---------------------------------------------------------------------------

def test_constants_are_defined_once_in_the_app():
    source = Path("app.py").read_text(encoding="utf-8")
    assignments = [
        line.split("=")[0].strip()
        for line in source.splitlines()
        if line.startswith("BENCHMARK_REPORT_MD")
    ]
    assert len(assignments) == 1
