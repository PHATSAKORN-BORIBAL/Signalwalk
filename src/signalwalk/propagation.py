"""Multi-wall path-loss model, fitted to survey points.

    RSSI(x) = A - 10 * n * log10(max(d, 1 m)) - sum_k  w_k * (walls of kind k crossed)

* A   signal at 1 m from the router (dBm)
* n   path-loss exponent
* w_k loss per wall of kind k (dB)

The model is linear in (A, n, w_light, w_interior, w_heavy), so fitting is a
regularised linear regression: a MAP estimate with Gaussian priors centred on
sensible indoor defaults, then projected onto physical bounds (n in a range,
wall losses >= 0). Wall kinds that no measurement path crosses keep their prior.

This is an established family of models ("multi-wall" / COST-231 style). The
priors and bounds are my own choices (see docs/DESIGN_DECISIONS.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

from .config import ModelConfig
from .floorplan import WALL_KINDS, FloorPlan

PARAM_NAMES = ("a_dbm", "n", *(f"w_{k}" for k in WALL_KINDS))


@dataclass(frozen=True)
class PathLossModel:
    a_dbm: float
    n: float
    wall_db: tuple[float, ...]                 # one per WALL_KINDS
    observed_kinds: tuple[bool, ...] = (True,) * len(WALL_KINDS)  # kinds with evidence

    def theta(self) -> np.ndarray:
        return np.array([self.a_dbm, self.n, *self.wall_db])

    def predict(self, plan: FloorPlan, px: np.ndarray, py: np.ndarray,
                ap: Optional[tuple[float, float]] = None) -> np.ndarray:
        """Predicted dBm at points (px, py) for a router at ``ap`` (default: the plan's)."""
        ap = ap or plan.router
        px, py = np.asarray(px, float), np.asarray(py, float)
        return features(plan, ap, px, py) @ self.theta()

    def to_dict(self) -> dict:
        return {"a_dbm": round(self.a_dbm, 2), "n": round(self.n, 2),
                "wall_db": {k: round(v, 2) for k, v in zip(WALL_KINDS, self.wall_db)},
                "observed_kinds": [k for k, o in zip(WALL_KINDS, self.observed_kinds) if o]}


def features(plan: FloorPlan, ap: tuple[float, float], px: np.ndarray, py: np.ndarray) -> np.ndarray:
    """(N, 5) design matrix: [1, -10 log10 d, -walls_light, -walls_interior, -walls_heavy]."""
    d = np.maximum(np.hypot(px - ap[0], py - ap[1]), 1.0)
    cols = [np.ones_like(d), -10.0 * np.log10(d)]
    counts = plan.crossings(ap, px, py)
    cols.extend(-counts[:, k] for k in range(len(WALL_KINDS)))
    return np.column_stack(cols)


def prior_model(cfg: ModelConfig) -> PathLossModel:
    p = cfg.prior
    return PathLossModel(p.a_dbm, p.n, tuple(float(p.wall_db[k]) for k in WALL_KINDS),
                         (False,) * len(WALL_KINDS))


def _solve_bounded(xa: np.ndarray, ya: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """Least squares with box constraints by repeatedly fixing the worst violator."""
    p = xa.shape[1]
    fixed: dict[int, float] = {}
    theta = np.zeros(p)
    for _ in range(p + 1):
        free = [j for j in range(p) if j not in fixed]
        rhs = ya.copy()
        for j, v in fixed.items():
            rhs = rhs - xa[:, j] * v
        sol, *_ = np.linalg.lstsq(xa[:, free], rhs, rcond=None)
        theta = np.zeros(p)
        for j, v in fixed.items():
            theta[j] = v
        for idx, j in enumerate(free):
            theta[j] = sol[idx]
        viol = [(max(lower[j] - theta[j], theta[j] - upper[j]), j) for j in free
                if theta[j] < lower[j] or theta[j] > upper[j]]
        if not viol:
            break
        _, worst = max(viol)
        fixed[worst] = float(np.clip(theta[worst], lower[worst], upper[worst]))
    return np.clip(theta, lower, upper)


def fit_model(plan: FloorPlan, px: Sequence[float], py: Sequence[float], rssi: Sequence[float],
              cfg: ModelConfig, ap: Optional[tuple[float, float]] = None) -> PathLossModel:
    """MAP fit of the model. With no data, returns the prior."""
    px, py, y = (np.asarray(v, float) for v in (px, py, rssi))
    if y.size == 0:
        return prior_model(cfg)
    ap = ap or plan.router
    x = features(plan, ap, px, py)
    prior = prior_model(cfg).theta()
    prior_std = np.array([cfg.a_std, cfg.n_std] + [cfg.wall_std] * len(WALL_KINDS))
    sigma = cfg.noise_db
    xa = np.vstack([x / sigma, np.diag(1.0 / prior_std)])
    ya = np.concatenate([y / sigma, prior / prior_std])
    lower = np.array([-70.0, cfg.min_n] + [0.0] * len(WALL_KINDS))
    upper = np.array([-10.0, cfg.max_n] + [cfg.max_wall_db] * len(WALL_KINDS))
    theta = _solve_bounded(xa, ya, lower, upper)
    observed = tuple(bool(np.any(x[:, 2 + k] != 0)) for k in range(len(WALL_KINDS)))
    return PathLossModel(float(theta[0]), float(theta[1]), tuple(float(v) for v in theta[2:]), observed)
