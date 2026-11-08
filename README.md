# Hermes Gaze ("Telepathy") 👁️🧠

> **Multimodal Deictic Reference Resolution & Gaze Tracking for Hermes Agent & Google Chrome**  
> *"Neuralink at home: point with your eyes, command with your voice. Hermes knows what 'this' means."*  
> Entry for the **Nous Research Hermes Agent Plugin Hackathon** (Nov 2026).

---

## Overview

Hold Space, speak, and release: Hermes answers or uses guarded browser actions.
Cursor (`hover`) mode remains a permanent option and uses exact captured DOM identities; webcam mode
uses personally calibrated local left-eye appearance and iris features in a separate owned window.
Both freeze evidence at release and align spoken referents with the pointing history.
The model chooses semantic scope from the question, not from cursor proximity alone.

Simulated and webcam gaze retain Bayesian resolution for noisy samples, with
spatial scoring, temporal alignment, semantic reranking and the Semantic Lens.
No real-camera accuracy number is established.

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

Release freezes browser evidence before transcription. The existing capsule immediately
shows “Looking into …”; hint persistence runs after microphone stop/reservation, not
ahead of them on the ordered intent worker. Capsule placement samples only its
candidate strip, without changing placement scores. CoreML prewarm loads and runs
one silent prediction before sharing the cached runner; models and fallbacks are unchanged.

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
including the new prediction warmup. Registration runs it on a daemon; a question
arriving before warmup finishes can still wait on the loader lock. These runs
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
[Webcam gaze](docs/WEBCAM_GAZE.md). The nine-point appearance model requires recalibration after moving or changing glasses. Its Chrome/fake-camera proof is deferred; reserved offline research is not live accuracy.

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
