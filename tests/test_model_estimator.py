import numpy as np
import pytest

from conftest import survey_for
from signalwalk.estimator import fit_map, idw, loo_cross_validation
from signalwalk.propagation import features, fit_model, prior_model

TRUE = np.array([-38.0, 3.1, 0.0, 5.0, 11.0])


def synthetic(plan, n=60, noise=1.5, seed=0):
    rng = np.random.default_rng(seed)
    px, py = rng.uniform(0.3, 9.7, n), rng.uniform(0.3, 5.7, n)
    y = features(plan, plan.router, px, py) @ TRUE + rng.normal(0, noise, n)
    return px, py, y


def test_fit_recovers_known_parameters(corridor_plan, settings):
    px, py, y = synthetic(corridor_plan)
    m = fit_model(corridor_plan, px, py, y, settings.model)
    assert abs(m.a_dbm - -38.0) < 3 and abs(m.n - 3.1) < 0.35
    assert abs(m.wall_db[1] - 5.0) < 2.0 and abs(m.wall_db[2] - 11.0) < 2.5
    assert m.observed_kinds == (False, True, True)          # no light walls in this plan


def test_no_data_returns_prior_and_unseen_kinds_keep_prior(corridor_plan, settings):
    m0 = fit_model(corridor_plan, [], [], [], settings.model)
    assert m0.theta().tolist() == prior_model(settings.model).theta().tolist()
    px, py, y = synthetic(corridor_plan)
    assert fit_model(corridor_plan, px, py, y, settings.model).wall_db[0] == pytest.approx(settings.model.prior.wall_db["light"], abs=0.01)


def test_bounds_are_enforced(corridor_plan, settings):
    rng = np.random.default_rng(1)
    px, py = rng.uniform(0.3, 9.7, 30), rng.uniform(0.3, 5.7, 30)
    # signal that INCREASES behind walls: the fit must not return negative wall loss
    y = -50 + 4.0 * (px > 4) + rng.normal(0, 1, 30)
    m = fit_model(corridor_plan, px, py, y, settings.model)
    assert min(m.wall_db) >= 0 and settings.model.min_n <= m.n <= settings.model.max_n


def test_gp_interpolates_measurements_and_uncertainty_grows_away(apartment, settings):
    _, meas = survey_for(apartment)
    fm = fit_map(apartment, meas, settings)
    px, py = np.array([m.x for m in meas]), np.array([m.y for m in meas])
    mean, std, _ = fm.predict(px, py)
    assert np.sqrt(np.mean((mean - np.array([m.rssi_dbm for m in meas])) ** 2)) < 3.0
    far_mean, far_std, _ = fm.predict(np.array([0.05]), np.array([0.05]))
    assert std.mean() < far_std[0] or far_std[0] > 1.5
    empty = fit_map(apartment, [], settings)
    assert empty.predict(np.array([3.0]), np.array([3.0]))[1][0] == settings.gp.sigma_f_db


def test_loo_cross_validation_beats_plain_interpolation(apartment, settings):
    _, meas = survey_for(apartment, n=24)
    cv = loo_cross_validation(apartment, meas, settings)
    assert cv["n"] == 24 and cv["rmse_hybrid"] < cv["rmse_idw"] and cv["rmse_model"] < cv["rmse_idw"]
    assert loo_cross_validation(apartment, meas[:3], settings) is None


def test_idw_reproduces_a_point_and_averages_far_away():
    v = idw([0, 10], [0, 0], [-40, -80], np.array([0.0, 5.0]), np.array([0.0, 0.0]))
    assert abs(v[0] - -40) < 0.01 and abs(v[1] - -60) < 0.01
