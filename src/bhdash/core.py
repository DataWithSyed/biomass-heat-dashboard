"""Dashboard logic, kept free of Streamlit so it can be unit-tested.

Two ways to get numbers:

* **Precomputed** - read the result matrices of ``biomass-heat-scenarios`` v0.1.0
  (copied into ``data/``, provenance in ``data/PROVENANCE.md``) and re-apply the
  feasibility rule with the user's "burner retrofit allowed" choice. Instant.
* **Live** - rebuild every chain with the scenario package for any process temperature,
  load profile and air-preheat choice, then cost it with ``bhlcoh.lcoh_breakdown`` under
  user cost inputs. Technical results (design point and the rolling day-ahead electrolyser
  dispatch) are cached, so moving a cost slider only re-runs the cost build-up.

Feasibility uses ``bhscen.quality.feasibility`` unchanged. The NG reference and break-even
CO2 price use ``bhscen.evaluate.ng_lcoh`` / ``breakeven_co2``.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

CHAINS = ("air", "oxy_none", "steam_dfb", "oxy_none_elec", "oxy_partial", "oxy_full")
ELECTROLYSER_CHAINS = ("oxy_none_elec", "oxy_partial", "oxy_full")
CHAIN_LABELS = {
    "air": "Air gasification",
    "oxy_none": "Oxyfuel, O2 from ASU",
    "steam_dfb": "Steam gasification (DFB)",
    "oxy_none_elec": "Oxyfuel, O2 from electrolyser, H2 blended",
    "oxy_partial": "Oxyfuel + partial methanation",
    "oxy_full": "Oxyfuel + full methanation",
}
COST_CASES = {"central": "scenario_matrix.csv", "integrated": "scenario_matrix_integrated.csv"}
# integrated-site case of the scenario study: aux/project costs and staff x 0.5
INTEGRATED_OVERRIDES = {"aux_project_mult": 0.5, "personnel_mult": 0.5}
T_MIN_C, T_MAX_C = 300.0, 1300.0    # range covered by the scenario study


@dataclass(frozen=True)
class Requirement:
    """A process heat requirement as the user states it."""
    t_process_c: float = 1000.0
    profile: str = "continuous"          # "continuous" | "two_shift"
    retrofit_allowed: bool = True        # may the burner / gas train be changed?
    recuperation: bool = False           # recuperative combustion-air preheat
    heat_mw: float = 10.0

    def validate(self) -> None:
        if not T_MIN_C <= self.t_process_c <= T_MAX_C:
            raise ValueError(f"process temperature must be {T_MIN_C:.0f}-{T_MAX_C:.0f} degC")
        if self.profile not in ("continuous", "two_shift"):
            raise ValueError(f"unknown load profile {self.profile!r}")


# The four process scenarios of the study (umbrella docs/scenarios.md)
PRESETS: Dict[str, Requirement] = {
    "P1": Requirement(300.0, "continuous", True),
    "P2": Requirement(800.0, "two_shift", True),
    "P3": Requirement(1000.0, "continuous", True),
    "P4": Requirement(1300.0, "continuous", False),
}
PRESET_LABELS = {
    "P1": "P1 - drying / low-temperature heat, 300 degC, continuous",
    "P2": "P2 - metal heat treatment, 800 degC, two shifts",
    "P3": "P3 - ceramics / brick kiln, 1000 degC, continuous (reference)",
    "P4": "P4 - very-high-temperature furnace, 1300 degC, retrofit-free",
}


def preset_key(req: Requirement) -> Optional[str]:
    """Preset whose temperature and profile match ``req`` (retrofit/preheat may differ)."""
    for k, p in PRESETS.items():
        if p.t_process_c == req.t_process_c and p.profile == req.profile \
                and req.heat_mw == 10.0:
            return k
    return None


# ---------------------------------------------------------------------------------------------
# Precomputed results
# ---------------------------------------------------------------------------------------------
@lru_cache(maxsize=4)
def _read(case: str) -> pd.DataFrame:
    if case not in COST_CASES:
        raise ValueError(f"cost case must be one of {list(COST_CASES)}")
    df = pd.read_csv(DATA / COST_CASES[case])
    for c in ("recuperation", "flame_ok", "heat_ok", "feasible", "wobbe_ok", "density_ok", "h2_ok"):
        df[c] = df[c].astype(str).str.lower().eq("true")
    df["reasons"] = df["reasons"].fillna("")
    return df


def load_matrix(case: str = "central") -> pd.DataFrame:
    return _read(case).copy()


def _reasons(row, retrofit_allowed: bool) -> str:
    """Rebuild the infeasibility reasons with the user's retrofit choice."""
    out = [r.strip() for r in str(row["reasons"]).split(";")
           if r.strip() and not r.strip().startswith("needs retrofit-free")]
    if not retrofit_allowed and row["gas_class"] == "retrofit":
        out.append(f"needs retrofit-free fuel, gas is '{row['gas_class']}'")
    return "; ".join(out)


