"""Tests for frontend/panels/benchmark.py — the Benchmark Lab.

No Streamlit, no network, no model.  The honesty rules are the point of these
tests: provenance comes from the record and never from the numbers, an
unmeasured metric is never rendered as a zero, and live and scripted runs are
never charted against each other.
"""
import copy
import re

import pytest

from frontend.panels import benchmark


def _visible(html: str) -> str:
    """The text a reader sees, whitespace-normalised."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def _record(**overrides):
    """A run record shaped like ``logger.log_run`` writes them."""
    record = {
        "timestamp": "2026-10-06T19:15:20+00:00",
        "instruction": "Move to the goal using the safest route.",
        "backend": "api",
        "success": True,
        "attempts": 1,
        "latency": 1.25,
        "actions": [{"cmd": "turn_right"}, {"cmd": "forward", "steps": 7}],
        "world": None,
        "mode": "live",
        "history": [],
    }
    record.update(overrides)
    return record


@pytest.fixture
def no_model(monkeypatch):
    """Every path to a model raises — a benchmark view must not need one."""
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the benchmark lab must not call a model")

    from frontend.panels import engine as engine_impl

    for name in (
        "run_plan", "run_map_vision", "get_ask", "get_vision_ask",
        "_planner_functions", "_vision_functions", "dry_ask", "dry_vision_ask",
    ):
        monkeypatch.setattr(engine_impl, name, explode)
    return explode


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------

def test_a_stated_mode_is_believed():
    live = benchmark.provenance(_record(mode="live"))
    scripted = benchmark.provenance(_record(mode="synthetic", backend="dry"))
    assert live["mode"] == "live"
    assert scripted["mode"] == "synthetic"
    assert "logged" in live["basis"]


def test_the_stated_mode_beats_the_backend_name():
    """A run is classified by what it recorded, not by what it was called."""
    found = benchmark.provenance(_record(backend="ollama", mode="synthetic"))
    assert found["mode"] == "synthetic"


def test_the_scripted_reader_is_synthetic_even_without_a_stated_mode():
    for backend in ("dry", "dry_model", "dry-4b", "scripted"):
        found = benchmark.provenance({"backend": backend, "success": True})
        assert found["mode"] == "synthetic", backend
        assert backend in found["basis"]


def test_a_run_that_does_not_say_how_it_ran_is_unclassified():
    """The old, tempting mistake: reading a model name as a live measurement."""
    for backend in ("api", "ollama", "local", "preview", "gemini"):
        found = benchmark.provenance({"backend": backend, "success": True,
                                      "latency": 38.0, "attempts": 1})
        assert found["mode"] is None, backend
        assert "does not say" in found["basis"]


def test_a_record_that_is_not_a_dict_is_unclassified():
    assert benchmark.provenance(None)["mode"] is None
    assert benchmark.provenance(["api"])["mode"] is None


# ---------------------------------------------------------------------------
# Rows and buckets
# ---------------------------------------------------------------------------

def test_every_run_lands_in_exactly_one_bucket():
    records = [
        _record(mode="live"),
        _record(mode="synthetic", backend="dry"),
        {"backend": "ollama", "success": True, "attempts": 1, "latency": 38.0},
    ]
    buckets = benchmark.split(benchmark.rows(records))
    assert [len(buckets[mode]) for mode in (
        benchmark.MODE_LIVE, benchmark.MODE_SYNTHETIC, benchmark.UNCLASSIFIED
    )] == [1, 1, 1]
    assert len(buckets[benchmark.UNCLASSIFIED]) == 1


def test_a_row_carries_only_what_its_source_recorded():
    """No source's missing field is filled in from another source."""
    log_row = benchmark.rows([_record()], "run log")[0]
    assert log_row["actions"] == 2
    assert log_row["case"] is None and log_row["max_tries"] is None

    artifact_row = benchmark.rows(
        [{"backend": "dry", "mode": "synthetic", "success": True, "attempts": 2,
          "latency": 0.001, "case": "default_map", "max_tries": 3}],
        "stored benchmark artifact",
    )[0]
    assert artifact_row["case"] == "default_map"
    assert artifact_row["max_tries"] == 3
    assert artifact_row["actions"] is None      # the artifact has no plan


def test_a_record_that_is_not_a_dict_is_skipped():
    assert benchmark.rows([None, "nope", 7, _record()]) == \
        benchmark.rows([_record()])
    assert benchmark.rows(None) == []


# ---------------------------------------------------------------------------
# Metrics — each one with its own denominator
# ---------------------------------------------------------------------------

def _metric(run_rows, key):
    return {item["id"]: item for item in benchmark.metrics(run_rows)}[key]


def test_success_rate_counts_the_runs_that_have_an_outcome():
    metric = _metric(benchmark.rows([
        _record(success=True), _record(success=True), _record(success=False),
    ]), "success")
    assert metric["value"] == pytest.approx(2 / 3)
    assert metric["display"] == "67%"
    assert metric["n"] == 3
    assert "2 of 3" in metric["detail"]


