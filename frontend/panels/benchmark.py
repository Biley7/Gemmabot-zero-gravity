"""RobotBench — the benchmark lab: live and synthetic runs, measured and kept apart.

Owner: FRONTEND.  No Streamlit import, no network, no model, no timing done
here: every number is read out of runs that already happened, and the two
execution metrics are reproduced by replaying the recorded plan on the recorded
world with the simulator alone.

The nine metrics
----------------
success rate, verification rejection rate, repair rate, repair success rate,
average actions, average attempts, latency, collision rate and boundary
violation rate.  Each one names its own denominator and defines itself in words
(see :data:`DEFINITIONS` and :data:`TOOLTIPS`), because a rate without its
denominator is a claim nobody can check.

What "no misleading metrics" means in this module
-------------------------------------------------
1. **Provenance comes from the record, never from the result.** A run says
   whether a model answered (``mode == "live"``) or a scripted reader did
   (``"synthetic"``).  When the record does not say — as with runs written
   before the field existed — the run lands in a third bucket, *unclassified*,
   and is never counted as either.  A scripted run can produce exactly the same
   plan as a real one, so nothing here infers provenance from numbers.
2. **Every rate carries its denominator.** ``metrics()`` returns ``value=None``
   with ``n == 0`` rather than ``0.0`` when there is nothing to divide by; the
   HTML renders that as "no data", never as a zero.
3. **A metric with no measurement is absent, not zero.** Latency averages only
   the runs whose latency was measured, and reports how many were not; the same
   for action counts.
4. **Units are never mixed on one axis.** Bars are only ever drawn within a
   metric, on that metric's own scale.
5. **Sources are never summed.** The run log and a stored benchmark artifact
   overlap — the runner logs its runs — so each is measured on its own and the
   overlap is stated.
6. **A small sample is labelled, not quietly printed.** Below the configured
   floor (``config.BENCH_MIN_SAMPLE``) a number describes the runs that were
   made and nothing else, so every metric says so and the header says it loudest.

Public surface
--------------
PRODUCT / MIN_SAMPLE
MODE_LIVE / MODE_SYNTHETIC / UNCLASSIFIED
MODE_LABELS / MODE_STATES / MODE_NOTES
DEFINITIONS                    what each metric means, in one line
TOOLTIPS                       the same, long enough to act on
provenance(record)             (mode, basis) for one run — never a guess
rows(records, source)          normalised run rows from either source
split(rows)                    mode → rows, plus the unclassified bucket
metrics(rows)                  the nine metrics, each with value, n and tooltip
series(rows)                   per backend (and repair setting) aggregates
cells(rows)                    per case × max_tries aggregates
facts_rows(section)            the section's headline counts
sample_html(rows)              whether this sample may be compared at all
headline_html(sections)        ROBOTBENCH: scenarios, modes, the four numbers
chart_minimal(rows)            low-ink glance chart for ONE mode's rows
chart_technical(rows)          labelled small multiples, one scale per metric
facts_html / metrics_html / groups_html / section_html / cells_html
headline_html / caveats_html / panel
"""
from __future__ import annotations

from gemmabot.config import BENCH_MIN_SAMPLE

from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.panels.engine import backend_label
from frontend.panels import replay as replay_panel
from frontend.simulation import player as playback
from frontend.components.blocks import empty_state, escape as _e, fact_cards, shell, scroll_x, sub_title

# The product this lab measures with, and the floor under which a number may not
# be read as a comparison.  The floor is configuration so the runner's report and
# this view cannot disagree about when a sample is too small.
PRODUCT = "RobotBench"
MIN_SAMPLE = BENCH_MIN_SAMPLE

# What the simulator stopped on, counted separately: a wall in the way is a
# collision, the edge of the grid is a boundary violation.
COLLISION = playback.HALT_COLLISION
BOUNDARY = playback.HALT_BOUNDARY

MODE_LIVE = "live"
MODE_SYNTHETIC = "synthetic"
# Not a third kind of run — the absence of the fact.  Kept in its own bucket so
# it can only ever be shown as itself.
UNCLASSIFIED = "unclassified"

MODE_LABELS: dict[str, str] = {
    MODE_LIVE: "LIVE",
    MODE_SYNTHETIC: "SYNTHETIC",
    UNCLASSIFIED: "UNCLASSIFIED",
}

# LIVE is a fact, not a pass: blue, the console's "measured" accent.  SYNTHETIC
# is amber because it is the one a reader must not mistake for a model result.
MODE_STATES: dict[str, str] = {
    MODE_LIVE: "running",
    MODE_SYNTHETIC: "warning",
    UNCLASSIFIED: "neutral",
}

MODE_COLORS: dict[str, str] = {
    MODE_LIVE: C.RUNNING,
    MODE_SYNTHETIC: C.WARNING,
    UNCLASSIFIED: C.TEXT_MUTED,
}

MODE_NOTES: dict[str, str] = {
    MODE_LIVE: "a model answered these runs",
    MODE_SYNTHETIC: "a scripted reader answered these runs — no model was called",
    UNCLASSIFIED: "recorded before the run's mode was captured, so it cannot be "
                  "attributed to either side",
}

# Scripted readers announce themselves in the backend name (``dry`` from
# ``engine.DRY_BACKEND``, ``dry_model``/``dry_vision`` in older logs).  This is a
# naming convention of this project, not an inference from a run's numbers:
# no model is configured for a backend whose name says it is the dry reader.
_SCRIPTED_MARKERS: tuple[str, ...] = ("dry", "scripted", "fake")

# What each metric is, printed next to it so a reader can check the arithmetic.
DEFINITIONS: dict[str, str] = {
    "success": "share of runs whose plan passed the verifier",
    "rejected": "share of runs the verifier refused every attempt of — the run "
                "ended with no verified plan",
    "repair": "share of runs that needed more than one attempt — the first plan "
              "was refused and the loop repaired it",
    "repair_success": "share of the runs that needed repair which still finished "
                      "with a verified plan",
    "collision": "share of runs whose recorded plans the simulator stopped at "
                 "an obstacle — including the attempts the repair loop refused",
    "boundary": "share of runs whose recorded plans the simulator stopped at the "
                "edge of the grid",
    "latency": "mean wall-clock seconds per run, over the runs that measured it; "
               "not a throughput measurement",
    "actions": "mean actions in the accepted plan, over the runs that recorded one",
    "attempts": "mean planning attempts per run, over the runs that recorded them",
}

