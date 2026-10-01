"""Command-line interface: ``python -m signalwalk <command>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .analysis import analyze
from .collectors import SignalReadError, detect_reader, take_spot_measurement
from .config import REPO_ROOT, ConfigError, Settings, load_dotenv, load_settings
from .floorplan import FloorPlan, FloorPlanError, load_floorplan
from .render import render_svg, text_report
from .simulator import SimWorld, simulate_survey
from .survey import Measurement, Survey, SurveyError

DEFAULT_PLAN = "apartment"


def resolve_floorplan(arg: Optional[str]) -> FloorPlan:
    """Accept a path, or a bare name such as 'apartment' (looked up in examples/floorplans)."""
    arg = arg or DEFAULT_PLAN
    candidates = [Path(arg)]
    if not arg.lower().endswith(".json"):
        for base in (Path.cwd(), REPO_ROOT):
            candidates.append(base / "examples" / "floorplans" / f"{arg}.json")
    for cand in candidates:
        if cand.is_file():
            return load_floorplan(cand)
    raise FloorPlanError(f"Floor plan '{arg}' not found. Give a .json path or one of: apartment, office")


# ---------------------------------------------------------------- commands

def cmd_demo(args, settings: Settings) -> int:
    """Simulate a survey of an example home and print the full report."""
    plan = resolve_floorplan(args.floorplan)
    world = SimWorld(plan, seed=args.seed)
    measurements = simulate_survey(world, args.points, settings.survey.readings_per_spot,
                                   np.random.default_rng([args.seed, 5]))
    print(f"Simulated survey: {len(measurements)} spots in '{plan.name}' (seed {args.seed}). "
          "All numbers below come from SIMULATED data.\n")
    result = analyze(plan, measurements, settings)
    print(text_report(plan, result, measurements))
    if args.svg:
        Path(args.svg).write_text(render_svg(plan, result, measurements), encoding="utf-8")
        print(f"\nWrote SVG heatmap: {args.svg}")
    if args.survey_out:
        survey = Survey(plan)
        survey.extend(measurements)
        Path(args.survey_out).write_text(survey.to_csv(), encoding="utf-8")
        print(f"Wrote survey CSV: {args.survey_out}")
    return 0


def cmd_serve(args, settings: Settings) -> int:
    import dataclasses

    import uvicorn

    from .api import create_app

    plan = resolve_floorplan(args.floorplan)
    server = settings.server
    changes = {k: v for k, v in (("host", args.host), ("port", args.port), ("sim_seed", args.seed)) if v is not None}
    if args.real:
        changes["mode"] = "real"
    if args.simulate:
        changes["mode"] = "simulate"
    server = dataclasses.replace(server, **changes)
    settings = dataclasses.replace(settings, server=server)
    settings.validate()
    if server.mode == "real":
        try:
            reading = detect_reader().read()
            print(f"Wi-Fi reader OK: {reading.dbm:.1f} dBm")
        except SignalReadError as exc:
            print(f"Warning: cannot read Wi-Fi signal right now ({exc}). "
                  "Run 'signalwalk check-reader' for details.", file=sys.stderr)
    if server.host not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: listening on a non-local address. SignalWalk has NO authentication; anyone who can "
              "reach this port can read your floor plan and survey and trigger Wi-Fi measurements.", file=sys.stderr)
    print(f"SignalWalk dashboard: http://{server.host}:{server.port}  "
          f"(mode: {server.mode}, plan: {plan.name})")
    uvicorn.run(create_app(settings, plan, server.mode), host=server.host, port=server.port, log_level="warning")
    return 0


def _parse_position(text: str, plan: FloorPlan) -> tuple[float, float]:
    parts = text.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError("enter two numbers: x y (metres from the top-left corner)")
    x, y = float(parts[0]), float(parts[1])
    if not plan.inside(x, y):
        raise ValueError(f"({x}, {y}) is outside the {plan.width_m:g} x {plan.height_m:g} m plan")
    return x, y


def cmd_survey(args, settings: Settings, input_fn=input) -> int:
    """Interactive terminal survey using this computer's Wi-Fi adapter."""
    plan = resolve_floorplan(args.floorplan)
    reader = detect_reader()
    survey = Survey(plan)
    out = Path(args.out)
    if out.exists() and not args.fresh:
        survey.load(out)
        print(f"Resumed {len(survey)} measurement(s) from {out}")
    print(f"Plan: {plan.name} ({plan.width_m:g} x {plan.height_m:g} m). Router at {plan.router}.")
    print("Stand still where you want to measure, then type its position as 'x y' in metres "
          "(from the top-left corner).\nCommands: u = undo last, r = report, q = save and quit.\n")
    while True:
        try:
            line = input_fn(f"[{len(survey)}] position> ").strip()
        except EOFError:
            line = "q"
        if line in ("q", "quit"):
            break
        if line in ("u", "undo"):
            if len(survey):
                survey.remove(len(survey) - 1); survey.save_json(out); print("removed last measurement")
            continue
        if line in ("r", "report"):
            if len(survey) >= 3:
                print(text_report(plan, analyze(plan, survey.measurements, settings), survey.measurements))
            else:
                print("need at least 3 measurements first")
            continue
        try:
            x, y = _parse_position(line, plan)
            spot = take_spot_measurement(reader, settings.survey.readings_per_spot,
                                         settings.survey.reading_interval_s)
        except (ValueError, SignalReadError) as exc:
            print(f"  ! {exc}")
            continue
        survey.add(Measurement(x, y, spot.dbm, spot.n_readings, spot.spread_db, None, "real", spot.ap_tag))
        survey.save_json(out)
        note = "  (device switched access points!)" if spot.roamed else ""
        print(f"  {spot.dbm:.1f} dBm  (spread {spot.spread_db:.1f} dB over {spot.n_readings} readings){note}")
    survey.save_json(out)
    print(f"Saved {len(survey)} measurement(s) to {out}")
    if len(survey) >= 3:
        print(text_report(plan, analyze(plan, survey.measurements, settings), survey.measurements))
    return 0


