"""Tests for frontend/components/theme.py — the one stylesheet.

The theme is the only place styling is allowed to live, so these tests check the
things a screenshot would: that keyboard focus is visible, that motion is
optional, that a narrow window does not push the page sideways, and that every
class the shared blocks emit is actually painted by a rule.
"""
import sys
import types

from frontend.components import blocks
from frontend.components import colors as C
from frontend.components import theme

CSS = theme._css()
# Whitespace-normalised, for assertions about a rule written across lines.
SPACED = " ".join(CSS.split())


# ---------------------------------------------------------------------------
# It has to be valid CSS first
# ---------------------------------------------------------------------------

def test_the_stylesheet_is_balanced_and_fully_rendered():
    assert CSS.count("{") == CSS.count("}")
    assert "{{" not in CSS and "}}" not in CSS
    assert CSS.strip().startswith("<style>")
    assert CSS.strip().endswith("</style>")


def test_the_streamlit_config_dict_points_at_the_same_palette():
    assert theme.STREAMLIT_THEME["primaryColor"] == C.ACCENT_BLUE
    assert theme.STREAMLIT_THEME["backgroundColor"] == C.BG_BASE
    assert theme.STREAMLIT_THEME["base"] == "dark"


# ---------------------------------------------------------------------------
# It has to actually reach the page, on every run
# ---------------------------------------------------------------------------

def test_the_stylesheet_is_emitted_on_every_run_not_once_per_process(monkeypatch):
    """A guard here used to delete the whole theme after the first rerun.

    Streamlit rebuilds the element tree from scratch on each run while this
    module stays in sys.modules, so "inject only once" means the second run —
    any button press — never sends the CSS, and a later session never sees it.
    """
    calls = []
    fake_streamlit = types.SimpleNamespace(
        markdown=lambda body, **kwargs: calls.append((body, kwargs))
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    theme.inject_theme()
    theme.inject_theme()

    assert len(calls) == 2, "the theme was skipped on a repeated call"
    assert calls[0][0] == CSS and calls[1][0] == CSS
    assert all(kwargs.get("unsafe_allow_html") for _, kwargs in calls)


# ---------------------------------------------------------------------------
# Focus: a keyboard user must be able to see where they are
# ---------------------------------------------------------------------------

def test_keyboard_focus_draws_a_ring_in_the_accent_colour():
    assert ":focus-visible" in CSS
    ring = CSS.split(":focus-visible")[1].split("}")[0]
    assert C.ACCENT_BLUE in ring
    assert "outline" in ring


def test_focus_is_not_stolen_from_pointer_users():
    """Clicking an input moves its border, not a ring: only keys draw the ring."""
    assert ":focus-visible {" in CSS
    pointer_focus = CSS.split(".stTextInput input:focus {")[1].split("}")[0]
    assert "outline" not in pointer_focus
    assert "border-color" in pointer_focus


def test_the_select_and_number_input_show_focus_on_the_container():
    assert 'data-baseweb="select"]:focus-within' in CSS


# ---------------------------------------------------------------------------
# Motion: the operator can ask for none
# ---------------------------------------------------------------------------

def test_reduced_motion_neutralises_animation_and_transition():
    assert "prefers-reduced-motion: reduce" in CSS
    block = CSS.split("prefers-reduced-motion: reduce")[1]
    assert "animation-duration: 0.001ms" in block
    assert "animation-iteration-count: 1" in block
    assert "transition-duration: 0.001ms" in block


def test_reduced_motion_is_announced_as_a_media_query_not_a_guess():
    assert "@media (prefers-reduced-motion: reduce)" in CSS


# ---------------------------------------------------------------------------
# Responsiveness
# ---------------------------------------------------------------------------

def test_the_board_scrolls_instead_of_squeezing_its_cells():
    assert ".gb-grid, .gb-hero-grid" in CSS
    rule = CSS.split(".gb-grid, .gb-hero-grid")[1].split("}")[0]
    assert "overflow-x: auto" in rule
    assert "max-width: 100%" in rule


def test_there_are_rules_for_a_narrow_window():
    assert "@media (max-width: 720px)" in CSS
    assert "@media (max-width: 1100px)" in CSS
    narrow = CSS.split("@media (max-width: 720px)")[1]
    assert ".gb-panel, .gb-card, .gb-shell" in narrow     # lighter padding
    assert "[role=\"tablist\"]" in narrow                  # tabs scroll, not squash


# ---------------------------------------------------------------------------
# The shared blocks are painted here, not inline in the panels
# ---------------------------------------------------------------------------

BLOCK_CLASSES = (
    "gb-shell",
    "gb-sub-title",
    "gb-empty",
    "gb-empty-dense",
    "gb-empty-title",
    "gb-empty-hint",
    "gb-fact-grid",
    "gb-fact",
    "gb-fact-label",
    "gb-fact-value",
    "gb-fact-detail",
    "gb-scroll-x",
)


def test_every_class_the_shared_blocks_emit_has_a_rule():
    for name in BLOCK_CLASSES:
        assert f".{name}" in CSS, f"{name} is emitted by blocks but never styled"


def test_every_state_a_readout_can_carry_has_its_own_colour():
    for state in blocks.STATES:
        assert f'.gb-fact[data-state="{state}"] .gb-fact-value' in SPACED, state
    assert C.SUCCESS in CSS.split('[data-state="success"]')[1]
    assert C.ERROR in CSS.split('[data-state="error"]')[1]
    assert C.WARNING in CSS.split('[data-state="warning"]')[1]


def test_the_fact_value_size_is_a_variable_the_block_can_set():
    assert "--gb-fact-value-size" in CSS


def test_readouts_and_badges_transition_consistently():
    """One duration for a border/colour change, so hover feels the same."""
    assert ".gb-fact {" in CSS
    fact_rule = CSS.split(".gb-fact {")[1].split("}")[0]
    assert "transition" in fact_rule
    assert ".gb-badge, .gb-status-chip" in CSS


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def test_the_spinner_label_is_styled_like_the_rest_of_the_telemetry():
    assert '[data-testid="stSpinner"]' in CSS
    spinner = CSS.split('[data-testid="stSpinner"] > div')[1].split("}")[0]
    assert C.TEXT_SECONDARY in spinner
    assert "font-family" in spinner      # the label matches the other telemetry
