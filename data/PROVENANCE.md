# Data provenance

| File | Origin | Notes |
|---|---|---|
| `scenario_matrix.csv` | [`biomass-heat-scenarios`](https://github.com/DataWithSyed/biomass-heat-scenarios) `results/scenario_matrix.csv`, commit `6d4711f` (tag v0.1.0) | 4 processes x 2 preheat cases x 6 chains, central cost case. Copied unchanged |
| `scenario_matrix_integrated.csv` | same repo and commit, `results/scenario_matrix_integrated.csv` | integrated-site cost case (aux/project costs and staff x 0.5). Copied unchanged |
| `ranking_best_feasible.csv` | same repo and commit, `results/ranking_best_feasible.csv` | used by the tests as an independent check of the dashboard's filtering/ranking |
| `p2_continuous_counterfactual.csv` | same repo and commit | P2 furnace run continuously instead of two shifts |
| `de_lu_da_hourly.csv.gz` | same repo and commit, `data/de_lu_da_hourly.csv.gz` | hourly DE-LU day-ahead prices 2025-10-30 -> 2026-10-30 (8,761 h, mean 110.8 EUR/MWh). **Source: Energy-Charts.info (Fraunhofer ISE), CC BY 4.0; original data Bundesnetzagentur / SMARD.de.** Used only by the live recompute (electrolyser dispatch) |

All costs are EUR 2025 per MWh of process heat at 10 MW. The precomputed matrices use the
central inputs listed in the scenarios repo `results/run_meta.json` (gas 44.1 EUR/MWh GCV,
EUA 76.02 EUR/t, wood chips 30.3 EUR/MWh, 7 %, 20 years).

To refresh after a new scenarios release, re-run `scripts/run_scenarios.py` in that repo, copy
the files above and update the commit hash here. `tests/test_core.py` checks that a live
recompute reproduces the copied matrix.
