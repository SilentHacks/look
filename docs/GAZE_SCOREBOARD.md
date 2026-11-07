# Gaze tuning — observed results, 2026-11-07

## Decision

**Leave production unchanged: nine-point MediaPipe iris/head ridge λ=1.**
No evaluated configuration supports a reliable 3×3, let alone 4×4, claim.
The best aggregate same-day 3×3 result is **43.9%** (per-axis, 25 points),
versus **36.6%** for the same-budget baseline; its cross-day score is
**43.1% versus 39.4%**. Ordinary ridge λ=10 / 25 points is almost tied
same-day (**43.8%**) and best cross-day (**44.2%**), but neither wins
consistently per person or across grid/error metrics.

The nine-point ridge10 candidate regresses p03 from 43.1% to 37.9% same-day
and p02 from 45.0% to 37.7% cross-day. At 25 points, ridge10 regresses p02
cross-day from 55.0% to 51.8%, including 5×5 from 31.4% to 23.0%.
Sparse public calibration also does not establish the right regularization for
45+ live frames. A two-protocol aggregate win alone is insufficient to replace
the live default. No production estimator, calibration UI, smoothing, cursor mode
or companion appearance changed.

**Realistic region:** at most a provisional **2×2** experiment, not an established
product capability. Ridge10 / 25 points scores 67.9% same-day and 68.4% cross-day
at 2×2; the unchanged baseline / 25 scores 57.3% and 61.5%. Those are public-data
diagnostics, not this user's laptop accuracy, and the production UI still has nine
points. Stop this sweep below the requested ~60% 3×3 threshold. Next useful evidence
is a real, authorized session with seconds of calibration per point and held-out
validation, or a rights-cleared pretrained appearance family with disjoint test
people—not a larger hyperparameter grid.

## Data and separation

- Reused official MPIIFaceGaze ZIP (942,343,290 bytes), SHA-256
  `237c0bd75bd5454b53c8c5b1cacccd73813e8e0475907a0624cdc547dd085482`.
  CC BY-NC-SA / non-commercial scientific evaluation only; ephemeral personal fits,
  no reusable weights, public images, features or profiles committed or installed.
- Expanded p00–p02 to **p00–p05**, **1,675 images**, **18 day windows**. This avoids
  selecting a winner only on the original three people. Days were selected from
  acquisition counts/order, never gaze labels, face quality or test results.
- First/middle/last days with ≥80 images; at most 100 acquisition-ordered images/day:

  | Person | Days (sample counts) |
  |---|---|
  | p00 | 1 (100), 17 (100), 38 (100) |
  | p01 | 12 (83), 42 (100), 58 (85) |
  | p02 | 2 (82), 17 (100), 35 (91) |
  | p03 | 35 (89), 49 (81), 61 (83) |
  | p04 | 1 (100), 15 (100), 25 (81) |
  | p05 | 2 (100), 13 (100), 26 (100) |

- **Same-session column = same-day proxy for MPII:** fresh fit on each day's first
  40%, test its later 60% on exact held-out targets. Original image order, not
  fabricated seconds. MPII cannot prove these were one uninterrupted sitting.
  The implemented real-video protocol uses each recording's actual initial
  calibration block and later held-out frames, refitting per recording.
- **Cross-day:** first 40% of selected whole days calibrate; later days test.
  On three selected days, this means the first day calibrates and two later days
  test. It is a different, denser sample from the earlier 900-image milestone,
  so do not compare its headline directly with the earlier 29.8%/41.2% table.
- Same-day test denominator: **1,008** frames at nine points; **1,007** at 16/25.
  Cross-day: **1,121** at every budget. Later exact calibration-target repeats are
  excluded. All configurations share calibration target choices and test rows
  at a given budget; gating never substitutes another target. Retained targets
  are recorded (gate: 8–9 / 13–16 / 21–25 for nominal 9 / 16 / 25).
- All 1,675 images returned baseline features; coverage losses here are mainly
  off-screen estimates, plus intentional candidate gating. No clamping to edges.
  Missing/off-screen predictions remain **misses** in every region denominator.
