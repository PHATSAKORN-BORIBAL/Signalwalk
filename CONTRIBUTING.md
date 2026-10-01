# Contributing

Small, readable codebase. Keep it that way.

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
```

Ground rules

- `python -m pytest` must stay green; add a test for every behaviour change.
- **Honest claims.** Anything measured only on simulated data must say so.
- **Tested parsers only.** A new OS reader needs a parser with a sample-output test, and must be
  labelled "not tested on hardware" until someone runs it on real hardware.
- **Model changes need evidence.** Re-run `python -m signalwalk evaluate` and paste the tables in your PR.
- **No personal data.** Do not commit real surveys or floor plans of private homes.
- New floor plans: `python -m signalwalk validate-floorplan yourfile.json`.

Commit subjects: imperative, 50 characters or fewer (see `docs/GIT_COMMIT_PLAN.md`).
