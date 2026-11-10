# Historical prior-art search and pitch — 2026-11-05

> Research snapshot and proposed marketing, not a current competitive audit.
> The absolute novelty, catalogue counts, accuracy, hands-free and “Neuralink”
> comparisons below are unverified historical claims, not release evidence or
> medical/accessibility claims. No exhaustive novelty search is established.
> Use [the current submission draft](SUBMISSION_DRAFT.md) for reviewable copy and
> [README](../README.md) for implemented behavior.

## 1. Executive Summary: Has Anyone Done This?

**No.** Across the Hermes Marketplace, all 170+ open/recent plugin catalog PRs in `NousResearch/hermes-agent`, GitHub repositories, and academic HCI literature, **no one has combined webcam gaze tracking, live DOM/accessibility semantics, deictic speech alignment, and an LLM browser agent with an uncertainty-driven expansion UI.**

The closest work falls into four separate buckets that have never been connected:

1. **Hermes plugins:** Zero gaze, webcam, or eye-tracking plugins exist in the catalog or open PR queue.
2. **Open-source gaze engines (Fovea, WebGazer, GazeTheWeb, Heliox-OS):** Treat gaze as a replacement mouse cursor or raw `(x, y)` stream. None fuse gaze with DOM semantics + natural language + an LLM agent.
3. **Academic HCI (Bolt 1980, EyePoint 2007, GazePointAR 2024):** Solved isolated pieces (deictic speech, gaze magnification, or AR VLM queries) but never in a live browser DOM with probabilistic disambiguation and an action-taking agent.
4. **Commercial hardware (Apple Vision Pro, Tobii, Neuralink):** Prove the UX ("look and pinch / speak") is the gold standard of spatial/neural computing, which makes bringing a software-only version to any MacBook webcam a great pitch.

---

## 2. Hermes Plugin Catalog & Hackathon Queue Audit (Nov 5, 2026)

I audited the live Hermes Marketplace (`/docs/plugins`) and queried the `NousResearch/hermes-agent` GitHub repo for all issues and PRs mentioning `gaze`, `eye`, `webcam`, `camera`, `neuralink`, `bci`, `voice`, or `browser`, plus the ~173 recent `plugin-catalog` PRs.

