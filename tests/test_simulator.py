import numpy as np

from signalwalk.floorplan import distance_to_segments
from signalwalk.simulator import CEIL_DBM, FLOOR_DBM, SimWorld, plan_survey_points


def test_same_seed_same_world_different_seed_differs(apartment):
    a, b, c = SimWorld(apartment, 1), SimWorld(apartment, 1), SimWorld(apartment, 2)
    px, py = np.array([3.0, 8.0]), np.array([2.0, 6.0])
    assert np.array_equal(a.true_rssi(px, py), b.true_rssi(px, py)) and not np.array_equal(a.true_rssi(px, py), c.true_rssi(px, py))


def test_signal_falls_with_distance_and_walls(apartment):
    w = SimWorld(apartment, 4)
    near = w.true_rssi(np.array([1.5]), np.array([1.0]))[0]
    far_room = w.true_rssi(np.array([11.0]), np.array([7.0]))[0]
    assert near > far_room + 15
    g = w.grid_truth(0.5)
    assert g.min() >= FLOOR_DBM and g.max() <= CEIL_DBM and g.shape == (16, 24)


def test_moving_the_router_changes_the_field(apartment):
    w = SimWorld(apartment, 4)
    a, b = w.grid_truth(0.5), w.grid_truth(0.5, ap=(9.0, 6.0))
    assert a[2, 2] > b[2, 2] and b[12, 18] > a[12, 18]


def test_measurements_are_noisy_but_centred_on_truth(apartment):
    w = SimWorld(apartment, 4)
    truth = w.true_rssi(np.array([3.0]), np.array([2.0]))[0]
    vals = [w.measure(3.0, 2.0, 5, np.random.default_rng(i)).rssi_dbm for i in range(200)]
    assert abs(np.mean(vals) - truth) < 1.0 and 0.5 < np.std(vals) < 2.5
    m = w.measure(3.0, 2.0, 5, np.random.default_rng(0))
    assert m.source == "simulated" and m.n_readings == 5
    assert m.rssi_dbm == round(m.rssi_dbm)          # median of 5 whole-dBm readings


def test_survey_points_cover_every_room_and_avoid_walls(apartment, office):
    for plan in (apartment, office):
        pts = plan_survey_points(plan, 20, np.random.default_rng(1))
        assert len(pts) == 20
        assert all(any(r.contains(x, y) for x, y in pts) for r in plan.rooms)
        arr = np.array(pts)
        assert (distance_to_segments(arr[:, 0], arr[:, 1], plan.wall_array()) >= 0.2).mean() > 0.9


def test_few_points_still_works(apartment):
    assert len(plan_survey_points(apartment, 3, np.random.default_rng(1))) == 3
