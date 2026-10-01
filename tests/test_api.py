import dataclasses

import pytest
from fastapi.testclient import TestClient

from signalwalk.api import create_app
from signalwalk.collectors import Reading, SignalReadError
from signalwalk.service import Session


class FakeReader:
    name = "fake"

    def __init__(self, dbm=-60.0, fail=False):
        self.dbm, self.fail = dbm, fail

    def read(self):
        if self.fail:
            raise SignalReadError("adapter is off")
        return Reading(self.dbm, "abc123")


def client_for(settings, plan, mode="simulate", reader=None):
    fast = dataclasses.replace(settings, survey=dataclasses.replace(settings.survey, reading_interval_s=0.0))
    session = Session(fast, plan, mode, reader=reader)
    return TestClient(create_app(fast, plan, mode, session)), session


def test_health_state_and_security_headers(settings, apartment):
    c, _ = client_for(settings, apartment)
    assert c.get("/api/health").json() == {"status": "ok", "version": "0.1.0", "mode": "simulate"}
    st = c.get("/api/state").json()
    assert st["mode"] == "simulate" and st["floorplan"]["router"] == {"x": 1.0, "y": 1.0} and st["measurements"] == []
    r = c.get("/")
    assert r.status_code == 200 and "SignalWalk" in r.text
    assert "script-src 'self'" in r.headers["content-security-policy"] and r.headers["x-content-type-options"] == "nosniff"
    assert c.get("/static/app.js").status_code == 200 and c.get("/static/style.css").status_code == 200


def test_measure_analysis_flow_in_simulation(settings, apartment):
    c, _ = client_for(settings, apartment)
    assert c.get("/api/analysis").json()["suggestions"] is None
    for x, y in [(1.5, 1.5), (5, 2), (9, 2), (2, 6), (7.5, 6), (10.5, 6)]:
        r = c.post("/api/measure", json={"x": x, "y": y})
        assert r.status_code == 200 and r.json()["measurement"]["source"] == "simulated"
    a = c.get("/api/analysis").json()
    assert a["n_points"] == 6 and a["suggestions"]["router"]["suggestions"] and a["zones"] is not None
    assert c.get("/api/state").json()["measurements"][0]["x"] == 1.5


def test_measure_validation(settings, apartment):
    c, _ = client_for(settings, apartment)
    assert c.post("/api/measure", json={"x": 50, "y": 1}).status_code == 422       # outside plan (service)
    assert c.post("/api/measure", json={"x": -1, "y": 1}).status_code == 422       # pydantic bound
    assert c.post("/api/measure", json={"x": "a", "y": 1}).status_code == 422
    assert c.post("/api/measure", json={"x": 1}).status_code == 422


def test_delete_reset_and_auto_survey(settings, apartment):
    c, s = client_for(settings, apartment)
    assert c.post("/api/sim/auto-survey", json={"count": 8}).json() == {"added": 8, "count": 8}
    assert c.delete("/api/measurements/0").json()["count"] == 7
    assert c.delete("/api/measurements/99").status_code == 404
    assert c.post("/api/sim/auto-survey", json={"count": 0}).status_code == 422
    assert c.post("/api/sim/auto-survey", json={"count": 500}).status_code == 422
    assert c.post("/api/reset").json() == {"count": 0} and len(s.survey) == 0


def test_analysis_is_cached_until_the_survey_changes(settings, apartment):
    c, s = client_for(settings, apartment)
    c.post("/api/sim/auto-survey", json={"count": 6})
    first = s.analysis()
    assert s.analysis() is first
    c.post("/api/measure", json={"x": 3, "y": 3})
    assert s.analysis() is not first


def test_exports(settings, apartment):
    c, _ = client_for(settings, apartment)
    c.post("/api/sim/auto-survey", json={"count": 6})
    csv = c.get("/api/export/survey.csv")
    assert "attachment" in csv.headers["content-disposition"] and csv.text.startswith("x_m,y_m,rssi_dbm")
    assert len(csv.text.strip().splitlines()) == 7
    assert c.get("/api/export/survey.json").json()["schema"] == "signalwalk.survey/1"
    svg = c.get("/api/export/heatmap.svg")
    assert svg.headers["content-type"].startswith("image/svg+xml") and svg.text.startswith("<svg")


def test_real_mode_uses_the_reader_and_reports_failures(settings, apartment):
    c, _ = client_for(settings, apartment, "real", FakeReader(-63.0))
    assert c.get("/api/state").json()["reader"] == "fake"
    r = c.post("/api/measure", json={"x": 2, "y": 2}).json()["measurement"]
    assert r["rssi_dbm"] == -63.0 and r["source"] == "real" and r["n_readings"] == settings.survey.readings_per_spot
    assert c.post("/api/sim/auto-survey", json={"count": 5}).status_code == 409     # simulation only
    bad, _ = client_for(settings, apartment, "real", FakeReader(fail=True))
    resp = bad.post("/api/measure", json={"x": 2, "y": 2})
    assert resp.status_code == 503 and "adapter is off" in resp.json()["detail"]
    assert len(bad.get("/api/state").json()["measurements"]) == 0


def test_busy_session_returns_409(settings, apartment):
    c, s = client_for(settings, apartment)
    assert s._measuring.acquire(blocking=False)
    try:
        assert c.post("/api/measure", json={"x": 2, "y": 2}).status_code == 409
    finally:
        s._measuring.release()
    assert c.post("/api/measure", json={"x": 2, "y": 2}).status_code == 200


def test_invalid_mode_rejected(settings, apartment):
    with pytest.raises(ValueError):
        Session(settings, apartment, "banana")
