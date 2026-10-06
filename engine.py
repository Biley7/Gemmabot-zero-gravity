# Compatibility shim — real implementation moved to frontend/panels/engine.py
from frontend.panels.engine import *  # noqa: F401, F403
from frontend.panels.engine import (  # noqa: F401
    ask_auto,
    get_ask,
    get_vision_ask,
    run_plan,
    run_map_vision,
    verify_run,
    execute,
    check_connections,
    backend_label,
    backend_model,
    sample_world,
    default_maps,
    SAMPLE_WORLD,
    BACKEND_DISPLAY,
    AskFn,
    VisionAskFn,
    AttemptFn,
    _normalise,
    _used_backend_label,
)
