"""Synthetic evaluation against simulated ground truth. SIMULATION ONLY.

The simulator (simulator.py) uses a different propagation model from the estimator,
so this is more than the model re-fitting its own equations, but both are still
written by the same person and nothing here involves a real building.

For each simulated world and survey size it reports:
* map error (RMSE dB vs the true field) for the hybrid map, the path-loss model
  alone and plain inverse-distance interpolation,
* weak-zone overlap (IoU of predicted vs true "signal < weak" cells),
* placement: TRUE coverage after following the advice vs before, vs the best
  possible candidate (oracle, found by trying every candidate in the true world),
  vs a randomly chosen candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from .analysis import analyze
from .config import Settings
from .estimator import fit_map, idw
from .floorplan import FloorPlan, candidate_positions
from .simulator import SimWorld, simulate_survey


def _true_coverage(truth: np.ndarray, weights: np.ndarray, weak_dbm: float) -> float:
    return float(((truth >= weak_dbm) * weights).sum() / weights.sum())


@dataclass
class Row:
    plan: str
    n_points: int
    worlds: int
    rmse_hybrid: float
    rmse_model: float
    rmse_idw: float
    weak_iou: float
    cov_before: float
    cov_advice: float
    cov_oracle: float
    cov_random: float
    cov_center: float
    gain_captured: float | None
    hurt_pct: float
    ext_before: float
    ext_advice: float
    ext_oracle: float


@dataclass
class EvaluationReport:
    rows: list[Row] = field(default_factory=list)

    def to_markdown(self) -> str:
        head = ["### Map accuracy (lower RMSE is better; truth = simulated field)",
                "| Plan | Points | Worlds | Hybrid RMSE | Model-only RMSE | Plain interpolation RMSE | Weak-zone IoU |",
                "|---|---:|---:|---:|---:|---:|---:|"]
        for r in self.rows:
            head.append(f"| {r.plan} | {r.n_points} | {r.worlds} | {r.rmse_hybrid:.2f} dB | {r.rmse_model:.2f} dB | "
                        f"{r.rmse_idw:.2f} dB | {r.weak_iou:.2f} |")
        head += ["", "### Router advice, scored in the TRUE simulated world (share of weighted area with OK signal)",
                 "| Plan | Points | Before | After advice (#1) | Centre-of-plan rule (no survey) | Best possible (oracle) | Random candidate | Share of possible gain captured | Advice made it worse (>1 pt) |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in self.rows:
            cap = "n/a" if r.gain_captured is None else f"{100 * r.gain_captured:.0f}%"
            head.append(f"| {r.plan} | {r.n_points} | {100 * r.cov_before:.1f}% | {100 * r.cov_advice:.1f}% | "
                        f"{100 * r.cov_center:.1f}% | {100 * r.cov_oracle:.1f}% | {100 * r.cov_random:.1f}% | {cap} | {r.hurt_pct:.0f}% |")
        head += ["", "### Extender advice, scored in the TRUE simulated world",
                 "| Plan | Points | Router only | With advised extender | Best possible extender |",
                 "|---|---:|---:|---:|---:|"]
        for r in self.rows:
            head.append(f"| {r.plan} | {r.n_points} | {100 * r.ext_before:.1f}% | {100 * r.ext_advice:.1f}% | "
                        f"{100 * r.ext_oracle:.1f}% |")
        return "\n".join(head)


def evaluate(settings: Settings, plans: Sequence[FloorPlan], worlds: int = 20,
             point_counts: Sequence[int] = (10, 20, 30), seed: int = 1000) -> EvaluationReport:
    thr, pl = settings.thresholds, settings.placement
    report = EvaluationReport()
    for plan in plans:
        cell, coarse = settings.grid.cell_m, settings.grid.placement_cell_m
        xs, ys = plan.cell_centers(cell)
        gx, gy = np.meshgrid(xs, ys)
        cxs, cys = plan.cell_centers(coarse)
        cgx, cgy = np.meshgrid(cxs, cys)
        weights = plan.cell_weights(cxs, cys)
        candidates = candidate_positions(plan, coarse, pl.wall_clearance_m)

        acc = {n: {k: [] for k in ("h", "m", "i", "iou", "b", "a", "o", "r", "c", "cap", "hurt", "eb", "ea", "eo")}
               for n in point_counts}
        for w in range(worlds):
            world = SimWorld(plan, seed=seed + w)
            truth_fine = world.grid_truth(cell)
            weak_true = truth_fine < thr.weak_dbm
            truth_router = world.true_rssi(cgx.ravel(), cgy.ravel()).reshape(cgx.shape)
            cov_before = _true_coverage(truth_router, weights, thr.weak_dbm)
            # sweep every candidate in the true world once (shared by all survey sizes)
            move_cov, ext_cov, cand_truth = {}, {}, {}
            for c in candidates:
                t = world.true_rssi(cgx.ravel(), cgy.ravel(), ap=c).reshape(cgx.shape)
                move_cov[c] = _true_coverage(t, weights, thr.weak_dbm)
                hears = float(world.true_rssi(np.array([c[0]]), np.array([c[1]]))[0])
                if hears >= pl.backhaul_min_dbm:
                    ext_cov[c] = _true_coverage(np.maximum(truth_router, t), weights, thr.weak_dbm)
                cand_truth[c] = t
            oracle = max(move_cov.values())
            random_mean = float(np.mean(list(move_cov.values())))
            # no-survey rule of thumb: the candidate nearest the weighted centre of the plan
            cgx_f, cgy_f = cgx.ravel(), cgy.ravel()
            centre = (float((cgx_f * weights.ravel()).sum() / weights.sum()),
                      float((cgy_f * weights.ravel()).sum() / weights.sum()))
            centre_pick = min(candidates, key=lambda c: (c[0] - centre[0]) ** 2 + (c[1] - centre[1]) ** 2)
            centre_cov = move_cov[centre_pick]
            ext_oracle = max(ext_cov.values()) if ext_cov else cov_before

            for n in point_counts:
                rng = np.random.default_rng([seed, w, n])
                meas = simulate_survey(world, n, settings.survey.readings_per_spot, rng)
                fitted = fit_map(plan, meas, settings)
                mean, _, base = fitted.predict(gx.ravel(), gy.ravel())
                mean, base = mean.reshape(gx.shape), base.reshape(gx.shape)
                near = idw([m.x for m in meas], [m.y for m in meas], [m.rssi_dbm for m in meas],
                           gx.ravel(), gy.ravel()).reshape(gx.shape)
                rmse = lambda e: float(np.sqrt(np.mean((e - truth_fine) ** 2)))
                a = acc[n]
                a["h"].append(rmse(mean)); a["m"].append(rmse(base)); a["i"].append(rmse(near))
                pred_weak = mean < thr.weak_dbm
                union = (pred_weak | weak_true).sum()
                a["iou"].append(1.0 if union == 0 else float((pred_weak & weak_true).sum() / union))

                res = analyze(plan, meas, settings)
                picks = res["suggestions"]["router"]["suggestions"]
                cov_advice = move_cov.get((picks[0]["x"], picks[0]["y"]), cov_before) if picks else cov_before
                if picks:                                  # candidates may be rounded to 2 decimals
                    key = min(move_cov, key=lambda c: abs(c[0] - picks[0]["x"]) + abs(c[1] - picks[0]["y"]))
                    cov_advice = move_cov[key]
                a["b"].append(cov_before); a["a"].append(cov_advice); a["o"].append(oracle); a["r"].append(random_mean); a["c"].append(centre_cov)
                if oracle - cov_before >= 0.03:
                    a["cap"].append((cov_advice - cov_before) / (oracle - cov_before))
                a["hurt"].append(float(cov_advice < cov_before - 0.01))

                ext = res["suggestions"]["extender"]["suggestion"]
                ext_after = cov_before
                if ext:
                    key = min(candidates, key=lambda c: abs(c[0] - ext["x"]) + abs(c[1] - ext["y"]))
                    ext_after = ext_cov.get(key, cov_before)     # invalid backhaul in truth -> no gain
                a["eb"].append(cov_before); a["ea"].append(ext_after); a["eo"].append(ext_oracle)

        for n in point_counts:
            a = acc[n]
            mean_of = lambda k: float(np.mean(a[k]))
            report.rows.append(Row(plan.name.split(" (")[0], n, worlds, mean_of("h"), mean_of("m"), mean_of("i"),
                                   mean_of("iou"), mean_of("b"), mean_of("a"), mean_of("o"), mean_of("r"), mean_of("c"),
                                   float(np.mean(a["cap"])) if a["cap"] else None,
                                   100 * mean_of("hurt"), mean_of("eb"), mean_of("ea"), mean_of("eo")))
    return report
