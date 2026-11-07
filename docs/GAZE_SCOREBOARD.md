# Gaze evaluation — observed results, 2026-11-07

Internal non-commercial evaluation. Public-data scores describe p00/p01/p02 and
their laptop setups, **not this user's laptop**. Fake-camera scores test plumbing
only. Nothing here establishes a comfortable 4×4 or 5×5 real-user tracker.

## Inputs and protocol

- Official MPIIFaceGaze original ZIP: 942,343,290 bytes; SHA-256 `237c0bd75bd5454b53c8c5b1cacccd73813e8e0475907a0624cdc547dd085482`.
- 300 acquisition-order samples/person, three people (900 input images).
- Earliest 40% of whole acquisition days supplies calibration candidates;
  554 later-day, held-out-target test images at nine calibration points.
- Nine-point public calibration uses nine labelled stills, not a seconds-long
  live fixation at each dot. The eval-only calibrator relaxes the live UI's
  nine-target/45-frame/fit-rejection checks; the feature/predictor/λ=1 solver is
  numerically identical. No public-data profiles are shipped or installed.
- Fake recording: 144.031 seconds, 2,513,200-byte VP8 camera-only video, four task
  phases, 0700 directory/0600 files. Decoded every third frame with real PTS.
  NASA portrait motion is not eye-gaze ground truth. No physical screen/eye
  geometry supplied, so fake-recording degree scores are correctly N/A.
- Commands and interpretation: [GAZE_EVAL.md](GAZE_EVAL.md).

## Nine-point public headline (frame-weighted, all 554 test images)

| Configuration | Returned predictions | 3×3 hit | 4×4 hit | 5×5 hit |
|---|---|---|---|---|
| Baseline λ=1 | 416/554 (75.1%) | 29.8% | 20.6% | 13.2% |
| Variant λ=10 | 544/554 (98.2%) | 41.2% | 27.6% | 15.3% |

Missing face/blink and off-screen predictions count as misses. Stronger ridge
regularization improved coverage and aggregate region hits in this small sparse
sample; **do not tune production defaults from it**. More calibration points
helped some people, not uniformly. Next evidence should be a user recording and
an authorized temporal EVE/EOTT sample, not another claimed product accuracy.

## Measured-noise resolution benchmark

All 554 nine-point public held-out residuals, translated to the existing synthetic
dashboard targets; no generated gaze noise or paid model calls. Temporal still
samples are not invented trajectories. This tests noise transfer into the existing
resolver, **not real ASR/utterance/model answer correctness**.

| Resolution method | Baseline λ=1 residuals | Variant λ=10 residuals |
|---|---|---|
| Raw hit test | 6.3% | 9.9% |
| Spatial box | 31.0% | 31.4% |
| Fusion top-1 | 61.6% | 76.2% |
| Fusion top-3 coverage | 71.1% | 92.2% |
| Top-3 × modeled 0.97 Lens pick | 69.0% | 89.4% |

The default synthetic benchmark also ran: fusion top-1 at σ80/130/180 was
98.3% / 85.0% / 86.7%, and top-3 coverage was 100% / 100% / 98.3%.
Those figures remain synthetic, not webcam accuracy.

## Full per-person / calibration-size scoreboard

# Offline gaze scoreboard

Region hits include missing/off-screen predictions as misses. Errors are conditional on a prediction.
Public results describe those participants and setups, not the user's laptop. Fake-camera results test plumbing only.