# The metrics that are a share of something, and so read "no data" rather than
# "—" when there is nothing to divide by.
RATE_METRICS = ("success", "rejected", "repair", "repair_success",
                "collision", "boundary")


def test_no_runs_means_no_rate_not_a_zero_rate():
    seen = set()
    for metric in benchmark.metrics([]):
        seen.add(metric["id"])
        assert metric["value"] is None
        assert metric["n"] == 0
        assert metric["display"] == (
            "no data" if metric["id"] in RATE_METRICS else "—"
        )
    assert seen == set(RATE_METRICS) | {"latency", "actions", "attempts"}


def test_a_run_without_an_outcome_is_excluded_not_counted_as_a_failure():
    metric = _metric(benchmark.rows([
        _record(success=True), _record(success=None),
    ]), "success")
    assert metric["n"] == 1
    assert metric["excluded"] == 1
    assert metric["value"] == 1.0


def test_repair_rate_is_the_share_that_needed_more_than_one_attempt():
    metric = _metric(benchmark.rows([
        _record(attempts=1), _record(attempts=2), _record(attempts=3),
    ]), "repair")
    assert metric["value"] == pytest.approx(2 / 3)
    assert metric["n"] == 3
    assert "2 of 3" in metric["detail"]
    assert "still finished" in metric["detail"]


def test_repair_rate_ignores_runs_that_never_recorded_an_attempt_count():
    metric = _metric(benchmark.rows([
        _record(attempts=3), {"backend": "dry", "mode": "synthetic", "success": True},
    ]), "repair")
    assert metric["n"] == 1
    assert metric["excluded"] == 1
    assert metric["value"] == 1.0


def test_latency_averages_only_measured_runs_and_says_how_many_it_skipped():
    metric = _metric(benchmark.rows([
        _record(latency=1.0), _record(latency=3.0), _record(latency=None),
    ]), "latency")
    assert metric["value"] == pytest.approx(2.0)
    assert metric["display"] == "2.00 s"
    assert metric["n"] == 2
    assert metric["excluded"] == 1
    assert "2 of 3" in metric["detail"]


def test_latency_with_nothing_measured_is_no_data():
    metric = _metric(benchmark.rows([_record(latency=None)]), "latency")
    assert metric["value"] is None
    assert metric["display"] == "—"
    assert metric["unit"] == "s"


def test_actions_averages_the_accepted_plan_length():
    metric = _metric(benchmark.rows([
        _record(actions=[{"cmd": "forward"}]),
        _record(actions=[{"cmd": "forward"}] * 5),
        _record(actions=None),
    ]), "actions")
    assert metric["value"] == pytest.approx(3.0)
    assert metric["display"] == "3.0"
    assert metric["excluded"] == 1


def test_attempts_average_and_its_excluded_count():
    metric = _metric(benchmark.rows([
        _record(attempts=1), _record(attempts=2), _record(attempts=None),
    ]), "attempts")
    assert metric["value"] == pytest.approx(1.5)
    assert metric["n"] == 2
    assert metric["excluded"] == 1


def test_every_metric_states_what_it_measures():
    for metric in benchmark.metrics(benchmark.rows([_record()])):
        assert metric["definition"] == benchmark.DEFINITIONS[metric["id"]]
        assert metric["label"] and metric["unit"]


# ---------------------------------------------------------------------------
# The unit is printed once
# ---------------------------------------------------------------------------

# The two fields disagree about who owns the unit: a rate is formatted with its
# "%", a count is not.  Painting both printed it twice — "100% %", "0.20 ms ms".
DOUBLED_UNITS = ("% %", "ms ms", "s s", "steps steps", "tries tries")


def test_a_unit_only_belongs_on_a_number():
    assert benchmark.split_unit("0.20 ms", "ms") == ("0.20", "ms")
    assert benchmark.split_unit("100%", "%") == ("100", "%")
    # A count leaves the unit out of its display; it still needs it added back.
    assert benchmark.split_unit("4.5", "steps") == ("4.5", "steps")
    # Placeholders are not measurements.
    assert benchmark.split_unit("—", "s") == ("—", "")
    assert benchmark.split_unit("no data", "%") == ("no data", "")
    # A display that is nothing but its unit cannot be split.
    assert benchmark.split_unit("ms", "ms") == ("ms", "")
    assert benchmark.split_unit("1.0", "") == ("1.0", "")


def test_a_metric_card_shows_all_five_readouts_with_their_unit_once():
    html = benchmark.metrics_html(benchmark.rows([
        _record(mode="synthetic", backend="dry", latency=0.20, success=True),
        _record(mode="synthetic", backend="dry", latency=0.20, success=False),
    ]))
    text = _visible(html)

    for doubled in DOUBLED_UNITS:
        assert doubled not in text, f"the unit is printed twice: {doubled!r}"

    assert "0.20 s" in text          # latency owns its unit in the display
    assert "50 %" in text             # the rate reads big number, small unit
    # A count leaves the unit to metric['unit'], and it is still added back.
    assert re.search(r"\d+(\.\d+)? steps\b", text), text
    assert re.search(r"\d+(\.\d+)? tries\b", text), text


