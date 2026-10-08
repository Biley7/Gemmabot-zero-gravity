"""Tests for frontend/components/blocks.py — the blocks every panel shares.

These blocks exist because five panels had each grown their own copy.  So the
tests here cover the blocks themselves *and* guard the duplication from coming
back: a panel that defines its own escaper or its own fact-card markup fails.
"""
from pathlib import Path

import pytest

from frontend.components import blocks
from frontend.components import colors as C

PANELS = ("brain", "replay", "safety", "vision", "benchmark")
PANEL_DIR = Path(__file__).resolve().parent.parent / "frontend" / "panels"


def _rows():
    return [
        {"id": "run", "label": "Run", "value": "#3", "detail": "at 12:00",
         "state": "neutral"},
        {"id": "attempts", "label": "Attempts", "value": "2",
         "detail": "1 failed", "state": "error"},
    ]


# ---------------------------------------------------------------------------
# escape / plural
# ---------------------------------------------------------------------------

def test_escape_neutralises_anything_that_could_close_a_tag():
    assert blocks.escape("<script>alert(1)</script>") == \
        "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert blocks.escape('a "quoted" & \'apostrophed\' value') == \
        "a &quot;quoted&quot; &amp; &#x27;apostrophed&#x27; value"


def test_escape_takes_values_that_are_not_strings():
    assert blocks.escape(None) == "None"
    assert blocks.escape(7) == "7"
    assert blocks.escape([1, 2]) == "[1, 2]"


def test_plural_counts_the_word_not_the_number():
    assert blocks.plural(1, "action") == "1 action"
    assert blocks.plural(0, "action") == "0 actions"
    assert blocks.plural(2, "action") == "2 actions"
    assert blocks.plural(2, "run") == "2 runs"


# ---------------------------------------------------------------------------
# Structure blocks
# ---------------------------------------------------------------------------

def test_sub_title_and_shell_are_classes_not_inline_styles():
    assert blocks.sub_title("Per case") == \
        "<div class='gb-sub-title'>Per case</div>"
    assert blocks.shell("<span>x</span>") == \
        "<div class='gb-shell'><span>x</span></div>"


def test_sub_title_escapes_its_text():
    assert "<b>" not in blocks.sub_title("<b>raw</b>")


def test_empty_state_says_what_is_missing_and_what_would_fill_it():
    html = blocks.empty_state("No runs yet.", "Run a plan to fill this in.")
    assert "gb-empty" in html
    assert "gb-empty-title'>No runs yet." in html
    assert "gb-empty-hint'>Run a plan to fill this in." in html
    assert "gb-empty-dense" not in html


def test_the_dense_empty_state_drops_the_border_for_the_sidebar():
    html = blocks.empty_state("No runs yet.", dense=True)
    assert "gb-empty-dense" in html
    assert "gb-empty-hint" not in html          # a hint is optional


def test_empty_state_escapes_both_strings():
    html = blocks.empty_state("<script>alert(1)</script>", "</div>")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;/div&gt;" in html


# ---------------------------------------------------------------------------
# fact_cards
# ---------------------------------------------------------------------------

def test_fact_cards_emit_the_metadata_every_panel_relies_on():
    html = blocks.fact_cards(_rows(), css_class="gb-replay-fact", column_min=160)
    assert html.count("class='gb-fact gb-replay-fact'") == 2
    assert "data-fact='run' data-value='#3' data-state='neutral'" in html
    assert "data-fact='attempts' data-value='2' data-state='error'" in html
    assert "grid-template-columns:repeat(auto-fit,minmax(160px,1fr))" in html
    assert "gb-fact-grid" in html


def test_a_fact_card_carries_a_tooltip_of_label_value_and_detail():
    html = blocks.fact_cards(_rows()[:1], css_class="gb-x")
    assert "title='Run: #3 — at 12:00'" in html


def test_an_unknown_state_renders_as_neutral_rather_than_unstyled():
    """A state the theme has no colour for must not leave the value unpainted."""
    html = blocks.fact_cards(
        [{"id": "x", "label": "X", "value": "1", "detail": "", "state": "vibes"}],
        css_class="gb-x",
    )
    assert "data-state='neutral'" in html


