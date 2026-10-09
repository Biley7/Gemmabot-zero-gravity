"""Canonical model-reply parsing — one implementation, every call site.

Owner: BACKEND.

Parsing is its own layer in the GemmaBot Guard pipeline: a planner *proposes*
text, this module extracts the structured value from it, and the validator
decides whether that value is acceptable.  ``backend.planner`` and
``backend.verifier.harness`` parse plans through :func:`parse_plan_reply`;
``backend.vision.map_vision`` parses world objects through
:func:`parse_world_reply`.  Fence tolerance and failure messages live here
once, so the three call sites cannot drift apart.

Public surface
--------------
extract_json_value(text, *, missing_message) -> Any
parse_plan_reply(text)                        -> (thought: str, actions: list)
parse_world_reply(text)                       -> Any
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?")


def extract_json_value(text: str, *, missing_message: str) -> Any:
    """Return the JSON value found between the first ``{`` and last ``}``.

    Code fences are stripped first, matching what models actually emit.
    Raises ``ValueError(missing_message)`` when there is no brace pair or the
    slice is not valid JSON — the failure each caller has always reported.
    """
    cleaned = _FENCE.sub("", text or "")
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(missing_message)
    return json.loads(cleaned[start:end + 1])


def parse_plan_reply(text: str) -> tuple[str, list]:
    """Parse the ``{thought, actions}`` plan reply (see docs/CONTRACTS.md).

    Only extraction happens here; whether the actions are *valid* is the
    validator's call (``backend.verifier.harness.verify_plan``).
    """
    data = extract_json_value(text, missing_message="No JSON found in reply")
    return data.get("thought", ""), data.get("actions", [])


def parse_world_reply(text: str) -> Any:
    """Parse a map-vision ``{robot, dir, goal, walls}`` reply.

    The raw value is returned; semantic validation is
    ``backend.vision.map_vision.check_world_report``'s job.
    """
    return extract_json_value(
        text, missing_message="No JSON object found in model reply"
    )