- Fits and normalization use calibration only; no people, future labels,
  smoothing state or frames are pooled into training. Public “25 points” means
  25 labelled stills, not 25 one-second fixation recordings or a new live UI.

## All candidates, both protocols

Frame-weighted exact-cell hits. S = same-day proxy; C = cross-day. Angular mean
is conditional on a returned prediction, using the dataset's calibrated monitor
plane and per-image face-center proxy. Coverage is separate. Latency = measured
MediaPipe inference + Python prediction, with patch extraction for `appearance`;
excludes model reset/startup, decode, CDP, exposure and camera-to-answer delay.
The extraction overlapped the private fake-device probe; this is not an idle-device
thermal or real-camera latency measurement. Typical landmark means are ~35 ms;
patch ridge adds ~1.2 ms. Person ranges aggregate that person's day windows.

| Configuration | Points | Same-day 3×3 / 4×4 / 5×5 | Cross-day 3×3 / 4×4 / 5×5 | Degrees mean S / C | Coverage S / C | Latency ms S / C | Person 3×3 range S / C |
|---|---:|---|---|---|---|---|---|
| baseline-ridge1 | 9 | 29.5% / 19.2% / 13.1% | 26.1% / 17.8% / 11.2% | 6.80 / 7.38 | 78.4% / 75.1% | 35.10 / 35.13 | 17.8–43.1% / 11.0–45.0% |
| ridge10 | 9 | 36.7% / 23.6% / 14.1% | 32.5% / 21.4% / 14.5% | 6.52 / 6.98 | 97.5% / 96.3% | 35.10 / 35.13 | 32.3–41.1% / 21.5–46.4% |
| ridge100 | 9 | 12.7% / 10.2% / 5.9% | 12.9% / 11.5% / 4.7% | 9.53 / 9.57 | 100.0% / 100.0% | 35.10 / 35.13 | 10.6–14.4% / 10.8–14.5% |
| eyes-only | 9 | 37.3% / 23.4% / 15.5% | 34.0% / 21.4% / 12.3% | 6.52 / 6.87 | 97.7% / 98.7% | 35.10 / 35.13 | 27.3–46.1% / 24.3–45.5% |
| one-eye | 9 | 27.7% / 18.3% / 10.3% | 25.7% / 15.0% / 10.3% | 7.53 / 8.19 | 98.3% / 95.9% | 35.10 / 35.13 | 23.0–34.9% / 17.5–36.5% |
| head-local | 9 | 27.6% / 18.1% / 11.1% | 22.2% / 12.8% / 7.5% | 7.41 / 8.99 | 94.0% / 96.3% | 35.10 / 35.13 | 22.2–33.5% / 16.0–30.9% |
| openness-gate | 9 | 36.1% / 24.0% / 14.6% | 31.2% / 20.3% / 12.8% | 6.48 / 7.10 | 96.7% / 94.8% | 35.10 / 35.13 | 31.1–41.1% / 21.5–46.4% |
| poly2 | 9 | 19.5% / 12.7% / 8.9% | 20.4% / 11.5% / 7.3% | 9.20 / 9.17 | 88.5% / 85.5% | 35.11 / 35.14 | 17.0–24.4% / 17.5–25.1% |
| rbf | 9 | 32.9% / 22.2% / 14.1% | 35.1% / 22.5% / 15.5% | 7.02 / 7.11 | 99.8% / 99.7% | 35.11 / 35.13 | 26.7–43.8% / 26.5–51.8% |
| per-axis | 9 | 37.3% / 23.4% / 15.3% | 32.7% / 21.4% / 15.0% | 6.45 / 6.73 | 97.5% / 96.1% | 35.10 / 35.13 | 34.2–39.4% / 26.0–45.3% |
| appearance | 9 | 24.5% / 16.2% / 11.6% | 26.7% / 17.0% / 13.1% | 8.14 / 8.25 | 76.1% / 83.1% | 36.30 / 36.32 | 11.1–32.0% / 18.2–41.5% |
| baseline-ridge1 | 16 | 32.5% / 22.1% / 18.2% | 33.2% / 21.7% / 16.6% | 5.95 / 6.06 | 79.2% / 78.5% | 35.10 / 35.13 | 27.8–44.1% / 17.5–50.8% |
| ridge10 | 16 | 41.8% / 28.7% / 20.2% | 40.0% / 26.8% / 17.7% | 5.68 / 5.77 | 96.0% / 94.9% | 35.10 / 35.13 | 35.4–47.9% / 32.0–49.2% |
| ridge100 | 16 | 14.9% / 11.8% / 6.5% | 14.1% / 13.3% / 6.9% | 8.75 / 8.72 | 100.0% / 100.0% | 35.10 / 35.13 | 10.6–18.3% / 10.8–16.0% |
| eyes-only | 16 | 42.4% / 28.2% / 19.3% | 37.3% / 23.2% / 15.2% | 6.06 / 6.34 | 97.1% / 96.7% | 35.10 / 35.13 | 33.7–52.7% / 29.3–51.3% |
| one-eye | 16 | 35.5% / 21.7% / 13.4% | 33.4% / 22.3% / 14.6% | 6.55 / 6.67 | 98.1% / 95.8% | 35.10 / 35.13 | 30.8–38.2% / 27.5–38.7% |
| head-local | 16 | 33.7% / 23.7% / 14.1% | 28.6% / 16.9% / 12.2% | 6.58 / 7.45 | 95.0% / 95.6% | 35.10 / 35.13 | 25.0–41.2% / 18.5–41.4% |
| openness-gate | 16 | 41.6% / 28.9% / 20.6% | 39.6% / 26.2% / 17.2% | 5.67 / 5.78 | 95.0% / 93.8% | 35.10 / 35.13 | 35.4–47.3% / 32.0–48.7% |
| poly2 | 16 | 26.0% / 15.0% / 11.2% | 25.5% / 16.3% / 10.2% | 8.26 / 7.82 | 87.0% / 80.7% | 35.11 / 35.14 | 21.2–30.0% / 18.5–31.7% |
| rbf | 16 | 37.8% / 25.1% / 16.7% | 35.7% / 26.0% / 16.3% | 6.49 / 6.55 | 99.8% / 98.9% | 35.11 / 35.13 | 32.9–44.7% / 24.0–47.6% |
| per-axis | 16 | 41.6% / 26.7% / 20.3% | 39.2% / 26.4% / 16.8% | 5.71 / 5.80 | 95.8% / 94.7% | 35.10 / 35.13 | 35.5–46.7% / 33.0–46.6% |
| appearance | 16 | 36.2% / 25.2% / 18.4% | 33.4% / 21.5% / 18.2% | 6.57 / 6.59 | 78.8% / 82.5% | 36.30 / 36.32 | 27.8–44.2% / 18.0–53.5% |
| baseline-ridge1 | 25 | 36.6% / 26.3% / 18.4% | 39.4% / 29.7% / 21.0% | 5.59 / 5.39 | 82.4% / 85.5% | 35.10 / 35.13 | 27.8–45.4% / 23.0–55.0% |
| ridge10 | 25 | 43.8% / 29.8% / 22.0% | 44.2% / 29.9% / 20.1% | 5.29 / 5.43 | 94.3% / 94.6% | 35.10 / 35.13 | 39.1–50.9% / 39.0–51.8% |
| ridge100 | 25 | 19.2% / 14.6% / 8.2% | 18.1% / 14.8% / 8.0% | 7.98 / 8.02 | 100.0% / 100.0% | 35.10 / 35.13 | 12.4–24.9% / 12.4–22.5% |
| eyes-only | 25 | 42.3% / 29.7% / 21.0% | 39.7% / 24.6% / 16.7% | 5.86 / 6.12 | 94.4% / 94.0% | 35.10 / 35.13 | 35.5–51.5% / 27.6–53.4% |
| one-eye | 25 | 38.1% / 25.6% / 16.6% | 37.6% / 26.4% / 16.6% | 6.07 / 6.20 | 97.2% / 96.4% | 35.10 / 35.13 | 34.2–42.2% / 30.0–44.0% |
| head-local | 25 | 33.9% / 24.1% / 16.7% | 32.8% / 20.8% / 14.0% | 6.00 / 6.80 | 93.0% / 92.7% | 35.10 / 35.13 | 28.3–42.4% / 21.0–49.2% |
| openness-gate | 25 | 43.2% / 30.0% / 21.4% | 43.7% / 29.5% / 20.1% | 5.31 / 5.41 | 93.5% / 93.3% | 35.10 / 35.13 | 39.1–50.3% / 39.0–51.3% |
| poly2 | 25 | 30.5% / 20.0% / 14.7% | 26.9% / 16.5% / 11.7% | 7.13 / 7.18 | 87.3% / 78.3% | 35.11 / 35.14 | 26.1–36.8% / 20.4–43.9% |
| rbf | 25 | 39.4% / 25.4% / 17.8% | 38.4% / 24.9% / 18.2% | 6.10 / 6.38 | 99.0% / 98.8% | 35.11 / 35.13 | 33.9–44.7% / 32.4–48.8% |
| per-axis | 25 | 43.9% / 29.2% / 22.8% | 43.1% / 28.7% / 20.0% | 5.28 / 5.45 | 94.2% / 94.5% | 35.10 / 35.13 | 36.1–52.7% / 36.0–50.3% |
| appearance | 25 | 42.7% / 34.3% / 29.1% | 40.9% / 26.9% / 22.7% | 5.06 / 5.59 | 80.7% / 85.9% | 36.30 / 36.32 | 31.1–59.4% / 19.5–59.5% |

