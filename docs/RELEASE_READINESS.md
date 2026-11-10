# Look source-beta release record — 2026-11-10

**Local preparation, not permission to publish or release sign-off.** No push, PR,
Store/catalogue submission, announcement or external message was made. The owner
reserves approval for each of those actions. Submission copy is
[local and unsubmitted](SUBMISSION_DRAFT.md).

## Scope and integration contract

Starting point: `feature/look-platform-contract`,
`3b850207165c327a5899e94eb188029721e4825a`. All approved tracks are integrated,
in this order: cleanup `c7bbac3`, validator `930f98a`, release docs `be0b950`,
extension setup `070f26d`, cross-profile ownership correction `c4ddab4`.
The README conflict retained the shorter release guide and restored the
prompt-only probe prerequisites. Setup now uses `/look setup extension`, fixed
staged source files and the current Hermes Python; no manual ID/path is needed.

Integration also isolates both optional live probes' account-wide runtime in
their temporary `HOME`, removes private dependency-state sharing from the UI
probe, and updates the stock-startup fake for the current `on_error` callback.
No product policy was weakened to make a test pass. Untracked `docs/research/`
is excluded from commits and source archives. The final local commit/digest is
recorded in the integration handoff, not advertised as a published release pin.
Headed ordinary-user/device/provider acceptance remains open.

## Publication/history audit

Scope: baseline HEAD ancestry only, **not every local branch/checkpoint ref**.
Normal explicit branch publication includes its ancestors, including deleted
files. Do not use `push --mirror`, `--all` or an indiscriminate tag push.

- 114 reachable commits; 1,541 objects; 969 distinct blobs, 23,070,515 bytes.
  Current baseline tree: 172 files. No NUL-containing binary blob in that ancestry;
  no tracked model weights, audio/video, state DB, compiled Python/native library
  or archive in the baseline tree. This is an inventory, not malware certification.
- [Gitleaks 8.30.1](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1),
  default rules, full redaction, ran locally against the pinned Git history and
  separately **every distinct reachable blob**, including merge-only content.
  Git mode reported 105 diff-bearing commits; object enumeration covered all 114.
  The downloaded mac-arm64 archive was 7,897,593 bytes, SHA-256
  `b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5`,
  matching the official GitHub asset digest.
- Both scans exited 1 with the same single finding: `generic-api-key`,
  `tests/extension_chrome.py:36`, blob
  `3297570f9f09eb5b9c24b1b1334265740e31d6ca`. The source labels it a fixture
  extension identity; OpenSSL successfully parsed its DER as a **public key**.
  It is not a private credential or production/Store identity. No blanket
  scanner suppression was added. Reports contain redaction, never secret values.
- Additional local pattern screening covered private-key/provider-token signatures,
  credential assignments/URLs, email addresses and home paths; commit-message
  credential signature counts were zero. Credential-like matches were synthetic
  test sentinels/userinfo fixtures. All 466 content email matches used test/reserved
  domains. This does not establish absence of arbitrary/custom-format secrets.
- **Publication metadata decision remains:** two distinct Git identities occur;
  one uses a personal author/committer address, the other a GitHub noreply address.
  Values are deliberately not copied into this report. Owner approval of intended
  public metadata is required. No history rewrite was attempted or authorized.
- **Historical privacy residual:** 30 distinct blobs contain developer home paths,
  including retired raw action-result JSON, old README/plan/runner versions, and
  synthetic leak fixtures. Current release commands were made portable, not
  history-scrubbed. Removed phase0/phase1/action raw results remain reachable;
  source scans found no credential signatures there. They contain historical
  prompts/answers/tool traces and merit explicit owner publication review, not a
  claim that deleting current files erased them.

This is a scoped credential/artifact review, not comprehensive privacy, legal or
security certification. The numbers above describe the baseline, not the final
integrated ancestry. Integration checks changed paths, source packaging and stock
scanner findings; a full historical rescan of the intended publication ref remains
an owner publication gate. Do not extend old scans to unreviewed refs or recordings.

## Source, licences and packaging

