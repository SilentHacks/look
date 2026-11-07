# Offline gaze evaluation and personal recording

[Dataset survey and access decisions](GAZE_DATASETS.md) ·
[Observed scoreboard](GAZE_SCOREBOARD.md)

No Hermes session, website camera permission, API key or hosted model is needed.
The live gaze defaults and companion/cursor appearance are unchanged.

## Run locally

From the repository root, with its virtualenv and macOS Chrome installed:

```bash
# Existing runtime deps: numpy and websockets. SciPy is eval-only, for MATLAB geometry.
.venv/bin/pip install 'scipy>=1.11,<2.0'
# Helpers load the existing test package shell, not the plugin's registration hooks.
gaze_eval() { .venv/bin/python -c 'import tests; from hermes_gaze.benchmark.gaze_eval import main; main()' "$@"; }
gaze_record() { .venv/bin/python -c 'import tests; from hermes_gaze.benchmark.gaze_record import main; main()' "$@"; }
gaze_tuning() { .venv/bin/python -c 'import tests; from hermes_gaze.benchmark.gaze_tuning import main; main()' "$@"; }
CACHE="$HOME/.cache/hermes-gaze-eval"

# Official, anonymous, non-commercial-scientific-use original archive, <1 GB.
# Read GAZE_DATASETS.md first. Never train or ship weights from this research data.
mkdir -p "$CACHE"
curl --fail --location --max-filesize 10000000000 \
  --output "$CACHE/MPIIFaceGaze.zip" \
  https://datasets.d2.mpi-inf.mpg.de/MPIIGaze/MPIIFaceGaze.zip

# Reuse the cached ZIP. Dense, label-blind days allow same-day 25-point calibration.
gaze_eval mpiiface "$CACHE/MPIIFaceGaze.zip" --people p00 p01 p02 p03 p04 p05 \
  --days 3 --per-day 100 --out "$CACHE/tuning-frames"
gaze_eval extract "$CACHE/tuning-frames/manifest.json" --out "$CACHE/tuning-features"
gaze_tuning "$CACHE/tuning-features/features.json" --points 9 16 25 --out "$CACHE/tuning-scores"
# Baseline-only comparison or a trusted local GazeEstimator factory:
gaze_eval score "$CACHE/tuning-features/features.json" --points 9 16 25 \
  --protocols same-session cross-day --out "$CACHE/baseline-scores"
```

Outputs: `SCOREBOARD.md`, numeric `results.json`, and held-out `*-trace.json` files.
Data/output directories must be outside this repo and mode `0700`; files are `0600`.
Do not point the command at a shared directory. No images or fitted profiles enter Git.
The downloader is explicit, size-bounded and separate from running an evaluation.

## Personal recording checklist — user only, about 15 minutes

**Agents must never run this real-camera command.** Fake-device reproduction is below.
The user can run this without starting Hermes or touching their ordinary Chrome profile.

1. Use a private room; the camera captures your face **and background**. Close any
   sensitive material in view. Leave the laptop/display/camera fixed at 100% zoom.
   Use your usual glasses, screen brightness and working distance.
2. Run one three-minute session:
   ```bash
   gaze_record --condition upright --duration 180
   ```
   Allow **camera only** in the separate owned window. Maximize it **before**
   clicking **Start recording**. No microphone is requested or recorded.
3. Follow the dot with your eyes, naturally. First: nine fixed calibration targets
   (45 seconds). Then: a 4×4 fixed grid, slow moving targets, and reading-style
   left-to-right sweeps. Keep the window visible; do not resize/move it or change
   display/zoom while recording. Initial settling frames after fixed-target moves
   are excluded from scoring.
4. Repeat for four more three-minute sessions:
   ```bash
   gaze_record --condition lean-back --duration 180
   gaze_record --condition lean-side --duration 180
   gaze_record --condition dim --duration 180
   gaze_record --condition side-light --duration 180
   ```
   The instructions describe each condition. Use comfortable changes, not strain
   or darkness. Each session includes its own early calibration, so separately
   scored sessions compare **calibrated** performance across conditions, not the
   effect of changing posture without recalibration.
5. Wait for automatic completion and the terminal's **Saved private local
   recording** line. **Esc** saves and stops early. Hiding or moving/resizing the
   window stops early rather than retaining incorrect targets. Closing Chrome or
   terminating the process can leave an unfinalized video; the loader refuses it.
6. Each session lives in `~/.cache/hermes-gaze-eval/recordings/<date-random-id>/`:
   - `camera.webm`: original unannotated camera stream, VP8 encoded; no audio.
   - `targets.jsonl`: camera-frame timestamps, displayed-task target and phase.
   - `recording.json`: pseudonym, condition, geometry, completion reason and size.
   Keep all three for future estimators. Nothing is uploaded or sent to Hermes.
   Delete the session directory to delete its video and metadata; also delete any
   derived frame/features/score directories. Ordinary file deletion is not a claim
   of forensic erasure from SSDs, backups or snapshots.
