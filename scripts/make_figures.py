"""Build the README figures and the temperature sweep (results/temperature_sweep.csv).

    python scripts/make_figures.py      # ~1-2 min (electrolyser LPs at 11 temperatures x 2)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib                                   # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                     # noqa: E402
import numpy as np                                  # noqa: E402

from bhdash import core, plots                      # noqa: E402

FIG, RES = ROOT / "figures", ROOT / "results"
FIG.mkdir(exist_ok=True); RES.mkdir(exist_ok=True)

# 1-2: the reference process P3 as the dashboard shows it
v = core.precomputed_view("P3", False)
plots.lcoh_bars(v, "P3 1000 degC, continuous, cold air, central costs").savefig(
    FIG / "01_p3_lcoh.png", dpi=130)
plots.co2_lines(v, 1500, 76.02, "P3: LCOH vs CO2 price").savefig(FIG / "02_p3_co2.png", dpi=130)
plt.close("all")

# 3: temperature sweep (live recompute, central costs, continuous duty)
t0 = time.time()
temps = np.arange(300, 1301, 100, dtype=float)
sw = core.temperature_sweep(temps, core.cost_inputs_for())
sw.to_csv(RES / "temperature_sweep.csv", index=False)
print(f"sweep {time.time() - t0:.0f} s")
print(sw.round(1).to_string(index=False))

fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
for rec, ls in ((False, "-"), (True, "--")):
    for allowed, col in ((True, "#55a868"), (False, "#c44e52")):
        d = sw[(sw.recuperation == rec) & (sw.retrofit_allowed == allowed)]
        lab = f"{'retrofit allowed' if allowed else 'retrofit-free'}, {'recup.' if rec else 'cold air'}"
        a1.plot(d.t_process_c, d.lcoh, ls, color=col, marker="o", ms=3, label="best biomass, " + lab)
        a2.plot(d.t_process_c, d.breakeven_co2_eur_t, ls, color=col, marker="o", ms=3, label=lab)
    g = sw[(sw.recuperation == rec) & sw.retrofit_allowed]
    a1.plot(g.t_process_c, g.ng_lcoh, ls, color="k", label=f"natural gas, {'recup.' if rec else 'cold air'}")
a1.set_xlabel("Process temperature, degC"); a1.set_ylabel("EUR per MWh heat")
a1.set_title("Cheapest feasible chain vs natural gas (central costs)", fontsize=10)
a2.set_xlabel("Process temperature, degC"); a2.set_ylabel("EUR/t CO2")
a2.set_title("Break-even CO2 price of the cheapest feasible chain", fontsize=10)
a1.legend(fontsize=7); a2.legend(fontsize=7)
fig.tight_layout(); fig.savefig(FIG / "03_temperature_sweep.png", dpi=130)
print("figures written")
