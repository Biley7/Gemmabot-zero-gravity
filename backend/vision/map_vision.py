"""Map vision — hand-drawn map reader and world validator.

Owner: BACKEND

Public API
----------
check_world(world) -> (bool, str)
    Pure validation + BFS reachability.  No AI.  No network.
    Thin wrapper over check_world_report(): (report["ok"], report["reason"]).

check_world_report(world) -> {"ok", "reason", "checks"}
    The same verdict, reported per check — ✓ Valid, ✓ Inside bounds,
    ✓ Reachable.  A check that could not be evaluated is ok=None (unproven),
    never a pass.

build_map_prompt() -> str
    System prompt telling the vision model what JSON to return.

read_map(image_bytes, mime_type, ask_vision, max_tries=2) -> (world | None, history)
    Calls ask_vision, parses the reply, validates with check_world.
    Retries once with the exact failure message on the first bad result.

ask_vision_api(prompt, image_bytes, mime_type) -> str
    Vision call via google-genai (inline bytes + text part).

ask_vision_ollama(prompt, image_bytes, mime_type) -> str
    Vision call via ollama Python library (images field).
"""
from __future__ import annotations

import json
from collections import deque
from typing import Any

from backend.parsing import parse_world_reply

# ---------------------------------------------------------------------------
# Constants (mirrored from config / simulator so this module stands alone)
# ---------------------------------------------------------------------------
from backend.logger.logger import redact_secrets
from gemmabot.config import (
    SIZE,
    GEMMA_API_MODEL,
    OLLAMA_MODEL,
    TEMPERATURE,
    api_key,
    missing_api_key_message,
)
from gemmabot.simulator import DIRS


# ---------------------------------------------------------------------------
# 1.  check_world — pure code, no AI
# ---------------------------------------------------------------------------

# The three verdicts the Vision Lab displays for a proposed world, in the
# order they are always reported:
#     ✓ Valid · ✓ Inside bounds · ✓ Reachable
# ``valid`` covers the reading's shape (robot / heading / goal / walls) and that
# the two endpoints are real, distinct cells; ``in_bounds`` is the grid extent;
# ``reachable`` is the BFS search.  A check that could not be evaluated is
# ``ok=None`` (unproven) and is never reported as a pass — the same convention
# ``backend.verifier.harness.verify_plan`` uses.
WORLD_CHECKS: tuple[tuple[str, str], ...] = (
    ("valid", "Valid"),
    ("in_bounds", "Inside bounds"),
    ("reachable", "Reachable"),
)


def _plural(count: int, noun: str) -> str:
    """``1 wall`` / ``7 walls``."""
    return f"{count} {noun}" if int(count) == 1 else f"{int(count)} {noun}s"


def _finding(check_id: str, message: str, **facts: Any) -> dict:
    """One problem: which check it fails, the sentence, and the fact behind it."""
    return {"check": check_id, "message": message, "data": dict(facts)}


