"""Router placement advice and 'measure here next' suggestions.

Router moves and extenders are evaluated with the fitted PATH-LOSS MODEL ONLY: a
moved router changes the wall-crossing geometry, so residuals measured for the old
position do not transfer reliably. Model uncertainty enters as a Gaussian error of
size ``model_rmse_db`` (from leave-one-out cross-validation), so every candidate is
scored by *expected* coverage, sum(weight * P(signal >= weak)) / sum(weight).

Assumptions (documented in docs/DESIGN_DECISIONS.md): the new router radiates like
the old one (same A), Wi-Fi channel/interference is ignored, an extender radiates
like the router, and only signal strength (not throughput) is considered.
"""

from __future__ import annotations

import numpy as np

from .config import Settings
from .deadzones import normal_cdf
from .estimator import FittedMap
from .floorplan import FloorPlan, candidate_positions, distance_to_segments


def expected_coverage(mean: np.ndarray, sigma: float | np.ndarray, weights: np.ndarray,
                      weak_dbm: float) -> float:
    p = normal_cdf((mean - weak_dbm) / sigma)
    return float((p * weights).sum() / weights.sum())


def _spread(points: list[tuple[float, float, float]], k: int, min_sep: float
            ) -> list[tuple[float, float, float]]:
    """Greedy pick of best-scoring points that are at least ``min_sep`` apart."""
    chosen: list[tuple[float, float, float]] = []
    for x, y, score in sorted(points, key=lambda p: -p[2]):
        if all(np.hypot(x - cx, y - cy) >= min_sep for cx, cy, _ in chosen):
            chosen.append((x, y, score))
        if len(chosen) == k:
            break
    return chosen


def _placement_grid(plan: FloorPlan, settings: Settings):
    xs, ys = plan.cell_centers(settings.grid.placement_cell_m)
    gx, gy = np.meshgrid(xs, ys)
    return gx.ravel(), gy.ravel(), plan.cell_weights(xs, ys).ravel()


def suggest_router_moves(plan: FloorPlan, fitted: FittedMap, settings: Settings,
                         model_rmse_db: float) -> dict:
    thr = settings.thresholds
    px, py, weights = _placement_grid(plan, settings)
    model = fitted.model
    current = expected_coverage(model.predict(plan, px, py), model_rmse_db, weights, thr.weak_dbm)
    scored = []
    for cx, cy in candidate_positions(plan, settings.grid.placement_cell_m, settings.placement.wall_clearance_m):
        cov = expected_coverage(model.predict(plan, px, py, ap=(cx, cy)), model_rmse_db, weights, thr.weak_dbm)
        scored.append((cx, cy, cov))
    picks = _spread(scored, settings.placement.top_k, settings.placement.min_separation_m)
    return {"baseline_pct": round(100 * current, 1), "model_rmse_db": round(model_rmse_db, 1),
            "suggestions": [{"kind": "move_router", "x": round(x, 2), "y": round(y, 2),
                             "room": plan.room_name_at(x, y),
                             "expected_coverage_pct": round(100 * c, 1),
                             "gain_pp": round(100 * (c - current), 1)} for x, y, c in picks]}


def suggest_extender(plan: FloorPlan, fitted: FittedMap, settings: Settings,
                     model_rmse_db: float) -> dict:
    """Where a second access point / extender would help most while still hearing the router."""
    thr, pl = settings.thresholds, settings.placement
    px, py, weights = _placement_grid(plan, settings)
    r_mean, r_std, _ = fitted.predict(px, py)                 # router's contribution: the real map
    p_router = normal_cdf((r_mean - thr.weak_dbm) / r_std)
    base = float((p_router * weights).sum() / weights.sum())
    scored = []
    for cx, cy in candidate_positions(plan, settings.grid.placement_cell_m, pl.wall_clearance_m):
        hear = fitted.predict(np.array([cx]), np.array([cy]))[0][0]
        if hear < pl.backhaul_min_dbm:
            continue                                          # extender could not hear the router well
        e_mean = fitted.model.predict(plan, px, py, ap=(cx, cy))
        p_ext = normal_cdf((e_mean - thr.weak_dbm) / model_rmse_db)
        cov = float(((1.0 - (1.0 - p_router) * (1.0 - p_ext)) * weights).sum() / weights.sum())
        scored.append((cx, cy, cov))
    picks = _spread(scored, 1, pl.min_separation_m)
    best = None
    if picks:
        x, y, c = picks[0]
        hear = float(fitted.predict(np.array([x]), np.array([y]))[0][0])
        best = {"kind": "add_extender", "x": round(x, 2), "y": round(y, 2), "room": plan.room_name_at(x, y),
                "expected_coverage_pct": round(100 * c, 1), "gain_pp": round(100 * (c - base), 1),
                "hears_router_dbm": round(hear, 1)}
    return {"baseline_pct": round(100 * base, 1), "backhaul_min_dbm": pl.backhaul_min_dbm, "suggestion": best}


def next_survey_spots(plan: FloorPlan, xs: np.ndarray, ys: np.ndarray, mean: np.ndarray, std: np.ndarray,
                      settings: Settings) -> list[dict]:
    """Where one more measurement would resolve the most doubt about weak vs OK.

    Score = min(P, 1-P) where P = P(signal < weak): highest when the map cannot tell.
    """
    thr, pl = settings.thresholds, settings.placement
    p = normal_cdf((thr.weak_dbm - mean) / std)
    score = np.minimum(p, 1.0 - p) * std
    gx, gy = np.meshgrid(xs, ys)
    clear = distance_to_segments(gx.ravel(), gy.ravel(), plan.wall_array()) >= pl.wall_clearance_m + 0.1
    pts = [(float(x), float(y), float(s)) for x, y, s, ok in
           zip(gx.ravel(), gy.ravel(), score.ravel(), clear) if ok]
    picks = _spread(pts, pl.next_spots, pl.next_spot_separation_m)
    out = []
    for x, y, s in picks:
        if s < 0.3:
            continue                                    # the map is already sure everywhere else
        j = int(np.argmin(np.abs(ys - y))); i = int(np.argmin(np.abs(xs - x)))
        out.append({"x": round(x, 2), "y": round(y, 2), "room": plan.room_name_at(x, y),
                    "uncertainty_db": round(float(std[j, i]), 1), "p_weak": round(float(p[j, i]), 2)})
    return out
