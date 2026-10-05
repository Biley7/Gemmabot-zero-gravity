# Compatibility shim — real implementation moved to backend/vision/map_vision.py
from backend.vision.map_vision import *  # noqa: F401, F403
from backend.vision.map_vision import (  # noqa: F401
    check_world,
    build_map_prompt,
    read_map,
    ask_vision_api,
    ask_vision_ollama,
)
