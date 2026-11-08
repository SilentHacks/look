# Webcam gaze

## Choice and runtime

MediaPipe Face Landmarker (Face Mesh V2 with iris landmarks), followed by our own
personal ridge regressor. The model card explicitly licenses the weights under
Apache-2.0; Tasks Vision is also Apache-2.0. Google does not publish separate
training-image dataset terms. See [third-party notices](../THIRD_PARTY_NOTICES.md)
for primary sources, pinned versions, hashes and the full upstream licence.
No GazeFollower/GazeFollower2, Glance, EyeTrax or WebEyeTrack code is used.

This avoids uncertain gaze-checkpoint provenance and Python MediaPipe wheel
compatibility. Python remains 3.14; inference uses Tasks Vision 0.10.32 WASM/SIMD
on CPU in a **separate Chrome process and private temporary profile**. This host
currently supports macOS's standard Google Chrome installation. No new Python
runtime or Python dependency is installed.

During ordinary plugin use, only `/gaze mode webcam` or `/gaze calibrate` starts
the camera. Registration, model tools, status and changing configuration do not.
The owned window requests video only, never audio. It captures and infers locally;
images never leave it in ordinary tracking mode. The separate, explicit
[guided dataset recorder](GAZE_RECORDING.md) saves camera video locally.
Eight bounded iris/head features cross an exact-context, nonce-checked
`__hermesGazeIntent` CDP binding. There is no HTTP sample endpoint. The camera
profile has extensions disabled and HTTP(S) requests blocked after startup.
Downloads happen in Python, before the camera starts, from official sources;
verified cached assets work offline.

The owned process disables background timer/renderer/occlusion throttling and
uses a 100ms timer rather than animation frames. This is not imposed on the
companion or the user's browser. A missing face, blink, stale frame, off-screen
prediction, wrong display or missing viewport origin supplies **no fixation**.
Four seconds without frames stops the tracker. Stop, mode change, disconnect,
unload and owned-document replacement close only the camera process we started.

## Calibration and coordinates

`/gaze calibrate` brings the owned window forward. Maximize it, keep its zoom at
100%, and click **Calibrate nine points**. Look at each dot, press Space, and keep
looking for about one second. Esc cancels; moving/resizing the calibration window
cancels rather than applying wrong screen targets. The trusted opening click
measures the actual viewport origin, including browser chrome. Nine targets are
converted to desktop logical coordinates using that origin, not a fullscreen or
`outerHeight - innerHeight` guess.

The fitted profile is stored atomically at
`${XDG_CONFIG_HOME:-~/.config}/hermes-gaze/webcam-calibration.json`, mode `0600`
in a `0700` directory. No images, audio, raw calibration samples or profile values
are logged or committed. Delete that file to forget calibration. The profile is
versioned to the estimator and one display; recalibrate after camera/posture or
display changes. A training-fit check is not a human accuracy measurement.
Stopping during calibration discards that unfinished collection, not the saved
profile. Restarting immediately resumes predictions from the saved profile.

On each new companion tab, move the pointer once **in the page** to measure the
viewport origin from a trusted mouse event. Repeat after resizing, zooming or
changing browser chrome/side panels. Window movement on the same display is
accounted for by its screen-position delta. The scale from desktop logical pixels
to page CSS pixels is `page.devicePixelRatio / calibration.devicePixelRatio`;
Retina pixels are not multiplied twice. The mapper adds the current scroll offset
for document coordinates. A different display or pinch zoom is rejected rather
than guessed. This initial pointer measurement is a deliberate usability limit.

Observations use `(performance.timeOrigin + performance.now()) / 1000` at inference
start, compatible with audio word epochs. Camera exposure-to-inference latency is
not measured. Python maps each prediction only into the currently focused owned
Chrome document, delivers its soft region, and calls `session.ingest(...)`.
Question release freezes that document's camera fixations/candidates before ASR.
The existing Bayesian fusion and temporal alignment resolve the question; the
answering model gets its bounded evidence. Webcam research is read-only. Cursor
mode is permanent and retains its exact-identity path.
Frozen ASR results cannot change the live mode or restore action authority,
including a simulated question completed after switching to webcam. Choosing a
simulated target requires both the saved resolution and the live mode to be simulated.

`tracker.webcam_gaze.GazeEstimator` is the swappable prediction/calibration
boundary. `WebcamHost` accepts an estimator and an observation-runtime source;
the shipped source extracts MediaPipe iris/head features. A replacement model
needs its own audited/pinned assets and observation script, not another resolver.

