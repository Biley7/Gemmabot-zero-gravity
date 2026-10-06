"""
Design token: Animations
Subtle, functional transitions only. No bounce. No spin art.
All durations in milliseconds; easing curves are CSS strings.

Consumers: theme.py, components.py
"""

# ── Duration (ms) ─────────────────────────────────────────────────────────────
DURATION_INSTANT  =  80   # state dot swap (success → error)
DURATION_FAST     = 120   # badge colour change, border highlight
DURATION_BASE     = 200   # standard hover / focus transition
DURATION_MODERATE = 300   # panel expand/collapse, status chip swap
DURATION_SLOW     = 500   # board cell update during execution

# ── Execution playback (Phase 3) ─────────────────────────────────────────────
# These are the animation's 1× timings. The player divides by the selected
# speed (0.5× / 1× / 2× / 4×); nothing else scales them.
CELL_STEP_MS   = 300   # forward: exactly one cell at 1×
TURN_MS        = 300   # smooth 90° rotation at 1×
STEP_GAP_MS    = 60    # settle beat between two actions
HALT_MS        = 420   # beat held on a blocked / unknown action
TRACE_DRAW_MS  = 160   # trail segment drawing in behind the robot
SPEED_OPTIONS: tuple[float, ...] = (0.5, 1.0, 2.0, 4.0)
DEFAULT_SPEED = 1.0

# ── Easing ───────────────────────────────────────────────────────────────────
EASE_OUT   = "cubic-bezier(0.0, 0.0, 0.2, 1.0)"   # decelerate — most UI transitions
EASE_IN    = "cubic-bezier(0.4, 0.0, 1.0, 1.0)"   # accelerate — exit transitions
EASE_INOUT = "cubic-bezier(0.4, 0.0, 0.2, 1.0)"   # balanced — expand/collapse

# ── Keyframe CSS blocks ───────────────────────────────────────────────────────

# Pulse used on the THINKING chip while the model is generating
KEYFRAME_PULSE = f"""
@keyframes gb-pulse {{
  0%   {{ opacity: 1; }}
  50%  {{ opacity: 0.45; }}
  100% {{ opacity: 1; }}
}}
"""

# Blink cursor used in the execution step log (monospace telemetry)
KEYFRAME_BLINK = f"""
@keyframes gb-blink {{
  0%, 100% {{ opacity: 1; }}
  50%       {{ opacity: 0; }}
}}
"""

# Slide in from top for status chips on state change
KEYFRAME_SLIDE_IN = f"""
@keyframes gb-slide-in {{
  from {{ opacity: 0; transform: translateY(-4px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}
"""

# Subtle goal glow — breathes softly, never distracting
KEYFRAME_GOAL_GLOW = """
@keyframes gb-goal-glow {
  0%   { box-shadow: 0 0 4px 1px rgba(62,207,142,0.15); }
  50%  { box-shadow: 0 0 10px 3px rgba(62,207,142,0.32); }
  100% { box-shadow: 0 0 4px 1px rgba(62,207,142,0.15); }
}
"""

# Current-step cell flash — single pulse when a step fires
KEYFRAME_STEP_FLASH = """
@keyframes gb-step-flash {
  0%   { box-shadow: 0 0 0 0 rgba(74,143,255,0.0); }
  30%  { box-shadow: 0 0 12px 4px rgba(74,143,255,0.55); }
  100% { box-shadow: 0 0 4px 1px rgba(74,143,255,0.15); }
}
"""

# Fade in used for cards / panels on first render
KEYFRAME_FADE_IN = """
@keyframes gb-fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
"""

# Trail segment drawing itself in — used by the execution player's path trace
KEYFRAME_TRACE_DRAW = """
@keyframes gb-trace-draw {
  from { stroke-dashoffset: var(--gb-trace-len, 40); }
  to   { stroke-dashoffset: 0; }
}
"""

# Collision marker — the cell the verifier refused (Safety Lab).  Breathes
# red like the goal breathes green: same rhythm, opposite meaning.
KEYFRAME_DANGER_PULSE = """
@keyframes gb-danger-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(240,82,82,0.0); }
  50%  { box-shadow: 0 0 12px 3px rgba(240,82,82,0.42); }
  100% { box-shadow: 0 0 0 0 rgba(240,82,82,0.0); }
}
"""

def transition(*properties: str, duration: int = DURATION_BASE, easing: str = EASE_OUT) -> str:
    """Return a CSS transition string for the given properties."""
    dur = f"{duration}ms"
    return ", ".join(f"{p} {dur} {easing}" for p in properties)

def animation_pulse(duration_ms: int = 1800) -> str:
    return f"gb-pulse {duration_ms}ms {EASE_INOUT} infinite"

def animation_danger_pulse(duration_ms: int = 1800) -> str:
    """Slow red breathing for a cell the verifier refused."""
    return f"gb-danger-pulse {duration_ms}ms {EASE_INOUT} infinite"

def animation_slide_in(duration_ms: int = DURATION_MODERATE) -> str:
    return f"gb-slide-in {duration_ms}ms {EASE_OUT} both"

def animation_fade_in(duration_ms: int = DURATION_MODERATE) -> str:
    return f"gb-fade-in {duration_ms}ms {EASE_OUT} both"

# ── All keyframe CSS combined (injected once by theme.py) ────────────────────
ALL_KEYFRAMES = "\n".join([
    KEYFRAME_PULSE,
    KEYFRAME_BLINK,
    KEYFRAME_SLIDE_IN,
    KEYFRAME_FADE_IN,
    KEYFRAME_GOAL_GLOW,
    KEYFRAME_STEP_FLASH,
    KEYFRAME_DANGER_PULSE,
    KEYFRAME_TRACE_DRAW,
])
