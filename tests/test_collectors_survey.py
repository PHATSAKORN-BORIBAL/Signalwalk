import pytest

from signalwalk.collectors import (CommandReader, FallbackReader, ProcWirelessReader, Reading, SignalReadError,
                                   ap_tag, detect_reader, parse_macos, parse_netsh, parse_nmcli,
                                   parse_proc_net_wireless, pct_to_dbm, take_spot_measurement)
from signalwalk.floorplan import floorplan_from_dict
from signalwalk.survey import Measurement, Survey, SurveyError

# Sample text written from the tools' documented formats (NOT captured from real hardware).
NETSH = """
    Name                   : Wi-Fi
    Description            : Example Wireless Adapter
    State                  : connected
    SSID                   : HomeNet
    BSSID                  : aa:bb:cc:dd:ee:ff
    Radio type             : 802.11ax
    Band                   : 5 GHz
    Signal                 : 84%
    Profile                : HomeNet
"""
NETSH_DOWN = "    Name : Wi-Fi\n    State                  : disconnected\n"
NMCLI = "  :40:aa\\:bb\\:cc\\:00\\:00\\:01\n*:78:aa\\:bb\\:cc\\:dd\\:ee\\:ff\n"
PROC = ("Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n"
        " face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n"
        "wlan0: 0000   60.  -52.  -256        0      0      0      0      0        0\n")
PROC_NO_DBM = PROC.replace("-52.", " 180.")
MACOS = "      Current Network Information:\n        HomeNet:\n          BSSID: aa:bb:cc:dd:ee:ff\n          Signal / Noise: -61 dBm / -92 dBm\n"


def test_percent_conversion():
    assert pct_to_dbm(100) == -50 and pct_to_dbm(0) == -100 and pct_to_dbm(84) == -58 and pct_to_dbm(150) == -50


def test_parsers_extract_signal_and_hash_the_bssid():
    r = parse_netsh(NETSH)
    assert r.dbm == -58 and len(r.ap_tag) == 6 and "aabb" not in r.ap_tag
    assert parse_nmcli(NMCLI).dbm == -61 and parse_nmcli(NMCLI).ap_tag is not None
    assert parse_proc_net_wireless(PROC) == Reading(-52.0, None)
    assert parse_macos(MACOS).dbm == -61
    assert ap_tag("AA:BB:CC:DD:EE:FF") == ap_tag("aa:bb:cc:dd:ee:ff") and ap_tag(None) is None


@pytest.mark.parametrize("fn,text", [(parse_netsh, NETSH_DOWN), (parse_netsh, "garbage"), (parse_nmcli, "no star here\n"),
                                     (parse_proc_net_wireless, "a\nb\n"), (parse_proc_net_wireless, PROC_NO_DBM),
                                     (parse_macos, "nothing")])
def test_parsers_raise_clean_errors(fn, text):
    with pytest.raises(SignalReadError):
        fn(text)


def test_command_reader_handles_missing_tool_and_bad_exit():
    with pytest.raises(SignalReadError, match="not installed"):
        CommandReader("x", ["definitely-not-a-real-command-xyz"], parse_netsh).read()
    with pytest.raises(SignalReadError, match="failed"):
        CommandReader("x", ["python3", "-c", "import sys; sys.exit(3)"], parse_netsh).read()
    assert CommandReader("x", ["python3", "-c", f"print({NETSH!r})"], parse_netsh).read().dbm == -58


def test_proc_reader_and_fallback(tmp_path):
    f = tmp_path / "wireless"
    f.write_text(PROC)
    assert ProcWirelessReader(str(f)).read().dbm == -52
    with pytest.raises(SignalReadError, match="Cannot read"):
        ProcWirelessReader(str(tmp_path / "missing")).read()
    chain = FallbackReader([ProcWirelessReader(str(tmp_path / "missing")), ProcWirelessReader(str(f))])
    assert chain.read().dbm == -52
    with pytest.raises(SignalReadError):
        FallbackReader([ProcWirelessReader(str(tmp_path / "a")), ProcWirelessReader(str(tmp_path / "b"))]).read()


