"""Benchmark Lab — live and synthetic runs, measured and kept apart.

Owner: FRONTEND.  No Streamlit import, no network, no model, no timing done
here: every number is read out of runs that already happened.

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

Public surface
--------------
MODE_LIVE / MODE_SYNTHETIC / UNCLASSIFIED
MODE_LABELS / MODE_STATES / MODE_NOTES
DEFINITIONS                    what each metric means, in one line
provenance(record)             (mode, basis) for one run — never a guess
rows(records, source)          normalised run rows from either source
split(rows)                    mode → rows, plus the unclassified bucket
metrics(rows)                  the five metrics, each with value and n
series(rows)                   per backend (and repair setting) aggregates
cells(rows)                    per case × max_tries aggregates
facts_rows(section)            the section's headline counts
chart_minimal(rows)            low-ink glance chart for ONE mode's rows
chart_technical(rows)          labelled small multiples, one scale per metric
facts_html / metrics_html / groups_html / section_html / cells_html
intro_html / caveats_html / panel
"""
from __future__ import annotations

import html as _html

from frontend.components import components as DS
from frontend.components import colors as C
from frontend.components import spacing as S
from frontend.components import typography as T
from frontend.panels.engine import backend_label

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
    "repair": "share of runs that needed more than one attempt — the first plan "
              "was refused and the loop repaired it",
    "latency": "mean wall-clock seconds per run, over the runs that measured it; "
               "not a throughput measurement",
    "actions": "mean actions in the accepted plan, over the runs that recorded one",
    "attempts": "mean planning attempts per run, over the runs that recorded them",
}


def _e(value: object) -> str:
    """HTML-escape any value to a safe string."""
    return _html.escape(str(value))


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

