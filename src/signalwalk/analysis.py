"""Turn a floor plan plus survey points into the full JSON-ready analysis."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .config import Settings
from .deadzones import find_zones, room_report
from .estimator import fit_map, loo_cross_validation
from .floorplan import WALL_KINDS, FloorPlan
from .placement import next_survey_spots, suggest_extender, suggest_router_moves
from .survey import Measurement


def analyze(plan: FloorPlan, measurements: Sequence[Measurement], settings: Settings,
            with_suggestions: bool = True) -> dict:
    thr = settings.thresholds
    xs, ys = plan.cell_centers(settings.grid.cell_m)
    gx, gy = np.meshgrid(xs, ys)
    fitted = fit_map(plan, measurements, settings)
    mean, std, _ = fitted.predict(gx.ravel(), gy.ravel())
    mean, std = mean.reshape(gx.shape), std.reshape(gx.shape)

    pts = [(m.x, m.y) for m in measurements]
    weights = plan.cell_weights(xs, ys)
    share = lambda mask: round(float(100 * (weights * mask).sum() / weights.sum()), 1)
    coverage = {"strong_pct": share(mean >= thr.strong_dbm), "ok_pct": share(mean >= thr.weak_dbm),
                "weak_pct": share((mean < thr.weak_dbm) & (mean >= thr.dead_dbm)),
                "dead_pct": share(mean < thr.dead_dbm)}

    n = len(measurements)
    cv = loo_cross_validation(plan, measurements, settings) if n else None
    warnings = _warnings(plan, measurements, settings, fitted.model, gx.ravel(), gy.ravel())

    result = {
        "floorplan": plan.name, "n_points": n,
        "grid": {"cell_m": settings.grid.cell_m, "nx": len(xs), "ny": len(ys),
                 "mean": np.round(mean, 1).tolist(), "std": np.round(std, 1).tolist()},
        "model": fitted.model.to_dict(), "cv": cv, "coverage": coverage,
        "zones": [z.to_dict() for z in find_zones(plan, xs, ys, mean, std, settings, pts)],
        "rooms": room_report(plan, xs, ys, mean, settings, pts),
        "suggestions": None, "warnings": warnings,
        "thresholds": {"strong_dbm": thr.strong_dbm, "weak_dbm": thr.weak_dbm, "dead_dbm": thr.dead_dbm},
    }
    if with_suggestions and n >= 3:
        rmse = cv["rmse_model"] if cv else settings.placement.default_model_rmse_db
        rmse = max(rmse, 2.0)                        # never claim better than measurement noise
        result["suggestions"] = {
            "router": suggest_router_moves(plan, fitted, settings, rmse),
            "extender": suggest_extender(plan, fitted, settings, rmse),
            "next_spots": next_survey_spots(plan, xs, ys, mean, std, settings),
        }
    return result


def _warnings(plan: FloorPlan, measurements: Sequence[Measurement], settings: Settings, model,
              gx: np.ndarray, gy: np.ndarray) -> list[str]:
    out: list[str] = []
    n = len(measurements)
    if n == 0:
        return ["No measurements yet: the map shows only the generic prior. Click on the plan to measure."]
    if n < settings.survey.min_points_warn:
        out.append(f"Only {n} measurement(s). Maps built from fewer than {settings.survey.min_points_warn} "
                   "points are rough; treat suggestions as hints.")
    empty = [r.name for r in plan.rooms if not any(r.contains(m.x, m.y) for m in measurements)]
    if empty:
        out.append("No measurements inside: " + ", ".join(empty) + ".")
    tags = {m.ap_tag for m in measurements if m.ap_tag}
    if len(tags) > 1:
        out.append(f"Your device connected to {len(tags)} different access points during the survey. "
                   "The model assumes a single router; results may be mixed up.")
    relied_on = plan.crossings(plan.router, gx, gy).any(axis=0)      # kinds the map extrapolates through
    unseen = [k for k, seen, used in zip(WALL_KINDS, model.observed_kinds, relied_on) if used and not seen]
    if unseen:
        out.append("No measurement path crossed any '" + "', '".join(unseen) +
                   "' wall, so its loss is a default assumption.")
    return out
