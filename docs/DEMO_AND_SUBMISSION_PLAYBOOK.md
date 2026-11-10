# Historical demo and catalogue draft — not release instructions

> Superseded planning copy, retained for provenance. The timing, accuracy,
> hands-free/dwell-action, One-Euro/click-recalibration, catalogue availability,
> validation and architecture claims below are **not current product claims or
> verified submission instructions**. Do not run these commands or reuse this
> copy for a release. Use [the current local submission draft](SUBMISSION_DRAFT.md),
> [README](../README.md) and [release gates](RELEASE_READINESS.md).

## 1. The 85-Second X Demo Video Script ("Neuralink at Home")

**Visual Setup (Critical for Credibility):**
- **Main frame (85% of screen):** Chrome showing a real, dense web interface (an analytics dashboard with a small toolbar + data table, and a two-product comparison/docs page).
- **Picture-in-Picture (bottom-left or top-right):** Camera shot of **you AND your hands resting visibly on the desk / arms crossed**, not touching the trackpad or mouse, only tapping a single hotkey with one finger while speaking. Seeing your eyes move and your hands off the mouse sells the "Neuralink at home" hook instantly.

---

### Scene 1: The Hook (0:00 – 0:10)
- **Visual:** You sit back from your MacBook, hands off the trackpad. You glance around a dense web dashboard. When you hold the hotkey, a soft cyan uncertainty spotlight appears where you're looking.
- **Voiceover / On-screen caption:**
  > *"What if Hermes had Neuralink at home? No \$3,500 headset, no hardware eye-tracker—just a MacBook webcam. You look at anything in Chrome, hold a key, and talk."*

### Scene 2: "What happens if I press this?" — Semantic Snapping (0:10 – 0:26)
- **Visual:** You look at a cluster of small toolbar icons (`Run Query`, `Schedule`, `Purge Cache`). The spotlight covers all three (~130 px radius), outlining each with subtle probability opacity.
- **You say:** *"What happens if I press this?"* (looking near `Purge Cache`).
- **Visual:** Within 250 ms, `Purge Cache` pins with `[1]` and a non-blocking tooltip card answers:
  > **`Purge Cache`** — *Clears 1.4 GB of cached query results for this workspace (reversible, forces re-fetch on next load).*
- **Caption:** *"Webcam gaze alone has ~120px of error. We fuse eye fixations with Chrome's Accessibility tree and LLM intent."*

### Scene 3: "Download this" — The Semantic Lens (0:26 – 0:46)
- **Visual:** You look at two tiny adjacent buttons: `Export CSV` and `Generate Report` (only 12 px apart).
- **You say:** *"Download this."*
- **Visual:** Because both buttons remain plausible inside the gaze covariance ellipse, the **Semantic Lens** bursts open with a crisp 180 ms spring animation: two large, separated cards (`[1] Export CSV — Downloads 1,240 rows as .csv` and `[2] Generate Report — Opens PDF builder modal`).
- **Visual:** You simply **look at Card 1** for 400 ms—the cyan dwell ring completes around `1`, Card 1 flashes, and `results.csv` downloads.
- **Caption:** *"When gaze is ambiguous, the Semantic Lens pops candidates apart so your eyes can pick with 98% accuracy."*

### Scene 4: "Export these results and make me a chart" — Multi-Granularity Action (0:46 – 1:04)
- **Visual:** You look down at the middle of a 6-column campaign performance table.
- **You say:** *"Export these results and make me a chart of Spend vs. ROAS."*
- **Visual:** Even though your eyes landed on a single `<td>` cell, the resolver promotes the candidate to the parent `<table>` (outlined in cyan: `Table · 6 cols · 42 rows`), extracts the data, saves the CSV, and renders a clean interactive chart right in the overlay / Hermes pane.
- **Caption:** *"Utterance semantics automatically resolve granularity—cell vs. row vs. whole table."*

### Scene 5: "Compare this one with this one" — Temporal Eye-Voice Alignment (1:04 – 1:18)
- **Visual:** You look at Product Card A while saying *"Compare **this** one..."*, then glance right to Product Card B while saying *"...with **this** one."*
- **Visual:** Word-level timestamps from Whisper align each *"this"* with its corresponding fixation cluster. Pin `[1]` locks onto Card A, Pin `[2]` locks onto Card B, and Hermes displays a side-by-side diff of the two items.

### Scene 6: Benchmark & Closing Card (1:18 – 1:25)
- **Visual:** Fast cut to the benchmark table (`19% raw webcam gaze -> 83% Bayesian fusion -> 98% with Semantic Lens`) and the install command:
  ```bash
  hermes plugins install hermes-gaze
  ```
- **Voiceover:** *"100% local vision. Works with mouse hover too if your camera is off. Available now in the Hermes Marketplace."*

---

## 2. X Post Template

