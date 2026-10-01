# Project Pitch

How to present SignalWalk in a portfolio or interview. The wording describes what the project is *designed to do* and what has been *demonstrated on simulated data*. Edit the "my contribution" section to match what you personally did; nothing here invents experience for you.

## 30-second explanation

"SignalWalk is a Wi-Fi dead-zone mapper. You give it a simple floor plan, walk around with a laptop clicking where you stand, and it measures the signal. It fits a wall-aware model of how Wi-Fi fades, corrects it with what you actually measured, and draws a coverage map with dead zones, a report card per room, and advice on where to move the router. It also says where it is unsure, so it can tell you where to measure next. There is a simulation mode, so you can try it without any hardware."

## 1-minute explanation

"Most Wi-Fi heatmaps just blur between measured dots, which ignores walls and gives no idea how wrong they are. SignalWalk combines two ideas. First, a multi-wall path-loss model: signal falls with distance and by a fixed amount for each wall the straight line crosses. It is fitted as a regularised regression with sensible priors, so it works with few points. Second, a Gaussian process models whatever the physics misses, like furniture and doorways, and gives a confidence value everywhere.

From that it finds dead zones, grades each room, and scores candidate router positions by expected coverage, using the model's cross-validated error as the error bar. It also picks the spots where one more measurement would reduce doubt the most.

It runs entirely on simulated data so far: I built a virtual house whose physics deliberately differs from the model, and on that the hybrid map has about half the error of plain interpolation, and the router advice captured most of the possible gain. The real-Wi-Fi readers are tested against sample output but not on real hardware, so the next step is validating on real homes."

## Problem

Wi-Fi dead zones are common, invisible, and people guess router placement. Existing "heatmap" tools blur dots, ignore walls, and don't say how reliable the picture is.

## Solution

Floor plan + click-to-measure survey + physics-based model with a Gaussian-process correction + expected-coverage placement advice + uncertainty-driven "measure next", with leave-one-out error reporting.

## My technical contribution (edit to reflect your own work)

- Designed the model: bounded MAP regression for a multi-wall path-loss model, Matern-3/2 GP on residuals.
- Implemented vectorised wall-crossing geometry, dead-zone labelling, room grading, router / extender search, "measure next".
- Built a simulator whose ground truth differs from the estimator and an evaluation with oracle and no-survey baselines.
- Built OS signal readers with tested parsers, the FastAPI service, the canvas dashboard and the SVG / ASCII renderers.
- Wrote 82 automated tests and a headless dashboard smoke test.

## Main technologies

Python, NumPy (regression, Gaussian process, geometry), FastAPI, Pydantic, YAML, Canvas / vanilla JavaScript, SVG, pytest. Real readings via `netsh`, `nmcli`, `/proc/net/wireless`, `system_profiler` (untested on hardware).

## Interesting technical challenges

- **Walls without a physics engine.** The model needs "how many walls does the line from the router to this point cross?" for thousands of points and hundreds of candidate router positions. Segment-intersection tests are vectorised in NumPy, so one analysis (with CV and placement search) takes roughly 0.03-0.2 s for 20 points on the development machine (a single observation, not a benchmark).
- **Not trusting a good-looking number.** The first evaluation looked great, so I added a "just put it in the middle" baseline that needs no survey. The survey-based advice still won, but by a smaller margin in the simple apartment, and in the office it was sometimes wrong (3-10% of simulated homes). I kept those numbers in the docs.
- **Avoiding a circular test.** The simulator uses a different model from the estimator (two-slope loss, per-wall variation, hidden furniture, correlated shadowing).
- **Honest uncertainty for hypothetical placements.** Residuals measured for the old router position do not transfer, so advice uses the model only with its cross-validated error.

Be ready to say: results are on simulated data; thresholds and priors are my own; real readers are untested on hardware.

## Honest talking points

- "Multi-wall models, Gaussian processes and cross-validation are established; the combination and workflow are my design."
- "The advice is an estimate with an error bar, and in a few simulated homes it pointed the wrong way."
- "It measures signal strength, not throughput."

## Future development

Validate on real homes and against a commercial survey tool, add throughput measurement, floor-plan import, multi-AP and multi-floor support, a phone companion for surveying, learn GP hyperparameters from data.

## Likely interview questions

- *Why a Gaussian process on top of the model?* Physics extrapolates through walls; the GP corrects local misfit and gives a confidence value.
- *Why not just interpolate?* It ignores walls; measured error was about twice as high in simulation.
- *How do you know the advice is any good?* Only in simulation: scored against a true field, with oracle, random and no-survey baselines. Real validation is the next step.
- *What breaks it?* Roaming/mesh, band switching, wrong floor plan, interference, readings from a moving laptop.
