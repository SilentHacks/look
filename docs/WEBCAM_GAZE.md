# Webcam gaze

## Choice and runtime

MediaPipe Face Landmarker (Face Mesh V2 with iris landmarks), followed by our own
personal ridge regressor. The model card explicitly licenses the weights under
Apache-2.0. Tasks Vision is also Apache-2.0. Google does not publish separate
training-image dataset terms. See [third-party notices](../THIRD_PARTY_NOTICES.md)
for primary sources, pinned versions, hashes and the full upstream licence.
No GazeFollower/GazeFollower2, Glance, EyeTrax or WebEyeTrack code is used.

This avoids uncertain gaze-checkpoint provenance and Python MediaPipe wheel
compatibility. Tasks Vision 0.10.32 WASM/SIMD runs on CPU in a **separate Chrome
process and private temporary profile**. The supported beta requires native arm64
Python on an Apple Silicon Mac and standard Google Chrome in Applications.
Platform/Chrome preflight runs before asset preparation. No new Python runtime or
Python dependency is installed. See the README for version evidence and unverified platforms.

Before updating or reloading the plugin, quit Hermes and run `hermes gateway stop`
first, then restart Hermes. Hermes runs a background gateway that keeps old code
loaded even after the terminal closes. Closing the terminal alone is not a reload.

During ordinary plugin use, only explicit `/look mode webcam`, `/look calibrate`,
`/look setup eyes` or protected camera controls start the camera. Registration,
model tools, status and changing configuration do not.
The owned window requests video only, never audio. It captures and infers locally.
Images never leave it in ordinary tracking mode. The separate, explicit
[guided dataset recorder](GAZE_RECORDING.md) saves camera video locally.
Only 130 bounded numeric biometric features cross an exact-context, nonce-checked
`__hermesGazeIntent` CDP binding: 128 normalized left-eye appearance values followed
by that eye's two iris coordinates. No raw pixels, canvas patches or images cross
the live binding. Features are never logged or included in `/look diagnostics`.
There is no HTTP sample endpoint. The camera
profile has extensions disabled and HTTP(S) requests blocked after startup.
Only `/look setup eyes` authorizes Python to download missing pinned files (~11 MB)
from official sources, then open the camera. Normal startup and developer
evaluation/recording verify cache-only assets. Verified caches work offline.
Preparation runs in a worker. `/look tracker` and the protected Eye tracking
controls distinguish preparing files, opening the window, loading the model,
opening camera access and failure. No percentage or permission outcome is invented.
**Use cursor**, `/look cursor`, Stop and disconnect revoke startup before slow work
can launch Chrome or hand off to camera access. A blocked network read may take
up to its 60-second socket timeout to finish. Cursor use does not wait for it.
Retry waits until that cancelled worker exits. It never starts a second worker.
Failures do not silently switch the evidence source or overwrite saved calibration.
`/look diagnostics` retains the failure stage, exception/error category, optional
OS error/exit code and bounded native failure categories. No raw Chrome stderr,
paths, URLs, device details or biometric values are retained or printed.

The owned process disables background timer/renderer/occlusion throttling and
uses a 100ms timer rather than animation frames. This is not imposed on the
companion or the user's browser. A missing face, blink, stale frame, off-screen
prediction, wrong display or missing viewport origin supplies **no fixation**.
Four seconds without frames stops the tracker. Stop, mode change, disconnect,
unload and owned-document replacement close only the camera process we started.

## Calibration and coordinates

Run `/look calibrate` to open the camera window. `/look mode webcam` opens the same setup.

1. Maximize the window and keep Chrome zoom at 100%.
2. Choose **Start calibration**, or **Calibrate again** for a saved setup.
3. Look at each dot, tap Space and keep looking until it moves, about one second.
   If your eyes aren’t visible long enough, the dot asks you to try again.

Press Esc or choose **Cancel** to stop. Moving, resizing or hiding the window also
cancels the attempt. Your saved calibration stays unchanged. The trusted opening click
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
trial**: a trial hits inside one cell of a 3×3 screen grid around its target. Eight
of ten pass. Fewer than six valid trials cannot judge.

The result states whether calibration was saved, whether a saved calibration passed,
or why another attempt is needed. No circles or miss lines are shown. A weak or
unmeasurable new calibration offers **Calibrate again** or **Use cursor** and
keeps any earlier saved calibration. A cancelled or failed attempt saves nothing.
Moving, resizing or hiding the window during measurement or at the stopped boundary
discards the candidate. Saved setup offers **Check** or **Calibrate again**.
Checking goes straight to ten targets and never rewrites the saved profile.

**Try a question** opens a practice question about Saturn. Your microphone stays off.
Hold Space, wait for **Listening**, then release it to see an example answer.
A short tap or early release lets you try again. Esc, switching windows or moving
your face out of view interrupts practice. No question is sent to Hermes.

Choose **Return to browsing** or **Skip practice** to return to the page where you
started setup. The camera keeps running in its own window.
If that page has closed, changed or can’t be brought forward, choose **Try again**
to check it again. In Look’s separate browser, **Open start page** opens Look’s
local page and makes it the next return destination. The extension refuses this
local-file fallback in your browser; open an ordinary web page there and run
`/look calibrate` again to capture that destination.
Look does not navigate an unrelated tab or reopen the missing page by its URL.

