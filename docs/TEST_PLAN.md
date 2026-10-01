# Test Plan

All automated tests use simulated or hand-written data. Nothing was tested on real Wi-Fi hardware.

```bash
python -m pytest                                          # 82 tests, about 8 s
python -m signalwalk evaluate                             # synthetic evaluation
node scripts/dashboard_smoke.js http://127.0.0.1:8000     # optional, dev-only (needs jsdom)
```

## Automated tests

| File | Focus |
|---|---|
| `test_config.py` | defaults, env overrides, invalid values, unknown keys, missing explicit config file, `.env` parsing |
| `test_floorplan.py` | wall-crossing geometry and doorway gaps, per-kind counts, room lookup and weights, nine invalid-plan cases, candidate clearance, shipped plans valid |
| `test_model_estimator.py` | recovery of known parameters from synthetic data, priors for unseen wall kinds, bound enforcement, GP behaviour and uncertainty, cross-validation beats interpolation |
| `test_zones_placement.py` | normal CDF values, component labelling, zone filtering and severity, room grades, expected coverage, router advice improves and spreads, extender backhaul rule, "measure next", analysis output shape and warnings, roaming warning |
| `test_collectors_survey.py` | parsers for netsh / nmcli / `/proc/net/wireless` / macOS sample text, clean errors on bad input, BSSID hashing, command runner failure modes, fallback chain, platform detection, median-of-N with failures and roaming, survey validation, JSON/CSV round trips and errors |
| `test_simulator.py` | determinism, distance and wall effects, router move changes the field, noise statistics, survey points cover rooms and avoid walls |
| `test_api.py` | health, state, headers, measure flow, validation (422), delete / reset / auto-survey, analysis caching, exports, real mode with a fake reader (success, 503, 409), busy session |
| `test_cli_render_eval.py` | demo output and files, analyze round trip, clean CLI errors, check-reader failure, scripted interactive survey, SVG/ASCII renderers, XML escaping, palette monotonic, small evaluation |

## Dashboard smoke test

`scripts/dashboard_smoke.js` loads the real page from a running simulate-mode server in jsdom (canvas stubbed) and
checks 22 behaviours: plan name and badge, empty state, auto-survey, coverage bar, advice, room report, click to
measure, hover tooltip, delete, undo, reset, out-of-plan error toast and no JS errors. It does **not** check how
anything looks.

## Manual checklist

- [ ] `python -m signalwalk demo` prints a report with a map, zones and advice.
- [ ] `serve --simulate`: click on the plan, heatmap changes; "Show confidence" dims far-from-data areas.
- [ ] `check-reader` on your computer prints a dBm value (real hardware, untested by the author).
- [ ] `serve --real`: measuring takes about 2 s and the value looks plausible.
- [ ] Moving the router and re-surveying a few spots improves the numbers the tool predicted (the real test).

## Not covered

- Real Wi-Fi hardware, real homes, real browsers, phones, assistive technology.
- Windows and macOS readers beyond parsing sample text.
- Load or soak testing; security testing beyond the unit tests.
- Coverage was not measured with a tool.
