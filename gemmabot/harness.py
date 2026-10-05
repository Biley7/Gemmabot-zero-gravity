# Compatibility shim — real implementation moved to backend/verifier/harness.py
from backend.verifier.harness import *  # noqa: F401, F403
from backend.verifier.harness import dry_run, plan_with_repair, _repair_prompt  # noqa: F401
