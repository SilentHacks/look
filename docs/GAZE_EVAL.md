# Offline gaze evaluation

[Collect a dataset](GAZE_RECORDING.md) · [Dataset decision](GAZE_DATASETS.md) ·
[Scoreboard](GAZE_SCOREBOARD.md)

No Hermes session, API key, hosted model, website permission, real camera or
microphone is needed for evaluation. Run `scripts/gaze.py` from the repository root.
No shell functions or plugin registration are needed. The live appearance model is
documented in [Webcam gaze](WEBCAM_GAZE.md). Evaluation keeps the original baseline
and existing saved-feature layout for reproducible comparisons.

## Load, extract, compare

Install the project runtime dependencies, Chrome, FFmpeg and ffprobe as described
in the [recording guide](GAZE_RECORDING.md). SciPy is not required.

```bash
CACHE="$HOME/.cache/hermes-gaze-eval"
.venv/bin/python scripts/gaze.py data list
.venv/bin/python scripts/gaze.py data load --stride 2 --out "$CACHE/owned-frames"
.venv/bin/python scripts/gaze.py eval extract "$CACHE/owned-frames/manifest.json" --out "$CACHE/owned-features"
.venv/bin/python scripts/gaze.py eval score "$CACHE/owned-features/features.json" \
  --points 9 16 25 --protocols same-session cross-condition cross-glasses --out "$CACHE/owned-scores"
.venv/bin/python scripts/gaze.py tune "$CACHE/owned-features/features.json" \
  --points 9 16 25 --out "$CACHE/owned-tuning"
```

Use new output directories for a new extraction. `data load` joins every complete
recording, across people and imported bundles. Add `--person p-a7c4` to load one
participant. Partial sessions remain available on disk, but are excluded from this
batch loader. The low-level `eval recording SESSION --out DIR` can decode a
finalized partial recording for recovery. An unfinalized video is refused.

Output directories are outside the repo and `0700`. Files are `0600`. Nothing is
uploaded, installed as a live profile or added to Git. Decoded PNGs can be much
larger than video: load one person first and delete derived frames when no longer
needed. `--stride 2` decodes every second frame. Do not use a stride so large that
selected calibration targets have fewer than 45 valid observations in total.

## Protocols and separation

Targets are chosen from the source's initial contiguous calibration phase only.
Nested farthest-point selection gives 9/16/25 labelled locations from the 5×5
collection. 16 is a spatially spread subset, not a literal 4×4 acquisition grid.
Selection is label-only and **before** face filtering or candidate gating. A missing
face never moves calibration into the test phase or substitutes an easier target.
The selected observations may lose faces. Retained target count is reported.

- **`same-session`**: fresh personal fit for each session. Later fixed/moving/reading
  frames test it. The explicit `no-recalibration` session instead names its earlier
  baseline session in `calibration_source`. It has no calibration phase of its own.
- **`cross-condition`**: use the earliest compatible earlier upright baseline with
  the same person, glasses, camera/device and pixel geometry. Test each later
  non-baseline condition without refitting. Target-session calibration is ignored.
- **`cross-glasses`**: use the earliest compatible earlier session of the same
  condition/person/device/geometry with different eyewear. Test without refitting.
  Direction depends on recording order and is explicit in `calibration_session`.
  This includes contacts when present. Record a further round to test the opposite
  temporal direction. No future session is silently used to calibrate the past.
- **Cross-person summary**: frame-weight within each person/condition/glasses,
  then equal weight per person. No cross-person training or pooled personal fit.
  `summary.json` includes both per-person and macro rows. Conditions and eyewear
  remain separate. A missing compatible source is `unscorable`, not a fallback.

Fits require matching camera/device and display/viewport size, DPR and screen size.
Changed physical viewing distance is allowed and uses the target session's physical
geometry for degrees, when supplied. Never silently rescale an incompatible
camera/display pair. After lid changes, restore the original viewport size before
starting the next block.

