"""Settings loading and validation (YAML file plus a few SIGNALWALK_* variables)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """Raised for missing or inconsistent configuration."""


@dataclass(frozen=True)
class Thresholds:
    strong_dbm: float = -55.0
    weak_dbm: float = -70.0
    dead_dbm: float = -80.0


@dataclass(frozen=True)
class GridConfig:
    cell_m: float = 0.25
    placement_cell_m: float = 0.5


@dataclass(frozen=True)
class ModelPrior:
    a_dbm: float = -40.0
    n: float = 2.8
    wall_db: Mapping[str, float] = field(default_factory=lambda: {"light": 3.0, "interior": 6.0, "heavy": 12.0})


@dataclass(frozen=True)
class ModelConfig:
    prior: ModelPrior = field(default_factory=ModelPrior)
    a_std: float = 12.0
    n_std: float = 0.8
    wall_std: float = 4.0
    noise_db: float = 3.0
    min_n: float = 1.5
    max_n: float = 5.0
    max_wall_db: float = 25.0


@dataclass(frozen=True)
class GPConfig:
    sigma_f_db: float = 4.0
    length_m: float = 3.0
    sigma_n_db: float = 2.5


@dataclass(frozen=True)
class SurveyConfig:
    readings_per_spot: int = 5
    reading_interval_s: float = 0.4
    min_points_warn: int = 10


@dataclass(frozen=True)
class PlacementConfig:
    top_k: int = 3
    min_separation_m: float = 1.5
    wall_clearance_m: float = 0.3
    backhaul_min_dbm: float = -65.0
    next_spots: int = 3
    next_spot_separation_m: float = 2.0
    default_model_rmse_db: float = 6.0


@dataclass(frozen=True)
class ZoneConfig:
    min_area_m2: float = 1.0


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    mode: str = "simulate"
    sim_seed: int = 3


@dataclass(frozen=True)
class Settings:
    thresholds: Thresholds = field(default_factory=Thresholds)
    grid: GridConfig = field(default_factory=GridConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    gp: GPConfig = field(default_factory=GPConfig)
    survey: SurveyConfig = field(default_factory=SurveyConfig)
    placement: PlacementConfig = field(default_factory=PlacementConfig)
    zones: ZoneConfig = field(default_factory=ZoneConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    def validate(self) -> None:
        t = self.thresholds
        if not t.dead_dbm < t.weak_dbm < t.strong_dbm < 0:
            raise ConfigError("thresholds must satisfy dead_dbm < weak_dbm < strong_dbm < 0")
        if self.grid.cell_m <= 0 or self.grid.placement_cell_m <= 0:
            raise ConfigError("grid cell sizes must be > 0")
        if self.gp.length_m <= 0 or self.gp.sigma_f_db <= 0 or self.gp.sigma_n_db <= 0:
            raise ConfigError("gp parameters must be > 0")
        if self.survey.readings_per_spot < 1:
            raise ConfigError("survey.readings_per_spot must be >= 1")
        if not self.model.min_n < self.model.max_n:
            raise ConfigError("model.min_n must be < model.max_n")
        if self.server.mode not in ("simulate", "real"):
            raise ConfigError("server.mode must be 'simulate' or 'real'")
        if not 0 < self.server.port < 65536:
            raise ConfigError("server.port must be 1-65535")


def resolve_config_path(explicit: Optional[str | Path] = None,
                        environ: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    env = os.environ if environ is None else environ
    for cand in (explicit, env.get("SIGNALWALK_CONFIG"), Path.cwd() / "config" / "default.yaml",
                 REPO_ROOT / "config" / "default.yaml"):
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


def resolve_app_dir(environ: Optional[Mapping[str, str]] = None) -> Optional[Path]:
    env = os.environ if environ is None else environ
    for cand in (env.get("SIGNALWALK_APP_DIR"), Path.cwd() / "app", REPO_ROOT / "app"):
        if cand and (Path(cand) / "index.html").is_file():
            return Path(cand)
    return None


def _build(cls, data: Optional[Mapping[str, Any]], where: str):
    data = dict(data or {})
    names = {f.name for f in fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ConfigError(f"Unknown key(s) in '{where}': {sorted(unknown)}")
    return cls(**data)


def load_settings(path: Optional[str | Path] = None,
                  environ: Optional[Mapping[str, str]] = None) -> Settings:
    """Load settings. Falls back to built-in defaults if no file is found."""
    env = os.environ if environ is None else environ
    raw: dict[str, Any] = {}
    if path and not Path(path).is_file():
        raise ConfigError(f"Config file not found: {path}")     # never silently fall back to defaults
    cfg_path = resolve_config_path(path, env)
    if cfg_path is not None:
        try:
            raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Invalid YAML in {cfg_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"{cfg_path} must contain a mapping")
    known = {"thresholds", "grid", "model", "gp", "survey", "placement", "zones", "server"}
    if set(raw) - known:
        raise ConfigError(f"Unknown top-level key(s): {sorted(set(raw) - known)}")

    model_raw = dict(raw.get("model") or {})
    prior = _build(ModelPrior, model_raw.pop("prior", None), "model.prior")
    model = _build(ModelConfig, {**model_raw, "prior": prior}, "model")

    server_raw = dict(raw.get("server") or {})
    if env.get("SIGNALWALK_HOST"): server_raw["host"] = env["SIGNALWALK_HOST"]
    if env.get("SIGNALWALK_PORT"): server_raw["port"] = env["SIGNALWALK_PORT"]
    if env.get("SIGNALWALK_MODE"): server_raw["mode"] = env["SIGNALWALK_MODE"]
    if env.get("SIGNALWALK_SIM_SEED"): server_raw["sim_seed"] = env["SIGNALWALK_SIM_SEED"]
    try:
        server_raw["port"] = int(server_raw.get("port", 8000))
        server_raw["sim_seed"] = int(server_raw.get("sim_seed", 3))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid server setting: {exc}") from exc

    settings = Settings(
        thresholds=_build(Thresholds, raw.get("thresholds"), "thresholds"),
        grid=_build(GridConfig, raw.get("grid"), "grid"), model=model,
        gp=_build(GPConfig, raw.get("gp"), "gp"), survey=_build(SurveyConfig, raw.get("survey"), "survey"),
        placement=_build(PlacementConfig, raw.get("placement"), "placement"),
        zones=_build(ZoneConfig, raw.get("zones"), "zones"),
        server=_build(ServerConfig, server_raw, "server"))
    settings.validate()
    return settings


def parse_dotenv(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key.strip():
            result[key.strip()] = value
    return result


def load_dotenv(path: str | Path = ".env", environ: Optional[dict] = None) -> bool:
    env = os.environ if environ is None else environ
    p = Path(path)
    if not p.is_file():
        return False
    for key, value in parse_dotenv(p.read_text(encoding="utf-8")).items():
        env.setdefault(key, value)
    return True