| Dataset/person | Configuration | Cal points/frames | Test/predicted | 3×3 | 4×4 | 5×5 | px mean/median/p95 | degrees mean/median/p95 | jitter px | latency mean ms | CPU extract/predict ms | Drift first→last px |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MPIIFaceGaze/p00 | baseline-ridge1 | 5/5 | 187/148 | 25.7% | 16.6% | 12.3% | 270.80/249.63/495.39 | 7.38/6.49/14.40 | N/A | 35.07 | 63.71/0.005 | 274.0→274.5 (23.0 acquisition days) |
| MPIIFaceGaze/p01 | baseline-ridge1 | 5/5 | 192/146 | 29.7% | 16.1% | 12.0% | 292.53/268.72/555.59 | 6.72/6.02/14.46 | N/A | 34.55 | 62.09/0.006 | 322.1→288.8 (40.0 acquisition days) |
| MPIIFaceGaze/p02 | baseline-ridge1 | 5/5 | 175/125 | 22.3% | 13.7% | 7.4% | 283.64/267.98/562.64 | 7.02/6.56/12.80 | N/A | 34.72 | 62.50/0.005 | 294.4→248.8 (23.0 acquisition days) |
| MPIIFaceGaze/p00 | baseline-ridge1 | 9/9 | 187/157 | 33.2% | 25.7% | 18.2% | 222.16/195.72/442.35 | 6.04/5.27/12.46 | N/A | 35.07 | 63.71/0.005 | 200.7→229.4 (23.0 acquisition days) |
| MPIIFaceGaze/p01 | baseline-ridge1 | 9/9 | 192/140 | 23.4% | 15.1% | 8.3% | 312.99/293.28/598.89 | 7.10/6.58/14.54 | N/A | 34.54 | 62.09/0.005 | 329.3→304.9 (40.0 acquisition days) |
| MPIIFaceGaze/p02 | baseline-ridge1 | 9/9 | 175/119 | 33.1% | 21.1% | 13.1% | 194.68/169.42/386.21 | 4.86/4.38/9.78 | N/A | 34.72 | 62.50/0.005 | 187.5→182.0 (23.0 acquisition days) |
| MPIIFaceGaze/p00 | baseline-ridge1 | 16/16 | 187/163 | 45.5% | 35.8% | 27.3% | 170.20/151.19/337.11 | 4.65/4.32/9.60 | N/A | 35.07 | 63.71/0.005 | 169.6→168.3 (23.0 acquisition days) |
| MPIIFaceGaze/p01 | baseline-ridge1 | 16/16 | 192/153 | 33.3% | 22.4% | 19.8% | 251.55/231.54/509.37 | 5.72/5.06/11.82 | N/A | 34.54 | 62.09/0.005 | 292.8→227.5 (40.0 acquisition days) |
| MPIIFaceGaze/p02 | baseline-ridge1 | 16/16 | 175/114 | 31.4% | 25.1% | 14.3% | 181.88/173.67/337.49 | 4.47/4.23/8.20 | N/A | 34.72 | 62.50/0.005 | 189.6→176.9 (23.0 acquisition days) |
| MPIIFaceGaze/p00 | ridge10 | 5/5 | 187/184 | 29.9% | 17.6% | 11.2% | 284.13/280.59/522.98 | 7.79/7.70/14.18 | N/A | 35.07 | 63.71/0.005 | 276.5→284.9 (23.0 acquisition days) |
| MPIIFaceGaze/p01 | ridge10 | 5/5 | 192/187 | 29.2% | 15.6% | 10.9% | 317.77/305.14/608.30 | 7.41/6.73/14.60 | N/A | 34.55 | 62.09/0.005 | 323.7→317.0 (40.0 acquisition days) |
| MPIIFaceGaze/p02 | ridge10 | 5/5 | 175/168 | 29.1% | 18.3% | 12.6% | 273.13/254.08/543.97 | 6.87/6.82/13.16 | N/A | 34.72 | 62.50/0.005 | 293.4→240.3 (23.0 acquisition days) |
| MPIIFaceGaze/p00 | ridge10 | 9/9 | 187/186 | 40.1% | 29.9% | 16.0% | 227.18/207.84/441.93 | 6.21/5.84/11.64 | N/A | 35.07 | 63.71/0.005 | 222.1→235.6 (23.0 acquisition days) |
| MPIIFaceGaze/p01 | ridge10 | 9/9 | 192/191 | 43.2% | 23.4% | 13.5% | 256.54/246.24/518.92 | 5.84/5.67/11.58 | N/A | 34.55 | 62.09/0.005 | 278.0→236.6 (40.0 acquisition days) |
| MPIIFaceGaze/p02 | ridge10 | 9/9 | 175/167 | 40.0% | 29.7% | 16.6% | 213.96/199.31/460.24 | 5.29/5.00/10.84 | N/A | 34.72 | 62.50/0.005 | 235.4→161.1 (23.0 acquisition days) |
| MPIIFaceGaze/p00 | ridge10 | 16/16 | 187/181 | 45.5% | 34.8% | 19.8% | 192.84/185.13/331.41 | 5.30/5.28/9.21 | N/A | 35.07 | 63.71/0.005 | 187.9→197.2 (23.0 acquisition days) |
| MPIIFaceGaze/p01 | ridge10 | 16/16 | 192/179 | 35.9% | 21.9% | 15.6% | 260.58/240.11/488.75 | 5.99/5.58/12.42 | N/A | 34.55 | 62.09/0.005 | 291.5→257.3 (40.0 acquisition days) |
| MPIIFaceGaze/p02 | ridge10 | 16/16 | 175/156 | 45.1% | 32.0% | 27.4% | 171.82/148.78/375.14 | 4.25/3.79/9.08 | N/A | 34.72 | 62.50/0.005 | 185.0→135.6 (23.0 acquisition days) |
| personal-fake/nasa-fake | baseline-ridge1 | 5/80 | 457/432 | 22.5% | 7.7% | 3.7% | 474.65/412.79/1167.45 | N/A | 8.64 | 13.38 | 12.92/0.005 | 375.1→523.3 (104.2 seconds) |
| personal-fake/nasa-fake | baseline-ridge1 | 9/144 | 457/432 | 22.5% | 10.9% | 3.7% | 476.62/418.09/1176.71 | N/A | 1.43 | 13.38 | 12.92/0.005 | 376.1→524.6 (104.2 seconds) |
| personal-fake/nasa-fake | baseline-ridge1 | 16 | unscorable: Only 9 valid early targets for 16-point calibration | — | — | — | — | — | — | — | — | — |
| personal-fake/nasa-fake | ridge10 | 5/80 | 457/428 | 22.5% | 8.8% | 3.7% | 442.61/379.02/1094.87 | N/A | 26.47 | 13.38 | 12.92/0.005 | 355.5→488.1 (104.2 seconds) |
| personal-fake/nasa-fake | ridge10 | 9/144 | 457/432 | 22.5% | 9.2% | 3.7% | 457.47/395.65/1137.26 | N/A | 10.37 | 13.38 | 12.92/0.005 | 364.4→503.3 (104.2 seconds) |
| personal-fake/nasa-fake | ridge10 | 16 | unscorable: Only 9 valid early targets for 16-point calibration | — | — | — | — | — | — | — | — | — |

