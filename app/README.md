# Dashboard (`app/`)

A no-build, dependency-free web UI served by the FastAPI app.

- `index.html`: page skeleton
- `static/style.css`: styling
- `static/app.js`: API calls, canvas heatmap, advice markers, side panels

How it works

- The floor plan is drawn on a `<canvas>`. The analysis grid (one value per 25 cm cell) is written into an
  offscreen `ImageData` and scaled up with smoothing, which gives the continuous heatmap.
- **Click** on the plan = `POST /api/measure` at that position. **Hover** shows the predicted dBm and its error bar.
- "Show confidence" overlays a pale veil where the Gaussian process is unsure.
- The colour palette is a copy of `PALETTE` in `src/signalwalk/render.py`; keep them in sync.
- Server text is inserted with `textContent` only. No external requests, so it works offline.

Status: **prototype**. Checked by a headless jsdom smoke test (`scripts/dashboard_smoke.js`, canvas stubbed, 22 checks).
Not verified visually in a real browser, on phones, or with assistive technology.
