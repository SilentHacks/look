# AGENTS.md — hermes-gaze contributor guide

Written for coding agents working in this repository. Read this before editing.

Hermes Gaze ("Telepathy") is a Hermes Agent plugin that supplies exact Chrome
cursor identity and bounded structural evidence in hover mode. The model decides
semantic scope from the utterance; noisy simulated mode retains Bayesian fusion.

## Project map

| Path | What lives here |
|---|---|
| `plugin.yaml` | Plugin manifest: tools/hooks/skill declarations, config schema. Keep 1:1 with `register()`. |
| `__init__.py` | Thin registration of six tools, context/stream/final/turn-end hooks, `/gaze` session connection, CLI and skill. |
| `tools.py` | Schemas/thin handlers for `gaze_resolve`, simulated-only `gaze_choose`, snapshot `gaze_highlight`, guarded `gaze_click`, calibration and benchmark. |
| `service.py` | Resolution, frozen `submit_snapshot` delivery/fallback, nonce-checked binding dispatch and one-shot explanation. |
| `voice_turns.py` | `VoiceTurns`: Python-owned browsing inbox, serial admission, frozen item evidence, exact request/session/turn matching and versioned UI state, including which answers have been shown or retreated and the one-time hints. |
| `actions.py` | `SnapshotActions`: current handle/epoch ownership, live control risk policy, single-use fingerprint-bound confirmations and unknown-outcome handling. |
| `config.py` | `GazeConfig` dataclass + `GazeConfig.from_ctx(ctx)` — plugin settings only. |
| `voice.py` | `transcribe_audio_buffer` backend chain on macOS: `asr/` (Parakeet TDT on CoreML/ANE in-process, ~65ms) → `parakeet-mlx` (~180ms) → `faster-whisper` (the only backend on Linux). `record_microphone`, `MAX_AUDIO_BYTES`. |
| `asr/` | `coreml_model.py` — pyobjc `CompiledMLModel` replacement (coremltools ships no cp314 wheels); `parakeet_coreml.py` — TDT greedy decode vendored from silicon-asr (MIT). |
| `server.py` | `SessionHttpServer`: GET-only static server on `127.0.0.1:9111` for the demo page (`/`, `/index.html`, `/api/status`). No POST, no CORS, no resolution endpoints. |
| `cli.py` | `hermes gaze` subcommand + `/gaze` slash handler. |
| `browser/cdp_bridge.py` | Per-tab isolated-world CDP worker; retriable reads versus non-retrying `eval_js_once` mutations; session snapshot activation/epoch ownership and simulated choose. |
| `browser/companion.py` | Follows foreground focus, delivers Python-cached inbox state only to that protected renderer; evidence, actions and non-inbox replies retain captured ownership. Opens validated links and brings a source tab forward. |
| `browser/overlay.js` | DOM collector and captured identities, plus the companion's input, pointing, motion and placement. Keeps rings and text-free glass plates in a closed shadow. Holds no UI tree; it sends view messages to the frames. |
| `browser/panel.js` | Card stack and capsule renderer in two script-disabled, opaque-origin sandbox iframes. All words and the voice-level bars live here. Trusted events return only through its CDP context. |
| `browser/markdown.js` | PURE allow-list markdown parser for answers, loaded into the frames and into node tests. No DOM, no HTML passthrough, no images, no hrefs. |
| `naming.py`, `answer_title.py` | PURE plain-language names, errors and speech; bounded opening answer-heading extraction. |
| `microphone.py` | Single-owner native capture; closes on release, cancellation, definite focus/document loss, device error, disconnect or the native 30-second deadline. Chrome checks cannot block the native deadline. |
| `resolver/` | PURE modules — `bayesian_fusion.py` (scoring + decision policy), `temporal_aligner.py`, `data_extractor.py`. No I/O imports allowed (enforced by `tests/test_layering.py`). |
| `resolver/cursor_context.py` | PURE exact preceding-hit selection and shared ≤6000-character fenced context; hover never calls Bayesian fusion or the legacy candidate extractor. |
| `tracker/` | PURE modules — `simulated_gaze.py` (ring buffer + pointer tracker), `recalibrator.py`. Same purity rule. |
| `benchmark/` | `benchmark_page.html` (self-contained demo dashboard) + `run_benchmark.py` (accuracy suite). |
| `tests/` | stdlib `unittest` only. `tests/__init__.py` registers a `hermes_gaze` package *shell* (no `__init__.py` exec) so tests can `from hermes_gaze.service import ...` exactly like Hermes's plugin loader. |
| `docs/` | PLAN (original design — see its header note), prior art & pitch, demo playbook. |
| `skills/gaze-telepathy/SKILL.md` | Bundled skill for browser evidence, snapshot tools and session setup. Keep simulated decision names/thresholds in sync with `resolver/bayesian_fusion.py`. |

