# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: signalwalk` | Not installed and `src/` not on the path | `pip install -e .` or `PYTHONPATH=src` |
| `Floor plan 'x' not found` | Wrong name or path | Use `apartment`, `office` or a path to a `.json` file |
| `INVALID: ... outside the plan` | A wall, room or router coordinate is beyond width/height | Fix the coordinates; run `validate-floorplan` |
| `INVALID: router sits on a wall` | Router exactly on a wall line | Move it 5 cm off the wall |
| `Config file not found` | `--config` path typo | Fix the path (it never falls back silently) |
| `check-reader`: "Cannot read /proc/net/wireless" | No Wi-Fi interface exposed (desktop, VM, container) | Run on a laptop with Wi-Fi |
| "does not report dBm in /proc/net/wireless" | Driver uses a 0-255 scale | Install NetworkManager (`nmcli`) |
| "Wi-Fi adapter is not connected" | Not connected | Connect to the network you want to map |
| "No 'Signal / Noise' line found" | macOS output differs or access is restricted | Not supported on all macOS versions; try Windows or Linux |
| Dashboard toast "Could not read Wi-Fi signal" | Adapter off or reader failing mid-survey | Run `check-reader`; retry |
| "Another measurement is still running" | Clicked twice quickly in real mode | Wait about 2 s |
| Heads-up: "connected to N different access points" | Device roamed (mesh / two routers) | Turn off the second AP, or survey one AP at a time |
| Map looks blotchy with few points | Under-sampled | Add points; use the dashed `?` suggestions |
| Dead zone appears where you measured fine signal | Position typed wrongly, or plan walls misplaced | Check the coordinates; delete the wrong point |
| Advice puts the router somewhere impossible | It is searching a grid | Add `router_candidates` (outlets) to the plan |
| Readings jump 5-10 dB between nearby spots | Laptop orientation, band switching, interference | Keep the laptop in the same pose; lock to one band; re-measure |
| Port in use | Another process on 8000 | `serve --port 8001` |
| Dashboard blank | Wrong directory | Run from the repo root or set `SIGNALWALK_APP_DIR` |
| `WARNING: listening on a non-local address` | You used `--host 0.0.0.0` | There is no authentication: use only on a trusted network |