def _world_findings(world: Any) -> tuple[list[dict], dict | None]:
    """Every problem *world* has, in the order the checker has always found them.

    Returns ``(findings, parts)``.  *parts* is the parsed robot / goal / walls /
    heading when the reading's shape is readable at all, and ``None`` when it is
    not — a reading that is not a world cannot be bounds-checked or searched, so
    the later checks stay unproven instead of being guessed.
    """
    findings: list[dict] = []

    # ── Type guard ────────────────────────────────────────────────────────
    if not isinstance(world, dict):
        return (
            [_finding("valid", f"world must be a dict, got {type(world).__name__}")],
            None,
        )

    # ── Required keys ─────────────────────────────────────────────────────
    required = {"robot": list, "dir": str, "goal": list, "walls": list}
    for key, expected_type in required.items():
        if key not in world:
            findings.append(_finding("valid", f"missing required key: '{key}'"))
        elif not isinstance(world[key], expected_type):
            findings.append(_finding(
                "valid",
                f"'{key}' must be {expected_type.__name__}, "
                f"got {type(world[key]).__name__}",
                field=key,
            ))
    if findings:
        return findings, None

    robot = world["robot"]
    goal  = world["goal"]
    walls = world["walls"]
    heading = world["dir"]

    # ── robot and goal must be [x, y] int lists ───────────────────────────
    for name, cell in (("robot", robot), ("goal", goal)):
        if len(cell) != 2 or not all(isinstance(v, int) for v in cell):
            findings.append(_finding(
                "valid", f"'{name}' must be a list of two ints, got {cell!r}",
                field=name,
            ))

    # ── walls must be a list of [x, y] int pairs ─────────────────────────
    for i, w in enumerate(walls):
        if (not isinstance(w, list) or len(w) != 2
                or not all(isinstance(v, int) for v in w)):
            findings.append(_finding(
                "valid", f"walls[{i}] must be a list of two ints, got {w!r}",
                field=f"walls[{i}]",
            ))

    # ── heading ───────────────────────────────────────────────────────────
    if heading not in DIRS:
        findings.append(_finding(
            "valid", f"heading '{heading}' is not valid; expected one of {DIRS}",
            field="dir",
        ))

    if findings:
        return findings, None

    # ── bounds check (0 ≤ x, y < SIZE) ───────────────────────────────────
    def in_bounds(cell: list) -> bool:
        return 0 <= cell[0] < SIZE and 0 <= cell[1] < SIZE

    if not in_bounds(robot):
        findings.append(_finding(
            "in_bounds",
            f"robot position {robot} is outside the {SIZE}×{SIZE} grid",
            cell=list(robot), field="robot",
        ))
    if not in_bounds(goal):
        findings.append(_finding(
            "in_bounds",
            f"goal position {goal} is outside the {SIZE}×{SIZE} grid",
            cell=list(goal), field="goal",
        ))
    for i, w in enumerate(walls):
        if not in_bounds(w):
            findings.append(_finding(
                "in_bounds",
                f"walls[{i}] = {w} is outside the {SIZE}×{SIZE} grid",
                cell=list(w), field=f"walls[{i}]",
            ))

    # ── wall-overlap checks ───────────────────────────────────────────────
    wall_set = {tuple(w) for w in walls}
    if tuple(robot) in wall_set:
        findings.append(_finding(
            "valid", f"robot start {robot} is on a wall",
            cell=list(robot), field="robot",
        ))
    if tuple(goal) in wall_set:
        findings.append(_finding(
            "valid", f"goal {goal} is on a wall",
            cell=list(goal), field="goal",
        ))

    # ── start ≠ goal ──────────────────────────────────────────────────────
    if robot == goal:
        findings.append(_finding(
            "valid", f"robot start and goal are the same cell {robot}",
            cell=list(robot),
        ))

    return findings, {"robot": robot, "goal": goal, "walls": walls, "dir": heading}


def _unsearchable_reason(parts: dict | None, findings: list[dict]) -> str | None:
    """Why reachability cannot be asked, or ``None`` when it can.

    A BFS verdict is only well-posed for a reading whose robot and goal are real,
    distinct, in-grid cells that are not themselves obstacles.  Anything else is
    reported as unproven rather than searched.
    """
    if parts is None:
        return findings[0]["message"] if findings else "the reading is not a world"
    blocker = next(
        (f for f in findings if f["check"] in ("valid", "in_bounds")), None
    )
    return blocker["message"] if blocker else None


