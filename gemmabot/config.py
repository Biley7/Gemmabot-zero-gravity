"""Configuration constants for the Gemmabot project.

Owner: BACKEND
"""
import os


# Grid configuration
SIZE = 8

# Simulation timing
STEP_DELAY = 0.5

# AI model parameters
TEMPERATURE = 0.2

# Repair loop configuration
MAX_REPAIRS = 2

# Model names (read from environment, with defaults)
GEMMA_API_MODEL = os.getenv("GEMMA_API_MODEL", "gemma-4-26b-a4b-it")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
