# Hermes Gaze ("Telepathy") 👁️🧠

> **Multimodal Deictic Reference Resolution & Gaze Tracking for Hermes Agent & Google Chrome**  
> *"Neuralink at home: point with your eyes, command with your voice. Hermes knows what 'this' means."*  
> Entry for the **Nous Research Hermes Agent Plugin Hackathon** (Nov 2026).

---

## Overview

Raw webcam gaze tracking suffers from ~80–180 px of spatial jitter and drift—worse than the size of a standard web button.

**Hermes Gaze** solves this by treating eye tracking not as a naive mouse replacement, but as one signal in a **Bayesian Reference Resolution** engine:
1. **Temporal Eye-Voice Alignment:** Aligns a 10-second fixation buffer to speech word-timestamps (`faster-whisper`), capturing what you looked at right when saying *"this"*, *"these"*, or *"that"*.
2. **Spatial Box-Integral:** Integrates 2D gaze covariance over candidate elements extracted from Chrome's live DOM & Accessibility tree via CDP.
3. **Semantic Reranking:** Fuses intent verb priors with `ctx.llm` scoring and consequence estimation.
4. **Semantic Lens:** When two candidates are ambiguous, pops out separated cards with action previews for instant gaze-dwell, voice, or keyboard selection.

---

## Documentation

- **[PLAN.md](file:///home/codex-dev/work/hermes-gaze/PLAN.md)**: Full technical specification, math, architecture, and 6-day implementation roadmap.
- **[PRIOR_ART_AND_PITCH.md](file:///home/codex-dev/work/hermes-gaze/PRIOR_ART_AND_PITCH.md)**: Competitive analysis of the Hermes catalog, open PRs, GitHub repos, academic papers (Bolt 1980, EyePoint 2007), and marketing strategy.
- **[DEMO_AND_SUBMISSION_PLAYBOOK.md](file:///home/codex-dev/work/hermes-gaze/DEMO_AND_SUBMISSION_PLAYBOOK.md)**: 85-second X video script, X post copy, and catalog PR submission template.
