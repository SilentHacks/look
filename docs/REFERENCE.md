# Look technical reference

User setup: [README](../README.md). Verification: [CONTRIBUTING](../CONTRIBUTING.md).
Historical measurements are attributed to their original runs, not new release proof.
The development extension has its own [current setup guide](CHROME_EXTENSION.md).

## Stock session and ownership

Stock native input is verified against Hermes source
`2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19`. Look connects only to its own
in-process POSIX gateway through the captured profile's private direct
`gateway.sock`, obtains a one-use interactive ticket, and resumes the command's
exact logical session. Auth never enters Chrome. Missing/unsafe sockets,
fallback socket-pointer layouts, host isolation, remote clients and mismatched
owners are refused. Look starts no gateway or second agent. Other frontends
retain the stock Boolean SDK injector, which cannot observe pre-hook failures.
Use ordinary Hermes input there if Look cannot deliver. Never auto-resend.

Each saved question has one stable submission ID. The existing inbox remains
the only Look FIFO. Native terminal receipts release it, including constructor
failures before hooks. Lost acknowledgements retain an unknown attempt:
`/look` in the **same** conversation reconciles the same ID, never a new-ID replay.
Retry is withheld until a definite terminal/refusal. Stop revokes local
presentation/action authority, not an already admitted Hermes turn. An unresolved
attempt prevents switching conversations. Reset/compaction revoke the binding.
Stale exact questions are withheld by the pre-inference hook. Stock has no
atomic caller-supplied reset/authority fence. This is not a claim of one.

TypeSafe is optional. No key is required for startup or the ordinary answer.
The existing optional post-answer Hermes scope selector can still make an
auxiliary inference. Questions/evidence may persist in Hermes history.

### Use my existing Chrome

Use `/look setup extension`, then `/look start --extension` and connect the
selected tab from Chrome's Extensions menu. See [extension setup](CHROME_EXTENSION.md).
Use `/look start --separate` for Look's separate browser.

