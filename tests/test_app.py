"""Streamlit AppTest smoke tests: the app renders without exceptions in both modes."""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_app_precomputed_default():
    at = st_testing.AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Steam" in m.value for m in at.metric)
    assert any("453" in i.value for i in at.info)


def test_app_precomputed_p4_toggle_retrofit():
    at = st_testing.AppTest.from_file(APP, default_timeout=60).run()
    at.selectbox(key="preset").select("P4").run()
    assert not at.exception
    assert "full methanation" in at.info[0].value
    at.checkbox(key="retrofit_P4").check().run()
    assert not at.exception
    assert "Steam gasification" in at.info[0].value


def test_app_live_mode():
    at = st_testing.AppTest.from_file(APP, default_timeout=120).run()
    at.radio(key="mode").set_value("Custom requirement (live)").run()
    assert not at.exception
    at.slider(key="t_proc").set_value(600).run()
    at.slider(key="co2").set_value(300.0).run()
    assert not at.exception
    assert at.info[0].value.startswith("Cheapest feasible chain")