def test_an_unmeasured_card_carries_no_unit_at_all():
    """"no data s" would dress a placeholder up as a measurement."""
    text = _visible(benchmark.metrics_html(benchmark.rows([
        _record(latency=None, success=None, actions=None, attempts=None),
    ])))
    for doubled in DOUBLED_UNITS:
        assert doubled not in text
    assert "no data" in text
    assert not re.search(r"no data\s+(%|s|ms|steps|tries)", text)
    assert not re.search(r"—\s+(%|s|ms|steps|tries)", text)


def test_the_chart_axes_still_get_their_unit_from_the_metric():
    """The split is for the cards; the axes keep reading metric['unit']."""
    rows = benchmark.rows([
        _record(mode="synthetic", backend="dry", latency=2.5),
    ])
    assert "axis" in benchmark.chart_technical(rows)
    assert benchmark._unit_for("latency", 2.5) == "s"
    assert benchmark._unit_for("latency", 0.002) == "ms"


def test_a_negative_or_absurd_value_does_not_become_a_measurement():
    metric = _metric(benchmark.rows([_record(latency="not a number")]), "latency")
    assert metric["value"] is None
    assert metric["excluded"] == 1


# ---------------------------------------------------------------------------
# Series and cells
# ---------------------------------------------------------------------------

def test_series_split_by_backend_and_repair_setting():
    rows = benchmark.rows([
        _record(backend="api", mode="live"),
        _record(backend="api", mode="live"),
        {"backend": "dry", "mode": "synthetic", "success": True, "attempts": 2,
         "latency": 0.0, "case": "default_map", "max_tries": 3},
        {"backend": "dry", "mode": "synthetic", "success": True, "attempts": 1,
         "latency": 0.0, "case": "default_map", "max_tries": 1},
    ])
    groups = benchmark.series(rows)
    labels = [group["label"] for group in groups]
    assert labels[0] == "API (Gemini)"                       # biggest n first
    assert [group["n"] for group in groups] == [2, 1, 1]
    assert set(labels[1:]) == {
        "Scripted (dry mode) · max_tries=1",
        "Scripted (dry mode) · max_tries=3",
    }
    assert all(
        set(group["metrics"]) == set(RATE_METRICS)
        | {"latency", "actions", "attempts"}
        for group in benchmark.series(rows)
    )


def test_cells_exist_only_for_sources_that_recorded_a_case():
    rows = benchmark.rows([
        {"backend": "dry", "mode": "synthetic", "success": True, "attempts": 1,
         "latency": 0.0, "case": "default_map", "max_tries": 1},
        _record(),                                            # a log run: no case
    ])
    cells = benchmark.cells(rows)
    assert [(cell["case"], cell["max_tries"], cell["n"]) for cell in cells] == [
        ("default_map", 1, 1)
    ]
    assert benchmark.cells(benchmark.rows([_record()])) == []


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def test_the_minimal_chart_draws_one_row_per_series_and_per_rate():
    rows = benchmark.rows([_record(mode="live"), _record(mode="live")])
    html = benchmark.chart_minimal(rows)
    # success + repair + rejected: the loop's own story
    assert html.count("gb-bench-min-row") == 3
    assert "67%" not in html and "n=2" in html
    assert "share one 0" in html or "one 0" in html  # the shared-scale note


def test_the_minimal_chart_does_not_draw_a_zero_bar_for_no_data():
    """0% and *no data* are different statements and are drawn differently."""
    rows = benchmark.rows([{"backend": "api", "mode": "live", "success": True,
                            "attempts": None, "latency": None, "actions": None}])
    html = benchmark.chart_minimal(rows)
    # Success is 100% and rejection is a real 0% — the verifier refused nothing,
    # which is a measurement.  Repair has no data and gets no bar at all.
    assert html.count("gb-bench-min-row") == 3
    assert html.count("background:#4a8fff") == 2
    # The one unmeasured row says so twice — where its bar would be and where
    # its value would be — and never as a zero-length bar.
    assert html.count("no data") == 2


def test_a_chart_of_one_mode_never_carries_the_other_mode_series():
    live = benchmark.rows([_record(backend="api", mode="live")])
    scripted = benchmark.rows([{"backend": "dry", "mode": "synthetic",
                               "success": True, "attempts": 1, "latency": 0.0}])
    assert "Scripted" not in benchmark.chart_minimal(live)
    assert "API (Gemini)" not in benchmark.chart_technical(scripted)


def test_the_technical_chart_is_small_multiples_one_panel_per_metric():
    html = benchmark.chart_technical(benchmark.rows([_record(mode="live")]))
    assert html.count("gb-bench-tech-panel") == 9
    for key in ("success", "rejected", "repair", "repair_success", "collision",
                "boundary", "latency", "actions", "attempts"):
        assert f"data-panel='{key}'" in html
    assert html.count("gb-bench-tech-row") == 9
    assert "data-n='1'" in html
    assert "not comparable" in html