### Configuration definitions

- `baseline-ridge1`: unchanged shipped feature/predictor/λ=1 solver; eval-only
  calibration relaxes nine-target/45-frame/training-fit UI guards.
- `ridge10`, `ridge100`: only λ changes. Coverage alone can improve by collapsing
  to central predictions: λ=100 is worse on region hits and angular error.
- `eyes-only`: four eye-corner-relative iris coordinates, λ=10, no head features.
- `one-eye`: one eye plus the original four head features, λ=10. Baseline already
  uses both eyes; this ablation generally loses.
- `head-local`: image-aspect-corrected 3D face basis, both iris positions projected
  into head coordinates, nose/scale/roll and yaw/pitch proxies, λ=10. Worse here;
  MediaPipe's inferred iris depth is not measured eyeball geometry.
- `openness-gate`: ridge10 plus both eye ratios ≥.18 and blink blendshape ≤.4.
  Drops observations from the fixed calibration selection as well as predictions.
- `poly2`: all degree-two products of standardized baseline inputs, λ=10.
- `rbf`: standardized baseline, RBF bandwidth √(feature count), α=.1.
- `per-axis`: separate horizontal/vertical iris inputs, each retaining four head
  features, λ=10. Ordinary linear ridge already has independent output weights;
  the tested change is the input subset, not a duplicated solver.
