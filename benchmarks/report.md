# RobotBench results

Dataset `gemmabot-grid-v1` — the 8x8 grid scenarios below, each run against the deterministic simulator.

Each row is one comparable cell: same dataset, model, backend, mode and repair setting. `mode` is `live` when a model answered the runs and `synthetic` when the scripted reader did; the two are never compared.

| dataset | model | backend | mode | max_tries | runs | success | failure | rejected | repaired (ok) | latency mean / median / p95 / max (s) | sample |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemmabot-grid-v1 | — | dry | synthetic | 1 | 15 | 15 | 0 | 0 | 0 (0) | 0.000 / 0.000 / 0.000 / 0.000 | below floor |
| gemmabot-grid-v1 | — | dry | synthetic | 3 | 15 | 15 | 0 | 0 | 10 (10) | 0.000 / 0.000 / 0.000 / 0.000 | below floor |

**Insufficient sample.** n = 15 — below the 30-run floor: these numbers describe these runs, not the model, and must not be used to rank one model above another.

