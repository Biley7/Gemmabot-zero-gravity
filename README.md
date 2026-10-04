# Gemmabot

A virtual 8x8 grid robot planned by Gemma, shown in a Streamlit app.

## Setup

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

## Run

Start the Streamlit app:
```bash
streamlit run app.py
```

## Test

Run the test suite:
```bash
pytest
```

## Team Roles

- **BACKEND**: Owns `gemmabot/` directory (except `schemas.py`)
- **FRONTEND**: Owns `app.py` and `frontend/` directory
- **SHARED**: `schemas.py` and `docs/CONTRACTS.md` require agreement from both teams