Exact calibration-location repeats are excluded from headline tests. The start and
end 3×3 validation blocks use the **same nine targets and dwell**, including repeats
of calibration coordinates: they are separately scored in `results.json` under
`validation`. Each has frame/prediction counts, 3×3/4×4/5×5 hits and conditional
pixel error. `bias_shift_px` compares their mean residuals. This matched probe is
more interpretable than the additional descriptive first/last-third drift metric,
which is confounded by target movement and condition. No refit uses either probe.

## Metrics and candidates

Headline: **3×3, 4×4, 5×5 exact cell hits**. Missing-face, blink, gated and off-screen
predictions remain misses in the full test denominator. Coverage is separate.
2×2 remains a coarse diagnostic in JSON. Pixel mean/median/p95 are conditional on a
prediction. Approximate centered-viewer degrees are available only when all three
physical measurements were supplied. Otherwise `N/A`. They are not measured 3D
head/eye rays. Jitter is RMS adjacent stationary-target residual displacement with
a gap of at most 250 ms. Latency is WASM inference + Python prediction, not exposure
or camera-to-answer delay. CPU is renderer/Python thread time, not total OS/GPU use.

`EvalRidge` keeps the original iris/head λ1 predictor, standardization and ridge
solver as the baseline. Dataset experiments allow target counts beyond the live UI's nine, but still require 45
finite samples, distinct targets, eye movement and a training error ≤.20. A fake
portrait may fail that honest fit check. Never weaken it to manufacture accuracy.

Eleven tuning configurations remain: baseline λ=1, ridge λ=10/100, eyes-only,
one-eye, head-local coordinates, openness/blink gating, degree-two polynomial,
RBF ridge, separate per-axis inputs and scratch personal eye-pixel ridge. Every
normalization and fit sees calibration only. No external gaze checkpoint or
reusable public-data weights. `tune --configs ...` selects existing configurations.
`--protocols ...` selects protocols. `eval score --estimator module:factory` loads
only a **trusted local** `GazeEstimator` implementation. Never use an imported
participant's code or factory.

For causal smoothing/jitter experiments only, append
`--jitter-trace /absolute/held-out-trace.json` to `tune`. Raw, EMA (120 ms) and trailing
median3 + EMA reset on missing samples, >250 ms gaps and session boundaries. They
never fill abstentions or read target labels for filtering. No live smoothing is
changed.

## Feature-only research with a reserved final phase

The [personal-calibration research report](GAZE_TUNING_RESEARCH.md) records the
frozen comparison, uncertainty and original shipping recommendation. The later live
cutover implements its nine-point left-appearance + iris λ10 candidate with strict
rejection and no smoothing. It does not install research fits or bias refresh.

`research` reads an existing `features.json` only. It does not run Chrome, load
images, access devices, fetch assets or install calibration profiles:

```bash
.venv/bin/python scripts/gaze.py research "$CACHE/owned-features/features.json" \
  --out "$CACHE/owned-tuning/research" --stage select
.venv/bin/python scripts/gaze.py research "$CACHE/owned-features/features.json" \
  --out "$CACHE/owned-tuning/research" --stage report
.venv/bin/python scripts/gaze.py research-safety "$CACHE/owned-features/features.json" \
  --out "$CACHE/owned-tuning/research"
```

Selection uses fixed/moving/reading phases, excluding exact selected-calibration
coordinates. Every `validation-end` frame is removed before the search. Fits and
normalizers see only selected initial calibration frames. Optional 1/3/5-point
bias refresh uses labelled `validation-start` locations, before screen rejection.
Those observations are a calibration cost, not test data. This is the only
research exception to the standard evaluator's no-validation-refit rule.

The finite hill-climb starts with eye/pose/appearance subsets, five ridge
strengths, polynomial and RBF models. Top development candidates try Huber fitting,
blink/openness rejection, causal EMA, limited off-screen tolerance and bias
refresh. Choices are frozen separately for each point budget, protocol and
eyewear stratum, plus a shared-eyewear choice. Selection optimizes equal-session,
equal-3×3/4×4/5×5 hits. Missing predictions and failed fits count as misses.
No weights are pooled between sessions or eyewear states.

