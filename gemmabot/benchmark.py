"""RobotBench — the benchmark runner.

Owner: BACKEND

Evaluates AI-generated robot plans against deterministic simulation
environments.  Measures success rate, verification rejection rate, repair rate,
repair success rate, average actions, average attempts, latency, collision rate
and boundary violation rate for each backend and repair setting (max_tries=1 =
no repair, max_tries=3 = with repair).

Every record states its own ``mode``: ``"live"`` when a model really answered,
``"synthetic"`` when the scripted reader did.  That is what keeps a dry run from
being read as a measurement of a model it never called.  ``--dry`` replaces the
backends entirely, so it is recorded as the single ``dry`` backend rather than as
whatever names it was asked for.

Every result also names what it measured and over how many runs: the dataset,
the scenario, the model id, the backend, the mode, a timestamp, the run and
success/failure counts and the latency statistics (see :func:`result_records`).
A result whose sample is too small to compare is marked as such rather than
printed as a verdict about a model.

Usage
-----
    python -m gemmabot.benchmark --backend ollama          # default
    python -m gemmabot.benchmark --backend api
    python -m gemmabot.benchmark --backend both
    python -m gemmabot.benchmark --dry                     # scripted reader, no network
    python -m gemmabot.benchmark --backend ollama --runs 5

Public API
----------
PRODUCT / DATASET_ID / MIN_SAMPLE
dataset() / scenarios()       what this runner measures
run_benchmark(backends, cases, runs_per_case, max_tries_list, delay) -> list[dict]
latency_stats(values) -> dict
group_results(results) -> list[dict]
result_records(results) -> list[dict]     self-describing aggregate results
sample_verdict(runs) -> dict              whether a sample may be compared at all
summarize(results) -> str
save_results(results, path) -> None        raw results + the aggregate report
"""
from __future__ import annotations

import copy
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from gemmabot.config import BENCH_MIN_SAMPLE, GEMMA_API_MODEL, OLLAMA_MODEL
from gemmabot.simulator import new_world
from backend.verifier.harness import plan_with_repair, verify_plan
from backend.logger.logger import log_run, redact_secrets


# The product this module implements.  Named once so the CLI, the stored
# artifact, the report and the UI all call the same thing the same thing.
PRODUCT = "RobotBench"

# What the numbers were measured on.  A result without a dataset is not
# reproducible, so the id and the scenario names travel with every record.
DATASET_ID = "gemmabot-grid-v1"
DATASET_NOTE = "the 8x8 grid scenarios below, each run against the deterministic simulator"

# Below this many runs, a difference between two series is not evidence of a
# difference between two models — it is noise, and it must be reported as such.
# The floor itself is configuration (``BENCH_MIN_SAMPLE``) so the runner and the
# lab cannot disagree about it; this name is the runner's public alias.
MIN_SAMPLE = BENCH_MIN_SAMPLE


def dataset() -> dict:
    """The dataset this runner measures: its id, what it holds, its scenarios."""
    return {
        "id": DATASET_ID,
        "note": DATASET_NOTE,
        "scenarios": scenarios(),
    }


def scenarios() -> list[str]:
    """The scenario identifiers, in the order the runner runs them."""
    return [str(case["name"]) for case in TEST_CASES]


