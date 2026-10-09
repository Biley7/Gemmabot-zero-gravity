# Compatibility shim — real implementation moved to backend/verifier/harness.py
from backend.verifier.harness import *  # noqa: F401, F403
from backend.verifier.harness import dry_run, plan_with_repair, _repair_prompt  # noqa: F401

if __name__ == "__main__":
    # ``python -m gemmabot.harness`` is the documented no-network self-test
    # (RUN_AND_DEPLOY.md §2.4).  A bare re-export used to run this file's own
    # (empty) ``__main__``, so the command printed nothing and exited 0; run the
    # real module's self-test instead.
    import runpy

    runpy.run_module("backend.verifier.harness", run_name="__main__")
