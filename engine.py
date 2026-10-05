# Compatibility shim — real implementation moved to frontend/panels/engine.py
from frontend.panels.engine import *  # noqa: F401, F403
from frontend.panels.engine import (  # noqa: F401
    ask_auto,
    get_ask,
    get_vision_ask,
    run_plan,
    run_map_vision,
    execute,
    check_connections,
    sample_world,
    default_maps,
    SAMPLE_WORLD,
    AskFn,
    VisionAskFn,
    _normalise,
    _used_backend_label,
)