def _unreachable_finding(parts: dict) -> dict | None:
    """The unreachable-goal finding, or ``None`` when the BFS reaches the goal.

    4-directional BFS over the grid; headings are irrelevant to reachability.
    """
    wall_set = {tuple(w) for w in parts["walls"]}
    start = tuple(parts["robot"])
    target = tuple(parts["goal"])
    visited = {start}
    queue: deque[tuple[int, int]] = deque([start])
    found = False

    while queue and not found:
        cx, cy = queue.popleft()
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            nb = (nx, ny)
            if (0 <= nx < SIZE and 0 <= ny < SIZE
                    and nb not in wall_set
                    and nb not in visited):
                if nb == target:
                    found = True
                    break
                visited.add(nb)
                queue.append(nb)

    if found:
        return None
    return _finding(
        "reachable",
        f"goal is unreachable: no path from {parts['robot']} to {parts['goal']} "
        f"on a {SIZE}×{SIZE} grid with {len(parts['walls'])} wall(s)",
        robot=list(parts["robot"]), goal=list(parts["goal"]),
        walls=len(parts["walls"]),
    )


def _pass_detail(check_id: str, parts: dict) -> str:
    """What a passing check actually established, in the reading's own numbers."""
    walls = len(parts["walls"])
    if check_id == "valid":
        return (
            f"well-formed world — robot, heading, goal and "
            f"{_plural(walls, 'wall')} parsed"
        )
    if check_id == "in_bounds":
        return (
            f"robot, goal and all {_plural(walls, 'wall')} fit the "
            f"{SIZE}×{SIZE} grid"
        )
    return (
        f"BFS found a path from {parts['robot']} to {parts['goal']} "
        f"around {_plural(walls, 'wall')}"
    )


def check_world_report(world: Any) -> dict:
    """Validate *world* and report each check separately.

    The structured form of :func:`check_world`: same verdict, same failure
    sentence, plus one record per entry in ``WORLD_CHECKS``.

    Returns
    -------
    dict
        ``{"ok": bool, "reason": str, "checks": [{"id", "label", "ok",
        "detail", "data"}]}``.  ``reason`` is the first problem found (or
        ``"ok"``); ``ok`` is true only when all three checks passed; a check that
        could not be evaluated is ``ok=None``; ``data`` carries the fact behind a
        failure and is ``{}`` on a pass or an unproven check.

    Never raises on any input.
    """
    findings, parts = _world_findings(world)

    # Reachability is only asked when the question is well-posed, and its
    # finding joins the earlier ones so `reason` stays the first problem found.
    blocker = _unsearchable_reason(parts, findings)
    if blocker is None and parts is not None:
        unreachable = _unreachable_finding(parts)
        if unreachable:
            findings.append(unreachable)

    by_check: dict[str, list[dict]] = {check_id: [] for check_id, _ in WORLD_CHECKS}
    for finding in findings:
        by_check[finding["check"]].append(finding)

    checks: list[dict] = []
    for check_id, label in WORLD_CHECKS:
        hits = by_check[check_id]
        # Unproven is per check: without a parsed reading nothing can be
        # bounds-checked, and without a real start and goal there is nothing to
        # search.  A check that *was* evaluated reports its own verdict — shape,
        # extents and the two endpoints are examined independently, so a
        # failure in one never hides a pass in another.
        unproven: str | None = None
        if parts is None:
            unproven = "not evaluated — the reading is not a world yet"
        if check_id == "reachable" and blocker is not None:
            unproven = f"not evaluated — {blocker}"

        if hits:
            ok, detail, data = False, hits[0]["message"], hits[0]["data"]
        elif unproven is not None:
            ok, detail, data = None, unproven, {}
        else:
            ok, detail, data = True, _pass_detail(check_id, parts), {}
        checks.append({
            "id": check_id, "label": label, "ok": ok,
            "detail": detail, "data": data,
        })

    return {
        "ok": all(check["ok"] is True for check in checks),
        "reason": findings[0]["message"] if findings else "ok",
        "checks": checks,
    }


