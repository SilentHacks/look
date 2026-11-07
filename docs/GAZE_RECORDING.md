# Record our gaze dataset

**User-operated real camera only. Agents must use fake devices.** This is a
standalone recorder, not Hermes or the companion. It never touches ordinary Chrome,
uses no microphone, makes no hosted-model/API calls and uploads nothing.

## 1. Setup once

Current host: macOS with Google Chrome in `/Applications/Google Chrome.app`.
From the repository root:

```bash
# Skip venv creation/install if this checkout already has the project environment.
python3 -m venv .venv
.venv/bin/python -m pip install 'numpy>=1.26,<3' 'websockets>=12,<16'
brew install ffmpeg
.venv/bin/python scripts/gaze.py record --help
.venv/bin/python scripts/gaze.py data --help
```

No SciPy, ASR packages, Hermes installation, shell function or `PYTHONPATH` is
needed for the dataset tools. The first run prepares the existing checksum-pinned
Apache-2.0 MediaPipe runtime assets; cached assets work offline. Do not run the
hyphenated checkout as `python -m benchmark.gaze_record`: use the wrapper above.

Choose a **random anonymous ID**, e.g. `p-a7c4` (p- plus 4–24 lowercase
letters/digits). Do not use your name, initials, email or a public account handle.
Use the **same ID** for both glasses rounds and later sessions. Use an anonymous,
stable device/camera/display label, e.g. `laptop-front`; use a different label for
a different camera or display. Never put names, contact details or serial numbers
in the device label or notes. Video itself is identifiable face data: an anonymous
ID does not anonymize the face.

Private files live outside the repo at:
`~/.cache/hermes-gaze-eval/recordings/<ID>/<session>/`. Directories are `0700`,
files `0600`. Each session retains original face/background `camera.webm`,
`targets.jsonl` and `recording.json`. The participant folder also holds `consent.json`.
Check free disk space before recording. At 1.5 Mbit/s, allow roughly 30 MB per
150-second session, plus encoder variation. Decoded evaluation frames can be much
larger; never put raw or derived data in Git or a shared/cloud-synced folder.

## 2. First round: six blocks, about 15 minutes + breaks

Clear private material from the background. Fix the laptop and camera, use 100%
Chrome zoom and your usual display brightness. Do not strain or use uncomfortable
light. Run **one command**:

```bash
.venv/bin/python scripts/gaze.py record --person p-a7c4 --glasses glasses --device laptop-front
```

1. A separate private Chrome window opens. A **one-screen consent note appears
   before any camera request** for a new ID: face/background video, target positions
   and anonymous metadata stay local; no audio; optional export; how to delete.
   Choose **I agree — continue**, or **No thanks** to stop without camera capture.
2. Choose **Enable camera** and allow camera only. No microphone permission is
   requested. The camera preview lets you check framing and background.
3. Maximize the window before starting. Read the block instruction. Confirm/edit
   the four condition fields: posture/head, lighting, distance and camera/lid angle.
   Add a short session note if useful: e.g. “screen brightness 60%, glare on right
   lens”. Date/time, ID, glasses, device and actual display/viewport geometry are
   saved automatically. A note is optional; conditions are not.
4. Scroll down to **Start session**. Follow the dot with your **eyes**, not the
   pointer. Blink naturally. Keep the window visible and its position/size/zoom
   fixed. Stay in the named posture for the whole session.
5. After 150 seconds, the session saves and a **break screen** names the next block.
   Rest your eyes, restore baseline settings, then make only that block's change.
   The camera preview remains active during breaks, but video is not recorded.
   Start the next session when ready; breaks have no timer.
6. At the final block, the owned window closes and the terminal prints each saved
   path. No live gaze profile has been changed.

| Block, in order | What to do for the entire session | Recalibration |
|---|---|---|
| `upright` | Normal upright posture, comfortable normal light, usual distance; remember this camera/lid angle. | New 25-location collection |
| `distance` | Lean back comfortably; alternatively move closer. Describe which and approximate distance in the field/note. Keep lid/camera fixed. | New collection |
| `head` | Return to usual distance. Turn or tilt your head **slightly**, hold that comfortable pose and follow with your eyes. Describe direction/tilt. | New collection |
| `light` | Upright again. Lower or brighten the room light comfortably. Describe light direction/level; avoid strong glare or darkness. | New collection |
| `lid` | Restore normal light. Tilt the laptop lid a little **before** starting; describe direction/angle. Keep camera fixed during the session. | New collection |
| `no-recalibration` | Restore baseline lid, display/window size and light; lean back slightly. Keep the new distance while following. | **Earlier complete upright session with the same ID/glasses/device**, no new calibration |

