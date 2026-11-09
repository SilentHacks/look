# Hermes Gaze ("Telepathy")

Point or look at a page in Chrome, hold Space, wait for **Listening**, then ask.
Hermes answers in a private card or uses guarded browser actions. Eye tracking is
**beta**: a local, personally calibrated estimate of broad regions, not a precise pointer.

## Install on Mac

Supported lane for this beta: **Apple Silicon Mac, standard Google Chrome in
Applications, one display, English**. Hermes Agent must already be installed and
able to answer a normal message. Metadata requires Hermes `>=0.22.0` and Python
`>=3.11,<3.15`; that is not a claim that every version has been tested. Intel Macs,
Linux, alternate Chrome builds and multiple displays are outside this release lane.

Until a catalogue listing is accepted, install the published GitHub release pin:

```bash
hermes plugins install https://github.com/SilentHacks/hermes-gaze --ref '<RELEASE_SHA>' --enable
```

**Replace `<RELEASE_SHA>` with the release's full forty-character commit SHA.**
This is a clearly marked placeholder, not a published release or a catalogue
availability claim. Do not substitute a branch or install an unreviewed moving head.
Review Hermes's security and dependency prompts; consent to preparing the declared
Python packages through Hermes PM. Do not bypass a dangerous security finding.
If you decline dependencies, the plugin stays disabled; later run
`hermes plugins enable hermes-gaze` and accept preparation. Noninteractive
installs do not imply consent.

If Hermes reports an out-of-sync environment, missing packages or a stale lock,
quit Hermes and run this in the terminal that normally launches it:

```bash
hermes pm install
hermes plugins enable hermes-gaze
```

Restart Hermes afterward. Do not `pip install` into an arbitrary Python or
hand-edit the generated workspace lock. If preparation still fails, keep its
exact error: installing the plugin and successfully enabling its dependencies
are different steps.

## First answer

Launch Hermes from **Terminal or your usual terminal app**, with that app allowed
under macOS **System Settings → Privacy & Security → Microphone** and, for
optional eyes, **Camera**. Permission belongs to the launching app/process; do not
assume granting a website permission fixes native capture. Restart that app after
changing permissions. T3 Code's terminal is not a supported camera launcher.

In the intended Hermes profile's `config.yaml`, merge these settings:

```yaml
plugins:
  isolation: in_process
  entries:
    hermes-gaze:
      allow_gateway_injection: true
```

This changes Hermes's plugin-isolation policy, not just Gaze's appearance. The
guide never changes it silently. Restart Hermes after configuration changes.
The shell `hermes gaze` command needs in-process isolation and does **not** bind
your interactive conversation.

In a new Hermes conversation:

- Enter `/gaze` for the first-run checklist and explicit local recognition setup.
  It discloses downloads without opening Chrome, the camera, microphone or speakers.
  `/gaze setup` reopens it and retries preparation at any time.
- Send a **normal first message**, such as `Reply only Ready.`, and wait for the
  answer. The host cannot prepare a fresh conversation from a Chrome question;
  connecting alone is not enough. No hidden warm-up message is sent for you.
- Enter `/gaze connect` to open the separate companion Chrome. Later `/gaze`
  reconnects without repeating the checklist.
- Use `/gaze mode hover` for cursor mode. Open a page or enter `/gaze demo` for
  the local practice dashboard. **Point at something. Hold Space. Wait for
  Listening, then ask. Let go when you are done.**

Plugin registration **never downloads models**. An already-cached CoreML model is
checksum-verified and silently warmed in the background. The first `/gaze` guide,
or `/gaze setup`, starts missing downloads and shows **Preparing local speech recognition**.
Preparation can compile models; there is no fixed wait guarantee. Check `/gaze setup`
for **Local speech recognition is ready**; hosts supporting plugin messages
also receive a completion notice. Space is refused with a plain explanation until
a model is ready, without opening the microphone or waiting on preparation.
If recognition is preparing or your microphone is unavailable, **Right Option**
opens protected typed questions. Text fields and **keyboard-focused controls**
keep native Space: click ordinary page text before trying to talk. A tap scrolls.
**Q** recalls answers; **Esc** stops or dismisses; holding Space on an answer asks
a follow-up. Failure cards offer **Try again**, **Skip**, or **Continue with the rest**.

Connected conversations use guarded browsing tools instead of raw terminal,
code, generic browser or delegation tools. `/gaze disconnect` restores ordinary
Hermes tools. Send, Buy, Delete and similar actions need your mouse click on the
protected review card; speech and gaze cannot approve them. Stop does not undo
typing or navigation already performed.

### Try eyes, beta

