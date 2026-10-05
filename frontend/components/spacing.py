"""
Design token: Spacing
4-point base grid. Every layout value derives from SP * n.

Consumers: theme.py, components.py, ui_helpers.py
"""

# ── Base unit ────────────────────────────────────────────────────────────────
SP = 4   # px

# ── Named scale ──────────────────────────────────────────────────────────────
XS   = SP * 1    #  4px — tight intra-component gap
SM   = SP * 2    #  8px — icon padding, badge padding
MD   = SP * 3    # 12px — standard internal padding
LG   = SP * 4    # 16px — card padding, section gap
XL   = SP * 5    # 20px — panel padding
XXL  = SP * 6    # 24px — section separation
XXXL = SP * 8    # 32px — major layout gap

# ── Component-specific shortcuts (all derive from scale above) ───────────────
CARD_PADDING      = LG       # 16px
PANEL_PADDING     = XL       # 20px
BADGE_PADDING_X   = SM       #  8px
BADGE_PADDING_Y   = XS       #  4px
SECTION_GAP       = XXL      # 24px
DIVIDER_MARGIN_Y  = MD       # 12px
METRIC_GAP        = SM       #  8px
ACTION_ROW_GAP    = SM       #  8px

# ── Grid cell ────────────────────────────────────────────────────────────────
CELL_SIZE         = 40       # px — compat grid cell (used by grid_html)
CELL_SIZE_HERO    = 64       # px — hero grid cell (world_grid_html)
CELL_LABEL_WIDTH  = 24       # px — axis label gutter (compat)
CELL_LABEL_HERO   = 28       # px — axis label gutter (hero)

# ── Border radius ────────────────────────────────────────────────────────────
RADIUS_SM  = 3    # px — badge, chip
RADIUS_MD  = 5    # px — card, panel
RADIUS_LG  = 8    # px — large panel

# ── Border width ─────────────────────────────────────────────────────────────
BORDER_WIDTH = 1  # px — all borders

def px(value: int) -> str:
    """Return an integer value as a CSS pixel string."""
    return f"{value}px"
