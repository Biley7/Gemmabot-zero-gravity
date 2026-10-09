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

/* ── Shared blocks (frontend/components/blocks.py) ────────────────────────
   These were inline styles repeated in every panel.  A block is a class here,
   so the four labs cannot drift apart, and a hover or a focus state is
   declared once instead of nowhere. */

/* Panel-inner surface */
.gb-shell {{
    background-color: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-radius: {S.px(S.RADIUS_MD)};
    padding: {S.px(S.MD)};
}}

/* Small-caps label above a block */
.gb-sub-title {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_MUTED};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    margin-bottom: {S.px(S.SM)};
}}

/* Empty state — one look for every panel, dense variant for the sidebar */
.gb-empty {{
    background-color: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px dashed {C.BORDER_DEFAULT};
    border-radius: {S.px(S.RADIUS_MD)};
    padding: {S.px(S.MD)} {S.px(S.LG)};
}}
.gb-empty-dense {{
    background-color: transparent;
    border: none;
    border-radius: 0;
    padding: {S.px(S.XS)} 0;
}}
.gb-empty-title {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    color: {C.TEXT_SECONDARY};
}}
.gb-empty-hint {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_MUTED};
    margin-top: {S.px(S.XS)};
}}

/* Readout cards — label / value / detail, coloured by data-state so that
   "success" is the same green in every lab. */
.gb-fact-grid {{
    display: grid;
    gap: {S.px(S.SM)};
}}
.gb-fact {{
    display: flex;
    flex-direction: column;
    gap: {S.px(S.XS)};
    padding: {S.px(S.SM)} {S.px(S.MD)};
    background-color: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-radius: {S.px(S.RADIUS_MD)};
    transition: {A.transition("border-color", duration=A.DURATION_FAST)};
}}
.gb-fact:hover {{
    border-color: {C.BORDER_DEFAULT};
}}
.gb-fact-label {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_MUTED};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
}}
.gb-fact-value {{
    font-family: {T.FONT_MONO};
    font-size: var(--gb-fact-value-size, {T.SIZE_BASE}px);
    color: {C.TEXT_PRIMARY};
    line-height: {T.LEADING_TIGHT};
}}
.gb-fact-detail {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_MUTED};
}}
.gb-fact[data-state="success"] .gb-fact-value {{ color: {C.SUCCESS}; }}
.gb-fact[data-state="warning"] .gb-fact-value {{ color: {C.WARNING}; }}
.gb-fact[data-state="error"]   .gb-fact-value {{ color: {C.ERROR}; }}
.gb-fact[data-state="running"] .gb-fact-value {{ color: {C.RUNNING}; }}
.gb-fact[data-state="thinking"] .gb-fact-value {{ color: {C.THINKING}; }}
.gb-fact[data-state="neutral"] .gb-fact-value {{ color: {C.TELEMETRY_VALUE}; }}

/* A dense table scrolls itself rather than pushing the page sideways */
.gb-scroll-x {{
    overflow-x: auto;
    padding-bottom: {S.px(S.XS)};
    scrollbar-width: thin;
}}

/* ── Console shell (frontend/console/shell.py) ────────────────────────────
   The header, the console status bar and the simulator viewport.  This is the
   frame that makes the five labs read as one instrument rather than as pages:
   one wordmark, one status vocabulary, one framed drawing surface. */

.gb-console-head  {{
    display: flex;
    align-items: baseline;
    gap: {S.px(S.MD)};
    padding-bottom: {S.px(S.SM)};
}}
.gb-wordmark  {{
    font-family: {T.FONT_SANS};
    font-size: 22px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    letter-spacing: -0.01em;
    line-height: {T.LEADING_TIGHT};
    color: {C.TEXT_PRIMARY};
}}
.gb-tagline  {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_MUTED};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    white-space: nowrap;
}}
.gb-head-rule  {{
    flex: 1;
    height: 1px;
    min-width: {S.px(S.SM)};
    align-self: center;
    background: {C.BORDER_SUBTLE};
}}
.gb-head-meta  {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_SECONDARY};
    letter-spacing: {T.TRACKING_WIDE};
    white-space: nowrap;
}}
.gb-head-model {{ color: {C.TELEMETRY_VALUE}; }}