See [extension verification](CHROME_EXTENSION.md#verification-and-remaining-gates)
for disposable-browser coverage and user-operated permission checks.

### Commands

|Command|Purpose|
|---|---|
|`/look` or `/look start`|Start/connect in Chrome|
|`/look stop`|Stop capture, camera, read-aloud and overlay. Keep browser tabs|
|`/look status`|Current state, without diagnostic counters|
|`/look calibrate`|Start optional eye tracking from verified cached files|
|`/look cursor`|Stop the camera and return to the pointer|
|`/look setup`|Prepare/retry local recognition|
|`/look setup extension`|Stage the extension/native host for the current Hermes Python|
|`/look start --extension`|Approve one extension connection for 120 seconds. Choose Connect this tab|
|`/look setup extension uninstall`|Remove Look's owned native registration and staged files|
|`/look setup eyes`|Download missing eye-tracking files (~11 MB), then open the camera|
|`/look diagnostics`|Technical connection, recognition, dependency and tracker details|
|`/look diagnostics timing`|Save the recent release traces|
|`/look help advanced`|Practice, simulation, evidence inspection and benchmarks|

Stop affects the machine's shared companion, including a binding from another
Hermes conversation. It removes input interception, revokes action/approval
authority and pauses the inbox. Retained answers remain in memory. It does not
undo typing/navigation or cancel a Hermes turn already accepted by the host.
Start reconnects in cursor mode. Eye tracking always needs an explicit start.
Closing companion tabs alone does not stop the separate camera. `/look status`
reports camera activity even without an attached page. `/look stop` releases both.
In separate-Chrome mode, Stop leaves its local debugging port live until Chrome
exits. It keeps that dedicated profile and sign-ins. It never kills a browser.
Start can reuse that verified browser, including after a Hermes process restart.

**Compatibility:** `/gaze` and `hermes gaze` remain aliases. `connect` means `start`,
`disconnect` now performs the full `stop`, and `tracker stop` means `cursor`.
`timing`, `voice`, `mode`, `resolve`, `listen`, `demo` and `benchmark` remain available.
The plugin/install/config key is still `hermes-gaze`. Public `gaze_*` tool schemas,
caches, Chrome profile, calibration and bundled skill identifiers are unchanged.
Existing configuration and saved calibration need no migration.
Bare `/look` and `/gaze` keep the chosen source for this process. An existing
Chrome reconnect requires explicit acceptance again. Only explicit `setup`
prepares downloads. Detailed tracker counters moved from
ordinary `tracker`/`status` output to `diagnostics`.

After updating the installed plugin, quit Hermes, run `hermes gateway stop`, then
restart Hermes so its command registry and loaded code refresh. A separate installed
copy must be updated first. Editing another checkout does not update it.
No host patch or new manifest command field is needed: slash/CLI names register
through Hermes's public APIs. Under host isolation, shell plugin commands are unavailable.

Plugin registration **never downloads models**. Supported cached models are
checksum-verified and loaded asynchronously in preference order: CoreML → MLX →
configured faster-whisper on native Apple Silicon Mac. Other platforms use configured
faster-whisper. CoreML also runs a silent warmup prediction. Explicit recognition setup tries every usable
verified cache before downloading missing assets, so an offline cached fallback
does not require a preferred-backend download. Integrity failures stop setup
without fallback. Only explicit `/look setup` permits missing downloads
when no cached backend works and shows **Preparing local speech recognition**.
Preparation can compile models. There is no fixed wait guarantee. The connected
page shows a typed-input hint while recognition prepares and announces readiness
when a verified backend finishes loading, including registration's cache-only warmup.
This uses the foreground-owned inbox and does not require Hermes `post_message`.
Explicit setup also reports completion on hosts supporting plugin messages.
Space is refused with a plain explanation until a model is ready, without opening
the microphone or waiting on preparation. ASR readiness is not microphone permission.
If recognition is preparing or your microphone is unavailable, **Right Option**
opens protected typed questions. Text fields and **keyboard-focused controls**
keep native Space: click ordinary page text before trying to talk. A tap scrolls.
**Q** recalls answers. **Esc** stops or dismisses. Holding Space on an answer asks
a follow-up. Failure cards offer **Try again**, **Skip**, or **Continue with the rest**.

Connected conversations use guarded browsing tools instead of raw terminal,
code, generic browser or delegation tools. `/look stop` restores ordinary
Hermes tools. Send, Buy, Delete and similar actions need your mouse click on the
protected review card. Speech and gaze cannot approve them. Stop does not undo
typing or navigation already performed.

### Try eyes, beta

After a useful cursor answer, explicitly enter `/look calibrate`. It switches to
webcam mode and verifies cached files asynchronously before opening the separate camera.
If files are missing, `/look setup eyes` explicitly permits their download and camera startup.
Preparation, window startup, model loading, camera access and failures appear in
`/look tracker` and the protected **Eye tracking** controls. **Use cursor** or `/look cursor`
cancels immediately. A blocked network read may finish later, but cannot open a camera.
Failures keep webcam selected until you choose cursor. No cursor evidence is fabricated.
Click **Start calibration**
(**Calibrate again** for a saved setup). Look at each dot, tap Space, and keep looking
until it moves. After nine accepted targets, **Ready to check** waits for your
**Start accuracy check** action before ten checks. **Check** tests a saved setup
directly without replacing it.
Optional **Try a question** rehearses a silent guided example. **Return to browsing**
or **Skip practice** brings the captured companion page forward while the camera
keeps running behind it. Missing/replaced pages or uncertain focus stay in recovery.
**Open start page** is an explicit owned fallback, not a claim to restore the old page.
Press **Q** before the first answer, or **Eye tracking** in an answer's footer,
for **Use cursor** and the camera window.
`/look mode webcam` opens the same flow. Move the pointer once in every page,
and again after zooming or resizing. Use one display, good light and broad page
regions. Recalibrate after moving or changing camera, posture or glasses.
No real-camera population accuracy has been established. `/look cursor`
stops tracking and returns to cursor. See [webcam setup and limits](WEBCAM_GAZE.md).

### Optional read aloud

Silent answers do not need speech-output assets. To download the pinned local
Phonon voice, without playing sound, quit Hermes and run:

```bash
hermes look setup-speech
```

Restart Hermes, obtain an answer and choose **Read aloud** when you want sound.
The model is approximately 65 MB plus its voice files. Assets stay in
`${XDG_CACHE_HOME:-~/.cache}/hermes-gaze/phonon`. Automatic reading starts off.
Missing or unusable assets can select macOS `say` before any audio starts.
See [offline read-aloud details](#offline-read-aloud-setup).

### Runtime downloads

All sizes below are approximate decimal payload sizes from publisher metadata, not
measured transfers. Package installation, cache and compilation overhead are additional.
ASR and Phonon inputs are pinned in [`audio/assets.json`](../audio/assets.json), with a SHA-256 for
every selected file. Setup verifies cached bytes before fetching only missing files.
Runtime loaders use local paths only and verify before native loading. A checksum
failure stops preparation, not a silent fallback or automatic replacement.
Small cached graph/config/tokenizer SHA-256 values were computed after matching the
recorded immutable Git blob IDs. Weight checksums come from publisher LFS metadata.

| Download / publisher | Trigger | Immutable revision / integrity | Approximate size | Cache / licences |
|---|---|---|---|---|
| Parakeet v2 CoreML, FluidInference conversion of NVIDIA | Explicit recognition setup. Preferred native Apple Silicon backend | [`ee09c569f73759e6d44c9bd16766f477b2b36d39`](https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v2-coreml/tree/ee09c569f73759e6d44c9bd16766f477b2b36d39). SHA-256 manifest | 465 MB, 21 selected files | Shared HF hub. Weights CC-BY-4.0, vendored runner MIT |
| Parakeet v2 MLX, mlx-community conversion of NVIDIA | Same explicit setup, only if CoreML unavailable on native Apple Silicon | [`8ae155301e23d820d82aa60d24817c900e69e487`](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v2/tree/8ae155301e23d820d82aa60d24817c900e69e487). SHA-256 manifest | 2.47 GB | Shared HF hub. Weights CC-BY-4.0, runtime Apache-2.0 |
| faster-whisper base.en / tiny.en, SYSTRAN conversion of OpenAI | Explicit setup on Linux/Intel/Rosetta, or after both Apple Silicon backends unavailable | base.en [`3d3d5dee26484f91867d81cb899cfcf72b96be6c`](https://huggingface.co/Systran/faster-whisper-base.en/tree/3d3d5dee26484f91867d81cb899cfcf72b96be6c), tiny.en [`0d3d19a32d3338f10357c0889762bd8d64bbdeba`](https://huggingface.co/Systran/faster-whisper-tiny.en/tree/0d3d19a32d3338f10357c0889762bd8d64bbdeba). SHA-256 manifest including required tokenizer | 148 MB / 78.1 MB | Shared HF hub. Converted weights/runtime MIT |
| Phonon-31M English q8, Gradium | Explicit `hermes look setup-speech` only | [`8c64b55ec301728e2d1695bfea87a08a267d0c2d`](https://huggingface.co/gradium/phonon-31m-en/tree/8c64b55ec301728e2d1695bfea87a08a267d0c2d). SHA-256 manifest | 65 MB | Plugin phonon cache. Assets Apache-2.0, ptts MIT OR Apache-2.0 |
| Russell / selected English catalogue voice, Gradium | Same explicit read-aloud setup | [`0ee17205f254b5abc43b266c8a0f215565c352f7`](https://huggingface.co/gradium/phonon-voices/tree/0ee17205f254b5abc43b266c8a0f215565c352f7). SHA-256 manifest and pinned English embeddings | 0.26 MB each plus metadata | Plugin phonon cache. Apache-2.0 |
| MediaPipe Tasks Vision JS/WASM, Google npm | Only explicit `/look setup eyes`. Ordinary start and offline evaluation are cache-only | [0.10.32](https://registry.npmjs.org/@mediapipe/tasks-vision/0.10.32). SHA-256 `b362a2b56aafcce7857047c25dc8fd69612fd8e75018e264717d24290e7815c1` | 6.6 MB compressed. 23.6 MB unpacked | Plugin webcam cache. Apache-2.0 |
| Face Landmarker, Google storage | Same explicit optional webcam setup | [float16 version 1](https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task). SHA-256 `64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff` | 3.76 MB | Plugin webcam cache. Apache-2.0 |

The shared Hugging Face hub defaults to `${HF_HOME:-${XDG_CACHE_HOME:-~/.cache}/huggingface}/hub`.
`HF_HUB_CACHE` (or legacy `HUGGINGFACE_HUB_CACHE`) overrides it. Downloads use the
official `https://huggingface.co` endpoint and may follow publisher storage redirects.
Phonon and webcam use `${XDG_CACHE_HOME:-~/.cache}/hermes-gaze/phonon` and
`webcam-0.10.32`. Warm model caches stay offline. Do not delete shared caches wholesale.

`whisper_model` supports **base.en (default) and tiny.en only**. Other aliases,
arbitrary repositories and local custom models are unsupported and rejected before
loading. Each includes a verified local tokenizer: there is no OpenAI tokenizer
fallback download. Backend order on native Apple Silicon remains CoreML v2 → MLX v2 → faster-whisper.
Fallback preparation can add the listed sizes. Recognition never downloads while
holding or releasing Space.

**CoreML v2 is the default, not v3.** V3 is unsupported: its publisher card labels
CC-BY-4.0 in frontmatter but says Apache 2.0 in its body. That contradiction is
unresolved. No v3 weight licence is asserted here. FluidInference publishes the
conversion and references it in FluidAudio. It is not NVIDIA-hosted or evidence of
NVIDIA endorsement. Catalog acceptance of converter-owned CoreML/MLX distributions
still needs a maintainer ruling. See [third-party notices](../THIRD_PARTY_NOTICES.md).

Chrome, ffmpeg, CoreML and installed macOS voices are existing local tools, not
installed by this downloader. Python/native dependencies are prepared separately by
Hermes PM. Transitive wheel licences and dependency-internal network behavior have
not been audited. The catalog entry PR must repeat these download/network disclosures.


## Daily use, updates and removal

Start Hermes in your permitted terminal app and run `/look` in the intended
canonical local conversation. Eyes stay an explicit step.
After a gaze-model change, recalibrate when asked. A saved profile is not proof
of today's accuracy.

**Before updating or reloading the plugin, quit Hermes and run
`hermes gateway stop` first.** Hermes runs a background gateway that keeps the old
code loaded even after the terminal closes. Closing and reopening the terminal
alone does not reload Gaze. Stop the gateway before replacing files or repairing
the environment, then restart Hermes and start a new conversation.

`hermes plugins check-updates` checks for updates. A GitHub SHA install is
intentionally pinned: `hermes plugins update hermes-gaze` will not move that pin.
For a new published release, use the same install command with the new full SHA
and add `--force` to replace the old checkout. Review the new code and prompts
before doing so. Once installed through an accepted catalogue entry,
`hermes plugins update hermes-gaze` follows its reviewed pin. Restart Hermes and
start a new conversation after updates. `hermes pm install` repairs/prepares
Hermes's environment. It is not a plugin updater or a speech-asset downloader.

Stop Look and uninstall its native host with `/look setup extension uninstall`,
then remove Look in Chrome before quitting Hermes/removing the plugin:

```bash
hermes plugins remove hermes-gaze
```

Removal is **not forgetting all data**. It does not erase Hermes history, provider
records, shared Hugging Face recognition-model caches, local calibration
(`${XDG_CONFIG_HOME:-~/.config}/hermes-gaze/webcam-calibration.json`), downloaded
Gaze assets under `${XDG_CACHE_HOME:-~/.cache}/hermes-gaze`, or the companion's
account-scoped Chrome profile/sign-ins at `~/.cache/hermes-gaze/chrome-profile`.
Earlier Hermes-profile Chrome directories stay untouched. Restart every Hermes
process after upgrading the ownership change. Plugin first-run state still lives
under Hermes `plugin-data`. Remove only the data you intend to forget. Shared caches
may serve other software. Manage Hermes history separately. No automatic purge
or recursive deletion is performed by this plugin.

## Overview

Cursor (`hover`) mode uses exact captured page identities. Webcam beta uses
personally calibrated local left-eye appearance and iris features. Both freeze
evidence at release and align speech with pointing history. The model chooses
semantic scope from the question. Simulated and webcam gaze retain Bayesian
resolution for noisy samples. No real-camera accuracy number is established.

## Architecture

- **Python owns policy.** Simulated and webcam gaze share Bayesian resolution. Hover sends exact cursor evidence to the model, which chooses scope. Python enforces snapshot ownership and action confirmation. The overlay only collects DOM facts and renders results.
- **Persistent CDP sessions.** One isolated-world websocket per supported tab. Reads follow focus, while actions retain their captured tab/document. Ordered nonce-bearing binding intents carry questions and native talk controls. No HTTP resolution/action endpoints.
- **Honest failures.** Missing/detached/expired evidence and uncertain click outcomes are reported, never replaced with synthetic targets or silently retried mutations.
- **Pointing modes:** `hover` supplies exact cursor identity and surrounding structure, with explicit snapshot tools for highlighting/actions. `simulated` retains Bayesian noisy-gaze resolution. `webcam` uses local, personally calibrated left-eye appearance and iris features from a separate owned camera window. Gaze is read-only evidence, while explicit user action tasks use the guarded DOM tools.
- **Demo page:** a GET-only static server on `127.0.0.1:9111` serves `benchmark/benchmark_page.html` plus `/api/status` (no POST, no CORS). The overlay itself is always injected over CDP, never fetched from a server.

### Cursor context and actions

Hover supplies evidence, not a preselected subject. The model sees the pointed
cell, row/column/table/panel handles, surrounding structural text and separate
controls. Small demo tables include all five rows and six columns. Larger tables
prioritize pointed rows, headers and omission counts. System guidance is registered
separately from per-turn `<browser_context>` evidence, which labels the user's
question and pointer age. The complete escaped envelope, including its
`Resolution` epoch, is at most 6000 characters. New guidance requires a new session.

Hovering inside a card also captures its enclosing item and nearest local peer
collection. Semantic items and headed flex/grid children supply separate member
facts, viewport rectangles and exact-node handles. The hovered leaf stays the
only pointer hit. Group headings/notes exclude member text. Hidden variants and
editable values are excluded. Rendered offscreen peers are explicitly labelled.
This is bounded DOM/layout evidence, not full visual scene understanding:
unrelated portals and canvas content need another capture strategy.

Typed questions use the latest real Chrome target and its age. Voice evidence
freezes at recording stop before ASR. Real word timestamps select preceding
cursor identities, including two spoken referents. Detached or replaced nodes
never rematch selectors. Password/payment fields and associated labels are
filtered before serialization. Page text stays inside an escaped untrusted fence.

Fresh hover evidence highlights the pointed handles. On question acceptance,
an asynchronous TypeSafe decision selects the intended captured scope, without
waiting for the answer. Queued items decide from their own frozen evidence.
Older answers never replace a newer question's highlight. Missing keys, disabled
early selection or failed decisions use the existing post-answer model call.
A successful `none` leaves the highlight unchanged and skips that fallback.
`gaze_highlight(handles=[...], resolution_id=N)` remains available for explicit
scope changes. Pins follow the original elements through scrolling. Background
tabs, replacement documents and superseded requests cannot receive scope changes.
Saved-item comparisons can offer both targets/rows only when both identities are
already in the current capture on the same document. Otherwise highlighting stays
on the selected item's document. Comparison evidence can still include both items.

Historical browser-action results include a recorded 25/25 local-fixture run with
Beam through stock dispatch. This is not current user-site or live-provider
acceptance. See [the dated evidence and earlier failed trials](BROWSER_ACTIONS.md).

`gaze_read` starts a separate, turn-owned action capture: bounded structure and
captured field/control identities, never field values. `gaze_fill` batches text,
native selects and contenteditable fields. `gaze_click`, `gaze_press`,
`gaze_open_tab`, `gaze_navigate`, `gaze_scroll` and `gaze_wait` cover the fixed
general vocabulary. No per-site adapters or arbitrary model code. New tabs return
their own structure and become the task target. Stale epochs return fresh
structure without replaying the rejected operation.

By default `gaze_request_commit` shows the glass confirmation card with safe field
content and destination. Submit, Send, Buy, Delete, publish and ambiguous controls
require a trusted primary click. Approval is content-bound and single-use.

In the connected conversation, `/look actions allow-all` explicitly turns off
Look's action approval prompts. Requested consequential clicks and
`gaze_request_commit` then execute directly. This can send, buy or delete without
review, including if page instructions mislead the model. `/look actions` and
`/look status` show when prompts are off. `/look actions confirm` restores them.
Changing the mode stops the current task. Ask again to continue.
Reconnecting, switching conversations or stopping resets the mode to confirmation.
It is not saved to configuration.

This skips only Look's approval cards. Chrome, OS, native-input and external
permissions remain unchanged, as do exact session/turn/tab/document/route/epoch
ownership, secret-field exclusions and the ban on raw model browser code.
Esc or Stop cancels further steps. Unknown mutation outcomes revoke the task and
must not be retried automatically.

Hermes uses its own memory/context for personal details and asks for missing ones.
Password, payment and similar secret fields are never read or written. **A rare
site may act on typing alone. Navigation/GETs can also have effects.** This is not
a universal guarantee about site JavaScript. See [browser action policy and
hands-on checklist](BROWSER_ACTIONS.md).

The companion's default endpoint is `127.0.0.1:9333`, not Hermes's browser tool.
Never point `browser_exec`, `browser_cdp`, `BROWSER_CDP_URL`, `BU_CDP_URL`,
`BU_CDP_WS` or Hermes `browser.cdp_url` at it. A connected companion session
removes and vetoes arbitrary code/browser/terminal/delegation tools. Disconnect
with `/look stop` to use the ordinary Hermes tool surface again. A raw
debugger can synthesize trusted clicks. That authority defeats the private card.

Only `http://127.0.0.1:<port>` or `http://localhost:<port>` is supported for
`cdp_url`. Localhost is normalized to the literal loopback address. Remote,
HTTPS, IPv6, credentialed, query and path-based endpoints are rejected before
network access. Discovery ignores environment proxies and refuses redirects.
The companion requires `websockets` 15.x. Upgrade dependencies through the normal
consented plugin update/install if an older environment still has 12–14.

In **separate-Chrome mode**, Look opens a persistent profile apart from personal
Chrome and uses a private launch-identity file plus an exclusive per-profile
runtime lock. Before attachment, it checks that Chrome reports that launch identity,
the exact dedicated profile and configured port. Each page WebSocket verifies
the same identity before bindings/scripts. Page sockets pin the TCP destination
to loopback and reject cross-origin WebSocket redirects. New tabs and discovery
use the verified browser socket, not fresh
HTTP mutations. An occupied port, another runtime, missing identity file or
wrong Chrome fails closed, without injecting or killing the occupant.
Verification uses Chrome's `--enable-automation` command-line reporting. Sites
can detect automation and Chrome may show its automation notice. Site sign-in
compatibility is not guaranteed.

An explicitly configured local `cdp_url` still chooses the companion port. It
is **not** permission to attach an arbitrary existing browser. After upgrading
from the old unverified launcher, quit **only Look's companion Chrome windows**
once, then `/look start`. The same profile/sign-ins remain. For an unrelated
port occupant, leave it alone and configure a free local port. If the dedicated
profile is still open on an old port, close its companion windows before changing
ports. A lost/corrupt identity file cannot safely recover an already-running
browser: close that companion and restart, without deleting profile data.

This prevents accidental endpoint/profile mix-ups. It is **not local attacker
authentication**. Chrome CDP has no authentication: any process able to reach
the loopback port has debugger authority, can read the launch identity, inspect
sign-ins and synthesize trusted input. Same-user/root code can also alter local
files or bypass the advisory lock. Trust local users/processes and filesystem.
Do not forward the port. The identity never enters website DOM/JavaScript, and
the protected renderer remains a website boundary, not a debugger boundary.

No-device ownership regression: `HERMES_DISABLE_LAZY_INSTALLS=1 .venv/bin/python
-B -m unittest tests.test_companion_ownership`. Real temporary-profile Chrome:
`HERMES_DISABLE_LAZY_INSTALLS=1 .venv/bin/python -B tests/companion_ownership_chrome.py`.

Collection is bounded: 60 seconds/256 cursor intervals, 64 target identities, 32
retained captures, 1024 rows/table, 64 collected columns and 8192 captured members/
handles. Model rows use at most 12 cells, with the pointed value described
separately. Column handles retain captured members, never replacement cells.
Card groups search at most eight ancestor levels and 128 children per container.
They retain 16 members (more only to preserve pointed items), with visible peers
first. Collection caps and packet omissions are explicit. Capped membership
counts are lower bounds.
Scope navigation, up/down scope correction and save-trial controls are removed.
Replay recording is off unless `record_trials: true`. Files may contain sensitive
browsing evidence but never microphone audio.
Hermes also persists injected page evidence in `state.db` (`api_content`),
independently of plugin replay recording.

#### Technical disclosure: early-highlight network use

`early_highlight` defaults to `true`, with `highlight_model: "jev-1.14.0"`.
With an optional `TYPESAFE_API_KEY` resolved through Hermes's profile-scoped
`agent.secret_scope.get_secret`, one HTTPS request goes directly to
`https://api.typesafe.ai/v1/systemone` per accepted hover question.
It sends the question (which can itself contain sensitive text), native pointer
role, referent count, available semantic scopes and frozen static descriptions.
`highlight_include_page_text` defaults to `false`: no independently collected
page text, titles, values, URLs, handles, geometry or pointer timestamps are sent.
Opting in adds the existing escaped, bounded (≤6000-character) captured evidence
packet, including page text/values, sanitized URLs and short evidence handles.
No audio, cookies, credentials or live DOM identities are sent in the payload.
The key is used only in the Authorization header, never in page evidence or inbox state.
The 1.5-second decision deadline never waits on answer generation. Returned labels
map locally to frozen handle arrays and can only highlight, never authorize actions.
There is no second decision provider. Failure uses the existing configured Hermes
model and its existing evidence flow. Provider retention is not established here.

Set the optional **TypeSafe API key** in Hermes Desktop → Settings → Plugins →
hermes-gaze. The manifest declares `typesafe_api_key` as `type: secret`, with
`env: TYPESAFE_API_KEY`. Hermes owns credential storage, not plugin settings.
There is no `requires_env` gate or install-time key prompt. Disabled early
highlighting does not read the key or call TypeSafe. Missing keys, unavailable
secret APIs, unbound scopes and request failures use the existing post-answer
Hermes selector. A successful `none` decision does not invoke that fallback.
For this credential, the plugin never reads files or looks up the process environment.
Browser callbacks retain the connecting command's profile context. Keys are
resolved per decision, not cached in snapshots or copied to the browser. Stop
and native binding revocation clear that context. A new connection captures its
own. Late transcription cannot acquire a new connection's key.
This optional integration uses stock Hermes only. No host patch or TypeSafe key
is needed to start Look or ask questions.
See Hermes's [secret settings contract](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins#settings-form-in-the-desktop)
and [catalog rules 6/11](https://github.com/NousResearch/hermes-agent/blob/main/plugin-catalog/README.md#admission-policy).
An optional schema secret is not a required `capabilities.requires_env` entry.



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
conversation so frozen system guidance is refreshed. Run `/look` or `/look start`.
The first real Chrome question initializes the lazy canonical agent. No dummy
turn is sent. `/look demo` opens the dashboard if wanted.
Hold Space in Chrome, wait for **Listening**, speak and release. Native
`sounddevice` capture opens only during talk and closes on release. Switching
tabs while recording cancels it. macOS microphone permission belongs to the app
hosting Hermes (for example Terminal), not Chrome or the website. Only your
words become a normal user message. The matching session hook attaches frozen
page context. Answers stream into Hermes and the foreground supported Chrome tab.
The inbox survives navigation in memory. Highlights/actions never move to an
unrelated tab or replacement document.
Refreshing cursor evidence through a tool does not interrupt that turn's answer stream.
Followups without a fresh capture use conversation history without reattaching old
evidence or changing its epoch. A connected non-deictic utterance without a target is delivered
as plain text. After compaction, resolving again captures the current cursor, not
the historical target. `/look stop` revokes pending and active action ownership.
It does not cancel a Hermes turn already accepted by the host.


Release ordering, bounded capture and historical latency measurements are documented in
[the dated investigation](RELEASE_FREEZE.md). Fake-device timings are not physical-device or provider latency.

The companion uses glass cards and text-free pointing rings, with nothing idle
apart from a one-time first hint. **Q** recalls the answer stack. **Right Alt**
(or your configured shortcut) opens protected question entry. **Escape** dismisses
settled answers. On a card, or within 90 px of the last pointing anchor, hold Space
to ask a follow-up. Pointing elsewhere asks a new question.
Cards keep question/answer history, bounded scrolling, Retry/Skip/Resume and
mouse-only approval. Answers take reading turns (12 seconds by default, longer
for long text). Hovering, selecting, scrolling or reading aloud holds the card.
Each answer in a card retains its first 12,000 characters, not a rolling tail. Longer
answers show a separate plain-text shortening notice, even inside unfinished
Markdown, and read-aloud speaks that notice too. Streaming, completed and recalled
cards use the same bound. Short answers are unchanged. Full responses remain in
Hermes history, outside the card's bounded copy.
A new question can yield a settled card to its answer's first words, silently.
New and recalled cards open at the conversation's beginning. Streaming never
follows the bottom: manual scroll, selection and focus stay put, including when
follow-ups or retries append to an open card.
Code blocks and wide tables scroll horizontally within the card. Vertical wheel
input over either scrolls the answer body, without scrolling the website.

The first answer waits for the private frame’s layout measurement before appearing.
Later size changes update the card without moving your scroll position.
Sizing includes the measured title, notices, footer and 24px plate rounding.
If a long answer has under 300px of reading room, it relocates once to reserve
roughly 60% of the viewport (at least 300px for the body when space permits).
Placement still minimizes target overlap, but may cover part of a large target
rather than leave the answer in a shallow strip. Short answers stay compact.
`HERMES_DISABLE_LAZY_INSTALLS=1 .venv/bin/python tests/ui_review/probe_card_growth.py`
checks a fresh captured comparison at 1440×900 and 800×700, streaming and settled,
including viewport bounds, top/manual scroll and 24px plate geometry.

`HERMES_DISABLE_LAZY_INSTALLS=1 .venv/bin/python tests/ui_review/probe_first_answer.py`
reproduces delayed frame readiness and delayed font metrics in private Chrome,
then checks long streaming, manual reading, follow-up, Retry and Q recall, plus
trusted code/table wheels on both axes during streaming, completion and recall.

Read aloud uses local **Gradium Phonon-31M English**, catalogue voice **Russell**,
through native streaming output. Stop, Esc, another read request and disconnect
cancel generation and buffered playback. Automatic reading of completed answers
is explicitly enabled per plugin session and starts off. No answer text goes to
a provider or website. Missing dependencies/assets or a model-load failure select
macOS `say` before audio starts. The card reports that fallback and its reason.
There is no mid-answer voice switch. See [offline speech setup](#offline-read-aloud-setup).

System sans-serif and monospace fonts are referenced, never bundled or downloaded.
Glass follows the page's light/dark background. Reduced motion disables movement,
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

Run `hermes look setup-speech` from your permitted terminal app after installing
and enabling the plugin through Hermes PM. It downloads the pinned q8 model
(approximately 65 MB) and Russell embedding without opening an audio device.
This shell command needs in-process plugin isolation, as does the companion.
Alternatively, run the installed plugin's `scripts/setup_speech.py` with the
Hermes environment's Python. That script does not import Hermes.
Setup and Hermes must use the same OS user/cache root. Restart Hermes afterward.

The plugin setting `tts_voice` defaults to `Russell`. To change it, first run
`HERMES_DISABLE_LAZY_INSTALLS=1 hermes look setup-speech --voice NAME`, then set
`tts_voice: NAME` in the existing plugin config. Only downloaded English catalogue
voices are available. No model setting, hosted TTS, cloning or prewarm is needed.
Model revision: `8c64b55ec301728e2d1695bfea87a08a267d0c2d`.
Voice catalogue revision: `0ee17205f254b5abc43b266c8a0f215565c352f7`.
The 31M model/tokenizer/voices are Apache-2.0. The runtime is MIT OR Apache-2.0.
Do not substitute the noncommercial 40M models. Apple fallback audio is not
established as cleared for publishing in a demo video.

Hands-on audible check (user only):

1. Connect with `/look`, obtain an answer, choose **Read aloud**. Confirm
   the card says **Reading with Phonon · Russell** and the voice is Russell.
2. Start a long answer, stop it, then read another answer. Confirm immediate silence
   on Stop and no overlap, old words or stale reading state on replacement.
3. Start again and press Esc. Confirm speech stops and the card dismisses.
4. During speech enter `/look stop`. Confirm silence. Reconnect and read again.
5. Enable automatic reading. Complete a new answer. Confirm it reads once, not while
   streaming. Disable it and confirm the next completed answer remains silent.
6. Start talking while an answer is reading. Speech closes before the microphone
   opens. Wait for **Listening**. Read aloud is blocked while talking, and answers
   completed during the hold stay silent. Read them explicitly after release.
   If output cannot stop within one second, capture fails rather than overlapping it.

No-speaker regression: `python3 -m unittest tests.test_speech tests.test_voice_turns`.
With `ptts` and assets installed, run `python tests/phonon_smoke.py`: real Russell
generation into a paced fake sink, first-chunk timing and <100 ms cancellation.
On macOS, prefix it with
`sandbox-exec -p '(version 1)(allow default)(deny network*)'` to prove offline use.
