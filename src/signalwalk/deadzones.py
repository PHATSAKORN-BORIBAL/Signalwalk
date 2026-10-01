"""Dead-zone detection and per-room report cards."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

import numpy as np

from .config import Settings
from .floorplan import FloorPlan


def normal_cdf(z: np.ndarray) -> np.ndarray:
    """Standard normal CDF via the Abramowitz-Stegun 7.1.26 erf approximation (|err| < 1.5e-7)."""
    z = np.asarray(z, dtype=float)
    x = np.abs(z) / np.sqrt(2.0)
    t = 1.0 / (1.0 + 0.3275911 * x)
    poly = ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t
    erf = 1.0 - poly * np.exp(-x * x)
    return 0.5 * (1.0 + np.sign(z) * erf)


def label_components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected component labelling. Returns (labels, count); 0 = background."""
    labels = np.zeros(mask.shape, dtype=int)
    ny, nx = mask.shape
    count = 0
    for j in range(ny):
        for i in range(nx):
            if mask[j, i] and labels[j, i] == 0:
                count += 1
                stack = [(j, i)]
                labels[j, i] = count
                while stack:
                    cj, ci = stack.pop()
                    for nj, ni in ((cj + 1, ci), (cj - 1, ci), (cj, ci + 1), (cj, ci - 1)):
                        if 0 <= nj < ny and 0 <= ni < nx and mask[nj, ni] and labels[nj, ni] == 0:
                            labels[nj, ni] = count
                            stack.append((nj, ni))
    return labels, count


@dataclass
class Zone:
    id: int
    area_m2: float
    x: float
    y: float
    min_dbm: float
    mean_dbm: float
    severity: str                    # "dead" | "weak"
    rooms: list[dict]                # [{"name":..., "share":...}] largest first
    certainty: float                 # mean P(signal < weak threshold) over the zone
    measured_inside: int             # survey points that fall in the zone

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(area_m2=round(self.area_m2, 1), x=round(self.x, 2), y=round(self.y, 2),
                 min_dbm=round(self.min_dbm, 1), mean_dbm=round(self.mean_dbm, 1),
                 certainty=round(self.certainty, 2))
        return d


def find_zones(plan: FloorPlan, xs: np.ndarray, ys: np.ndarray, mean: np.ndarray, std: np.ndarray,
               settings: Settings, points: Optional[list[tuple[float, float]]] = None) -> list[Zone]:
    thr = settings.thresholds
    cell_area = (xs[1] - xs[0] if len(xs) > 1 else 1.0) * (ys[1] - ys[0] if len(ys) > 1 else 1.0)
    labels, count = label_components(mean < thr.weak_dbm)
    p_weak = normal_cdf((thr.weak_dbm - mean) / std)
    gx, gy = np.meshgrid(xs, ys)
    zones: list[Zone] = []
    for lab in range(1, count + 1):
        sel = labels == lab
        area = float(sel.sum() * cell_area)
        if area < settings.zones.min_area_m2:
            continue
        shares: dict[str, int] = {}
        for x, y in zip(gx[sel], gy[sel]):
            name = plan.room_name_at(float(x), float(y))
            shares[name] = shares.get(name, 0) + 1
        total = sum(shares.values())
        rooms = [{"name": n, "share": round(c / total, 2)}
                 for n, c in sorted(shares.items(), key=lambda kv: -kv[1]) if c / total >= 0.15]
        inside = 0
        for px, py in points or []:
            i = int(np.argmin(np.abs(xs - px))); j = int(np.argmin(np.abs(ys - py)))
            inside += int(sel[j, i])
        zones.append(Zone(0, area, float(gx[sel].mean()), float(gy[sel].mean()), float(mean[sel].min()),
                          float(mean[sel].mean()), "dead" if mean[sel].min() < thr.dead_dbm else "weak",
                          rooms, float(p_weak[sel].mean()), inside))
    zones.sort(key=lambda z: (-z.area_m2, z.min_dbm))
    for i, z in enumerate(zones, start=1):
        z.id = i
    return zones


def room_report(plan: FloorPlan, xs: np.ndarray, ys: np.ndarray, mean: np.ndarray,
                settings: Settings, measured: list[tuple[float, float]]) -> list[dict]:
    """Per-room 'report card': typical signal and the share of the room that is OK."""
    thr = settings.thresholds
    gx, gy = np.meshgrid(xs, ys)
    report = []
    for room in plan.rooms:
        sel = (gx >= room.x) & (gx < room.x + room.w) & (gy >= room.y) & (gy < room.y + room.h)
        if not sel.any():
            continue
        vals = mean[sel]
        count = sum(room.contains(px, py) for px, py in measured)
        ok = float((vals >= thr.weak_dbm).mean())
        report.append({"room": room.name, "median_dbm": round(float(np.median(vals)), 1),
                       "worst_dbm": round(float(vals.min()), 1), "ok_pct": round(100 * ok),
                       "measured_points": count,
                       "grade": _grade(float(np.median(vals)), ok, thr)})
    return report


def _grade(median: float, ok_share: float, thr) -> str:
    if ok_share >= 0.95 and median >= thr.strong_dbm - 5:
        return "good"
    if ok_share >= 0.8:
        return "fair"
    if ok_share >= 0.4:
        return "poor"
    return "dead"
