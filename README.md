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

- **One resolver, in Python.** All spatial-semantic scoring and the decision policy (`pin_immediate` / `execute_safe` / `open_semantic_lens` / `confirm_destructive`) live in `resolver/bayesian_fusion.py`. `browser/overlay.js` is a *terminal*: it renders the spotlight, pins, HUD, and Semantic Lens, and ships the raw inputs (pointer, fixations, candidates, mic audio) — it never re-implements resolution.
- **Persistent CDP session.** `browser/cdp_bridge.py` keeps ONE websocket per pinned Chrome tab on a dedicated worker loop and registers `Runtime.addBinding("__hermesGazeIntent")`. Overlay → Python traffic is JSON intents (`resolve`, `scope`, `record`, `choose`, `explain`, `transcribe`, `configure`); Python → overlay replies are `window.__HERMES_GAZE_OVERLAY__.onIntentResult(...)` evals. There is no HTTP API surface.
- **Honest failures.** When candidates or fixations are missing, `service.py` returns `{"ok": false, "error": ...}` — never a fabricated stand-in.
- **Pointing modes:** `hover` (Magic Pointer, σ = 24 px) and `simulated` (cursor + Gaussian noise, default σ = 120 px) for developing and benchmarking the resolver under eye-tracker-grade uncertainty; camera-based tracking is deliberately not implemented in this revision.
- **Demo page:** a GET-only static server on `127.0.0.1:9111` serves `benchmark/benchmark_page.html` plus `/api/status` (no POST, no CORS). The overlay itself is always injected over CDP, never fetched from a server.

### Scope context (demo foundation)

Point at a campaign cell and resolve a question. The HUD offers **Cell · Row ·
Column · Table · Panel**; rows and columns are sibling alternatives, not ancestors.
Buttons and product cards also expose their containing scopes. Labels and summaries
come from DOM semantics; demo `data-gaze-*` annotations are optional.

- Click a scope, or use **↑** for the next alternative and **↓** for the previous.
  This changes the subject and highlight, **never clicks a page control**.
- The compact `[gaze_ref]` includes the selected subject, nearby scope alternatives,
  and associated action controls. The hook and HUD explanations use the same context.
  Action controls are described separately from the subject; this is not a new
  automatic scope decider or action-execution system.
- Click **Confirm intended scope & save trial** even when the initial selection
  was correct. Corrections are not ground-truth confirmations until you confirm.

Resolution, correction, and confirmation events append to `replay.jsonl` in
Hermes's `plugin_data_dir("hermes-gaze")`, or `~/.cache/hermes-gaze/` standalone.
These local recordings contain page URLs, utterances, word timestamps, pointer/
fixation samples, DOM candidates, and results, **not microphone audio**. Treat them
as potentially sensitive browsing data. Each line is JSON; `record` events identify
confirmed intended scopes for later replay. Step 1 adds no external model service,
training pipeline, or automatic scope-selection benchmark.

### Phase 0: Hermes session probe

This opt-in experiment uses a **hardcoded two-row fixture**, not live cursor
context. Normal `/gaze` resolution is unchanged. In the profile you want to test,
set `plugins.entries.hermes-gaze.allow_gateway_injection: true` and use in-process
plugin isolation. Restart Hermes after loading the plugin changes.

```text
/gaze demo
/gaze probe start
/gaze probe status
/gaze probe followup
/gaze probe status
/gaze probe stop
```

`start` injects an ordinary user message into the calling session. The matching
hook supplies the fixture and asks the configured model to highlight its table;
text-stream hooks mirror the answer into Chrome, with a final-response backstop.
`followup` asks for a random code from the first hook context **without resending
that context**. Status includes acceptance, hook/stream/tool observations, timing,
and recall results. `stop` detaches observation; it does not cancel a running turn.
The commands do not alter consent settings or choose a different model.

For repeatable development checks, run `benchmark/probe_phase0.py --output
/tmp/gaze-phase0.json` with Python from the Hermes environment. It uses temporary
private config/credential copies, a separate headless Chrome, synthesized speech
through the real transcriber, and three initial/follow-up pairs for each backend
session source (`tui`, `desktop`). It checks actual HUD text and table geometry.
This tests backend delivery, **not the native desktop renderer or a physical
microphone**; run the commands above in the app for those live-surface checks.

Recorded observations: [`benchmark/phase0_results.json`](benchmark/phase0_results.json).
All six controlled initial/follow-up pairs passed on the configured Beam model.
Hook-only context survived into the next turn without resending it; first answers
took 2.0–5.1 seconds after injection (ASR excluded). This is integration evidence,
not a broad model-reliability result; exploratory failures and UI limits are listed
with the measurements.
An additional actual TUI run rendered the answer and probe status, with 16.3 seconds
to first text including tool discovery. Its throwaway harness timed out during
shutdown; only the rendering observation is claimed. Native Desktop could not
launch because its packaged app was missing.

## Quickstart

```bash
# inside Hermes (slash command)
/gaze demo                 # launch Chrome (:9222) on the benchmark dashboard + inject the HUD
/gaze mode simulated       # noisy-gaze mode ('/gaze mode hover' for the exact Magic Pointer)
/gaze resolve what does this do
/gaze benchmark            # reproducible accuracy table across noise levels
```

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
