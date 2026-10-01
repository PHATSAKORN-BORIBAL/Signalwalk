import copy
import json

import numpy as np
import pytest

from signalwalk.floorplan import (FloorPlanError, candidate_positions, crossing_matrix, floorplan_from_dict,
                                  load_floorplan)

BASE = {"name": "t", "width_m": 10, "height_m": 6, "router": {"x": 1, "y": 3}, "walls": [], "rooms": []}


def test_crossing_matrix_counts_only_real_crossings():
    walls = np.array([[4.0, 0, 4.0, 6.0], [7.0, 0, 7.0, 2.0]])
    px, py = np.array([2.0, 5.0, 8.0, 8.0]), np.array([3.0, 3.0, 3.0, 1.0])
    m = crossing_matrix((1.0, 3.0), px, py, walls)
    assert m.tolist() == [[False, False], [True, False], [True, False], [True, True]]


def test_no_walls_gives_empty_matrix():
    assert crossing_matrix((0, 0), np.array([1.0]), np.array([1.0]), np.zeros((0, 4))).shape == (1, 0)


def test_crossings_are_grouped_by_kind(corridor_plan):
    counts = corridor_plan.crossings((1, 3), np.array([2.0, 5.0, 9.0]), np.array([3.0, 3.0, 3.0]))
    assert counts.tolist() == [[0, 0, 0], [0, 1, 0], [0, 1, 1]]     # light, interior, heavy


def test_doorway_gap_lets_the_line_through(apartment):
    # Living room -> Bedroom 1 through the 1.5..2.4 m doorway vs straight through the wall.
    through_door = apartment.crossings((2.0, 3.0), np.array([2.0]), np.array([6.0]))[0]
    through_wall = apartment.crossings((0.7, 3.0), np.array([0.7]), np.array([6.0]))[0]
    assert through_door.sum() == 0 and through_wall.sum() == 1


def test_room_lookup_and_weights(apartment):
    assert apartment.room_name_at(1, 1) == "Living room"
    assert apartment.room_name_at(11, 7) == "Home office"
    xs, ys = apartment.cell_centers(0.5)
    w = apartment.cell_weights(xs, ys)
    assert w.shape == (len(ys), len(xs)) and w.max() == 1.5 and w.min() == 0.6


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d.update(width_m=0), "between 1 and 200"),
    (lambda d: d.update(walls=[{"x1": 0, "y1": 0, "x2": 99, "y2": 0}]), "outside the plan"),
    (lambda d: d.update(walls=[{"x1": 0, "y1": 0, "x2": 5, "y2": 0, "kind": "concrete"}]), "kind must be"),
    (lambda d: d.update(walls=[{"x1": 1, "y1": 1, "x2": 1, "y2": 1}]), "zero length"),
    (lambda d: d.pop("router"), "'router'"),
    (lambda d: d.update(router={"x": 50, "y": 1}), "outside the plan"),
    (lambda d: d.update(rooms=[{"name": "r", "x": 8, "y": 0, "w": 5, "h": 2}]), "extends outside"),
    (lambda d: d.update(walls=[{"x1": 1, "y1": 0, "x2": 1, "y2": 6}]), "sits on a wall"),
    (lambda d: d.update(width_m="wide"), "must be a number"),
])
def test_invalid_floorplans_are_rejected(mutate, message):
    data = copy.deepcopy(BASE)
    mutate(data)
    with pytest.raises(FloorPlanError, match=message):
        floorplan_from_dict(data)


def test_load_errors(tmp_path):
    with pytest.raises(FloorPlanError, match="not found"):
        load_floorplan(tmp_path / "none.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(FloorPlanError, match="not valid JSON"):
        load_floorplan(bad)


def test_candidates_use_given_outlets_and_respect_wall_clearance(apartment, corridor_plan):
    outlets = candidate_positions(apartment, 0.5, 0.3)
    assert set(outlets) <= set(apartment.router_candidates) and len(outlets) >= 6
    grid = candidate_positions(corridor_plan, 0.5, 0.3)
    assert grid and all(abs(x - 4) >= 0.3 and abs(x - 7) >= 0.3 for x, _ in grid)


def test_shipped_floorplans_are_valid(apartment, office):
    assert len(apartment.walls) > 10 and len(office.rooms) == 8
    assert json.loads(json.dumps(apartment.to_dict()))["router"] == {"x": 1.0, "y": 1.0}