Latency = WASM inference + Python predict wall time, excludes decoding, CDP and camera exposure.
CPU = Chrome renderer thread CPU (includes image decode/model reset/CDP work) / Python prediction thread CPU.
Jitter = RMS successive residual displacement on stationary targets ≤250 ms apart; still images: N/A.
Drift is descriptive early/late error and bias shift, confounded by target/posture changes; not causal sensor drift.
Baseline uses the shipped predictor and λ=1 solver; offline calibration relaxes live nine-target/45-frame/fit-rejection UI guards.
No model profiles or public-data weights are shipped; live defaults are unchanged.

## Verification actually run

- `.venv/bin/python -m unittest discover -s tests -t .`: **165 tests, OK**.
  Includes six new offline behavioral regressions (numerical baseline parity,
  chronological/target separation, later-session leakage, abstention denominator,
  measured-noise benchmark behavior and recording ownership/permissions).
- `node tests/cursor_context_dom.js`: **24 passed, 0 failed**.
- `node --check` on all seven `browser/*.js` files: **all passed**.
- `.venv/bin/python tests/webcam_chrome.py --out /tmp/hermes-gaze-eval-webcam-proof`:
  passed nine-point calibration/0600 persistence, isolated context, interrupted
  restart, 20 hidden samples/2 seconds, webcam-only ingestion/held-Space fusion,
  focused-tab ownership, stopped owned process and cursor-mode return.
- `.venv/bin/python tests/gaze_eval_chrome.py --out ~/.cache/hermes-gaze-eval/fake-proof`:
  passed full 144-second fake recorder; no audio track, all four phases, 0700/0600.
  Actual target surface screenshot was inspected.
  The final recorder-boundary version also passed a 36.041-second capture
  (650,149-byte video) at `~/.cache/hermes-gaze-eval/fake-boundary-proof`.
- Public and retained fake-camera frames were extracted by pinned WASM in owned
  Chrome and scored through `GazeEstimator` for both configurations.
- Measured-noise benchmark ran with baseline and variant traces (554 trials each),
  and the seeded default synthetic benchmark ran (60 trials/noise level).
- The retained fake-video temporal trace also ran (457 trials): raw 6.8%, spatial
  18.6%, fusion top-1 47.9%, top-3 74.8%; **plumbing only, not human accuracy**.
  A self-check caught old valid samples rescuing a missing current observation;
  reproduced as 100% instead of 50%, fixed, and retained as a regression.
- `py_compile` passed for changed Python sources and new test/probe sources.

No real webcam or microphone opened; no ordinary Chrome/profile, running Hermes,
port 9222, paid inference, account registration, agreement signature, push or PR.
This is an implementation-worker handoff; independent feature-cycle review belongs
to the controller and is not claimed here.
