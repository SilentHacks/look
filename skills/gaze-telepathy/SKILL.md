---
name: gaze-telepathy
description: Resolve deictic pronouns ("this", "that", "these", "those", "here") in Chrome using live pointer/gaze fixations, DOM/Accessibility semantics, and Semantic Lens disambiguation.
---

# Gaze & Magic Pointer Reference Resolution (`hermes-gaze`)

When the user points at Google Chrome (via mouse hover or cursor wiggle — modes `hover` and `simulated`; camera-based tracking is not implemented) and uses deictic language such as:
- *"What happens if I press **this**?"*
- *"Download **this**"*
- *"Export **these** results and chart Spend vs ROAS"*
- *"Compare **this** one with **this** one"*

## How Deictic Resolution Works
1. **Automatic Context Injection (`pre_llm_call`):** Whenever the user types or speaks a deictic phrase while Chrome `:9222` is connected, `hermes-gaze` automatically attaches a `[gaze_ref]` block containing the top resolved DOM/Accessibility candidate(s), their spatial-semantic probabilities, bounding boxes, and 1-line consequence previews.
2. **Explicit Tools:**
   - Call `gaze_resolve(utterance=...)` to resolve what the user is currently pointing or looking at in Chrome.
   - If the resolution returns `decision: "open_semantic_lens"` or `"confirm_destructive"`, the **Semantic Lens** is already open in Chrome showing numbered cards (`[1]`, `[2]`, ...). Ask the user or wait for `gaze_choose(candidate_index=...)` (1–4).
   - Call `gaze_highlight(selector=..., label=..., hud_message=...)` to pin an element in Chrome and display your concise answer directly inside the bottom glassmorphic HUD.
   - `gaze_calibrate(mode=..., sigma_px=...)` switches `hover`/`simulated` pointing and tunes spatial uncertainty; `gaze_benchmark` runs the accuracy suite.
3. **Voice Push-to-Talk:** Holding the hotkey in Chrome records mic audio in-page; the overlay ships it as a `transcribe` intent over the `__hermesGazeIntent` CDP binding (no HTTP endpoints), local `faster-whisper` returns word-level timestamps, and the transcript is re-sent as a `resolve` intent — so spoken *"this"*/*"these"* land on the same temporal alignment path as typed deictics.

## Decision Policy
- **Read-Only Questions** (*"what does this do?"*, *"explain this"*) → `pin_immediate`: Never block with a confirmation modal. Answer immediately using the top candidate (or briefly explain both `#1` and `#2` if they are close in probability).
- **Reversible UI Actions** (*"click this"*, *"sort by ROAS"*) → `execute_safe` when top probability `P >= 0.76` and margin `>= 0.26`; otherwise `open_semantic_lens` and let the Lens cards separate the targets.
- **High-Consequence / Irreversible Actions** (`delete`, `submit`, `pay`, `buy`, `send`, `revoke`, `purge`) → `confirm_destructive`: Always require explicit confirmation via the Semantic Lens before clicking.

## User Commands
- `/gaze demo` — launch Chrome with CDP (:9222) on the demo dashboard and inject the HUD.
- `/gaze mode hover|simulated` — switch between the exact Magic Pointer and noisy-gaze simulation.
- `/gaze resolve <utterance>` — resolve a typed deictic phrase against the live tab.
- `/gaze listen` (alias `/gaze voice`) — record mic audio, transcribe, and resolve.
- `/gaze benchmark` — print the quantitative accuracy table; `/gaze status` (or bare `/gaze`) shows connection/mode/drift state.
- `hermes gaze` exposes the same subcommands from the shell (`status`, `demo --mode`, `listen --duration`, `voice`, `benchmark --trials`, `resolve`).