# The same definitions, long enough to decide something with.  Rendered as the
# tooltip of the metric card: a number a reader cannot look up is a number they
# have to take on trust.
TOOLTIPS: dict[str, str] = {
    "success": (
        "A run counts as a success when its plan passed the verifier — not when a "
        "robot reached a goal in the real world. Denominator: runs that recorded "
        "an outcome. A run whose outcome was never recorded is excluded, not "
        "counted as a failure."
    ),
    "rejected": (
        "How often the verifier refused the plan: the run ended with no verified "
        "plan, because every attempt it had was refused. Denominator: runs whose "
        "attempts were recorded. A run that failed without any recorded attempt "
        "verdict (for example a backend error) is excluded — nothing was refused."
    ),
    "repair": (
        "How often the first plan was not good enough: the run needed more than "
        "one attempt. Denominator: runs that recorded an attempt count. Repair "
        "is not failure — see repair success rate for what happened after it."
    ),
    "repair_success": (
        "Of the runs that needed repair, how many still ended with a verified "
        "plan. Denominator: the runs with more than one attempt. This is the "
        "number that says whether the repair loop is worth having."
    ),
    "collision": (
        "How often a model proposed a plan that would drive into an obstacle. "
        "Every plan the run recorded is replayed by the simulator alone: the "
        "accepted plan and each attempt the repair loop refused. The accepted "
        "plan alone would always read 0% — the verifier passed it — so the "
        "refused attempts are what this measures. Denominator: runs that "
        "recorded a world and at least one plan."
    ),
    "boundary": (
        "How often a model proposed a plan that would leave the grid. Same "
        "denominator and the same replay as the collision rate; counted apart "
        "because an off-by-one at the edge is a different bug from hitting an "
        "obstacle."
    ),
    "latency": (
        "Mean wall-clock seconds per run, measured on the machine that made the "
        "run — so it is not comparable across machines, and a scripted run's "
        "near-zero latency is not a model speed. Denominator: the runs that "
        "measured one."
    ),
    "actions": (
        "Mean number of actions in the accepted plan. Shorter plans are not "
        "automatically better: this measures plan shape, not plan quality. "
        "Denominator: the runs that recorded a plan."
    ),
    "attempts": (
        "Mean planning attempts per run, including the repairs. Denominator: the "
        "runs that recorded an attempt count."
    ),
}




def _num(value: object) -> float | None:
    """A finite float, or ``None`` — a missing measurement is never a zero."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _int_or_none(value: object) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def _mean(values: list[float]) -> float | None:
    return (sum(values) / len(values)) if values else None


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def _is_scripted_name(backend: object) -> bool:
    name = str(backend or "").strip().lower()
    return bool(name) and any(marker in name for marker in _SCRIPTED_MARKERS)


def provenance(record: object) -> dict:
    """Where one run's answers came from — ``{mode, basis, backend}``.

    ``mode`` is ``"live"``, ``"synthetic"``, or ``None`` for *unrecorded*.  The
    basis string says why, so the UI can show the reasoning rather than assert a
    verdict.  A record that states its mode is believed; a record that does not
    is only classified when its backend is the scripted reader by name.
    """
    record = record if isinstance(record, dict) else {}
    backend = str(record.get("backend") or "unknown")
    stated = record.get("mode")
    if stated in (MODE_LIVE, MODE_SYNTHETIC):
        return {
            "mode": stated,
            "backend": backend,
            "basis": "stated by the run when it was logged",
        }
    if _is_scripted_name(backend):
        return {
            "mode": MODE_SYNTHETIC,
            "backend": backend,
            "basis": f"the backend {backend!r} is the scripted reader — no model "
                     f"is configured for it",
        }
    return {
        "mode": None,
        "backend": backend,
        "basis": "the record does not say whether a model answered it",
    }


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _verdict(record: dict) -> bool | None:
    """The verifier's own verdict on the accepted plan, or ``None``."""
    found = record.get("verification")
    if not isinstance(found, dict):
        return None
    ok = found.get("ok")
    return ok if isinstance(ok, bool) else None


def _attempt_verdicts(record: dict) -> tuple[int, int]:
    """``(refused, recorded)`` attempt verdicts from the run's own history.

    Every planning attempt the verifier saw is recorded with its ``ok``.  Counts
    only what is there: an attempt without a boolean verdict is neither.
    """
    history = record.get("history")
    if not isinstance(history, list):
        return 0, 0
    verdicts = [
        entry.get("ok") for entry in history
        if isinstance(entry, dict) and isinstance(entry.get("ok"), bool)
    ]
    return sum(1 for value in verdicts if value is False), len(verdicts)


def _rejected(ok: bool | None, refused: int, recorded: int) -> bool | None:
    """Whether the verifier ended up refusing this run.

    ``True`` when the run finished without an accepted plan *and* at least one
    attempt was refused — every attempt it had was refused.  ``False`` when a
    plan was accepted.  ``None`` when nothing was refused that we know of: a run
    that failed for another reason (a backend error, say) is not a rejection,
    and counting it as one would blame the verifier for it.
    """
    if ok is True:
        return False
    if ok is False and recorded and refused:
        return True
    return None


def _plans(record: dict) -> list[list[dict]]:
    """The distinct plans the record holds: each attempt's, then the accepted one.

    The accepted plan alone would measure nothing — the verifier passed it, so
    it cannot collide.  What these metrics are for is what the model *proposed*,
    which is the accepted plan plus every attempt the repair loop refused.  The
    accepted plan is usually also the last attempt's plan, so it is only added
    when no attempt recorded it; replaying the same plan twice would weight it
    twice.
    """
    plans: list[list[dict]] = []
    history = record.get("history")
    if isinstance(history, list):
        for entry in history:
            actions = entry.get("actions") if isinstance(entry, dict) else None
            if isinstance(actions, list) and actions and actions not in plans:
                plans.append(actions)
    accepted = record.get("actions")
    if isinstance(accepted, list) and accepted and accepted not in plans:
        plans.append(accepted)
    return plans


def _reproduced(record: dict) -> tuple[dict[str, int], int, bool]:
    """What the simulator stops on, over every plan the run recorded.

    Replays each plan on the recorded world with the simulator alone — no model,
    no network — and counts the stops by kind: a wall is a collision, the edge of
    the grid a boundary violation.  Returns the counts, how many plans were
    reproduced, and whether there was anything to reproduce at all.  A run with
    no world or no plan is not reproducible, and its plans are not counted.
    """
    stops = {COLLISION: 0, BOUNDARY: 0}
    world = record.get("world")
    plans = _plans(record)
    if not plans or not isinstance(world, dict):
        return stops, 0, False

    reproduced = 0
    for actions in plans:
        try:
            timeline = replay_panel.timeline(
                {"world": world, "actions": actions}, {"actions": actions}
            )
        except Exception:  # noqa: BLE001 - a bad record must not break the lab
            continue
        if not isinstance(timeline, dict):
            continue
        reproduced += 1
        stopped = playback.halt_kind(timeline)
        if stopped in stops:
            stops[stopped] += 1
    return stops, reproduced, reproduced > 0