## Invariants (each with the WHY)

- **Python owns noisy-gaze and action policy; the model chooses cursor scope.**
  The overlay collects identities/structural facts and renders highlights/status,
  never scores, ranks or decides semantic scope/risk. This keeps one policy
  implementation instead of diverging JS/Python decisions.
- **User message and browser evidence are separate concepts.** Durable guidance is
  registered as a frozen system prompt section. Both modes use `build_context` for
  an escaped `<browser_context>` envelope with `<page_data>`, relative pointer age
  and the labelled question. `stamp_resolution` changes only its trusted epoch
  slot. Never slice a rendered packet: its fences and suffix share the 6000-char bound.
- **Overlay → Python only via `__hermesGazeIntent`.** No `fetch()` to `server.py`, no
  new HTTP endpoints, no `Runtime.evaluate` polling for decisions. The binding keeps a
  single ordered channel that works on file:// and any origin without CORS. Replies
  are callback-style (`reply({...})` → `api.onIntentResult`) — intents return nothing.
  Service intents carry `nonce`, pushed via `api.setIntentNonce` after each
  (re)injection. The nonce remains in the main-frame isolated-world closure, never
  the DOM or UI frame. The transport accepts service intents only from that exact
  context and stamps tab/document/route ownership. Private renderer traffic is
  accepted only from its separately owned CDP context and cannot call service
  handlers directly. It contains no nonce. Ask, keyboard submission, microphone
  controls and confirmation require trusted UI input before crossing this bridge.
- **Closed shadow DOM alone is not a privacy boundary.** Earlier page listeners can
  read typed keys and `getSelection()` can expose selected shadow text. Private UI
  lives in opaque-origin, script-disabled sandbox iframes, initialized only by
  CDP; no `postMessage`, origin HTTP endpoint, extension, or page script runs there.
  Only text-free geometry enters the website's closed shadow tree: rings and glass
  plates. Plate and hit-area heights are rounded to 24px steps and capsule widths to
  16px, so the exact length of an answer is not exposed. Voice level goes straight
  from Python to the capsule frame and never touches the main world. The host uses
  the top layer and re-raises when a site dialog or popover opens. Tampered
  visibility/transforms reject UI input. Sites can still remove or hide the host
  (denial of service), not read its private content or mint input. They can observe
  the frame's coarse rectangle by hit testing, and that focus sits in a frame.
- **Canvas does not render in a scripts-disabled document.** Chrome shows fallback
  content. The waveform is DOM bars; do not move it back to a canvas in the frame.
- **The look is the approved prototype, one material: glass.** Nothing on screen when
  idle, apart from a one-time first hint. Plain words, no icons, numbers or lock.
  `prefers-reduced-transparency` still gets a solid surface, as an accessibility
  setting, not a choice. Timers do not fire in the frames: timing lives in the main
  isolated world or CSS, and streaming is pushed over CDP.
- **Answers are untrusted content, rendered through an allow-list.** Never put model or
  page text through `innerHTML`. No images, no remote resources, no `<a>` or href in the
  frames: a link is a span, opened by Python after `safe_link` from a trusted click, and
  it shows its host. Mid-stream, half-finished markup waits offstage rather than flashing
  raw markers. DOM updates patch in place so private focus, selection and scroll survive.
  Answers cannot supply confirmations or controls.
- **Stack state is Python's.** `presented`, `archived`, names, hints and read-aloud state
  come in the inbox, so they follow navigation and tabs; springs and placement are local.
  The first answer that has started and not been shown comes forward by itself. Each gets
  its turn of `answer_turn_seconds` (12s default, longer by reading speed; hover holds),
  then the next unseen one, then the stack retreats. Esc answers for everything settled.
- **What Space asks.** On the card, or moved under 90px since asking, is a follow-up;
  pointed elsewhere is a new question. A hold that began on the card stays on it until
  the pointer travels 90px, because the card stops taking hover while talking.
- **A quick Space tap is the website's.** Under 130ms it is replayed as real trusted
  input over CDP, so media sites keep their behaviour. Holds under 220ms cancel silently.
