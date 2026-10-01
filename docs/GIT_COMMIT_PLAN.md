# Git Commit Plan

A clean history that tells the story of the build (subjects of 50 characters or fewer):

| # | Commit message | Files |
|---|---|---|
| 1 | `Initial project structure` | `LICENSE`, `.gitignore`, `.env.example`, `pyproject.toml`, `requirements*.txt` |
| 2 | `Add config loader and defaults` | `config/default.yaml`, `config.py`, `tests/test_config.py` |
| 3 | `Add floor plan geometry` | `floorplan.py`, `examples/floorplans/`, `tests/test_floorplan.py` |
| 4 | `Add survey model and CSV/JSON I/O` | `survey.py` |
| 5 | `Add Wi-Fi readers and parsers` | `collectors.py`, `tests/test_collectors_survey.py` |
| 6 | `Add multi-wall path-loss model` | `propagation.py` |
| 7 | `Add Gaussian-process estimator and CV` | `estimator.py`, `tests/test_model_estimator.py` |
| 8 | `Add dead zones and placement advice` | `deadzones.py`, `placement.py`, `analysis.py`, `tests/test_zones_placement.py` |
| 9 | `Add simulated house` | `simulator.py`, `tests/conftest.py`, `tests/test_simulator.py` |
| 10 | `Add session service and API` | `service.py`, `api.py`, `tests/test_api.py` |
| 11 | `Add ASCII and SVG renderers` | `render.py`, `docs/assets/` |
| 12 | `Add CLI` | `cli.py`, `__main__.py` |
| 13 | `Add click-to-measure dashboard` | `app/` |
| 14 | `Add synthetic evaluation` | `evaluation.py`, `tests/test_cli_render_eval.py` |
| 15 | `Add examples and smoke test` | `examples/surveys/`, `scripts/dashboard_smoke.js` |
| 16 | `Add documentation` | `docs/*.md`, `SECURITY.md`, `CONTRIBUTING.md` |
| 17 | `Write README` | `README.md` |

Single-commit alternative:

```
Add SignalWalk: Wi-Fi dead-zone mapper
```

Tips: run `python -m pytest` before commits that add code; never commit your own surveys (`survey.json` is git-ignored); tag the first release with `git tag v0.1.0`.
