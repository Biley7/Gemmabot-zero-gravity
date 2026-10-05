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

# Fade in used for cards / panels on first render
KEYFRAME_FADE_IN = f"""
@keyframes gb-fade-in {{
  from {{ opacity: 0; }}
  to   {{ opacity: 1; }}
}}
"""

def transition(*properties: str, duration: int = DURATION_BASE, easing: str = EASE_OUT) -> str:
    """Return a CSS transition string for the given properties."""
    dur = f"{duration}ms"
    return ", ".join(f"{p} {dur} {easing}" for p in properties)

def animation_pulse(duration_ms: int = 1800) -> str:
    return f"gb-pulse {duration_ms}ms {EASE_INOUT} infinite"

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
])
