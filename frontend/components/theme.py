"""
Design system: Theme injector
Assembles all tokens into a single CSS block injected via st.markdown().
Call inject_theme() once at the top of app.py, after st.set_page_config().

Also exports STREAMLIT_THEME — a dict for .streamlit/config.toml values
that can be read programmatically.
"""
from __future__ import annotations

from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.components import animations as A


# ── Streamlit config.toml equivalent (for reference / programmatic use) ──────
STREAMLIT_THEME: dict = {
    "base": "dark",
    "primaryColor": C.ACCENT_BLUE,
    "backgroundColor": C.BG_BASE,
    "secondaryBackgroundColor": C.BG_SURFACE,
    "textColor": C.TEXT_PRIMARY,
    "font": "monospace",
}


def _css() -> str:
    """Build the complete CSS string from design tokens."""
    return f"""
<style>
/* ── Keyframe animations ──────────────────────────────────────────────── */
{A.ALL_KEYFRAMES}

/* ── Root / page ──────────────────────────────────────────────────────── */
html, body, [data-testid="stAppViewContainer"] {{
    background-color: {C.BG_BASE} !important;
    color: {C.TEXT_PRIMARY};
    font-family: {T.FONT_SANS};
    font-size: {T.SIZE_MD}px;
    line-height: {T.LEADING_BASE};
}}

/* ── Main content area ────────────────────────────────────────────────── */
[data-testid="stMain"] {{
    background-color: {C.BG_BASE} !important;
}}

/* ── Sidebar ──────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {{
    background-color: {C.BG_SURFACE} !important;
    border-right: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE} !important;
}}
[data-testid="stSidebar"] * {{
    font-family: {T.FONT_SANS};
}}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stSlider label,
[data-testid="stSidebar"] .stNumberInput label {{
    color: {C.TEXT_SECONDARY} !important;
    font-size: {T.SIZE_SM}px !important;
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
}}

/* ── Page title (h1) ──────────────────────────────────────────────────── */
h1 {{
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_XL}px !important;
    font-weight: {T.WEIGHT_SEMIBOLD} !important;
    color: {C.TEXT_PRIMARY} !important;
    letter-spacing: 0.04em;
    margin-bottom: {S.px(S.MD)} !important;
}}

/* ── h2, h3 ───────────────────────────────────────────────────────────── */
h2, h3 {{
    font-family: {T.FONT_SANS} !important;
    font-weight: {T.WEIGHT_MEDIUM} !important;
    color: {C.TEXT_PRIMARY} !important;
    letter-spacing: {T.TRACKING_WIDE};
}}
h2 {{ font-size: {T.SIZE_LG}px !important; }}
h3 {{ font-size: {T.SIZE_MD}px !important; }}

/* ── Caption / small ──────────────────────────────────────────────────── */
[data-testid="stCaptionContainer"],
.stCaption {{
    color: {C.TEXT_MUTED} !important;
    font-size: {T.SIZE_SM}px !important;
    font-family: {T.FONT_MONO} !important;
}}

/* ── Buttons ──────────────────────────────────────────────────────────── */
.stButton button {{
    background-color: {C.BG_ELEVATED} !important;
    color: {C.TEXT_PRIMARY} !important;
    border: {S.BORDER_WIDTH}px solid {C.BORDER_DEFAULT} !important;
    border-radius: {S.px(S.RADIUS_SM)} !important;
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_SM}px !important;
    letter-spacing: {T.TRACKING_WIDE};
    padding: {S.px(S.XS)} {S.px(S.LG)} !important;
    transition: {A.transition("background-color", "border-color")} !important;
}}
.stButton button:hover {{
    background-color: {C.BG_OVERLAY} !important;
    border-color: {C.BORDER_STRONG} !important;
}}
/* Primary button */
.stButton button[kind="primary"] {{
    background-color: {C.ACCENT_BLUE} !important;
    border-color: {C.ACCENT_BLUE} !important;
    color: {C.BG_BASE} !important;
    font-weight: {T.WEIGHT_SEMIBOLD} !important;
}}
.stButton button[kind="primary"]:hover {{
    background-color: {C.ACCENT_BLUE_DIM} !important;
    border-color: {C.ACCENT_BLUE_DIM} !important;
}}

/* ── Text input ───────────────────────────────────────────────────────── */
.stTextInput input {{
    background-color: {C.BG_OVERLAY} !important;
    color: {C.TEXT_PRIMARY} !important;
    border: {S.BORDER_WIDTH}px solid {C.BORDER_DEFAULT} !important;
    border-radius: {S.px(S.RADIUS_SM)} !important;
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_BASE}px !important;
    transition: {A.transition("border-color")} !important;
}}
.stTextInput input:focus {{
    border-color: {C.BORDER_STRONG} !important;
    box-shadow: 0 0 0 2px {C.RUNNING_BG} !important;
}}

/* ── Selectbox / radio / number input ────────────────────────────────── */
.stSelectbox select,
.stSelectbox [data-baseweb="select"] {{
    background-color: {C.BG_OVERLAY} !important;
    border-color: {C.BORDER_DEFAULT} !important;
    border-radius: {S.px(S.RADIUS_SM)} !important;
    font-family: {T.FONT_MONO} !important;
    color: {C.TEXT_PRIMARY} !important;
}}

/* ── Expander ─────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    background-color: {C.BG_SURFACE} !important;
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE} !important;
    border-radius: {S.px(S.RADIUS_MD)} !important;
    margin-bottom: {S.px(S.SM)} !important;
}}
[data-testid="stExpander"] summary {{
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_SM}px !important;
    color: {C.TEXT_SECONDARY} !important;
    letter-spacing: {T.TRACKING_WIDE};
    padding: {S.px(S.MD)} {S.px(S.LG)} !important;
}}

/* ── Code blocks ──────────────────────────────────────────────────────── */
.stCodeBlock, code, pre {{
    background-color: {C.BG_ELEVATED} !important;
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE} !important;
    border-radius: {S.px(S.RADIUS_SM)} !important;
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_SM}px !important;
    color: {C.TEXT_PRIMARY} !important;
}}

/* ── Metrics ──────────────────────────────────────────────────────────── */
[data-testid="stMetric"] {{
    background-color: {C.BG_SURFACE} !important;
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE} !important;
    border-radius: {S.px(S.RADIUS_MD)} !important;
    padding: {S.px(S.MD)} {S.px(S.LG)} !important;
}}
[data-testid="stMetricLabel"] {{
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_SM}px !important;
    color: {C.TELEMETRY_LABEL} !important;
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
}}
[data-testid="stMetricValue"] {{
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_XL}px !important;
    font-weight: {T.WEIGHT_SEMIBOLD} !important;
    color: {C.TELEMETRY_VALUE} !important;
    line-height: {T.LEADING_TIGHT};
}}

/* ── Alerts ───────────────────────────────────────────────────────────── */
[data-testid="stAlert"] {{
    border-radius: {S.px(S.RADIUS_MD)} !important;
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_SM}px !important;
    border-width: {S.BORDER_WIDTH}px !important;
    border-style: solid !important;
}}
.stSuccess {{
    background-color: {C.SUCCESS_BG} !important;
    border-color: {C.SUCCESS_BORDER} !important;
    color: {C.SUCCESS} !important;
}}
.stError {{
    background-color: {C.ERROR_BG} !important;
    border-color: {C.ERROR_BORDER} !important;
    color: {C.ERROR} !important;
}}
.stWarning {{
    background-color: {C.WARNING_BG} !important;
    border-color: {C.WARNING_BORDER} !important;
    color: {C.WARNING} !important;
}}
.stInfo {{
    background-color: {C.RUNNING_BG} !important;
    border-color: {C.RUNNING_BORDER} !important;
    color: {C.RUNNING} !important;
}}

/* ── Tabs ─────────────────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tablist"] {{
    border-bottom: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE} !important;
    gap: {S.px(S.XS)} !important;
}}
[data-testid="stTabs"] [role="tab"] {{
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_SM}px !important;
    color: {C.TEXT_SECONDARY} !important;
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    border: none !important;
    background: transparent !important;
    padding: {S.px(S.SM)} {S.px(S.MD)} !important;
    transition: {A.transition("color", "border-color")} !important;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
    color: {C.TEXT_PRIMARY} !important;
    border-bottom: 2px solid {C.ACCENT_BLUE} !important;
}}

/* ── Dividers ─────────────────────────────────────────────────────────── */
hr {{
    border: none !important;
    border-top: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE} !important;
    margin: {S.px(S.DIVIDER_MARGIN_Y)} 0 !important;
}}

/* ── Scrollbars ───────────────────────────────────────────────────────── */
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: {C.BG_BASE}; }}
::-webkit-scrollbar-thumb {{
    background: {C.BORDER_DEFAULT};
    border-radius: 3px;
}}
::-webkit-scrollbar-thumb:hover {{ background: {C.BORDER_STRONG}; }}

/* ── Custom GemmaBot component classes ───────────────────────────────── */

/* Card */
.gb-card {{
    background-color: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-radius: {S.px(S.RADIUS_MD)};
    padding: {S.px(S.CARD_PADDING)};
    animation: {A.animation_fade_in()};
    transition: {A.transition("border-color")};
}}
.gb-card:hover {{
    border-color: {C.BORDER_DEFAULT};
}}

/* Panel (heavier than card) */
.gb-panel {{
    background-color: {C.BG_ELEVATED};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_DEFAULT};
    border-radius: {S.px(S.RADIUS_LG)};
    padding: {S.px(S.PANEL_PADDING)};
}}

/* Badge */
.gb-badge {{
    display: inline-flex;
    align-items: center;
    gap: {S.px(S.XS)};
    padding: {S.px(S.BADGE_PADDING_Y)} {S.px(S.BADGE_PADDING_X)};
    border-radius: {S.px(S.RADIUS_SM)};
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    font-weight: {T.WEIGHT_MEDIUM};
    letter-spacing: {T.TRACKING_WIDE};
    line-height: {T.LEADING_TIGHT};
    border-width: {S.BORDER_WIDTH}px;
    border-style: solid;
}}
.gb-badge-success {{
    background-color: {C.SUCCESS_BG};
    border-color: {C.SUCCESS_BORDER};
    color: {C.SUCCESS};
}}
.gb-badge-warning {{
    background-color: {C.WARNING_BG};
    border-color: {C.WARNING_BORDER};
    color: {C.WARNING};
}}
.gb-badge-error {{
    background-color: {C.ERROR_BG};
    border-color: {C.ERROR_BORDER};
    color: {C.ERROR};
}}
.gb-badge-running {{
    background-color: {C.RUNNING_BG};
    border-color: {C.RUNNING_BORDER};
    color: {C.RUNNING};
}}
.gb-badge-thinking {{
    background-color: {C.THINKING_BG};
    border-color: {C.THINKING_BORDER};
    color: {C.THINKING};
    animation: {A.animation_pulse()};
}}
.gb-badge-neutral {{
    background-color: {C.BG_ELEVATED};
    border-color: {C.BORDER_DEFAULT};
    color: {C.TEXT_SECONDARY};
}}

/* StatusChip */
.gb-status-chip {{
    display: inline-flex;
    align-items: center;
    gap: {S.px(S.XS)};
    padding: {S.px(S.XS)} {S.px(S.MD)};
    border-radius: {S.px(S.RADIUS_SM)};
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    font-weight: {T.WEIGHT_MEDIUM};
    letter-spacing: {T.TRACKING_WIDE};
    border-width: {S.BORDER_WIDTH}px;
    border-style: solid;
    animation: {A.animation_slide_in()};
}}
.gb-dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    display: inline-block;
    flex-shrink: 0;
}}
.gb-dot-success  {{ background-color: {C.SUCCESS}; }}
.gb-dot-warning  {{ background-color: {C.WARNING}; }}
.gb-dot-error    {{ background-color: {C.ERROR}; }}
.gb-dot-running  {{ background-color: {C.RUNNING}; animation: {A.animation_pulse()}; }}
.gb-dot-thinking {{ background-color: {C.THINKING}; animation: {A.animation_pulse(1400)}; }}

/* SectionTitle */
.gb-section-title {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    color: {C.TEXT_MUTED};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    margin-bottom: {S.px(S.SM)};
    display: flex;
    align-items: center;
    gap: {S.px(S.SM)};
}}
.gb-section-title::after {{
    content: "";
    flex: 1;
    height: {S.BORDER_WIDTH}px;
    background-color: {C.BORDER_SUBTLE};
    display: block;
}}

/* Divider */
.gb-divider {{
    border: none;
    border-top: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    margin: {S.px(S.DIVIDER_MARGIN_Y)} 0;
}}

/* ActionList row */
.gb-action-list {{
    display: flex;
    flex-direction: column;
    gap: {S.px(S.ACTION_ROW_GAP)};
}}
.gb-action-row {{
    display: flex;
    align-items: center;
    gap: {S.px(S.SM)};
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    color: {C.TEXT_SECONDARY};
    padding: {S.px(S.XS)} 0;
    border-bottom: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    transition: {A.transition("color")};
}}
.gb-action-row:last-child {{
    border-bottom: none;
}}
.gb-action-index {{
    color: {C.TEXT_MUTED};
    width: 20px;
    text-align: right;
    flex-shrink: 0;
}}
.gb-action-cmd {{
    color: {C.ACCENT_BLUE};
    min-width: 80px;
}}
.gb-action-detail {{
    color: {C.TEXT_SECONDARY};
}}
.gb-action-msg {{
    margin-left: auto;
    color: {C.TEXT_MUTED};
    font-size: {T.SIZE_XS}px;
}}

/* MetricCard */
.gb-metric-card {{
    background-color: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-radius: {S.px(S.RADIUS_MD)};
    padding: {S.px(S.MD)} {S.px(S.LG)};
    display: flex;
    flex-direction: column;
    gap: {S.px(S.XS)};
}}
.gb-metric-label {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TELEMETRY_LABEL};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
}}
.gb-metric-value {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XL}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    color: {C.TELEMETRY_VALUE};
    line-height: {T.LEADING_TIGHT};
}}
.gb-metric-unit {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    color: {C.TELEMETRY_UNIT};
    margin-left: 2px;
}}

/* Telemetry row (used in sidebar) */
.gb-telem-row {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    padding: {S.px(S.XS)} 0;
    border-bottom: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
}}
.gb-telem-key {{
    color: {C.TELEMETRY_LABEL};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    font-size: {T.SIZE_XS}px;
}}
.gb-telem-val {{
    color: {C.TELEMETRY_VALUE};
    font-weight: {T.WEIGHT_MEDIUM};
}}
</style>
"""


_injected = False


def inject_theme() -> None:
    """Inject the full design-system CSS into the Streamlit page.

    Safe to call multiple times — only injects once per session.
    Call immediately after st.set_page_config().
    """
    global _injected
    if _injected:
        return
    import streamlit as st
    st.markdown(_css(), unsafe_allow_html=True)
    _injected = True
