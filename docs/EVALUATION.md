# Evaluation (simulation only)

## What this is, and what it is not

`python -m signalwalk evaluate` builds many random **virtual** homes from the two example plans, surveys each with
a sensible walk, runs the whole pipeline, and compares the result with the simulator's *true* signal field.

The simulator (`src/signalwalk/simulator.py`) deliberately uses a **different propagation model** from the estimator:
two-slope path loss, a separate random loss for every wall, hidden furniture that is not in the floor plan, and
spatially correlated shadowing. So the estimator is not simply recovering its own equations. But:

* **It is still my own simulator**, not a real building, and I chose its parameter ranges.
* The thresholds (-70 / -80 dBm), priors and Gaussian-process settings were chosen by me, and the model structure
  was developed while looking at this simulator.
* **Nothing here says how accurate SignalWalk would be in a real home.**

## Method

* 30 random worlds per plan (seeds 1000-1029), survey sizes 10, 20 and 30 spots, 5 readings per spot (median, whole dBm).
* **Map error:** RMSE in dB over the 25 cm grid against the noise-free true field. Compared: the hybrid map, the
  path-loss model alone, and plain inverse-distance interpolation.
* **Weak-zone IoU:** overlap of predicted vs true "signal below -70 dBm" cells (1.0 = identical).
* **Router advice:** for every allowed candidate position the *true* world is recomputed (new router position, new
  shadowing draw). We report the true share of weighted area with OK signal (>= -70 dBm) before moving, after
  moving to advice #1, for the best candidate (oracle, which uses the truth), for a random candidate, and for a
  "centre of the plan" rule that needs no survey.
* **Extender advice:** true coverage when the advised extender is added (it must hear the router at >= -65 dBm in the
  true world, otherwise no gain counts) vs the best possible extender.

Command: `python -m signalwalk evaluate --worlds 30 --seed 1000` (about 25 s on the development sandbox, one run).

## Results (measured)

### Map accuracy (lower RMSE is better; truth = simulated field)
| Plan | Points | Worlds | Hybrid RMSE | Model-only RMSE | Plain interpolation RMSE | Weak-zone IoU |
|---|---:|---:|---:|---:|---:|---:|
| Two-bedroom apartment | 10 | 30 | 3.29 dB | 3.65 dB | 6.64 dB | 0.73 |
| Two-bedroom apartment | 20 | 30 | 2.61 dB | 3.36 dB | 5.31 dB | 0.77 |
| Two-bedroom apartment | 30 | 30 | 2.27 dB | 3.23 dB | 4.79 dB | 0.80 |
| Small office with lift core | 10 | 30 | 3.81 dB | 4.08 dB | 9.15 dB | 0.93 |
| Small office with lift core | 20 | 30 | 2.99 dB | 3.63 dB | 6.96 dB | 0.93 |
| Small office with lift core | 30 | 30 | 2.61 dB | 3.48 dB | 6.03 dB | 0.93 |

### Router advice, scored in the TRUE simulated world (share of weighted area with OK signal)
| Plan | Points | Before | After advice (#1) | Centre-of-plan rule (no survey) | Best possible (oracle) | Random candidate | Share of possible gain captured | Advice made it worse (>1 pt) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Two-bedroom apartment | 10 | 70.5% | 90.0% | 85.8% | 91.1% | 74.5% | 94% | 0% |
| Two-bedroom apartment | 20 | 70.5% | 90.3% | 85.8% | 91.1% | 74.5% | 95% | 0% |
| Two-bedroom apartment | 30 | 70.5% | 90.3% | 85.8% | 91.1% | 74.5% | 95% | 0% |
| Small office with lift core | 10 | 52.6% | 72.0% | 50.2% | 80.1% | 55.8% | 69% | 10% |
| Small office with lift core | 20 | 52.6% | 71.7% | 50.2% | 80.1% | 55.8% | 69% | 3% |
| Small office with lift core | 30 | 52.6% | 72.1% | 50.2% | 80.1% | 55.8% | 70% | 3% |

### Extender advice, scored in the TRUE simulated world
| Plan | Points | Router only | With advised extender | Best possible extender |
|---|---:|---:|---:|---:|
| Two-bedroom apartment | 10 | 70.5% | 89.8% | 94.3% |
| Two-bedroom apartment | 20 | 70.5% | 90.3% | 94.3% |
| Two-bedroom apartment | 30 | 70.5% | 90.5% | 94.3% |
| Small office with lift core | 10 | 52.6% | 77.2% | 92.8% |
| Small office with lift core | 20 | 52.6% | 82.8% | 92.8% |
| Small office with lift core | 30 | 52.6% | 84.3% | 92.8% |

## Reading the results honestly

* **The hybrid map beats both alternatives** in every row: about half the error of plain interpolation, and 0.3 to
  1.0 dB better than the model alone, with the gap growing as points are added.
* **Router advice helped in this simulator.** It captured roughly 95% of the oracle's possible gain in the apartment
  and about 70% in the office, and beat the no-survey centre rule in both plans (the centre of the office lands
  beside the lift core and does no better than leaving the router where it is).
* **The apartment is an easy case:** only 8 allowed outlet positions, so even a random choice scores 74.5% and the
  centre rule 85.8%. The office, with a grid of about 400 candidates, is the more informative test.
* **The advice can be wrong.** In the office with 10 points it made true coverage more than 1 point worse in 10% of
  worlds (3% with 20 or 30 points). That is why the dashboard shows an error bar and calls it an estimate.
* **Extender advice** (an extra device, so not a like-for-like comparison) tied the router move in the apartment
  (90.3% each at 20 points) and beat it in the office (82.8% vs 71.7% at 20 points), but it is further from its own
  best possible in the office (84.3% vs 92.8% at 30 points).
* The advice rows barely change between 20 and 30 points probably because the placement search uses the model only,
  whose fit may already be stable by 20 points. I did not test that explanation.

## What would make this meaningful

1. Surveys of real homes with a second, independent measurement of the *moved-router* result.
2. A comparison with an established survey tool on the same home.
3. Wall losses and thresholds checked against real measurements instead of my own priors.
