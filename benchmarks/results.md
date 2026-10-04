# GemmaBot Benchmark Results

## Aggregate results

| Backend | max_tries | Success % | Avg attempts | Avg latency (s) | Runs |
|---------|-----------|----------:|-------------:|----------------:|-----:|
| api | 1 (no repair) | 100% | 1.00 | 0.000 | 15 |
| api | 3 (repair ≤3) | 100% | 2.00 | 0.000 | 15 |
| ollama | 1 (no repair) | 100% | 1.00 | 0.000 | 15 |
| ollama | 3 (repair ≤3) | 100% | 2.00 | 0.000 | 15 |

## Per-case breakdown

| Backend | Case | max_tries | Success % | Avg attempts | Avg latency (s) |
|---------|------|-----------|----------:|-------------:|----------------:|
| api | default_map | 1 | 100% | 1.00 | 0.000 |
| api | default_map | 3 | 100% | 2.00 | 0.001 |
| api | long_detour_wall | 1 | 100% | 1.00 | 0.000 |
| api | long_detour_wall | 3 | 100% | 2.00 | 0.001 |
| api | one_turn_south | 1 | 100% | 1.00 | 0.000 |
| api | one_turn_south | 3 | 100% | 2.00 | 0.000 |
| api | several_turns_west | 1 | 100% | 1.00 | 0.000 |
| api | several_turns_west | 3 | 100% | 2.00 | 0.000 |
| api | tricky_pocket | 1 | 100% | 1.00 | 0.000 |
| api | tricky_pocket | 3 | 100% | 2.00 | 0.000 |
| ollama | default_map | 1 | 100% | 1.00 | 0.000 |
| ollama | default_map | 3 | 100% | 2.00 | 0.001 |
| ollama | long_detour_wall | 1 | 100% | 1.00 | 0.000 |
| ollama | long_detour_wall | 3 | 100% | 2.00 | 0.000 |
| ollama | one_turn_south | 1 | 100% | 1.00 | 0.000 |
| ollama | one_turn_south | 3 | 100% | 2.00 | 0.000 |
| ollama | several_turns_west | 1 | 100% | 1.00 | 0.000 |
| ollama | several_turns_west | 3 | 100% | 2.00 | 0.000 |
| ollama | tricky_pocket | 1 | 100% | 1.00 | 0.000 |
| ollama | tricky_pocket | 3 | 100% | 2.00 | 0.000 |
