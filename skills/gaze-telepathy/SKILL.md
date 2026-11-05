---
name: gaze-telepathy
description: Resolve deictic pronouns ("this", "that", "these", "those", "here") in Chrome using live pointer/gaze fixations, DOM/Accessibility semantics, and Semantic Lens disambiguation.
---

# Gaze & Magic Pointer Reference Resolution (`hermes-gaze`)

When the user points at Google Chrome (via mouse hover, cursor wiggle, or webcam gaze) and uses deictic language such as:
- *"What happens if I press **this**?"*
- *"Download **this**"*
- *"Export **these** results and chart Spend vs ROAS"*
- *"Compare **this** one with **this** one"*

## How Deictic Resolution Works
1. **Automatic Context Injection (`pre_llm_call`):** Whenever the user types or speaks a deictic phrase while Chrome `:9222` is connected, `hermes-gaze` automatically attaches a `[gaze_ref]` block containing the top resolved DOM/Accessibility candidate(s), their spatial-semantic probabilities, bounding boxes, and 1-line consequence previews.
2. **Explicit Tools:**
   - Call `gaze_resolve(utterance=...)` to resolve what the user is currently pointing or looking at in Chrome.
   - If the resolution returns `decision: "disambiguate"` or `"confirm_destructive"`, the **Semantic Lens** is already open in Chrome showing numbered cards (`[1]`, `[2]`, ...). Ask the user or wait for `gaze_choose(candidate_index=...)`.
   - Call `gaze_highlight(selector=..., label=..., hud_message=...)` to pin an element in Chrome and display your concise answer directly inside the bottom glassmorphic HUD.

## Decision Policy
- **Read-Only Questions** (*"what does this do?"*, *"explain this"*): Never block with a confirmation modal. Answer immediately using the top candidate (or briefly explain both `#1` and `#2` if they are close in probability).
- **Reversible UI Actions** (*"click this"*, *"sort by ROAS"*): Execute immediately when top probability `P >= 0.78` and margin `>= 0.30`; otherwise let the Semantic Lens disambiguate.
- **High-Consequence / Irreversible Actions** (`delete`, `submit`, `pay`, `buy`, `send`, `revoke`, `purge`): Always require explicit confirmation via the Semantic Lens before clicking.
