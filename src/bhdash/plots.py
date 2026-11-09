"""Matplotlib figures shared by the Streamlit app and the README figure script."""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .core import co2_curve

GROUPS = [("g_CAPEX", "CAPEX", "#4c72b0"), ("g_O&M", "O&M", "#8172b2"),
          ("g_Biomass", "Biomass", "#55a868"), ("g_Electricity", "Electricity", "#dd8452"),
          ("g_O2 sales", "O2 sales", "#937860")]
SHORT = {"Air gasification": "Air", "Oxyfuel, O2 from ASU": "Oxy + ASU",
         "Steam gasification (DFB)": "Steam DFB",
         "Oxyfuel, O2 from electrolyser, H2 blended": "Oxy + el. O2",
         "Oxyfuel + partial methanation": "Oxy + part. meth.",
         "Oxyfuel + full methanation": "Oxy + full meth."}


def lcoh_bars(view: pd.DataFrame, title: str = "", ax=None):
    """Stacked LCOH breakdown per chain (infeasible chains hatched) plus the gas reference."""
    own = ax is None
    if own:
        fig, ax = plt.subplots(figsize=(8, 4.2))
    v = view.sort_values("lcoh")
    x = np.arange(len(v) + 1)
    bottom = np.zeros(len(v))
    for col, name, colour in GROUPS:
        vals = v[col].to_numpy() if col in v else np.zeros(len(v))
        if not np.any(vals):
            continue
        pos = np.where(vals > 0, vals, 0)
        ax.bar(x[:-1], pos, bottom=bottom, color=colour, label=name, width=0.7)
        bottom += pos
    for i, (_, r) in enumerate(v.iterrows()):
        if not r["feasible"]:
            ax.bar(x[i], r["lcoh"], fill=False, hatch="//", edgecolor="0.3", width=0.7)
        ax.text(x[i], r["lcoh"] + 8, f"{r['lcoh']:.0f}", ha="center", fontsize=8)
    ng = float(v.iloc[0]["ng_lcoh"])
    ax.bar(x[-1], v.iloc[0]["ng_fuel"], color="0.55", width=0.7, label="Gas fuel")
    ax.bar(x[-1], v.iloc[0]["ng_co2"], bottom=v.iloc[0]["ng_fuel"], color="0.25", width=0.7,
           label="Gas CO2")
    ax.text(x[-1], ng + 8, f"{ng:.0f}", ha="center", fontsize=8)
    ax.axhline(ng, color="0.25", lw=0.8, ls="--")
    labels = [SHORT.get(l, l) + ("" if f else "\n(infeasible)")
              for l, f in zip(v["label"], v["feasible"])] + ["Natural\ngas"]
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel("EUR per MWh process heat")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, ncol=4, loc="upper left")
    ax.set_ylim(0, max(v["lcoh"].max(), ng) * 1.25)
    if own:
        fig.tight_layout()
        return fig
    return ax


def co2_lines(view: pd.DataFrame, co2_max: float = 1500.0, current: float | None = None,
              title: str = "", ax=None):
    """LCOH vs CO2 price: gas line against flat biomass lines; crossings = break-even."""
    own = ax is None
    if own:
        fig, ax = plt.subplots(figsize=(8, 4.2))
    p = np.linspace(0, co2_max, 151)
    d = co2_curve(view, p)
    ax.plot(d.co2_eur_t, d["Natural gas"], color="k", lw=2, label="Natural gas + CO2")
    for col in d.columns[2:]:
        ax.plot(d.co2_eur_t, d[col], lw=1.4, label=SHORT.get(col, col))
    feas = view[view.feasible]
    for _, r in feas.iterrows():
        be = r["breakeven_co2_eur_t"]
        if 0 <= be <= co2_max:
            ax.plot(be, r["lcoh"], "o", color="k", ms=4)
    if current is not None:
        ax.axvline(current, color="0.5", ls=":", lw=1)
        ax.text(current, ax.get_ylim()[1] * 0.02, f" today {current:.0f}", fontsize=7,
                color="0.4")
    ax.set_xlabel("CO2 price, EUR/t")
    ax.set_ylabel("EUR per MWh process heat")
    ax.set_title(title, fontsize=10)
    ax.legend(fontsize=7, loc="upper left")
    if own:
        fig.tight_layout()
        return fig
    return ax
