# Hermes Gaze ("Telepathy") 👁️🧠

> **Multimodal Deictic Reference Resolution & Gaze Tracking for Hermes Agent & Google Chrome**  
> *"Neuralink at home: point with your eyes, command with your voice. Hermes knows what 'this' means."*  
> Entry for the **Nous Research Hermes Agent Plugin Hackathon** (Nov 2026).

---

## Overview

Raw gaze/pointer tracking suffers from ~80–180 px of spatial jitter and drift—worse than the size of a standard web button.

**Hermes Gaze** solves this by treating pointing not as a naive mouse replacement, but as one signal in a **Bayesian Reference Resolution** engine:
1. **Temporal Eye-Voice Alignment:** Aligns a 10-second fixation buffer to speech word-timestamps (Parakeet TDT on CoreML/ANE in-process via pyobjc on macOS, `faster-whisper` elsewhere), capturing what you looked at right when saying *"this"*, *"these"*, or *"that"*.
2. **Spatial Box-Integral:** Integrates 2D gaze covariance over candidate elements extracted from Chrome's live DOM & Accessibility tree via CDP.
3. **Semantic Reranking:** Fuses intent verb priors with `ctx.llm` scoring and consequence estimation.
4. **Semantic Lens:** When two candidates are ambiguous, pops out separated cards with action previews for instant gaze-dwell, voice, or keyboard selection.

## Architecture

- **Python owns policy.** Simulated and webcam gaze share Bayesian resolution. Hover sends exact cursor evidence to the model, which chooses scope; Python enforces snapshot ownership and action confirmation. The overlay only collects DOM facts and renders results.
- **Persistent CDP sessions.** One isolated-world websocket per supported tab; reads follow focus, while actions retain their captured tab/document. Ordered nonce-bearing binding intents carry questions and native talk controls. No HTTP resolution/action endpoints.
- **Honest failures.** Missing/detached/expired evidence and uncertain click outcomes are reported, never replaced with synthetic targets or silently retried mutations.
- **Pointing modes:** `hover` supplies exact cursor identity and surrounding structure, with explicit snapshot tools for highlighting/actions. `simulated` retains Bayesian noisy-gaze resolution. `webcam` uses local, personally calibrated iris/head landmarks from a separate owned camera window; gaze is read-only evidence, while explicit user action tasks use the guarded DOM tools.
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
page context. Answers stream into Hermes and all supported Chrome tabs. The
latest answer survives navigation in memory; highlights/actions never move to
an unrelated tab or replacement document.
Refreshing cursor evidence through a tool does not interrupt that turn's answer stream.
Followups without a fresh capture use conversation history without reattaching old
evidence or changing its epoch. A connected non-deictic utterance without a target is delivered
as plain text. After compaction, resolving again captures the current cursor, not
the historical target. `/gaze disconnect` revokes pending and active action ownership;
it does not cancel a Hermes turn already accepted by the host.

Errata leaves vermilion proofing marks and temporary source-attached paper notes.
Nothing remains idle except a bare unread count. **Q** recalls the answer index;
**Right Alt** (or your configured lock shortcut) opens protected question entry.
**Escape** or the cross dismisses a note; the double-arrow moves it aside.
Recall a target and use its reply arrow for a follow-up. Notes keep question/answer
history, bounded scrolling, queue counts, Retry/Skip/Resume and mouse-only Confirm/Cancel.
They dock at the viewport edge when the captured source is offscreen or unavailable.
Completed notes retreat after 12 seconds when neither hovered nor being edited;
completion never changes selection or announces a new answer.

