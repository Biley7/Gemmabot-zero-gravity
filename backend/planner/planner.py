"""AI planner that calls Gemma models to generate action plans.

Owner: BACKEND

This module is one *implementation* of ``backend.guard.planner.Planner``
(Gemini / Ollama transports).  Parsing lives in ``backend.parsing``.
"""
from backend.parsing import parse_plan_reply
from google import genai
from google.genai import types
import ollama

from gemmabot.config import (
    GEMMA_API_MODEL,
    OLLAMA_MODEL,
    TEMPERATURE,
    api_key,
    missing_api_key_message,
)
from gemmabot.prompts import SYSTEM, world_prompt


def parse_plan(text):
    """Pull the JSON object out of a model reply (handles ``` fences).

    Thin compatibility wrapper: the one implementation is
    ``backend.parsing.parse_plan_reply``.
    """
    return parse_plan_reply(text)


def ask_api(instruction, world, model=None):
    """Call Gemini API with Gemma model.

    Fails before the client is constructed when no credential is configured,
    so a missing key surfaces as a readable message instead of a network or
    SDK error.
    """
    if not api_key():
        raise RuntimeError(missing_api_key_message())
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
