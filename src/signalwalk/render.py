"""Terminal (ASCII) and SVG renderings of an analysis result.

The palette runs dark (dead) to bright (strong), so dead zones stand out and the
ramp stays readable for most kinds of colour blindness. app/static/app.js uses
the same stops.
"""

from __future__ import annotations

from html import escape
from typing import Optional, Sequence

import numpy as np

from .floorplan import FloorPlan
from .survey import Measurement

PALETTE = [(-95.0, (18, 10, 42)), (-85.0, (58, 15, 96)), (-75.0, (140, 40, 120)),
           (-67.0, (220, 80, 90)), (-60.0, (245, 140, 60)), (-52.0, (250, 200, 80)),
           (-42.0, (252, 245, 170))]
WALL_STYLE = {"light": 1.2, "interior": 2.4, "heavy": 4.0}
INK = "#14212e"


def rssi_rgb(dbm: float) -> tuple[int, int, int]:
    if dbm <= PALETTE[0][0]:
        return PALETTE[0][1]
    for (d0, c0), (d1, c1) in zip(PALETTE, PALETTE[1:]):
        if dbm <= d1:
            t = (dbm - d0) / (d1 - d0)
            return tuple(int(round(a + (b - a) * t)) for a, b in zip(c0, c1))  # type: ignore[return-value]
    return PALETTE[-1][1]


def rssi_hex(dbm: float) -> str:
    return "#%02x%02x%02x" % rssi_rgb(dbm)


# ------------------------------------------------------------------- ASCII

def _rasterize(plan: FloorPlan, cols: int, rows: int) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for w in plan.walls:
        steps = int(max(abs(w.x2 - w.x1) / plan.width_m * cols, abs(w.y2 - w.y1) / plan.height_m * rows)) * 2 + 2
        for t in np.linspace(0.0, 1.0, steps):
            c = int((w.x1 + (w.x2 - w.x1) * t) / plan.width_m * cols)
            r = int((w.y1 + (w.y2 - w.y1) * t) / plan.height_m * rows)
            cells.add((min(rows - 1, r), min(cols - 1, c)))
    return cells


def _ramp(dbm: float, thr: dict) -> str:
    if dbm >= thr["strong_dbm"]: return "@"
    if dbm >= thr["strong_dbm"] - 7: return "#"
    if dbm >= thr["weak_dbm"]: return "*"
    if dbm >= thr["weak_dbm"] - 5: return "+"
    if dbm >= thr["dead_dbm"]: return "."
    return " "


