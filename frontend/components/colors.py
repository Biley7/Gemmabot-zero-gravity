"""
Design token: Colors
Robot Lab / Simulation / Modern Control Console palette.

All values are CSS hex strings. No gradients. No neon.
Consumers: theme.py, components.py, ui_helpers.py
"""

# ── Surfaces ────────────────────────────────────────────────────────────────
BG_BASE        = "#0e0f11"   # page background — deep graphite
BG_SURFACE     = "#14161a"   # card / panel surface
BG_ELEVATED    = "#1b1d23"   # raised panel, modal
BG_OVERLAY     = "#21242c"   # hover overlay, input background

# ── Borders ─────────────────────────────────────────────────────────────────
BORDER_SUBTLE  = "#252830"   # faint structural border
BORDER_DEFAULT = "#32363f"   # standard border
BORDER_STRONG  = "#4a4f5c"   # active / focused border

# ── Text ────────────────────────────────────────────────────────────────────
TEXT_PRIMARY   = "#e8eaf0"   # main readable text
TEXT_SECONDARY = "#9299a8"   # labels, captions
TEXT_MUTED     = "#5c6270"   # disabled, placeholder
TEXT_INVERSE   = "#0e0f11"   # text on light badge backgrounds

# ── Accent ──────────────────────────────────────────────────────────────────
ACCENT_BLUE    = "#4a8fff"   # primary interactive accent
ACCENT_BLUE_DIM = "#2a5fcc"  # pressed / active state

# ── Semantic states ──────────────────────────────────────────────────────────
SUCCESS        = "#3ecf8e"   # verified safe, goal reached
SUCCESS_BG     = "#0d2e20"   # success surface
SUCCESS_BORDER = "#1a5c3e"

WARNING        = "#f0a742"   # partial / retrying
WARNING_BG     = "#2a1e08"
WARNING_BORDER = "#5c3c10"

ERROR          = "#f05252"   # blocked, failed, rejected
ERROR_BG       = "#2a0d0d"
ERROR_BORDER   = "#5c1a1a"

RUNNING        = "#4a8fff"   # in-progress, planning
RUNNING_BG     = "#0d1e3a"
RUNNING_BORDER = "#1a3a6e"

THINKING       = "#c084fc"   # model is generating
THINKING_BG    = "#1a0d2e"
THINKING_BORDER = "#3a1a5c"

# ── Simulation grid ──────────────────────────────────────────────────────────
GRID_EMPTY          = "#111318"   # traversable cell
GRID_WALL           = "#2a2d35"   # wall cell
GRID_GOAL           = "#1a2210"   # goal cell
GRID_ROBOT          = "#0d1e2e"   # robot cell
GRID_BORDER         = "#252830"   # cell border
GRID_LABEL          = "#5c6270"   # coordinate axis labels

# Additional cell states for the hero grid
GRID_PATH           = "#0d1e2e"   # cells on executed path
GRID_PATH_BORDER    = "#1a3a6e"   # border accent for path cells
GRID_CURRENT        = "#0d2540"   # the step currently animating
GRID_CURRENT_BORDER = "#4a8fff"   # bright accent on current-step cell

# Glow colours (box-shadow values, not fills)
GRID_GOAL_GLOW      = "#3ecf8e"   # subtle green glow around goal
GRID_ROBOT_GLOW     = "#4a8fff"   # blue glow around robot
GRID_CURRENT_GLOW   = "#4a8fff"   # bright glow on active step

# Wall inner gradient stops (dark top to solid bottom — no actual gradient, just two-stop)
GRID_WALL_SURFACE   = "#32363f"   # lighter face of solid wall block
GRID_WALL_EDGE      = "#1e2028"   # shadow edge of wall block

# Hover
GRID_HOVER          = "#1e2230"   # cell hover overlay

# ── Monospace telemetry ──────────────────────────────────────────────────────
TELEMETRY_VALUE = "#c8d0e0"  # metric value
TELEMETRY_LABEL = "#5c6270"  # metric label
TELEMETRY_UNIT  = "#9299a8"  # unit suffix (s, ms, %)