7. Optional physical geometry: supply **all three** `--width-mm`, `--height-mm`
   (full display dimensions) and `--distance-mm` (eye-to-display distance).
   The recorder scales dimensions to its viewport. Degrees use an approximate
   centered-viewer geometry, not measured 3D eye/head pose; omit measurements for
   honest `N/A` degrees. Pixels and grid hits do not need them.

Load and evaluate an actual session, using its printed path:

```bash
SESSION="$CACHE/recordings/<actual-session-directory>"
gaze_eval recording "$SESSION" --stride 3 --out "$CACHE/personal-frames"
gaze_eval extract "$CACHE/personal-frames/manifest.json" --out "$CACHE/personal-features"
gaze_eval score "$CACHE/personal-features/features.json" --points 5 9 --protocols same-session --out "$CACHE/personal-scores"
```

A recording contains nine calibration locations: requesting 16 or 25 reports
`unscorable`, never invented extra points. Dense public stills support 9/16/25-point
experiments. Use distinct output directories for each session.

## Why frame stepping instead of fake-camera playback for scoring?

Acquisition and the recording smoke probe use the **real owned Chrome camera
path**, including fake-file camera flags in automation. Evaluation decodes retained
video with FFmpeg, obtains frame PTS from ffprobe, matches the last target at each
PTS, and steps selected frames through the **same pinned MediaPipe WASM, model,
CPU delegate, confidence settings, eight-feature function and VIDEO mode**.
The offline runtime additionally requests blendshapes and computes head-local
features and normalized 16×8 grayscale patches of each eye. These additions do
not change live extraction. Video timestamps retain their real cadence.
Independent public stills reset the face track; otherwise one person's previous
image could influence the next.
No real camera or microphone is opened for offline feature extraction.

This avoids dropped/repeated frames and wall-clock races from playing sparse
labelled images as a fake camera. The cost: it does **not** measure device startup,
exposure delay, live dropped-frame rates, thermals or real-time end-to-end latency.
Recorder target/video alignment is bounded approximately to one camera frame,
not laboratory hardware synchronization. Fixed-target settling excludes transition
frames; fast eye saccades and moving-target lag still need a synchronized human
video dataset such as EVE. No claim of frame-perfect camera/target synchronization.

The decoder defaults to every third camera frame. Change `--stride` to compare
cadences, using new output paths. The reported inference wall time excludes model
initialization/reset, decoding and CDP. CPU is renderer-thread CPU including those
per-frame decode/reset/CDP costs, plus Python prediction thread CPU—not total OS
CPU, GPU usage or a live webcam battery/heat measurement.

## Protocol, calibration and metrics

Common JSON manifest (`version: 1`):

- Top level: `dataset`, `licence`, `sessions`.
- Session: `person` (pseudonym), `session`, `screen`, `temporal`, `clock`, `frames`;
  optional `start_epoch` orders multiple recordings. Screen coordinates are local
  pixels with zero `left`/`top`; width/height, DPR and screen geometry use the live
  estimator's existing keys. Optional mm/monitor pose/eye origin enable degrees.
- Frame: absolute image `path`, `t`, pixel `target: [x,y]`, `phase`;
  `calibration` is the recording's initial block, followed by `fixed`, `moving` or
  `reading`. Public day-ordered stills use `unassigned`; their `t` is an acquisition
  **day**, not fabricated seconds. `temporal: false` disables video jitter.
- Extracted frame: `features` or explicit `null` for missing face/blink,
  `inference_ms`, `extract_cpu_ms`, plus eval-only `pose_features`, `openness`,
  `blink`, `appearance` (256 eye pixels + the original eight features), and
  `appearance_inference_ms`. Manifests identify both feature and offline-runtime
  source hashes. Frames remain available for future extractors.

Both protocols split **before face filtering**, choose farthest calibration
targets using early labels only, and exclude all exact calibration-target repeats
from test. Missing early faces never move the cutoff. Every fit is personal;
scaling, weights and temporal state never cross people or test boundaries.

- **Same-session:** public stills refit independently on each acquisition day's
  earliest 40% of frames (original image order), then test its later 60%, on
  held-out targets. MPII has no within-day timestamps/session IDs: this is a
  **same-day proxy**, not proof of one uninterrupted sitting. Real video instead
  uses each recording's first contiguous `calibration` block and later held-out
  targets from that recording, with a fresh fit for every recording.
- **Cross-day:** public stills calibrate on the earliest 40% of whole selected
  acquisition days and test later days. Multiple personal recordings calibrate
  only on the first recording's initial block and test non-calibration frames of
  later recordings; a lone recording is unscorable, not silently same-session.
- `mpiiface --days 3 --per-day 100` chooses first/middle/last acquisition days
  containing at least 80 images, using counts/order only. At most 100 images/day
  are evenly sampled in acquisition order. This supports 25 early targets without
  downloading more data. Without `--days`, `--limit` retains sparse whole-history
  sampling for the original cross-day reproduction.