def test_detect_reader_by_platform():
    assert detect_reader("Windows").name == "windows:netsh" and detect_reader("Darwin").name.startswith("macos")
    assert "nmcli" in detect_reader("Linux", which=lambda n: "/usr/bin/nmcli").name
    assert "nmcli" not in detect_reader("Linux", which=lambda n: None).name
    with pytest.raises(SignalReadError, match="Unsupported"):
        detect_reader("Plan9")


class FakeReader:
    name = "fake"

    def __init__(self, seq):
        self.seq = list(seq)

    def read(self):
        item = self.seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_spot_measurement_takes_the_median_and_survives_failures():
    seq = [Reading(-60, "aaaaaa"), Reading(-61, "aaaaaa"), SignalReadError("blip"), Reading(-40, "aaaaaa"), Reading(-62, "aaaaaa")]
    spot = take_spot_measurement(FakeReader(seq), 5, 0, sleep=lambda s: None)
    assert spot.dbm == -60.5 and spot.n_readings == 4 and spot.spread_db == 22 and not spot.roamed
    with pytest.raises(SignalReadError, match="down"):
        take_spot_measurement(FakeReader([SignalReadError("down")] * 3 + [Reading(-50)]), 4, 0, sleep=lambda s: None)
    roam = take_spot_measurement(FakeReader([Reading(-50, "aaaaaa"), Reading(-51, "bbbbbb"), Reading(-50, "aaaaaa")]), 3, 0, sleep=lambda s: None)
    assert roam.roamed and roam.ap_tag == "aaaaaa"


# --------------------------------------------------------------------- survey

@pytest.fixture()
def survey():
    plan = floorplan_from_dict({"name": "t", "width_m": 10, "height_m": 6, "router": {"x": 1, "y": 3}})
    return Survey(plan)


def test_measurement_validation(survey):
    survey.add(Measurement(1, 1, -50))
    for bad in (Measurement(11, 1, -50), Measurement(1, 7, -50), Measurement(1, 1, -5), Measurement(1, 1, -120),
                Measurement(float("nan"), 1, -50), Measurement(1, 1, float("inf"))):
        with pytest.raises(SurveyError):
            survey.add(bad)
    assert len(survey) == 1


def test_add_remove_clear_bump_version(survey):
    v0 = survey.version
    survey.add(Measurement(1, 1, -50)); survey.add(Measurement(2, 2, -60))
    assert survey.remove(0).rssi_dbm == -50 and len(survey) == 1 and survey.version == v0 + 3
    with pytest.raises(SurveyError):
        survey.remove(5)
    survey.clear()
    assert len(survey) == 0


def test_json_and_csv_round_trip(survey, tmp_path):
    survey.add(Measurement(1.5, 2.5, -55.5, 5, 2.0, None, "real", "abc123")); survey.add(Measurement(4, 4, -71))
    survey.save_json(tmp_path / "s.json")
    other = Survey(survey.plan)
    other.load(tmp_path / "s.json")
    assert other.measurements == survey.measurements
    (tmp_path / "s.csv").write_text(survey.to_csv())
    third = Survey(survey.plan)
    third.load(tmp_path / "s.csv")
    assert [(m.x, m.y, m.rssi_dbm) for m in third.measurements] == [(1.5, 2.5, -55.5), (4.0, 4.0, -71.0)]
    assert "abc123" not in survey.to_csv()          # access-point tags are not exported


def test_survey_file_errors(survey, tmp_path):
    with pytest.raises(SurveyError, match="not found"):
        survey.load(tmp_path / "none.json")
    (tmp_path / "bad.json").write_text("{oops")
    with pytest.raises(SurveyError, match="Cannot read"):
        survey.load(tmp_path / "bad.json")
    (tmp_path / "bad.csv").write_text("a,b\n1,2\n")
    with pytest.raises(SurveyError, match="needs columns"):
        survey.load(tmp_path / "bad.csv")
    (tmp_path / "bad2.csv").write_text("x_m,y_m,rssi_dbm\n1,1,abc\n")
    with pytest.raises(SurveyError, match="line 2"):
        survey.load(tmp_path / "bad2.csv")
    (tmp_path / "out.csv").write_text("x_m,y_m,rssi_dbm\n99,1,-50\n")
    with pytest.raises(SurveyError, match="outside"):
        survey.load(tmp_path / "out.csv")
