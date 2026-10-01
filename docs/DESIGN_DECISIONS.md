# Design Decisions

"Established" = a well-known technique. "Proposed" = my own design choice, not validated on real buildings.

## Established building blocks

- **Multi-wall path-loss models:** signal falls with log-distance and by a fixed amount per wall crossed.
- **Gaussian-process regression** with a Matern kernel for spatial interpolation (kriging-style).
- **MAP / ridge regression** (Gaussian priors on parameters) and **leave-one-out cross-validation.**
- **RSSI measured by the OS** on a normal laptop.

## Proposed design

### 1. Physics first, data second (hybrid map)
Pure interpolation of dots (the usual "heatmap") ignores walls, so a room behind a wall inherits its neighbour's
signal. The model gives structure; the Gaussian process fixes what the model misses near measurements and
returns an uncertainty. Measured effect (simulated): hybrid error is about half that of plain interpolation and
0.3-1.0 dB better than the model alone ([EVALUATION.md](EVALUATION.md)).

### 2. MAP regression with priors and bounds
The model is linear in `(A, n, w_light, w_interior, w_heavy)`, so fitting is a small regularised least squares.
Priors (A = -40 dBm, n = 2.8, walls 3 / 6 / 12 dB) keep the fit sane with few points; **wall kinds that no
measurement crosses keep their prior** instead of becoming nonsense. Bounds (n in [1.5, 5], wall loss in [0, 25] dB)
are enforced by repeatedly fixing the worst violator. *Cost:* the priors are mine, and a wall kind seen only a few
times is mostly prior.

### 3. Floor plan as a small JSON file
Counting walls crossed needs geometry. Asking for a hand-written JSON plan keeps the code simple and testable.
*Cost:* the user must measure and write the plan; position errors degrade the fit. (Future: import from a drawing.)

### 4. Placement uses the model only, with an honest error bar
When the router moves, the geometry changes and residuals measured for the old position do not transfer
reliably. So hypothetical placements use the path-loss model alone, with a Gaussian error equal to the
**leave-one-out RMSE of the model** (never below 2 dB, 6 dB if there are too few points to cross-validate). Each
candidate is scored by *expected coverage*: the room-weighted share of floor with P(signal >= -70 dBm).
*Cost:* assumes the new router radiates like the old one and ignores interference and antenna patterns.

### 5. Extender = second source that must hear the first
An extender is scored with `1 - (1 - P_router)(1 - P_extender)` per cell (treating the two as independent) and is
only allowed where the router's *measured map* says the signal is at least -65 dBm. *Cost:* independence is an
approximation; the extender is assumed to radiate like the router.

### 6. "Measure next" from uncertainty
Score = `min(P, 1 - P) x std`, where P = P(signal < -70 dBm): high where the map cannot tell weak from OK. Spots
are spread at least 2 m apart and kept 0.4 m off walls. This is a simple form of active learning.

### 7. Median of five readings; roaming detection without storing MACs
A single reading is noisy; the median of 5 resists an odd sample. The access point's address is hashed to a
6-character tag only to notice that the device roamed mid-survey. SSIDs and MACs are never stored.

### 8. Signal strength, not throughput
RSSI is easy to read on any laptop with no extra server. It is a proxy: good signal does not guarantee speed.
The thresholds (-55 / -70 / -80 dBm) are rule-of-thumb values and configurable.

### 9. A simulator that is not the estimator
The ground-truth world uses a different model (two-slope loss, per-wall random loss, hidden obstacles, correlated
shadowing), so the evaluation checks robustness to model mismatch. A "centre of the plan" baseline was added to
check that the survey beats a no-survey rule. It is still my own simulator.

### 10. NumPy only
The regression, Gaussian process, normal CDF (Abramowitz-Stegun erf approximation, error < 1.5e-7) and connected
components are a few dozen lines each. That keeps installation to four small packages and every step readable.

### 11. Colour palette dark = dead
A magma-like ramp (dark for dead, bright for strong) makes dead zones stand out and stays readable for most
colour-vision types. The same palette is used by the SVG renderer and the dashboard.

### 12. Local-only, no authentication
It is a single-user tool that can run OS commands, so it binds to `127.0.0.1` and warns otherwise.

## Alternatives considered

- **Image-based floor plan import / computer vision:** too much scope; a JSON plan is enough to demonstrate the idea.
- **Ray tracing:** more physical, much more code, needs wall materials I cannot know.
- **Learning a neural network on measurements:** no real data; less explainable.
- **Ping/throughput measurement:** needs a known server; left as a future extension.
