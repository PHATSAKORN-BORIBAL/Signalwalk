"""Read the laptop's own Wi-Fi signal strength.

Only the signal strength (and a short hash of the access-point address, to detect
roaming) is kept. SSIDs and MAC addresses are never stored.

STATUS: the Linux /proc/net/wireless, nmcli, Windows netsh and macOS parsers are
unit-tested against sample text written from the tools' documented formats. They
have NOT been run against real Wi-Fi hardware by the author.
"""

from __future__ import annotations

import hashlib
import math
import platform
import re
import shutil
import statistics
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional, Sequence


class SignalReadError(RuntimeError):
    """The signal strength could not be read (not connected, tool missing, ...)."""


@dataclass(frozen=True)
class Reading:
    dbm: float
    ap_tag: Optional[str] = None


def pct_to_dbm(pct: float) -> float:
    """Common quality-percent -> dBm approximation: dBm = pct/2 - 100."""
    return max(0.0, min(100.0, pct)) / 2.0 - 100.0


def ap_tag(bssid: Optional[str]) -> Optional[str]:
    """Short one-way tag so roaming can be detected without keeping the MAC."""
    if not bssid:
        return None
    return hashlib.sha256(bssid.strip().lower().encode()).hexdigest()[:6]


# ------------------------------------------------------------------ parsers

def parse_netsh(text: str) -> Reading:
    """Windows: ``netsh wlan show interfaces``."""
    fields = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields.setdefault(key.strip().lower(), value.strip())
    if fields.get("state", "").lower() != "connected":
        raise SignalReadError("Wi-Fi adapter is not connected to a network")
    m = re.match(r"(\d+)\s*%", fields.get("signal", ""))
    if not m:
        raise SignalReadError("No 'Signal' percentage found in netsh output")
    return Reading(pct_to_dbm(float(m.group(1))), ap_tag(fields.get("bssid")))


def parse_nmcli(text: str) -> Reading:
    """Linux NetworkManager: ``nmcli -t -f IN-USE,SIGNAL,BSSID dev wifi``."""
    for line in text.splitlines():
        if line.startswith("*"):
            parts = re.split(r"(?<!\\):", line)
            try:
                pct = float(parts[1])
            except (IndexError, ValueError) as exc:
                raise SignalReadError("Could not parse nmcli signal column") from exc
            bssid = parts[2].replace("\\:", ":") if len(parts) > 2 else None
            return Reading(pct_to_dbm(pct), ap_tag(bssid))
    raise SignalReadError("nmcli lists no connected network (no '*' row)")


def parse_proc_net_wireless(text: str, iface: Optional[str] = None) -> Reading:
    """Linux: ``/proc/net/wireless`` (level column is dBm)."""
    for line in text.splitlines()[2:]:
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        cols = rest.split()
        if iface and name.strip() != iface:
            continue
        try:
            level = float(cols[2].rstrip("."))
        except (IndexError, ValueError):
            continue
        if level >= 0:      # some drivers report 0 or a 0-255 scale; do not guess
            raise SignalReadError(f"{name.strip()} does not report dBm in /proc/net/wireless")
        return Reading(level, None)
    raise SignalReadError("No wireless interface found in /proc/net/wireless")


def parse_macos(text: str) -> Reading:
    """macOS: ``system_profiler SPAirPortDataType`` ('Signal / Noise: -55 dBm / -90 dBm')."""
    m = re.search(r"Signal\s*/\s*Noise:\s*(-?\d+)\s*dBm", text)
    if not m:
        raise SignalReadError("No 'Signal / Noise' line found (are you connected to Wi-Fi?)")
    bssid = re.search(r"BSSID:\s*([0-9A-Fa-f:]{17})", text)
    return Reading(float(m.group(1)), ap_tag(bssid.group(1) if bssid else None))


# ------------------------------------------------------------------ readers

class SignalReader(ABC):
    name = "reader"

    @abstractmethod
    def read(self) -> Reading:
        """Return one reading or raise ``SignalReadError``."""


class CommandReader(SignalReader):
    """Runs a fixed command (no shell, no user input) and parses its output."""

    def __init__(self, name: str, command: Sequence[str], parser: Callable[[str], Reading],
                 timeout_s: float = 10.0):
        self.name, self.command, self.parser, self.timeout_s = name, list(command), parser, timeout_s

    def read(self) -> Reading:
        try:
            done = subprocess.run(self.command, capture_output=True, text=True,
                                  timeout=self.timeout_s, check=False)
        except FileNotFoundError as exc:
            raise SignalReadError(f"'{self.command[0]}' is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise SignalReadError(f"'{self.command[0]}' timed out") from exc
        if done.returncode != 0:
            raise SignalReadError(f"'{self.command[0]}' failed: {(done.stderr or done.stdout).strip()[:120]}")
        return self.parser(done.stdout)


class ProcWirelessReader(SignalReader):
    name = "linux:/proc/net/wireless"

    def __init__(self, path: str = "/proc/net/wireless"):
        self.path = path

    def read(self) -> Reading:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return parse_proc_net_wireless(fh.read())
        except OSError as exc:
            raise SignalReadError(f"Cannot read {self.path}: {exc}") from exc


class FallbackReader(SignalReader):
    """Try several readers in order; use the first that works."""

    def __init__(self, readers: Sequence[SignalReader]):
        self.readers = list(readers)
        self.name = "+".join(r.name for r in self.readers)

    def read(self) -> Reading:
        errors = []
        for reader in self.readers:
            try:
                return reader.read()
            except SignalReadError as exc:
                errors.append(f"{reader.name}: {exc}")
        raise SignalReadError("; ".join(errors))


def detect_reader(system: Optional[str] = None,
                  which: Callable[[str], Optional[str]] = shutil.which) -> SignalReader:
    system = system or platform.system()
    if system == "Windows":
        return CommandReader("windows:netsh", ["netsh", "wlan", "show", "interfaces"], parse_netsh)
    if system == "Darwin":
        return CommandReader("macos:system_profiler", ["system_profiler", "SPAirPortDataType"],
                             parse_macos, timeout_s=20.0)
    if system == "Linux":
        readers: list[SignalReader] = [ProcWirelessReader()]
        if which("nmcli"):
            readers.append(CommandReader("linux:nmcli", ["nmcli", "-t", "-f", "IN-USE,SIGNAL,BSSID",
                                                         "dev", "wifi"], parse_nmcli))
        return FallbackReader(readers)
    raise SignalReadError(f"Unsupported operating system: {system}")


@dataclass(frozen=True)
class SpotResult:
    dbm: float
    spread_db: float
    n_readings: int
    ap_tag: Optional[str]
    roamed: bool


def take_spot_measurement(reader: SignalReader, n: int, interval_s: float,
                          sleep: Callable[[float], None] = time.sleep) -> SpotResult:
    """Take ``n`` readings and return their median (robust to a single odd sample)."""
    readings: list[Reading] = []
    last_error: Optional[SignalReadError] = None
    for i in range(n):
        try:
            readings.append(reader.read())
        except SignalReadError as exc:
            last_error = exc
        if i < n - 1:
            sleep(interval_s)
    if len(readings) < max(1, math.ceil(n / 2)):
        raise SignalReadError(str(last_error) if last_error else "Not enough valid readings")
    values = [r.dbm for r in readings]
    tags = [r.ap_tag for r in readings if r.ap_tag]
    majority = max(set(tags), key=tags.count) if tags else None
    return SpotResult(float(statistics.median(values)), float(max(values) - min(values)),
                      len(values), majority, len(set(tags)) > 1)
