"""Service layer for frontend-backend communication.

Owner: BACKEND
"""
from typing import Literal
from gemmabot.schemas import World, RunResult


def run_instruction(instruction: str, world: World, backend: Literal["api", "ollama", "auto"]) -> RunResult:
    """Run an instruction through the full pipeline.

    This is the main entry point for the frontend.

    Args:
        instruction: Natural language instruction
        world: Initial world state
        backend: Which AI backend to use

    Returns:
        RunResult with execution details
    """
    raise NotImplementedError
