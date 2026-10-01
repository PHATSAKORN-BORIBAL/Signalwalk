"""Measurements and the survey container (JSON and CSV persistence)."""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

from .floorplan import FloorPlan

RSSI_MIN, RSSI_MAX = -100.0, -10.0


class SurveyError(ValueError):
    """Raised for invalid measurements or unreadable survey files."""


@dataclass(frozen=True)
class Measurement:
    x: float
    y: float
    rssi_dbm: float
    n_readings: int = 1
    spread_db: float = 0.0          # max - min of the readings taken at this spot
    ts: Optional[float] = None      # unix time, informational only
    source: str = "real"            # real | simulated | csv
    ap_tag: Optional[str] = None    # short hash of the access point, to detect roaming

    def to_dict(self) -> dict:
        return asdict(self)


class Survey:
    """An ordered list of validated measurements for one floor plan."""

    def __init__(self, plan: FloorPlan):
        self.plan = plan
        self._items: list[Measurement] = []
        self.version = 0

    def __len__(self) -> int:
        return len(self._items)

    @property
    def measurements(self) -> list[Measurement]:
        return list(self._items)

    def validate(self, m: Measurement) -> None:
        for name in ("x", "y", "rssi_dbm"):
            if not math.isfinite(getattr(m, name)):
                raise SurveyError(f"{name} must be a finite number")
        if not self.plan.inside(m.x, m.y):
            raise SurveyError(f"Position ({m.x:.2f}, {m.y:.2f}) is outside the "
                              f"{self.plan.width_m:g} x {self.plan.height_m:g} m plan")
        if not RSSI_MIN <= m.rssi_dbm <= RSSI_MAX:
            raise SurveyError(f"Signal {m.rssi_dbm:.1f} dBm is outside the plausible range "
                              f"{RSSI_MIN:g}..{RSSI_MAX:g} dBm")

    def add(self, m: Measurement) -> int:
        self.validate(m)
        self._items.append(m)
        self.version += 1
        return len(self._items) - 1

    def extend(self, items: Iterable[Measurement]) -> None:
        for m in items:
            self.add(m)

    def remove(self, index: int) -> Measurement:
        if not 0 <= index < len(self._items):
            raise SurveyError(f"No measurement #{index}")
        self.version += 1
        return self._items.pop(index)

    def clear(self) -> None:
        self._items.clear()
        self.version += 1

    # ---- persistence
    def to_dict(self) -> dict:
        return {"schema": "signalwalk.survey/1", "floorplan": self.plan.name,
                "measurements": [m.to_dict() for m in self._items]}

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")

    def load_json(self, path: str | Path) -> None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            items = [Measurement(**{k: v for k, v in d.items() if k in Measurement.__dataclass_fields__})
                     for d in data["measurements"]]
        except FileNotFoundError as exc:
            raise SurveyError(f"Survey file not found: {path}") from exc
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise SurveyError(f"Cannot read survey {path}: {exc}") from exc
        self.clear()
        self.extend(items)

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["x_m", "y_m", "rssi_dbm", "n_readings", "spread_db", "source"])
        for m in self._items:
            writer.writerow([f"{m.x:.2f}", f"{m.y:.2f}", f"{m.rssi_dbm:.1f}", m.n_readings,
                             f"{m.spread_db:.1f}", m.source])
        return buf.getvalue()

    def load_csv(self, path: str | Path) -> None:
        """CSV needs columns x_m, y_m, rssi_dbm (others optional)."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SurveyError(f"Survey file not found: {path}") from exc
        reader = csv.DictReader(io.StringIO(text))
        need = {"x_m", "y_m", "rssi_dbm"}
        if not reader.fieldnames or not need <= set(reader.fieldnames):
            raise SurveyError(f"CSV needs columns {sorted(need)}")
        items = []
        for line, row in enumerate(reader, start=2):
            try:
                items.append(Measurement(float(row["x_m"]), float(row["y_m"]), float(row["rssi_dbm"]),
                                         int(float(row.get("n_readings") or 1)),
                                         float(row.get("spread_db") or 0.0), None, "csv"))
            except (TypeError, ValueError) as exc:
                raise SurveyError(f"CSV line {line}: {exc}") from exc
        self.clear()
        self.extend(items)

    def load(self, path: str | Path) -> None:
        (self.load_json if str(path).lower().endswith(".json") else self.load_csv)(path)
