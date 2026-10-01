# Installation

Requires **Python 3.10+**. Developed and tested with Python 3.12 on Linux. No special hardware is needed for simulation.

```bash
git clone https://github.com/<your-username>/signalwalk.git
cd signalwalk
python3 -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m pytest                       # optional check
python -m signalwalk demo              # first run
```

Without an editable install (run from the repository root):

```bash
pip install -r requirements-dev.txt
PYTHONPATH=src python -m signalwalk demo        # PowerShell: $env:PYTHONPATH="src"
```

## Real Wi-Fi readings

- **Windows:** nothing extra. Uses `netsh wlan show interfaces`.
- **Linux:** reads `/proc/net/wireless`, then `nmcli` if installed.
- **macOS:** uses `system_profiler SPAirPortDataType`. May not work on newer versions.

Test with `python -m signalwalk check-reader` (connect to Wi-Fi first). All three are untested on real hardware by the author.

## Optional: dashboard smoke test

```bash
npm install jsdom                       # any scratch folder; node_modules is git-ignored
python -m signalwalk serve --simulate --port 8771 &
node scripts/dashboard_smoke.js http://127.0.0.1:8771
```
