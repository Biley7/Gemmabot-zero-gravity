"""Map vision — hand-drawn map reader and world validator.

Owner: BACKEND

Public API
----------
check_world(world) -> (bool, str)
    Pure validation + BFS reachability.  No AI.  No network.

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
import re
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# Constants (mirrored from config / simulator so this module stands alone)
# ---------------------------------------------------------------------------
from gemmabot.config import SIZE, GEMMA_API_MODEL, OLLAMA_MODEL, TEMPERATURE
from gemmabot.simulator import DIRS


# ---------------------------------------------------------------------------
# 1.  check_world — pure code, no AI
# ---------------------------------------------------------------------------

def check_world(world: Any) -> tuple[bool, str]:
    """Validate a world dict for correctness and reachability.

    Parameters
    ----------
    world:
        Any value — the function never raises on bad input.

    Returns
    -------
    (True, "ok")
        World is structurally valid and the goal is reachable from start.
    (False, reason)
        Describes the first problem found.
    """
    # ── Type guard ────────────────────────────────────────────────────────
    if not isinstance(world, dict):
        return False, f"world must be a dict, got {type(world).__name__}"

    # ── Required keys ─────────────────────────────────────────────────────
    required = {"robot": list, "dir": str, "goal": list, "walls": list}
    for key, expected_type in required.items():
        if key not in world:
            return False, f"missing required key: '{key}'"
        if not isinstance(world[key], expected_type):
            return False, (
                f"'{key}' must be {expected_type.__name__}, "
                f"got {type(world[key]).__name__}"
            )

    robot = world["robot"]
    goal  = world["goal"]
    walls = world["walls"]
    heading = world["dir"]

    # ── robot and goal must be [x, y] int lists ───────────────────────────
    for name, cell in (("robot", robot), ("goal", goal)):
        if len(cell) != 2 or not all(isinstance(v, int) for v in cell):
            return False, f"'{name}' must be a list of two ints, got {cell!r}"

    # ── walls must be a list of [x, y] int pairs ─────────────────────────
    for i, w in enumerate(walls):
        if (not isinstance(w, list) or len(w) != 2
                or not all(isinstance(v, int) for v in w)):
            return False, f"walls[{i}] must be a list of two ints, got {w!r}"

    # ── heading ───────────────────────────────────────────────────────────
    if heading not in DIRS:
        return False, f"heading '{heading}' is not valid; expected one of {DIRS}"

    # ── bounds check (0 ≤ x, y < SIZE) ───────────────────────────────────
    def in_bounds(cell: list) -> bool:
        return 0 <= cell[0] < SIZE and 0 <= cell[1] < SIZE

    if not in_bounds(robot):
        return False, f"robot position {robot} is outside the {SIZE}×{SIZE} grid"
    if not in_bounds(goal):
        return False, f"goal position {goal} is outside the {SIZE}×{SIZE} grid"
    for i, w in enumerate(walls):
        if not in_bounds(w):
            return False, (
                f"walls[{i}] = {w} is outside the {SIZE}×{SIZE} grid"
            )

    # ── wall-overlap checks ───────────────────────────────────────────────
    wall_set = {tuple(w) for w in walls}
    if tuple(robot) in wall_set:
        return False, f"robot start {robot} is on a wall"
    if tuple(goal) in wall_set:
        return False, f"goal {goal} is on a wall"

    # ── start ≠ goal ──────────────────────────────────────────────────────
    if robot == goal:
        return False, f"robot start and goal are the same cell {robot}"

    # ── BFS reachability (4-directional, ignores heading) ─────────────────
    start = tuple(robot)
    target = tuple(goal)
    visited = {start}
    queue: deque[tuple[int, int]] = deque([start])
    found = False

    while queue:
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
            break

    if not found:
        return False, (
            f"goal is unreachable: no path from {robot} to {goal} "
            f"on a {SIZE}×{SIZE} grid with {len(walls)} wall(s)"
        )

    return True, "ok"


# ---------------------------------------------------------------------------
# 2.  build_map_prompt
# ---------------------------------------------------------------------------

def build_map_prompt() -> str:
    """Return a prompt instructing the vision model to output a world dict.

    The field names match the real world dict used by the simulator so the
    result can be passed directly to check_world and new_world().
    """
    return (
        f"This image shows a hand-drawn {SIZE}×{SIZE} grid map of a robot world.\n"
        "Identify:\n"
        "  - The robot's starting cell (column x, row y — zero-indexed from top-left)\n"
        "  - The robot's heading (one of: N, E, S, W)\n"
        "  - The goal cell\n"
        "  - All wall cells\n\n"
        "Reply with ONLY a JSON object — no explanation, no code fences — "
        "in this exact shape:\n"
        '{"robot": [x, y], "dir": "E", "goal": [x, y], '
        '"walls": [[x, y], ...]}\n\n'
        f"The grid is {SIZE} columns wide and {SIZE} rows tall. "
        "All coordinates must be integers in the range [0, 7]."
    )


# ---------------------------------------------------------------------------
# 3.  read_map
# ---------------------------------------------------------------------------

def _parse_world_json(text: str) -> dict:
    """Extract a JSON object from *text*, stripping code fences if present.

    Raises ValueError if no valid JSON object is found.
    """
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model reply")
    return json.loads(text[start:end + 1])


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
            feedback = f"ask_vision raised an error: {exc}"
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
            feedback = f"could not parse reply as JSON: {exc}"
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
        If the google-genai SDK is unavailable or if the call fails.
    """
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
