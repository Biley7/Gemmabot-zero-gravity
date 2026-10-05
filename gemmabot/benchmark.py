"""Benchmark runner for GemmaBot.

Owner: BACKEND

Measures success rate, average attempts, and latency for each backend and
repair setting (max_tries=1 = no repair, max_tries=3 = with repair).

Usage
-----
    python -m gemmabot.benchmark --backend ollama          # default
    python -m gemmabot.benchmark --backend api
    python -m gemmabot.benchmark --backend both
    python -m gemmabot.benchmark --dry                     # fake model, no network
    python -m gemmabot.benchmark --backend ollama --runs 5

Public API
----------
run_benchmark(backends, cases, runs_per_case, max_tries_list, delay) -> list[dict]
summarize(results) -> str
save_results(results, path) -> None
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Callable

from gemmabot.simulator import new_world
from backend.verifier.harness import plan_with_repair
from backend.logger.logger import log_run

# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
# new_world() is fixed — no parameters.  To create variants we deep-copy and
# mutate only the fields that actually exist in the world dict.
# World shape: robot=[x,y], dir="N/E/S/W", goal=[x,y], walls=[[x,y],...]

def _world(**overrides) -> dict:
    """Return a deep copy of new_world() with any overrides applied."""
    w = copy.deepcopy(new_world())
    w.update(overrides)
    return w


TEST_CASES: list[dict] = [
    # 1. Default map — robot [0,0] E → goal [6,5]
    {
        "name": "default_map",
        "instruction": (
            "Navigate from [0,0] facing East to goal [6,5]. "
            "Walls block column x=3 (rows 0-3) and x=5 (rows 4-6). "
            "Plan a clear route using forward, turn_left, turn_right."
        ),
        "world": _world(),
    },

    # 2. One-turn case — goal is directly south, robot faces East
    {
        "name": "one_turn_south",
        "instruction": (
            "Navigate from [0,0] facing East to goal [0,6]. "
            "The goal is directly south. Turn right (to face South) "
            "then move forward."
        ),
        "world": _world(goal=[0, 6], walls=[]),
    },

    # 3. Several turns — goal is directly behind the robot (West)
    {
        "name": "several_turns_west",
        "instruction": (
            "Navigate from [0,0] facing East to goal [0, 4]. "
            "The goal is south of the start. "
            "Turn and move south to reach it."
        ),
        "world": _world(goal=[0, 4], walls=[]),
    },

    # 4. Long detour — goal on the other side of a full vertical wall
    {
        "name": "long_detour_wall",
        "instruction": (
            "Navigate from [0,0] facing East to goal [7,4]. "
            "A full vertical wall at x=4 (rows 0-6) blocks direct East movement. "
            "You must go South past the wall end at row 7, then East, then North."
        ),
        "world": _world(
            goal=[7, 4],
            walls=[[4, 0], [4, 1], [4, 2], [4, 3], [4, 4], [4, 5], [4, 6]],
        ),
    },

    # 5. Tricky — goal is surrounded on three sides; only one entry from South
    {
        "name": "tricky_pocket",
        "instruction": (
            "Navigate from [0,0] facing East to goal [4,2]. "
            "Walls block [3,2], [5,2], and [4,1] — the goal is in a pocket "
            "open only from the South at [4,3]. "
            "Approach from below: go East to x=4, go South to y=3, then turn North one step."
        ),
        "world": _world(
            goal=[4, 2],
            walls=[[3, 2], [5, 2], [4, 1]],
        ),
    },
]


# ---------------------------------------------------------------------------
# Fake ask function for --dry mode
# ---------------------------------------------------------------------------

# The correct solution for each case (validated manually against the world).
_DRY_PLANS: dict[str, list[dict]] = {
    "default_map": [
        {"cmd": "turn_right"},          # face S
        {"cmd": "forward", "steps": 7}, # [0,0]→[0,7]
        {"cmd": "turn_left"},           # face E
        {"cmd": "forward", "steps": 6}, # [0,7]→[6,7]
        {"cmd": "turn_left"},           # face N
        {"cmd": "forward", "steps": 2}, # [6,7]→[6,5] ✓
    ],
    "one_turn_south": [
        {"cmd": "turn_right"},          # face S
        {"cmd": "forward", "steps": 6}, # [0,0]→[0,6] ✓
    ],
    "several_turns_west": [
        {"cmd": "turn_right"},          # face S
        {"cmd": "forward", "steps": 4}, # [0,0]→[0,4] ✓
    ],
    "long_detour_wall": [
        {"cmd": "turn_right"},          # face S
        {"cmd": "forward", "steps": 7}, # [0,0]→[0,7]
        {"cmd": "turn_left"},           # face E
        {"cmd": "forward", "steps": 7}, # [0,7]→[7,7]
        {"cmd": "turn_left"},           # face N
        {"cmd": "forward", "steps": 3}, # [7,7]→[7,4] ✓
    ],
    "tricky_pocket": [
        # Go south first to y=3, then east to x=4, then north into pocket.
        {"cmd": "turn_right"},          # face S  [0,0]
        {"cmd": "forward", "steps": 3}, # [0,0]→[0,3]  (south corridor, no walls)
        {"cmd": "turn_left"},           # face E  [0,3]
        {"cmd": "forward", "steps": 4}, # [0,3]→[4,3]  (x=3,y=3 not walled; x=4 not blocked at y=3)
        {"cmd": "turn_left"},           # face N  [4,3]
        {"cmd": "forward", "steps": 1}, # [4,3]→[4,2] ✓
    ],
}


def _make_dry_ask(case_name: str, succeed_on_attempt: int = 1) -> Callable:
    """Return a fake ask function that gives a correct plan on *succeed_on_attempt*.

    On earlier attempts it returns a wall-hitting plan so the repair loop has
    something to work with, making the dry run exercise the full pipeline.
    """
    calls = [0]
    correct = _DRY_PLANS.get(case_name, _DRY_PLANS["default_map"])
    bad = [{"cmd": "forward", "steps": 7}]  # always blocked somewhere

    def _ask(instruction: str, world: dict) -> str:
        calls[0] += 1
        plan = correct if calls[0] >= succeed_on_attempt else bad
        return json.dumps({"thought": "dry-run fake", "actions": plan})

    return _ask


# ---------------------------------------------------------------------------
# run_benchmark
# ---------------------------------------------------------------------------

def run_benchmark(
    backends: dict[str, Callable],
    cases: list[dict] = TEST_CASES,
    runs_per_case: int = 3,
    max_tries_list: tuple[int, ...] = (1, 3),
    delay: float = 2.0,
    dry: bool = False,
) -> list[dict]:
    """Run the full benchmark matrix.

    Parameters
    ----------
    backends:
        ``{"ollama": ask_ollama, "api": ask_api}`` or any subset.
        In ``--dry`` mode this is replaced by per-case fake functions.
    cases:
        List of test-case dicts (name, instruction, world).
    runs_per_case:
        How many independent runs per (backend × case × max_tries) cell.
    max_tries_list:
        Repair settings to compare.  ``1`` = no repair, ``3`` = with repair.
    delay:
        Seconds to sleep between real API calls.
    dry:
        If True, ignore *backends* and use fake ask functions.

    Returns
    -------
    list[dict]
        One record per individual run with keys:
        backend, case, max_tries, run, success, attempts, latency, error.
    """
    total_calls = len(backends) * len(cases) * len(max_tries_list) * runs_per_case
    print(f"\nBenchmark plan: {len(backends)} backend(s) × {len(cases)} cases × "
          f"{len(max_tries_list)} max_tries settings × {runs_per_case} run(s) "
          f"= {total_calls} total model call-groups")
    print("(Each call-group may use up to max_tries model calls internally.)\n")

    if not dry:
        ans = input("Proceed? [y/n] ").strip().lower()
        if ans != "y":
            print("Benchmark cancelled.")
            return []

    results: list[dict] = []
    call_count = 0

    for backend_name, ask_fn in backends.items():
        for case in cases:
            for max_tries in max_tries_list:
                for run_idx in range(1, runs_per_case + 1):
                    call_count += 1
                    label = (f"[{call_count}/{total_calls}] "
                             f"{backend_name} | {case['name']} | "
                             f"max_tries={max_tries} | run {run_idx}")
                    print(label)

                    # In dry mode, swap in a fake ask per case.
                    # On run 1 succeed immediately; run 2 succeed on attempt 2;
                    # run 3 succeed on attempt min(3, max_tries) — exercises repair.
                    if dry:
                        succeed_on = min(run_idx, max_tries)
                        effective_ask = _make_dry_ask(case["name"], succeed_on)
                    else:
                        effective_ask = ask_fn

                    t0 = time.perf_counter()
                    actions = None
                    attempts = 0
                    history: list[dict] = []
                    error_text = ""

                    try:
                        actions, attempts, history = plan_with_repair(
                            instruction=case["instruction"],
                            world=copy.deepcopy(case["world"]),
                            ask=effective_ask,
                            max_tries=max_tries,
                        )
                    except Exception as exc:  # noqa: BLE001
                        error_text = f"{type(exc).__name__}: {exc}"
                        print(f"  ERROR: {error_text}")
                        attempts = max_tries
                        time.sleep(5)  # back off after unexpected errors

                    latency = time.perf_counter() - t0

                    record = {
                        "backend":   backend_name,
                        "case":      case["name"],
                        "max_tries": max_tries,
                        "run":       run_idx,
                        "success":   actions is not None,
                        "attempts":  attempts,
                        "latency":   round(latency, 3),
                        "error":     error_text,
                    }
                    results.append(record)

                    # Persist to log.
                    log_run(
                        instruction=case["instruction"],
                        backend=backend_name,
                        actions=actions,
                        attempts=attempts,
                        history=history,
                        latency=latency,
                    )

                    status = "✓" if record["success"] else "✗"
                    print(f"  {status} success={record['success']}  "
                          f"attempts={record['attempts']}  "
                          f"latency={record['latency']:.2f}s")

                    # Rate-limit delay between real API calls.
                    if not dry and call_count < total_calls:
                        time.sleep(delay)

    return results


# ---------------------------------------------------------------------------
# summarize
# ---------------------------------------------------------------------------

def summarize(results: list[dict]) -> str:
    """Build a Markdown summary table from benchmark results.

    Returns a string with:
    - An aggregate table: backend × max_tries → success %, avg attempts, avg latency
    - A per-case breakdown table
    """
    if not results:
        return "_No results to summarize._\n"

    from collections import defaultdict

    # ── Aggregate: (backend, max_tries) ──────────────────────────────────
    agg: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        agg[(r["backend"], r["max_tries"])].append(r)

    agg_lines = [
        "## Aggregate results\n",
        "| Backend | max_tries | Success % | Avg attempts | Avg latency (s) | Runs |",
        "|---------|-----------|----------:|-------------:|----------------:|-----:|",
    ]
    for (backend, mt), rows in sorted(agg.items()):
        n = len(rows)
        sr = 100.0 * sum(r["success"] for r in rows) / n
        aa = sum(r["attempts"] for r in rows) / n
        al = sum(r["latency"] for r in rows) / n
        repair_label = "no repair" if mt == 1 else f"repair ≤{mt}"
        agg_lines.append(
            f"| {backend} | {mt} ({repair_label}) | {sr:.0f}% | {aa:.2f} | {al:.3f} | {n} |"
        )

    # ── Per-case breakdown: (backend, case, max_tries) ────────────────────
    case_agg: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        case_agg[(r["backend"], r["case"], r["max_tries"])].append(r)

    case_lines = [
        "\n## Per-case breakdown\n",
        "| Backend | Case | max_tries | Success % | Avg attempts | Avg latency (s) |",
        "|---------|------|-----------|----------:|-------------:|----------------:|",
    ]
    for (backend, case, mt), rows in sorted(case_agg.items()):
        n = len(rows)
        sr = 100.0 * sum(r["success"] for r in rows) / n
        aa = sum(r["attempts"] for r in rows) / n
        al = sum(r["latency"] for r in rows) / n
        case_lines.append(
            f"| {backend} | {case} | {mt} | {sr:.0f}% | {aa:.2f} | {al:.3f} |"
        )

    return "\n".join(agg_lines) + "\n" + "\n".join(case_lines) + "\n"


# ---------------------------------------------------------------------------
# save_results
# ---------------------------------------------------------------------------

def save_results(
    results: list[dict],
    path: str = "benchmarks/results.json",
) -> None:
    """Save raw results as JSON and the Markdown table as results.md.

    Creates the ``benchmarks/`` directory if it does not exist.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Raw JSON
    with out.open("w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"[benchmark] Saved raw results → {out}")

    # Markdown table alongside the JSON
    md_path = out.with_suffix(".md")
    with md_path.open("w", encoding="utf-8") as fh:
        fh.write("# GemmaBot Benchmark Results\n\n")
        fh.write(summarize(results))
    print(f"[benchmark] Saved markdown table → {md_path}")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser():
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m gemmabot.benchmark",
        description="Run the GemmaBot planning benchmark.",
    )
    p.add_argument(
        "--backend",
        choices=["ollama", "api", "both"],
        default="ollama",
        help="Which model backend to use (default: ollama).",
    )
    p.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Runs per (backend × case × max_tries) cell (default: 3).",
    )
    p.add_argument(
        "--dry",
        action="store_true",
        help="Use a fake ask function — no network calls, free to run.",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds between real API calls (default: 2.0).",
    )
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.dry:
        # Fake backends — one per name so the table shows separate rows.
        backends: dict[str, Callable] = {}
        names = (
            ["ollama", "api"] if args.backend == "both"
            else [args.backend]
        )
        # The actual callable is replaced per-case inside run_benchmark when
        # dry=True, but we need a placeholder to drive the matrix.
        for name in names:
            backends[name] = lambda i, w: "{}"   # never actually called
    else:
        # Real backends — lazy import so the module loads without google/ollama.
        from backend.planner.planner import ask_api, ask_ollama  # noqa: PLC0415
        if args.backend == "ollama":
            backends = {"ollama": ask_ollama}
        elif args.backend == "api":
            backends = {"api": ask_api}
        else:
            backends = {"ollama": ask_ollama, "api": ask_api}

    results = run_benchmark(
        backends=backends,
        runs_per_case=args.runs,
        dry=args.dry,
        delay=args.delay,
    )

    if results:
        table = summarize(results)
        print("\n" + table)
        save_results(results)


if __name__ == "__main__":
    main()
