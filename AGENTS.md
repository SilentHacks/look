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
| `voice_turns.py` | `VoiceTurns`: host session binding, exact text/session FIFO matching, frozen contexts, turn-owned answer streaming and final backstop. |
| `actions.py` | `SnapshotActions`: current handle/epoch ownership, live control risk policy, single-use fingerprint-bound confirmations and unknown-outcome handling. |
| `config.py` | `GazeConfig` dataclass + `GazeConfig.from_ctx(ctx)` — plugin settings only. |
| `voice.py` | `transcribe_audio_buffer` backend chain on macOS: `asr/` (Parakeet TDT on CoreML/ANE in-process, ~65ms) → `parakeet-mlx` (~180ms) → `faster-whisper` (the only backend on Linux). `record_microphone`, `MAX_AUDIO_BYTES`. |
| `asr/` | `coreml_model.py` — pyobjc `CompiledMLModel` replacement (coremltools ships no cp314 wheels); `parakeet_coreml.py` — TDT greedy decode vendored from silicon-asr (MIT). |
| `server.py` | `SessionHttpServer`: GET-only static server on `127.0.0.1:9111` for the demo page (`/`, `/index.html`, `/api/status`). No POST, no CORS, no resolution endpoints. |
| `cli.py` | `hermes gaze` subcommand + `/gaze` slash handler. |
| `browser/cdp_bridge.py` | Per-tab isolated-world CDP worker; retriable reads versus non-retrying `eval_js_once` mutations; session snapshot activation/epoch ownership and simulated choose. |
| `browser/companion.py` | Discovers supported tabs, follows foreground focus, routes evidence/mutations/replies to their captured tab and document. Background replies wait in Python. |
| `browser/overlay.js` | DOM collector, exact snapshot identities and live highlight geometry; detached private control tree mirrored through CDP. |
| `browser/panel.js` | Private renderer in a script-disabled, opaque-origin sandbox iframe. Trusted UI events return only through its CDP context, never page messaging. |
| `microphone.py` | Single-owner native capture; closes on release, cancellation, focus/document/route loss, device error, disconnect or the native 30-second deadline. |
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
  lives in an opaque-origin, script-disabled sandbox iframe, initialized only by
  CDP; no `postMessage`, origin HTTP endpoint, extension, or page script runs there.
  Its main-world control tree is detached, not website DOM. Only non-private
  highlight geometry enters the website's closed shadow tree. The host uses the
  top layer; tampered visibility/transforms reject UI input. Sites can still remove
  or hide the host (denial of service), not read its private content or mint input.
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
  Lens card would click whatever now sits at that index.
- **Hover snapshots are immutable server-owned evidence.** Activation bumps the
  epoch, invalidates simulated choose/pending confirmations, stamps `Resolution`
  into the bounded context, and activates the browser's captured identity map.
  Queued voice snapshots activate only in the matching session/text pre-hook.
  Explain checks the saved snapshot before and after the call; hook context is
  returned verbatim, including the current epoch.
  Fresh hover evidence highlights its available pointer handles automatically.
  After an answer, one bounded `ctx.llm` call selects the evidenced answer scope;
  saved snapshot identity, current epoch and captured handles are checked again
  before highlighting. No protocol markers enter the answer or transcript.
  `gaze_highlight` remains for explicit/manual scope changes. Followups without
  fresh evidence attach nothing and preserve the epoch and pending confirmations.
  Live identity/fingerprint and single-use approval checks still apply. Read-only
  one-shot turns may highlight but cannot click or confirm actions.
- **Cursor wire privacy precedes serialization.** Never read form values or use
  ancestor `innerText`; the bounded collector excludes sensitive fields and their
  associated labels. Freeze mode-appropriate evidence at recording stop, before
  ASR: cursor identities in hover, candidates/pointer/fixations in simulated mode.
  Evidence URLs are HTTP(S), at most three per item and 600 characters each.
  Strip credentials, all query parameters and fragments before wire serialization
  and again before model serialization; never guess which query values are secrets.
  Pointed facts/URLs precede peer URLs in the shared 6000-character fenced packet.
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
- **Voice ownership includes session, exact utterance and turn.** Reasoning and
  foreign/late deltas never reach Chrome. Disconnect revokes active actions.
  `on_session_end` is a per-turn event, not a chat disconnect.
- **Focus changes do not retarget evidence or replies.** Freeze the source tab,
  unique CDP document context and route generation during collection, before
  scoring/ASR. Carry that evidence locally through scoring and pass it explicitly
  into activation; `last_resolution_input` is current-resolution state, not a
  worker's ownership token. Mutations require that owner and foreground focus;
  never fall back to the newly focused tab. Browser-owned same-document navigation events revoke
  action authority and confirmations, including after a route returns to its old
  URL; captured read-only highlight geometry remains usable.
  Session events and intent replies (including one-shot answers) retain their
  captured tab/document. No recipient means no delivery. Background replies wait
  in Python until that source is foreground; replacement documents inherit none.
  Post-answer highlighting uses the same foreground/source-document guard.
- **Microphone capture stays outside website origins.** Native `sounddevice`
  owns the device only during talk; no browser grant, `getUserMedia`, pre-warmed
  input stream or audio bytes in the page. Focus/document/route loss, device error
  and a hard 30-second native deadline cancel and discard, never submit partial
  speech. The watchdog checks every 100ms. A hostile site can suppress Space keyup:
  capture may continue until that deadline; no Input Monitoring permission is
  requested. The UI shows the cap and receives native cancellation notification.
  Wait for Listening before speaking.
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
