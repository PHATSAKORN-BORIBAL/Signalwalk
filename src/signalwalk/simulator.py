"""A simulated house to survey. SIMULATION ONLY.

The ground truth deliberately uses a DIFFERENT propagation model from the
estimator in ``propagation.py`` so that the evaluation is not simply the model
recovering its own equations:

* two-slope path loss (gentle up to a breakpoint, steeper beyond it)
* every wall gets its own random loss (not one value per kind)
* hidden obstacles (furniture, appliances) that are NOT in the floor plan
* spatially correlated shadowing (random Fourier features)
* per-reading fast fading noise, quantised to whole dBm

It is still my own hand-written model, not real measurements.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from .floorplan import FloorPlan, crossing_matrix, distance_to_segments
from .survey import Measurement

BASE_WALL_DB = {"light": 3.0, "interior": 7.0, "heavy": 13.0}
FLOOR_DBM, CEIL_DBM = -92.0, -20.0
FADING_SD_DB = 2.5
SHADOW_SD_DB = 2.5
SHADOW_LENGTH_M = 2.0


class SimWorld:
    def __init__(self, plan: FloorPlan, seed: int = 0, n_hidden: int = 3):
        self.plan, self.seed = plan, seed
        rng = np.random.default_rng([seed, 101])
        self.a_dbm = rng.uniform(-45.0, -34.0)
        self.n1 = rng.uniform(1.8, 2.3)
        self.n2 = rng.uniform(3.0, 4.2)
        self.breakpoint_m = rng.uniform(4.0, 7.0)
        wall_loss = np.array([BASE_WALL_DB[w.kind] * rng.uniform(0.6, 1.6) for w in plan.walls])
        hidden = []
        for _ in range(n_hidden):
            cx, cy = rng.uniform(1.0, plan.width_m - 1.0), rng.uniform(1.0, plan.height_m - 1.0)
            ang, half = rng.uniform(0, math.pi), rng.uniform(0.5, 1.0)
            hidden.append([cx - half * math.cos(ang), cy - half * math.sin(ang),
                           cx + half * math.cos(ang), cy + half * math.sin(ang)])
        self.hidden = np.array(hidden, dtype=float).reshape(-1, 4)
        hidden_loss = rng.uniform(3.0, 8.0, len(hidden))
        self._walls = np.vstack([plan.wall_array(), self.hidden])
        self._loss = np.concatenate([wall_loss, hidden_loss])

    def _shadow(self, px: np.ndarray, py: np.ndarray, ap: tuple[float, float]) -> np.ndarray:
        """Correlated shadowing; a different draw for each router position."""
        rng = np.random.default_rng([self.seed, int(round(ap[0] * 100)), int(round(ap[1] * 100)), 17])
        k = 24
        omega = rng.normal(0.0, 1.0 / SHADOW_LENGTH_M, (k, 2))
        phase = rng.uniform(0.0, 2 * math.pi, k)
        arg = px[:, None] * omega[None, :, 0] + py[:, None] * omega[None, :, 1] + phase[None, :]
        return SHADOW_SD_DB * math.sqrt(2.0 / k) * np.cos(arg).sum(axis=1)

    def true_rssi(self, px: np.ndarray, py: np.ndarray,
                  ap: Optional[tuple[float, float]] = None) -> np.ndarray:
        """Noise-free 'true' signal (dBm) at points, for a router at ``ap``."""
        ap = ap or self.plan.router
        px, py = np.asarray(px, float), np.asarray(py, float)
        d = np.maximum(np.hypot(px - ap[0], py - ap[1]), 1.0)
        near = 10.0 * self.n1 * np.log10(d)
        far = 10.0 * self.n1 * math.log10(self.breakpoint_m) + 10.0 * self.n2 * np.log10(d / self.breakpoint_m)
        path = np.where(d <= self.breakpoint_m, near, far)
        walls = crossing_matrix(ap, px, py, self._walls).astype(float) @ self._loss
        return np.clip(self.a_dbm - path - walls + self._shadow(px, py, ap), FLOOR_DBM, CEIL_DBM)

    def grid_truth(self, cell_m: float, ap: Optional[tuple[float, float]] = None) -> np.ndarray:
        xs, ys = self.plan.cell_centers(cell_m)
        gx, gy = np.meshgrid(xs, ys)
        return self.true_rssi(gx.ravel(), gy.ravel(), ap).reshape(gx.shape)

    def measure(self, x: float, y: float, n_readings: int, rng: np.random.Generator) -> Measurement:
        """What a laptop standing at (x, y) would report: median of noisy integer readings."""
        true = float(self.true_rssi(np.array([x]), np.array([y]))[0])
        readings = np.clip(np.round(true + rng.normal(0.0, FADING_SD_DB, n_readings)), FLOOR_DBM, CEIL_DBM)
        return Measurement(float(x), float(y), float(np.median(readings)), int(n_readings),
                           float(readings.max() - readings.min()), None, "simulated", "sim000")


def plan_survey_points(plan: FloorPlan, n: int, rng: np.random.Generator,
                       min_sep_m: float = 1.2, margin_m: float = 0.35) -> list[tuple[float, float]]:
    """Where a sensible person would stand: at least one spot per room, the rest
    spread in proportion to room area, away from walls and from each other."""
    regions = [(r.x, r.y, r.w, r.h) for r in plan.rooms] or [(0.0, 0.0, plan.width_m, plan.height_m)]
    areas = np.array([w * h for _, _, w, h in regions])
    quota = np.zeros(len(regions), dtype=int)
    quota[: min(n, len(regions))] = 1
    for idx in rng.choice(len(regions), size=max(0, n - len(regions)), p=areas / areas.sum()):
        quota[idx] += 1
    walls = plan.wall_array()
    points: list[tuple[float, float]] = []
    for (x, y, w, h), q in zip(regions, quota):
        for _ in range(int(q)):
            for attempt in range(300):
                sep = min_sep_m if attempt < 200 else 0.0
                px = rng.uniform(x + min(margin_m, w / 2), x + w - min(margin_m, w / 2))
                py = rng.uniform(y + min(margin_m, h / 2), y + h - min(margin_m, h / 2))
                if distance_to_segments(np.array([px]), np.array([py]), walls)[0] < 0.25 and attempt < 250:
                    continue
                if all(math.hypot(px - qx, py - qy) >= sep for qx, qy in points):
                    points.append((float(px), float(py)))
                    break
    return points


def simulate_survey(world: SimWorld, n: int, readings: int, rng: np.random.Generator) -> list[Measurement]:
    return [world.measure(x, y, readings, rng) for x, y in plan_survey_points(world.plan, n, rng)]
