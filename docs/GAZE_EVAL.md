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
CACHE="$HOME/.cache/hermes-gaze-eval"

# Official, anonymous, non-commercial-scientific-use original archive, <1 GB.
# Read GAZE_DATASETS.md first. Never train or ship weights from this research data.
mkdir -p "$CACHE"
curl --fail --location --max-filesize 10000000000 \
  --output "$CACHE/MPIIFaceGaze.zip" \
  https://datasets.d2.mpi-inf.mpg.de/MPIIGaze/MPIIFaceGaze.zip

gaze_eval mpiiface "$CACHE/MPIIFaceGaze.zip" --people p00 p01 p02 --limit 300 --out "$CACHE/mpiiface-300"
gaze_eval extract "$CACHE/mpiiface-300/manifest.json" --out "$CACHE/public-features"
gaze_eval score "$CACHE/public-features/features.json" --points 5 9 16 --out "$CACHE/scores"
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
gaze_eval score "$CACHE/personal-features/features.json" --points 5 9 --out "$CACHE/personal-scores"
```

A recording contains nine calibration locations: requesting 16 reports
`unscorable`, never invented extra points. The public still dataset supports
5/9/16-point experiments. Use distinct output directories for each session.

## Why frame stepping instead of fake-camera playback for scoring?

Acquisition and the recording smoke probe use the **real owned Chrome camera
path**, including fake-file camera flags in automation. Evaluation decodes retained
video with FFmpeg, obtains frame PTS from ffprobe, matches the last target at each
PTS, and steps selected frames through the **same pinned MediaPipe WASM, model,
CPU delegate, confidence settings, eight-feature function and VIDEO mode**.
Video timestamps retain their real cadence. Independent public stills reset the
face track; otherwise one person's previous image could influence the next.
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
  `inference_ms`, `extract_cpu_ms`. Extracted manifests identify the shared feature
  source hash. Frames remain available for a future extractor/model.

Per person: MPIIFaceGaze uses the earliest 40% of **whole acquisition days** as
calibration candidates; every test frame is from a later day. Personal video uses
only its first contiguous calibration block; later recordings cannot leak their
calibration back into earlier test periods. Deterministic farthest-target sampling
uses early labels only. All later exact repeats of held-in target locations are
excluded, so the score is on **both unseen targets and later time**. Missing early
faces do not move the chronological cutoff. Calibration never uses test features,
targets, smoothing state or pooled people. Each configuration gets a fresh model.

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

- Headline: 3×3, 4×4, 5×5 exact cell hits; missing/off-screen predictions are **misses**.
- Pixel and available angular mean/median/p95: conditional on a returned prediction;
  coverage is stored separately in results JSON. MPII degrees use calibrated 3D
  screen-plane rays from the dataset's per-image face center (an eye-origin proxy).
- Jitter: RMS successive residual displacement on a stationary target, adjacent
  samples at most 250 ms apart. Never computed from unrelated still images.
- Drift: first/last-third error and bias shift, elapsed seconds or acquisition days.
  Target difficulty, posture and lighting confound this descriptive number.
- Latency/CPU: per-frame wall/thread times, not camera-to-answer delay.

## Existing resolver with measured gaze residuals

```bash
.venv/bin/python -c 'import tests, runpy; runpy.run_module("hermes_gaze.benchmark.run_benchmark", run_name="__main__")' \
  --gaze-trace "$CACHE/scores/public-features-baseline-ridge1-9-trace.json" --trials 554
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
gaze_eval score "$CACHE/fake-features-new/features.json" --points 5 9 --out "$CACHE/fake-scores-new"
```

The probe uses a checksum-pinned public-domain NASA portrait, translated in a Y4M
fake camera, and trusted CDP Start input in a private Chrome process. It records all
four phases for 144 seconds, checks the absence of audio and file permissions, and
stops only its own process. A translated portrait is **not human gaze ground truth**;
its scores prove comparisons and retention work, not useful eye tracking.