def apply_retrofit_rule(df: pd.DataFrame, retrofit_allowed: bool) -> pd.DataFrame:
    """Same rule as ``bhscen.quality.feasibility`` with retrofit_free = not retrofit_allowed."""
    out = df.copy()
    out["gas_ok"] = True if retrofit_allowed else out["gas_class"].ne("retrofit")
    out["feasible"] = out["flame_ok"] & out["heat_ok"] & out["gas_ok"]
    out["reasons"] = out.apply(_reasons, axis=1, retrofit_allowed=retrofit_allowed)
    return _rank(out)


def _rank(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["rank"] = np.nan
    f = out[out.feasible]
    out.loc[f.index, "rank"] = f["lcoh"].rank(method="first")
    return out.sort_values(["feasible", "lcoh"], ascending=[False, True]).reset_index(drop=True)


def precomputed_view(process: str, recuperation: bool, case: str = "central",
                     retrofit_allowed: Optional[bool] = None) -> pd.DataFrame:
    """Rows of the precomputed matrix for one preset process / preheat / cost case.

    ``retrofit_allowed=None`` keeps the preset's own rule (P4 is retrofit-free)."""
    if process not in PRESETS:
        raise ValueError(f"process must be one of {list(PRESETS)}")
    if retrofit_allowed is None:
        retrofit_allowed = PRESETS[process].retrofit_allowed
    df = _read(case)
    sel = df[(df.process == process) & (df.recuperation == bool(recuperation))]
    return apply_retrofit_rule(sel, retrofit_allowed)


def best_feasible(view: pd.DataFrame) -> Optional[pd.Series]:
    f = view[view.feasible].sort_values("lcoh")
    return None if f.empty else f.iloc[0]


# ---------------------------------------------------------------------------------------------
# Live recompute
# ---------------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def load_prices():
    """Hourly DE-LU day-ahead prices used by the study (Energy-Charts, CC BY 4.0)."""
    from bhed.prices import load_prices as _lp
    s = _lp(DATA / "de_lu_da_hourly.csv.gz")
    return s.values, s.index


def cost_inputs_for(case: str = "central", **overrides):
    """``bhlcoh.CostInputs`` for a cost case plus user overrides.

    Uses the ``CostInputs()`` defaults (the study's central case). ``bhlcoh.central_inputs()``
    is avoided on purpose: it reads a data file that a pip-installed ``bhlcoh`` does not ship,
    and it returns the same 44.1 EUR/MWh gas price as the default."""
    from bhlcoh import CostInputs
    base = CostInputs()
    if case == "integrated":
        base = base.with_(**INTEGRATED_OVERRIDES)
    elif case != "central":
        raise ValueError(f"cost case must be one of {list(COST_CASES)}")
    return base.with_(**overrides) if overrides else base


def default_sizing(config: str, req: Requirement) -> Optional[Tuple[float, float]]:
    """Electrolyser size (x design rating) and storage hours for a live run.

    Taken from the LCOH-optimal choice of the precomputed central matrix at the nearest
    preset temperature with the same load profile and preheat (the grid search there needs
    ~9-12 year-long LPs per chain, too slow for an interactive app)."""
    if config not in ELECTROLYSER_CHAINS:
        return None
    df = _read("central")
    cands = [k for k, p in PRESETS.items() if p.profile == req.profile] or list(PRESETS)
    k = min(cands, key=lambda k: abs(PRESETS[k].t_process_c - req.t_process_c))
    r = df[(df.process == k) & (df.recuperation == req.recuperation) & (df.config == config)]
    r = r.iloc[0]
    return float(r.capacity_factor), float(r.storage_h)


def _process(req: Requirement):
    from bhscen.processes import Process
    return Process("custom", "user requirement", float(req.t_process_c), heat_mw=req.heat_mw,
                   profile=req.profile, retrofit_free=not req.retrofit_allowed)


@lru_cache(maxsize=256)
def technical(config: str, t_process_c: float, profile: str, recuperation: bool,
              heat_mw: float = 10.0, sizing: Optional[Tuple[float, float]] = None,
              standby_frac: Optional[float] = None) -> Dict:
    """Cost-independent part of a chain evaluation: design point, load profile, dispatch.

    Returns a dict with the ``ChainInputs`` (``bhlcoh``), the plant-model design point and
    the full-load hours. Cached: the electrolyser LP takes about 1 s per chain."""
    from bhscen.design import design
    from bhscen.dispatch import case_from_design, rolling_dispatch
    from bhscen.evaluate import STANDBY_FRAC, _chain_inputs
    from bhscen.processes import full_load_hours, load_profile
    req = Requirement(t_process_c, profile, True, recuperation, heat_mw)
    req.validate()
    proc = _process(req)
    prices, index = load_prices()
    dp = design(config, float(t_process_c), bool(recuperation), float(heat_mw))
    prof = load_profile(proc, index)
    flh = full_load_hours(prof)
    sb = STANDBY_FRAC if standby_frac is None else standby_frac
    disp = None
    if config in ELECTROLYSER_CHAINS:
        if sizing is None:
            raise ValueError("electrolyser chains need a sizing (capacity factor, storage h)")
        cf, sh = sizing
        disp = rolling_dispatch(prices, prof, case_from_design(dp, cf, sh))
        ch = _chain_inputs(config, dp, proc, prof, prices, flh, sb, disp, cf, sh)
    else:
        ch = _chain_inputs(config, dp, proc, prof, prices, flh, sb)
    unserved = float(disp["h2_unserved_kg"]) if disp else 0.0
    return {"chain": ch, "dp": dp, "flh": flh, "h2_unserved_kg": unserved}


def evaluate_live(config: str, req: Requirement, base, sizing=None) -> Dict:
    """One chain under a user requirement and cost inputs (``bhlcoh.CostInputs``)."""
    from bhlcoh.chains import grouped, lcoh_breakdown
    from bhscen.evaluate import breakeven_co2, cost_inputs, ng_lcoh
    from bhscen.quality import feasibility
    req.validate()
    if sizing is None:
        sizing = default_sizing(config, req)
    t = technical(config, float(req.t_process_c), req.profile, bool(req.recuperation),
                  float(req.heat_mw), sizing)
    proc = _process(req)
    dp, ch = t["dp"], t["chain"]
    c = cost_inputs(base, t["flh"], dp["o2_asu_kg_h"])
    b = lcoh_breakdown(ch, c)
    ng = ng_lcoh(c, proc, req.recuperation)
    f = feasibility(dp, proc)
    return {
        "config": config, "label": CHAIN_LABELS[config], "t_process_c": req.t_process_c,
        "profile": req.profile, "recuperation": req.recuperation, "flh": t["flh"],
        "t_air_c": dp["t_air_c"],
        "capacity_factor": ch.capacity_factor, "storage_h": ch.storage_h,
        "lcoh": b["total"], "capex_meur": b["capex_total_meur"],
        **{f"g_{k}": v for k, v in grouped(b).items()},
        "ng_lcoh": ng["total"], "ng_fuel": ng["fuel"], "ng_co2": ng["co2"],
        "gap_to_ng": b["total"] - ng["total"],
        "breakeven_co2_eur_t": breakeven_co2(b["total"], c, proc, req.recuperation),
        "co2_avoided_t_per_mwh": ng["co2_t_per_mwh"],
        "biomass_mwh_per_mwh": ch.biomass_mwh_per_mwh,
        "electricity_mwh_per_mwh": ch.electricity_mwh_per_mwh_heat,
        "adiabatic_flame_c": dp["adiabatic_flame_C"],
        "available_heat_frac": dp["available_heat_frac"],
        "h2_unserved_kg": t["h2_unserved_kg"],
        **f,
    }


def live_view(req: Requirement, base, chains: Iterable[str] = CHAINS) -> pd.DataFrame:
    """All chains for a requirement, ranked like the scenario study."""
    rows = [evaluate_live(cfg, req, base) for cfg in chains]
    return _rank(pd.DataFrame(rows))


# ---------------------------------------------------------------------------------------------
# Comparison helpers
# ---------------------------------------------------------------------------------------------
def co2_curve(view: pd.DataFrame, co2_prices: np.ndarray) -> pd.DataFrame:
    """LCOH versus CO2 price for gas and every feasible chain.

    Biomass chains carry no fossil CO2 cost, so their LCOH is flat; gas rises with slope
    ``co2_avoided_t_per_mwh``. The crossing is the break-even CO2 price."""
    if view.empty:
        raise ValueError("empty view")
    r0 = view.iloc[0]
    out = {"co2_eur_t": co2_prices,
           "Natural gas": r0["ng_fuel"] + r0["co2_avoided_t_per_mwh"] * co2_prices}
    for _, r in view[view.feasible].iterrows():
        out[r["label"]] = np.full_like(co2_prices, r["lcoh"], dtype=float)
    return pd.DataFrame(out)


def summary_sentence(view: pd.DataFrame, co2_price: float) -> str:
    b = best_feasible(view)
    if b is None:
        return "No chain passes the feasibility screen for this requirement."
    ng = float(b["ng_lcoh"])
    word = "above" if b["lcoh"] > ng else "below"
    return (f"Cheapest feasible chain: {b['label']} at {b['lcoh']:.0f} EUR/MWh heat, "
            f"{abs(b['lcoh'] - ng):.0f} EUR/MWh {word} natural gas ({ng:.0f} EUR/MWh at "
            f"{co2_price:.0f} EUR/t CO2). Break-even CO2 price: "
            f"{b['breakeven_co2_eur_t']:.0f} EUR/t.")


def temperature_sweep(temps: Iterable[float], base, profile: str = "continuous",
                      recuperation_cases: Iterable[bool] = (False, True)) -> pd.DataFrame:
    """Best feasible chain vs process temperature, with and without a burner retrofit.

    Live recompute at every temperature (electrolyser sizing from the nearest preset).
    Retrofit only changes the feasibility filter, so one evaluation serves both cases."""
    rows = []
    for rec in recuperation_cases:
        for t in temps:
            req = Requirement(float(t), profile, True, rec)
            full = pd.DataFrame([evaluate_live(cfg, req, base) for cfg in CHAINS])
            for allowed in (True, False):
                v = apply_retrofit_rule(full, allowed)
                b = best_feasible(v)
                rows.append({
                    "t_process_c": float(t), "profile": profile, "recuperation": rec,
                    "retrofit_allowed": allowed, "n_feasible": int(v.feasible.sum()),
                    "best_chain": None if b is None else b["config"],
                    "lcoh": np.nan if b is None else b["lcoh"],
                    "ng_lcoh": float(full.iloc[0]["ng_lcoh"]),
                    "breakeven_co2_eur_t": np.nan if b is None else b["breakeven_co2_eur_t"],
                    "infeasible": ", ".join(v[~v.feasible].config),
                })
    return pd.DataFrame(rows)