.gb-console-bar  {{
    display: flex;
    align-items: center;
    gap: {S.px(S.MD)};
    padding: {S.px(S.SM)} 0;
    border-bottom: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    margin-bottom: {S.px(S.LG)};
}}
.gb-console-chip  {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    line-height: {T.LEADING_TIGHT};
    padding: {S.px(S.XS)} {S.px(S.SM)};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_DEFAULT};
    border-radius: {S.px(S.RADIUS_SM)};
    background: {C.BG_ELEVATED};
    color: {C.TEXT_SECONDARY};
    white-space: nowrap;
    transition: {A.transition("background-color", "border-color", "color",
                             duration=A.DURATION_FAST)};
}}
.gb-console-chip[data-status="thinking"] {{
    background: {C.THINKING_BG}; border-color: {C.THINKING_BORDER};
    color: {C.THINKING}; animation: {A.animation_pulse(1400)};
}}
.gb-console-chip[data-status="verifying"],
.gb-console-chip[data-status="executing"] {{
    background: {C.RUNNING_BG}; border-color: {C.RUNNING_BORDER}; color: {C.RUNNING};
}}
.gb-console-chip[data-status="complete"] {{
    background: {C.SUCCESS_BG}; border-color: {C.SUCCESS_BORDER}; color: {C.SUCCESS};
}}
.gb-console-chip[data-status="failed"] {{
    background: {C.ERROR_BG}; border-color: {C.ERROR_BORDER}; color: {C.ERROR};
}}
.gb-console-activity  {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    color: {C.TEXT_SECONDARY};
    min-width: 0;
}}
.gb-console-meta  {{
    margin-left: auto;
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TELEMETRY_UNIT};
    white-space: nowrap;
}}

/* The viewport: the drawing surface the simulator owns.  The floor is darker
   than any panel, so the board reads as an instrument, not as a card. */
.gb-viewport  {{
    background: {C.BG_INSET};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_DEFAULT};
    border-radius: {S.px(S.RADIUS_LG)};
    overflow: hidden;
}}
.gb-viewport-bar  {{
    display: flex;
    align-items: center;
    gap: {S.px(S.SM)};
    padding: {S.px(S.SM)} {S.px(S.MD)};
    background: {C.BG_SURFACE};
    border-bottom: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
}}
.gb-viewport-title  {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    color: {C.TEXT_SECONDARY};
    white-space: nowrap;
}}
.gb-viewport-meta  {{
    margin-left: auto;
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TELEMETRY_LABEL};
    letter-spacing: 0.04em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.gb-viewport-body  {{
    display: flex;
    justify-content: center;
    padding: {S.px(S.MD)};
}}
.gb-viewport-foot  {{
    padding: {S.px(S.SM)} {S.px(S.MD)};
    background: {C.BG_SURFACE};
    border-top: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
}}

/* ── Console zones (frontend/console/pipeline.py) ─────────────────────────
   One label per zone, then the instrument itself. */
.gb-zone {{ margin-top: {S.px(S.LG)}; }}
.gb-zone-bar {{
    display: flex;
    align-items: baseline;
    gap: {S.px(S.SM)};
    margin-bottom: {S.px(S.SM)};
}}
.gb-zone-title {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    font-weight: {T.WEIGHT_SEMIBOLD};
    letter-spacing: {T.TRACKING_WIDE};
    text-transform: uppercase;
    color: {C.TEXT_SECONDARY};
}}
.gb-zone-meta {{
    margin-left: auto;
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_MUTED};
    white-space: nowrap;
}}

/* ── Pipeline ────────────────────────────────────────────────────────────
   Six stages, in order, each carrying the state it really reached.  The state
   is a 2px edge on the left plus the label colour — no banners. */
.gb-pipe {{
    display: flex;
    flex-wrap: wrap;
    background: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-radius: {S.px(S.RADIUS_MD)};
    overflow: hidden;
}}
.gb-pipe-stage {{
    position: relative;
    flex: 1 1 {S.px(112)};
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: {S.px(S.SM)} {S.px(S.MD)};
    border-right: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    transition: {A.transition("background-color", duration=A.DURATION_FAST)};
}}
.gb-pipe-stage:last-child {{ border-right: none; }}
.gb-pipe-stage::before {{
    content: "";
    position: absolute;
    left: 0; top: 0; bottom: 0;
    width: 2px;
    background: transparent;
}}
.gb-pipe-label {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    letter-spacing: {T.TRACKING_WIDE};
    color: {C.TEXT_MUTED};
    white-space: nowrap;
}}
/* The flow arrow between stages is information: it says which way the
   pipeline runs. */