def rows(records: list[dict] | None, source: str = "run log") -> list[dict]:
    """Normalise records from either source into one row shape.

    Reads only fields the records already have, plus what the simulator can
    reproduce from them (see :func:`_blocked`).  A field the source does not
    carry stays ``None`` and every metric that needs it will report that it has
    no measurement rather than invent one.
    """
    out: list[dict] = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        found = provenance(record)
        actions = record.get("actions")
        backend = found["backend"]
        max_tries = _int_or_none(record.get("max_tries"))
        ok = (record.get("success") if isinstance(record.get("success"), bool)
              else None)
        refused, recorded = _attempt_verdicts(record)
        stopped, plans_reproduced, reproducible = _reproduced(record)
        scenario = record.get("scenario") or record.get("case")
        out.append({
            "backend": backend,
            "backend_label": backend_label(backend),
            "mode": found["mode"],
            "basis": found["basis"],
            "ok": ok,
            "attempts": _int_or_none(record.get("attempts")),
            "latency": _num(record.get("latency")),
            "actions": len(actions) if isinstance(actions, list) else None,
            "case": str(record["case"]) if record.get("case") else None,
            "max_tries": max_tries,
            "source": source,
            # Everything the four outcome metrics rest on.  Each is ``None``
            # when the record did not say, which is why none of them is ever
            # read as a zero.
            "verdict": _verdict(record),
            "refused": refused,
            "verdicts": recorded,
            "rejected": _rejected(ok, refused, recorded),
            "stopped": stopped,
            "plans": plans_reproduced,
            "reproducible": reproducible,
            "dataset": str(record["dataset"]) if record.get("dataset") else None,
            "scenario": str(scenario) if scenario else None,
            "model": str(record["model"]) if record.get("model") else None,
            "run_id": str(record["run_id"]) if record.get("run_id") else None,
            "timestamp": str(record["timestamp"]) if record.get("timestamp") else None,
        })
    return out


def split(run_rows: list[dict] | None) -> dict[str, list[dict]]:
    """``{live, synthetic, unclassified}`` — every row lands in exactly one."""
    buckets: dict[str, list[dict]] = {
        MODE_LIVE: [], MODE_SYNTHETIC: [], UNCLASSIFIED: [],
    }
    for row in run_rows or []:
        key = row.get("mode")
        buckets[key if key in (MODE_LIVE, MODE_SYNTHETIC) else UNCLASSIFIED].append(row)
    return buckets


def _series_label(row: dict) -> str:
    """Backend label, plus the repair setting when the source distinguishes it."""
    label = row["backend_label"]
    if row.get("max_tries") is not None:
        label += f" · max_tries={row['max_tries']}"
    return label


def series(run_rows: list[dict] | None) -> list[dict]:
    """Per series (backend + repair setting) aggregates, biggest n first."""
    grouped: dict[str, list[dict]] = {}
    for row in run_rows or []:
        grouped.setdefault(_series_label(row), []).append(row)

    out: list[dict] = []
    for label, group in grouped.items():
        out.append({
            "label": label,
            "mode": group[0]["mode"],
            "n": len(group),
            "metrics": {item["id"]: item for item in metrics(group)},
        })
    return sorted(out, key=lambda item: (-item["n"], item["label"]))


