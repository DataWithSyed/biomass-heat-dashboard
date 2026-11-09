"""Streamlit front end. All numbers come from ``bhdash.core`` (tested separately).

Run:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import numpy as np                      # noqa: E402
import streamlit as st                  # noqa: E402

from bhdash import core, plots          # noqa: E402

st.set_page_config(page_title="Biomass process heat vs natural gas", layout="wide")
st.title("Biomass gasification for industrial process heat")
st.caption("Screening dashboard for 10 MW of process heat: which gasification chains can serve "
           "a process, and what they cost against a natural-gas furnace. Part of the "
           "[Biomass Process Heat](https://github.com/DataWithSyed/biomass-process-heat) series. "
           "EUR 2025 per MWh of heat. Screening-level model, not a design tool.")

# ---------------------------------------------------------------------------------------------
# Sidebar: the process requirement
# ---------------------------------------------------------------------------------------------
sb = st.sidebar
sb.header("1. Process requirement")
mode = sb.radio("Mode", ["Study scenarios (precomputed)", "Custom requirement (live)"],
                key="mode",
                help="Precomputed is instant and shows the published study numbers. Live "
                     "rebuilds every chain with the plant model, dispatch LP and LCOH code.")
live = mode.startswith("Custom")

if not live:
    pk = sb.selectbox("Process scenario", list(core.PRESETS), key="preset",
                      format_func=lambda k: core.PRESET_LABELS[k], index=2)
    preset = core.PRESETS[pk]
    t_proc, profile = preset.t_process_c, preset.profile
    retrofit = sb.checkbox("Burner retrofit allowed", value=preset.retrofit_allowed,
                           key=f"retrofit_{pk}",   # per preset, so P4 starts retrofit-free
                           help="Unticked: only gases inside the DVGW G 260 H-gas Wobbe band "
                                "can be used (no burner change).")
else:
    t_proc = float(sb.slider("Process (flue-gas exit) temperature, degC", 300, 1300, 1000, 50,
                             key="t_proc"))
    profile = sb.selectbox("Load profile", ["continuous", "two_shift"], key="profile",
                           format_func=lambda p: {"continuous": "Continuous (8,000 h)",
                                                  "two_shift": "Two shifts, Mon-Fri 06-22 h"}[p])
    retrofit = sb.checkbox("Burner retrofit allowed", value=True, key="retrofit")
recup = sb.checkbox("Recuperative combustion-air preheat", value=False, key="recup",
                    help="Air preheated by the flue gas (effectiveness 0.6, max 700 degC). "
                         "Applied to the gas furnace as well.")

sb.header("2. Cost case")
case = sb.radio("Cost case", ["central", "integrated"], key="case",
                format_func=lambda c: {"central": "Central (stand-alone plant)",
                                       "integrated": "Integrated site (aux/project and staff x0.5)"}[c])

overrides = {}
if live:
    with sb.expander("Cost inputs (live mode)", expanded=True):
        base = core.cost_inputs_for(case)
        overrides = dict(
            gas_eur_mwh_gcv=st.slider("Gas price, EUR/MWh (GCV)", 10.0, 120.0,
                                      float(base.gas_eur_mwh_gcv), 0.5, key="gas"),
            co2_eur_t=st.slider("CO2 price, EUR/t", 0.0, 400.0, float(base.co2_eur_t), 1.0,
                                key="co2"),
            biomass_eur_mwh=st.slider("Wood chips, EUR/MWh", 10.0, 60.0,
                                      float(round(base.biomass_eur_mwh, 1)), 0.5, key="bio"),
            discount_rate=st.slider("Discount rate", 0.03, 0.12, float(base.discount_rate),
                                    0.005, key="wacc"),
            electricity_price_mult=st.slider("Day-ahead price multiplier", 0.5, 1.5, 1.0, 0.05,
                                             key="elmult"),
            electricity_adder_eur_mwh=st.slider("Grid fees/levies on electricity, EUR/MWh",
                                                0.0, 80.0, 0.0, 1.0, key="eladd"),
        )
co2_now = overrides.get("co2_eur_t", core.cost_inputs_for(case).co2_eur_t)

# ---------------------------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------------------------
if live:
    req = core.Requirement(t_proc, profile, retrofit, recup)
    with st.spinner("Recomputing chains (first run of a requirement takes a few seconds: "
                    "year-long electrolyser dispatch LPs)..."):
        view = core.live_view(req, core.cost_inputs_for(case, **overrides))
    source = ("live recompute with bhscen/bhlcoh; electrolyser size and storage taken from "
              "the study optimum at the nearest preset temperature")
else:
    view = core.precomputed_view(pk, recup, case, retrofit)
    source = "precomputed results of biomass-heat-scenarios v0.1.0 (data/PROVENANCE.md)"

# ---------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------
b = core.best_feasible(view)
c1, c2, c3, c4 = st.columns(4)
ng = float(view.iloc[0]["ng_lcoh"])
c4.metric("Natural gas + CO2", f"{ng:.0f} EUR/MWh")
if b is None:
    c1.metric("Best feasible chain", "none")
else:
    c1.metric("Best feasible chain", plots.SHORT.get(b["label"], b["label"]))
    c2.metric("Its LCOH", f"{b['lcoh']:.0f} EUR/MWh", f"{b['lcoh'] - ng:+.0f} vs gas",
              delta_color="inverse")
    c3.metric("Break-even CO2 price", f"{b['breakeven_co2_eur_t']:.0f} EUR/t")
st.info(core.summary_sentence(view, co2_now))
n_f = int(view.feasible.sum())
st.caption(f"{n_f} of {len(view)} chains pass the feasibility screen. Source: {source}.")

title = (f"{t_proc:.0f} degC, {profile.replace('_', '-')}, "
         f"{'recuperated' if recup else 'cold'} air, {case} costs")
left, right = st.columns(2)
with left:
    st.subheader("LCOH by chain")
    st.pyplot(plots.lcoh_bars(view, title), clear_figure=True)
with right:
    st.subheader("When would biomass win? LCOH vs CO2 price")
    co2_max = float(max(1500.0, np.nanmax(view[view.feasible].breakeven_co2_eur_t) * 1.1)
                    if n_f else 1500.0)
    st.pyplot(plots.co2_lines(view, co2_max, co2_now, title), clear_figure=True)

st.subheader("Feasibility and cost table")
cols = ["rank", "label", "feasible", "reasons", "lcoh", "ng_lcoh", "gap_to_ng",
        "breakeven_co2_eur_t", "gas_class", "wobbe_MJ_Nm3", "adiabatic_flame_c",
        "available_heat_frac", "capacity_factor", "storage_h", "capex_meur"]
st.dataframe(view[cols].round(2), hide_index=True, width="stretch")

with st.expander("Method and assumptions"):
    st.markdown(
        "* **Feasibility** (`bhscen.quality.feasibility`): adiabatic flame at least 300 K above "
        "the process temperature; at least 30 % of fuel LHV usable at process temperature; "
        "without burner retrofit the gas must lie in the DVGW G 260 H-gas Wobbe band "
        "(49.0-55.4 MJ/m3). Thresholds are screening assumptions.\n"
        "* **LCOH**: `bhlcoh.lcoh_breakdown` (annuity, GoBiGas-scaled CAPEX, Schmidt 2017 "
        "electrolyser, Goetz 2016 storage, VTT T91 ASU), full-load hours from the load profile. "
        "Electrolyser chains run a rolling day-ahead LP on real DE-LU 2025-26 prices.\n"
        "* **Gas reference**: the same furnace and air preheat fired with natural gas, "
        "Eurostat DE band I4 price (excl. taxes) plus the EU ETS price.\n"
        "* Two-shift profile, standby share and feasibility thresholds are synthetic or assumed. "
        "No recuperator or burner-retrofit cost is included.\n"
        "* Sources and the full assumption list: "
        "[biomass-heat-scenarios](https://github.com/DataWithSyed/biomass-heat-scenarios) and "
        "[biomass-heat-lcoh](https://github.com/DataWithSyed/biomass-heat-lcoh).")
st.caption("Day-ahead prices: Energy-Charts.info (Fraunhofer ISE), CC BY 4.0; "
           "source Bundesnetzagentur | SMARD.de.")

sweep_file = Path(__file__).resolve().parent / "results" / "temperature_sweep.csv"
if sweep_file.exists():
    with st.expander("Temperature sweep 300-1300 degC (precomputed, central costs, continuous)"):
        import pandas as pd                                     # noqa: E402
        sw = pd.read_csv(sweep_file)
        st.image(str(Path(__file__).resolve().parent / "figures" / "03_temperature_sweep.png"))
        st.dataframe(sw.round(1), hide_index=True, width="stretch")
