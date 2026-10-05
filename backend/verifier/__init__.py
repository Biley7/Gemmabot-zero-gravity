"""Verifier subpackage — re-exports the public API of harness.py."""
from backend.verifier.harness import dry_run, plan_with_repair

__all__ = ["dry_run", "plan_with_repair"]