def cells(run_rows: list[dict] | None) -> list[dict]:
    """Per case × repair-setting aggregates — only for rows that recorded them."""
    grouped: dict[tuple[str, int | None], list[dict]] = {}
    for row in run_rows or []:
        if row.get("case") is None:
            continue
        grouped.setdefault((row["case"], row.get("max_tries")), []).append(row)

    out: list[dict] = []
    for (case, max_tries), group in grouped.items():
        out.append({
            "case": case,
            "max_tries": max_tries,
            "n": len(group),
            "metrics": {item["id"]: item for item in metrics(group)},
        })
    return sorted(out, key=lambda item: (item["case"], item["max_tries"] or 0))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def sample_verdict(runs: int) -> dict:
    """Whether a sample of *runs* may be read as evidence about a model.

    Mirrors the runner's floor (``config.BENCH_MIN_SAMPLE``) so the view and the
    report cannot disagree about when a number is too small to compare.
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


def metrics(run_rows: list[dict] | None) -> list[dict]:
    """The nine RobotBench metrics, each with its own denominator.

    Returns one dict per metric: ``id``, ``label``, ``value`` (``None`` when
    nothing could be measured), ``display``, ``unit``, ``n`` (how many runs the
    value rests on), ``excluded`` (runs the metric had to skip), ``state``,
    ``definition``, ``tooltip`` and ``detail``.

    The order is the order of the question: did the plan pass, how often was it
    refused, how often did the loop repair it, did the repair work, what stopped
    the broken ones, and how long did all of it take.
    """
    run_rows = list(run_rows or [])

    known_ok = [row["ok"] for row in run_rows if row["ok"] is not None]
    known_attempts = [row["attempts"] for row in run_rows if row["attempts"] is not None]
    measured_latency = [row["latency"] for row in run_rows if row["latency"] is not None]
    known_actions = [row["actions"] for row in run_rows if row["actions"] is not None]

    success = _mean([1.0 if ok else 0.0 for ok in known_ok])
    repaired = [value for value in known_attempts if value > 1]
    repair = _mean([1.0 if value > 1 else 0.0 for value in known_attempts])
    recovered = sum(
        1 for row in run_rows
        if row["attempts"] is not None and row["attempts"] > 1 and row["ok"] is True
    )
    latency = _mean(measured_latency) if measured_latency else None
    actions = _mean([float(value) for value in known_actions]) if known_actions else None
    attempts = _mean([float(value) for value in known_attempts]) if known_attempts else None

    # ── Rejection: the verifier refused every attempt the run had ────────────
    judged = [row for row in run_rows if row["rejected"] is not None]
    rejected_runs = sum(1 for row in judged if row["rejected"])
    rejection = _mean([1.0 if row["rejected"] else 0.0 for row in judged])
    verdicts = sum(int(row["verdicts"] or 0) for row in run_rows)
    refused = sum(int(row["refused"] or 0) for row in run_rows)

    # ── Repair success: of the runs that needed repair, how many finished ────
    recoverable = [row for row in run_rows
                   if row["attempts"] is not None and row["attempts"] > 1]
    repaired_ok = sum(1 for row in recoverable if row["ok"] is True)
    repair_success = _mean(
        [1.0 if row["ok"] is True else 0.0 for row in recoverable]
    )

    # ── What stopped the plans the simulator could reproduce ────────────────
    replayed = [row for row in run_rows if row["reproducible"]]
    plans_total = sum(int(row["plans"] or 0) for row in replayed)
    collisions = sum(1 for row in replayed if row["stopped"].get(COLLISION))
    boundaries = sum(1 for row in replayed if row["stopped"].get(BOUNDARY))
    collided_plans = sum(int(row["stopped"].get(COLLISION) or 0) for row in replayed)
    off_grid_plans = sum(int(row["stopped"].get(BOUNDARY) or 0) for row in replayed)
    collision = _mean(
        [1.0 if row["stopped"].get(COLLISION) else 0.0 for row in replayed]
    )
    boundary = _mean(
        [1.0 if row["stopped"].get(BOUNDARY) else 0.0 for row in replayed]
    )

    def _latency_display(mean: float | None) -> tuple[str, str]:
        """Seconds, unless that would round a real measurement down to zero."""
        if mean is None:
            return "—", "s"
        if 0.0 < mean < 0.005:
            return f"{mean * 1000:.2f} ms", "ms"
        return f"{mean:.2f} s", "s"

    def item(  # noqa: ANN001
        key: str, label: str, value: float | None, display: str, unit: str,
        n: int, excluded: int, detail: str, state: str = "neutral",
    ) -> dict:
        return {
            "id": key,
            "label": label,
            "value": value,
            "display": display,
            "unit": unit,
            "n": n,
            "excluded": excluded,
            "detail": detail,
            "state": state if value is not None else "neutral",
            "definition": DEFINITIONS[key],
            "tooltip": TOOLTIPS[key],
            "caution": bool(value is not None) and n < MIN_SAMPLE,
            "sample": sample_verdict(n),
        }

    no_data = "no data"
    total = len(run_rows)

    return [
        item(
            "success", "Success rate", success,
            _pct(success) if success is not None else no_data, "%",
            len(known_ok), total - len(known_ok),
            f"{sum(1 for ok in known_ok if ok)} of {len(known_ok)} runs passed the "
            f"verifier" if known_ok else "no run recorded an outcome",
            "success" if success == 1.0 else ("warning" if success is not None else "neutral"),
        ),
        item(
            "rejected", "Rejection rate", rejection,
            _pct(rejection) if rejection is not None else no_data, "%",
            len(judged), total - len(judged),
            f"{rejected_runs} of {len(judged)} runs ended with no verified plan · "
            f"{refused} of {verdicts} attempts refused by the verifier"
            if judged else "no run recorded an attempt verdict",
            "warning" if rejected_runs else "neutral",
        ),
        item(
            "repair", "Repair rate", repair,
            _pct(repair) if repair is not None else no_data, "%",
            len(known_attempts), total - len(known_attempts),
            f"{len(repaired)} of {len(known_attempts)} runs needed more than one "
            f"attempt · {recovered} of those still finished"
            if known_attempts else "no run recorded an attempt count",
            "warning" if repaired else "neutral",
        ),
        item(
            "repair_success", "Repair success rate", repair_success,
            _pct(repair_success) if repair_success is not None else no_data, "%",
            len(recoverable),
            # Runs with no attempt count are the unmeasured ones here: a run that
            # recorded one attempt simply needed no repair, which the detail
            # says, and is outside the population rather than uncounted.
            total - len(known_attempts),
            f"{repaired_ok} of {len(recoverable)} repaired runs still passed the "
            f"verifier" if recoverable else "no run needed repair",
            "success" if repair_success == 1.0 else (
                "warning" if repair_success is not None else "neutral"
            ),
        ),
        item(
            "collision", "Collision rate", collision,
            _pct(collision) if collision is not None else no_data, "%",
            len(replayed), total - len(replayed),
            f"{collisions} of {len(replayed)} runs proposed a plan the simulator "
            f"stopped at an obstacle · {collided_plans} of {plans_total} reproduced "
            f"plans hit one" if replayed else "no run recorded a world and a plan "
            f"to reproduce",
            "warning" if collisions else "neutral",
        ),
        item(
            "boundary", "Boundary violation rate", boundary,
            _pct(boundary) if boundary is not None else no_data, "%",
            len(replayed), total - len(replayed),
            f"{boundaries} of {len(replayed)} runs proposed a plan the simulator "
            f"stopped at the edge of the grid · {off_grid_plans} of {plans_total} "
            f"reproduced plans left it" if replayed else "no run recorded a world "
            f"and a plan to reproduce",
            "warning" if boundaries else "neutral",
        ),
        item(
            "latency", "Mean latency", latency,
            *_latency_display(latency),
            len(measured_latency), total - len(measured_latency),
            f"{len(measured_latency)} of {total} runs measured a latency"
            if measured_latency else "no run recorded a latency",
        ),
        item(
            "actions", "Mean actions", actions,
            "—" if actions is None else f"{actions:.1f}", "steps",
            len(known_actions), total - len(known_actions),
            f"{len(known_actions)} of {total} runs recorded a plan"
            if known_actions else "no run recorded a plan",
        ),
        item(
            "attempts", "Mean attempts", attempts,
            "—" if attempts is None else f"{attempts:.2f}", "tries",
            len(known_attempts), total - len(known_attempts),
            f"{len(known_attempts)} of {total} runs recorded an attempt count"
            if known_attempts else "no run recorded an attempt count",
        ),
    ]


def facts_rows(section: dict) -> list[dict]:
    """Headline counts for one section: how much of it is measured at all."""
    buckets = split(section.get("rows"))
    total = len(section.get("rows") or [])
    return [
        {"id": "runs", "label": "Runs", "value": str(total),
         "detail": section.get("source", "")},
        {"id": "live", "label": "Live", "value": str(len(buckets[MODE_LIVE])),
         "detail": "a model answered", "state": "running"},
        {"id": "synthetic", "label": "Synthetic", "value": str(len(buckets[MODE_SYNTHETIC])),
         "detail": "scripted reader", "state": "warning"},
        {"id": "unclassified", "label": "Unclassified",
         "value": str(len(buckets[UNCLASSIFIED])), "detail": "mode not recorded"},
    ]


# ---------------------------------------------------------------------------
# HTML — readouts
# ---------------------------------------------------------------------------

def facts_html(section: dict) -> str:
    """The section's four counts, so a reader knows the sample size first."""
    return fact_cards(
        facts_rows(section),
        css_class="gb-bench-fact",
        column_min=130,
        value_size=T.SIZE_LG,
    )


