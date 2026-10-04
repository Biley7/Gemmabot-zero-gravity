"""Prompts for AI model interaction.

Owner: BACKEND
"""
import json
from gemmabot.config import SIZE


SYSTEM = f"""You are the brain of a robot on an {SIZE}x{SIZE} grid.
Coordinates are [x, y]. x grows to the east (right), y grows to the south (down).
Headings: N means y-1, E means x+1, S means y+1, W means x-1.
The robot can only do these actions:
  {{"cmd":"forward","steps":<integer 1-7>}}
  {{"cmd":"turn_left"}}   (90 degrees counter-clockwise)
  {{"cmd":"turn_right"}}  (90 degrees clockwise)
Walls and the grid edge block movement. Plan the whole route in one go.
Reply with ONLY JSON, no extra text, in this shape:
{{"thought":"one short sentence","actions":[...]}}"""


def world_prompt(world, instruction):
    return f"World state: {json.dumps(world)}\nInstruction: {instruction}"
