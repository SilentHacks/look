# Look source-beta release record — 2026-11-10

**Local preparation, not permission to publish or release sign-off.** No push, PR,
Store/catalogue submission, announcement or external message was made. The owner
reserves approval for each of those actions. Submission copy is
[local and unsubmitted](SUBMISSION_DRAFT.md).

## Scope and integration contract

Reviewed baseline: `feature/look-platform-contract`,
`3b850207165c327a5899e94eb188029721e4825a`. Release-doc work is on a separate
worktree/branch; it changes no runtime, extension implementation or test file.
The exact integrated release commit must be selected **after** extension setup
and test-cleanup changes land. The baseline is evidence identity, not a proposed
public install pin.

Extension integration owner must reconcile [CHROME_EXTENSION.md](CHROME_EXTENSION.md)
with the final setup command, installed source/Python paths, stopped upgrade,
relocation/reinstall and scoped uninstall. This record does not assume that the
current manual native-host command is the final onboarding. Test-cleanup owner
must reconcile the command matrix and stock-validator benchmark warning below.
Neither headless test totals nor another transport's proof close the extension's
headed ordinary-user gates. Preserve unrelated untracked `docs/research/`.

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
security certification. Repeat it on the **integrated intended publication ref**
and final artifacts; do not extend its result to unreviewed local refs, recordings,
model caches, profiles, research folders or a later demo video.

## Source, licences and packaging

The 13 intended release-document files were also scanned separately with
Gitleaks: exit 0, no findings. Their relative local Markdown targets resolved.
README onboarding is 175 lines; longer runtime disclosures moved to
`docs/REFERENCE.md`, not discarded.

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
| `hermes plugins validate CHECKOUT` | Exit 0; manifest/dependency declaration, isolated registration, tools/hooks/middleware alignment and safe scanner verdict passed. One private-core-import warning below. |
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

**Limits and warnings:** the copied host lacked its full native tool/install stamp
and printed `unknown-managed install` / out-of-sync notices for ffmpeg, node, npm,
ripgrep (and transient venv state). Existing dependency imports helped bootstrap
it. That limits a clean whole-Hermes-install claim; it did not prevent isolated
plugin PM admission or doctor registration. `plugins validate` also warned about
`benchmark/probe_sessions.py:264` importing `pm.environments.installs_root`
(catalogue rule 9). The test-cleanup owner should remove that private seam or
establish the supported replacement before a catalogue submission; this task did
not modify their harness.

The declared Python/Hermes ranges, a headless Chrome report or these install
checks are not a compatibility matrix. Runtime suite/browser acceptance results
elsewhere are historical attribution unless the integration owner reruns them.

## Exact remaining release gates

### Before a public source-beta announcement

1. Integrate setup/test work; select and review one immutable commit. Reconcile
   README/extension instructions and rerun the affected command/contract checks.
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

- Catalogue: resolve the private-import warning, check current organizer/catalogue
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

## Cost and actions

Product/provider inference, account/Store purchases and external communications:
**$0 / none**. Public package/tool downloads occurred. No push, PR, publication,
history rewrite, personal Chrome/device access or credential-store access.
Assistant/session billing is not exposed. One harness semantic-search attempt was
rejected before producing results (0 reported tokens/$0); no model inference was
used to test the product. Local audit reports use redaction and metadata only.