- `appearance`: per-eye contrast-normalized 16×8 grayscale pixels (256 total)
  plus the original eight features, personal ridge λ=10; no pretrained gaze
  weights. At 25 points it helps finer-grid same-day hits (34.3% at 4×4), but
  loses coverage and cross-day consistency. **Not a BlazeGaze/CNN result.**

## Per-person spread and regressions

No statistical independence is claimed for frames within a day. These six people
are evidence against uniform improvement, not a population/laptop accuracy bound.
Full 792 per-person/session rows include all candidates/budgets in private
`~/.cache/hermes-gaze-eval/tuning-final/results.json`; the human-readable full table
and held-out traces are alongside it. Key configurations:

| Person | Configuration / points | Same-day 3×3 / 4×4 / 5×5 | Cross-day 3×3 / 4×4 / 5×5 | Degrees mean S / C | Coverage S / C |
|---|---|---|---|---|---|
| p00 | baseline-ridge1 / 9 | 27.8% / 20.0% / 12.2% | 11.0% / 8.0% / 3.5% | 6.27 / 9.90 | 75.0% / 58.5% |
| p01 | baseline-ridge1 / 9 | 24.2% / 18.0% / 11.8% | 16.8% / 9.2% / 6.5% | 7.69 / 8.39 | 83.2% / 74.6% |
| p02 | baseline-ridge1 / 9 | 35.2% / 21.2% / 14.5% | 45.0% / 30.4% / 22.5% | 5.74 / 4.98 | 79.4% / 89.5% |
| p03 | baseline-ridge1 / 9 | 43.1% / 26.1% / 20.9% | 42.7% / 32.9% / 18.3% | 7.76 / 6.81 | 87.6% / 89.6% |
| p04 | baseline-ridge1 / 9 | 17.8% / 14.2% / 11.8% | 24.9% / 17.1% / 8.8% | 7.06 / 7.10 | 66.9% / 70.7% |
| p05 | baseline-ridge1 / 9 | 30.0% / 16.7% / 8.3% | 19.5% / 12.0% / 9.0% | 6.37 / 8.05 | 79.4% / 70.5% |
| p00 | ridge10 / 9 | 41.1% / 25.0% / 13.9% | 21.5% / 15.5% / 9.5% | 6.25 / 9.13 | 95.6% / 90.5% |
| p01 | ridge10 / 9 | 32.3% / 19.9% / 8.1% | 24.9% / 20.5% / 13.5% | 6.90 / 6.78 | 98.1% / 95.1% |
| p02 | ridge10 / 9 | 36.4% / 24.2% / 15.2% | 37.7% / 20.4% / 11.5% | 5.86 / 5.78 | 98.8% / 100.0% |
| p03 | ridge10 / 9 | 37.9% / 24.8% / 12.4% | 38.4% / 26.2% / 15.9% | 8.60 / 7.84 | 100.0% / 99.4% |
| p04 | ridge10 / 9 | 34.3% / 28.4% / 18.3% | 46.4% / 28.7% / 21.5% | 5.76 / 5.68 | 94.1% / 95.0% |
| p05 | ridge10 / 9 | 37.8% / 19.4% / 16.1% | 28.0% / 18.5% / 16.0% | 5.93 / 6.75 | 98.9% / 98.0% |
| p00 | baseline-ridge1 / 25 | 34.4% / 26.7% / 19.4% | 43.5% / 37.0% / 22.5% | 4.97 / 4.35 | 77.2% / 84.5% |
| p01 | baseline-ridge1 / 25 | 44.1% / 25.5% / 14.3% | 36.2% / 28.1% / 21.6% | 5.06 / 5.23 | 87.0% / 90.8% |
| p02 | baseline-ridge1 / 25 | 35.2% / 27.9% / 21.8% | 55.0% / 40.8% / 31.4% | 4.84 / 3.72 | 80.0% / 92.1% |
| p03 | baseline-ridge1 / 25 | 45.4% / 33.6% / 20.4% | 43.9% / 38.4% / 23.2% | 6.78 / 6.32 | 86.8% / 88.4% |
| p04 | baseline-ridge1 / 25 | 27.8% / 23.1% / 20.1% | 35.9% / 20.4% / 16.0% | 6.50 / 6.32 | 80.5% / 86.2% |
| p05 | baseline-ridge1 / 25 | 34.4% / 22.2% / 14.4% | 23.0% / 14.5% / 11.5% | 5.48 / 6.89 | 83.9% / 72.0% |
| p00 | ridge10 / 25 | 42.8% / 32.8% / 20.6% | 47.0% / 33.5% / 21.5% | 4.89 / 4.72 | 91.1% / 94.0% |
| p01 | ridge10 / 25 | 41.0% / 25.5% / 18.6% | 41.6% / 29.2% / 18.4% | 5.09 / 5.04 | 94.4% / 96.2% |
| p02 | ridge10 / 25 | 50.9% / 35.8% / 32.1% | 51.8% / 35.6% / 23.0% | 4.12 / 4.15 | 97.0% / 96.3% |
| p03 | ridge10 / 25 | 46.7% / 32.2% / 17.8% | 42.7% / 34.1% / 22.6% | 6.96 / 7.17 | 97.4% / 97.0% |
| p04 | ridge10 / 25 | 39.1% / 28.4% / 24.9% | 42.5% / 26.0% / 18.8% | 5.67 / 5.82 | 92.3% / 93.9% |
| p05 | ridge10 / 25 | 42.8% / 24.4% / 18.3% | 39.0% / 21.5% / 16.5% | 5.17 / 5.95 | 94.4% / 90.5% |
| p00 | per-axis / 25 | 45.6% / 33.3% / 21.7% | 46.0% / 35.5% / 24.0% | 4.84 / 4.42 | 93.3% / 93.0% |
| p01 | per-axis / 25 | 44.7% / 24.2% / 18.0% | 40.5% / 29.2% / 20.5% | 5.07 / 5.03 | 94.4% / 96.8% |
| p02 | per-axis / 25 | 52.7% / 36.4% / 30.9% | 50.3% / 34.6% / 18.3% | 4.02 / 4.32 | 96.4% / 96.9% |
| p03 | per-axis / 25 | 43.4% / 28.3% / 21.1% | 36.0% / 29.3% / 20.1% | 7.24 / 7.65 | 96.7% / 95.1% |
| p04 | per-axis / 25 | 36.1% / 29.0% / 28.4% | 43.6% / 24.9% / 18.2% | 5.62 / 5.71 | 90.5% / 93.4% |
| p05 | per-axis / 25 | 41.1% / 23.9% / 17.2% | 41.0% / 19.0% / 18.5% | 5.10 / 5.95 | 94.4% / 92.0% |
| p00 | appearance / 25 | 31.7% / 26.1% / 25.0% | 19.5% / 12.0% / 9.0% | 5.39 / 6.80 | 75.6% / 73.0% |
| p01 | appearance / 25 | 56.5% / 43.5% / 39.8% | 59.5% / 47.6% / 36.8% | 3.49 / 3.69 | 96.3% / 97.3% |
| p02 | appearance / 25 | 59.4% / 50.3% / 41.8% | 44.0% / 26.7% / 24.6% | 3.32 / 5.63 | 95.2% / 86.4% |
| p03 | appearance / 25 | 44.7% / 40.1% / 28.3% | 53.0% / 36.0% / 33.5% | 6.00 / 5.93 | 75.7% / 92.7% |
| p04 | appearance / 25 | 35.5% / 26.6% / 23.7% | 38.1% / 21.0% / 20.4% | 7.62 / 6.01 | 86.4% / 81.8% |
| p05 | appearance / 25 | 31.1% / 21.7% / 17.8% | 34.5% / 20.5% / 15.0% | 4.94 / 5.86 | 57.8% / 86.0% |