- **Everything lit counts.** The capture lists what was lit (`lit`) and the resolver adds
  those to `pointed`, after any spoken-word anchors.
  Immediate names use bounded `safeText` only; combined targets use the first short
  subject and a count. Queued cards keep that fallback until their answer starts.
  Exact-owned browsing requests ask for an ordinary `## Subject` heading and blank
  line. Terminal/history retain it; cards and read-aloud use the body. Only the first
  attempt of the original question can promote the item name, once; Retry and
  follow-ups never rename it. No naming side call or hosted-title setting exists.
  A request-owned parser waits at most 500ms from first text and buffers at most
  96 undecided characters. Invalid, missing or cut headings pass through unchanged
  and keep the fallback. Final hooks reuse that decision. A title update never
  selects, reorders, marks unread, announces or speaks.
- **Inbox `speak` resolves server-owned item/request text, never client-supplied speech.**
  It speaks `speech_text`, no markup characters. macOS `/usr/bin/say` receives text on
  stdin; one cancellable worker owns playback. `auto_speak` is an explicit runtime toggle,
  initially off; disconnect cancels playback.
- **Whisper word timestamps are audio-relative.** `transcribe_audio_buffer` takes
  `audio_epoch` (the first native input buffer's ADC wall-clock epoch for Chrome,
  `time.time()` before `record_microphone` on the tool path) and shifts each word.
  The temporal aligner compares anchors against fixation epochs — unshifted word
  times silently collapse alignment onto the latest fixation.
- **Relative imports only inside the package.** Hermes loads this plugin as
  `hermes_plugins.hermes_gaze`; `import hermes_gaze` inside a module would exec a
  SECOND copy of the package (the split-brain singleton bug this refactor removed).
  `tests/test_layering.py` fails on any `import hermes_gaze` / `from hermes_gaze`
  outside `tests/`.
- **`resolver/` and `tracker/` stay pure.** No `websockets`, `urllib.request`,
  `http.server`, `subprocess`, `socket`, or imports of `browser`/`service`/`server`.
  The pure stdlib `urllib.parse` is allowed for URL sanitization.
- **`check_gaze_requirements` stays constant-`True`.** Hermes re-evaluates `check_fn`
  every turn; returning `False` when Chrome is down would mutate the tool surface
  mid-conversation and break the cached prompt prefix (see Hermes's per-conversation
  prompt-caching invariant). Chrome health is reported in-band (`chrome_connected`).
- **`MLMultiArray` conversions live only in `asr/coreml_model.py`.** Two CoreML
  traps already bit once: input arrays must be tagged with the real
  `MLMultiArrayDataType*` constants — a hand-coded wrong code makes CoreML read
  the buffer at half width (the fp32-as-fp16 NaN bug) — and outputs must be
  read via `getBytesWithHandler` + `strides`, never `dataPointer` + `shape`:
  `dataType` need not match storage dtype, and dynamic outputs under-report
  `shape`/`count` (Encoder claims 188 frames, stores 192). `strides[0]*shape[0]`
  is the true element count.
- **No fabricated fallbacks.** When candidates or fixations are missing, return
  `{"ok": false, "error": ...}` — never inject synthetic dashboard candidates or a
  fake center fixation. A wrong confident answer is worse than an honest failure.
- **All fixations enter via `session.ingest(...)`.** It converts wire dicts to
  `FixationSample`, subtracts the recalibrator bias, and dedupes on a
  `(t_end, x_doc, y_doc)` watermark. Bypassing it re-introduces double-counted
  fixations and un-corrected drift.
  It also returns that capture's normalized samples for local scoring; never score
  a tab against the machine-wide ring's samples from other documents.
- **Resolution epoch guards `choose`.** Every resolution bumps
  `session.resolution_id`; a `choose` intent carrying a mismatched `resolution_id`
  gets `"stale resolution"`. Never accept a choose without the epoch check — a stale
  choice would click whatever now sits at that index.
- **Hover snapshots are immutable server-owned evidence.** Activation bumps the
  epoch, invalidates simulated choose/pending confirmations, stamps `Resolution`
  into the bounded context, and activates the browser's captured identity map.
  Inbox snapshots activate read-only on question acceptance so queued targets can
  highlight early; admission never reactivates an older item's decision snapshot.
  Explain checks the saved snapshot before and after the call; hook context is
  returned verbatim, including the current epoch.
  Fresh hover evidence highlights its available pointer handles automatically.
  An asynchronous TypeSafe decision selects intended scope at question acceptance,
  with a 1.5-second deadline and page evidence opt-in (off by default). Only static
  described scope labels cross that boundary otherwise; identities map locally.
  Failed/disabled/no-key decisions alone use the existing post-answer `ctx.llm`
  selector; successful `none` does not. Saved identity, epoch, foreground document
  and supersession checks guard application. No protocol tokens are generated for
  titles: the ordinary Markdown heading remains readable in terminal/history.
  `gaze_highlight` remains for explicit/manual scope changes. Inbox research is
  read-only, including recalled items and follow-ups; clicks require fresh manual
  pointing. A new capture revokes pending approval immediately.
  Live identity/fingerprint and single-use approval checks still apply.