The same camera process, document and video stream stay live behind browsing.
Its retained **Eye tracking** page offers return, recalibration and **Use cursor**.
Closing the last supported browsing tab or waiting for a page to reattach does not
stop the camera while the same approved browser connection remains live. There is
no fixation delivery until a supported foreground page has a measured viewport.
Stop, disconnect, browser-connection replacement and **Use cursor** still revoke
the camera; a later connection cannot inherit it.
In the companion, press **Q** before the first answer, or choose **Eye tracking**
in an answer's footer, to open camera controls and **Use cursor**. Camera/session
loss revokes setup return and stops the corresponding runtime without joining
the camera reader under the inbox lock. The saved calibration remains unchanged.
Focused companion buttons accept trusted Enter/Space input. Those keys never approve
website actions. Status commands do not replace an ongoing setup's connection.
Explicit reconnects do. Restarting a closed camera document gives completion a
fresh setup generation rather than reusing an earlier return attempt.

**Use cursor** is available at entry and on unsuccessful results/recovery.
Camera errors stay on screen with a plain state and **Try again**.
If the window closes or startup returns `stopped`, the command offers
**Try again** with `/look calibrate`. It does not claim calibration is ready.

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
to page CSS pixels is `page.devicePixelRatio / calibration.devicePixelRatio`.
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
The existing Bayesian fusion and temporal alignment resolve the question. The
answering model gets its bounded evidence. Webcam research is read-only. Cursor
mode is permanent and retains its exact-identity path.
Frozen ASR results cannot change the live mode or restore action authority,
including a simulated question completed after switching to webcam. Choosing a
simulated target requires both the saved resolution and the live mode to be simulated.

`tracker.webcam_gaze.GazeEstimator` is the swappable prediction/calibration
boundary. `WebcamHost` accepts an estimator and an observation-runtime source.
The shipped `AppearanceEstimator` has model id
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
cutover. It is one person's recorded footage, not population or live accuracy.
Fake devices prove plumbing only. Broad-region gaze remains experimental, not
button precision or unattended posture reuse.

**Follow-up:** a five-point labelled bias refresh needs a separate live interaction
and validation, especially with glasses. This milestone deliberately requires full
nine-point recalibration after moving instead.

## Hands-on checklist (real hardware: user only)

1. Start a normal Hermes conversation, then `/look`.
2. `/look setup eyes` on first use (may download ~11 MB). Later `/look mode webcam`
   uses verified cached files. Allow **camera only** in the separate tracker window.
   Confirm the camera indicator. No website needs a camera permission.
3. `/look calibrate`: maximize that window and complete the dots and the short
   check. Note the plain result and whether it matched how well it followed you.
   Stay in the same posture and lighting. Try Practise and losing your face.
4. Return to a supported Chrome page. Move the pointer once in its content.
   Leave the pointer elsewhere, look at a broad region, hold Space, wait for
   Listening, and ask about “this”. Judge a roughly 3×3–4×4 region, not buttons.
5. `/look diagnostics`: `samples` should rise, `sample_age_seconds` stay fresh,
   and `delivered` rise while a calibrated Chrome page has focus. Switch tabs,
   seed each once, and repeat. No old tab should acquire the new gaze highlight.
6. Resize/zoom the page: move its pointer once again. Scroll and ask again.
   After moving, leaning back or changing camera position/glasses, recalibrate.
   Record actual successes/errors before making any accuracy or comfort claim.
7. `/look cursor`: confirm the camera indicator goes off and exact cursor
   questions still work. `/look stop` also detaches the companion. Browser tabs stay open.

### When gaze is not fresh

`/look diagnostics` includes cumulative numeric `drops` counters for this tracker
instance, retained across stop/restart. Compare two readings while the companion
page has focus. Old counts from calibration or another application are normal.
No coordinates, features, images or calibration values are included.

Startup regressions use mocked slow assets, cancellation, missing Chrome and
connection races. `tests/webcam_startup_chrome.py` exercises protected recovery
without opening capture devices. `tests/calibration_return_chrome.py` uses fake
video and a synthetic saved fit for camera/handoff checks. These do not establish
real macOS permission behavior, physical camera release timing or live gaze accuracy.

- `no_features`: no usable face/eyes, including blinks.
- `uncalibrated`, `calibrating`: waiting for a profile or collecting calibration.
  These frames intentionally do not become predictions.
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

With a valid page anchor but no fresh delivery, the page says
“Eye tracking isn’t ready. Check /look status.” A size change or pinch zoom gets its own
instruction. Missing gaze still blocks talking. There is no cursor/center fallback.


## Reproducible fake-device proof

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python tests/webcam_chrome.py --out /tmp/hermes-webcam-proof
```

`tests/calibration_chrome.py --out DIR` is headless and exercises every calibration,
check, practice, failure and restart state with a fake camera. Only `predict` is scripted
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
Screenshots and a small results JSON go to the output directory. Calibration and
fake video are temporary and removed.

The appearance-live milestone did **not** run this Chrome probe: another builder
was using private test windows. Schedule it serially before claiming live proof.
The camera window's isolated `__HERMES_WEBCAM__.status()` now exposes aggregate
`frame_ms` (WASM + feature extraction wall time), `feature_ms` (iris + appearance
extraction wall time) and `sample_hz` (processed frames over elapsed inference-start
time). The probe saves those numeric aggregates in `camera_runtime`. None contain
features, coordinates or images. Live per-frame cost and fake-camera sample rate
remain unmeasured until that deferred run. These timers exclude exposure, binding
serialization/delivery and Python prediction. They are not CPU or end-to-end latency.

**Human gaze accuracy, real-camera latency/heat and posture robustness are not
measured by a fake camera.** The 3×3–4×4 target is a design goal, not a result.
