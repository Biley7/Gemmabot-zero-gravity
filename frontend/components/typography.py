"""
Design token: Typography
Two stacks only: monospace for all telemetry / code, sans-serif for prose.
No display fonts. No decorative weights.

Consumers: theme.py, components.py, ui_helpers.py
"""

# ── Font stacks ───────────────────────────────────────────────────────────────
FONT_MONO = (
    "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, "
    "'Liberation Mono', monospace"
)
FONT_SANS = (
    "Inter, 'Helvetica Neue', Arial, sans-serif"
)

# ── Size scale (px) ──────────────────────────────────────────────────────────
SIZE_XS   = 10   # coordinate axis labels
SIZE_SM   = 11   # muted captions, telemetry labels
SIZE_BASE = 13   # body, card content
SIZE_MD   = 14   # standard UI text
SIZE_LG   = 16   # section titles
SIZE_XL   = 20   # panel headers
SIZE_XXL  = 24   # page title (handled by Streamlit)

# ── Weight ───────────────────────────────────────────────────────────────────
WEIGHT_NORMAL  = 400
WEIGHT_MEDIUM  = 500
WEIGHT_SEMIBOLD = 600

# ── Line height ───────────────────────────────────────────────────────────────
LEADING_TIGHT  = 1.2   # badges, chips, metric values
LEADING_BASE   = 1.5   # body text
LEADING_RELAXED = 1.7  # long prose

# ── Letter spacing ────────────────────────────────────────────────────────────
TRACKING_WIDE   = "0.08em"  # section title caps, labels
TRACKING_NORMAL = "0em"

# ── Convenience CSS snippets ─────────────────────────────────────────────────
def mono(size: int | None = None) -> str:
    """Return a CSS font-family + font-size snippet for monospace use."""
    base = f"font-family:{FONT_MONO}"
    return f"{base};font-size:{size}px" if size else base

def sans(size: int | None = None) -> str:
    """Return a CSS font-family + font-size snippet for sans-serif use."""
    base = f"font-family:{FONT_SANS}"
    return f"{base};font-size:{size}px" if size else base