def test_the_technical_chart_labels_the_axis_in_the_metric_its_own_unit():
    html = benchmark.chart_technical(benchmark.rows([
        _record(mode="live", latency=2.0),
    ]))
    assert "axis 0 · 50 · 100 %" in html            # a rate axis
    assert "axis 0.00 · 1.20 · 2.40 s" in html      # a latency axis, same panel set


def test_a_sub_millisecond_latency_is_drawn_in_ms_not_as_zero_seconds():
    """A scripted run is not instant; an axis of '0.00s' would say it was."""
    rows = benchmark.rows([
        _record(mode="synthetic", backend="dry", latency=0.0003),
        _record(mode="synthetic", backend="dry", latency=0.0001),
    ])
    html = benchmark.chart_technical(rows)
    assert "axis 0.00 · 0.12 · 0.24 ms" in html      # the mean is 0.0002 s
    assert "data-value='0.20 ms'" in html
    assert "0.00 s" not in html
    # And the readout card does not round it away either.
    metric = _metric(rows, "latency")
    assert metric["display"] == "0.20 ms"
    assert metric["unit"] == "ms"


def test_an_ordinary_latency_stays_in_seconds():
    plain = _metric(benchmark.rows([_record(latency=1.25)]), "latency")
    assert plain["display"] == "1.25 s" and plain["unit"] == "s"
    # A run whose clock shows exactly zero is reported as zero, not as 0.00 ms.
    zero = _metric(benchmark.rows([_record(latency=0.0)]), "latency")
    assert zero["display"] == "0.00 s" and zero["unit"] == "s"


def test_an_all_zero_metric_says_there_is_no_spread():
    """A rounded-away latency must not be spread over an axis it never used."""
    html = benchmark.chart_technical(benchmark.rows([
        _record(mode="synthetic", backend="dry", latency=0.0),
        _record(mode="synthetic", backend="dry", latency=0.0),
    ]))
    assert "no spread — every reading is zero" in html
    assert "axis 0.00 · 0.50 · 1.00 s" not in html
    assert "data-value='0.00 s'" in html          # the value is still reported


def test_an_unmeasured_metric_is_absent_from_the_technical_chart():
    html = benchmark.chart_technical(benchmark.rows([
        _record(mode="live", latency=None, actions=None),
    ]))
    assert "no data (1 run(s) unmeasured)" in html
    # latency, rejection and the two execution metrics have nothing to measure
    # here; the run recorded no world to reproduce, no attempt verdict and no
    # latency.  None of them is drawn as a zero-length bar.
    assert html.count("no data (1 run(s) unmeasured)") == 4


def test_both_charts_say_so_when_there_is_nothing_to_chart():
    # One shared empty state now, so the wording is the same in every panel.
    assert "No runs to chart." in benchmark.chart_minimal([])
    assert "No runs to chart." in benchmark.chart_technical(None)


# ---------------------------------------------------------------------------
# The rendered view
# ---------------------------------------------------------------------------

def _section(records=None, **overrides):
    section = {
        "id": "log",
        "title": "Run log",
        "source": "appended by the app",
        "path": "logs/runs.jsonl",
        "note": "a run's mode is recorded when it is logged",
        "rows": benchmark.rows(records if records is not None else [_record()]),
    }
    section.update(overrides)
    return section


def test_the_facts_count_each_bucket():
    rows = benchmark.rows([
        _record(mode="live"), _record(mode="synthetic", backend="dry"),
        {"backend": "ollama", "success": True, "attempts": 1, "latency": 1.0},
    ])
    facts = {row["id"]: row["value"] for row in benchmark.facts_rows(_section(rows))}
    assert facts == {"runs": "3", "live": "1", "synthetic": "1", "unclassified": "1"}


def test_the_view_separates_live_from_synthetic_and_shows_unclassified_apart():
    section = _section([
        _record(mode="live"), _record(mode="synthetic", backend="dry"),
        {"backend": "ollama", "success": True, "attempts": 1, "latency": 1.0},
    ])
    html = benchmark.section_html(section)
    assert "data-mode='live'" in html
    assert "data-mode='synthetic'" in html
    assert "data-mode='unclassified'" in html
    # The unclassified runs are explained, never folded into a side.
    assert "excluded from both columns" in html


def test_the_view_makes_no_claim_when_a_mode_has_no_runs():
    section = _section([_record(mode="synthetic", backend="dry")])
    html = benchmark.section_html(section)
    assert "No live runs in this source." in html
    assert "Nothing is shown rather than a zero." in html


def test_an_empty_source_says_it_is_empty():
    html = benchmark.section_html(_section(rows=[]))
    assert "Nothing recorded here yet." in html


def test_the_headline_says_so_when_no_live_run_exists():
    sections = [_section([{"backend": "dry", "mode": "synthetic",
                           "success": True, "attempts": 1, "latency": 0.0}])]
    html = benchmark.headline_html(sections)
    assert "No live run has been recorded" in html
    assert "python -m gemmabot.benchmark --backend both" in html
    assert "SYNTHETIC 1" in html


def test_the_headline_reports_live_runs_when_there_are_any():
    html = benchmark.headline_html([_section([_record(mode="live")])])
    assert "1 live run(s) recorded" in html
    assert "No live run has been recorded" not in html