def split_unit(display: str, unit: str) -> tuple[str, str]:
    """The amount and its unit, ready to be painted side by side exactly once.

    The two fields disagree about who owns the unit.  A rate or a latency keeps
    it in the display, because the value is formatted *with* it ("100%",
    "0.20 ms"); a count does not, and leaves it to ``metric['unit']`` (display
    "1.0", unit "steps").  Painting display and then unit printed it twice for
    the first kind — "100% %", "0.20 ms ms" — so the suffix is stripped off here
    when the display already carries it, and left alone when it does not.

    Either way the caller gets a number and its unit and appends the unit once.
    A placeholder ("—", "no data") is not a measurement, so it is returned
    without a unit: a unit only belongs on a number.
    """
    amount = display[: -len(unit)].rstrip() if unit and display.endswith(unit) else display
    if not unit or not any(char.isdigit() for char in amount):
        return display, ""
    return amount, unit


def metrics_html(run_rows: list[dict]) -> str:
    """The metrics as cards, each with its denominator, definition and tooltip.

    Every card carries the long explanation as a ``title`` so a reader can hover
    it without the layout shouting, and a card resting on too few runs says so
    in the card itself rather than only in a footnote.
    """
    cards: list[str] = []
    for metric in metrics(run_rows):
        empty = metric["value"] is None
        color = C.TEXT_MUTED if empty else C.TELEMETRY_VALUE
        amount, unit_token = split_unit(metric["display"], metric["unit"])
        unit_span = (
            f"<span style='font-size:{T.SIZE_XS}px;color:{C.TELEMETRY_UNIT}'> "
            f"{_e(unit_token)}</span>"
            if unit_token else ""
        )
        excluded_note = (
            f" · {metric['excluded']} not measured"
            if metric["excluded"] else ""
        )
        caution = (
            f"<span class='gb-bench-caution' data-caution='true' "
            f"style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.WARNING}'>⚠ below the {metric['sample']['min']}-run floor "
            f"— no comparison</span>"
            if metric["caution"] else ""
        )
        cards.append(
            f"<div class='gb-bench-metric' data-metric='{_e(metric['id'])}' "
            f"data-value='{'' if empty else _e(metric['display'])}' "
            f"data-n='{metric['n']}' "
            f"data-definition='{_e(metric['definition'])}' "
            f"title='{_e(metric['tooltip'])}' "
            f"style='display:flex;flex-direction:column;gap:{S.px(S.XS)};"
            f"padding:{S.px(S.SM)} {S.px(S.MD)};background:{C.BG_SURFACE};"
            f"border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_MD)}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
            f"text-transform:uppercase'>{_e(metric['label'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_LG}px;"
            f"color:{color}'>{_e(amount)}{unit_span}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_SECONDARY}'>n = {metric['n']}"
            f"{excluded_note}"
            f"</span>"
            f"{caution}"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED}'>{_e(metric['detail'])}</span>"
            f"<span style='font-family:{T.FONT_SANS};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED}'>{_e(metric['definition'])}</span>"
            f"</div>"
        )
    return (
        f"<div style='display:grid;"
        f"grid-template-columns:repeat(auto-fit,minmax({S.px(180)},1fr));"
        f"gap:{S.px(S.SM)}'>" + "".join(cards) + "</div>"
    )


# ---------------------------------------------------------------------------
# HTML — charts
# ---------------------------------------------------------------------------

def _bar(fraction: float, color: str, *, width: int = 160, height: int = 6) -> str:
    """One bar, length = fraction of *its own metric's* scale (never mixed)."""
    filled = max(0.0, min(1.0, fraction)) * width
    return (
        f"<span style='display:inline-block;width:{S.px(width)};height:{S.px(height)};"
        f"background:{C.BG_OVERLAY};border-radius:{S.px(2)};position:relative;"
        f"vertical-align:middle'>"
        f"<span style='display:block;width:{filled:.1f}px;height:{S.px(height)};"
        f"background:{color};border-radius:{S.px(2)}'></span></span>"
    )


def chart_minimal(run_rows: list[dict] | None) -> str:
    """The glance: passed, repaired and refused per series, one 0–100% scale.

    Only those three, because they are the ones that share a unit and tell the
    loop's story: the plan passed, the loop had to repair it, or the verifier
    refused it.  Adding latencies or action counts to the same bars would make
    the lengths compare things that are not comparable.

    Call it with one mode's rows: bars from live and scripted runs on one chart
    would invite a comparison between a model and a script.
    """
    groups = series(run_rows)
    if not groups:
        return shell(empty_state(
            "No runs to chart.",
            "Live and synthetic runs are charted separately; both are empty here.",
        ))

    lines: list[str] = []
    for group in groups:
        color = MODE_COLORS.get(group["mode"] or UNCLASSIFIED, C.TEXT_MUTED)
        success = group["metrics"]["success"]
        rejected = group["metrics"]["rejected"]
        repair = group["metrics"]["repair"]
        for metric, mark in (
            (success, "success"), (repair, "repair"), (rejected, "rejected"),
        ):
            value = metric["value"]
            bar = (
                _bar(value, color)
                if value is not None
                else f"<span style='display:inline-block;font-family:{T.FONT_MONO};"
                     f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED}'>"
                     f"no data</span>"
            )
            lines.append(
                f"<div class='gb-bench-min-row' data-series='{_e(group['label'])}' "
                f"data-metric='{mark}' "
                f"style='display:flex;align-items:center;gap:{S.px(S.SM)}'>"
                f"<span style='width:{S.px(78)};font-family:{T.FONT_MONO};"
                f"font-size:{T.SIZE_XS}px;color:{color};overflow:hidden;"
                f"text-overflow:ellipsis;white-space:nowrap'>"
                f"{_e(group['label']) if mark == 'success' else ''}</span>"
                f"<span style='width:{S.px(58)};font-family:{T.FONT_MONO};"
                f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED}'>{mark}</span>"
                f"{bar}"
                f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                f"color:{C.TELEMETRY_VALUE}'>"
                f"{_e(metric['display'])}</span>"
                f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
                f"color:{C.TEXT_MUTED}'>n={metric['n']}</span>"
                f"</div>"
            )
    legend = (
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};margin-bottom:{S.px(S.SM)}'>"
        f"these bars share one 0–100% scale, and a run can be both repaired and "
        f"successful</div>"
    )
    return shell(legend + "".join(lines))


def _scale_max(metric_id: str, values: list[float]) -> float:
    """Top of the axis for one metric, in that metric's own unit.

    ``0.0`` means every reading is zero, which is a real state (the runner
    rounds latencies to milliseconds) and is reported as no spread rather than
    being spread over a default 0-1 axis that would imply a scale nobody
    measured.
    """
    if metric_id in ("success", "repair"):
        return 1.0
    top = max(values) if values else 0.0
    return top * 1.2 if top > 0 else 0.0


