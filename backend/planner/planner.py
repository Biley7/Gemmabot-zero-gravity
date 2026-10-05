"""AI planner that calls Gemma models to generate action plans.

Owner: BACKEND
"""
import json
import re
from google import genai
from google.genai import types
import ollama

from gemmabot.config import GEMMA_API_MODEL, OLLAMA_MODEL, TEMPERATURE
from gemmabot.prompts import SYSTEM, world_prompt


def parse_plan(text):
    """Pull the JSON object out of a model reply (handles ``` fences)."""
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON found in reply")
    data = json.loads(text[start:end + 1])
    return data.get("thought", ""), data.get("actions", [])


def ask_api(instruction, world, model=None):
    """Call Gemini API with Gemma model."""
    if model is None:
        model = GEMMA_API_MODEL
    client = genai.Client()  # uses GEMINI_API_KEY
    r = client.models.generate_content(
        model=model,
        contents=world_prompt(world, instruction),
        config=types.GenerateContentConfig(system_instruction=SYSTEM, temperature=TEMPERATURE),
    )
    return r.text


def ask_ollama(instruction, world, model=None):
    """Call local Ollama with Gemma model."""
    if model is None:
        model = OLLAMA_MODEL
    r = ollama.chat(model=model, messages=[
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": world_prompt(world, instruction)},
    ])
    return r["message"]["content"]