def test_the_caveats_name_the_limits_of_the_numbers():
    html = benchmark.caveats_html([_section(), _section()])
    assert "passed the verifier" in html
    assert "wall-clock" in html
    assert "scripted reader" in html
    assert "never added up" in html           # the two sources overlap
    assert "never added up" not in benchmark.caveats_html([_section()])


def test_the_panel_is_a_design_system_panel():
    html = benchmark.panel("<div>body</div>")
    assert "gb-panel" in html and benchmark.PRODUCT in html


def test_rendering_the_whole_view_touches_no_model(no_model):
    """The lab measures logged runs; it has no path to a model at all."""
    section = _section([
        _record(mode="live"), _record(mode="synthetic", backend="dry"),
    ])
    body = (
        benchmark.headline_html([section])
        + benchmark.caveats_html([section])
        + benchmark.section_html(section)
    )
    assert "gb-bench-tech-panel" in body
    assert len(benchmark.panel(body)) > len(body)


def test_the_view_renders_a_realistic_mixed_log():
    """A log like the repo's own: scripted, model-named and ad-hoc backends."""
    records = [
        {"backend": "api", "success": True, "attempts": 1, "latency": 38.37},
        {"backend": "ollama", "success": False, "attempts": 3, "latency": 12.0},
        {"backend": "preview", "success": True, "attempts": 2, "latency": 0.1},
        {"backend": "dry_model", "success": True, "attempts": 2, "latency": 0.0},
        _record(mode="live"),
        _record(mode="synthetic", backend="dry"),
    ]
    section = _section(copy.deepcopy(records))
    html = benchmark.section_html(section)
    facts = {row["id"]: row["value"] for row in benchmark.facts_rows(section)}
    assert facts["unclassified"] == "3"      # api, ollama, preview: no mode recorded
    assert facts["synthetic"] == "2"         # dry_model by name + the stated one
    assert facts["live"] == "1"


# ---------------------------------------------------------------------------
# The runner — what it records about its own runs
# ---------------------------------------------------------------------------

DEFAULT_PLAN = [
    {"cmd": "turn_right"},
    {"cmd": "forward", "steps": 7},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 6},
    {"cmd": "turn_left"},
    {"cmd": "forward", "steps": 2},
]


def _fake_ask(*_args, **_kwargs):
    import json

    return json.dumps({"thought": "fake", "actions": DEFAULT_PLAN})


def _run(tmp_path, **kwargs):
    from gemmabot import benchmark as runner

    path = str(tmp_path / "runs.jsonl")
    results = runner.run_benchmark(
        backends=kwargs.pop("backends", {"dry": _fake_ask}),
        cases=runner.TEST_CASES[:1],
        runs_per_case=1,
        max_tries_list=(1,),
        log_path=path,
        **kwargs,
    )
    return runner, results, path


def test_a_dry_benchmark_records_itself_as_synthetic(tmp_path):
    """The old artifact called these runs 'api' and 'ollama'. This is why not."""
    runner, results, log_path = _run(tmp_path, dry=True)
    assert len(results) == 1
    record = results[0]
    assert record["mode"] == "synthetic"
    assert record["backend"] == "dry"
    assert record["requested_backend"] == "dry"

    # The run log agrees, and the run is replayable because the world was kept.
    from gemmabot import logger as run_logger

    logged = run_logger.load_runs(path=log_path)
    assert [entry["mode"] for entry in logged] == ["synthetic"]
    assert logged[0]["world"] is not None
    assert logged[0]["actions"] == DEFAULT_PLAN


def test_a_live_benchmark_records_the_backend_it_used(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_a: "y")
    runner, results, _ = _run(tmp_path, backends={"api": _fake_ask})
    assert results[0]["mode"] == "live"
    assert results[0]["backend"] == "api"
    assert results[0]["success"] is True
    assert results[0]["attempts"] == 1


def test_the_summary_says_when_every_run_was_scripted():
    from gemmabot import benchmark as runner

    text = runner.summarize([
        {"backend": "dry", "mode": "synthetic", "case": "default_map",
         "max_tries": 3, "run": 1, "success": True, "attempts": 1, "latency": 0.0,
         "error": ""},
    ])
    assert "Synthetic runs only" in text
    assert "| dry | synthetic | 3" in text
    assert "api" not in text and "ollama" not in text


def test_the_summary_warns_when_live_and_synthetic_are_mixed():
    from gemmabot import benchmark as runner

    rows = [
        {"backend": "api", "mode": "live", "case": "c", "max_tries": 1, "run": 1,
         "success": True, "attempts": 1, "latency": 1.0, "error": ""},
        {"backend": "dry", "mode": "synthetic", "case": "c", "max_tries": 1,
         "run": 1, "success": True, "attempts": 1, "latency": 0.0, "error": ""},
    ]
    text = runner.summarize(rows)
    assert "Mixed modes" in text
    assert "`live`" in text and "`synthetic`" in text