After a useful cursor answer, explicitly enter `/gaze calibrate`. It switches to
webcam mode and opens the separate local camera window. Click **Start calibration**
(**Calibrate again** for a saved setup). Look at each dot, tap Space, and keep looking
until it moves. After nine accepted targets, **Ready to check** waits for your
**Start accuracy check** action before ten checks. **Check** tests a saved setup
directly without replacing it.
`/gaze mode webcam` opens the same flow. Move the pointer once in every page,
and again after zooming or resizing. Use one display, good light and broad page
regions; recalibrate after moving or changing camera, posture or glasses.
No real-camera population accuracy has been established. `/gaze tracker stop`
stops tracking and returns to cursor. See [webcam setup and limits](docs/WEBCAM_GAZE.md).

### Optional read aloud

Silent answers do not need speech-output assets. To download the pinned local
Phonon voice, without playing sound, quit Hermes and run:

```bash
hermes gaze setup-speech
```

Restart Hermes, obtain an answer and choose **Read aloud** when you want sound.
The model is approximately 65 MB plus its voice files; assets stay in
`${XDG_CACHE_HOME:-~/.cache}/hermes-gaze/phonon`. Automatic reading starts off.
Missing or unusable assets can select macOS `say` before any audio starts.
See [offline read-aloud details](#offline-read-aloud-setup).

## Privacy and limits

Local camera does **not** mean local questions or page context. Live tracking
keeps camera images and numeric eye features local and does not save video.
Calibration is sensitive and saved locally. The separate development recorder
can save video only when explicitly started; it is not part of this guide.
The microphone opens only while talking. Recognition is local; model preparation
can download assets. Failed recordings can remain in memory for transcription
retry until the plugin exits. The macOS MLX recognition fallback writes a
temporary WAV and normally deletes it after recognition; a crash or failed
deletion can leave that audio in the operating system's temporary folder.

Your transcribed or typed question and bounded page evidence go to the model
configured in Hermes. **Hermes can retain page context in conversation history
(`state.db`), even when plugin replay recording is off.** Provider retention
depends on your provider. Optional early highlighting, when enabled with a
TypeSafe key, also sends TypeSafe the question and static structural scope
descriptions; extra page text is off by default. Details follow below.

This is bounded page structure, not universal screen vision. Cross-origin
frames, canvas and unknown custom widgets may be unavailable. Detached targets
fail rather than being guessed. Eye estimates cannot replace precise controls
or certify accessibility. The companion is a separate browser profile: existing
Chrome sign-ins are not automatically shared.

### Runtime downloads

All sizes below are approximate decimal payload sizes from publisher metadata, not
measured transfers; package installation, cache and compilation overhead are additional.
ASR and Phonon inputs are pinned in [`assets.json`](assets.json), with a SHA-256 for
every selected file. Setup verifies cached bytes before fetching only missing files;
runtime loaders use local paths only and verify before native loading. A checksum
failure stops preparation, not a silent fallback or automatic replacement.
Small cached graph/config/tokenizer SHA-256 values were computed after matching the
recorded immutable Git blob IDs; weight checksums come from publisher LFS metadata.

| Download / publisher | Trigger | Immutable revision / integrity | Approximate size | Cache / licences |
|---|---|---|---|---|
| Parakeet v2 CoreML, FluidInference conversion of NVIDIA | Explicit recognition setup; preferred macOS backend | [`ee09c569f73759e6d44c9bd16766f477b2b36d39`](https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v2-coreml/tree/ee09c569f73759e6d44c9bd16766f477b2b36d39); SHA-256 manifest | 465 MB, 21 selected files | Shared HF hub; weights CC-BY-4.0, vendored runner MIT |
| Parakeet v2 MLX, mlx-community conversion of NVIDIA | Same explicit setup, only if CoreML unavailable on macOS | [`8ae155301e23d820d82aa60d24817c900e69e487`](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v2/tree/8ae155301e23d820d82aa60d24817c900e69e487); SHA-256 manifest | 2.47 GB | Shared HF hub; weights CC-BY-4.0, runtime Apache-2.0 |
| faster-whisper base.en / tiny.en, SYSTRAN conversion of OpenAI | Explicit setup on Linux, or after both macOS backends unavailable | base.en [`3d3d5dee26484f91867d81cb899cfcf72b96be6c`](https://huggingface.co/Systran/faster-whisper-base.en/tree/3d3d5dee26484f91867d81cb899cfcf72b96be6c), tiny.en [`0d3d19a32d3338f10357c0889762bd8d64bbdeba`](https://huggingface.co/Systran/faster-whisper-tiny.en/tree/0d3d19a32d3338f10357c0889762bd8d64bbdeba); SHA-256 manifest including required tokenizer | 148 MB / 78.1 MB | Shared HF hub; converted weights/runtime MIT |
| Phonon-31M English q8, Gradium | Explicit `hermes gaze setup-speech` only | [`8c64b55ec301728e2d1695bfea87a08a267d0c2d`](https://huggingface.co/gradium/phonon-31m-en/tree/8c64b55ec301728e2d1695bfea87a08a267d0c2d); SHA-256 manifest | 65 MB | Plugin phonon cache; assets Apache-2.0, ptts MIT OR Apache-2.0 |
| Russell / selected English catalogue voice, Gradium | Same explicit read-aloud setup | [`0ee17205f254b5abc43b266c8a0f215565c352f7`](https://huggingface.co/gradium/phonon-voices/tree/0ee17205f254b5abc43b266c8a0f215565c352f7); SHA-256 manifest and pinned English embeddings | 0.26 MB each plus metadata | Plugin phonon cache; Apache-2.0 |
| MediaPipe Tasks Vision JS/WASM, Google npm | Explicit optional webcam start or offline developer evaluation | [0.10.32](https://registry.npmjs.org/@mediapipe/tasks-vision/0.10.32); SHA-256 `b362a2b56aafcce7857047c25dc8fd69612fd8e75018e264717d24290e7815c1` | 23.6 MB unpacked; compressed size unverified | Plugin webcam cache; Apache-2.0 |
| Face Landmarker, Google storage | Same explicit optional webcam setup | [float16 version 1](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task); SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` | 3.76 MB | Plugin webcam cache; Apache-2.0 |

The shared Hugging Face hub defaults to `${HF_HOME:-${XDG_CACHE_HOME:-~/.cache}/huggingface}/hub`;
`HF_HUB_CACHE` (or legacy `HUGGINGFACE_HUB_CACHE`) overrides it. Downloads use the
official `https://huggingface.co` endpoint and may follow publisher storage redirects.
Phonon and webcam use `${XDG_CACHE_HOME:-~/.cache}/hermes-gaze/phonon` and
`webcam-0.10.32`. Warm model caches stay offline. Do not delete shared caches wholesale.

`whisper_model` supports **base.en (default) and tiny.en only**; other aliases,
arbitrary repositories and local custom models are unsupported and rejected before
loading. Each includes a verified local tokenizer: there is no OpenAI tokenizer
fallback download. Backend order remains CoreML v2 → MLX v2 → faster-whisper on Mac.
Fallback preparation can add the listed sizes; recognition never downloads while
holding or releasing Space.

**CoreML v2 is the default, not v3.** V3 is unsupported: its publisher card labels
CC-BY-4.0 in frontmatter but says Apache 2.0 in its body. That contradiction is
unresolved; no v3 weight licence is asserted here. FluidInference publishes the
conversion and references it in FluidAudio; it is not NVIDIA-hosted or evidence of
NVIDIA endorsement. Catalog acceptance of converter-owned CoreML/MLX distributions
still needs a maintainer ruling. See [third-party notices](THIRD_PARTY_NOTICES.md).

Chrome, ffmpeg, CoreML and installed macOS voices are existing local tools, not
installed by this downloader. Python/native dependencies are prepared separately by
Hermes PM; transitive wheel licences and dependency-internal network behavior have
not been audited. The catalog entry PR must repeat these download/network disclosures.


## Daily use, updates and removal

Start Hermes in your permitted terminal app; initialize each new conversation
with a normal message, then `/gaze` to reconnect. Eyes stay an explicit step.
After a gaze-model change, recalibrate when asked; a saved profile is not proof
of today's accuracy.

**Before updating or reloading the plugin, quit Hermes and run
`hermes gateway stop` first.** Hermes runs a background gateway that keeps the old
code loaded even after the terminal closes. Closing and reopening the terminal
alone does not reload Gaze. Stop the gateway before replacing files or repairing
the environment, then restart Hermes and start a new conversation.

`hermes plugins check-updates` checks for updates. A GitHub SHA install is
intentionally pinned: `hermes plugins update hermes-gaze` will not move that pin.
For a new published release, use the same install command with the new full SHA
and add `--force` to replace the old checkout; review the new code and prompts
before doing so. Once installed through an accepted catalogue entry,
`hermes plugins update hermes-gaze` follows its reviewed pin. Restart Hermes and
start a new conversation after updates. `hermes pm install` repairs/prepares
Hermes's environment; it is not a plugin updater or a speech-asset downloader.

Disconnect and quit Hermes before removal:

```bash
hermes plugins remove hermes-gaze
```

Removal is **not forgetting all data**. It does not erase Hermes history, provider
records, shared Hugging Face recognition-model caches, local calibration
(`${XDG_CONFIG_HOME:-~/.config}/hermes-gaze/webcam-calibration.json`), downloaded
Gaze assets under `${XDG_CACHE_HOME:-~/.cache}/hermes-gaze`, or the companion's
Chrome profile/sign-ins under Hermes `plugin-data` (standalone fallback:
`~/.cache/hermes-gaze/chrome-profile`). Plugin first-run state also lives under
Hermes `plugin-data`. Remove only the data you intend to forget; shared caches
may serve other software. Manage Hermes history separately. No automatic purge
or recursive deletion is performed by this plugin.

## Overview

Cursor (`hover`) mode uses exact captured page identities. Webcam beta uses
personally calibrated local left-eye appearance and iris features. Both freeze
evidence at release and align speech with pointing history. The model chooses
semantic scope from the question. Simulated and webcam gaze retain Bayesian
resolution for noisy samples. No real-camera accuracy number is established.

## Architecture

- **Python owns policy.** Simulated and webcam gaze share Bayesian resolution. Hover sends exact cursor evidence to the model, which chooses scope; Python enforces snapshot ownership and action confirmation. The overlay only collects DOM facts and renders results.
- **Persistent CDP sessions.** One isolated-world websocket per supported tab; reads follow focus, while actions retain their captured tab/document. Ordered nonce-bearing binding intents carry questions and native talk controls. No HTTP resolution/action endpoints.
- **Honest failures.** Missing/detached/expired evidence and uncertain click outcomes are reported, never replaced with synthetic targets or silently retried mutations.
- **Pointing modes:** `hover` supplies exact cursor identity and surrounding structure, with explicit snapshot tools for highlighting/actions. `simulated` retains Bayesian noisy-gaze resolution. `webcam` uses local, personally calibrated left-eye appearance and iris features from a separate owned camera window; gaze is read-only evidence, while explicit user action tasks use the guarded DOM tools.
- **Demo page:** a GET-only static server on `127.0.0.1:9111` serves `benchmark/benchmark_page.html` plus `/api/status` (no POST, no CORS). The overlay itself is always injected over CDP, never fetched from a server.

### Cursor context and actions

Hover supplies evidence, not a preselected subject. The model sees the pointed
cell, row/column/table/panel handles, surrounding structural text and separate
controls. Small demo tables include all five rows and six columns; larger tables
prioritize pointed rows, headers and omission counts. System guidance is registered
separately from per-turn `<browser_context>` evidence, which labels the user's
question and pointer age. The complete escaped envelope, including its
`Resolution` epoch, is at most 6000 characters. New guidance requires a new session.

Hovering inside a card also captures its enclosing item and nearest local peer
collection. Semantic items and headed flex/grid children supply separate member
facts, viewport rectangles and exact-node handles; the hovered leaf stays the
only pointer hit. Group headings/notes exclude member text. Hidden variants and
editable values are excluded; rendered offscreen peers are explicitly labelled.
This is bounded DOM/layout evidence, not full visual scene understanding:
unrelated portals and canvas content need another capture strategy.

Typed questions use the latest real Chrome target and its age. Voice evidence
freezes at recording stop before ASR; real word timestamps select preceding
cursor identities, including two spoken referents. Detached or replaced nodes
never rematch selectors. Password/payment fields and associated labels are
filtered before serialization; page text stays inside an escaped untrusted fence.

Fresh hover evidence highlights the pointed handles. On question acceptance,
an asynchronous TypeSafe decision selects the intended captured scope, without
waiting for the answer. Queued items decide from their own frozen evidence;
older answers never replace a newer question's highlight. Missing keys, disabled
early selection or failed decisions use the existing post-answer model call.
A successful `none` leaves the highlight unchanged and skips that fallback.
`gaze_highlight(handles=[...], resolution_id=N)` remains available for explicit
scope changes. Pins follow the original elements through scrolling; background
tabs, replacement documents and superseded requests cannot receive scope changes.
Saved-item comparisons can offer both targets/rows only when both identities are
already in the current capture on the same document. Otherwise highlighting stays
on the selected item's document; comparison evidence can still include both items.

**Browser-action acceptance is not complete:** the earlier forced-direct free
trial scored 3/5 for new-tab email. Final default-dispatch measurement awaits a
free quota reset; [results and resumption](docs/BROWSER_ACTIONS.md#production-measurements).

`gaze_read` starts a separate, turn-owned action capture: bounded structure and
captured field/control identities, never field values. `gaze_fill` batches text,
native selects and contenteditable fields; `gaze_click`, `gaze_press`,
`gaze_open_tab`, `gaze_navigate`, `gaze_scroll` and `gaze_wait` cover the fixed
general vocabulary. No per-site adapters or arbitrary model code. New tabs return
their own structure and become the task target; stale epochs return fresh
structure without replaying the rejected operation.

`gaze_request_commit` shows the existing glass confirmation card, including safe
field content and destination. Submit, Send, Buy, Delete, publish and ambiguous
controls require a trusted primary click. Approval is content-bound and single
use; synthetic events, page/answer text, raw model calls, speech and keys cannot
approve. Esc or the visible Stop cancels further task steps. Unknown mutation
outcomes revoke the task and must not be retried automatically.

Hermes uses its own memory/context for personal details and asks for missing ones.
Password, payment and similar secret fields are never read or written. **A rare
site may act on typing alone; navigation/GETs can also have effects.** This is not
a universal guarantee about site JavaScript. See [browser action policy and
hands-on checklist](docs/BROWSER_ACTIONS.md).

The companion's default endpoint is `127.0.0.1:9333`, not Hermes's browser tool.
Never point `browser_exec`, `browser_cdp`, `BROWSER_CDP_URL`, `BU_CDP_URL`,
`BU_CDP_WS` or Hermes `browser.cdp_url` at it. A connected companion session
removes and vetoes arbitrary code/browser/terminal/delegation tools. Disconnect
with `/gaze disconnect` to use the ordinary Hermes tool surface again. A raw
debugger can synthesize trusted clicks; that authority defeats the private card.

Collection is bounded: 60 seconds/256 cursor intervals, 64 target identities, 32
retained captures, 1024 rows/table, 64 collected columns and 8192 captured members/
handles. Model rows use at most 12 cells, with the pointed value described
separately; column handles retain captured members, never replacement cells.
Card groups search at most eight ancestor levels and 128 children per container;
they retain 16 members (more only to preserve pointed items), with visible peers
first. Collection caps and packet omissions are explicit; capped membership
counts are lower bounds.
Scope navigation, up/down scope correction and save-trial controls are removed.
Replay recording is off unless `record_trials: true`; files may contain sensitive
browsing evidence but never microphone audio.
Hermes also persists injected page evidence in `state.db` (`api_content`),
independently of plugin replay recording.

#### Technical disclosure: early-highlight network use

`early_highlight` defaults to `true`, with `highlight_model: "jev-1.14.0"`.
With `TYPESAFE_API_KEY` in the Hermes process environment, one HTTPS request goes
directly to `https://api.typesafe.ai/v1/systemone` per accepted hover question.
It sends the question (which can itself contain sensitive text), native pointer
role, referent count, available semantic scopes and frozen static descriptions.
`highlight_include_page_text` defaults to `false`: no independently collected
page text, titles, values, URLs, handles, geometry or pointer timestamps are sent.
Opting in adds the existing escaped, bounded (≤6000-character) captured evidence
packet, including page text/values, sanitized URLs and short evidence handles.
No audio, cookies, credentials or live DOM identities are sent in the payload.
The API key is read only from the environment and used in the Authorization header.
The 1.5-second decision deadline never waits on answer generation. Returned labels
map locally to frozen handle arrays and can only highlight, never authorize actions.
There is no second decision provider. Failure uses the existing configured Hermes
model and its existing evidence flow; provider retention is not established here.

Hermes loads `~/.hermes/.env`, not this repository's `.env`. To use a key kept only
in the repository without moving or copying it, export `TYPESAFE_API_KEY` from that
file into the launching shell's environment, without printing it, and start a new
Hermes process from that shell. Existing Hermes processes do not inherit later exports.


Run `node tests/cursor_context_dom.js` and
`python3 -m unittest discover -s tests -t .` for deterministic checks.

### Connect Chrome voice to Hermes

Use in-process plugin isolation and grant injection in the intended profile:

```yaml
plugins:
  isolation: in_process
  entries:
    hermes-gaze:
      allow_gateway_injection: true
```

Restart Hermes after changing plugin code or configuration, and start a new
conversation so frozen system guidance is refreshed. Send one normal message
first (for example, `Reply only Ready.`); the host cannot accept injected Chrome
turns until its lazy agent is initialized. Run `/gaze` or `/gaze connect` in that
conversation to open/attach the dedicated Chrome companion; `/gaze demo` opens
the dashboard if wanted.
Hold Space in Chrome, wait for **Listening**, speak and release. Native
`sounddevice` capture opens only during talk and closes on release; switching
tabs while recording cancels it. macOS microphone permission belongs to the app
hosting Hermes (for example Terminal), not Chrome or the website. Only your
words become a normal user message; the matching session hook attaches frozen
page context. Answers stream into Hermes and the foreground supported Chrome tab.
The inbox survives navigation in memory; highlights/actions never move to an
unrelated tab or replacement document.
Refreshing cursor evidence through a tool does not interrupt that turn's answer stream.
Followups without a fresh capture use conversation history without reattaching old
evidence or changing its epoch. A connected non-deictic utterance without a target is delivered
as plain text. After compaction, resolving again captures the current cursor, not
the historical target. `/gaze disconnect` revokes pending and active action ownership;
it does not cancel a Hermes turn already accepted by the host.

Release freezes browser evidence and seals PCM before transcription. Expensive
release work now waits for acknowledgement of that release's protected-frame
capsule render (or Listening removal on a follow-up), not merely inbox publication.
Gaze resolution, native stream stop/close and ASR therefore follow the first UI push.
The wait and publication hold neither microphone nor callback-buffer locks; session
rebind retains its safe lock order. New input is refused until shutdown finishes.
Sealing retains every already-admitted callback buffer and its device status;
callbacks after sealing cannot append or invalidate sealed speech. An unavailable
release renderer fails capture after the five-second CDP window and still closes input.
Hint persistence follows stop/reservation on the ordered intent worker. Capsule
placement and visual design are unchanged. Cached CoreML prewarm still runs one
silent prediction before sharing the runner; uncached preparation is explicit.

`/gaze timing` works without recording opt-in or a connected browser. It retains
the last eight releases in memory: browser keyup (zero), evidence start/freeze/send;
Python binding/worker receipt, microphone/PCM lock waits and seal, release-render
wait/start/acknowledgement, capture resolution, inbox/approval/publication stages,
native stop/close, ASR lock/model/inference stages, injection and first matching delta.
Browser and Python clocks are separate: subtract stages within their own group,
never across groups. Missing stages have not happened (or that path was not used).
The first UI push is a completed CDP render, not proof of a painted frame.
No audio, transcript, page data, coordinates or browser/request identifiers enter
the trace. `/gaze timing` explicitly saves its full JSON to a private
`~/.cache/hermes-gaze/release-timing.json` file and prints its path with a short
summary; it is never sent to Chrome/model providers.

A 20 ms Python heartbeat runs only while releases are being measured, through their
first delta or failure/completion. It retires after the final sample; disconnect and
plugin unload stop unfinished measurements, and reload retires the previous worker.
It reports each turn's maximum scheduling gap plus the maximum across measured
releases in this process, not idle time before the first release. At 500 ms the
same worker takes one all-thread Python stack sample: file basenames, function
names and line numbers only, at most 64 frames per thread. No locals, arguments,
source lines or exception text are captured. `slow_release` includes the sample
time, last observed/current stage, scheduling gap and whether completion preceded it.
A native call retaining the GIL delays this Python watchdog too; a late sample
must not be mistaken for the stack during the stall.

A delayed-render plus two-second GIL-holding fake reproduced a 2,032 ms processing
push before the render barrier and 105 ms after it. Ordinary blocked stop/close/ASR
alone did not reproduce it. This establishes an ordering defect, not the cause of
the user's physical-device freeze or a regression caused by `b569aec`. The first
release update is protected; later GIL-held work can still stall Python interaction.
See [the statement-order trace, lock analysis and hardware diagnostic limits](docs/RELEASE_FREEZE.md).

Device-free synthetic 3-second PCM through the real, offline CoreML path on
2026-11-08: first process load/transcription 29,834 ms, heartbeat max gap 19.8 ms;
warm transcriptions 76.5/78.2 ms, gaps 12.5/12.5 ms. A later fresh process after
those cache/compile effects took 1,584.7 ms (model ready 1,506.5 ms), max gap
128.1 ms; warm runs 77.6/75.3 ms, max gaps 12.5 ms. These are not an ASR
before/after speedup: neither run demonstrates a multi-second GIL stall. No model
download, microphone, camera, speaker or live Hermes was used; ASR remains
in-process because isolation is not justified by this evidence.

The blocked-close regression originally published no transcribing inbox state
within 200 ms; after sealing PCM and moving reservation ahead of shutdown it
published in 0.4–0.8 ms, while close remained blocked. In private headless Chrome,
the capsule was visibly populated in 70/83/90 ms while fake stop/close/ASR were
blocked for roughly 500 ms. Page timers, scrolling and typing remained responsive
on a 10,000-paragraph local page; heartbeat gaps stayed below 26 ms. These probes
exercise failure isolation, not physical PortAudio latency or the reported freeze.

Private headless Chrome measurements against `d2f6657`, using synthesized
“Explain this region” PCM in a fake native input, real offline CoreML, and a
scripted host (50 ms thinking, 10 ms per word). Five warm captures per build;
the first capture after loading is reported separately. Browser timestamps use
`performance.timeOrigin + performance.now()`; Python uses wall-clock milliseconds.

| Stage, milliseconds | Before | After |
|---|---:|---:|
| Evidence freeze, median duration | 0.2 | 0.4 |
| Binding → intent worker, median | 31.4 | 0.1 |
| Release → microphone closed, median | 32.4 | 1.3 |
| Microphone stop/close, median duration (fake device) | 0.011 | 0.013 |
| Release → processing words in private renderer, median | 27.8 | 10.6 |
| Release → ASR started, median | 37.2 | 17.8 |
| PCM decode, median duration (16 kHz; no resampling) | 0.6 | 1.0 |
| Cached runner lookup, median duration | 0.002 | 0.003 |
| ASR inference, median duration | 100.1 | 103.3 |
| ASR worker startup, median | 0.09 | 0.14 |
| First inbox delivery, median duration | 31.0 | 11.0 |
| Scope activation, median duration | 0.9 | 0.8 |
| Release → host injection, median | 142.7 | 127.5 |
| Release → first host text delta, median | 197.8 | 182.4 |
| Release → first answer words in private renderer, median | 299.4 | 285.3 |
| First speech inference after load | 188.4 | 101.7 |
| First capture → answer words after load | 404.2 | 289.1 |

This improves release feedback and first-use inference, not steady-state model
speed. Cached-model process initialization measured 459 ms before and 467 ms after,
including the new prediction warmup. Registration runs cached warmup on a daemon.
Those historical runs allowed a question to wait on the loader lock; current Space
admission refuses capture until readiness, rather than waiting. These runs
did not measure an uncached model download/ANE compile, hardware close time, or
live Hermes/provider TTFT. Native capture is already 16 kHz; raw PCM avoids
ffmpeg and resampling. The measured worker and loader waits were uncontended.
Inbox delivery performs foreground/document checks over CDP; discovery's 250 ms
poll is only a retry/recall path, not normal streaming delivery. Input watchdog
polls (100 ms) and voice-level updates (40 ms) are independent of release.
The 80 ms stream-update cadence, bounded 500 ms title decision and existing
card motion remain unchanged. FIFO, terminal-hook admission and source ownership
are unchanged.

A blocked fake scope provider still allowed injection at 24 ms and visible answer
words by 202 ms; its deadline completed at 1,524 ms after release-command dispatch.
The 1.5-second scope decision does not block admission. This isolated check used
stub transcription and no provider network request.

Consolidation verification used fake devices and serial private Chrome runs:
199 unit tests, changed-JavaScript syntax, security and recording-hold regressions,
webcam handoff/calibration, and all eleven UI probes (including card sizing) passed.
One headless default recorder session completed at 102.6 seconds with every phase;
its 252 reading frames included 48 settling frames across all four line starts.
No real-camera accuracy, live provider timing or physical-device latency is claimed.

The companion uses glass cards and text-free pointing rings, with nothing idle
apart from a one-time first hint. **Q** recalls the answer stack; **Right Alt**
(or your configured shortcut) opens protected question entry. **Escape** dismisses
settled answers. On a card, or within 90 px of the last pointing anchor, hold Space
to ask a follow-up; pointing elsewhere asks a new question.
Cards keep question/answer history, bounded scrolling, Retry/Skip/Resume and
mouse-only approval. Answers take reading turns (12 seconds by default, longer
for long text); hovering, selecting, scrolling or reading aloud holds the card.
A new question can yield a settled card to its answer's first words, silently.
New and recalled cards open at the conversation's beginning. Streaming never
follows the bottom: manual scroll, selection and focus stay put, including when
follow-ups or retries append to an open card.

First-use layout waits for the protected frame's first measurement instead of
showing a 64px placeholder. The frame observes settled layout too: measuring only
inside render missed later frame-width/text-metric changes and left the host
clipping a taller answer until another delta arrived. The former bottom-follow
flag also moved the opening out of view on every streaming update.
`HERMES_DISABLE_LAZY_INSTALLS=1 .venv/bin/python tests/ui_review/probe_first_answer.py`
reproduces delayed frame readiness and delayed font metrics in private Chrome,
then checks long streaming, manual reading, follow-up, Retry and Q recall.

Read aloud uses local **Gradium Phonon-31M English**, catalogue voice **Russell**,
through native streaming output. Stop, Esc, another read request and disconnect
cancel generation and buffered playback. Automatic reading of completed answers
is explicitly enabled per plugin session and starts off. No answer text goes to
a provider or website. Missing dependencies/assets or a model-load failure select
macOS `say` before audio starts; the card reports that fallback and its reason.
There is no mid-answer voice switch. See [offline speech setup](#offline-read-aloud-setup).

System sans-serif and monospace fonts are referenced, never bundled or downloaded.
Glass follows the page's light/dark background; reduced motion disables movement,
and reduced transparency uses a solid accessible surface.

Without a connected session, read-only one-shot answers still appear, without
saved conversations or actions. Action requests fail instead of using that fallback.
ASR file downloads remain quiet without suppressing errors or redirecting output.
Browser-supplied compressed audio still requires `ffmpeg` on Hermes's PATH
(or in a standard macOS location), with MIME type preserved through decoding.
Native microphone PCM/WAV uses the in-process fast path and does not require
`ffmpeg`. Decoder failures report the real diagnostic, never reinterpret
compressed bytes as PCM.

### Offline read-aloud setup

Run `hermes gaze setup-speech` from your permitted terminal app after installing
and enabling the plugin through Hermes PM. It downloads the pinned q8 model
(approximately 65 MB) and Russell embedding without opening an audio device.
This shell command needs in-process plugin isolation, as does the companion.
Alternatively, run the installed plugin's `scripts/setup_speech.py` with the
Hermes environment's Python; that script does not import Hermes.
Setup and Hermes must use the same OS user/cache root. Restart Hermes afterward.

The plugin setting `tts_voice` defaults to `Russell`. To change it, first run
`HERMES_DISABLE_LAZY_INSTALLS=1 hermes gaze setup-speech --voice NAME`, then set
`tts_voice: NAME` in the existing plugin config. Only downloaded English catalogue
voices are available. No model setting, hosted TTS, cloning or prewarm is needed.
Model revision: `8c64b55ec301728e2d1695bfea87a08a267d0c2d`;
voice catalogue revision: `0ee17205f254b5abc43b266c8a0f215565c352f7`.
The 31M model/tokenizer/voices are Apache-2.0; the runtime is MIT OR Apache-2.0.
Do not substitute the noncommercial 40M models. Apple fallback audio is not
established as cleared for publishing in a demo video.

Hands-on audible check (user only):

1. Connect with `/gaze connect`, obtain an answer, choose **Read aloud**. Confirm
   the card says **Reading with Phonon · Russell** and the voice is Russell.
2. Start a long answer, stop it, then read another answer. Confirm immediate silence
   on Stop and no overlap, old words or stale reading state on replacement.
3. Start again and press Esc. Confirm speech stops and the card dismisses.
4. During speech enter `/gaze disconnect`. Confirm silence; reconnect and read again.
5. Enable automatic reading; complete a new answer. Confirm it reads once, not while
   streaming. Disable it and confirm the next completed answer remains silent.
6. Start talking while an answer is reading. Speech closes before the microphone
   opens; wait for **Listening**. Read aloud is blocked while talking, and answers
   completed during the hold stay silent. Read them explicitly after release.
   If output cannot stop within one second, capture fails rather than overlapping it.

No-speaker regression: `python3 -m unittest tests.test_speech tests.test_voice_turns`.
With `ptts` and assets installed, run `python tests/phonon_smoke.py`: real Russell
generation into a paced fake sink, first-chunk timing and <100 ms cancellation.
On macOS, prefix it with
`sandbox-exec -p '(version 1)(allow default)(deny network*)'` to prove offline use.


Development smoke: use Python from a Hermes environment:

```bash
python benchmark/probe_sessions.py --prompt-only --trials 10 --sources tui --require-pass --output /tmp/gaze-prompts-neutral.json
python benchmark/probe_sessions.py --prompt-only --repo-folder --trials 10 --sources tui --require-pass --output /tmp/gaze-prompts-repo.json
```

The session harness's `--prompt-only` path checks real TUI and desktop **backends**,
not the native desktop renderer or physical microphone, using private config,
credential copies and Chrome. Its historical default voice flow targets the retired
open-shadow HUD; use `benchmark/probe_companion_ui.py` for the current protected UI.
Prompt-only mode uses fresh sessions and the configured model for headers, a cell,
a button, a wider-scope followup, hostile page text, a synthetic stale cursor,
pasted code and an explicit plugin question. `--repo-folder` enables project rules;
the default uses a neutral folder. Reports retain answers, captures and browser
operations; `--plugin-root` can select an isolated committed baseline.
Prompt-only questions remain the first user request in each fresh session.
`--turn-interval 6` spaces submissions for free-model quotas. Provider errors and
240-second terminal-response timeouts remain failed trials, not fallback answers.
Obsolete Phase 0/1 raw results and the open-shadow `probe_phase1.py` harness are
retained in git history, not the installable tree. Current security/evidence
regressions live in `tests/` and `tests/ui_review/`.


## Development commands

The first-run route is above; simulated gaze and benchmarks are development
tools, not steps a newcomer needs for a first answer.

```text
/gaze setup                Prepare pinned local recognition and show readiness
/gaze demo                 Open the local dashboard in the companion
/gaze mode simulated       Explore noisy-gaze simulation
/gaze tracker              Inspect eye-tracking state
/gaze benchmark            Run the simulated accuracy benchmark
```

```bash
# from the shell
hermes gaze demo
hermes gaze benchmark
python3 -m unittest discover -s tests -t .  # full suite; no Chrome needed
```

Installation verification uses Hermes's real validator and package manager with
temporary `HOME` and `HERMES_HOME`, a local Git commit pin, explicit dependency
consent, and a fresh-process enabled-state check. This proves the local manager
path, not a yet-unpublished GitHub release pin or catalogue acceptance.
Private headless Chrome checks use fake devices and scripted answers; they do
not prove macOS permission dialogs, physical audio, real-camera accuracy or a
first live answer from a provider. Those remain user-operated release checks.

## Documentation

- **[AGENTS.md](AGENTS.md)**: contributor guide for coding agents — module map, architecture invariants, test & lint commands, known limits.
- **[docs/PLAN.md](docs/PLAN.md)**: historical technical specification and roadmap; not a current release promise.
- **[docs/PRIOR_ART_AND_PITCH.md](docs/PRIOR_ART_AND_PITCH.md)**: historical research and pitch; catalogue and accuracy claims are not release evidence.
- **[docs/DEMO_AND_SUBMISSION_PLAYBOOK.md](docs/DEMO_AND_SUBMISSION_PLAYBOOK.md)**: historical demo/submission draft; not proof of catalogue availability.
