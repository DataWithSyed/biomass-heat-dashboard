import math

import numpy as np
import pandas as pd
import pytest

from bhdash import core

DATA = core.DATA


def test_matrix_shape_and_provenance():
    for case in ("central", "integrated"):
        df = core.load_matrix(case)
        assert len(df) == 48                                   # 4 processes x 2 x 6 chains
        assert set(df.config) == set(core.CHAINS)
    assert (DATA / "PROVENANCE.md").read_text().count("6d4711f") >= 1


@pytest.mark.parametrize("case", ["central", "integrated"])
def test_precomputed_best_matches_published_ranking(case):
    """Dashboard filter + ranking reproduces ranking_best_feasible.csv of the scenarios repo."""
    ref = pd.read_csv(DATA / "ranking_best_feasible.csv")
    ref = ref[ref.cost_case == case]
    for _, r in ref.iterrows():
        rec = str(r.recuperation).lower() == "true"
        v = core.precomputed_view(r.process, rec, case)
        b = core.best_feasible(v)
        assert b["config"] == r.best_chain
        assert b["lcoh"] == pytest.approx(r.lcoh, rel=1e-9)
        assert b["breakeven_co2_eur_t"] == pytest.approx(r.breakeven_co2, rel=1e-9)
        assert int(v.feasible.sum()) == r.n_feasible


def test_retrofit_rule_p4():
    strict = core.precomputed_view("P4", False)               # preset: retrofit-free
    assert list(strict[strict.feasible].config) == ["oxy_full"]
    assert strict.loc[strict.config == "steam_dfb", "reasons"].item().startswith("needs retrofit")
    relaxed = core.precomputed_view("P4", False, retrofit_allowed=True)
    b = core.best_feasible(relaxed)
    assert b["config"] == "steam_dfb"
    assert b["breakeven_co2_eur_t"] == pytest.approx(379.07, abs=0.05)   # scenarios README
    # air gas fails on flame margin regardless of the retrofit choice
    assert not relaxed.loc[relaxed.config == "air", "feasible"].item()
    assert "flame margin" in relaxed.loc[relaxed.config == "air", "reasons"].item()


def test_retrofit_forbidden_at_p3_leaves_only_wobbe_compatible():
    v = core.precomputed_view("P3", False, retrofit_allowed=False)
    f = v[v.feasible]
    assert set(f.gas_class) <= {"drop-in", "wobbe-compatible"}
    assert list(f.config) == ["oxy_full"]


def test_ranks_are_consecutive_for_feasible_only():
    v = core.precomputed_view("P1", True)
    assert sorted(v[v.feasible]["rank"]) == list(range(1, int(v.feasible.sum()) + 1))
    assert v[~v.feasible]["rank"].isna().all()


def test_requirement_validation():
    with pytest.raises(ValueError):
        core.Requirement(200.0).validate()
    with pytest.raises(ValueError):
        core.Requirement(800.0, profile="three_shift").validate()
    with pytest.raises(ValueError):
        core.precomputed_view("P9", False)
    with pytest.raises(ValueError):
        core.cost_inputs_for("cheap")


def test_cost_inputs_defaults_and_integrated():
    c = core.cost_inputs_for("central")
    assert c.gas_eur_mwh_gcv == pytest.approx(44.1)
    assert c.co2_eur_t == pytest.approx(76.02)
    i = core.cost_inputs_for("integrated", co2_eur_t=150.0)
    assert (i.aux_project_mult, i.personnel_mult, i.co2_eur_t) == (0.5, 0.5, 150.0)


def test_default_sizing_nearest_preset():
    assert core.default_sizing("steam_dfb", core.Requirement()) is None
    df = core.load_matrix()
    r = df[(df.process == "P3") & (~df.recuperation) & (df.config == "oxy_full")].iloc[0]
    assert core.default_sizing("oxy_full", core.Requirement(1050.0)) == \
        (r.capacity_factor, r.storage_h)
    # two-shift requirements take the two-shift preset (P2) sizing
    r2 = df[(df.process == "P2") & (~df.recuperation) & (df.config == "oxy_partial")].iloc[0]
    assert core.default_sizing("oxy_partial", core.Requirement(1200.0, "two_shift")) == \
        (r2.capacity_factor, r2.storage_h)