.gb-pipe-stage:not(:last-child) .gb-pipe-label::after {{
    content: "→";
    margin-left: {S.px(S.XS)};
    color: {C.BORDER_STRONG};
}}
.gb-pipe-detail {{
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    color: {C.TEXT_MUTED};
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.gb-pipe-stage[data-state="passed"]::before {{ background: {C.SUCCESS}; }}
.gb-pipe-stage[data-state="passed"] .gb-pipe-label {{ color: {C.SUCCESS}; }}
.gb-pipe-stage[data-state="failed"]::before {{ background: {C.ERROR}; }}
.gb-pipe-stage[data-state="failed"] .gb-pipe-label {{ color: {C.ERROR}; }}
.gb-pipe-stage[data-state="failed"] .gb-pipe-detail {{ color: {C.ERROR}; }}
.gb-pipe-stage[data-state="running"] {{ background: {C.RUNNING_BG}; }}
.gb-pipe-stage[data-state="running"]::before {{
    background: {C.ACCENT_BLUE};
    animation: {A.animation_pulse(1600)};
}}
.gb-pipe-stage[data-state="running"] .gb-pipe-label {{ color: {C.RUNNING}; }}
.gb-pipe-stage[data-state="skipped"]::before {{ background: {C.BORDER_DEFAULT}; }}
.gb-pipe-stage[data-state="skipped"] .gb-pipe-label {{ color: {C.TEXT_SECONDARY}; }}

/* ── Action timeline ─────────────────────────────────────────────────────
   The plan, action by action, with the message the simulator logged for it.
   The row the execution stands on is marked; the actions after a halt stay
   pending, because a plan is not an execution. */
.gb-tl {{
    display: flex;
    flex-direction: column;
    background: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-radius: {S.px(S.RADIUS_MD)};
    overflow: hidden;
}}
.gb-tl-row {{
    display: flex;
    align-items: baseline;
    gap: {S.px(S.SM)};
    padding: {S.px(S.XS)} {S.px(S.MD)};
    border-bottom: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-left: 2px solid transparent;
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_SM}px;
    color: {C.TEXT_SECONDARY};
    transition: {A.transition("background-color", "border-color", "color",
                             duration=A.DURATION_FAST)};
}}
.gb-tl-row:last-child {{ border-bottom: none; }}
.gb-tl-row:hover {{ background: {C.BG_OVERLAY}; }}
.gb-tl-idx {{ color: {C.TEXT_MUTED}; flex-shrink: 0; width: {S.px(20)}; text-align: right; }}
.gb-tl-cmd {{
    color: {C.TEXT_PRIMARY};
    letter-spacing: 0.04em;
    flex-shrink: 0;
    min-width: {S.px(104)};
}}
.gb-tl-msg {{
    margin-left: auto;
    color: {C.TEXT_MUTED};
    font-size: {T.SIZE_XS}px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.gb-tl-row[data-state="done"] {{ border-left-color: {C.SUCCESS_BORDER}; }}
.gb-tl-row[data-state="done"] .gb-tl-cmd {{ color: {C.TEXT_SECONDARY}; }}
.gb-tl-row[data-state="pending"] .gb-tl-cmd {{ color: {C.TEXT_MUTED}; }}
.gb-tl-row[data-state="blocked"] {{ border-left-color: {C.ERROR}; }}
.gb-tl-row[data-state="blocked"] .gb-tl-cmd,
.gb-tl-row[data-state="blocked"] .gb-tl-msg {{ color: {C.ERROR}; }}
.gb-tl-row[data-current="true"] {{ background: {C.RUNNING_BG}; }}
.gb-tl-row[data-current="true"] .gb-tl-idx {{ color: {C.ACCENT_BLUE}; }}

/* ── Status strip ────────────────────────────────────────────────────────
   The four harness checks, in one line, with the verdict carried by the mark
   rather than by a banner. */
.gb-statusstrip {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: {S.px(S.SM)} {S.px(S.LG)};
    padding: {S.px(S.SM)} 0;
}}
.gb-status-item {{
    display: inline-flex;
    align-items: center;
    gap: {S.px(S.XS)};
    font-family: {T.FONT_MONO};
    font-size: {T.SIZE_XS}px;
    letter-spacing: {T.TRACKING_WIDE};
    color: {C.TEXT_MUTED};
}}
.gb-status-mark {{ font-size: {T.SIZE_BASE}px; color: {C.TEXT_MUTED}; }}
.gb-status-item[data-verdict="true"] .gb-status-mark {{ color: {C.SUCCESS}; }}
.gb-status-item[data-verdict="true"] .gb-status-label {{ color: {C.TEXT_SECONDARY}; }}
.gb-status-item[data-verdict="false"] .gb-status-mark,
.gb-status-item[data-verdict="false"] .gb-status-label {{ color: {C.ERROR}; }}
.gb-status-item:not(:last-child)::after {{
    content: "·";
    margin-left: {S.px(S.LG)};
    color: {C.BORDER_STRONG};
}}

/* ── Console command block ───────────────────────────────────────────────
   The left column of the Mission screen: a label, a readout, an action. */
.gb-command {{
    display: flex;
    flex-direction: column;
    gap: {S.px(S.SM)};
    padding: {S.px(S.MD)};
    background: {C.BG_SURFACE};
    border: {S.BORDER_WIDTH}px solid {C.BORDER_SUBTLE};
    border-radius: {S.px(S.RADIUS_MD)};
}}

/* ── Focus ──────────────────────────────────────────────────────────────
   Keyboard focus is a visible ring; pointer clicks stay quiet.  Everything
   below sets a border colour, so without this a keyboard user could not see
   where they are. */
:focus-visible {{
    outline: 2px solid {C.ACCENT_BLUE} !important;
    outline-offset: 2px !important;
}}
[data-baseweb="select"]:focus-within,
[data-testid="stNumberInput"] input:focus {{
    border-color: {C.BORDER_STRONG} !important;
}}

/* ── Selection ─────────────────────────────────────────────────────────── */
::selection {{
    background-color: {C.RUNNING_BG};
    color: {C.TEXT_PRIMARY};
}}

/* ── Loading ────────────────────────────────────────────────────────────
   A model call is the one place the console goes quiet: the label is mono,
   muted and always says what is being waited on. */
[data-testid="stSpinner"],
[data-testid="stSpinner"] > div {{
    font-family: {T.FONT_MONO} !important;
    font-size: {T.SIZE_SM}px !important;
    color: {C.TEXT_SECONDARY} !important;
}}

/* ── Tab hover / active ────────────────────────────────────────────────── */
[data-testid="stTabs"] [role="tab"]:hover {{
    color: {C.TEXT_PRIMARY} !important;
}}
.gb-action-row:hover {{
    background-color: {C.BG_OVERLAY};
}}
.gb-badge, .gb-status-chip {{
    transition: {A.transition("background-color", "border-color", "color",
                             duration=A.DURATION_FAST)} !important;
}}

/* ── Reduced motion ─────────────────────────────────────────────────────
   A control system that pulses at someone who asked it not to is a control
   system that ignores its operator.  The execution player checks the same
   media query before it autoplays. */
@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
        scroll-behavior: auto !important;
    }}
}}

