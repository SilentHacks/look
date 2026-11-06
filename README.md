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

- **Python owns policy.** Noisy simulated gaze uses Bayesian resolution. Hover sends exact cursor evidence to the model, which chooses scope; Python enforces snapshot ownership and action confirmation. The overlay only collects DOM facts and renders results.
- **Persistent CDP session.** One websocket per pinned tab; ordered nonce-bearing binding intents include `submit`, `resolve`, `choose`, `explain`, `transcribe`, `confirm_action` and `configure`. No HTTP resolution/action endpoints.
- **Honest failures.** Missing/detached/expired evidence and uncertain click outcomes are reported, never replaced with synthetic targets or silently retried mutations.
- **Pointing modes:** `hover` supplies exact cursor identity and surrounding structure, with explicit snapshot tools for highlighting/actions. `simulated` retains Bayesian noisy-gaze resolution. Camera tracking is not implemented.
- **Demo page:** a GET-only static server on `127.0.0.1:9111` serves `benchmark/benchmark_page.html` plus `/api/status` (no POST, no CORS). The overlay itself is always injected over CDP, never fetched from a server.

### Cursor context and actions

Hover supplies evidence, not a preselected subject. The model sees the pointed
cell, row/column/table/panel handles, surrounding structural text and separate
controls. Small demo tables include all five rows and six columns; larger tables
prioritize pointed rows, headers and omission counts. System guidance is registered
separately from per-turn `<browser_context>` evidence, which labels the user's
question and pointer age. The complete escaped envelope, including its
`Resolution` epoch, is at most 6000 characters. New guidance requires a new session.

Typed questions use the latest real Chrome target and its age. Voice evidence
freezes at recording stop before ASR; real word timestamps select preceding
cursor identities, including two spoken referents. Detached or replaced nodes
never rematch selectors. Password/payment fields and associated labels are
filtered before serialization; page text stays inside an escaped untrusted fence.

Fresh hover evidence automatically highlights the pointed handles.
`gaze_highlight(handles=[...], resolution_id=N)` changes that highlight when the model
uses a different scope, including captured rows and columns. `gaze_click(handle=..., resolution_id=N)`
activates a current control. Risky labels/classes, destructive utterances and form
submissions require a trusted primary mouse click on the Chrome confirmation
card. Synthetic clicks, spoken/tool confirmation, stale epochs and changed targets
cannot approve it. Safe-looking controls execute immediately.
Chrome displays confirmation execution, cancellation and failure outcomes.

The action policy is demo-oriented and lexical, not a general website safety
guarantee; disguised controls can evade classification. Privileged CDP/OS clients
are outside the page-script/tool-argument confirmation boundary. Mutation requests
are not automatically replayed after transport loss; an unknown outcome revokes
the active snapshot.

Collection is bounded: 60 seconds/256 cursor intervals, 64 target identities, 32
retained captures, 1024 rows/table, 64 collected columns and 8192 captured members/
handles. Model rows use at most 12 cells, with the pointed value described
separately; column handles retain captured members, never replacement cells.
Scope navigation, up/down scope correction and save-trial controls are removed.
Replay recording is off unless `record_trials: true`; files may contain sensitive
browsing evidence but never microphone audio.
Hermes also persists injected page evidence in `state.db` (`api_content`),
independently of plugin replay recording.

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

Restart Hermes after changing plugin configuration. Run `/gaze` or `/gaze connect`
in the TUI/desktop conversation that should receive speech, then `/gaze demo`.
Hold Space in Chrome, speak and release. Only your words become a normal user
message; the matching session hook attaches frozen page context. The answer
streams into Hermes and Chrome, with a final-response backstop.
Refreshing cursor evidence through a tool does not interrupt that turn's answer stream.
Spoken or typed followups use conversation history without reattaching old evidence
or changing its epoch. A connected non-deictic utterance without a target is delivered
as plain text. After compaction, resolving again captures the current cursor, not
the historical target. `/gaze disconnect` revokes pending and active action ownership;
it does not cancel a Hermes turn already accepted by the host.

The HUD shows listening, transcribing, queued, thinking and completion/error
states. Without a connected/authorized session, read-only questions can use a
clearly labeled one-shot call, with no conversation followups or actions. Action
requests fail rather than silently using that fallback. ASR file downloads are
quiet without suppressing errors or redirecting process output.

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
Prompt-only mode uses fresh sessions and the configured model for headers, a cell,
a button, a wider-scope followup, hostile page text, a synthetic stale cursor,
pasted code and an explicit plugin question. `--repo-folder` enables project rules;
the default uses a neutral folder. Reports retain answers, captures and browser
operations; `--plugin-root` can select an isolated committed baseline.
Historical Phase 0/1 measurements remain in `benchmark/*results.json`; the
hardcoded `/gaze probe` experiment is removed.

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