Read aloud uses local **Gradium Phonon-31M English**, catalogue voice **Russell**,
through native streaming output. Stop, Esc, another read request and disconnect
cancel generation and buffered playback. Automatic reading of completed answers
is explicitly enabled per plugin session and starts off. No answer text goes to
a provider or website. Missing dependencies/assets or a model-load failure select
macOS `say` before audio starts; the card reports that fallback and its reason.
There is no mid-answer voice switch. See [offline speech setup](#offline-read-aloud-setup).

Georgia (roman and italic) and Courier New are system font references, not bundled
or downloaded fonts; generic serif/monospace fallbacks cover other systems. No font
assets or third-party font licences ship. Paper follows the source page's light/dark
background. Reduced motion disables the rising note and animated ink.

Without a connected session, read-only one-shot answers still appear, without
saved conversations or actions. Action requests fail instead of using that fallback.
ASR file downloads remain quiet without suppressing errors or redirecting output.
Browser-supplied compressed audio still requires `ffmpeg` on Hermes's PATH
(or in a standard macOS location), with MIME type preserved through decoding.
Native microphone PCM/WAV uses the in-process fast path and does not require
`ffmpeg`. Decoder failures report the real diagnostic, never reinterpret
compressed bytes as PCM.

### Offline read-aloud setup

After bringing this feature into the installed plugin checkout, run these yourself
(the implementation agent does not modify Hermes's environment):

```bash
HERMES_DISABLE_LAZY_INSTALLS=1 hermes plugins validate /Users/Abid/Projects/hermes-gaze --install-deps
HERMES_DISABLE_LAZY_INSTALLS=1 hermes gaze setup-speech
```

The first command installs declared dependencies, including `ptts==0.6.0`, using
Hermes's launcher. The second downloads the pinned q8 model (~65 MB) and Russell
embedding once, without opening an audio device. It requires in-process plugin
isolation, as does the companion. Alternatively, run `scripts/setup_speech.py`
with the Hermes environment's Python; this standalone setup does not import Hermes.
Assets live in `${XDG_CACHE_HOME:-~/.cache}/hermes-gaze/phonon`; setup and Hermes
must use the same OS user/cache root. Restart Hermes after installing.

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
python benchmark/probe_sessions.py --output /tmp/gaze-sessions.json
python benchmark/probe_phase1.py --output /tmp/gaze-dom.json
python benchmark/probe_sessions.py --prompt-only --trials 10 --sources tui --require-pass --output /tmp/gaze-prompts-neutral.json
python benchmark/probe_sessions.py --prompt-only --repo-folder --trials 10 --sources tui --require-pass --output /tmp/gaze-prompts-repo.json
```

The session smoke uses private config/credential copies and private Chrome,
substituting synthesized WAV before the real transcription binding. It exercises
real TUI and desktop **backends**, not the native desktop renderer or physical microphone.
It reuses installed dependencies without updating them and initializes lazy host
agents with a normal control turn before injecting speech.
Prompt-only mode uses fresh sessions and the configured model for headers, a cell,
a button, a wider-scope followup, hostile page text, a synthetic stale cursor,
pasted code and an explicit plugin question. `--repo-folder` enables project rules;
the default uses a neutral folder. Reports retain answers, captures and browser
operations; `--plugin-root` can select an isolated committed baseline.
Prompt-only questions remain the first user request in each fresh session.
`--turn-interval 6` spaces submissions for free-model quotas. Provider errors and
240-second terminal-response timeouts remain failed trials, not fallback answers.
Historical Phase 0/1 measurements remain in `benchmark/*results.json`; the
hardcoded `/gaze probe` experiment is removed.

### Owner retest: combined companion branch

Run these commands yourself; they change the main checkout only when requested.
The plugin symlink `~/.hermes/plugins/hermes-gaze` already points at
`/Users/Abid/Projects/hermes-gaze`, so no reinstall or relink is needed.

1. Quit existing Hermes TUI/desktop processes. In Terminal:
   ```bash
   cd /Users/Abid/Projects/hermes-gaze
   git switch feature/companion-core
   ```
2. `sounddevice>=0.4.6,<0.6.0` is already declared in `pyproject.toml`.
   The owner's bootstrapped Hermes runtime was checked read-only and has
   `sounddevice 0.5.6` and `websockets 15.0.1`; no new dependency install is
   needed on this machine. On a machine missing plugin dependencies, use
   the Hermes launcher, not Homebrew Python:
   ```bash
   hermes plugins validate /Users/Abid/Projects/hermes-gaze --install-deps
   ```
   This installs declared dependencies into Hermes's environment; validation
   also runs catalog checks, so unrelated catalog failures are not mic errors.
3. In Terminal, still in that checkout:
   ```bash
   hermes
   ```
   Use a new conversation, send `Reply only Ready.`, and wait for the answer.
   Then enter `/gaze connect`. Expect `Chrome companion ready` and
   `Chrome voice connected to this Hermes session`. It opens a separate
   CDP Chrome profile on the configured port (default 9333), not the everyday
   Chrome profile. Use the newly opened window; no manual Chrome flags needed.
   Existing setup must use `plugins.isolation: in_process` and
   `plugins.entries.hermes-gaze.allow_gateway_injection: true` as above.
4. In that Chrome window, navigate normally to a public page or a deal list.
   Hover a deal title, hold Space, wait for **Listening**, then say:
   “Summarize this deal, its price and savings, and give its exact link.”
   Release Space. On first capture macOS may ask for microphone access for
   Terminal (when Hermes is launched there), or the responsible host app if
   launched elsewhere; it is not a Chrome website-permission prompt.
   Allow that host in System Settings → Privacy & Security → Microphone if
   previously denied, then restart Hermes and repeat step 3. The exact macOS
   label depends on the launch chain; permission prompting was not triggered
   during the integration check.
5. Expect the pointed highlight, answer text and captured HTTP(S) deal URL.
   The intended scope should widen before the answer (post-answer on fallback). Scroll: the outline
   must stay on the same element, disappear offscreen and return with it.
6. Ask once more, then switch supported tabs while Hermes is answering
   (after releasing Space). The reply should finish in the newly focused
   tab and remain available when returning. It must not move the deal's
   highlight onto another page. A background source retains its pointer
   highlight; automatic scope changes require the source to be foreground.
   Reload the source: the latest answer should return, but old pins must not.
   Closing Hermes ends this in-memory answer retention.


## Quickstart

```bash
# inside Hermes (slash command)
/gaze demo                 # launch the companion Chrome on the benchmark dashboard + inject the HUD
/gaze mode simulated       # noisy-gaze mode ('/gaze mode hover' for the exact Magic Pointer)
/gaze mode webcam          # start the separate camera window (explicit user command only)
/gaze calibrate            # local nine-point calibration; then move the pointer once per page
/gaze tracker              # camera/sample/calibration status; '/gaze tracker stop' returns to cursor
/gaze resolve what does this do
/gaze benchmark            # reproducible accuracy table across noise levels
```

Webcam setup, privacy, coordinate-mapping limits and the real-camera checklist:
[Webcam gaze](docs/WEBCAM_GAZE.md). Fake-camera plumbing is verified; human accuracy is not measured.

```bash
# from the shell
hermes gaze demo
hermes gaze benchmark
python3 -m unittest discover -s tests -t .  # full suite; no Chrome needed
```

## Documentation

- **[AGENTS.md](AGENTS.md)**: contributor guide for coding agents — module map, architecture invariants, test & lint commands, known limits.
- **[docs/PLAN.md](docs/PLAN.md)**: original technical specification, math, and 6-day implementation roadmap (pre-refactor — see the header note inside).
- **[docs/PRIOR_ART_AND_PITCH.md](docs/PRIOR_ART_AND_PITCH.md)**: competitive analysis of the Hermes catalog, open PRs, GitHub repos, academic papers (Bolt 1980, EyePoint 2007), and marketing strategy.
- **[docs/DEMO_AND_SUBMISSION_PLAYBOOK.md](docs/DEMO_AND_SUBMISSION_PLAYBOOK.md)**: 85-second X video script, X post copy, and catalog PR submission template.
