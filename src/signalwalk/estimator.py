"""Hybrid coverage estimator: path-loss model + Gaussian-process residual correction.

1. Fit the multi-wall model to the survey points (physics: extrapolates sensibly).
2. Model what is left over (furniture, doors, reflections) as a smooth random
   field with a Matern-3/2 Gaussian process (data: fixes the map near measurements).
3. The GP also yields a standard deviation everywhere, which drives the confidence
   layer and the "measure here next" suggestions.

Cross-validation refits everything with one point left out at a time, so the
reported errors include the model fit, not just the GP step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from .config import Settings
from .floorplan import FloorPlan
from .propagation import PathLossModel, fit_model
from .survey import Measurement

SQRT3 = math.sqrt(3.0)


def matern32(dist: np.ndarray, length_m: float, sigma_f: float) -> np.ndarray:
    a = SQRT3 * dist / length_m
    return sigma_f ** 2 * (1.0 + a) * np.exp(-a)


def _pairwise(ax: np.ndarray, ay: np.ndarray, bx: np.ndarray, by: np.ndarray) -> np.ndarray:
    return np.hypot(ax[:, None] - bx[None, :], ay[:, None] - by[None, :])


def idw(px, py, values, qx, qy, power: float = 2.0) -> np.ndarray:
    """Inverse-distance-weighted interpolation (plain baseline, no physics)."""
    px, py, values, qx, qy = (np.asarray(v, float) for v in (px, py, values, qx, qy))
    d = np.maximum(_pairwise(qx, qy, px, py), 1e-3)
    w = 1.0 / d ** power
    return (w * values[None, :]).sum(axis=1) / w.sum(axis=1)


@dataclass
class FittedMap:
    plan: FloorPlan
    model: PathLossModel
    settings: Settings
    px: np.ndarray
    py: np.ndarray
    residual: np.ndarray
    _chol_inv_k: Optional[np.ndarray] = None    # (K + noise I)^-1
    _alpha: Optional[np.ndarray] = None

    def predict(self, qx: np.ndarray, qy: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (mean, std, model_only_mean) at query points, all dBm."""
        qx, qy = np.asarray(qx, float), np.asarray(qy, float)
        base = self.model.predict(self.plan, qx, qy)
        gp = self.settings.gp
        if self.px.size == 0:
            return base, np.full_like(base, gp.sigma_f_db), base
        ks = matern32(_pairwise(qx, qy, self.px, self.py), gp.length_m, gp.sigma_f_db)
        mean = base + ks @ self._alpha
        var = gp.sigma_f_db ** 2 - np.einsum("ij,jk,ik->i", ks, self._chol_inv_k, ks)
        return mean, np.sqrt(np.maximum(var, 0.25 ** 2)), base


def fit_map(plan: FloorPlan, measurements: Sequence[Measurement], settings: Settings) -> FittedMap:
    px = np.array([m.x for m in measurements], float)
    py = np.array([m.y for m in measurements], float)
    y = np.array([m.rssi_dbm for m in measurements], float)
    model = fit_model(plan, px, py, y, settings.model)
    if px.size == 0:
        return FittedMap(plan, model, settings, px, py, y)
    residual = y - model.predict(plan, px, py)
    gp = settings.gp
    k = matern32(_pairwise(px, py, px, py), gp.length_m, gp.sigma_f_db) + gp.sigma_n_db ** 2 * np.eye(px.size)
    k_inv = np.linalg.inv(k)
    return FittedMap(plan, model, settings, px, py, residual, k_inv, k_inv @ residual)


def loo_cross_validation(plan: FloorPlan, measurements: Sequence[Measurement],
                         settings: Settings, min_points: int = 5) -> Optional[dict]:
    """Leave-one-out RMSE (dB) for the hybrid map, the model alone, and plain IDW."""
    n = len(measurements)
    if n < min_points:
        return None
    err_h, err_m, err_i = [], [], []
    for i in range(n):
        rest = [m for j, m in enumerate(measurements) if j != i]
        held = measurements[i]
        fitted = fit_map(plan, rest, settings)
        mean, _, base = fitted.predict(np.array([held.x]), np.array([held.y]))
        err_h.append(mean[0] - held.rssi_dbm)
        err_m.append(base[0] - held.rssi_dbm)
        near = idw([m.x for m in rest], [m.y for m in rest], [m.rssi_dbm for m in rest],
                   np.array([held.x]), np.array([held.y]))
        err_i.append(near[0] - held.rssi_dbm)
    rmse = lambda e: float(np.sqrt(np.mean(np.square(e))))
    return {"n": n, "rmse_hybrid": round(rmse(err_h), 2), "rmse_model": round(rmse(err_m), 2),
            "rmse_idw": round(rmse(err_i), 2)}
