"""Logging infrastructure for runs and attempts.

Owner: BACKEND
"""
from typing import Any
from gemmabot.schemas import RunResult


def log_run(result: RunResult) -> None:
    """Log a run result to persistent storage.

    Args:
        result: RunResult to log
    """
    raise NotImplementedError
