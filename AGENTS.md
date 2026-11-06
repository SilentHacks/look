# AGENTS.md — hermes-gaze contributor guide

Written for coding agents working in this repository. Read this before editing.

Hermes Gaze ("Telepathy") is a Hermes Agent plugin that supplies exact Chrome
cursor identity and bounded structural evidence in hover mode. The model decides
semantic scope from the utterance; noisy simulated mode retains Bayesian fusion.

## Project map

| Path | What lives here |
|---|---|
| `plugin.yaml` | Plugin manifest: tools/hooks/skill declarations, config schema. Keep 1:1 with `register()`. |
| `__init__.py` | `register(ctx)` entry point — wires tools, the `pre_llm_call` hook, the `/gaze` slash command, `hermes gaze` CLI, and the bundled skill. Thin wiring only. |
| `tools.py` | Tool schemas (`gaze_resolve`, `gaze_choose`, `gaze_highlight`, `gaze_calibrate`, `gaze_benchmark`) + thin handlers that delegate to `service.py`. |
| `service.py` | The session-facing layer: `resolve_now` (resolution + browser render), `handle_intent` (dispatches `resolve`/`choose`/`explain`/`transcribe`/`configure` binding intents), `explain_element`, `set_runtime`. |
| `config.py` | `GazeConfig` dataclass + `GazeConfig.from_ctx(ctx)` — plugin settings only. |
| `voice.py` | `transcribe_audio_buffer` backend chain on macOS: `asr/` (Parakeet TDT on CoreML/ANE in-process, ~65ms) → `parakeet-mlx` (~180ms) → `faster-whisper` (the only backend on Linux). `record_microphone`, `MAX_AUDIO_BYTES`. |
| `asr/` | `coreml_model.py` — pyobjc `CompiledMLModel` replacement (coremltools ships no cp314 wheels); `parakeet_coreml.py` — TDT greedy decode vendored from silicon-asr (MIT). |
| `server.py` | `SessionHttpServer`: GET-only static server on `127.0.0.1:9111` for the demo page (`/`, `/index.html`, `/api/status`). No POST, no CORS, no resolution endpoints. |
| `cli.py` | `hermes gaze` subcommand + `/gaze` slash handler. |
| `browser/cdp_bridge.py` | `CdpSession` (one persistent websocket per pinned tab on a dedicated worker-loop thread, `Runtime.addBinding("__hermesGazeIntent")`, `eval_js`, `set_intent_handler`) and `GazeSession` (ring buffer + tracker + recalibrator + resolution epoch + `ingest` + `choose` + `configure`). `overlay.js` sits beside it. |
| `browser/overlay.js` | The in-page terminal: spotlight, pins, HUD, Semantic Lens cards, mic capture, `extractCandidatesNear`. Talks to Python ONLY through the `__hermesGazeIntent` binding and `api.onIntentResult`. |
| `resolver/` | PURE modules — `bayesian_fusion.py` (scoring + decision policy), `temporal_aligner.py`, `data_extractor.py`. No I/O imports allowed (enforced by `tests/test_layering.py`). |
| `resolver/cursor_context.py` | PURE exact preceding-hit selection and shared ≤6000-character fenced context; hover never calls Bayesian fusion or the legacy candidate extractor. |
| `tracker/` | PURE modules — `simulated_gaze.py` (ring buffer + pointer tracker), `recalibrator.py`. Same purity rule. |
| `benchmark/` | `benchmark_page.html` (self-contained demo dashboard) + `run_benchmark.py` (accuracy suite). |
| `tests/` | stdlib `unittest` only. `tests/__init__.py` registers a `hermes_gaze` package *shell* (no `__init__.py` exec) so tests can `from hermes_gaze.service import ...` exactly like Hermes's plugin loader. |
| `docs/` | PLAN (original design — see its header note), prior art & pitch, demo playbook. |
| `skills/gaze-telepathy/SKILL.md` | Bundled skill teaching Hermes how to act on `[gaze_ref]` context. Keep decision names/thresholds in sync with `resolver/bayesian_fusion.py`. |

## Invariants (each with the WHY)

- **Exactly one resolver, and it is Python.** `overlay.js` must never score, rank, or
  decide — it collects inputs and renders results. Duplicated logic in JS and Python
  already diverged once (JS had its own thresholds); that is what the intent binding
  replaced. If the overlay needs a new resolution behavior, extend `service.py` and
  the intent vocabulary, never the JS.
- **Overlay → Python only via `__hermesGazeIntent`.** No `fetch()` to `server.py`, no
  new HTTP endpoints, no `Runtime.evaluate` polling for decisions. The binding keeps a
  single ordered channel that works on file:// and any origin without CORS. Replies
  are callback-style (`reply({...})` → `api.onIntentResult`) — intents return nothing.
  Every intent carries `nonce`, pushed to the overlay via `api.setIntentNonce` after
  each (re)injection; `handle_intent` rejects intents without the session's
  `session._intent_nonce` — the binding is callable by any same-frame page script,
  so the nonce is what stops forged resolves/transcribes/explains.
- **Whisper word timestamps are audio-relative.** `transcribe_audio_buffer` takes
  `audio_epoch` (wall-clock recording start: `state.recordStartEpoch` in the overlay,
  `time.time()` before `record_microphone` on the tool path) and shifts each word.
  The temporal aligner compares anchors against fixation epochs — unshifted word
  times silently collapse alignment onto the latest fixation.
- **Relative imports only inside the package.** Hermes loads this plugin as
  `hermes_plugins.hermes_gaze`; `import hermes_gaze` inside a module would exec a
  SECOND copy of the package (the split-brain singleton bug this refactor removed).
  `tests/test_layering.py` fails on any `import hermes_gaze` / `from hermes_gaze`
  outside `tests/`.
- **`resolver/` and `tracker/` stay pure.** No `websockets`, `urllib`, `subprocess`,
  `http.server`, `socket`, or imports of `browser`/`service`/`server`. Purity is what
  makes the resolver unit-testable without Chrome and safe to call on any thread.
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
- **Resolution epoch guards `choose`.** Every resolution bumps
  `session.resolution_id`; a `choose` intent carrying a mismatched `resolution_id`
  gets `"stale resolution"`. Never accept a choose without the epoch check — a stale
  Lens card would click whatever now sits at that index.
- **Hover snapshots are separate.** `last_hover_snapshot` invalidates
  `last_resolution`/choose state and owns the resolution epoch. Explain reads the
  stored utterance/context, checks epoch and pointed ID before and after the model
  call. Hook context is returned verbatim, without an extra wrapper.
- **Cursor wire privacy precedes serialization.** Never read form values or use
  ancestor `innerText`; the bounded collector excludes sensitive fields and their
  associated labels. Capture history/evidence at recording stop, before ASR.
- **No selector rematching for history.** Closure-held DOM identities are retained
  for bounded history; detached/expired targets are unavailable. `@` handles map
  to snapshot selectors/rectangles only, not action tools.

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