def rows(records: list[dict] | None, source: str = "run log") -> list[dict]:
    """Normalise records from either source into one row shape.

    Reads only fields the records already have.  A field the source does not
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
        out.append({
            "backend": backend,
            "backend_label": backend_label(backend),
            "mode": found["mode"],
            "basis": found["basis"],
            "ok": record.get("success") if isinstance(record.get("success"), bool) else None,
            "attempts": _int_or_none(record.get("attempts")),
            "latency": _num(record.get("latency")),
            "actions": len(actions) if isinstance(actions, list) else None,
            "case": str(record["case"]) if record.get("case") else None,
            "max_tries": max_tries,
            "source": source,
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

def metrics(run_rows: list[dict] | None) -> list[dict]:
    """The five benchmark metrics, each with its own denominator.

    Returns one dict per metric: ``id``, ``label``, ``value`` (``None`` when
    nothing could be measured), ``display``, ``unit``, ``n`` (how many runs the
    value rests on), ``excluded`` (runs the metric had to skip), ``state``,
    ``definition`` and ``detail``.
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
        }

    no_data = "no data"

    return [
        item(
            "success", "Success rate", success,
            _pct(success) if success is not None else no_data, "%",
            len(known_ok), len(run_rows) - len(known_ok),
            f"{sum(1 for ok in known_ok if ok)} of {len(known_ok)} runs passed the "
            f"verifier" if known_ok else "no run recorded an outcome",
            "success" if success == 1.0 else ("warning" if success is not None else "neutral"),
        ),
        item(
            "repair", "Repair rate", repair,
            _pct(repair) if repair is not None else no_data, "%",
            len(known_attempts), len(run_rows) - len(known_attempts),
            f"{len(repaired)} of {len(known_attempts)} runs needed more than one "
            f"attempt · {recovered} of those still finished"
            if known_attempts else "no run recorded an attempt count",
            "warning" if repaired else "neutral",
        ),
        item(
            "latency", "Mean latency", latency,
            *_latency_display(latency),
            len(measured_latency), len(run_rows) - len(measured_latency),
            f"{len(measured_latency)} of {len(run_rows)} runs measured a latency"
            if measured_latency else "no run recorded a latency",
        ),
        item(
            "actions", "Mean actions", actions,
            "—" if actions is None else f"{actions:.1f}", "steps",
            len(known_actions), len(run_rows) - len(known_actions),
            f"{len(known_actions)} of {len(run_rows)} runs recorded a plan"
            if known_actions else "no run recorded a plan",
        ),
        item(
            "attempts", "Mean attempts", attempts,
            "—" if attempts is None else f"{attempts:.2f}", "tries",
            len(known_attempts), len(run_rows) - len(known_attempts),
            f"{len(known_attempts)} of {len(run_rows)} runs recorded an attempt count"
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

def _shell(body: str) -> str:
    """A section's surface, so the two sources read as two separate things."""
    return (
        f"<div style='background:{C.BG_SURFACE};"
        f"border:1px solid {C.BORDER_SUBTLE};border-radius:{S.px(S.RADIUS_MD)};"
        f"padding:{S.px(S.MD)}'>{body}</div>"
    )


def facts_html(section: dict) -> str:
    """The section's four counts, so a reader knows the sample size first."""
    cards: list[str] = []
    for row in facts_rows(section):
        color = MODE_COLORS.get(row["id"], C.TELEMETRY_VALUE)
        cards.append(
            f"<div class='gb-bench-fact' data-fact='{_e(row['id'])}' "
            f"data-value='{_e(row['value'])}' "
            f"style='display:flex;flex-direction:column;gap:{S.px(S.XS)};"
            f"padding:{S.px(S.SM)} {S.px(S.MD)};background:{C.BG_ELEVATED};"
            f"border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_MD)}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
            f"text-transform:uppercase'>{_e(row['label'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_LG}px;"
            f"color:{color}'>{_e(row['value'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED}'>{_e(row['detail'])}</span>"
            f"</div>"
        )
    return (
        f"<div style='display:grid;"
        f"grid-template-columns:repeat(auto-fit,minmax({S.px(130)},1fr));"
        f"gap:{S.px(S.SM)}'>" + "".join(cards) + "</div>"
    )


def metrics_html(run_rows: list[dict]) -> str:
    """The five metrics as cards, each with its denominator and definition."""
    cards: list[str] = []
    for metric in metrics(run_rows):
        empty = metric["value"] is None
        color = C.TEXT_MUTED if empty else C.TELEMETRY_VALUE
        excluded_note = (
            f" · {metric['excluded']} not measured"
            if metric["excluded"] else ""
        )
        cards.append(
            f"<div class='gb-bench-metric' data-metric='{_e(metric['id'])}' "
            f"data-value='{'' if empty else _e(metric['display'])}' "
            f"data-n='{metric['n']}' "
            f"style='display:flex;flex-direction:column;gap:{S.px(S.XS)};"
            f"padding:{S.px(S.SM)} {S.px(S.MD)};background:{C.BG_SURFACE};"
            f"border:1px solid {C.BORDER_SUBTLE};"
            f"border-radius:{S.px(S.RADIUS_MD)}'>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
            f"text-transform:uppercase'>{_e(metric['label'])}</span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_LG}px;"
            f"color:{color}'>{_e(metric['display'])}"
            f"<span style='font-size:{T.SIZE_XS}px;color:{C.TELEMETRY_UNIT}'> "
            f"{'' if empty else _e(metric['unit'])}</span></span>"
            f"<span style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
            f"color:{C.TEXT_SECONDARY}'>n = {metric['n']}"
            f"{excluded_note}"
            f"</span>"
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
    """The glance: success and repair per series, one shared 0–100% scale.

    Only those two, because they are the only pair that share a unit.  Adding
    latencies or action counts to the same bars would make the lengths compare
    things that are not comparable.

    Call it with one mode's rows: bars from live and scripted runs on one chart
    would invite a comparison between a model and a script.
    """
    groups = series(run_rows)
    if not groups:
        return _shell(
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED}'>no runs to chart</div>"
        )

    lines: list[str] = []
    for group in groups:
        color = MODE_COLORS.get(group["mode"] or UNCLASSIFIED, C.TEXT_MUTED)
        success = group["metrics"]["success"]
        repair = group["metrics"]["repair"]
        for metric, mark in ((success, "success"), (repair, "repair")):
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
                f"{'' if mark == 'repair' else _e(group['label'])}</span>"
                f"<span style='width:{S.px(48)};font-family:{T.FONT_MONO};"
                f"font-size:{T.SIZE_XS}px;color:{C.TEXT_MUTED}'>"
                f"{'repair' if mark == 'repair' else 'success'}</span>"
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
        f"both bars share one 0–100% scale</div>"
    )
    return _shell(legend + "".join(lines))


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
        return _shell(
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED}'>no runs to chart</div>"
        )

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
    return _shell(
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
            # Metrics, then the glance chart — both scoped to this one mode.
            body = (
                metrics_html(group)
                + f"<div style='margin-top:{S.px(S.MD)}'>{chart_minimal(group)}</div>"
            )
        else:
            body = (
                f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
                f"color:{C.TEXT_MUTED};padding:{S.px(S.SM)} 0'>"
                f"no {MODE_LABELS[mode].lower()} runs in this source — nothing is "
                f"shown rather than a zero</div>"
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
        return _shell(
            title + source +
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED}'>nothing recorded here yet</div>"
        )

    buckets = split(section.get("rows"))
    parts = [
        title, source, facts_html(section),
        f"<div style='height:{S.px(S.LG)}'></div>", groups_html(section),
        f"<div style='height:{S.px(S.LG)}'></div>",
        _sub_title("Technical — one chart per mode, one scale per metric"),
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
        parts.append(
            f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_SM}px;"
            f"color:{C.TEXT_MUTED}'>no live or synthetic runs in this source, so no "
            f"chart is drawn — charting unclassified runs would invite a "
            f"comparison their records do not support</div>"
        )
    table = cells_html(section.get("rows") or [])
    if table:
        parts += [
            f"<div style='height:{S.px(S.LG)}'></div>",
            _sub_title("Per case × repair setting"),
            _shell(table),
        ]
    return _shell("".join(parts))


def _sub_title(text: str) -> str:
    return (
        f"<div style='font-family:{T.FONT_MONO};font-size:{T.SIZE_XS}px;"
        f"color:{C.TEXT_MUTED};letter-spacing:{T.TRACKING_WIDE};"
        f"text-transform:uppercase;margin-bottom:{S.px(S.SM)}'>{_e(text)}</div>"
    )


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
    return _shell(
        _sub_title("Read this first") +
        f"<ul style='margin:0;padding-left:{S.px(S.LG)};font-family:{T.FONT_SANS};"
        f"font-size:{T.SIZE_SM}px;color:{C.TEXT_SECONDARY};"
        f"line-height:{T.LEADING_BASE}'>{items}</ul>"
    )


def intro_html(sections: list[dict]) -> str:
    """What this view is, and where the data actually stands right now.

    The second half matters more than the first: if no live run has been
    recorded, the view says so instead of letting an empty LIVE column read as a
    clean bill of health, and names the command that would produce one.
    """
    counts = {
        mode: sum(len(split(section.get("rows"))[mode]) for section in sections)
        for mode in (MODE_LIVE, MODE_SYNTHETIC, UNCLASSIFIED)
    }
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
    modes = " · ".join(
        DS.status_chip(f"{MODE_LABELS[mode]} {counts[mode]}", MODE_STATES[mode])
        for mode in (MODE_LIVE, MODE_SYNTHETIC, UNCLASSIFIED)
    )
    return _shell(
        f"<div style='display:flex;align-items:center;gap:{S.px(S.SM)};"
        f"flex-wrap:wrap;margin-bottom:{S.px(S.MD)}'>{modes}</div>"
        f"<div style='font-family:{T.FONT_SANS};font-size:{T.SIZE_BASE}px;"
        f"color:{C.TEXT_SECONDARY};line-height:{T.LEADING_BASE}'>"
        f"Two kinds of run are measured here, and they are never merged: "
        f"<span style='color:{C.RUNNING}'>live</span> runs were answered by a "
        f"model; <span style='color:{C.WARNING}'>synthetic</span> runs by this "
        f"project's scripted reader, which calls nothing. "
        f"{live_line}</div>"
    )


def panel(body: str) -> str:
    """The Benchmark tab's container."""
    return DS.panel(body, title="Benchmark Lab")