def backend_model(backend: str) -> str | None:
    """The model id a benchmark backend would call, or ``None``.

    Read from ``gemmabot.config`` — the same values the app uses — so a logged
    benchmark run names the model it measured.  A scripted (dry) run names none,
    because no model replied to it.
    """
    name = (backend or "").strip().lower()
    if name == "api":
        return GEMMA_API_MODEL
    if name in ("ollama", "local"):
        return OLLAMA_MODEL
    return None

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
    log_path: str = "logs/runs.jsonl",
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
    log_path:
        Run log to append each run to, so the benchmark's runs reach the same
        log the app reads and stay replayable from it.

    Returns
    -------
    list[dict]
        One record per individual run with keys:
        backend, requested_backend, mode, case, max_tries, run, success,
        attempts, latency, error.  ``mode`` is ``"synthetic"`` for a dry run and
        ``"live"`` otherwise; in dry mode ``backend`` is the scripted reader and
        ``requested_backend`` keeps the name the matrix was asked for.
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
    mode = "synthetic" if dry else "live"

    if dry:
        print("dry mode: one scripted reader answers every case, so the backend "
              "column is not a comparison — the runs are recorded as backend "
              "'dry', mode 'synthetic'.\n")

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
                        error_text = redact_secrets(f"{type(exc).__name__}: {exc}")
                        print(f"  ERROR: {error_text}")
                        attempts = max_tries
                        time.sleep(5)  # back off after unexpected errors

                    latency = time.perf_counter() - t0

                    # The verdict on the accepted plan, from the same verifier
                    # the app runs.  A benchmark plans and verifies; it never
                    # drives the robot, so ``ran`` is False rather than absent —
                    # "this run did not execute" is a fact worth recording.
                    report = (
                        verify_plan(copy.deepcopy(case["world"]), actions)
                        if actions is not None else None
                    )
                    # Every per-run record names what it measured and where to
                    # find the run again: the dataset and the scenario it came
                    # from, the model that would answer it, the mode, the time it
                    # ran, and the id of the run it appended to the log.
                    record = {
                        "dataset":   DATASET_ID,
                        "scenario":  case["name"],
                        "case":      case["name"],
                        "model":     backend_model("dry" if dry else backend_name),
                        "backend":   "dry" if dry else backend_name,
                        "requested_backend": backend_name,
                        "mode":      mode,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "run_id":    None,
                        "max_tries": max_tries,
                        "run":       run_idx,
                        "success":   actions is not None,
                        "verified":  report["ok"] if report is not None else None,
                        "attempts":  attempts,
                        "latency":   round(latency, 3),
                        "error":     error_text,
                    }

                    # Persist to log — with the world and the plan, so the run
                    # stays replayable, and with its mode, so the log separates
                    # scripted runs from real ones.
                    logged = log_run(
                        instruction=case["instruction"],
                        backend=record["backend"],
                        actions=actions,
                        attempts=attempts,
                        history=history,
                        latency=latency,
                        path=log_path,
                        world=copy.deepcopy(case["world"]),
                        mode=mode,
                        input_type="benchmark",
                        model=backend_model(record["backend"]),
                        verification=(
                            {"ok": report["ok"], "reason": report["reason"]}
                            if report is not None else None
                        ),
                        execution={"ran": False, "halted": None, "steps": None},
                    )
                    record["run_id"] = (
                        logged.get("run_id") if isinstance(logged, dict) else None
                    )
                    results.append(record)

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
    - An aggregate table: backend × mode × max_tries → success %, avg attempts,
      avg latency
    - A per-case breakdown table

    The mode column is not decoration: a synthetic (scripted) row and a live one
    are different measurements and must never be read as one comparison.
    """
    if not results:
        return "_No results to summarize._\n"

    from collections import defaultdict

    modes = sorted({r.get("mode") or "unrecorded" for r in results})
    header_note = ""
    if len(modes) > 1:
        header_note = (
            "> **Mixed modes.** These rows mix " +
            ", ".join(f"`{m}`" for m in modes) +
            " runs. Only `live` rows measure a model; `synthetic` rows measure "
            "the scripted reader and the repair loop.\n"
        )
    elif modes and modes[0] == "synthetic":
        header_note = (
            "> **Synthetic runs only.** Every row below was answered by the "
            "scripted reader (`--dry`), not by a model. These numbers measure "
            "the planning loop and the repair setting — not model accuracy.\n"
        )

    # ── Aggregate: (backend, mode, max_tries) ────────────────────────────
    agg: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        agg[(r["backend"], r.get("mode") or "unrecorded", r["max_tries"])].append(r)

    agg_lines = [
        "## Aggregate results\n",
        "| Backend | Mode | max_tries | Success % | Avg attempts | Avg latency (s) | Runs |",
        "|---------|------|-----------|----------:|-------------:|----------------:|-----:|",
    ]
    for (backend, mode, mt), rows in sorted(agg.items()):
        n = len(rows)
        sr = 100.0 * sum(r["success"] for r in rows) / n
        aa = sum(r["attempts"] for r in rows) / n
        al = sum(r["latency"] for r in rows) / n
        repair_label = "no repair" if mt == 1 else f"repair ≤{mt}"
        agg_lines.append(
            f"| {backend} | {mode} | {mt} ({repair_label}) | {sr:.0f}% | {aa:.2f} | {al:.3f} | {n} |"
        )

    # ── Per-case breakdown: (backend, mode, case, max_tries) ──────────────
    case_agg: dict[tuple, list[dict]] = defaultdict(list)
    for r in results:
        case_agg[(r["backend"], r.get("mode") or "unrecorded", r["case"],
                  r["max_tries"])].append(r)

    case_lines = [
        "\n## Per-case breakdown\n",
        "| Backend | Mode | Case | max_tries | Success % | Avg attempts | Avg latency (s) |",
        "|---------|------|------|-----------|----------:|-------------:|----------------:|",
    ]
    for (backend, mode, case, mt), rows in sorted(case_agg.items()):
        n = len(rows)
        sr = 100.0 * sum(r["success"] for r in rows) / n
        aa = sum(r["attempts"] for r in rows) / n
        al = sum(r["latency"] for r in rows) / n
        case_lines.append(
            f"| {backend} | {mode} | {case} | {mt} | {sr:.0f}% | {aa:.2f} | {al:.3f} |"
        )

    # The smallest cell is the weakest evidence in the table, so that is the
    # sample size the caution is stated for.
    smallest = min((len(rows) for rows in agg.values()), default=0)
    return header_note + "\n".join(agg_lines) + "\n" + "\n".join(case_lines) + \
        sample_note(smallest)


# ---------------------------------------------------------------------------
# Latency statistics
# ---------------------------------------------------------------------------

def _measured(values: list[float]) -> list[float]:
    """The finite measurements only — an unmeasured run is not a zero."""
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if number == number and abs(number) != float("inf"):
            out.append(number)
    return out


def latency_stats(values: list[float | None]) -> dict:
    """Latency statistics over the runs that measured one.

    Mean, median, 95th percentile, minimum and maximum, each ``None`` when
    nothing was measured — a missing measurement is never a zero — plus ``n``
    (how many runs the statistics rest on) and ``excluded`` (how many did not
    measure one)."""
    total = len(list(values or []))
    measured = _measured(list(values or []))
    if not measured:
        return {
            "n": 0, "excluded": total, "mean": None, "median": None,
            "p95": None, "min": None, "max": None,
        }
    ordered = sorted(measured)
    # The 95th percentile by nearest rank.  An interpolating quantile would
    # happily report a value above the maximum on a small sample (4.7 s from a
    # 1 s and a 3 s run), which is not a latency anybody measured.
    rank = max(0, min(-(-95 * len(ordered) // 100) - 1, len(ordered) - 1))
    p95 = ordered[rank]
    return {
        "n": len(measured),
        "excluded": total - len(measured),
        "mean": round(statistics.fmean(ordered), 4),
        "median": round(statistics.median(ordered), 4),
        "p95": round(p95, 4),
        "min": round(min(ordered), 4),
        "max": round(max(ordered), 4),
    }


# ---------------------------------------------------------------------------
# Sample size — whether a comparison may be claimed at all
# ---------------------------------------------------------------------------

def sample_verdict(runs: int) -> dict:
    """Whether *runs* is enough to say anything about a model.

    ``comparable`` is False below :data:`MIN_SAMPLE`, and the note says so in
    words.  A benchmark may always report what it measured; it may not turn a
    handful of runs into a claim about which model is better.
    """
    return {
        "runs": runs,
        "min": MIN_SAMPLE,
        "comparable": runs >= MIN_SAMPLE,
        "note": (
            f"n = {runs} — at or above the {MIN_SAMPLE}-run floor for this dataset."
            if runs >= MIN_SAMPLE else
            f"n = {runs} — below the {MIN_SAMPLE}-run floor: these numbers describe "
            f"these runs, not the model, and must not be used to rank one model "
            f"above another."
        ),
    }


def sample_note(runs: int) -> str:
    """The sample-size caution as one line of Markdown, blank-line prefixed."""
    verdict = sample_verdict(runs)
    label = "Sample size." if verdict["comparable"] else "Insufficient sample."
    return f"\n**{label}** {verdict['note']}\n"


def group_results(results: list[dict]) -> list[dict]:
    """Group per-run results into cells that share dataset, model, backend,
    mode and repair setting.

    Only those five make two runs comparable: two runs from different scenarios
    or different models or a different mode are different measurements, and this
    function never merges them.  Returns one dict per cell with its runs."""
    grouped: dict[tuple, list[dict]] = {}
    for record in results or []:
        if not isinstance(record, dict):
            continue
        key = (
            str(record.get("dataset") or DATASET_ID),
            str(record.get("model") or ""),
            str(record.get("backend") or ""),
            str(record.get("mode") or "unrecorded"),
            record.get("max_tries"),
        )
        grouped.setdefault(key, []).append(record)

    out: list[dict] = []
    for (dataset_id, model, backend, mode, max_tries), rows in sorted(
        grouped.items(), key=lambda item: (str(item[0]), str(item[0][4]))
    ):
        out.append({
            "dataset": dataset_id,
            "model": model or None,
            "backend": backend,
            "mode": mode,
            "max_tries": max_tries,
            "scenarios": sorted({
                str(row["scenario"] if row.get("scenario") is not None else row.get("case"))
                for row in rows
                if (row.get("scenario") or row.get("case")) is not None
            }),
            "rows": rows,
        })
    return out


def reproduce_command(mode: str, backend: str, runs: int) -> str:
    """The command that would measure this cell again.

    A synthetic cell can only be reproduced by the scripted reader, so the
    command says ``--dry``; naming a backend there would ask for a model that
    never answered the runs in the first place.
    """
    if mode == "synthetic":
        return f"python -m gemmabot.benchmark --dry --runs {runs}"
    return f"python -m gemmabot.benchmark --backend {backend} --runs {runs}"


def result_records(results: list[dict]) -> list[dict]:
    """The self-describing results: what was measured, on what, and how much.

    One record per comparable cell, each carrying the dataset and scenario
    identifiers, the model, backend and mode, the timestamp of the first run in
    the cell, the number of runs, the success and failure counts, the latency
    statistics, the ids of the runs it summarizes (so every number can be traced
    back to a replayable log entry) and the sample-size verdict.

    A result never states a comparison: it says whether the sample would support
    one at all (see :func:`sample_verdict`).
    """
    out: list[dict] = []
    for cell in group_results(results):
        rows = cell["rows"]
        successes = sum(1 for row in rows if row.get("success") is True)
        failures = sum(1 for row in rows if row.get("success") is False)
        verified = [row.get("verified") for row in rows if isinstance(row.get("verified"), bool)]
        rejected = sum(1 for value in verified if value is False)
        repaired = [row for row in rows if (row.get("attempts") or 0) > 1]
        repaired_ok = sum(1 for row in repaired if row.get("success") is True)
        stamps = [str(row["timestamp"]) for row in rows if row.get("timestamp")]
        per_scenario = len(rows) // max(1, len(cell["scenarios"])) or 1
        out.append({
            "product": PRODUCT,
            "dataset": cell["dataset"],
            "scenarios": cell["scenarios"],
            "model": cell["model"],
            "backend": cell["backend"],
            "mode": cell["mode"],
            "max_tries": cell["max_tries"],
            "timestamp": min(stamps) if stamps else None,
            "runs": len(rows),
            "successes": successes,
            "failures": failures,
            "rejected": rejected,
            "repaired": len(repaired),
            "repaired_ok": repaired_ok,
            "latency": latency_stats([row.get("latency") for row in rows]),
            "run_ids": [row["run_id"] for row in rows if row.get("run_id")],
            "sample": sample_verdict(len(rows)),
            # How to make this result again, exactly: the same dataset, model,
            # backend and repair setting, on the same machine's code.
            "reproduce": reproduce_command(cell["mode"], cell["backend"], per_scenario),
        })
    return out


def report_markdown(results: list[dict]) -> str:
    """The aggregate report: one row per comparable cell, with its sample size."""
    records = result_records(results)
    lines = [
        f"# {PRODUCT} results\n",
        f"Dataset `{DATASET_ID}` — {DATASET_NOTE}.\n",
        "Each row is one comparable cell: same dataset, model, backend, mode and "
        "repair setting. `mode` is `live` when a model answered the runs and "
        "`synthetic` when the scripted reader did; the two are never compared.",
        "",
        "| dataset | model | backend | mode | max_tries | runs | success | failure "
        "| rejected | repaired (ok) | latency mean / median / p95 / max (s) | sample |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for record in records:
        stats = record["latency"]
        def _num(value):  # noqa: ANN202 - one formatter for four numbers
            return "—" if value is None else f"{value:.3f}"
        lines.append(
            f"| {record['dataset']} | {record['model'] or '—'} | {record['backend']} | "
            f"{record['mode']} | {record['max_tries']} | {record['runs']} | "
            f"{record['successes']} | {record['failures']} | {record['rejected']} | "
            f"{record['repaired']} ({record['repaired_ok']}) | "
            f"{_num(stats['mean'])} / {_num(stats['median'])} / {_num(stats['p95'])} / "
            f"{_num(stats['max'])} | "
            f"{'comparable' if record['sample']['comparable'] else 'below floor'} |"
        )
    smallest = min((record["runs"] for record in records), default=0)
    lines += ["", sample_note(smallest).strip(), ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# save_results
# ---------------------------------------------------------------------------

def save_results(
    results: list[dict],
    path: str = "benchmarks/results.json",
) -> dict:
    """Save the raw per-run results, the summary table and the aggregate report.

    Writes ``results.json`` (one record per run), ``results.md`` (the summary
    table) and ``report.json`` / ``report.md`` (the self-describing aggregate
    results, see :func:`result_records`).  Creates the ``benchmarks/`` directory
    if it does not exist.  Returns the written paths.
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
        fh.write(f"# {PRODUCT} Results\n\n")
        fh.write(
            "Each row carries the mode it was run in: `live` rows were answered "
            "by a model, `synthetic` rows by the scripted reader.\n\n"
        )
        fh.write(summarize(results))
    print(f"[benchmark] Saved markdown table → {md_path}")

    # The aggregate results, each naming what it measured and on how many runs.
    report_path = out.with_name("report.json")
    records = result_records(results)
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    print(f"[benchmark] Saved aggregate results → {report_path}")

    report_md = out.with_name("report.md")
    report_md.write_text(report_markdown(results), encoding="utf-8")
    print(f"[benchmark] Saved aggregate report → {report_md}")

    return {
        "results": str(out), "summary": str(md_path),
        "report": str(report_path), "report_markdown": str(report_md),
    }


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _build_parser():
    import argparse
    p = argparse.ArgumentParser(
        prog="python -m gemmabot.benchmark",
        description=f"Run {PRODUCT}: evaluate AI-generated robot plans against "
                    f"deterministic simulation scenarios.",
    )
    p.add_argument(
        "--backend",
        choices=["ollama", "api", "both"],
        default="ollama",
        help="Which model backend to use (default: ollama). Ignored by --dry.",
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
        help=(
            "Use a scripted reader instead of a model — no network, no credits. "
            "It answers every case, so --backend is ignored and the runs are "
            "recorded as backend 'dry', mode 'synthetic'."
        ),
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
        # One scripted reader for every case, so there is no backend dimension to
        # measure.  Recording two identical "ollama" and "api" rows would imply a
        # comparison that never happened.
        backends: dict[str, Callable] = {"dry": lambda i, w: "{}"}
        print("dry mode replaces the backends: --backend is ignored.")
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
        print("\n" + report_markdown(results))
        save_results(results)


if __name__ == "__main__":
    main()
