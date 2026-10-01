import json
import xml.dom.minidom


from conftest import survey_for
from signalwalk.analysis import analyze
from signalwalk.cli import main, resolve_floorplan
from signalwalk.evaluation import evaluate
from signalwalk.floorplan import FloorPlanError
from signalwalk.render import ascii_map, render_svg, rssi_hex, text_report


def test_demo_prints_full_report_and_writes_files(tmp_path, capsys):
    svg, csv = tmp_path / "m.svg", tmp_path / "s.csv"
    assert main(["demo", "--points", "18", "--svg", str(svg), "--survey-out", str(csv)]) == 0
    out = capsys.readouterr().out
    for needle in ("SIMULATED", "Room report card", "Weak / dead zones", "Router placement", "Leave-one-out", "Legend:"):
        assert needle in out
    xml.dom.minidom.parseString(svg.read_text(encoding="utf-8"))
    assert svg.stat().st_size < 90_000 and len(csv.read_text().strip().splitlines()) == 19


def test_analyze_command_round_trip(tmp_path, capsys):
    csv = tmp_path / "s.csv"
    main(["demo", "--points", "16", "--survey-out", str(csv)])
    capsys.readouterr()
    js = tmp_path / "a.json"
    assert main(["analyze", str(csv), "--floorplan", "apartment", "--json", str(js)]) == 0
    assert "16 measurement(s)" in capsys.readouterr().out
    assert json.loads(js.read_text())["n_points"] == 16


def test_cli_errors_are_clean(tmp_path, capsys):
    assert main(["demo", "--floorplan", "no-such-plan"]) == 2 and "not found" in capsys.readouterr().err
    assert main(["analyze", str(tmp_path / "nope.csv")]) == 2 and "Error" in capsys.readouterr().err
    assert main(["--config", "/nope.yaml", "demo"]) == 2
    assert main(["validate-floorplan", str(tmp_path / "x.json")]) == 1
    good = "examples/floorplans/office.json"
    assert main(["validate-floorplan", good]) == 0 and "8 rooms" in capsys.readouterr().out


def test_check_reader_reports_failure_without_crashing(capsys, monkeypatch):
    from signalwalk import cli
    from signalwalk.collectors import SignalReadError

    class Broken:
        name = "broken"

        def read(self):
            raise SignalReadError("no adapter")

    monkeypatch.setattr(cli, "detect_reader", lambda: Broken())
    assert main(["check-reader"]) == 1
    assert "no adapter" in capsys.readouterr().err


def test_interactive_survey_with_fake_reader(tmp_path, monkeypatch, capsys):
    from signalwalk import cli
    from signalwalk.collectors import Reading

    class Fixed:
        name = "fixed"
        n = 0

        def read(self):
            Fixed.n += 1
            return Reading(-50.0 - Fixed.n % 3, "aaaaaa")

    monkeypatch.setattr(cli, "detect_reader", lambda: Fixed())
    monkeypatch.setattr("signalwalk.collectors.time.sleep", lambda s: None)
    script = iter(["2 2", "5, 2", "99 99", "abc", "8 3", "u", "3 6", "r", "q"])
    settings = cli.load_settings()
    args = cli.build_parser().parse_args(["survey", "--floorplan", "apartment", "--out", str(tmp_path / "s.json"), "--fresh"])
    assert cli.cmd_survey(args, settings, input_fn=lambda prompt: next(script)) == 0
    out = capsys.readouterr().out
    assert "outside the 12 x 8 m plan" in out            # 99 99 rejected
    assert "removed last measurement" in out              # u
    assert "SignalWalk report" in out                     # r, with exactly 3 points left
    assert "spread" in out
    saved = json.loads((tmp_path / "s.json").read_text())
    assert len(saved["measurements"]) == 3 and all("ap_tag" in m for m in saved["measurements"])


def test_resolve_floorplan_by_name_and_path():
    assert resolve_floorplan("office").name.startswith("Small office")
    assert resolve_floorplan("examples/floorplans/apartment.json").width_m == 12.0
    try:
        resolve_floorplan("missing")
        raise AssertionError("expected FloorPlanError")
    except FloorPlanError:
        pass


def test_svg_and_ascii_renderers(apartment, settings):
    _, meas = survey_for(apartment)
    res = analyze(apartment, meas, settings)
    svg = render_svg(apartment, res, meas)
    xml.dom.minidom.parseString(svg)
    assert "Living room" in svg and svg.count("<circle") >= len(meas)
    art = ascii_map(apartment, res, meas)
    lines = art.splitlines()
    assert len({len(line) for line in lines}) == 1 and "R" in art and "█" in art and "1" in art
    assert "Router placement" in text_report(apartment, res, meas)


def test_svg_escapes_hostile_names(apartment, settings):
    import dataclasses
    _, meas = survey_for(apartment)
    evil = dataclasses.replace(apartment, name="<script>alert(1)</script> & co",
                               rooms=(dataclasses.replace(apartment.rooms[0], name="<b>x</b>"),) + apartment.rooms[1:])
    svg = render_svg(evil, analyze(evil, meas, settings), meas)
    assert "<script>" not in svg and "<b>" not in svg
    xml.dom.minidom.parseString(svg)


def test_palette_is_monotonic_in_brightness():
    def lum(h):
        r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    values = [lum(rssi_hex(d)) for d in range(-95, -41, 3)]
    assert all(b >= a - 1 for a, b in zip(values, values[1:]))
    assert rssi_hex(-200) == rssi_hex(-95) and rssi_hex(0) == rssi_hex(-42)


def test_small_evaluation_runs_and_reports(apartment, settings):
    rep = evaluate(settings, [apartment], worlds=2, point_counts=(12,))
    row = rep.rows[0]
    assert row.rmse_hybrid < row.rmse_idw and 0 <= row.weak_iou <= 1
    md = rep.to_markdown()
    assert "Centre-of-plan" in md and "Best possible" in md
