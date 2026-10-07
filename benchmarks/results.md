# GemmaBot Benchmark Results

Each row carries the mode it was run in: `live` rows were answered by a model, `synthetic` rows by the scripted reader.

> **Synthetic runs only.** Every row below was answered by the scripted reader (`--dry`), not by a model. These numbers measure the planning loop and the repair setting — not model accuracy.
## Aggregate results

| Backend | Mode | max_tries | Success % | Avg attempts | Avg latency (s) | Runs |
|---------|------|-----------|----------:|-------------:|----------------:|-----:|
| dry | synthetic | 1 (no repair) | 100% | 1.00 | 0.000 | 15 |
| dry | synthetic | 3 (repair ≤3) | 100% | 2.00 | 0.000 | 15 |

## Per-case breakdown

| Backend | Mode | Case | max_tries | Success % | Avg attempts | Avg latency (s) |
|---------|------|------|-----------|----------:|-------------:|----------------:|
| dry | synthetic | default_map | 1 | 100% | 1.00 | 0.000 |
| dry | synthetic | default_map | 3 | 100% | 2.00 | 0.000 |
| dry | synthetic | long_detour_wall | 1 | 100% | 1.00 | 0.000 |
| dry | synthetic | long_detour_wall | 3 | 100% | 2.00 | 0.000 |
| dry | synthetic | one_turn_south | 1 | 100% | 1.00 | 0.000 |
| dry | synthetic | one_turn_south | 3 | 100% | 2.00 | 0.000 |
| dry | synthetic | several_turns_west | 1 | 100% | 1.00 | 0.000 |
| dry | synthetic | several_turns_west | 3 | 100% | 2.00 | 0.000 |
| dry | synthetic | tricky_pocket | 1 | 100% | 1.00 | 0.000 |
| dry | synthetic | tricky_pocket | 3 | 100% | 2.00 | 0.000 |