- **Cursor wire privacy precedes serialization.** Never read form values or use
  ancestor `innerText`; the bounded collector excludes sensitive fields and their
  associated labels. Freeze mode-appropriate evidence at recording stop, before
  ASR: cursor identities in hover, candidates/pointer/fixations in simulated mode.
  Evidence URLs are HTTP(S), at most three per item and 600 characters each.
  Strip credentials and fragments always; retain ordinary query parameters but
  exclude secret-named parameters and long opaque values, bounded to 128 fields
  and 8192 input characters. Apply this before wire and again before model serialization.
  Pointed facts/URLs precede peer URLs in the shared 6000-character fenced packet.
  Covered-frame/modal surface warnings join the saved essential facts, so follow-ups
  and comparisons cannot lose them to optional neighbours/history under the budget.
- **No selector rematching for history or actions.** Short `@` handles refer to
  captured DOM identities/column members. Highlight/click require the current
  epoch; changed, detached or expired targets fail honestly.
  Highlight geometry follows those same nodes while selected, clipped to the
  viewport and scrolling ancestors; no animation-frame layout work runs without
  a live selection.
- **Confirmation is not a model tool.** Python classifies live risk and form
  submits. Only the nonce-checked binding from a trusted primary mouse click can
  consume its fingerprint-bound, single-use approval. Model/page text is plain
  text in the new HUD paths; it cannot supply confirmation markup.
- **Never replay mutations.** `eval_js_once` is mandatory for click commands.
  Lost replies mean unknown outcome, not \"not executed\"; revoke that snapshot.
- **Voice ownership includes item, request, session, exact wire text and turn.**
  `VoiceTurns` owns an in-memory inbox and at most eight waiting requests. Reserve
  capture order at recording stop, before ASR; inject only the FIFO head, and only
  after the previous `on_session_end` (not `post_llm_call`). Busy host injection
  merges questions, so each attempt has a unique item/request label matched exactly
  in `pre_llm_call`. Failures/interruption/disconnect retain partial answers and
  pause admission. Disconnect must not release host admission ownership:
  reconnect/Retry/Resume still wait for the actual terminal hook; the host can
  remain busy while unbound. Retry adds a new answer attempt (or retries saved in-memory ASR),
  Skip discards the failed attempt, Resume continues waiting work. ASR releases the
  intent worker so another recording can start; its bytes stay only in memory
  through transcription/retry. Reasoning and foreign/late deltas never reach Chrome.
  Recovery commands identify the failed request, not merely its item: an item may
  already have newer queued follow-ups. ASR finalizes the item's label/evidence;
  dependent follow-ups copy that finalized evidence only when admitted.
  Follow-ups explicitly identify a saved item and wait in the same queue. The
  previous item means capture order, never completion order. Rebuild saved evidence
  and conversation inside one fenced 6000-character packet; never slice packets.
  Reserve pointed facts and bounded per-cell row facts from both saved items before
  optional headers, conversation and surroundings can exhaust the shared budget.
- **Focus changes do not retarget evidence or discard answers.** Freeze source tab,
  unique CDP document context and route generation before scoring/ASR. Carry evidence
  locally into activation; never use mutable current-resolution state as ownership.
  Mutations require that owner and foreground focus. Browser-owned route events
  revoke actions and confirmations even if the URL returns; read-only highlight
  geometry remains usable. `pagehide` revokes snapshots, not answer streaming.
  The companion caches the full inbox in Python and delivers only to the focused
  tab's detached renderer and protected iframe, including recall after navigation.
  No answer content or unread text enters the page DOM or background renderers.
  During a navigation frames can be missing: `_on_new_context` is serialized and retried,
  because a half-armed page would swallow keys with nowhere to send them.
  Non-inbox replies still wait for their captured source document to be foreground.
  Inbox events (`type: inbox`, `version: 1`) replace UI state by increasing `revision`:
  connection/capture state/paused/selected item plus items with capture order, target/source,
  unread and expired action state, and request conversations with question, text,
  status/error/queue position. No DOM identities appear in this UI interface.
  Completion marks an answer unread unless its card is open. It may bring the card forward,
  silently. Python sends raw `error` and a `plain_error` sentence; the UI shows only the sentence.
  Asking again with nothing waiting clears a pause, unless the host refused injection.
  Post-answer scope selection uses the same foreground/source-document guard as
  other snapshot operations. A background source keeps its existing pointer
  highlight; it cannot transfer that highlight to the newly focused tab.