- Configurations use identical selected calibration targets and test rows at each
  point budget. Gating drops observations from that fixed selection, never replaces
  them with easier targets; `calibration_targets_used` records the retained count.
  Calibration sizes have nested target sets, so excluding later repeats can change
  their test denominators slightly. Protocols have different test populations.

The baseline is `LandmarkEstimator`'s predictor and standardized λ=1 ridge solver.
Its eval-only subclass relaxes live UI validity rules (exactly nine targets, at least
45 frames, training-fit rejection), because sparse public images have distinct
random target coordinates and cannot satisfy that acquisition protocol. A parity
test proves identical weights/predictions when given normal live calibration data.
Sparse public “nine points” means **nine labelled images**, not nine seconds-long
fixations. It is not a product-accuracy estimate of the live calibration UI.
`ridge10` changes only λ to 10, not shipped defaults. Alternative trusted local
factories implementing `tracker.webcam_gaze.GazeEstimator` can be passed with
`score --estimator package.module:factory`; compatible features are required.
Models with a different observation representation need a corresponding offline
extractor/runtime and manifest; do not pretend eight landmarks fit every model.

`gaze_tuning` runs eleven explicit configurations, not a hyperparameter grid:
ridge λ=1/10/100; eyes-only and one-eye ablations; aspect-corrected 3D head-local
iris coordinates plus yaw/pitch proxies; openness ≥.18 and blink ≤.4 gating;
degree-two polynomial ridge λ=10; RBF kernel ridge α=.1 with standardized
dimension-based bandwidth; separate horizontal/vertical iris models λ=10; and
personal pixel-appearance ridge λ=10. Both eyes and eye-corner-relative positions
are **already in the baseline**. The pixel model is not WebEyeTrack or a pretrained
CNN; it learns only that evaluation calibration, retains no reusable weights,
and introduces no external checkpoint. See [checkpoint provenance](GAZE_DATASETS.md#appearance-model-provenance).

For **jitter only**, pass an existing fake-recording trace:
```bash
gaze_tuning "$CACHE/tuning-features/features.json" --out "$CACHE/tuning-with-jitter" \
  --jitter-trace "$CACHE/scores/recording-features-baseline-ridge1-9-trace.json"
```
`jitter.json` compares raw samples, causal EMA (120 ms time constant), and trailing
three-sample coordinate median + EMA (single-spike rejection). Filters reset on
missing predictions, gaps >250 ms or session changes; they never fill abstentions.
Target labels enter only the stationary-jitter metric, never filtering. Added lag
is reported; the fake portrait cannot establish human saccade accuracy or comfort.


- Headline: 3×3, 4×4, 5×5 exact cell hits; missing/off-screen predictions are **misses**.
  JSON also includes 2×2 as a coarser-region diagnostic, not another tuning run.
- Pixel and available angular mean/median/p95: conditional on a returned prediction;
  coverage is displayed and stored separately. MPII degrees use calibrated 3D
  screen-plane rays from the dataset's per-image face center (an eye-origin proxy).
- Jitter: RMS successive residual displacement on a stationary target, adjacent
  samples at most 250 ms apart. Never computed from unrelated still images.
- Drift: first/last-third error and bias shift, elapsed seconds or acquisition days.
  Target difficulty, posture and lighting confound this descriptive number.
- Latency/CPU: per-frame wall/thread times, not camera-to-answer delay.

## Existing resolver with measured gaze residuals

```bash
.venv/bin/python -c 'import tests, runpy; runpy.run_module("hermes_gaze.benchmark.run_benchmark", run_name="__main__")' \
  --gaze-trace "$CACHE/tuning-scores/ridge10-25-same-session-trace.json" --trials 1007
```

This replaces Gaussian pointing noise with held-out measured prediction-minus-target
residuals. Dimensions scale to a 1280×900 dashboard and residuals translate to each
known benchmark target. Consecutive video residuals retain their time differences;
no synthetic distractor is added. Missing predictions remain misses. The resolver
uses the existing 120-px gaze uncertainty. Still-image trials are individual samples,
not invented eye trajectories. This is a **noise-transfer resolver benchmark**, not
real question/ASR/LLM success. The Lens ×0.97 row is still a modeled assumption.
Omit `--gaze-trace` for the existing seeded synthetic benchmark.

## Fake-device reproduction

```bash
.venv/bin/python tests/gaze_eval_chrome.py --out "$CACHE/fake-proof-new"
gaze_eval recording "$CACHE/fake-proof-new/recording" --out "$CACHE/fake-frames-new"
gaze_eval extract "$CACHE/fake-frames-new/manifest.json" --out "$CACHE/fake-features-new"
gaze_eval score "$CACHE/fake-features-new/features.json" --points 5 9 --protocols same-session --out "$CACHE/fake-scores-new"
```

The probe uses a checksum-pinned public-domain NASA portrait, translated in a Y4M
fake camera, and trusted CDP Start input in a private Chrome process. It records all
four phases for 144 seconds, checks the absence of audio and file permissions, and
stops only its own process. A translated portrait is **not human gaze ground truth**;
its scores prove comparisons and retention work, not useful eye tracking.