### Findings in `NousResearch/hermes-agent`
- **Gaze / Eye tracking / Webcam plugins:** **0** (the only hits for "gaze" in the repo are PR #89101 adding animated eye-drift to Bot Mode blob avatars).
- **Closest adjacent plugins in the hackathon queue:**
  - **`pinpoint` (PR #149426):** Audits a live page in Hermes Desktop's Browser pane for WCAG accessibility issues and renders numbered pins over offending elements. *Relevance:* Shows numbered in-page pins work well visually, and validates that browser-overlay plugins are well-received. Zero overlap with gaze or voice.
  - **`visor` (PR #149442):** Live agent canvas pushing visual blocks over SSE. Zero overlap.
  - **`gadget` (listed in catalog):** Push-to-talk from an ESP32 hardware button/mic into Hermes via a gateway platform adapter. *Relevance:* Proves our exact architecture for turning push-to-talk voice into a Hermes chat turn.
  - **`voice-gate` (PR #149072):** Voice-related gate plugin. No gaze/browser component.

**Conclusion for the hackathon:** You have a completely clear lane. Almost every other submission is a security guard (`say-do-gate`, `injection-guard`, `bumblebee-guard`, `cost-sentinel`), an MCP wrapper, a memory backend, or a dashboard widget. A multimodal hardware-in-the-loop interaction paradigm will stand out immediately in the 90-second X video feed.

---

## 3. Open-Source & GitHub Landscape

| Project | Stars / Status | What It Does | How We Differ |
|---|---|---|---|
| **WebGazer.js** (Brown HCI) | ~3.5k★ | In-browser JS webcam eye tracker that self-calibrates from mouse clicks. | Runs inside a single page (loses state across navigations unless injected everywhere); returns noisy `(x, y)` coordinates only; no LLM, no voice, no semantic fusion, no disambiguation UI. (We *do* borrow its click-recalibration insight.) |
| **Wega-Labs/fovea** | 8★ (2026) | Python + MediaPipe 0.10.x webcam gaze engine with calibration and NDJSON event stream. Tagline: *"Your gaze is an input."* | Positioning as a low-level OS pointer/input engine. explicitly lists fixation/dwell, target awareness, and multimodal fusion as "still planned". No DOM, no voice, no agent. |
| **VyomKulshrestha/Heliox-OS** | 70★ | Local-first desktop agent listing voice, gesture, gaze, and browser automation. | Treats gaze as a separate cursor/accessibility mode rather than probabilistic reference resolution fused with DOM and speech timestamps. |
| **developmentseed/gazet** | 24★ | "Lightweight LLM-driven Area-of-Interest retrieval" | Map/geospatial area-of-interest lookup, not eye tracking. |
| **MAMEM/GazeTheWeb** | 33★ | Custom Chromium browser for hardware eye trackers (Tobii) with enlarged browser chrome. | Requires dedicated hardware tracker; replaces the browser instead of attaching to Chrome via CDP; no LLM or voice. |
| **PINTO0309/screen-eye-tracking** | 55★ | Python MediaPipe desktop app that draws a red dot where you look on screen. | Pure coordinate estimation; demonstrates the ~100–180 px jitter problem when used without semantic snapping. |

---

## 4. Academic & Commercial Prior Art (Cite These!)

Citing two or three of these in your README and video shows deep technical grounding and explains *why* naive eye tracking fails while your approach succeeds:

1. **"Put-That-There: Voice and Gesture at the Graphics Interface" — Richard Bolt (MIT Media Lab, SIGGRAPH 1980)**
   - *What it did:* The foundational multimodal UI paper. Users pointed at a wall display and said *"Create a blue square there"* or *"Move that to the right of the green triangle."*
   - *How you build on it:* Eyes replace pointing; a live web DOM + accessibility tree replaces the toy shapes world; Hermes replaces the scripted command parser.

2. **"EyePoint: Practical Pointing and Selection Using Gaze and Keyboard" — Manu Kumar, Andreas Paepcke, Terry Winograd (Stanford HCI, CHI 2007)**
   - *What it did:* Solved low eye-tracker accuracy with a two-step loop: look at target → hold a hotkey → screen region around gaze magnifies → look at the target inside the magnified view → release hotkey to click.
   - *How you build on it:* EyePoint did **pixel magnification** (which distorts layout and only works for clicking). You do **semantic candidate expansion** — popping out only the plausible DOM elements as clean, readable cards with LLM-generated action previews, and only when gaze + speech remain ambiguous.

3. **"GazePointAR: A Context-Aware Multimodal Voice Assistant for Pronoun Disambiguation in Wearable AR" — Lee et al. (CHI 2024)**
   - *What it did:* Used an AR headset's eye tracker + object detection + LLM to resolve *"What is this?"* in the physical world.
   - *How you build on it:* Brings gaze-assisted pronoun disambiguation to desktop web browsing with a standard webcam, adding exact DOM/AX handles, Bayesian spatial-semantic fusion, and an interactive disambiguation Lens so the agent can take reliable browser actions.

4. **Apple Vision Pro (visionOS, 2024) & Neuralink "Telepathy" (Noland Arbaugh demo, 2024)**
   - *Vision Pro:* Proved that **eyes select ("where"), hands/voice confirm ("what")** is the most natural interaction loop ever shipped—and that hiding the raw eye cursor while only highlighting the snapped UI element is critical so users don't feel jitter.
   - *Neuralink:* Demonstrated effortless cursor/intent control ("I just look where I want to go and think about clicking").

---

## 5. Marketing Spin: "Neuralink at Home"

### Why the Hook Works
- **Instant comprehension in 3 seconds on X:** Everyone has seen the Neuralink and Vision Pro demos. Saying *"Neuralink at home — no skull surgery, no \$3,500 headset, just your MacBook webcam and Hermes"* immediately tells viewers what they are watching.
- **Strong contrast with the rest of the hackathon:** Most entries are developer utilities. A 90-second video where you sit back with your hands off the mouse/trackpad, look at parts of a complex webpage, speak naturally, and watch Hermes highlight, disambiguate, and execute feels like magic.

### How to Balance the Hype with Judge Scoring Criteria
The hackathon judges score on **Usefulness, Reliability, Polish, and Creativity**, and Nous maintainers are rigorous engineers (as seen in the catalog admission rules). If you *only* pitch "mind control," an engineer might dismiss it as a gimmicky webcam mouse.

Use a **two-layer pitch**:

- **The Viral Hook (X video title & first 5 seconds):**
  > *"Neuralink at home: I gave Hermes Agent eye-tracking and deictic intent resolution. Look at anything in Chrome, hold `Fn`, and just say 'what happens if I press this?' or 'export these and chart them' — zero mouse, zero hardware, just a MacBook webcam."*
- **The Engineering Substance (next 60 seconds & README):**
  > *"Raw webcam gaze has ~120 px of error—worse than the size of a button. What makes this actually work is **Bayesian Reference Resolution**: fusing a fixation ring buffer aligned to speech word-timestamps, Chrome's live Accessibility/DOM tree, and LLM intent scoring—plus a semantic Lens that pops apart ambiguous targets when confidence is low."*

### Name & Tagline Ideas
- **Plugin ID:** `hermes-gaze` or `telepathy` or `fovea-hermes` (`telepathy` leans into the Neuralink spin—Neuralink's first product is literally named **Telepathy**—while `hermes-gaze` is self-explanatory in the catalog. **Recommendation:** Catalog slug `hermes-gaze`, display title **"Hermes Telepathy (Gaze & Intent)"** or **"Hermes Gaze — Telepathy for the Browser"**).
- **One-line catalog description (must be concise per catalog rules):**
  > *"Point with your eyes, command with your voice: multimodal gaze + DOM + speech reference resolution for Chrome and Hermes Agent."*
