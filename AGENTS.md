# AGENTS.md — hermes-gaze contributor guide

Written for coding agents working in this repository. Read this before editing.

Hermes Gaze ("Telepathy") is a Hermes Agent plugin that resolves deictic phrases
("what does **this** do?", "export **these** results") against Google Chrome's live
DOM/Accessibility tree by fusing pointer/gaze fixations with speech timestamps via
Bayesian spatial-semantic resolution.

## Project map

| Path | What lives here |
|---|---|
| `plugin.yaml` | Plugin manifest: tools/hooks/skill declarations, config schema. Keep 1:1 with `register()`. |
| `__init__.py` | `register(ctx)` entry point — wires tools, the `pre_llm_call` hook, the `/gaze` slash command, `hermes gaze` CLI, and the bundled skill. Thin wiring only. |
| `tools.py` | Tool schemas (`gaze_resolve`, `gaze_choose`, `gaze_highlight`, `gaze_calibrate`, `gaze_benchmark`) + thin handlers that delegate to `service.py`. |
| `service.py` | The session-facing layer: `resolve_now` (resolution + browser render), `handle_intent` (dispatches `resolve`/`choose`/`explain`/`transcribe`/`configure` binding intents), `explain_element`, `set_runtime`. |
| `config.py` | `GazeConfig` dataclass + `GazeConfig.from_ctx(ctx)` — plugin settings only. |
| `voice.py` | `transcribe_audio_buffer` (lazy faster-whisper), `record_microphone`, `MAX_AUDIO_BYTES`. |
| `server.py` | `SessionHttpServer`: GET-only static server on `127.0.0.1:9111` for the demo page (`/`, `/index.html`, `/api/status`). No POST, no CORS, no resolution endpoints. |
| `cli.py` | `hermes gaze` subcommand + `/gaze` slash handler. |
| `browser/cdp_bridge.py` | `CdpSession` (one persistent websocket per pinned tab on a dedicated worker-loop thread, `Runtime.addBinding("__hermesGazeIntent")`, `eval_js`, `set_intent_handler`) and `GazeSession` (ring buffer + tracker + recalibrator + resolution epoch + `ingest` + `choose` + `configure`). `overlay.js` sits beside it. |
| `browser/overlay.js` | The in-page terminal: spotlight, pins, HUD, Semantic Lens cards, mic capture, `extractCandidatesNear`. Talks to Python ONLY through the `__hermesGazeIntent` binding and `api.onIntentResult`. |
| `resolver/` | PURE modules — `bayesian_fusion.py` (scoring + decision policy), `temporal_aligner.py`, `data_extractor.py`. No I/O imports allowed (enforced by `tests/test_layering.py`). |
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

## Commands

```bash
python3 -m unittest                              # whole suite (stdlib; no Chrome needed)
python3 -m unittest tests.test_service_intents   # one module
python3 -m py_compile tests/*.py service.py tools.py
node --check browser/overlay.js                  # JS syntax check
ruff check                                        # if ruff is installed
python3 -m benchmark.run_benchmark 2>/dev/null   # accuracy table (run from plugin root)
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
