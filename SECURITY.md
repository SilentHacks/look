# Security and privacy

Look is a technical source beta, not a security-certified browser or application
sandbox. The supported trial lane and current gates are in the
[README](README.md) and [release record](docs/RELEASE_READINESS.md).

## Report privately

Do not post credentials, active pairing tickets, account pages, transcripts,
recordings, calibration or full Hermes logs in a public issue.
Use the repository's **Security → Report a vulnerability** flow if it is enabled.
A working private reporting channel has **not been verified for this release**.
The maintainer must enable/verify one before public announcement. If it is absent,
request a private reporting channel without publishing exploit details. No response
time or security-update service is promised by this beta.

A useful sanitized report includes the exact Look and stock Hermes commits,
Python/OS/Chrome versions, connection lane, expected/observed behavior and minimal
local reproduction. Replace private text/URLs with fixtures. Give file/line or
commit/blob IDs, not secret values. Never test on somebody else's account, device
or browser. Do not execute Send/Buy/Delete to demonstrate a report.

If a real credential is exposed, revoke/rotate it with its owner before sharing
further. Removing a file does not remove Git history or provider/host retention.
History cleanup requires a separately approved plan.

## Boundaries to preserve

- **Debugger authority is broad.** Existing-Chrome native consent and the extension
  can inspect/mutate authorized pages. Dedicated Chrome also exposes local CDP.
  Do not forward debugger ports or connect generic model browser/code tools to
  Look's endpoint. Same-user/root programs and authorized debuggers are outside
  the protected website boundary.
- **Websites and answers are untrusted.** Private words and input live in opaque,
  script-disabled frames. Closed shadow DOM alone is not a privacy boundary.
  Page/answer text never grants a task or approves an action. Website denial of
  service (hiding/removing the host) remains possible.
- **Identity is not a selector.** Actions retain captured tab/document/route/epoch
  ownership. Consequential/ambiguous controls need a content-bound, single-use
  primary mouse approval. Detached identities fail. Missing mutation replies are
  unknown outcomes, never safe automatic retries. Typing/GET navigation can still
  have effects on unusual sites.
- **Stop has limits.** It cancels local capture/output/tasks/approvals, not an
  already admitted Hermes turn or an action that already executed. It is not data
  erasure. Transport loss releases intercepted input through a bounded lease.
- **Native devices are explicit.** No website microphone. Input opens only while
  talking. The separate camera is opt-in. Live eye features/images stay local.
  Saved calibration is sensitive. No real-device proof follows from fakes.
- **Local does not mean no retention.** Questions/page evidence reach the configured
  Hermes provider and can remain in Hermes history. Optional TypeSafe highlighting
  has its own disclosure. Failed audio stays in memory for retry. MLX's temporary
  WAV can survive a crash/deletion failure. Development recording is separate and
  must never be enabled silently.
- **Downloads and removal are separate.** Explicit setup verifies pinned assets.
  Dependency preparation can fetch packages/native wheels. Plugin removal does not
  erase shared model caches, calibration, browser profiles or host/provider history.

See [technical disclosures and data locations](docs/REFERENCE.md) and
[third-party notices](THIRD_PARTY_NOTICES.md). Never weaken these boundaries to
make a demo, integration test or catalog scan pass.