## Appearance checkpoint decision

Checked upstream [WebEyeTrack/BlazeGaze](GAZE_DATASETS.md#appearance-model-provenance)
at `75fbd2f5f784f2eb3a39675a8dcbf1b01c697f1c`: MIT **code**, but no independently
verified rights-cleared gaze checkpoint was identified there. GazeCapture-trained
models carry research-only provenance concerns. Contrary to assuming every browser
weight is GazeCapture-trained, the conversion script names an MPIIFaceGaze run;
that recipe trains on p00–p09, overlapping this sweep. Exact checkpoint/run mapping
and unrestricted weight rights remain unestablished. Did not download, run, ship
or call the upstream checkpoint cleared. The scored scratch pixel ridge avoids
that issue, but does not test the potential of a pretrained appearance model.

## Fake-camera temporal comparison — jitter only

Reused the retained 144.031-second camera-only NASA portrait recording and its
baseline nine-point held-out trace: **457 frames**, **432 predictions**, **148
adjacent stationary-target pairs** ≤250 ms. No human gaze/physical geometry;
no region, angular, saccade-accuracy or comfort claim from this video.

| Causal filter | Stationary residual jitter RMS | Predictions | Added lag tradeoff |
|---|---:|---:|---|
| Raw | 1.426 px | 432/457 | None |
| EMA, τ=120 ms | 1.180 px | 432/457 | 120 ms time constant |
| Trailing median3 + EMA | 0.889 px | 432/457 | About one sampled frame (200 ms) + EMA |

Median rejects isolated coordinate spikes; no future samples or target labels are
used by filters. Missing predictions/session changes/gaps reset state, never fill
abstentions. Fake motion is already very stable; a 0.54-px reduction cannot justify
adding roughly 200 ms plus EMA lag to live gaze. No production smoothing added.

## Reproduction and verification actually run

See [commands and split details](GAZE_EVAL.md). Actual private input/output paths:

- `~/.cache/hermes-gaze-eval/tuning-frames/manifest.json`: dense loader input.
- `~/.cache/hermes-gaze-eval/tuning-frames/appearance-features.json`: final stepped
  WASM extraction, including real eye pixels, openness and head-local candidates.
- `~/.cache/hermes-gaze-eval/tuning-final/`: all results, traces, full table and
  `jitter.json`. Eleven configurations × three budgets × two protocols;
  **792 successful rows**, no unscorable folds.
- Shared feature SHA-256: `7d7dc061f458f6f55ce9e80d9a52824555b3d868281b0d3a9d1c79e99cf8bf11`.
- Offline-runtime SHA-256: `f40c1491fdfa3433582846f95c3818de84c6c52c94bef7575373f1ffb384fde9`.
- `.venv/bin/python -m unittest discover -s tests -t .`: **168 tests, OK**.
  Includes same-day chronological separation/refitting, calibration-only candidate
  fits/profile reuse, abstention denominators and causal filter spike/missing reset.
- `node tests/cursor_context_dom.js`: **24 passed, 0 failed**.
- `node --check` on all **seven** `browser/*.js`: **all passed**.
- `.venv/bin/python tests/webcam_chrome.py --out /tmp/hermes-gaze-tuning-webcam-proof`:
  **passed**. Nine-point calibration, 0600 profile, isolated context, interrupted
  calibration restart, **20 hidden samples / 2 seconds**, wall-clock ingestion,
  **two fusion calls with camera-only samples**, focused-tab ownership, stopped
  owned process and return to cursor mode. Translated portrait/scripted answer/
  microphone stub only; this does not measure human accuracy.

- `gaze_eval score ... --points 9 --protocols same-session cross-day`: actual CLI
  smoke produced **48 successful rows** (two baseline variants, six people,
  18 same-day windows plus six cross-day fits per variant).
- `run_benchmark --gaze-trace .../ridge10-25-same-session-trace.json --trials 1007`:
  raw hit **11.1%**, spatial **30.4%**, fusion top-1 **76.8%**, top-3 **89.0%**;
  top-3 × modeled .97 pick **86.3%**. Successful new-trace consumer smoke, not
  human speech/model success and not a production gaze-accuracy estimate.

No real webcam/microphone, ordinary Chrome profile, running Hermes, port 9222,
paid inference, account registration, licence acceptance, push, PR or merge.
Reused the cached public archive/models; new frame/features directory is ~80 MiB.
The fake probe fetched its checksum-pinned NASA portrait; no new dataset/model
weights were downloaded. Cursor/companion appearance and production defaults unchanged.

## Prior milestone reference (not rerun as a tuning claim)

Commit `40b2e59`, original 900-image p00–p02 sparse sample, nine points, 554
cross-day held-out frames: baseline 29.8% / 20.6% / 13.2% at 3×3 / 4×4 / 5×5,
ridge10 41.2% / 27.6% / 15.3%; coverage 75.1% / 98.2%. Measured-noise fusion
top-1 was 61.6% / 76.2%, respectively. Different sample/protocol from this sweep;
noise-transfer fusion is not real spoken-question/answer success.
