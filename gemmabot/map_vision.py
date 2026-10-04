"""Map vision for multimodal AI (convert grid to visual representation).

Owner: BACKEND
"""
from typing import Any
from gemmabot.schemas import World


def world_to_image(world: World) -> Any:
    """Convert a world state to a visual representation.

    Args:
        world: World state to convert

    Returns:
        Visual representation (e.g., PIL Image)
    """
    raise NotImplementedError