def check_world(world: Any) -> tuple[bool, str]:
    """Validate a world dict for correctness and reachability.

    Thin wrapper over :func:`check_world_report` — ``(report["ok"],
    report["reason"])``.  Kept as the terse form for callers that only need the
    verdict and the first problem.

    Parameters
    ----------
    world:
        Any value — the function never raises on bad input.

    Returns
    -------
    (True, "ok")
        World is structurally valid, in bounds, and the goal is reachable.
    (False, reason)
        Describes the first problem found.
    """
    report = check_world_report(world)
    return report["ok"], report["reason"]


# ---------------------------------------------------------------------------
# 2.  build_map_prompt
# ---------------------------------------------------------------------------

def build_map_prompt() -> str:
    """Return the prompt sent to the vision model for map reading.

    The reply shape is the simulator's world dict (headings N, E, S, W — not
    arrows), so an accepted reply can be passed straight to check_world() and
    used as a world.  The prompt is perception-only: the backend verifies the
    proposed world independently.
    """
    last = SIZE - 1
    rules = [
        f"Coordinates are zero-based; x and y must be integers from 0 through {last}.",
        "Include every visible wall.",
        "Do not invent walls.",
        "Do not omit visible walls.",
        "Do not place the robot inside a wall.",
        "Do not place the goal inside a wall.",
        "Robot and goal must be different cells.",
        "Do not shift coordinates because of image margins.",
        f"The actual {SIZE}×{SIZE} grid defines the coordinate system.",
        "Determine direction from the visible robot arrow; dir must be one of N, E, S, W.",
        'If no direction arrow is visible, use "E" (the simulator default heading); '
        "never infer direction from the robot's position.",
        "Do not perform pathfinding.",
        "Do not modify the map to make it solvable.",
        "Do not add additional fields.",
    ]
    numbered_rules = "\n".join(
        f"{i}. {rule}" for i, rule in enumerate(rules, start=1)
    )
    return (
        "You are a computer vision system that converts a top-down robot maze "
        "image into a structured navigation world.\n\n"
        f"The image contains an exactly {SIZE}×{SIZE} grid.\n\n"
        "Coordinate system:\n"
        f"* leftmost column = x=0, rightmost column = x={last}\n"
        f"* top row = y=0, bottom row = y={last}\n"
        f"* coordinates are zero-based integers from 0 through {last}\n\n"
        "Objects:\n"
        "* R identifies the robot starting cell.\n"
        "* An arrow associated with R identifies the robot's facing direction "
        "(up = N, right = E, down = S, left = W).\n"
        "* G identifies the target goal.\n"
        "* Dark filled cells or cells marked X identify walls.\n"
        "* Empty cells are traversable.\n\n"
        "Determine the map from the visible image.\n\n"
        "Return exactly:\n"
        '{"robot": [x, y], "dir": "E", "goal": [x, y], "walls": [[x, y], [x, y]]}\n\n'
        "Rules:\n"
        f"{numbered_rules}\n\n"
        "The backend will independently verify the proposed world. "
        "Your job is perception only.\n\n"
        "Return ONLY the raw JSON object. Do not return markdown, code fences, "
        "explanations, comments, greetings, or any additional text."
    )


# ---------------------------------------------------------------------------
# 3.  read_map
# ---------------------------------------------------------------------------

def _parse_world_json(text: str) -> dict:
    """Extract a JSON object from *text*, stripping code fences if present.

    Thin wrapper: the one implementation is
    ``backend.parsing.parse_world_reply``.
    """
    return parse_world_reply(text)