The original 13 release-document files were scanned separately with Gitleaks:
exit 0, no findings. Their relative local Markdown targets resolved. Longer
runtime disclosures moved to `docs/REFERENCE.md`, not discarded.

- Root source licence: MIT, copyright SilentHacks. Vendored
  `asr/parakeet_coreml.py` has silicon-asr provenance/MIT text in
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Retain both files in archives.
- Runtime assets are external and explicitly prepared, pinned/hashed by
  `assets.json` and webcam code. Notices distinguish NVIDIA v2/FluidInference/MLX
  CC-BY-4.0 weights, Apache-2.0 MediaPipe/Phonon, and MIT runtimes. No v3 licence
  resolution, training-data licence, NVIDIA endorsement or catalogue approval
  is inferred. System fonts are referenced, not bundled.
- This deliverable is a **pinned Hermes Git source plugin**, not a tested Python
  wheel/sdist, native-app installer, signed bundle or Store extension. Runtime
  HTML/JS, manifest, assets manifest and skill must accompany Python sources.
  Models, datasets and browser binaries are not to be bundled casually.
- Resolved direct metadata in the isolated Apple Silicon install:

  | Distribution | Version | Published licence metadata |
  |---|---|---|
  | websockets | 15.0.1 | BSD-3-Clause |
  | faster-whisper | 1.2.1 | MIT |
  | sounddevice | 0.5.6 | MIT |
  | numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
  | parakeet-mlx | 0.7.0 | Apache-2.0 |
  | pyobjc-framework-CoreML | 13.0 | MIT |
  | ptts | 0.6.0 | MIT OR Apache-2.0 |
  | huggingface_hub | 1.33.0 | Apache-2.0 |

These are observed resolutions, not new dependency pins. The complete transitive
source/wheel licence graph was not legally audited. Source-only distribution does
not clear bundled dependencies or generated audio for republication. Do not use
Apple `say` fallback audio in a submission without establishing publication rights.

## Installation actually exercised

Host source: unmodified stock Hermes
`2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19` (`0.0.0` package metadata).
Python 3.14.9, Darwin 27.0.0 arm64. A Git archive of the host ran from a disposable
private directory; `HOME`, `HERMES_HOME`, XDG roots, temporary directory and uv cache
were isolated. Environment was allowlisted: no profile, `.env`, provider credentials,
user config, Chrome profile or model cache was copied. Initial CLI imports used
an existing prepared **dependency site only**, read-only; actual plugin dependency
resolution/preparation ran through stock PM into the temporary home. This is not
an independently bootstrapped Hermes application installer from a blank machine.

| Check | Observed result |
|---|---|
| `hermes plugins validate CHECKOUT` | Baseline exit 0 with the historical private-core warning below; integrated validation exits 0, safe, with no warnings. |
| `hermes plugins install file://CHECKOUT --ref BASELINE_SHA --enable`, no TTY | Exit 0 but **installed disabled**, explicitly skipped dependency preparation. Exact committed revision installed; no untracked files imported. |
| `hermes plugins enable hermes-gaze` | Exit 0; stock PM resolved 377 packages and installed the selected dependency environment. Explicit enable did not ask a second dependency question at this stock revision. |
| Fresh-process list and doctor | Enabled `git pinned@3b850207`, version 0.1.0; installed Git HEAD exactly matched baseline; doctor exit 0, import/registration passed, 14 tools and 7 hooks. |
| `hermes plugins remove hermes-gaze` | Exit 0; temporary installed plugin directory absent afterward. No real installation was touched. |
| Interactive pinned reinstall; answer **n** to dependency prompt | Exit 0; `dependency install declined`; source retained, enabled list empty. |
| Later explicit enable and fresh-process compact list | Exit 0; enabled at the same pin, no second dependency prompt. |

No dangerous finding was bypassed; no fake replacement package, patched host
source, dummy turn, provider inference, browser launch, microphone/camera/speaker
or real account was used by these installation checks. No model files were
created in the isolated XDG cache. Package/tool downloads are **not** a proof of
fully offline installation.

