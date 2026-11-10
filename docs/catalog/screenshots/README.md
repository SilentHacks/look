# Fixture-backed Look UI

**Scripted answers, no provider inference. Apple Silicon macOS beta; English-first.**

These original, unedited screenshots show the actual running Look extension and
protected renderer in disposable Chrome for Testing. Captured from source
`610c5a78a1ef5e987f64222a7999fbf28a24a310`, before the NVIDIA v3 backend integration;
they are not captures of v3 setup or a new end-to-end installation.
The fixture transport adds inspection/automatic pairing instrumentation, not a
replacement renderer. Only invented local data appears; no personal browser,
account, microphone, camera or speaker was used.

| Image | Actual fixture state |
|---|---|
| [01-typed-input.png](01-typed-input.png) | Trusted typed question before submission. |
| [02-scripted-answer.png](02-scripted-answer.png) | Protected answer card with an explicitly invented price. |
| [03-followup-input.png](03-followup-input.png) | Typed follow-up on the saved item. |
| [04-followup-answer.png](04-followup-answer.png) | Retained conversation with a scripted follow-up answer. |
| [05-protected-action-review.png](05-protected-action-review.png) | Real policy-generated review for Delete fixture. No approval or mutation. |
| [06-extension-consent.png](06-extension-consent.png) | Actual extension popup disclosure before Connect; not Chrome-native consent. |

Images were inspected at full resolution before publication. The loopback port
in the review is fixture-only, not a credential. No redaction or composition was
needed. These images do not prove live inference, native debugging consent,
store onboarding, physical-device performance or screen-reader compatibility.
