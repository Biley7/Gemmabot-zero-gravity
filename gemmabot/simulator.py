"""Virtual robot world simulation.

Owner: BACKEND
"""
from gemmabot.config import SIZE

# Physics constants
DIRS = ["N", "E", "S", "W"]                       # clockwise order
DELTA = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}  # x=column, y=row (down)
ARROW = {"N": "⬆️", "E": "➡️", "S": "⬇️", "W": "⬅️"}


def new_world():
    return {
        "robot": [0, 0],
        "dir": "E",
        "goal": [6, 5],
        "walls": [[3, 0], [3, 1], [3, 2], [3, 3], [5, 4], [5, 5], [5, 6]],
    }


def step(world, action):
    """Apply one action. Returns a log message."""
    cmd = action.get("cmd")
    if cmd == "turn_left":
        world["dir"] = DIRS[(DIRS.index(world["dir"]) - 1) % 4]
        return "turned left"
    if cmd == "turn_right":
        world["dir"] = DIRS[(DIRS.index(world["dir"]) + 1) % 4]
        return "turned right"
    if cmd == "forward":
        n = max(1, min(int(action.get("steps", 1)), SIZE - 1))
        dx, dy = DELTA[world["dir"]]
        for _ in range(n):
            nx, ny = world["robot"][0] + dx, world["robot"][1] + dy
            if not (0 <= nx < SIZE and 0 <= ny < SIZE) or [nx, ny] in world["walls"]:
                return f"blocked at {world['robot']}"
            world["robot"] = [nx, ny]
        return f"moved forward {n}"
    return f"unknown command: {action}"


def reached_goal(world):
    return world["robot"] == world["goal"]


def render(world):
    rows = []
    for y in range(SIZE):
        row = ""
        for x in range(SIZE):
            if [x, y] == world["robot"]:
                row += ARROW[world["dir"]]
            elif [x, y] == world["goal"]:
                row += "🎯"
            elif [x, y] in world["walls"]:
                row += "🧱"
            else:
                row += "⬜"
        rows.append(row)
    return rows
