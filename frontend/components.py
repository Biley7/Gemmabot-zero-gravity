"""Streamlit UI components.

Owner: FRONTEND
"""


def render_board(world) -> str:
    """Render the game board as HTML.

    Args:
        world: World state to render

    Returns:
        HTML string for display
    """
    raise NotImplementedError


def render_action_log(log: list[str]) -> None:
    """Render the action log in the UI.

    Args:
        log: List of action log entries
    """
    raise NotImplementedError