- **Microphone capture stays outside website origins.** Native `sounddevice`
  owns the device only during talk; no browser grant, `getUserMedia`, pre-warmed
  input stream or audio bytes in the page. Definite hidden/unfocused tab or full
  document replacement, device error and a hard 30-second native deadline cancel
  and discard, never submit partial speech. Slow/failed Chrome checks are unknown,
  not loss; same-document URL/route changes never cancel recording. Route changes
  still revoke action authority and confirmations. Evidence freezes at release with
  that document's current route, before ASR. Cursor history already retains real
  identities across scrolling and uses audio-relative word times shifted to wall time;
  detached/virtualized-away nodes fail honestly, never selector-rematch.
  The native watchdog checks every 100ms independently of Chrome reads and emits
  `record_warning` with `seconds_remaining: 5` once, about five seconds before the cap.
  A hostile site can suppress Space keyup: capture may continue until that deadline;
  no Input Monitoring permission is requested. The UI shows the cap, remaining-time
  warning and the actual cancellation reason. Wait for Listening before speaking.
- **Recording is development-only.** `record_trials` defaults false; never write
  audio. Preserving an accepted injection takes precedence over recorder errors.

## Commands

```bash
python3 -m unittest discover -s tests -t .       # whole suite (bare `-m unittest` also
                                                  # tries importing browser/resolver as
                                                  # top-level pkgs and errors — pre-existing)
python3 -m unittest tests.test_service_intents   # one module
python3 -m py_compile tests/*.py service.py tools.py
node --check browser/overlay.js                  # JS syntax check
ruff check                                        # if ruff is installed
.venv/bin/python tests/trust_boundaries_chrome.py    # private Chrome; includes the patched-API page
.venv/bin/python tests/recording_hold_chrome.py
# whole flow on a real Hermes backend, serial, free model; run with the Hermes venv's Python:
# HERMES_DISABLE_LAZY_INSTALLS=1 <venv>/bin/python benchmark/probe_companion_ui.py --out DIR --headless
# accuracy table — benchmark has package-relative imports, so load the tests shell first:
python3 -c "import tests; from hermes_gaze.benchmark.run_benchmark import run_benchmark_suite, format_benchmark_markdown; print(format_benchmark_markdown(run_benchmark_suite()))"
```

## Known limits

- `hermes gaze` CLI subcommand is unavailable under `plugins.isolation: host` —
  Hermes skips `register_cli_command` in host isolation. The `/gaze` slash command
  is unaffected.
- `get_shared_session()`'s `GazeSession` is deliberately machine-scoped: Chrome
  :9222 and the microphone are OS resources shared across Hermes profiles. Do not
  try to make it per-profile.
- Camera-based (true eye) tracking is intentionally unimplemented in this revision;
  modes are `hover` and `simulated`. `simulated` exists to exercise the resolver
  under realistic pointing noise.
- Binding replies are callback-style — `handle_intent(intent, reply)` returns
  `None`; assertions about results inspect the `reply` payload, not a return value.
- `transcribe` intents reject base64 audio over ~16 MB before decoding — keep the
  bound ahead of any decoder work.
- `benchmark/benchmark_page.html` must stay self-contained: zero server
  dependencies (no fetch, no script tags served from the demo server). The overlay
  is always injected via CDP.
- System guidance is frozen into new Hermes sessions; start a new session after
  changing it. Compaction can remove historical evidence: `gaze_resolve` then
  captures the current cursor, not the historical target.
- Hermes persists browser evidence in `state.db` through `api_content`, independently
  of `record_trials`. Disabling plugin replay recording does not disable host retention.
- `/gaze` or `/gaze connect` starts/attaches the Chrome companion and binds the
  current Hermes session. Host `tui_gateway/plugin_inject.py` rejects lazy sessions;
  the isolated live host sample instead accepted scheduling then returned
  `status=error`, `error_surface.code=agent_init_failed`, before plugin turn hooks.
  No public plugin initialization API exists. A first normal Hermes message is
  still required. Do not patch the host or inject a hidden warm-up turn here.
- Native microphone permission belongs to the process running Hermes, not Chrome.
  Website Permissions-Policy/CSP cannot block capture. Measured device startup was
  80ms standalone and 222ms through the private Chrome talk key; speech before
  Listening can be clipped. A zero-wait first-word guarantee is not established.
- Automatic attachment supports HTTP(S), file and about:blank pages, not Chrome
  internal pages. Background/closed-tab mutations fail rather than moving to a
  different tab. Answer retention is in-memory and ends with the plugin process.
