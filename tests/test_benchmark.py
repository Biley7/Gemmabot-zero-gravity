"""Tests for frontend/panels/benchmark.py — the Benchmark Lab.

No Streamlit, no network, no model.  The honesty rules are the point of these
tests: provenance comes from the record and never from the numbers, an
unmeasured metric is never rendered as a zero, and live and scripted runs are
never charted against each other.
"""
import copy

import pytest

from frontend.panels import benchmark


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


def test_no_runs_means_no_rate_not_a_zero_rate():
    for metric in benchmark.metrics([]):
        assert metric["value"] is None
        assert metric["n"] == 0
        assert metric["display"] == "no data" if metric["id"] in (
            "success", "repair") else metric["display"] == "—"


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
        set(group["metrics"]) == {"success", "repair", "latency", "actions", "attempts"}
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
    assert html.count("gb-bench-min-row") == 2       # success + repair
    assert "67%" not in html and "n=2" in html
    assert "share one 0" in html or "one 0" in html  # the shared-scale note


def test_the_minimal_chart_does_not_draw_a_zero_bar_for_no_data():
    rows = benchmark.rows([{"backend": "api", "mode": "live", "success": True,
                            "attempts": None, "latency": None, "actions": None}])
    html = benchmark.chart_minimal(rows)
    assert "no data" in html
    # The success bar is drawn; the repair bar is not.
    assert html.count("gb-bench-min-row") == 2
    assert html.count("background:#4a8fff") == 1


def test_a_chart_of_one_mode_never_carries_the_other_mode_series():
    live = benchmark.rows([_record(backend="api", mode="live")])
    scripted = benchmark.rows([{"backend": "dry", "mode": "synthetic",
                               "success": True, "attempts": 1, "latency": 0.0}])
    assert "Scripted" not in benchmark.chart_minimal(live)
    assert "API (Gemini)" not in benchmark.chart_technical(scripted)


def test_the_technical_chart_is_small_multiples_one_panel_per_metric():
    html = benchmark.chart_technical(benchmark.rows([_record(mode="live")]))
    assert html.count("gb-bench-tech-panel") == 5
    for key in ("success", "repair", "latency", "actions", "attempts"):
        assert f"data-panel='{key}'" in html
    assert html.count("gb-bench-tech-row") == 5
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
    assert html.count("no data (1 run(s) unmeasured)") == 2


def test_both_charts_say_so_when_there_is_nothing_to_chart():
    assert "no runs to chart" in benchmark.chart_minimal([])
    assert "no runs to chart" in benchmark.chart_technical(None)


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
    assert "no live runs in this source" in html
    assert "nothing is shown rather than a zero" in html


def test_an_empty_source_says_it_is_empty():
    html = benchmark.section_html(_section(rows=[]))
    assert "nothing recorded here yet" in html


def test_the_intro_says_so_when_no_live_run_exists():
    sections = [_section([{"backend": "dry", "mode": "synthetic",
                           "success": True, "attempts": 1, "latency": 0.0}])]
    html = benchmark.intro_html(sections)
    assert "No live run has been recorded" in html
    assert "python -m gemmabot.benchmark --backend both" in html
    assert "SYNTHETIC 1" in html


def test_the_intro_reports_live_runs_when_there_are_any():
    html = benchmark.intro_html([_section([_record(mode="live")])])
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
    assert "gb-panel" in html and "Benchmark Lab" in html


def test_rendering_the_whole_view_touches_no_model(no_model):
    """The lab measures logged runs; it has no path to a model at all."""
    section = _section([
        _record(mode="live"), _record(mode="synthetic", backend="dry"),
    ])
    body = (
        benchmark.intro_html([section])
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