The [guided recording protocol](GAZE_RECORDING.md) collects our own consented,
pseudonymous dataset with glasses/condition metadata and end validation.
[Offline evaluation](GAZE_EVAL.md) compares personal calibration budgets and
within-session, cross-condition and cross-glasses transfer, with per-person
summaries. [Human accuracy](GAZE_SCOREBOARD.md) awaits these recordings; fake
devices prove plumbing only. The production choice remains the existing nine-point
λ=1 estimator: no new defaults, smoothing or fitted profiles are installed.

## Hands-on checklist (real hardware: user only)

1. Start a normal Hermes conversation, then `/gaze connect`.
2. `/gaze mode webcam`: allow **camera only** in the separate tracker window.
   Confirm the camera indicator; no website needs a camera permission.
3. `/gaze calibrate`: maximize that window and complete nine points. Confirm
   “Calibration saved locally”. Stay in the same posture and lighting.
4. Return to a supported Chrome page; move the pointer once in its content.
   Leave the pointer elsewhere, look at a broad region, hold Space, wait for
   Listening, and ask about “this”. Judge a roughly 3×3–4×4 region, not buttons.
5. `/gaze tracker`: `samples` should rise, `sample_age_seconds` stay fresh,
   and `delivered` rise while a calibrated Chrome page has focus. Switch tabs,
   seed each once, and repeat. No old tab should acquire the new gaze highlight.
6. Resize/zoom the page: move its pointer once again. Scroll and ask again.
   Try a different posture; recalibrate if the region drifts. Record actual
   successes/errors before making any accuracy or comfort claim.
7. `/gaze mode hover`: confirm the camera indicator goes off and exact cursor
   questions still work. `/gaze tracker stop` and `/gaze disconnect` also stop it.

### When gaze is not fresh

`/gaze tracker` includes cumulative numeric `drops` counters for this tracker
instance, retained across stop/restart. Compare two readings while the companion
page has focus; old counts from calibration or another application are normal.
No coordinates, features, images or calibration values are included.

- `no_features`: no usable face/eyes, including blinks.
- `uncalibrated`, `calibrating`: waiting for a profile or collecting calibration;
  these frames intentionally do not become predictions.
- `offscreen`: the fitted estimator predicted outside the calibrated screen.
  Estimates are still rejected, not clamped. `prediction_rejected` is the
  corresponding generic rejection for a replacement estimator.
- `no_foreground_tab`: no supported companion page has focus, including while
  the separate calibration window or Hermes terminal is in front.
- `no_page_anchor`, `viewport_changed`: move the pointer once inside the page.
  These are the only cases that receive that on-page advice.
- `unsupported_zoom`: reset pinch zoom. `wrong_display`: return to the calibrated
  display or recalibrate there.
- `outside_page`: a valid screen prediction landed outside the page viewport
  (for example, over browser chrome). Moving the pointer is not a gaze fallback.
- `page_mode_mismatch`, `mode_changed`: page/session mode differs from webcam.
- `stale_sample`: expired, replayed or invalid observation timestamp.
- `invalid_geometry`, `transport_error`, `transport_timeout`, `rejected_by_page`:
  invalid viewport information, interrupted transport, a timed-out delivery, or
  page-side refusal. Navigation/focus changes can interrupt a captured delivery.

With a valid page anchor but no fresh delivery, the page says only
“No fresh gaze. Check /gaze tracker.” A size change or pinch zoom gets its own
instruction. Missing gaze still blocks talking; there is no cursor/center fallback.


## Reproducible fake-device proof

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python tests/webcam_chrome.py --out /tmp/hermes-webcam-proof
```

The probe uses `--use-fake-device-for-media-stream` and
`--use-file-for-fake-video-capture`, a hash-pinned NASA public-domain portrait
translated to nine positions, a stub microphone, and scripted answers. It uses
only private Chrome profiles on allocated ports, never port 9222 or a live
Hermes. It checks actual nine-point calibration/persistence, a direct return to an
already-open page with native focus (no focus emulation), held-Space fusion/inbox
delivery, specific missing/changed-anchor guidance, interruption and restart with
the saved profile, hidden-tab samples, wall-clock ingestion, foreground ownership
and return to cursor. Run it separately from other headed Chrome probes: those
processes can steal native OS focus.
Screenshots and a small results JSON go to the output directory; calibration and
fake video are temporary and removed.

**Human gaze accuracy, real-camera latency/heat and posture robustness are not
measured by a fake camera.** The 3×3–4×4 target is a design goal, not a result.
