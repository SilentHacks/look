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

Before updating or reloading the plugin, quit Hermes and run `hermes gateway stop`
first, then restart Hermes. Hermes runs a background gateway that keeps old code
loaded even after the terminal closes; closing the terminal alone is not a reload.

During ordinary plugin use, only `/look mode webcam` or `/look calibrate` starts
the camera. Registration, model tools, status and changing configuration do not.
The owned window requests video only, never audio. It captures and infers locally;
images never leave it in ordinary tracking mode. The separate, explicit
[guided dataset recorder](GAZE_RECORDING.md) saves camera video locally.
Only 130 bounded numeric biometric features cross an exact-context, nonce-checked
`__hermesGazeIntent` CDP binding: 128 normalized left-eye appearance values followed
by that eye's two iris coordinates. No raw pixels, canvas patches or images cross
the live binding. Features are never logged or included in `/look diagnostics`.
There is no HTTP sample endpoint. The camera
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

`/look calibrate` switches to webcam mode, starts the owned camera window and
brings it forward; `/look mode webcam` opens the same flow. Maximize it, keep its zoom at
100%, and click **Start calibration** (**Calibrate again** for a saved setup). At each dot, look at it, tap Space and keep looking for
about one second. Each dot keeps its concise instruction underneath: **Tap Space**,
**Keep looking**, or a retry cue. One current-target count advances only after Python
accepts the observation. A dot without enough usable frames asks again.
Esc or **Cancel** cancels; moving/resizing/hiding the window
cancels rather than applying wrong screen targets. The trusted opening click
measures the actual viewport origin, including browser chrome. Nine targets are
converted to desktop logical coordinates using that origin, not a fullscreen or
`outerHeight - innerHeight` guess.

### Held-out check and practice

Fitting produces a **candidate** in a private estimator copy. The accepted estimator
and file do not change until a check passes. **Ready to check** stops between fitting
and checking: explicitly activate **Start accuracy check** to continue. Space on the
neutral field cannot start it. The check uses the same fresh Space tap at every dot.
It tests five positions that differ from the training nine, in two orders (ten equal trials). Each trial ignores a settling period, then
takes the median of its valid estimates. Missing, off-screen or mostly absent trials
fail. Estimates stay in memory for that trial and never refit anything. Named
constants in `tracker/webcam_gaze.py` are **provisional pending a real-camera
trial**: a trial hits inside one cell of a 3×3 screen grid around its target; eight
of ten pass; fewer than six valid trials cannot judge.

The result states whether calibration was saved, whether a saved calibration passed,
or why another attempt is needed. No circles or miss lines are shown. A weak or
unmeasurable new calibration offers **Calibrate again** or **Use cursor** and
keeps any earlier saved calibration. A cancelled or failed attempt saves nothing.
Moving, resizing or hiding the window during measurement or at the stopped boundary
discards the candidate. Saved setup offers **Check** or **Calibrate again**;
checking goes straight to ten targets and never rewrites the saved profile.

**Try a question** opens the guided Saturn example. It is silent practice only:
no microphone, transcription, model call or question injection. A tap or early
release asks you to try the hold again; a completed hold shows **Listening**,
the suggested question, then a labelled example answer on release. Escape, blur
or face loss interrupts rehearsal without claiming completion. Completed practice
uses the inbox's existing coach state so browsing does not repeat the hold lesson;
skipping does not claim that it was taught. Real browsing **Listening** still
requires the first native microphone buffer.

**Return to browsing** and **Skip practice** activate the exact companion page
captured before opening setup, including its document, route, bound Hermes connection
and setup generation. One foreground request is followed by at most three seconds
of focus/visibility observations and a protected-renderer check. An acknowledgement
alone is not success. A closed/replaced page, disconnect, changed setup or unobserved
focus keeps explicit recovery; **Try again** rechecks the same destination.
**Open start page** explicitly creates/reuses a small local Look page in the
owned companion, waits for attachment and checks foreground ownership. It never
navigates an unrelated tab or restores a missing source by URL.

The same camera process, document and video stream stay live behind browsing.
Its retained **Eye tracking** page offers return, recalibration and **Use cursor**.
In the companion, press **Q** before the first answer, or choose **Eye tracking**
in an answer's footer, to open camera controls and **Use cursor**. Camera/session
loss revokes setup return and stops the corresponding runtime without joining
the camera reader under the inbox lock. The saved calibration remains unchanged.
Focused companion buttons accept trusted Enter/Space input; those keys never approve
website actions. Status commands do not replace an ongoing setup's connection;
explicit reconnects do. Restarting a closed camera document gives completion a
fresh setup generation rather than reusing an earlier return attempt.

**Use cursor** is available at entry and on unsuccessful results/recovery.
Camera errors stay on screen with a plain state and **Try again**.
If the window closes or startup returns `stopped`, the command offers
**Try again** with `/look calibrate`; it does not claim calibration is ready.

