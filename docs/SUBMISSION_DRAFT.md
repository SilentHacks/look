# Look: local submission draft

**Prepared for owner review. Not posted or submitted.** Product status: technical
source beta. No public release pin, Store approval, catalogue acceptance, new
recording or user/device sign-off is claimed. Organizer form fields, deadline,
video length and tagging rules need checking against the current official rules.
The old playbook is historical, not the source of those requirements.

## Copy ready for review

**Name:** Look

**One line:** Ask Hermes about what you point at in Chrome, with private answers
and guarded browser actions.

**Short description:**

Point at something in Chrome and ask Hermes about it. Type your question, or hold
Space, wait for Listening, then speak. Answers appear in a private card.
Look can also fill forms, click controls and navigate. Sending, buying, deleting
and other consequential or unclear actions need your mouse approval on a review card.

Speech recognition and optional calibrated eye tracking run locally on your Mac.
Your questions and page evidence still go to your configured model and may stay
in Hermes history. This Apple Silicon source beta includes experimental
broad-region eye tracking, not a precise gaze pointer. It is not a Chrome Web Store release.

**What is implemented:**

- Exact cursor identity, bounded structural context and frozen source ownership.
- Protected typed entry and native push-to-talk, with private streamed answer/history
  cards, follow-ups, recall, Stop and local read-aloud.
- Guarded read/fill/click/keys/tabs/navigation/scroll/wait operations, with
  content-bound single-use mouse approval for consequential/ambiguous controls.
- Optional nine-point personal webcam calibration in a separate window.
  Gaze supplies evidence, never action approval.
- Stock Hermes integration. Separate Chrome, explicit native existing-Chrome
  consent and a development extension are distinct connection lanes.

**Evidence statement:**

Local pinned-source installation, refused dependency preparation, later enable,
exact-pin discovery, isolated stock registration and scoped removal were
exercised with stock Hermes. Security/browser/race reports also exist from
private Chrome and fake-device/scripted-provider runs. They are not ordinary
signed-in-user, physical-device or current live-provider proof. The
[release record](RELEASE_READINESS.md) names the remaining gates and versions.
Do not substitute test totals for those missing journeys.

**Technical distinction:**

The model chooses what part of the page your question refers to. Python enforces
captured identities, ownership, risk and approval rules. Website and answer text
cannot grant approval. Private words and input live in opaque, script-disabled frames.
Closed shadow DOM alone is not the privacy boundary. Unknown mutations are not
silently retried. This is not protection from another authorized debugger or
malicious same-user software.

**Limitations/disclosures:**

Supported trial lane: native arm64 Apple Silicon Mac, standard Chrome, one
display, English, stock local in-process Hermes with explicit input permission.
Existing-browser connections have broad debugger authority. Cross-origin frames,
canvas and unknown widgets may be unavailable. Typing/navigation can have site
side effects. Eye tracking has no established population accuracy. Questions and
bounded page evidence may persist in Hermes/provider history. Models download
only through explicit setup. Dependencies/native wheels are prepared separately.
Optional TypeSafe highlighting adds its disclosed question/scope request when
configured. See [privacy](../README.md#privacy-and-action-limits) and
[third-party notices](../THIRD_PARTY_NOTICES.md).

**Source/licence:** MIT repository with attributed vendored/runtime/model terms.
The configured origin is `https://github.com/SilentHacks/hermes-gaze`. Public
visibility, the final integrated commit and an approved installation URL are not
verified here. No invented catalogue command or unpublished release SHA belongs
in submitted copy. [Full attribution](../THIRD_PARTY_NOTICES.md).

## Suggested 85-second recording plan

This is a plan for a **user-operated actual recording**, not recorded evidence.
Use the final reviewed installation and a local/non-sensitive page. Show the
connection lane, consent and beta label honestly. Do not edit scripted behavior
into an apparently live result.

| Time | User-operated scene |
|---|---|
| 0–10s | “I ask Hermes about what I point at.” Show a local table in Chrome and the actual connection lane. |
| 10–30s | Point to a cell, press Right Option and ask a real typed question. Show the answer arriving in the private card. |
| 30–45s | If physical mic acceptance passes: hold Space, wait for Listening, ask a follow-up and release. Otherwise demonstrate typed follow-up and say voice was not shown. |
| 45–65s | On a local fixture, request a safe change and then a consequential fixture control. Show the protected review, then use a real primary mouse click. Never send mail, buy, publish or delete real data. |
| 65–75s | If personal calibration/check and broad-region pointing work on camera, show them with the beta label. Otherwise omit gaze performance claims and demonstrate the cursor. |
| 75–85s | Show Stop and say: “Apple Silicon source beta. Tracking is local. Questions and page context go to my configured model.” Show only the owner-approved source/install link after publication. |

Do not display keys, pairing tickets, personal tabs, account names, receipts,
terminal history or model-profile secrets. Use silence or independently cleared
narration. Apple fallback voice publication rights are not established. Keep
asset attribution with the submitted source. Label any cuts, simulated devices,
scripted provider or prerecorded answer that appears in the video.

## Announcement draft: hold for approval

> I built Look to ask Hermes about what I point at in Chrome. Type a question or
> hold Space to talk, then read the answer in a private card. Browser actions
> that send, buy, delete or have unclear effects need your mouse approval.
> This is an Apple Silicon source beta. Optional eye tracking is experimental.
> Page context goes to your configured model. See the reviewed README for setup and limits.

Do not post until the owner approves the exact text, media, destination and
public commit/link. No novelty superlative, “mind reading”, population accuracy,
Marketplace/Store availability or all-platform claim is supported by this draft.

## Owner submission checklist

- [x] Integrate approved extension/test/release tracks. The final local pin is in the integration handoff.
- [ ] Clear the final-browser blocker and applicable [release gates](RELEASE_READINESS.md) before recording acceptance.
- [ ] Review intended refs, author metadata, historical traces and final source/media artifacts.
- [ ] Verify current organizer eligibility, deadline, fields, video/tag and attribution requirements.
- [ ] Run headed user/provider/device journeys for every behavior shown. Keep failures and limits honest.
- [ ] Review recording for private content and clear audio/image/voice rights.
- [ ] Approve exact public source pin, installation command, media and outbound text.
- [ ] After authorized publication, verify clean-home public-pin install and link accessibility.
- [ ] Explicitly authorize each PR, post, publication and submission. Retain the resulting receipt.

No checkbox here was completed by inference from a different lane or old report.