All sessions are 2.5 minutes by default (`--duration 120` through `180` is allowed).
The fixed calibration is a **random-order 5×5 grid near the screen edges**, about
1.2 seconds per target, first .35 seconds excluded for settling. This supports
9/16/25-location experiments on retained frames. A matched nine-target validation
probe follows calibration; later come randomized held-out fixed targets, moving
targets, reading-style sweeps, and **the same short validation probe at the end**.
Validation is never used for fitting. The no-recalibration block replaces the
initial calibration time with additional tests. Session duration scales the timing
proportionally; use the default for comparable human collections.

The no-recalibration baseline must have compatible viewport/display dimensions and
DPR. If the screen says no compatible baseline, restore the original window size
or record another upright block first. Cross-condition evaluation also deliberately
ignores each changed block's own calibration, so you get both freshly calibrated
and no-refit comparisons without recording another protocol.

### Optional measured physical geometry

Pixels and region hits need no ruler. For approximate angular errors, provide all
three measurements (full display width/height and eye-to-display distance in mm):

```bash
.venv/bin/python scripts/gaze.py record --person p-a7c4 --glasses glasses --device laptop-front \
  --width-mm 302 --height-mm 196 --distance-mm 600
```

Replace example measurements with yours. A per-session distance input then appears:
**measure/update it after posture/distance changes**, not just the first session.
The recorder scales full-display dimensions to the viewport. This is a centered
viewer approximation, not measured head pose. Omit measurements if uncertain;
angular error will honestly be `N/A`.

## 3. Stop, select blocks, resume

At any break choose **Stop here — resume later**. Rerun the exact same command:
completed blocks with that ID/glasses/device are skipped; remaining blocks resume
with instructions. Consent is remembered for the ID. Nothing overwrites a session.

To do only part of the protocol:

```bash
.venv/bin/python scripts/gaze.py record --person p-a7c4 --glasses glasses --device laptop-front \
  --blocks upright distance head
# Later, select the rest (or rerun the full command):
.venv/bin/python scripts/gaze.py record --person p-a7c4 --glasses glasses --device laptop-front \
  --blocks light lid no-recalibration
# Repeat a completed block, retaining the previous session too:
.venv/bin/python scripts/gaze.py record --person p-a7c4 --glasses glasses --device laptop-front \
  --blocks upright --repeat
```

**Esc during a session** saves a partial video and offers retry or stop. Hiding or
moving/resizing the window also ends that session early rather than keeping wrong
target geometry. Partial sessions are retained but do not count toward resume or
batch scoring. Closing Chrome/interrupting Python during recording may leave an
unfinalized file; it is not accepted as a complete session. Rerun to retry. Prefer
stopping at a break so the video has finalized. An abrupt disk/encoder failure can
leave an unfinished session; it never turns into a fabricated complete one.

## 4. Second round: without glasses

Take a longer break if needed, remove glasses, restore baseline setup, then use the
**same anonymous ID and device**, changing only eyewear:

```bash
.venv/bin/python scripts/gaze.py record --person p-a7c4 --glasses none --device laptop-front
```

Repeat the six blocks. Do not skip baseline: the no-recalibration block must reuse
an earlier baseline **in this eyewear state**. This makes about 30 minutes of video
across both rounds, plus breaks; split across days if you prefer. Record contacts
as `--glasses contacts`, not `none`. Date/time preserves the order; glasses transfer
is evaluated from the earlier eyewear round to the later one, with its source ID
reported. A later repeat can test the opposite temporal direction.

## 5. Inventory, load and score

```bash
CACHE="$HOME/.cache/hermes-gaze-eval"
.venv/bin/python scripts/gaze.py data list --person p-a7c4
.venv/bin/python scripts/gaze.py data load --person p-a7c4 --stride 2 --out "$CACHE/p-a7c4-frames"
.venv/bin/python scripts/gaze.py eval extract "$CACHE/p-a7c4-frames/manifest.json" --out "$CACHE/p-a7c4-features"
.venv/bin/python scripts/gaze.py eval score "$CACHE/p-a7c4-features/features.json" \
  --points 9 16 25 --protocols same-session cross-condition cross-glasses --out "$CACHE/p-a7c4-scores"
# Compare all existing candidate configurations; does not change live defaults:
.venv/bin/python scripts/gaze.py tune "$CACHE/p-a7c4-features/features.json" \
  --points 9 16 25 --out "$CACHE/p-a7c4-tuning"
```