def test_a_record_without_a_mode_is_shown_as_unrecorded():
    from gemmabot import benchmark as runner

    text = runner.summarize([
        {"backend": "api", "case": "default_map", "max_tries": 1, "run": 1,
         "success": True, "attempts": 1, "latency": 0.0, "error": ""},
    ])
    assert "| api | unrecorded |" in text


def test_saved_results_carry_the_mode_into_the_artifact(tmp_path):
    import json

    from gemmabot import benchmark as runner

    out = tmp_path / "benchmarks" / "results.json"
    runner.save_results([
        {"backend": "dry", "requested_backend": "dry", "mode": "synthetic",
         "case": "default_map", "max_tries": 1, "run": 1, "success": True,
         "attempts": 1, "latency": 0.0, "error": ""},
    ], path=str(out))
    stored = json.loads(out.read_text(encoding="utf-8"))
    assert stored[0]["mode"] == "synthetic"
    markdown = out.with_suffix(".md").read_text(encoding="utf-8")
    assert "| Mode |" in markdown
    assert "synthetic" in markdown
    assert "answered by a model" in markdown


# ---------------------------------------------------------------------------
# RobotBench — the four outcome metrics
# ---------------------------------------------------------------------------

def test_the_rejection_rate_is_measured_over_the_runs_the_verifier_judged():
    refused = _record(success=False, attempts=2, history=[
        {"attempt": 1, "ok": False, "feedback": "hit the wall"},
        {"attempt": 2, "ok": False, "feedback": "hit the wall again"},
    ])
    fixed = _record(success=True, attempts=2, history=[
        {"attempt": 1, "ok": False, "feedback": "hit the wall"},
        {"attempt": 2, "ok": True, "feedback": "ok"},
    ])
    metric = _metric(benchmark.rows([refused, fixed]), "rejected")
    assert metric["value"] == pytest.approx(0.5)
    assert metric["display"] == "50%"
    assert metric["n"] == 2
    assert metric["excluded"] == 0
    assert metric["detail"] == (
        "1 of 2 runs ended with no verified plan · 3 of 4 attempts refused "
        "by the verifier"
    )


def test_a_failure_with_no_refusal_on_record_is_not_counted_as_rejection():
    """A backend error is not the verifier refusing a plan."""
    metric = _metric(benchmark.rows([
        {"backend": "api", "mode": "live", "success": False, "latency": 1.0},
    ]), "rejected")
    assert metric["value"] is None
    assert metric["n"] == 0
    assert metric["excluded"] == 1
    assert metric["display"] == "no data"


def test_repair_success_is_measured_over_the_runs_that_needed_repair():
    rows = benchmark.rows([
        _record(success=True, attempts=2),
        _record(success=False, attempts=3),
        _record(success=True, attempts=1),
    ])
    metric = _metric(rows, "repair_success")
    assert metric["value"] == pytest.approx(0.5)
    assert metric["display"] == "50%"
    assert metric["n"] == 2
    assert metric["detail"] == "1 of 2 repaired runs still passed the verifier"
    # The run that needed no repair is outside the population, not a failure.
    assert _metric(rows, "repair")["value"] == pytest.approx(2 / 3)


def _world(**overrides):
    from gemmabot.simulator import new_world

    world = copy.deepcopy(new_world())
    world.update(overrides)
    return world


def test_a_plan_stopped_by_a_wall_is_a_collision_not_a_boundary():
    # The default world waits with a wall at [3, 0]; forward 7 stops at [2, 0].
    record = _record(world=_world(), actions=[{"cmd": "forward", "steps": 7}])
    rows = benchmark.rows([record])
    collision = _metric(rows, "collision")
    boundary = _metric(rows, "boundary")
    assert collision["value"] == 1.0
    assert boundary["value"] == 0.0
    assert collision["n"] == boundary["n"] == 1
    assert collision["detail"] == (
        "1 of 1 runs proposed a plan the simulator stopped at an obstacle · "
        "1 of 1 reproduced plans hit one"
    )
    assert boundary["detail"] == (
        "0 of 1 runs proposed a plan the simulator stopped at the edge of the "
        "grid · 0 of 1 reproduced plans left it"
    )


def test_a_plan_that_stepped_off_the_grid_is_a_boundary_violation():
    # No walls: from [5, 0] facing East, "forward 7" walks to the edge at x=7
    # and the next step would leave the grid.
    record = _record(
        world=_world(walls=[], goal=[7, 1], robot=[5, 0]),
        actions=[{"cmd": "forward", "steps": 7}],
    )
    rows = benchmark.rows([record])
    assert _metric(rows, "boundary")["value"] == 1.0
    assert _metric(rows, "collision")["value"] == 0.0


def test_a_run_with_no_world_to_replay_is_not_counted_as_a_collision():
    record = _record(world=None, actions=[{"cmd": "forward", "steps": 7}])
    metric = _metric(benchmark.rows([record]), "collision")
    assert metric["value"] is None
    assert metric["n"] == 0
    assert metric["excluded"] == 1
    assert metric["detail"] == (
        "no run recorded a world and a plan to reproduce"
    )