**Limits and warnings:** the copied host lacks its full native tool/install stamp
and prints `unknown-managed install` / out-of-sync notices for ffmpeg, node, npm
and ripgrep. Existing prepared dependency imports bootstrap the CLI, read-only.
That limits a fresh whole-Hermes-install claim, not isolated plugin PM admission.
The baseline warning about `pm.environments.installs_root` in the prompt probe is
fixed; integrated stock validation reports **zero warnings**.

### Integrated verification — 2026-11-10

- Full deterministic suite run once: **349 tests, PASS**, 16.343 seconds.
- Node: **27 collector/parser/action contracts PASS**, worker ownership races
  PASS, webcam feature checks PASS; syntax checks for extension worker/popup and
  browser overlay/panel/markdown PASS.
- Stock validator: manifest, 8 Python requirements, isolated capability probe,
  declared tools/hooks/middleware and scanner all PASS; safe, no warnings.
- Stock lifecycle acceptance initially found a stale test fake missing `on_error`.
  After correcting only that fake, the specific stock-startup probe passed:
  cold lazy first question without dummy turn, exact receipt/hook matching,
  permission refusal, constructor failure, lost acknowledgement, Stop/unknown
  ownership, reset and retirement paths. Inference/browser are local fakes.
- Both optional live probes passed a disposable-fixture handoff check: warmed
  Chrome profile equals the backend's temporary account-scoped profile, and no
  host dependency-state link is created. No live provider/device probe was run.
- Real stock local-pin install, enabled discovery, doctor (14 tools/7 hooks) and
  repeated **actual shell** `hermes look setup-extension` passed in a private home.
  The native registration uses only the fixed extension origin. Final update,
  staged-host relocation/status and scoped-removal receipts accompany the handoff.
- **Browser acceptance blocker:** available bundled Chrome for Testing
  **145.0.7632.6** passed 11 setup/pairing/opaque-frame checks, then the test-only
  `Input.dispatchMouseEvent` (`mouseMoved`) lost its reply; the generation revoked
  with “Chrome reply lost; outcome unknown. Do not replay the action.”
  Trusted-input/answer checks and the other three scenarios were not reached.
  No retry, timeout increase, browser-policy bypass or runtime workaround was added.
  This is not a passing final browser run or proof of a product-only root cause.
  Earlier setup-track **157.0.8103.50 / 66-check** proof is historical attribution,
  not a result on this integrated candidate. Resolve/retest in a supported isolated
  browser before treating the extension lane as accepted or recording a success claim.

The declared Python/Hermes ranges and these checks are not a compatibility matrix.
No personal browser, physical device, provider inference or installed Hermes
mutation was used. The user trial below is a procedure, not completed acceptance.

## Exact remaining release gates

### Before a public source-beta announcement

1. Review the final immutable local commit and the browser blocker above. Clear
   applicable browser acceptance before claiming release/recording success.
2. Owner reviews personal Git metadata, historical raw traces/developer paths,
   final source archive, intended refs and any demo media; approve the precise
   publication scope. No automatic rewrite or broad ref publication.
3. Verify a working private vulnerability-reporting channel; the local security
   policy does not configure GitHub reporting.
4. User runs supported **headed** Chrome setup → pair/consent → first typed answer
   → follow-up → safe local action → protected mouse-only approval → focus/tab/
   navigation loss → Stop/reconnect. Verify extension install/update/disable,
   native-host relocation/uninstall and ordinary profile coexistence on the final
   flow. No real purchase/send/delete; use a local fixture.
5. If voice/eyes/read-aloud are demonstrated, user verifies native permissions,
   real mic first word/deadline/cancellation, audible stop/no overlap and personal
   nine-point calibration/check. Report misses, not a population accuracy claim.
   Obtain a first answer from the user's configured provider separately; no such
   provider/device proof was obtained here. Native Allow/deny/revoke needs its own
   trial if that connection lane is advertised as accepted.
6. Owner approves publication/announcement. Once authorized and reachable, repeat
   temporary-home installation from the **public exact SHA**, including decline,
   recovery, update and removal. Publish that exact command, not a moving branch,
   invented catalogue install or this local baseline pin.

### Additional distribution/submission gates

