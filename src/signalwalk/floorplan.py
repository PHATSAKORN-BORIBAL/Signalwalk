"""Floor plan geometry: walls, rooms, router position, wall-crossing counts.

Coordinates are metres. x grows to the right, y grows downwards (like a picture),
origin at the top-left corner of the plan.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np

WALL_KINDS = ("light", "interior", "heavy")
# light    = drywall, glass, wooden partition
# interior = brick or block, bathroom walls
# heavy    = concrete, exterior walls, lift shafts


class FloorPlanError(ValueError):
    """Raised when a floor plan file is malformed."""


@dataclass(frozen=True)
class Wall:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: str = "light"

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


@dataclass(frozen=True)
class Room:
    name: str
    x: float
    y: float
    w: float
    h: float
    priority: float = 1.0

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def area(self) -> float:
        return self.w * self.h


def crossing_matrix(ap: tuple[float, float], px: np.ndarray, py: np.ndarray,
                    walls: np.ndarray) -> np.ndarray:
    """Boolean (N, W): does the straight line from ``ap`` to point i cross wall j?

    ``walls`` has shape (W, 4) = x1, y1, x2, y2. Proper crossings only.
    """
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    if walls.shape[0] == 0:
        return np.zeros((px.shape[0], 0), dtype=bool)
    ax, ay = ap
    dx, dy = (px - ax)[:, None], (py - ay)[:, None]
    x1, y1, x2, y2 = (walls[:, i][None, :] for i in range(4))
    o1 = dx * (y1 - ay) - dy * (x1 - ax)
    o2 = dx * (y2 - ay) - dy * (x2 - ax)
    wx, wy = x2 - x1, y2 - y1
    o3 = wx * (ay - y1) - wy * (ax - x1)
    o4 = wx * (py[:, None] - y1) - wy * (px[:, None] - x1)
    return (o1 * o2 < 0) & (o3 * o4 < 0)


def distance_to_segments(px: np.ndarray, py: np.ndarray, walls: np.ndarray) -> np.ndarray:
    """Distance from each point to the nearest wall segment (inf if there are no walls)."""
    px = np.asarray(px, dtype=float)[:, None]
    py = np.asarray(py, dtype=float)[:, None]
    if walls.shape[0] == 0:
        return np.full(px.shape[0], np.inf)
    x1, y1, x2, y2 = (walls[:, i][None, :] for i in range(4))
    vx, vy = x2 - x1, y2 - y1
    length2 = np.maximum(vx * vx + vy * vy, 1e-12)
    t = np.clip(((px - x1) * vx + (py - y1) * vy) / length2, 0.0, 1.0)
    return np.hypot(px - (x1 + t * vx), py - (y1 + t * vy)).min(axis=1)


@dataclass(frozen=True)
class FloorPlan:
    name: str
    width_m: float
    height_m: float
    router: tuple[float, float]
    walls: tuple[Wall, ...]
    rooms: tuple[Room, ...] = ()
    router_candidates: tuple[tuple[float, float], ...] = ()

    # ---- geometry helpers
    def wall_array(self) -> np.ndarray:
        return np.array([[w.x1, w.y1, w.x2, w.y2] for w in self.walls], dtype=float).reshape(-1, 4)

    def kind_onehot(self) -> np.ndarray:
        """(W, len(WALL_KINDS)) 0/1 matrix mapping each wall to its kind."""
        m = np.zeros((len(self.walls), len(WALL_KINDS)))
        for i, w in enumerate(self.walls):
            m[i, WALL_KINDS.index(w.kind)] = 1.0
        return m

    def crossings(self, ap: tuple[float, float], px: np.ndarray, py: np.ndarray) -> np.ndarray:
        """(N, 3) count of walls crossed on the way from ``ap``, per wall kind."""
        return crossing_matrix(ap, px, py, self.wall_array()).astype(float) @ self.kind_onehot()

    def room_at(self, px: float, py: float) -> Optional[Room]:
        for room in self.rooms:
            if room.contains(px, py):
                return room
        return None

    def room_name_at(self, px: float, py: float) -> str:
        room = self.room_at(px, py)
        return room.name if room else "Outside rooms"

    def inside(self, px: float, py: float) -> bool:
        return 0.0 <= px <= self.width_m and 0.0 <= py <= self.height_m

    def cell_centers(self, cell_m: float) -> tuple[np.ndarray, np.ndarray]:
        nx = max(1, int(round(self.width_m / cell_m)))
        ny = max(1, int(round(self.height_m / cell_m)))
        xs = (np.arange(nx) + 0.5) * (self.width_m / nx)
        ys = (np.arange(ny) + 0.5) * (self.height_m / ny)
        return xs, ys

    def cell_weights(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """(ny, nx) importance weights: room priority, or 1.0 outside any room."""
        w = np.ones((len(ys), len(xs)))
        for room in self.rooms:
            mx = (xs >= room.x) & (xs < room.x + room.w)
            my = (ys >= room.y) & (ys < room.y + room.h)
            w[np.ix_(my, mx)] = room.priority
        return w

    def to_dict(self) -> dict:
        return {
            "name": self.name, "width_m": self.width_m, "height_m": self.height_m,
            "router": {"x": self.router[0], "y": self.router[1]},
            "walls": [{"x1": w.x1, "y1": w.y1, "x2": w.x2, "y2": w.y2, "kind": w.kind} for w in self.walls],
            "rooms": [{"name": r.name, "x": r.x, "y": r.y, "w": r.w, "h": r.h, "priority": r.priority}
                      for r in self.rooms],
            "router_candidates": [{"x": x, "y": y} for x, y in self.router_candidates],
        }


def _num(d: Mapping[str, Any], key: str, where: str) -> float:
    try:
        v = float(d[key])
    except KeyError as exc:
        raise FloorPlanError(f"{where}: missing '{key}'") from exc
    except (TypeError, ValueError) as exc:
        raise FloorPlanError(f"{where}: '{key}' must be a number") from exc
    if not math.isfinite(v):
        raise FloorPlanError(f"{where}: '{key}' must be finite")
    return v


def floorplan_from_dict(data: Mapping[str, Any]) -> FloorPlan:
    if not isinstance(data, Mapping):
        raise FloorPlanError("floor plan must be a JSON object")
    width, height = _num(data, "width_m", "plan"), _num(data, "height_m", "plan")
    if not (1.0 <= width <= 200.0 and 1.0 <= height <= 200.0):
        raise FloorPlanError("plan: width_m and height_m must be between 1 and 200")

    def inside(x: float, y: float, where: str) -> None:
        if not (0.0 <= x <= width and 0.0 <= y <= height):
            raise FloorPlanError(f"{where}: point ({x}, {y}) is outside the plan")

    walls = []
    for i, w in enumerate(data.get("walls", [])):
        where = f"walls[{i}]"
        x1, y1, x2, y2 = (_num(w, k, where) for k in ("x1", "y1", "x2", "y2"))
        kind = str(w.get("kind", "light"))
        if kind not in WALL_KINDS:
            raise FloorPlanError(f"{where}: kind must be one of {WALL_KINDS}, got '{kind}'")
        inside(x1, y1, where); inside(x2, y2, where)
        wall = Wall(x1, y1, x2, y2, kind)
        if wall.length < 0.05:
            raise FloorPlanError(f"{where}: wall is (almost) zero length")
        walls.append(wall)

    rooms = []
    for i, r in enumerate(data.get("rooms", [])):
        where = f"rooms[{i}]"
        x, y, w_, h_ = (_num(r, k, where) for k in ("x", "y", "w", "h"))
        if w_ <= 0 or h_ <= 0:
            raise FloorPlanError(f"{where}: w and h must be > 0")
        if x < 0 or y < 0 or x + w_ > width + 1e-9 or y + h_ > height + 1e-9:
            raise FloorPlanError(f"{where}: room extends outside the plan")
        priority = float(r.get("priority", 1.0))
        if priority <= 0:
            raise FloorPlanError(f"{where}: priority must be > 0")
        rooms.append(Room(str(r.get("name", f"Room {i + 1}")), x, y, w_, h_, priority))

    router = data.get("router")
    if not isinstance(router, Mapping):
        raise FloorPlanError("plan: 'router' with x and y is required")
    rx, ry = _num(router, "x", "router"), _num(router, "y", "router")
    inside(rx, ry, "router")

    cands = []
    for i, c in enumerate(data.get("router_candidates", [])):
        cx, cy = _num(c, "x", f"router_candidates[{i}]"), _num(c, "y", f"router_candidates[{i}]")
        inside(cx, cy, f"router_candidates[{i}]")
        cands.append((cx, cy))

    plan = FloorPlan(str(data.get("name", "Untitled plan")), width, height, (rx, ry),
                     tuple(walls), tuple(rooms), tuple(cands))
    if distance_to_segments(np.array([rx]), np.array([ry]), plan.wall_array())[0] < 0.05:
        raise FloorPlanError("router: sits on a wall; move it slightly off the wall line")
    return plan


def load_floorplan(path: str | Path) -> FloorPlan:
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FloorPlanError(f"Floor plan not found: {p}") from exc
    except json.JSONDecodeError as exc:
        raise FloorPlanError(f"{p} is not valid JSON: {exc}") from exc
    return floorplan_from_dict(data)


def candidate_positions(plan: FloorPlan, step_m: float, clearance_m: float) -> list[tuple[float, float]]:
    """Places a router could go: the plan's own list if given, else a grid that
    keeps ``clearance_m`` away from every wall."""
    walls = plan.wall_array()
    if plan.router_candidates:
        pts = list(plan.router_candidates)
    else:
        xs, ys = plan.cell_centers(step_m)
        pts = [(float(x), float(y)) for y in ys for x in xs]
    arr = np.array(pts, dtype=float).reshape(-1, 2)
    keep = distance_to_segments(arr[:, 0], arr[:, 1], walls) >= clearance_m
    return [p for p, k in zip(pts, keep) if k]