def read_map(
    image_bytes: bytes,
    mime_type: str,
    ask_vision,
    max_tries: int = 2,
) -> tuple[dict | None, list[dict]]:
    """Ask a vision model to read a hand-drawn map, validate, and retry once.

    Parameters
    ----------
    image_bytes:
        Raw image data to send to the model.
    mime_type:
        MIME type string, e.g. ``"image/png"`` or ``"image/jpeg"``.
    ask_vision:
        Callable with signature
        ``ask_vision(prompt: str, image_bytes: bytes, mime_type: str) -> str``.
        Compatible with ``ask_vision_api`` and ``ask_vision_ollama``.
    max_tries:
        Maximum attempts (default 2).  On the second attempt the failure
        reason from ``check_world`` is appended to the prompt.

    Returns
    -------
    (world, history)
        *world* is the validated dict, or ``None`` if all tries failed.
        *history* has one record per attempt:
        ``{attempt, prompt, reply, ok, feedback}``.
    """
    history: list[dict] = []
    prompt = build_map_prompt()

    for attempt in range(1, max_tries + 1):
        reply = ""
        try:
            reply = ask_vision(prompt, image_bytes, mime_type)
        except Exception as exc:  # noqa: BLE001
            # An SDK error can embed request details; scrub before this feedback
            # reaches the history, the UI or a log.
            feedback = redact_secrets(f"ask_vision raised an error: {exc}")
            print(f"  [map attempt {attempt}/{max_tries}] ask error — {feedback}")
            history.append({"attempt": attempt, "prompt": prompt,
                            "reply": reply, "ok": False, "feedback": feedback})
            if attempt < max_tries:
                prompt = _repair_map_prompt(feedback)
            continue

        # ── Parse JSON ────────────────────────────────────────────────────
        try:
            world = _parse_world_json(reply)
        except Exception as exc:  # noqa: BLE001
            feedback = redact_secrets(f"could not parse reply as JSON: {exc}")
            print(f"  [map attempt {attempt}/{max_tries}] parse error — {feedback}")
            history.append({"attempt": attempt, "prompt": prompt,
                            "reply": reply, "ok": False, "feedback": feedback})
            if attempt < max_tries:
                prompt = _repair_map_prompt(feedback)
            continue

        # ── Validate ──────────────────────────────────────────────────────
        ok, feedback = check_world(world)
        print(
            f"  [map attempt {attempt}/{max_tries}] "
            + ("✓ valid world" if ok else f"✗ {feedback}")
        )
        history.append({"attempt": attempt, "prompt": prompt,
                        "reply": reply, "ok": ok, "feedback": feedback})

        if ok:
            return world, history

        if attempt < max_tries:
            prompt = _repair_map_prompt(feedback)

    return None, history


def _repair_map_prompt(reason: str) -> str:
    """Build a corrected-map prompt rooted in the original build_map_prompt."""
    return (
        build_map_prompt()
        + f"\n\nYour previous response was rejected.\nReason: {reason}\n"
        "Please look at the image again and provide a corrected JSON object."
    )


# ---------------------------------------------------------------------------
# 4.  ask_vision_api  /  ask_vision_ollama
# ---------------------------------------------------------------------------

def ask_vision_api(
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    model: str | None = None,
) -> str:
    """Send prompt + inline image to the Gemini API (google-genai SDK).

    Parameters
    ----------
    prompt:
        Text instruction for the model.
    image_bytes:
        Raw image bytes (e.g. PNG or JPEG).
    mime_type:
        MIME type of the image, e.g. ``"image/png"``.
    model:
        Override the default ``GEMMA_API_MODEL``.

    Returns
    -------
    str
        Raw text reply from the model.

    Raises
    ------
    RuntimeError
        If no API key is configured, the google-genai SDK is unavailable, or
        the call fails.
    """
    if not api_key():
        raise RuntimeError(missing_api_key_message())

    try:
        from google import genai              # noqa: PLC0415
        from google.genai import types        # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "google-genai package is not installed. "
            "Install it with: pip install google-genai"
        ) from exc

    if model is None:
        model = GEMMA_API_MODEL

    client = genai.Client()   # reads GEMINI_API_KEY from environment
    r = client.models.generate_content(
        model=model,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    types.Part.from_text(prompt),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=TEMPERATURE,
        ),
    )
    return r.text