```text
Neuralink at home for @NousResearch Hermes Agent 🧠👁️

Look at any button, table, or card in Chrome, hold a key, and talk:
• "What happens if I press this?"
• "Export these results and make me a chart"
• "Compare this one with this one"

Zero mouse. Zero hardware—just a MacBook webcam.

How it works:
Webcam gaze alone has ~130px of noise (bigger than a button). So hermes-gaze runs Bayesian reference resolution:
1. Aligns a 10s fixation buffer to Whisper word-timestamps ("this" / "these")
2. Integrates 2D gaze covariance over Chrome's live DOM + Accessibility tree
3. Pops out a Semantic Lens with dwell selection whenever two targets are too close

98% target resolution on dense UIs (vs 19% raw gaze).

Repo & Catalog PR below 👇
```

---

## 3. Hermes Plugin Catalog PR Template

When opening the PR against `NousResearch/hermes-agent`, add `plugin-catalog/entries/hermes-gaze.yaml` (check existing files in `plugin-catalog/entries/` for exact field ordering):

### Pre-PR Verification Commands (Run on MacBook)
```bash
# 1. Run the exact catalog validator + security scanner
hermes plugins validate /path/to/hermes-gaze --install-deps

# 2. Run isolated doctor test
hermes plugins doctor /path/to/hermes-gaze

# 3. Verify no compiled binaries (.task, .onnx, .pyc) are tracked in git
git status --ignored
git ls-files | grep -E '\.(task|tflite|onnx|bin|pyc|so|dylib)$' && echo "ERROR: binary tracked!" || echo "Clean: source only."

# 4. Get full 40-char commit SHA
git rev-parse HEAD
```

### PR Description Template (Covers Rule 2 & Rule 13 Disclosures)
```markdown
## Summary

Adds `hermes-gaze` (**Hermes Gaze / Telepathy**) to the Hermes plugin catalog (Hermes Agent Plugin Hackathon entry).

`hermes-gaze` brings multimodal deictic reference resolution ("point with your eyes, command with your voice") to Hermes Agent and Chrome:
- **Webcam gaze + head-pose tracker** (MediaPipe Face Landmarker + 9-point calibration + One-Euro filter + I-VT fixation buffer + online click/selection drift recalibration), plus a no-webcam mouse-hover / simulated-gaze fallback.
- **Temporal eye-voice alignment** pairing word timestamps (`faster-whisper`) for deictic words (*"this"*, *"these"*, *"that"*) with historical fixations in document coordinates.
- **Bayesian spatial-semantic resolver** combining 2D Gaussian box integration over Chrome's live DOM & Accessibility tree with verb-role priors and `ctx.llm` re-ranking.
- **Semantic Lens overlay** rendered in a closed Shadow DOM that expands ambiguous adjacent candidates into separated cards selectable by gaze dwell, voice, keyboard (`1–4`), or click.

- **Repository**: `https://github.com/<your-username>/hermes-gaze`
- **Version**: `"0.1.0"`
- **Pinned SHA**: `<40-character-commit-sha>`

## Hermes Surfaces Used
- `ctx.register_tool`: `gaze_resolve`, `gaze_choose`, `gaze_highlight`, `gaze_click`, `gaze_calibrate`, `gaze_benchmark`
- `ctx.register_system_prompt_section`: durable browser-evidence guidance, frozen for each new session
- `ctx.register_hook`: `pre_llm_call` (bounded, labelled browser evidence; pointer highlight on fresh hover activation), plus answer-stream and turn lifecycle hooks
- `ctx.register_platform`: `gaze` push-to-talk voice + gaze turn adapter
- `ctx.register_cli_command`: `gaze-chrome`, `gaze-calibrate`, `gaze-benchmark`
- `ctx.register_skill`: `gaze-telepathy`
- `ctx.llm`: semantic candidate re-ranking and consequence preview generation
- Desktop SDK (`desktop/plugin.js`): status-bar tracking indicator and calibration launcher using `@hermes/plugin-sdk` only

## Rule 13 Disclosures
- **Camera & Microphone (opt-in, local only):** Captures webcam frames via OpenCV (`cv2.VideoCapture`) when webcam tracking is enabled, and microphone audio via `sounddevice` only while the push-to-talk key is held. All video and audio are processed locally in memory; no frames or audio files are written to disk or sent over the network.
- **Local Chrome CDP connection:** Connects to the user's local Chrome debugging port (`ws://127.0.0.1:9222`, shared with Hermes's `/browser connect`) to read DOM/Accessibility layout and render the Shadow-DOM overlay.
- **First-run model weight download:** On first webcam launch, downloads Google's official MediaPipe Face Landmarker model (`face_landmarker.task`, ~3.7 MB, SHA-256 verified) from `https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task` into `plugin_data_dir() / "models"`. No binary blobs are committed to the repository.

## Validation
- `hermes plugins validate /path/to/hermes-gaze --install-deps` passes with 0 errors.
- `hermes plugins doctor /path/to/hermes-gaze` passes.
```