def test_an_execution_metric_is_absent_for_a_run_that_never_blocked():
    """A plan that ran clean is a 0% collision rate — not a missing reading."""
    record = _record(
        world=_world(walls=[], goal=[1, 0]),
        actions=[{"cmd": "forward", "steps": 1}],
    )
    metric = _metric(benchmark.rows([record]), "collision")
    assert metric["value"] == 0.0
    assert metric["n"] == 1
    assert metric["display"] == "0%"


# ---------------------------------------------------------------------------
# RobotBench — every number explains itself
# ---------------------------------------------------------------------------

def test_every_metric_carries_a_definition_and_a_tooltip():
    for metric in benchmark.metrics(benchmark.rows([_record()])):
        assert metric["definition"] == benchmark.DEFINITIONS[metric["id"]]
        assert metric["tooltip"] == benchmark.TOOLTIPS[metric["id"]]
        assert len(metric["tooltip"]) > len(metric["definition"])
        assert metric["tooltip"].endswith(".")


def test_a_card_below_the_sample_floor_says_it_cannot_be_compared():
    html = benchmark.metrics_html(benchmark.rows([_record(mode="live")]))
    assert "data-caution='true'" in html
    assert f"below the {benchmark.MIN_SAMPLE}-run floor" in html
    assert "no comparison" in html
    # The long explanation rides on the card as a tooltip, not only in a legend.
    assert "A run counts as a success when its plan passed the verifier" in html


def test_a_card_at_or_above_the_floor_carries_no_caution():
    rows = benchmark.rows([_record(mode="live")] * benchmark.MIN_SAMPLE)
    html = benchmark.metrics_html(rows)
    assert "data-caution='true'" not in html
    assert f"below the {benchmark.MIN_SAMPLE}-run floor" not in html


def test_the_sample_line_says_when_the_numbers_may_not_be_compared():
    small = benchmark.sample_html(benchmark.rows([_record()]))
    assert "data-comparable='false'" in small
    assert "must not be used to rank one model above another" in small

    big = benchmark.rows([_record()] * benchmark.MIN_SAMPLE)
    assert "data-comparable='true'" in benchmark.sample_html(big)


# ---------------------------------------------------------------------------
# RobotBench — the headline never merges the two modes
# ---------------------------------------------------------------------------

def test_the_headline_numbers_come_from_the_live_runs_only():
    sections = [
        _section([
            _record(mode="live", success=True, latency=1.0),
            _record(mode="live", success=False, latency=1.0),
        ]),
        _section([
            _record(mode="synthetic", backend="dry", success=False, latency=0.001),
            _record(mode="synthetic", backend="dry", success=False, latency=0.002),
        ]),
    ]
    html = benchmark.headline_html(sections)
    assert benchmark.PRODUCT.upper() in html
    assert "over 2 run(s) answered by a model" in html
    # Half the live runs passed; the scripted failures below them are not the
    # headline's success rate.
    assert "data-fact='success' data-value='50%'" in html
    assert "data-fact='success' data-value='0%'" not in html


def test_the_headline_says_so_when_only_scripted_runs_exist():
    sections = [_section([
        _record(mode="synthetic", backend="dry", success=True, latency=0.001),
    ])]
    html = benchmark.headline_html(sections)
    assert "answered by the scripted reader" in html
    assert "this is not model performance" in html


def test_the_headline_shows_nothing_rather_than_zeroes_when_nothing_ran():
    html = benchmark.headline_html([_section(rows=[])])
    assert "nothing to headline" in html
    assert "Nothing is shown rather than four zeroes." in html
    assert "no benchmark number is available" in html


def test_the_headline_counts_the_scenarios_it_covers():
    sections = [_section([
        _record(mode="live", scenario="default_map", dataset="gemmabot-grid-v1"),
        _record(mode="live", scenario="tricky_pocket", dataset="gemmabot-grid-v1"),
    ])]
    html = benchmark.headline_html(sections)
    assert "2 scenario(s)" in html
    assert "2 run(s) recorded" in html
    assert "gemmabot-grid-v1" in html


def test_a_row_keeps_the_identifiers_an_audit_needs():
    row = benchmark.rows([{
        "dataset": "gemmabot-grid-v1", "scenario": "default_map",
        "case": "default_map", "model": "gemma-x", "backend": "api",
        "mode": "live", "timestamp": "2026-10-13T00:00:00+00:00",
        "run_id": "abc123def456", "success": True, "attempts": 1,
        "latency": 1.0, "history": [],
    }])[0]
    assert row["dataset"] == "gemmabot-grid-v1"
    assert row["scenario"] == "default_map"
    assert row["model"] == "gemma-x"
    assert row["run_id"] == "abc123def456"
    assert row["timestamp"].startswith("2026-10-13")


def test_the_lab_and_the_runner_share_the_sample_floor():
    from gemmabot import benchmark as runner
    from gemmabot.config import BENCH_MIN_SAMPLE

    assert benchmark.MIN_SAMPLE == runner.MIN_SAMPLE == BENCH_MIN_SAMPLE


# ---------------------------------------------------------------------------
# RobotBench — the runner's own results
# ---------------------------------------------------------------------------