def ask_vision_ollama(
    prompt: str,
    image_bytes: bytes,
    mime_type: str,
    model: str | None = None,
) -> str:
    """Send prompt + inline image to a local Ollama vision model.

    Parameters
    ----------
    prompt:
        Text instruction for the model.
    image_bytes:
        Raw image bytes.
    mime_type:
        Accepted for API symmetry; Ollama does not require explicit typing.
    model:
        Override the default ``OLLAMA_MODEL``.

    Returns
    -------
    str
        Raw text reply from the model.

    Raises
    ------
    RuntimeError
        If the ollama package is unavailable or if the call fails.
    """
    try:
        import ollama as _ollama             # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "ollama package is not installed. "
            "Install it with: pip install ollama"
        ) from exc

    if model is None:
        model = OLLAMA_MODEL

    # The ollama Python library accepts raw bytes in the images list.
    r = _ollama.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [image_bytes],
            }
        ],
    )
    content = r.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError(
            f"Ollama returned an empty response for model '{model}'. "
            "Make sure the model is loaded and supports vision."
        )
    return content


# ---------------------------------------------------------------------------
# Self-test (no AI, no network)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from gemmabot.simulator import new_world

    SEP = "=" * 60

    # ══════════════════════════════════════════════════════════════════
    # Part 1: check_world — four hand-made worlds, no AI
    # ══════════════════════════════════════════════════════════════════
    print(SEP)
    print("Part 1: check_world — pure validation + BFS, no AI")
    print(SEP)

    # ── Case 1: valid world ───────────────────────────────────────────
    print("\nCase 1: valid world (default new_world())")
    w1 = new_world()
    ok1, msg1 = check_world(w1)
    print(f"  ok={ok1}  msg={msg1!r}")
    assert ok1 is True, f"FAIL: expected True, got ({ok1}, {msg1!r})"

    # ── Case 2: goal is on a wall ────────────────────────────────────
    print("\nCase 2: goal sits on a wall cell")
    w2 = new_world()
    w2["goal"] = [3, 1]     # [3,1] is in the wall list
    ok2, msg2 = check_world(w2)
    print(f"  ok={ok2}  msg={msg2!r}")
    assert ok2 is False
    assert "wall" in msg2.lower(), f"FAIL: expected 'wall' in message, got {msg2!r}"

    # ── Case 3: wall cell out of bounds ──────────────────────────────
    print("\nCase 3: a wall coordinate is out of grid bounds")
    w3 = new_world()
    w3["walls"].append([8, 8])   # SIZE=8, so 8 is out of bounds
    ok3, msg3 = check_world(w3)
    print(f"  ok={ok3}  msg={msg3!r}")
    assert ok3 is False
    assert "outside" in msg3.lower(), f"FAIL: expected 'outside' in message, got {msg3!r}"

    # ── Case 4: goal is unreachable (completely walled off) ──────────
    print("\nCase 4: goal is unreachable (surrounded by walls + grid edge)")
    w4 = {
        "robot": [0, 0],
        "dir": "E",
        "goal": [7, 7],
        # Seal off [7,7] with a three-wall fence + corner ensures no path
        "walls": [[6, 7], [7, 6], [6, 6]],
    }
    ok4, msg4 = check_world(w4)
    print(f"  ok={ok4}  msg={msg4!r}")
    assert ok4 is False
    assert "unreachable" in msg4.lower(), (
        f"FAIL: expected 'unreachable' in message, got {msg4!r}"
    )

    print("\n✓ All check_world cases passed.")

    # ══════════════════════════════════════════════════════════════════
    # Part 2: read_map with FAKE ask_vision — no network
    # ══════════════════════════════════════════════════════════════════
    print()
    print(SEP)
    print("Part 2: read_map — fake ask_vision, no AI")
    print(SEP)

    # A valid world JSON (matches new_world() layout)
    VALID_JSON = json.dumps({
        "robot": [0, 0],
        "dir": "E",
        "goal": [6, 5],
        "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]],
    })

    # An impossible world JSON (goal on a wall)
    BAD_JSON = json.dumps({
        "robot": [0, 0],
        "dir": "E",
        "goal": [3, 0],   # wall cell → fails check_world
        "walls": [[3, 0], [3, 1]],
    })

    FAKE_IMAGE = b"\x00"   # 1-byte placeholder — never sent to any real API

    # ── Test A: fake returns valid JSON straight away ─────────────────
    print("\nTest A: fake returns valid JSON on the first attempt")
    _a_calls = [0]
    def fake_ask_valid(prompt, image_bytes, mime_type):
        _a_calls[0] += 1
        return VALID_JSON

    world_a, hist_a = read_map(FAKE_IMAGE, "image/png", fake_ask_valid, max_tries=2)
    print(f"  world returned : {world_a is not None}  (expected True)")
    print(f"  attempts made  : {len(hist_a)}  (expected 1)")
    print(f"  ask called     : {_a_calls[0]}  (expected 1)")
    assert world_a is not None, "FAIL: should have returned a world"
    assert len(hist_a) == 1
    assert hist_a[0]["ok"] is True
    assert _a_calls[0] == 1

    # ── Test B: fake returns bad JSON first, valid on retry ───────────
    print("\nTest B: bad JSON first → valid on second attempt")
    _b_calls = [0]
    def fake_ask_retry(prompt, image_bytes, mime_type):
        _b_calls[0] += 1
        return VALID_JSON if _b_calls[0] >= 2 else BAD_JSON

    world_b, hist_b = read_map(FAKE_IMAGE, "image/png", fake_ask_retry, max_tries=2)
    print(f"  world returned : {world_b is not None}  (expected True)")
    print(f"  attempts made  : {len(hist_b)}  (expected 2)")
    print(f"  attempt 1 ok   : {hist_b[0]['ok']}  (expected False — goal on wall)")
    print(f"  attempt 2 ok   : {hist_b[1]['ok']}  (expected True)")
    assert world_b is not None, "FAIL: should have returned a world on retry"
    assert len(hist_b) == 2
    assert hist_b[0]["ok"] is False
    assert "wall" in hist_b[0]["feedback"].lower()
    assert hist_b[1]["ok"] is True
    assert _b_calls[0] == 2
    # Verify the repair prompt carried the failure reason
    assert "wall" in hist_b[1]["prompt"].lower(), (
        "FAIL: repair prompt should contain the check_world failure reason"
    )

    # ── Test C: fake always returns impossible world → returns None ───
    print("\nTest C: always-bad JSON → read_map returns None after max_tries")
    _c_calls = [0]
    def fake_ask_always_bad(prompt, image_bytes, mime_type):
        _c_calls[0] += 1
        return BAD_JSON

    world_c, hist_c = read_map(FAKE_IMAGE, "image/png", fake_ask_always_bad, max_tries=2)
    print(f"  world returned : {world_c}  (expected None)")
    print(f"  attempts made  : {len(hist_c)}  (expected 2)")
    print(f"  ask called     : {_c_calls[0]}  (expected 2)")
    assert world_c is None, "FAIL: should have returned None"
    assert len(hist_c) == 2
    assert all(not r["ok"] for r in hist_c)
    assert _c_calls[0] == 2

    # ── Test D: fake returns garbled non-JSON text ────────────────────
    print("\nTest D: garbled non-JSON → parse error captured, returns None")
    def fake_ask_garbled(prompt, image_bytes, mime_type):
        return "Here is the map! The robot starts at top-left and goes right."

    world_d, hist_d = read_map(FAKE_IMAGE, "image/png", fake_ask_garbled, max_tries=2)
    print(f"  world returned : {world_d}  (expected None)")
    print(f"  attempt 1 ok   : {hist_d[0]['ok']}  (expected False — parse error)")
    assert world_d is None
    assert hist_d[0]["ok"] is False
    assert "json" in hist_d[0]["feedback"].lower()

    print()
    print(SEP)
    print("All mapvision tests passed.")
