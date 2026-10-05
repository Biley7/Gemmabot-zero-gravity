# Compatibility shim — real implementation moved to frontend/simulation/ui_helpers.py
from frontend.simulation.ui_helpers import *  # noqa: F401, F403
from frontend.simulation.ui_helpers import (  # noqa: F401
    grid_html,
    attempt_cards,
    accepted_reply,
    run_metrics,
    short_json,
)