def test_a_missing_state_or_detail_does_not_break_the_card():
    html = blocks.fact_cards([{"id": "x", "label": "X", "value": "1"}],
                             css_class="gb-x")
    assert "data-state='neutral'" in html
    assert "gb-fact-detail'></span>" in html


def test_value_size_is_a_css_variable_only_when_asked_for():
    plain = blocks.fact_cards(_rows()[:1], css_class="gb-x")
    sized = blocks.fact_cards(_rows()[:1], css_class="gb-x", value_size=16)
    assert "--gb-fact-value-size" not in plain
    assert "--gb-fact-value-size:16px" in sized


def test_fact_cards_escape_every_value_they_print():
    html = blocks.fact_cards(
        [{"id": "<i>", "label": "<i>", "value": "<i>", "detail": "<i>",
          "state": "neutral"}],
        css_class="gb-x",
    )
    assert "<i>" not in html


def test_fact_cards_with_no_rows_is_an_empty_grid_not_a_crash():
    for rows in (None, []):
        html = blocks.fact_cards(rows, css_class="gb-x")
        assert "gb-fact-grid" in html
        assert "gb-fact " not in html


# ---------------------------------------------------------------------------
# scroll_x
# ---------------------------------------------------------------------------

def test_scroll_x_wraps_a_dense_table_with_a_readable_minimum():
    html = blocks.scroll_x("<div>row</div>", min_width=760)
    assert html.startswith("<div class='gb-scroll-x'>")
    assert "min-width:760px" in html
    assert "<div>row</div>" in html


def test_scroll_x_defaults_to_a_width_that_keeps_columns_legible():
    assert "min-width:720px" in blocks.scroll_x("x")


# ---------------------------------------------------------------------------
# state_color
# ---------------------------------------------------------------------------

def test_state_color_uses_the_semantic_tokens():
    assert blocks.state_color("success") == C.SUCCESS
    assert blocks.state_color("error") == C.ERROR
    assert blocks.state_color("warning") == C.WARNING
    assert blocks.state_color("running") == C.RUNNING
    assert blocks.state_color("nonsense") == C.TEXT_SECONDARY


# ---------------------------------------------------------------------------
# The duplication must not come back
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("panel", PANELS)
def test_no_panel_defines_its_own_escaper_or_pluraliser(panel):
    src = (PANEL_DIR / f"{panel}.py").read_text(encoding="utf-8")
    assert "def _e(" not in src, f"{panel}.py re-implements escape()"
    assert "def _plural(" not in src, f"{panel}.py re-implements plural()"
    assert "import html" not in src, f"{panel}.py imports html to build its own"


@pytest.mark.parametrize("panel", PANELS)
def test_every_panel_takes_its_blocks_from_the_shared_module(panel):
    src = (PANEL_DIR / f"{panel}.py").read_text(encoding="utf-8")
    assert "from frontend.components.blocks import" in src


# The class each panel keeps as its own hook (its own layout, its own tests).
FACT_CLASSES = {
    "replay": "gb-replay-fact",
    "safety": "gb-safety-fact",
    "vision": "gb-vision-fact",
    "benchmark": "gb-bench-fact",
}


@pytest.mark.parametrize("panel,css_class", sorted(FACT_CLASSES.items()))
def test_every_fact_grid_goes_through_the_shared_builder(panel, css_class):
    """A panel may pick its own column width, never its own card markup."""
    src = (PANEL_DIR / f"{panel}.py").read_text(encoding="utf-8")
    assert "fact_cards(" in src
    assert f'css_class="{css_class}"' in src


@pytest.mark.parametrize("panel", ["replay", "vision"])
def test_the_shared_card_is_what_the_panel_actually_renders(panel):
    module = __import__(f"frontend.panels.{panel}", fromlist=["facts_html"])
    html = module.facts_html(_rows())
    assert "gb-fact " in html
    assert "gb-fact-grid" in html
    assert FACT_CLASSES[panel] in html
    # Colour now comes from data-state through the theme, not from the panel,
    # and the card's geometry is a class rather than a repeated inline style.
    assert "style='color:" not in html
    assert "style='display:flex;flex-direction:column" not in html
