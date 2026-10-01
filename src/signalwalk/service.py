"""A survey session: floor plan + measurements + how to take a measurement."""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from .analysis import analyze
from .collectors import SignalReader, detect_reader, take_spot_measurement
from .config import Settings
from .floorplan import FloorPlan
from .simulator import SimWorld, simulate_survey
from .survey import Measurement, Survey, SurveyError


class SessionBusy(RuntimeError):
    """A measurement is already in progress."""


class Session:
    def __init__(self, settings: Settings, plan: FloorPlan, mode: str = "simulate",
                 reader: Optional[SignalReader] = None, seed: Optional[int] = None):
        if mode not in ("simulate", "real"):
            raise ValueError("mode must be 'simulate' or 'real'")
        self.settings, self.plan, self.mode = settings, plan, mode
        self.survey = Survey(plan)
        self.seed = settings.server.sim_seed if seed is None else seed
        self.world = SimWorld(plan, self.seed) if mode == "simulate" else None
        self.reader = (reader or detect_reader()) if mode == "real" else None
        self._rng = np.random.default_rng([self.seed, 77])
        self._lock = threading.RLock()
        self._measuring = threading.Lock()
        self._cache: tuple[int, bool, dict] | None = None

    # ---- measuring
    def measure(self, x: float, y: float) -> tuple[int, Measurement]:
        """Take one spot measurement at (x, y) metres. Blocks ~2 s in real mode."""
        if not self.plan.inside(x, y):
            raise SurveyError(f"Position ({x:.2f}, {y:.2f}) is outside the plan")
        if not self._measuring.acquire(blocking=False):
            raise SessionBusy("Another measurement is still running")
        try:
            n = self.settings.survey.readings_per_spot
            if self.mode == "simulate":
                with self._lock:
                    m = self.world.measure(x, y, n, self._rng)
            else:
                spot = take_spot_measurement(self.reader, n, self.settings.survey.reading_interval_s)
                m = Measurement(x, y, spot.dbm, spot.n_readings, spot.spread_db, time.time(), "real", spot.ap_tag)
            with self._lock:
                return self.survey.add(m), m
        finally:
            self._measuring.release()

    def auto_survey(self, count: int) -> list[Measurement]:
        """Simulation only: add ``count`` sensibly spread virtual measurements."""
        if self.mode != "simulate":
            raise SurveyError("Auto-survey exists only in simulation mode")
        with self._lock:
            batch = simulate_survey(self.world, count, self.settings.survey.readings_per_spot, self._rng)
            self.survey.extend(batch)
            return batch

    def remove(self, index: int) -> Measurement:
        with self._lock:
            return self.survey.remove(index)

    def reset(self) -> None:
        with self._lock:
            self.survey.clear()

    # ---- analysis
    def analysis(self, with_suggestions: bool = True) -> dict:
        with self._lock:
            key = self.survey.version
            if self._cache and self._cache[0] == key and self._cache[1] == with_suggestions:
                return self._cache[2]
            result = analyze(self.plan, self.survey.measurements, self.settings, with_suggestions)
            self._cache = (key, with_suggestions, result)
            return result