The accepted profile is stored atomically at
`${XDG_CONFIG_HOME:-~/.config}/hermes-gaze/webcam-calibration.json`, mode `0600`
in a `0700` directory. No images, audio, raw calibration samples or profile values
are logged or committed. Delete that file to forget calibration. The profile is
versioned to the estimator and one display. Old iris/head-only profiles are refused
without overwriting them: “The eye tracker changed. Please recalibrate with /look calibrate.”
Recalibrate after moving, leaning back, changing head/lid/camera position, lighting
or glasses, and if delivery drops. There is no automatic posture correction.
A training-fit check is not a human accuracy measurement.
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
After setup, **Move the pointer in this page.** appears only when that destination's
measured anchor is actually missing/changed. It lives in the protected renderer
and clears only on a trusted fresh pointer measurement, not a timer or synthetic
event. An already anchored page gets no pointer hint.

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
the shipped `AppearanceEstimator` has model id
`mediapipe-face-v2-left-appearance-iris-ridge10-1`. It uses **nine-point personal,
standardized linear ridge λ10, strict off-screen rejection, no smoothing**.
`browser/webcam_features.js` owns extraction for both live video and offline images:
the 16×8 row-major grayscale eye region spans 1.5 eye widths, aligned to landmarks
33→133. Luminance is (.299R + .587G + .114B)/255, centered by patch mean and divided
by max(.02, population standard deviation). The same eye's two iris coordinates
follow those 128 values. Calibration-only mean/scale standardization then precedes
ridge fitting. The old `LandmarkEstimator` remains the offline λ1 baseline only.
A replacement model needs its own audited/pinned assets and observation script,
not another resolver.

The [guided recording protocol](GAZE_RECORDING.md) collects our own consented,
pseudonymous dataset with glasses/condition metadata and end validation.
[Offline evaluation](GAZE_EVAL.md) compares personal calibration budgets and
within-session, cross-condition and cross-glasses transfer, with per-person
summaries. [Reserved offline validation](GAZE_TUNING_RESEARCH.md) motivated this
cutover; it is one person's recorded footage, not population or live accuracy.
Fake devices prove plumbing only. Broad-region gaze remains experimental, not
button precision or unattended posture reuse.

**Follow-up:** a five-point labelled bias refresh needs a separate live interaction
and validation, especially with glasses. This milestone deliberately requires full
nine-point recalibration after moving instead.

## Hands-on checklist (real hardware: user only)

1. Start a normal Hermes conversation, then `/look`.
2. `/look mode webcam`: allow **camera only** in the separate tracker window.
   Confirm the camera indicator; no website needs a camera permission.
3. `/look calibrate`: maximize that window and complete the dots and the short
   check. Note the plain result and whether it matched how well it followed you.
   Stay in the same posture and lighting. Try Practise and losing your face.
4. Return to a supported Chrome page; move the pointer once in its content.
   Leave the pointer elsewhere, look at a broad region, hold Space, wait for
   Listening, and ask about “this”. Judge a roughly 3×3–4×4 region, not buttons.
5. `/look diagnostics`: `samples` should rise, `sample_age_seconds` stay fresh,
   and `delivered` rise while a calibrated Chrome page has focus. Switch tabs,
   seed each once, and repeat. No old tab should acquire the new gaze highlight.
6. Resize/zoom the page: move its pointer once again. Scroll and ask again.
   After moving, leaning back or changing camera position/glasses, recalibrate.
   Record actual successes/errors before making any accuracy or comfort claim.
7. `/look cursor`: confirm the camera indicator goes off and exact cursor
   questions still work. `/look stop` also detaches the companion; browser tabs stay open.

### When gaze is not fresh

`/look diagnostics` includes cumulative numeric `drops` counters for this tracker
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
“No fresh gaze. Check /look status.” A size change or pinch zoom gets its own
instruction. Missing gaze still blocks talking; there is no cursor/center fallback.


## Reproducible fake-device proof

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python tests/webcam_chrome.py --out /tmp/hermes-webcam-proof
```

`tests/calibration_chrome.py --out DIR` is headless and exercises every calibration,
check, practice, failure and restart state with a fake camera; only `predict` is scripted
for the passing path. The headed probe below still needs a separate serial run.
`tests/calibration_return_chrome.py --headed --out DIR` checks the real completion
binding and native foreground return with fake video and a synthetic saved fit:
silent rehearsal, replay/forgery rejection, retained background inference/delivery,
replaced-source recovery, explicit start-page failure/retry, private origin guidance
and the companion's stop control. Run headed probes serially. Unit ownership races
and late replies are in `tests/test_calibration_return.py`.

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

The appearance-live milestone did **not** run this Chrome probe: another builder
was using private test windows. Schedule it serially before claiming live proof.
The camera window's isolated `__HERMES_WEBCAM__.status()` now exposes aggregate
`frame_ms` (WASM + feature extraction wall time), `feature_ms` (iris + appearance
extraction wall time) and `sample_hz` (processed frames over elapsed inference-start
time). The probe saves those numeric aggregates in `camera_runtime`; none contain
features, coordinates or images. Live per-frame cost and fake-camera sample rate
remain unmeasured until that deferred run. These timers exclude exposure, binding
serialization/delivery and Python prediction; they are not CPU or end-to-end latency.

**Human gaze accuracy, real-camera latency/heat and posture robustness are not
measured by a fake camera.** The 3×3–4×4 target is a design goal, not a result.
