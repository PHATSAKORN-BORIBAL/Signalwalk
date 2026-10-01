import numpy as np

from conftest import survey_for
from signalwalk.analysis import analyze
from signalwalk.deadzones import find_zones, label_components, normal_cdf, room_report
from signalwalk.estimator import fit_map
from signalwalk.placement import expected_coverage, next_survey_spots, suggest_extender, suggest_router_moves
from signalwalk.survey import Measurement


def test_normal_cdf_matches_known_values():
    z = np.array([-3.0, -1.0, 0.0, 1.0, 1.96, 3.0])
    assert np.allclose(normal_cdf(z), [0.00135, 0.15866, 0.5, 0.84134, 0.975, 0.99865], atol=2e-4)


def test_component_labelling_is_4_connected():
    mask = np.array([[1, 1, 0, 0], [0, 0, 0, 1], [1, 0, 0, 1], [1, 0, 1, 0]], dtype=bool)
    labels, n = label_components(mask)
    assert n == 4 and labels[0, 0] == labels[0, 1] and labels[1, 3] == labels[2, 3] and labels[3, 2] not in (0, labels[2, 3])


def test_zones_filter_small_areas_and_classify_severity(apartment, settings):
    xs, ys = apartment.cell_centers(0.25)
    mean = np.full((len(ys), len(xs)), -50.0)
    gx, gy = np.meshgrid(xs, ys)
    mean[(gx > 9.6) & (gy > 4.6)] = -88.0                 # big dead patch in the office
    mean[(gx < 1.0) & (gy < 1.0)] = -72.0                 # 1 m2 weak patch: right at the limit
    mean[5, 40] = -75.0                                   # single cell: too small
    std = np.full_like(mean, 2.0)
    zones = find_zones(apartment, xs, ys, mean, std, settings, [(11.0, 7.0)])
    assert zones[0].severity == "dead" and zones[0].rooms[0]["name"] == "Home office"
    assert zones[0].measured_inside == 1 and zones[0].certainty > 0.99
    assert all(z.area_m2 >= settings.zones.min_area_m2 for z in zones) and len(zones) <= 2


def test_room_report_grades(apartment, settings):
    xs, ys = apartment.cell_centers(0.25)
    mean = np.full((len(ys), len(xs)), -50.0)
    gx, gy = np.meshgrid(xs, ys)
    mean[gx >= 9.5] = -90.0
    rep = {r["room"]: r for r in room_report(apartment, xs, ys, mean, settings, [(1, 1)])}
    assert rep["Living room"]["grade"] == "good" and rep["Home office"]["grade"] == "dead"
    assert rep["Living room"]["measured_points"] == 1


def test_expected_coverage_bounds():
    w = np.ones((2, 2))
    assert expected_coverage(np.full((2, 2), -30.0), 3.0, w, -70) > 0.999
    assert expected_coverage(np.full((2, 2), -100.0), 3.0, w, -70) < 0.001
    assert abs(expected_coverage(np.full((2, 2), -70.0), 3.0, w, -70) - 0.5) < 1e-6


def test_router_advice_improves_coverage_and_spreads_picks(apartment, settings):
    _, meas = survey_for(apartment)
    fm = fit_map(apartment, meas, settings)
    out = suggest_router_moves(apartment, fm, settings, 3.5)
    sug = out["suggestions"]
    assert 1 <= len(sug) <= settings.placement.top_k and sug[0]["gain_pp"] > 5
    assert sug[0]["expected_coverage_pct"] >= sug[-1]["expected_coverage_pct"]
    for i in range(len(sug)):
        for j in range(i + 1, len(sug)):
            assert np.hypot(sug[i]["x"] - sug[j]["x"], sug[i]["y"] - sug[j]["y"]) >= settings.placement.min_separation_m


def test_extender_must_hear_the_router(apartment, settings):
    _, meas = survey_for(apartment)
    fm = fit_map(apartment, meas, settings)
    ext = suggest_extender(apartment, fm, settings, 3.5)["suggestion"]
    assert ext and ext["hears_router_dbm"] >= settings.placement.backhaul_min_dbm and ext["gain_pp"] > 0
    import dataclasses
    strict = dataclasses.replace(settings, placement=dataclasses.replace(settings.placement, backhaul_min_dbm=-20.0))
    assert suggest_extender(apartment, fm, strict, 3.5)["suggestion"] is None


def test_next_spots_avoid_walls_and_targets_uncertainty(apartment, settings):
    _, meas = survey_for(apartment, n=12)
    fm = fit_map(apartment, meas, settings)
    xs, ys = apartment.cell_centers(0.25)
    gx, gy = np.meshgrid(xs, ys)
    mean, std, _ = fm.predict(gx.ravel(), gy.ravel())
    spots = next_survey_spots(apartment, xs, ys, mean.reshape(gx.shape), std.reshape(gx.shape), settings)
    assert 1 <= len(spots) <= settings.placement.next_spots
    assert all(0.3 < s["p_weak"] < 0.7 or s["uncertainty_db"] > 1.5 for s in spots)


def test_analyze_output_shape_and_warnings(apartment, settings):
    empty = analyze(apartment, [], settings)
    assert empty["n_points"] == 0 and empty["suggestions"] is None and "No measurements yet" in empty["warnings"][0]
    few = analyze(apartment, [Measurement(1, 1, -45), Measurement(3, 2, -55), Measurement(6, 3, -60)], settings)
    assert few["suggestions"] is not None and any("Only 3" in w for w in few["warnings"])
    assert any("No measurements inside" in w for w in few["warnings"])
    g = few["grid"]
    assert len(g["mean"]) == g["ny"] and len(g["mean"][0]) == g["nx"] and len(g["std"]) == g["ny"]
    cov = few["coverage"]
    assert abs(cov["ok_pct"] + cov["weak_pct"] + cov["dead_pct"] - 100) < 0.5


def test_roaming_warning(apartment, settings):
    pts = [Measurement(1, 1, -45, ap_tag="aaaaaa"), Measurement(3, 2, -55, ap_tag="bbbbbb"), Measurement(6, 3, -60, ap_tag="aaaaaa")]
    assert any("different access points" in w for w in analyze(apartment, pts, settings)["warnings"])
