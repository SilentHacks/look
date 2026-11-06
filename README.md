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
- **Persistent CDP sessions.** One isolated-world websocket per supported tab; reads follow focus, while actions retain their captured tab/document. Ordered nonce-bearing binding intents carry questions and native talk controls. No HTTP resolution/action endpoints.
- **Honest failures.** Missing/detached/expired evidence and uncertain click outcomes are reported, never replaced with synthetic targets or silently retried mutations.
- **Pointing modes:** `hover` supplies exact cursor identity and surrounding structure, with explicit snapshot tools for highlighting/actions. `simulated` retains Bayesian noisy-gaze resolution. Camera tracking is not implemented.
- **Demo page:** a GET-only static server on `127.0.0.1:9111` serves `benchmark/benchmark_page.html` plus `/api/status` (no POST, no CORS). The overlay itself is always injected over CDP, never fetched from a server.

### Cursor context and actions

Hover supplies evidence, not a preselected subject. The model sees the pointed
cell, row/column/table/panel handles, surrounding structural text and separate
controls. Tables prioritize pointed rows and headers, then up to eleven neighbours
(visible rows first, nearest rows next), with explicit omission counts. System guidance is registered
separately from per-turn `<browser_context>` evidence, which labels the user's
question and pointer age. The complete escaped envelope, including its
`Resolution` epoch, is at most 6000 characters. New guidance requires a new session.

Hovering inside a card also captures its enclosing item and nearest local peer
collection. Semantic items, headed flex/grid children and repeated linked blocks
supply separate member facts, viewport rectangles and exact-node handles; the
hovered leaf stays the only pointer hit. Group headings/notes exclude member text.
Hidden variants and editable values are excluded; rendered offscreen peers are
explicitly labelled. Pointer hits descend through open shadow roots, preserving
root-local sensitive-label exclusions.

Frames (including same-origin frames), closed components and canvas contents are
not traversed. Frame hits explicitly say that the page underneath is covered and
the frame content was not read; they never substitute the hidden page's content.
Dialogs and wide fixed/sticky surfaces are labelled as potentially covering the
page, not classified as consent by their wording. Dismissing an overlay restores
normal pointer capture; the companion never dismisses it automatically. Occluded
controls are excluded. This is bounded DOM/layout evidence, not full visual scene
understanding; unrelated portal siblings are not inferred as peers.

Typed questions use the latest real Chrome target and its age. Voice evidence
freezes at recording stop before ASR; real word timestamps select preceding
cursor identities, including two spoken referents. Detached or replaced nodes
never rematch selectors. Password/payment fields and associated labels are
filtered before serialization; page text stays inside an escaped untrusted fence.

Fresh hover evidence automatically highlights the pointed handles. After each
answer, one bounded model call selects the captured answer scope; no tool turn is
needed. `gaze_highlight(handles=[...], resolution_id=N)` remains available for
explicit scope changes. Pins follow the original elements through scrolling and
same-document routes. Full navigation revokes those identities and clears pins.
Background-tab scope changes fail safely rather than highlighting the focused
tab; the original pointer highlight remains on its source document.
`gaze_click(handle=..., resolution_id=N)`
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
Card groups search at most eight ancestor levels and 128 children per container;
they retain 16 members (more only to preserve pointed items), with visible peers
first. Collection caps and packet omissions are explicit; capped membership
counts are lower bounds.
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

The Quiet Signal HUD uses a compact graphite/sage surface with separate target,
question and answer areas. Drag its header to reposition it; Minimize keeps a
small expandable header. Explain this, Summarize and Compare submit page-neutral
questions about the captured target. Pointer/Simulated switches pointing modes;
Clear dismisses highlights and the reply. Keyboard focus is visible, narrow
viewports scroll the body, and reduced-motion preferences disable transitions.

The HUD shows listening, transcribing, queued, thinking and completion/error
states. Without a connected/authorized session, read-only questions can use a
clearly labeled one-shot call, with no conversation followups or actions. Action
requests fail rather than silently using that fallback. ASR file downloads are
quiet without suppressing errors or redirecting process output.
Browser-supplied compressed audio still requires `ffmpeg` on Hermes's PATH
(or in a standard macOS location), with MIME type preserved through decoding.
Native microphone PCM/WAV uses the in-process fast path and does not require
`ffmpeg`. Decoder failures report the real diagnostic, never reinterpret
compressed bytes as PCM.

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
   CDP Chrome profile on the configured port (default 9222), not the everyday
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
   The post-answer scope can widen without a tool call. Scroll: the outline
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