def test_every_result_names_what_it_measured(tmp_path):
    from gemmabot import benchmark as runner

    _, results, _ = _run(tmp_path, dry=True)
    records = runner.result_records(results)
    assert len(records) == 1
    record = records[0]
    assert record["product"] == runner.PRODUCT
    assert record["dataset"] == runner.DATASET_ID
    assert record["scenarios"] == ["default_map"]
    assert record["backend"] == "dry" and record["mode"] == "synthetic"
    assert record["model"] is None          # no model answered a scripted run
    assert record["timestamp"]
    assert record["runs"] == 1
    assert record["successes"] + record["failures"] == record["runs"]
    assert record["run_ids"] == [results[0]["run_id"]]
    assert set(record["latency"]) == {
        "n", "excluded", "mean", "median", "p95", "min", "max",
    }


def test_a_per_run_record_can_be_traced_back_to_the_log(tmp_path):
    from gemmabot import benchmark as runner
    from gemmabot import logger as run_logger

    _, results, log_path = _run(tmp_path, dry=True)
    record = results[0]
    logged = {entry["run_id"]: entry for entry in run_logger.load_runs(path=log_path)}
    assert record["run_id"] in logged
    assert record["dataset"] == runner.DATASET_ID
    assert record["scenario"] == "default_map"
    assert record["timestamp"]
    # The logged run kept the world and the plan, so the result is replayable.
    assert logged[record["run_id"]]["world"] is not None
    assert logged[record["run_id"]]["actions"] is not None


def test_a_result_below_the_floor_may_not_be_read_as_a_comparison():
    from gemmabot import benchmark as runner

    below = runner.sample_verdict(runner.MIN_SAMPLE - 1)
    assert below["comparable"] is False
    assert "must not be used to rank" in below["note"]
    at = runner.sample_verdict(runner.MIN_SAMPLE)
    assert at["comparable"] is True
    assert "at or above" in at["note"]


def test_latency_statistics_ignore_runs_that_measured_nothing():
    from gemmabot import benchmark as runner

    stats = runner.latency_stats([1.0, None, 3.0, "nope"])
    assert stats["n"] == 2 and stats["excluded"] == 2
    assert stats["mean"] == 2.0 and stats["median"] == 2.0
    assert stats["min"] == 1.0 and stats["max"] == 3.0
    assert stats["p95"] == 3.0          # two points: the upper one is the p95
    empty = runner.latency_stats([])
    assert empty["mean"] is None and empty["n"] == 0


def test_a_synthetic_result_is_reproduced_without_naming_a_model():
    from gemmabot import benchmark as runner

    assert runner.reproduce_command("synthetic", "dry", 5) == \
        "python -m gemmabot.benchmark --dry --runs 5"
    assert runner.reproduce_command("live", "api", 5) == \
        "python -m gemmabot.benchmark --backend api --runs 5"


def test_the_report_is_saved_beside_the_results_the_lab_reads(tmp_path):
    import json
    from pathlib import Path

    from gemmabot import benchmark as runner

    _, results, _ = _run(tmp_path, dry=True)
    out = tmp_path / "benchmarks" / "results.json"
    paths = runner.save_results(results, path=str(out))
    assert set(paths) == {"results", "summary", "report", "report_markdown"}

    report = json.loads(Path(paths["report"]).read_text(encoding="utf-8"))
    assert report[0]["product"] == runner.PRODUCT
    assert report[0]["dataset"] == runner.DATASET_ID

    markdown = Path(paths["report_markdown"]).read_text(encoding="utf-8")
    assert runner.DATASET_ID in markdown
    assert "Insufficient sample" in markdown
    assert "must not be used to rank one model above another" in markdown


def test_the_dataset_lists_the_scenarios_it_measures():
    from gemmabot import benchmark as runner

    found = runner.dataset()
    assert found["id"] == runner.DATASET_ID
    assert found["scenarios"] == [case["name"] for case in runner.TEST_CASES]
    assert len(found["scenarios"]) >= 5


def test_collisions_are_measured_over_the_refused_attempts_too():
    """The accepted plan passed the verifier; the attempts are what collided."""
    record = _record(world=_world(), actions=DEFAULT_PLAN, history=[
        {"attempt": 1, "ok": False, "feedback": "blocked at [2, 0]",
         "actions": [{"cmd": "forward", "steps": 7}]},
        {"attempt": 2, "ok": True, "feedback": "ok", "actions": DEFAULT_PLAN},
    ])
    metric = _metric(benchmark.rows([record]), "collision")
    assert metric["value"] == 1.0
    assert metric["detail"] == (
        "1 of 1 runs proposed a plan the simulator stopped at an obstacle · "
        "1 of 2 reproduced plans hit one"
    )


def test_the_accepted_plan_alone_cannot_collide():
    """A verified plan is not evidence of anything: it passed by construction."""
    record = _record(
        world=_world(), actions=DEFAULT_PLAN,
        history=[{"attempt": 1, "ok": True, "feedback": "ok"}],
    )
    metric = _metric(benchmark.rows([record]), "collision")
    assert metric["value"] == 0.0
    assert metric["n"] == 1