@pytest.mark.parametrize("pk,rec,case,cfg", [
    ("P3", False, "central", "steam_dfb"),
    ("P1", True, "integrated", "air"),
    ("P2", False, "central", "oxy_none"),
    ("P4", True, "central", "oxy_full"),          # electrolyser chain: dispatch LP
])
def test_live_recompute_reproduces_matrix(pk, rec, case, cfg):
    p = core.PRESETS[pk]
    req = core.Requirement(p.t_process_c, p.profile, p.retrofit_allowed, rec)
    r = core.evaluate_live(cfg, req, core.cost_inputs_for(case))
    ref = core.precomputed_view(pk, rec, case).set_index("config").loc[cfg]
    assert r["lcoh"] == pytest.approx(ref.lcoh, rel=1e-9)
    assert r["ng_lcoh"] == pytest.approx(ref.ng_lcoh, rel=1e-9)
    assert r["breakeven_co2_eur_t"] == pytest.approx(ref.breakeven_co2_eur_t, rel=1e-9)
    assert r["feasible"] == ref.feasible


def test_cost_sliders_move_lcoh_as_expected():
    req = core.Requirement(1000.0)
    base = core.cost_inputs_for()
    r0 = core.evaluate_live("steam_dfb", req, base)
    r_bio = core.evaluate_live("steam_dfb", req, base.with_(biomass_eur_mwh=base.biomass_eur_mwh + 10))
    assert r_bio["lcoh"] - r0["lcoh"] == pytest.approx(10 * r0["biomass_mwh_per_mwh"], rel=1e-9)
    r_co2 = core.evaluate_live("steam_dfb", req, base.with_(co2_eur_t=200.0))
    assert r_co2["lcoh"] == pytest.approx(r0["lcoh"])                   # biomass: no CO2 cost
    assert r_co2["ng_lcoh"] - r0["ng_lcoh"] == pytest.approx(
        (200.0 - base.co2_eur_t) * r0["co2_avoided_t_per_mwh"])
    # at the break-even CO2 price gas and biomass cost the same
    r_be = core.evaluate_live("steam_dfb", req, base.with_(co2_eur_t=r0["breakeven_co2_eur_t"]))
    assert r_be["ng_lcoh"] == pytest.approx(r_be["lcoh"], rel=1e-9)


def test_co2_curve_crossing_is_breakeven():
    v = core.precomputed_view("P3", False)
    p = np.array([0.0, 453.0, 1000.0])
    d = core.co2_curve(v, p)
    b = core.best_feasible(v)
    be = b["breakeven_co2_eur_t"]
    ng_at_be = v.iloc[0]["ng_fuel"] + v.iloc[0]["co2_avoided_t_per_mwh"] * be
    assert ng_at_be == pytest.approx(b["lcoh"], rel=1e-9)
    assert list(d.columns[:2]) == ["co2_eur_t", "Natural gas"]
    assert d.shape[1] == 2 + int(v.feasible.sum())


def test_temperature_sweep_small():
    base = core.cost_inputs_for()
    s = core.temperature_sweep([1000.0], base, recuperation_cases=(False,))
    allowed = s[s.retrofit_allowed].iloc[0]
    strict = s[~s.retrofit_allowed].iloc[0]
    assert allowed.best_chain == "steam_dfb"
    assert allowed.lcoh == pytest.approx(268.24, abs=0.01)
    assert strict.best_chain == "oxy_full"
    assert strict.n_feasible == 1


def test_summary_sentence():
    s = core.summary_sentence(core.precomputed_view("P3", False), 76.02)
    assert "Steam gasification (DFB)" in s and "453 EUR/t" in s
    empty = core.precomputed_view("P3", False).assign(feasible=False)
    assert core.summary_sentence(empty, 76.0).startswith("No chain")