Read `SCOREBOARD.md`, `results.json` and `summary.json` under each score directory.
Headline is **3×3 / 4×4 / 5×5 region hit rate**, missing/off-screen predictions are
misses. Rows identify person/condition/glasses and calibration source. End-validation
errors and bias shift are in `results.json`. Insufficient samples, poor fit or no
compatible earlier source is `unscorable`, never a fake score or hidden refit.

To score **everyone**, omit `--person` on `data load` and choose a new output path;
then run `eval extract`, `eval score` and optionally `tune` on its manifest as above.
The generated scoreboard includes equal-person cross-person summaries while
keeping conditions/eyewear separate. Use new output directories after new recordings
or imports; old extracted manifests are not an auto-updating database.
See [GAZE_EVAL.md](GAZE_EVAL.md) for separation, metrics and estimator details.

## 6. Export, transfer and import

One person, all finalized sessions (including clearly marked partials), raw video
and target timestamps plus consent; no fitted model or machine-local frame paths:

```bash
CACHE="$HOME/.cache/hermes-gaze-eval"
.venv/bin/python scripts/gaze.py data export --person p-a7c4 --out "$CACHE/p-a7c4.zip"
# On this or another machine, from its repository root:
.venv/bin/python scripts/gaze.py data import "$CACHE/p-a7c4.zip"
.venv/bin/python scripts/gaze.py data list --person p-a7c4
```

Copy that **sensitive face-video ZIP** only through a trusted/private channel the
participant agrees to. It is not encrypted by the recorder; use an encrypted disk
or encrypted transfer. Exports never overwrite an existing path. Imports reject
unsafe paths, symlinks, missing source sessions and conflicting IDs/session files;
an identical reimport is safe. Bundles are limited to 4 GiB on import. Each person's
ID must be unique across machines; do not reuse an ID assigned to someone else.
Keep referenced baseline sessions when sharing no-recalibration recordings.

Optional alternate private roots use `data --root /absolute/private/path COMMAND`
and `record --out /absolute/private/path ...`. Copying/importing does not submit
anything to Hermes or start a camera. Load/extract again on the destination machine.

## 7. Delete / withdraw

Stop the recorder first. Review the exact paths; **these commands permanently
remove this ID's local raw recordings, consent and the per-person derived outputs
created above**. Run only for the participant you intend to delete:

```bash
CACHE="$HOME/.cache/hermes-gaze-eval"
rm -r -- "$CACHE/recordings/p-a7c4"
rm -r -- "$CACHE/p-a7c4-frames" "$CACHE/p-a7c4-features" "$CACHE/p-a7c4-scores" "$CACHE/p-a7c4-tuning"
rm -- "$CACHE/p-a7c4.zip"
```

Missing paths may report “No such file”; there is nothing there to remove. Also
delete copies on receiving machines, other exports, shared multi-person derived
frames/features/scores and backups/snapshots where applicable. Rebuild multi-person
outputs from remaining recordings. Deleting originals alone does **not** remove
face PNGs or features already derived/exported. Ordinary deletion is not a claim
of forensic erasure from SSDs or backup systems.

## 8. Onboard another person

1. Give them this guide and the same code revision/runtime. They need macOS Chrome,
   Python, numpy/websockets and FFmpeg, not Hermes or API keys.
2. Assign a fresh random ID such as `p-f9d2`; they retain that ID for both rounds.
   Explain that face video is identifiable and stays on their computer until they
   explicitly export/share it. No coercion; declining opens no camera.
3. Let **them** read/accept the consent screen and operate the camera. Ask them to
   record the same six blocks with their usual glasses, then without (or mark
   contacts accurately), using their own stable camera/display label.
4. They export their ID's bundle. Agree on trusted transfer and retention/deletion
   before copying it to this machine. Import and list it here; keep their device
   geometry/condition labels rather than relabelling them as your laptop.
5. Load everyone's complete sessions and score as above. Cross-person summaries
   compare independent personal fits. No human accuracy claim exists until actual
   consented recordings are scored; fake-device automation is not ground truth.