/* ── Responsiveness ─────────────────────────────────────────────────────
   The board and the dense tables are the two things that cannot shrink: they
   scroll instead of squeezing their cells into an unreadable column. */
.gb-grid, .gb-hero-grid {{
    max-width: 100%;
    overflow-x: auto;
}}

@media (max-width: 1100px) {{
    .gb-panel {{ padding: {S.px(S.LG)}; }}
    /* The pipeline wraps into two rows instead of squeezing its details to
       nothing, and the timeline keeps its command column readable. */
    .gb-pipe-stage {{ flex: 1 1 {S.px(140)}; }}
    .gb-tl-cmd {{ min-width: {S.px(84)}; }}
}}

@media (max-width: 720px) {{
    .gb-panel, .gb-card, .gb-shell {{ padding: {S.px(S.MD)}; }}
    h1 {{ font-size: {T.SIZE_LG}px !important; }}
    [data-testid="stTabs"] [role="tablist"] {{
        overflow-x: auto;
        flex-wrap: nowrap;
        scrollbar-width: thin;
    }}
    [data-testid="stTabs"] [role="tab"] {{
        white-space: nowrap;
        padding: {S.px(S.XS)} {S.px(S.SM)} !important;
    }}
    /* The header stacks rather than clipping the model readout, and the
       pipeline goes to two stages per row. */
    .gb-console-head {{
        flex-wrap: wrap;
        row-gap: {S.px(S.XS)};
    }}
    .gb-tagline {{ white-space: normal; }}
    .gb-head-rule {{ display: none; }}
    .gb-head-meta {{ white-space: normal; }}
    .gb-console-bar {{ flex-wrap: wrap; row-gap: {S.px(S.XS)}; }}
    .gb-console-meta {{ margin-left: 0; }}
    .gb-pipe-stage {{ flex: 1 1 50%; }}
    .gb-pipe-stage:nth-child(even) {{ border-right: none; }}
    .gb-tl-cmd {{ min-width: 0; }}
    .gb-tl-msg {{ display: none; }}
}}
</style>
"""


def inject_theme() -> None:
    """Inject the full design-system CSS into the Streamlit page.

    Called on *every* script run, deliberately.  Streamlit rebuilds the element
    tree from scratch on each rerun while this module stays in ``sys.modules``,
    so a "once per process" flag emits the stylesheet exactly once: the second
    run — any button press, any widget change — drops every ``.gb-*`` class, the
    ``:focus-visible`` rings, the reduced-motion block and the responsive rules
    for the rest of that session, and no session after the first one sees them
    at all.  That is exactly the "inconsistent styling" this module exists to
    prevent, so the injection must not be guarded.

    Re-emitting is cheap: the string is identical every time, so Streamlit
    hashes the element and leaves the rendered DOM untouched.
    """
    import streamlit as st

    st.markdown(_css(), unsafe_allow_html=True)