`selection.json` pins feature-file and research-code hashes. Selection cannot
overwrite itself, and reporting rejects changed inputs/code. `development.json`
is exploratory, **not** a held-out score. `final.json`, `final-summary.json` and
`FINAL.md` contain aggregate end-validation results only, never per-frame traces,
features or fitted weights. Each session has exact conditional mean/p95 error.
Summary p95 is explicitly the mean/range of session p95s, not a pooled quantile.
`research-safety` evaluates fixed ablations of those same frozen choices with
strict screen rejection, and the original baseline with 1/3/5-point bias refresh.
It never reselects a model. Aggregates go to `safety-ablations.json`.

This is phase separation, not independent-session or independent-person
validation. End probes are stationary and repeat some calibration coordinates.
They do not establish moving-target accuracy. Eight sessions from one person
cannot establish a population estimate or isolate eyewear from session order.
9/16/25 subsets come from one distributed 25-point acquisition, not measured
standalone live calibrations. Saved inference times plus new Python CPU/wall
times exclude capture, camera scheduling, UI and full-process CPU. EMA reports
its time constant and discrete low-frequency delay separately.

## Retained format and alignment

`recording.json` version 2 contains pseudonym, eyewear, condition label and explicit
posture/light/distance/camera-angle fields, anonymous device label, date/time, note,
screen geometry, seed, completion and optional calibration-source ID.
`targets.jsonl` has session-relative frame presentation timestamps, original video
media times, actual displayed target, phase and settling marker. The native frame
presentation clock resets against each session's recorder start, not a paused
preview's playback time. `camera.webm` is original camera-only VP8 video, no dots.

The common manifest remains version 1: dataset, licence and sessions. Each session
retains person/session/condition/glasses/device, geometry, start epoch, true video
clock and frames. A frame has absolute decoded path, epoch `t`, `video_t`, target
and phase. Extraction retains eight `features` or null, pose/openness/blink, and
`appearance` in the existing order: 128 normalized left-eye values, 128 right-eye
values, then the original eight features. Live and offline use the same shared
`browser/webcam_features.js` implementation. Live takes only the left eye and its
two iris coordinates (`appearance[:128] + appearance[-8:-6]`, length 130).
Existing saved feature files remain usable without re-extraction. Feature/runtime
hashes identify the extractor. Portable bundles contain raw recordings, not
machine-local PNG paths.

FFmpeg decoder PTS is matched to the last recorded target, never a future target.
Settling frames (first .35 s of each standard 1.2 s fixed dwell) are excluded before
extraction. Video is frame-stepped through the same pinned MediaPipe WASM/model,
CPU delegate, feature function and VIDEO mode. Session boundaries reset state.
Recorder/video alignment is approximate within a camera frame, not lab hardware
synchronization. Moving-target lag and saccades remain limitations. Frame stepping
does not measure device startup, live drops, thermals or battery cost.

## Resolver noise-transfer experiment

```bash
.venv/bin/python -c 'import tests, runpy; runpy.run_module("hermes_gaze.benchmark.run_benchmark", run_name="__main__")' \
  --gaze-trace "$CACHE/owned-scores/owned-features-ridge10-25-same-session-trace.json" --trials 100
```

Held-out prediction-minus-target residuals replace Gaussian gaze noise on the demo
dashboard. Missing predictions remain misses. This is **noise-transfer**, not real
spoken-question/ASR/model success. Omit the trace for the seeded synthetic benchmark.

## Fake-only reproduction

```bash
.venv/bin/python tests/gaze_eval_chrome.py --out /tmp/hermes-dataset-proof
.venv/bin/python tests/webcam_chrome.py --out /tmp/hermes-webcam-proof
```

The dataset probe accepts consent with trusted CDP input **before** opening its fake
camera, runs all six blocks twice (glasses/none), stops at a break and resumes in a
new owned process, verifies CLI resume, byte-identical export/import, decodes and
extracts retained video, then scores per condition/glasses and all protocols.
Accelerated 36-second sessions are fake-only. Human default is 150 seconds.
The translated public-domain NASA portrait is a plumbing fixture, not gaze ground
truth. Temporary videos/frames/features/bundles are removed. Only screenshots and
small JSON proof files remain. Private allocated CDP ports only, never 9222, user's
Chrome or running Hermes. No real camera, microphone or paid inference.