def _unit_for(metric_id: str, top: float) -> str:
    """The unit one metric's axis is drawn in — chosen from its own scale.

    A scripted run's latency is a fraction of a millisecond, so printing the
    axis in seconds would label every tick ``0.00`` and the bars would say
    nothing.  Sub-millisecond scales are drawn in ms instead of pretending.
    """
    if metric_id in ("success", "repair"):
        return "%"
    if metric_id == "latency":
        return "ms" if top < 0.01 else "s"
    return {"actions": "steps", "attempts": "tries"}.get(metric_id, "")


def _amount(metric_id: str, value: float, top: float) -> str:
    """One number on that metric's axis, at a precision the scale deserves."""
    if metric_id in ("success", "repair"):
        return f"{value * 100:.0f}"
    if metric_id == "latency":
        if top < 0.01:
            return f"{value * 1000:.2f}"
        return f"{value:.3f}" if top < 1 else f"{value:.2f}"
    return f"{value:.2f}" if top < 1 else f"{value:.1f}"


def _reading(metric_id: str, value: float, top: float, unit: str) -> str:
    """A reading with its unit — ``0.34 ms``, ``100%``, ``4.5 steps``."""
    amount = _amount(metric_id, value, top)
    return f"{amount}%" if unit == "%" else f"{amount} {unit}".strip()


def chart_technical(run_rows: list[dict] | None) -> str:
    """Small multiples: one labelled panel per metric, each on its own scale.

    A technical reader wants the axis, the exact value and the n behind every
    bar.  What they do not get — because it would be a lie — is bars from two
    different units sharing one axis.
    """
    groups = series(run_rows)
    if not groups:
        return shell(empty_state(
            "No runs to chart.",
            "Live and synthetic runs are charted separately; both are empty here.",
        ))

    panels: list[str] = []
    for metric in metrics(run_rows):
        values = [
            group["metrics"][metric["id"]]["value"]
            for group in groups
            if group["metrics"][metric["id"]]["value"] is not None
        ]
        top = _scale_max(metric["id"], values)
        no_spread = top <= 0
        unit = metric["unit"] if no_spread else _unit_for(metric["id"], top)
        ticks = " · ".join(
            _amount(metric["id"], top * fraction, top) for fraction in (0.0, 0.5, 1.0)
        )
        axis_note = (
            "no spread — every reading is zero" if no_spread
            else f"axis {ticks} {unit}"
        )
        bars: list[str] = []
        for group in groups:
            entry = group["metrics"][metric["id"]]
            color = MODE_COLORS.get(group["mode"] or UNCLASSIFIED, C.TEXT_MUTED)
            value = entry["value"]
            if value is None:
                bar = (
                    f"<span style='display:inline-block;font-family:{T.FONT_MONO};"
                    f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED}'>no data "
                    f"({entry['excluded']} run(s) unmeasured)</span>"
                )
                shown = "—"
            else:
                # Latency on a 0–top axis: a 1 ms scripted run would be a
                # sub-pixel bar, so the bar shows the fraction and the label
                # always carries the exact value.
                bar = _bar(value / top if not no_spread else 0.0, color, width=180)
                shown = _reading(metric["id"], value, top, unit)
            bars.append(
                f"<div class='gb-bench-tech-row' data-metric='{_e(metric['id'])}' "
                f"data-series='{_e(group['label'])}' "
                f"data-value='{_e(shown)}' data-n='{entry['n']}' "
                f"style='display:flex;align-items:center;gap:{S.px(S.SM)}'>"
                f"<span style='width:{S.px(120)};font-family:{T.FONT_MONO};"
                f"font-size:{T.SIZE_XS}px;color:{C.TEXT_SECONDARY};overflow:hidden;"
                f"text-overflow:ellipsis;white-space:nowrap' "
                f"title='{_e(group['label'])}'>{_e(group['label'])}</span>"
                f"{bar}"
                f"<span style='width:{S.px(52)};text-align:right;"
                f"font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                f"color:{C.TELEMETRY_VALUE}'>{_e(shown)}</span>"
                f"<span style='width:{S.px(38)};font-family:{T.FONT_MONO};"
                f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED}'>n={entry['n']}</span>"
                f"</div>"
            )
        panels.append(
            f"<div class='gb-bench-tech-panel' data-panel='{_e(metric['id'])}' "
            f"style='padding:{S.px(S.SM)} {S.px(S.MD)};background:{C.BG_SURFACE};"
            f"border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_MD)}'>"
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:baseline;margin-bottom:{S.px(S.SM)}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_PRIMARY};letter-spacing:{T.TRACKING_WIDE};"
            f"text-transform:uppercase'>{_e(metric['label'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED}'>{_e(axis_note)}</span>"
            f"</div>" + "".join(bars) + "</div>"
        )

    note = (
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};margin-bottom:{S.px(S.SM)}'>"
        f"each panel has its own scale and its own n — bars from different panels "
        f"are not comparable</div>"
    )
    return shell(
        note + f"<div style='display:grid;"
        f"grid-template-columns:repeat(auto-fit,minmax({S.px(320)},1fr));"
        f"gap:{S.px(S.SM)}'>" + "".join(panels) + "</div>"
    )


def cells_html(run_rows: list[dict]) -> str:
    """Per case × repair setting, for sources that carry a case name."""
    table = cells(run_rows)
    if not table:
        return ""
    header = (
        f"<div style='display:flex;gap:{S.px(S.SM)};padding:{S.px(S.XS)} 0;"
        f"border-bottom:1px solid {C.BORDER_DEFAULT};font-family:{T.FONT_MONO};"
        f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED};"
        f"letter-spacing:{T.TRACKING_WIDE};text-transform:uppercase'>"
        f"<span style='flex:1'>case</span>"
        f"<span style='width:{S.px(70)}'>max_tries</span>"
        f"<span style='width:{S.px(60)}'>success</span>"
        f"<span style='width:{S.px(60)}'>repair</span>"
        f"<span style='width:{S.px(60)}'>latency</span>"
        f"<span style='width:{S.px(40)}'>n</span>"
        f"</div>"
    )
    lines: list[str] = []
    for cell in table:
        lines.append(
            f"<div class='gb-bench-cell' data-case='{_e(cell['case'])}' "
            f"data-max-tries='{cell['max_tries']}' "
            f"style='display:flex;gap:{S.px(S.SM)};padding:{S.px(S.XS)} 0;"
            f"border-bottom:1px solid {C.BORDER_SUBTLE};"
            f"font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px'>"
            f"<span style='flex:1;color:{C.TEXT_SECONDARY}'>{_e(cell['case'])}</span>"
            f"<span style='width:{S.px(70)};color:{C.TELEMETRY_VALUE}'>"
            f"{cell['max_tries'] if cell['max_tries'] is not None else '—'}</span>"
            f"<span style='width:{S.px(60)};color:{C.TELEMETRY_VALUE}'>"
            f"{_e(cell['metrics']['success']['display'])}</span>"
            f"<span style='width:{S.px(60)};color:{C.TELEMETRY_VALUE}'>"
            f"{_e(cell['metrics']['repair']['display'])}</span>"
            f"<span style='width:{S.px(60)};color:{C.TELEMETRY_VALUE}'>"
            f"{_e(cell['metrics']['latency']['display'])}</span>"
            f"<span style='width:{S.px(40)};color:{C.TEXT_MUTED}'>"
            f"{cell['n']}</span>"
            f"</div>"
        )
    return header + "".join(lines)


