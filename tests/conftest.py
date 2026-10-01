import numpy as np
import pytest

from signalwalk.config import load_settings
from signalwalk.floorplan import floorplan_from_dict, load_floorplan
from signalwalk.simulator import SimWorld, simulate_survey


@pytest.fixture(scope="session")
def settings():
    return load_settings()


@pytest.fixture(scope="session")
def apartment():
    return load_floorplan("examples/floorplans/apartment.json")


@pytest.fixture(scope="session")
def office():
    return load_floorplan("examples/floorplans/office.json")


@pytest.fixture()
def corridor_plan():
    """10 x 6 m plan: router at the left, an interior wall at x=4 and a heavy wall at x=7."""
    return floorplan_from_dict({
        "name": "corridor", "width_m": 10, "height_m": 6, "router": {"x": 1, "y": 3},
        "walls": [{"x1": 4, "y1": 0, "x2": 4, "y2": 6, "kind": "interior"},
                  {"x1": 7, "y1": 0, "x2": 7, "y2": 6, "kind": "heavy"}]})


def survey_for(plan, seed=3, n=20):
    world = SimWorld(plan, seed=seed)
    return world, simulate_survey(world, n, 5, np.random.default_rng([seed, 5]))