def ascii_map(plan: FloorPlan, result: dict, points: Sequence[Measurement], cols: int = 72) -> str:
    """Heatmap as text. Walls are full blocks, R = router, o = measurement, 1-3 = advice."""
    rows = max(6, int(round(cols * plan.height_m / plan.width_m * 0.5)))
    mean = np.array(result["grid"]["mean"])
    ny, nx = mean.shape
    thr = result["thresholds"]
    canvas = [[" "] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            canvas[r][c] = _ramp(float(mean[min(ny - 1, int(r / rows * ny)), min(nx - 1, int(c / cols * nx))]), thr)
    for r, c in _rasterize(plan, cols, rows):
        canvas[r][c] = "█"

    def put(x: float, y: float, ch: str) -> None:
        c, r = min(cols - 1, int(x / plan.width_m * cols)), min(rows - 1, int(y / plan.height_m * rows))
        canvas[r][c] = ch

    for m in points:
        put(m.x, m.y, "o")
    advice = result.get("suggestions")
    if advice:
        for i, item in enumerate(advice["router"]["suggestions"], start=1):
            put(item["x"], item["y"], str(i))
    put(*plan.router, "R")
    top = "┌" + "─" * cols + "┐"
    body = ["│" + "".join(row) + "│" for row in canvas]
    return "\n".join([top, *body, "└" + "─" * cols + "┘"])


def text_report(plan: FloorPlan, result: dict, points: Sequence[Measurement]) -> str:
    thr, cov = result["thresholds"], result["coverage"]
    lines = ["=" * 78, f" SignalWalk report: {plan.name}", "=" * 78,
             f" {result['n_points']} measurement(s)   OK (>= {thr['weak_dbm']:g} dBm): {cov['ok_pct']:.0f}%   "
             f"weak: {cov['weak_pct']:.0f}%   dead (< {thr['dead_dbm']:g}): {cov['dead_pct']:.0f}%", "",
             ascii_map(plan, result, points),
             "  Legend: @ strong  # good  * OK  + weak  . poor  (blank) dead   █ wall   R router   o measured   1-3 advice",
             ""]
    if result["cv"]:
        cv = result["cv"]
        lines.append(f" Leave-one-out error: hybrid {cv['rmse_hybrid']} dB | model only {cv['rmse_model']} dB | "
                     f"plain interpolation {cv['rmse_idw']} dB")
    m = result["model"]
    lines.append(f" Fitted model: {m['a_dbm']} dBm at 1 m, exponent {m['n']}, walls "
                 + ", ".join(f"{k} {v} dB" for k, v in m["wall_db"].items()))
    lines += ["", " Room report card:"]
    for r in result["rooms"]:
        lines.append(f"  {r['room']:<16} median {r['median_dbm']:>6.1f} dBm   OK {r['ok_pct']:>3}%   "
                     f"grade: {r['grade']:<5} ({r['measured_points']} pts)")
    lines += ["", " Weak / dead zones:"]
    for z in result["zones"] or []:
        rooms = ", ".join(f"{r['name']} {int(r['share'] * 100)}%" for r in z["rooms"])
        lines.append(f"  #{z['id']} {z['severity']:<4} {z['area_m2']:>5.1f} m2  worst {z['min_dbm']:>6.1f} dBm  ({rooms})")
    if not result["zones"]:
        lines.append("  none found")
    advice = result["suggestions"]
    if advice:
        lines += ["", f" Router placement (model estimate, error about {advice['router']['model_rmse_db']} dB):",
                  f"  now: about {advice['router']['baseline_pct']}% of the weighted floor area has OK signal"]
        for i, x in enumerate(advice["router"]["suggestions"], start=1):
            lines.append(f"  {i}. move to ({x['x']}, {x['y']}) in {x['room']}: about {x['expected_coverage_pct']}% "
                         f"({x['gain_pp']:+.1f} points)")
        e = advice["extender"]["suggestion"]
        if e:
            lines.append(f"  extender at ({e['x']}, {e['y']}) in {e['room']}: about {e['expected_coverage_pct']}% "
                         f"({e['gain_pp']:+.1f} points; it would hear the router at {e['hears_router_dbm']} dBm)")
        if advice["next_spots"]:
            lines.append("  measure next: " + "; ".join(f"({p['x']}, {p['y']}) {p['room']}" for p in advice["next_spots"]))
    for w in result["warnings"]:
        lines.append(f" ! {w}")
    lines.append(" Note: signal strength only (not speed); advice comes from a fitted model and is an estimate.")
    return "\n".join(lines)


# --------------------------------------------------------------------- SVG

def _halo_text(x: float, y: float, text: str, size: int, weight: int = 600) -> str:
    """Light text with a dark outline, drawn as two elements so every renderer agrees."""
    common = f'x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" text-anchor="middle"'
    return (f'<text {common} fill="none" stroke="#0b1320" stroke-width="3.2" stroke-linejoin="round">{text}</text>'
            f'<text {common} fill="#ffffff">{text}</text>')


def render_svg(plan: FloorPlan, result: dict, points: Sequence[Measurement], scale: float = 60.0,
               title: Optional[str] = None) -> str:
    """Standalone heatmap SVG with walls, rooms, router, measurements and advice."""
    mean = np.array(result["grid"]["mean"])
    ny, nx = mean.shape
    pad, head, foot = 24, 44, 58
    w, h = plan.width_m * scale, plan.height_m * scale
    total_w, total_h = w + 2 * pad, h + head + foot
    cw, ch = w / nx, h / ny
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.0f} {total_h:.0f}" width="{total_w:.0f}" '
           f'height="{total_h:.0f}" role="img" aria-label="Wi-Fi coverage heatmap of {escape(plan.name)}">',
           '<rect width="100%" height="100%" fill="#f4f6f8"/>',
           '<g font-family="Avenir Next,Segoe UI,system-ui,sans-serif">',
           f'<text x="{pad}" y="28" font-size="17" font-weight="700" fill="{INK}">{escape(title or plan.name)}</text>',
           f'<g transform="translate({pad},{head})">']
    step = 2.0                                        # colour quantisation in dB -> long merged runs
    for j in range(ny):
        i = 0
        while i < nx:
            q = round(mean[j, i] / step)
            k = i
            while k + 1 < nx and round(mean[j, k + 1] / step) == q:
                k += 1
            out.append(f'<rect x="{i * cw:.1f}" y="{j * ch:.1f}" width="{(k - i + 1) * cw + 0.4:.1f}" '
                       f'height="{ch + 0.4:.1f}" fill="{rssi_hex(q * step)}"/>')
            i = k + 1
    for wall in plan.walls:
        line = (f'x1="{wall.x1 * scale:.1f}" y1="{wall.y1 * scale:.1f}" x2="{wall.x2 * scale:.1f}" '
                f'y2="{wall.y2 * scale:.1f}" stroke-linecap="round"')
        out.append(f'<line {line} stroke="#ffffff" stroke-opacity="0.85" stroke-width="{WALL_STYLE[wall.kind] + 2.5}"/>')
        out.append(f'<line {line} stroke="{INK}" stroke-width="{WALL_STYLE[wall.kind]}"/>')
    for room in plan.rooms:
        out.append(_halo_text((room.x + room.w / 2) * scale, (room.y + 0.32) * scale, escape(room.name), 11))
    for m in points:
        out.append(f'<circle cx="{m.x * scale:.1f}" cy="{m.y * scale:.1f}" r="4.5" fill="#ffffff" '
                   f'stroke="{INK}" stroke-width="1.5"/>')
    for zone in result.get("zones", [])[:6]:
        label = f'{"dead" if zone["severity"] == "dead" else "weak"} #{zone["id"]}'
        out.append(_halo_text(zone["x"] * scale, zone["y"] * scale + 4, label, 12, 800))
    advice = result.get("suggestions")
    if advice:
        for i, item in enumerate(advice["router"]["suggestions"], start=1):
            out.append(f'<g transform="translate({item["x"] * scale:.1f},{item["y"] * scale:.1f})">'
                       f'<circle r="11" fill="#22d3a6" stroke="{INK}" stroke-width="2"/>'
                       f'<text y="4.5" font-size="13" font-weight="800" text-anchor="middle" fill="{INK}">{i}</text></g>')
    rx, ry = plan.router
    out.append(f'<g transform="translate({rx * scale:.1f},{ry * scale:.1f})"><rect x="-10" y="-10" width="20" height="20" '
               f'rx="4" fill="{INK}" stroke="#ffffff" stroke-width="2"/><text y="4.5" font-size="12" font-weight="800" '
               f'text-anchor="middle" fill="#ffffff">R</text></g>')
    out.append("</g>")
    ly = head + h + 22
    for i, dbm in enumerate(range(-90, -41, 4)):
        out.append(f'<rect x="{pad + i * 16}" y="{ly}" width="16" height="10" fill="{rssi_hex(dbm)}"/>')
    lx = pad + 13 * 16 + 8
    out.append(f'<text x="{pad}" y="{ly + 24}" font-size="11" fill="{INK}">-90 dBm (dead)</text>')
    out.append(f'<text x="{pad + 13 * 16}" y="{ly + 24}" font-size="11" text-anchor="end" fill="{INK}">-42 dBm (strong)</text>')
    cov = result["coverage"]
    out.append(f'<text x="{lx}" y="{ly + 9}" font-size="12" fill="{INK}">{result["n_points"]} measurements &#183; '
               f'OK signal on {cov["ok_pct"]:.0f}% of the weighted floor area &#183; dead on {cov["dead_pct"]:.0f}%</text>')
    out.append(f'<text x="{lx}" y="{ly + 26}" font-size="11" fill="#5b6b78">R router &#183; white dots measured spots &#183; '
               f'green 1-3 suggested router positions (model estimate)</text>')
    out.append("</g></svg>")
    return "\n".join(out)