# ---------------------------------------------------------------------------
# HTML — the mode columns
# ---------------------------------------------------------------------------

def groups_html(section: dict) -> str:
    """LIVE and SYNTHETIC side by side, unclassified below and set apart.

    A bucket with no runs says so and shows no numbers: an empty column is the
    honest answer, and a zero-filled one would read as a measurement.
    """
    buckets = split(section.get("rows"))
    order = (MODE_LIVE, MODE_SYNTHETIC)
    columns: list[str] = []

    for mode in order:
        group = buckets[mode]
        color = MODE_COLORS[mode]
        chip = DS.status_chip(f"{MODE_LABELS[mode]} · {len(group)} run(s)", MODE_STATES[mode])
        if group:
            # The sample size, then the metrics, then the glance chart — all
            # scoped to this one mode.  The caution leads, because it decides
            # how much any number under it may be read as.
            body = (
                sample_html(group)
                + metrics_html(group)
                + f"<div style='margin-top:{S.px(S.MD)}'>{chart_minimal(group)}</div>"
            )
        else:
            body = empty_state(
                f"No {MODE_LABELS[mode].lower()} runs in this source.",
                "Nothing is shown rather than a zero.",
            )
        columns.append(
            f"<div class='gb-bench-group' data-mode='{mode}' "
            f"style='display:flex;flex-direction:column;gap:{S.px(S.SM)}'>"
            f"<div style='display:flex;align-items:center;gap:{S.px(S.SM)};"
            f"flex-wrap:wrap'>{chip}"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED}'>{_e(MODE_NOTES[mode])}</span></div>"
            f"{body}</div>"
        )

    unclassified = buckets[UNCLASSIFIED]
    extra = ""
    if unclassified:
        per_backend: dict[str, int] = {}
        for row in unclassified:
            per_backend[row["backend"]] = per_backend.get(row["backend"], 0) + 1
        chips = "".join(
            DS.badge(f"{name} · {count}", "neutral")
            for name, count in sorted(per_backend.items())
        )
        extra = (
            f"<div class='gb-bench-group' data-mode='{UNCLASSIFIED}' "
            f"style='margin-top:{S.px(S.MD)};padding:{S.px(S.SM)} {S.px(S.MD)};"
            f"background:{C.BG_ELEVATED};border:1px solid {C.BORDER_SUBTLE};"
            f"border-left:2px solid {C.TEXT_MUTED};"
            f"border-radius:{S.px(S.RADIUS_MD)}'>"
            f"<div style='display:flex;align-items:center;gap:{S.px(S.SM)};"
            f"flex-wrap:wrap;margin-bottom:{S.px(S.XS)}'>"
            f"{DS.status_chip(f'{MODE_LABELS[UNCLASSIFIED]} · {len(unclassified)} run(s)', MODE_STATES[UNCLASSIFIED])}"
            f"{chips}</div>"
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_SECONDARY}'>"
            f"{_e(MODE_NOTES[UNCLASSIFIED])} — they are excluded from both columns "
            f"above instead of being counted on one side. The oldest runs predate "
            f"the field; re-running is what makes a run classifiable.</div>"
            f"</div>"
        )

    return (
        f"<div class='gb-bench-groups' style='display:grid;"
        f"grid-template-columns:repeat(auto-fit,minmax({S.px(320)},1fr));"
        f"gap:{S.px(S.MD)}'>" + "".join(columns) + "</div>" + extra
    )


def section_html(section: dict) -> str:
    """One source: its counts, its LIVE/SYNTHETIC split, then one chart per mode."""
    title = DS.section_title(section.get("title", "Source"), icon="▦")
    source = (
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};margin-bottom:{S.px(S.MD)}'>"
        f"{_e(section.get('source', ''))} · {_e(section.get('path', ''))}"
        f"{' · ' + _e(section['note']) if section.get('note') else ''}</div>"
    )
    if not section.get("rows"):
        return shell(
            title + source +
            empty_state(
                "Nothing recorded here yet.",
                "Runs this app makes are appended to the run log; the benchmark "
                "runner also writes a stored artifact.",
            )
        )

    buckets = split(section.get("rows"))
    parts = [
        title, source, facts_html(section),
        f"<div style='height:{S.px(S.LG)}'></div>", groups_html(section),
        f"<div style='height:{S.px(S.LG)}'></div>",
        sub_title("Technical — one chart per mode, one scale per metric"),
    ]

    charted = False
    for mode in (MODE_LIVE, MODE_SYNTHETIC):
        group = buckets[mode]
        if not group:
            continue
        charted = True
        parts += [
            f"<div style='display:flex;align-items:center;gap:{S.px(S.SM)};"
            f"margin-bottom:{S.px(S.SM)}'>"
            f"{DS.status_chip(f'{MODE_LABELS[mode]} · {len(group)} run(s)', MODE_STATES[mode])}"
            f"</div>",
            chart_technical(group),
            f"<div style='height:{S.px(S.MD)}'></div>",
        ]

    if not charted:
        parts.append(empty_state(
            "No live or synthetic runs in this source, so no chart is drawn.",
            "Charting unclassified runs would invite a comparison their records "
            "do not support.",
        ))
    table = cells_html(section.get("rows") or [])
    if table:
        parts += [
            f"<div style='height:{S.px(S.LG)}'></div>",
            sub_title("Per case × repair setting"),
            shell(scroll_x(table, min_width=640)),
        ]
    return shell("".join(parts))


