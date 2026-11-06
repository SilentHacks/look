---
name: gaze-telepathy
description: Understand what the user points at in Chrome using exact cursor evidence, surrounding page structure, snapshot highlights and guarded actions.
---

# Cursor context in Chrome

Hermes Gaze adds private browser evidence automatically. Its system prompt section
defines how to use that evidence; the user's message remains the question.
`[gaze_ref]` was the legacy prefix for gaze/cursor evidence, not a user request.
Current packets use `<browser_context>` instead.

## Snapshot tools

Use the `Resolution: N` number and short `@` handles in the CURRENT context. Handles are snapshot identities, not selectors. Never reuse an old resolution after a new one arrives.

The pointer is highlighted automatically when fresh hover evidence activates.
To show a different scope, use `gaze_highlight(handles=["@..."], resolution_id=N)`.
For a comparison, include both handles. Omit `hud_message` during streaming.
Deferred tools are available through `tool_describe`, then `tool_call`.
- `gaze_click(handle="@...", resolution_id=N)` activates a current control, not a data container. For "export this table", the subject is the table but the action handle is the separate Export control. Never claim execution unless the tool reports `executed: true`.
- If a target changed, detached or expired, obtain fresh evidence with `gaze_resolve(utterance=...)`; do not guess a selector or retry a mutation whose outcome is unknown.

## Voice and followups

Run `/gaze` (or `/gaze connect`) in the intended Hermes TUI/desktop session to start the Chrome companion. Hold Space in Chrome, wait for “Listening”, speak, and release. Native capture opens only during talk; microphone permission belongs to Hermes, not website origins. Switching tabs while recording cancels that recording. The companion follows focused supported tabs and retains the latest answer across routing/navigation, but actions stay bound to the captured tab and identities. Evidence freezes at recording stop, before transcription. Only the spoken words become a normal user message; the hook attaches page evidence privately. The normal answer streams to Hermes and Chrome. Followups use conversation history without reattaching old evidence or changing its epoch; fresh captures replace it. After host compaction removes evidence, `gaze_resolve` captures the current cursor, not the historical target. Current Hermes hosts refuse injected turns in lazy sessions: send one normal Hermes message first if injection is refused; the plugin cannot initialize the host agent.

Without a connected/authorized Hermes session, Chrome can answer read-only one-shot questions, clearly labeled as having no conversation followups or actions. Use `/gaze disconnect` to detach. Gateway sessions require `plugins.entries.hermes-gaze.allow_gateway_injection: true` and in-process plugin isolation.

## Simulated mode

`simulated` keeps Bayesian noisy-gaze resolution for experiments. `gaze_choose(candidate_index=...)` selects an existing Semantic Lens candidate only in that mode; it is not the cursor action or confirmation tool. Read-only results pin immediately. Reversible actions execute only at probability >=0.76 and margin >=0.26; ambiguous targets open the Lens. Destructive actions require confirmation. Camera-based eye tracking is not implemented.

## Development

Scope-ladder/up/down/save-trial controls are removed. Local replay recording is off by default; enable the `record_trials` development setting to write evidence, never audio. Treat replay files as sensitive browsing data. The demo action-risk policy is deliberately lexical plus form-submit checks; it is not a general website safety guarantee.

Commands: `/gaze demo`, `/gaze mode hover|simulated`, `/gaze resolve <question>`, `/gaze listen`, `/gaze benchmark`. The shell `hermes gaze` commands control Chrome but do not connect an interactive Hermes conversation.