- Catalogue: the private-import warning is fixed; check current organizer/catalogue
  rules and required fields, repeat download/network disclosures, and obtain the
  maintainer ruling for converter-published CoreML/MLX assets. No catalogue entry
  or PR was created by this work.
- Consumer extension: stable owner-controlled identity, packaged native-host
  install/update/uninstall proof, accurate public privacy disclosure, Store
  account/fee/review and explicit owner authorization. Unpacked development is
  not consumer Store distribution; Store approval is not necessary to share a
  correctly labelled source beta.
- Submission: user records actual behavior using non-sensitive pages, checks
  organizer deadline/form/video/tag requirements, media/audio rights and final
  link accessibility, then explicitly approves posting/submitting. The historical
  playbook is not evidence of current rules or promised performance.

## User trial and recording procedure

User-operated only; use fictional data and a configured provider you authorize.
Keep pairing tickets, profiles, account names and terminal history out of recordings.

1. Install the final local Git SHA using the README's pinned command, check
   `hermes plugins list --plain --no-bundled`, merge the injection/in-process
   configuration, stop the gateway and restart **every** Hermes process.
2. Run `/look setup extension`. In the intended standard Chrome profile,
   `chrome://extensions` → Developer mode → Load unpacked →
   `~/Library/Application Support/Look/extension/unpacked`; review broad debugger
   permissions. Setup is not browser consent or Store installation.
3. From this checkout, serve only local fixtures:
   `python3 -m http.server 8765 --bind 127.0.0.1 --directory benchmark`.
   Open `http://127.0.0.1:8765/benchmark_page.html`.
   In the intended new Hermes conversation, `/look start --extension`; open Look
   on that tab, paste the fresh 120-second ticket, **Connect this tab**.
4. Point at a table cell, **Right Option**, type “What does this cell measure?”
   Check the private streamed answer refers to that cell. Ask a typed follow-up;
   verify recall with **Q**, selection/scroll and **Esc**.
5. In another terminal, run
   `python3 -m http.server 8766 --bind 127.0.0.1 --directory tests/browser_actions`.
   Open `http://127.0.0.1:8766/browser_actions_page.html?kind=mail`;
   choose **Use on this tab**. Ask: “Prepare a local fixture message to
   trial@example.com, subject Look trial, body This is fictional. Do not send.”
   Inspect the draft. Ask for Send review: Enter/Space must not approve; use
   **Cancel** first, then request fresh review and consciously primary-mouse approve.
   Only “Message sent locally.” should change; no real recipient/network send.
6. During another local task switch tabs/navigate: no input may target the new
   foreground document, and old approval must expire. `/look stop` must remove
   Look/stop capture and output while leaving tabs open. Pair with a fresh ticket.
7. For voice only after explicit `/look setup`: grant the launching app's macOS
   microphone permission, hold Space, **wait for Listening**, speak and release.
   Test focus-loss cancellation and the 30-second cap with the five-second warning.
   For read-aloud, explicitly prepare speech assets, verify audible Stop/Esc and
   no overlap before capture. For eyes, explicitly prepare/start calibration and
   pass the personal nine-point check; report misses. Do not claim these from mocks.
8. Stop, restart Hermes after updating the plugin, rerun setup, **Reload** Look and
   pair afresh. Test Chrome disable/remove and scoped host uninstall before plugin
   removal. Close both local HTTP servers with Ctrl-C. Native-consent Allow/deny/revoke
   is a separate trial if that lane is shown.

Record only accepted behavior, using the [85-second plan](SUBMISSION_DRAFT.md#suggested-85-second-recording-plan).
Do not show eye/voice performance that failed; keep the source-beta label and
question/page-sharing disclosure. Owner review/publication/media approval remains required.


## Cost and actions

Product/provider inference, account/Store purchases and external communications:
**$0 / none**. Public package/tool downloads occurred. No push, PR, publication,
history rewrite, personal Chrome/device access or credential-store access.
Assistant/session billing is not exposed; harness code-location searches are
separate from product inference and can incur tool charges. No model inference
was used to test the product. Local audit reports use redaction and metadata only.