def caveats_html(sections: list[dict]) -> str:
    """What these numbers are, stated before anyone reads them as a verdict."""
    lines = [
        "Success means the plan passed the verifier — not that a robot reached a "
        "goal in the world.",
        "Latency is wall-clock time measured on the machine that ran it, so "
        "comparing it across machines is meaningless.",
        "Synthetic runs exercise the loop and the repair path with a scripted "
        "reader; they say nothing about model accuracy.",
    ]
    if len(sections) > 1:
        lines.append(
            "The sources overlap: the benchmark runner logs every run it makes, so "
            "a run can appear in both. Counts are per source and never added up."
        )
    items = "".join(
        f"<li style='margin-bottom:{S.px(S.XS)}'>{_e(line)}</li>" for line in lines
    )
    return shell(
        sub_title("Read this first") +
        f"<ul style='margin:0;padding-left:{S.px(S.LG)};font-family:{T.FONT_SANS};"
        f"font-size:{T.SIZE_SM}px;color:{C.TEXT_SECONDARY};"
        f"line-height:{T.LEADING_BASE}'>{items}</ul>"
    )


def sample_html(run_rows: list[dict] | None) -> str:
    """Whether this bucket of runs may be compared at all, in one line.

    The floor is the point: below it, the honest statement is that the numbers
    describe the runs that were made.  Nothing else in the view is allowed to
    imply more, and this line is what keeps the reader from reading a ranking
    into forty runs.
    """
    rows = list(run_rows or [])
    verdict = sample_verdict(len(rows))
    color = C.TEXT_SECONDARY if verdict["comparable"] else C.WARNING
    return (
        f"<div class='gb-bench-sample' "
        f"data-comparable='{'true' if verdict['comparable'] else 'false'}' "
        f"style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{color};margin-bottom:{S.px(S.SM)}'>{_e(verdict['note'])}</div>"
    )


def headline_html(sections: list[dict]) -> str:
    """ROBOTBENCH: what was measured, on how many scenarios, and the numbers.

    The four headline numbers are computed over ONE mode's runs and the block
    says which: the live runs when there are any, otherwise the scripted
    reader's — with the fact stated on the block, because a scripted result read
    as a model result is exactly the mistake this lab exists to prevent.  Each
    number carries its definition as a tooltip and its own sample size.
    """
    rows = [row for section in sections for row in (section.get("rows") or [])]
    buckets = split(rows)
    live = buckets[MODE_LIVE]
    scripted = buckets[MODE_SYNTHETIC]
    basis_rows = live or scripted
    basis = MODE_LIVE if live else (MODE_SYNTHETIC if scripted else None)

    scenarios = sorted({row["scenario"] for row in rows if row.get("scenario")})
    dataset = next((row["dataset"] for row in rows if row.get("dataset")), None)

    given = f"{len(scenarios)} scenario(s)" if scenarios else "no scenario ids recorded"
    context = f"{len(rows)} run(s) recorded · {given}"
    if dataset:
        context += f" · dataset {_e(dataset)}"

    by_id = {metric["id"]: metric for metric in metrics(basis_rows)}
    if basis is None:
        numbers = empty_state(
            "No runs recorded, so there is nothing to headline.",
            "Nothing is shown rather than four zeroes.",
        )
        basis_line = "no runs recorded — no benchmark number is available"
    else:
        picks = [
            ("success", "SUCCESS"), ("repair", "REPAIRED"),
            ("rejected", "REJECTED"), ("latency", "AVG LATENCY"),
        ]
        cards = [
            {
                "id": key,
                "label": label,
                "value": by_id[key]["display"],
                "detail": (
                    f"{by_id[key]['definition']} · n = {by_id[key]['n']}"
                ),
                "state": (
                    "warning" if by_id[key]["caution"]
                    else by_id[key]["state"]
                ),
            }
            for key, label in picks
        ]
        numbers = fact_cards(
            cards, css_class="gb-bench-headline", column_min=150,
            value_size=T.SIZE_XL,
        )
        basis_line = (
            f"over {len(basis_rows)} run(s) answered by a model"
            if basis == MODE_LIVE else
            f"over {len(basis_rows)} run(s) answered by the scripted reader — "
            f"this is not model performance"
        )

    counts = {mode: len(buckets[mode]) for mode in (MODE_LIVE, MODE_SYNTHETIC, UNCLASSIFIED)}
    chips = " ".join(
        DS.status_chip(f"{MODE_LABELS[mode]} {counts[mode]}", MODE_STATES[mode])
        for mode in (MODE_LIVE, MODE_SYNTHETIC, UNCLASSIFIED)
    )
    live_line = (
        f"{counts[MODE_LIVE]} live run(s) recorded — those are the only ones that "
        f"say anything about a model."
        if counts[MODE_LIVE]
        else "No live run has been recorded here, so nothing in this view measures "
             "a model yet. They are what "
             "<code>python -m gemmabot.benchmark --backend both</code> produces; "
             "run it with a reachable backend and this column fills with real "
             "measurements."
    )

    return shell(
        f"<div style='display:flex;align-items:baseline;gap:{S.px(S.MD)};"
        f"flex-wrap:wrap;margin-bottom:{S.px(S.XS)}'>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_LG}px;"
        f"color:{C.TEXT_PRIMARY};letter-spacing:{T.TRACKING_WIDE}'>"
        f"{PRODUCT.upper()}</span>"
        f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED}'>{context}</span></div>"
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_SECONDARY};margin-bottom:{S.px(S.SM)}'>{basis_line}</div>"
        + numbers
        + sample_html(basis_rows)
        + f"<div style='display:flex;align-items:center;gap:{S.px(S.SM)};"
          f"flex-wrap:wrap;margin-top:{S.px(S.SM)}'>{chips}</div>"
        + f"<div style='font-family:{T.FONT_SANS};font-size:{T.SIZE_SM}px;"
          f"color:{C.TEXT_SECONDARY};line-height:{T.LEADING_BASE};"
          f"margin-top:{S.px(S.SM)}'>Two kinds of run are measured here and never "
          f"merged: <span style='color:{C.RUNNING}'>live</span> runs were "
          f"answered by a model; <span style='color:{C.WARNING}'>synthetic</span> "
          f"runs by this project's scripted reader, which calls nothing. "
          f"{live_line}</div>"
        + _tooltip_help()
    )


def _tooltip_help() -> str:
    """One visible sentence saying the numbers explain themselves on hover."""
    return (
        f"<div style='font-family:{T.FONT_SANS};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};margin-top:{S.px(S.XS)}'>"
        f"Every number carries its definition — hover it, or read the line under "
        f"each card, before comparing anything.</div>"
    )


def panel(body: str) -> str:
    """The Benchmark tab's container."""
    return DS.panel(body, title=PRODUCT)