def cmd_analyze(args, settings: Settings) -> int:
    plan = resolve_floorplan(args.floorplan)
    survey = Survey(plan)
    survey.load(args.survey)
    result = analyze(plan, survey.measurements, settings)
    print(text_report(plan, result, survey.measurements))
    if args.svg:
        Path(args.svg).write_text(render_svg(plan, result, survey.measurements), encoding="utf-8")
        print(f"\nWrote SVG heatmap: {args.svg}")
    if args.json:
        Path(args.json).write_text(json.dumps(result), encoding="utf-8")
        print(f"Wrote analysis JSON: {args.json}")
    return 0


def cmd_check_reader(args, settings: Settings) -> int:
    """Try to read the signal strength once and explain what happened."""
    try:
        reader = detect_reader()
    except SignalReadError as exc:
        print(f"Unsupported system: {exc}", file=sys.stderr)
        return 1
    print(f"Reader: {reader.name}")
    try:
        reading = reader.read()
    except SignalReadError as exc:
        print(f"Could not read signal: {exc}", file=sys.stderr)
        print("Tips: connect to Wi-Fi first; on Linux install NetworkManager (nmcli) or check "
              "/proc/net/wireless; see docs/TROUBLESHOOTING.md.", file=sys.stderr)
        return 1
    print(f"Signal: {reading.dbm:.1f} dBm  (access point tag: {reading.ap_tag or 'unknown'})")
    return 0


def cmd_validate(args, settings: Settings) -> int:
    try:
        plan = load_floorplan(args.floorplan)
    except FloorPlanError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    print(f"OK: '{plan.name}' {plan.width_m:g} x {plan.height_m:g} m, {len(plan.walls)} walls, "
          f"{len(plan.rooms)} rooms, router at {plan.router}")
    return 0


def cmd_evaluate(args, settings: Settings) -> int:
    from .evaluation import evaluate
    plans = [resolve_floorplan(p) for p in args.floorplans]
    print(f"Evaluating {args.worlds} simulated worlds per plan (seed {args.seed}) ...", flush=True)
    print(evaluate(settings, plans, worlds=args.worlds, point_counts=args.points, seed=args.seed).to_markdown())
    return 0


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="signalwalk",
                                description="SignalWalk: measure Wi-Fi by walking around; map it; find dead zones.")
    p.add_argument("--config", help="path to a config YAML (default: config/default.yaml)")
    sub = p.add_subparsers(dest="command", required=True)
    fp = "floor plan: a .json path or 'apartment' / 'office' (default apartment)"

    d = sub.add_parser("demo", help="simulate a survey and print a full report (no hardware)")
    d.add_argument("--floorplan", help=fp); d.add_argument("--points", type=int, default=20)
    d.add_argument("--seed", type=int, default=3); d.add_argument("--svg", help="write an SVG heatmap")
    d.add_argument("--survey-out", help="write the simulated survey as CSV")
    d.set_defaults(func=cmd_demo)

    s = sub.add_parser("serve", help="run the dashboard")
    s.add_argument("--floorplan", help=fp)
    m = s.add_mutually_exclusive_group()
    m.add_argument("--simulate", action="store_true", help="virtual house: click to 'measure' (default)")
    m.add_argument("--real", action="store_true", help="read this computer's Wi-Fi signal")
    s.add_argument("--host"); s.add_argument("--port", type=int); s.add_argument("--seed", type=int)
    s.set_defaults(func=cmd_serve)

    sv = sub.add_parser("survey", help="interactive terminal survey with this computer's Wi-Fi")
    sv.add_argument("--floorplan", help=fp); sv.add_argument("--out", default="survey.json")
    sv.add_argument("--fresh", action="store_true", help="ignore an existing --out file")
    sv.set_defaults(func=cmd_survey)

    a = sub.add_parser("analyze", help="analyse a saved survey (.json or .csv)")
    a.add_argument("survey"); a.add_argument("--floorplan", help=fp)
    a.add_argument("--svg"); a.add_argument("--json")
    a.set_defaults(func=cmd_analyze)

    c = sub.add_parser("check-reader", help="test reading this computer's Wi-Fi signal")
    c.set_defaults(func=cmd_check_reader)

    v = sub.add_parser("validate-floorplan", help="check a floor plan file")
    v.add_argument("floorplan"); v.set_defaults(func=cmd_validate)

    e = sub.add_parser("evaluate", help="synthetic evaluation (simulation only)")
    e.add_argument("--floorplans", nargs="+", default=["apartment", "office"])
    e.add_argument("--worlds", type=int, default=20); e.add_argument("--seed", type=int, default=1000)
    e.add_argument("--points", type=int, nargs="+", default=[10, 20, 30])
    e.set_defaults(func=cmd_evaluate)
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_dotenv(".env")
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
        return args.func(args, settings)
    except (ConfigError, FloorPlanError, SurveyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
