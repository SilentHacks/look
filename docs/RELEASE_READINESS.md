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
  `audio/asr/parakeet_coreml.py` has silicon-asr provenance/MIT text in
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md). Retain both files in archives.
- Runtime assets are external and explicitly prepared, pinned/hashed by
  `audio/assets.json` and webcam code. Notices distinguish NVIDIA v2/FluidInference/MLX
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

### Public source installation

On 2026-11-10, GitHub's anonymous repository API reported
[`SilentHacks/look`](https://github.com/SilentHacks/look) as public.
The old HTTPS repository address returns HTTP 301 to that URL.
The configured SSH origin was left unchanged.

Anonymous `git ls-remote` reported public `master` at
[`10ff13d7480e36a884084091be435a739bc1e722`](https://github.com/SilentHacks/look/commit/10ff13d7480e36a884084091be435a739bc1e722).
The README uses this full SHA with the official stock Hermes
[Git source installer](https://github.com/NousResearch/hermes-agent/blob/2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19/hermes_cli/plugins_cmd_install.py),
not a catalogue name, release tag or unpublished local commit.

The same stock host revision listed below was archived into a temporary directory.
`HOME`, `HERMES_HOME`, XDG roots, temporary directory and uv cache were isolated.
An allowlisted environment excluded credentials and personal configuration.
Existing prepared Python dependencies were used only for bootstrap imports.
Stock PM prepared the isolated runtime and plugin dependencies.

| Check | Observed result |
|---|---|
| Public HTTPS install with the README's exact `--ref` and `--enable`, no TTY | Exit 0, installed disabled because dependency consent was skipped |
| `hermes plugins enable hermes-gaze` | Exit 0, dependencies prepared and plugin enabled |
| Fresh-process list and installed Git HEAD | Enabled `git pinned@10ff13d7`, HEAD exactly matched the full public pin |
| Installed plugin doctor with `--ci` | Exit 0, discovery/import/registration passed, 14 tools and 7 hooks |
| Both README `hermes config set` commands | Exit 0, saved `in_process` and Boolean input permission in the isolated profile |

No host source was patched. No provider call, browser, device, personal profile
or model download was used. No dangerous scanner finding was bypassed.
The archived host printed the same missing native-tool/install-stamp warnings
described below. This verifies plugin installation, not a fresh Hermes application
install or a working browser/provider/device session.

**Pin limit:** this public commit predates the local card-sizing, exact cancellation
and navigation changes. Publish the integrated fixes separately, then anonymously
fetch and repeat installation/doctor before updating the README pin.
A local commit, including this documentation change, is not a public install pin.

### Earlier local-source installation

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
- **Pre-no-paste extension browser acceptance: 66 checks PASS** on the integrated
  `0ef0c2dd` runtime with official mac-arm64 Chrome for Testing **157.0.8103.50**,
  the [current stable channel](https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json)
  at verification. All four disposable-profile scenarios completed: private
  trusted input/answer, lost reply, native-host loss and worker reload. The saved
  screenshot shows the private answer; website text/selection/key leakage checks,
  focus/route/document refusal, guarded new tabs and Stop passed.
- The earlier **145.0.7632.6** blocker is isolated to that build's **headless
  `chrome.debugger` mouse driver**, not Look: a standalone extension with no Look
  scripts/native host reproduced the missing `mouseMoved` reply and absent mouse
  event while a concurrent `Runtime.evaluate` succeeded. The same isolated command
  replied in 10.4ms and delivered a trusted event on 157. The instrumented Look
  run on 145 revoked at its unchanged three-second deadline. No replay, timeout
  increase, ownership relaxation or product workaround was added.
- **145 is not browser-accepted by this work.** Its headed/physical behavior is
  unverified; the headless result does not establish that all Chrome 145 builds
  or ordinary user input are broken. Use current stable Chrome for the user trial.
  The native-consent lane's 145 protocol floor is separate from extension acceptance.
- Relevant follow-up regressions: **56 tests PASS** across extension, native
  consent, first-run and companion ownership; Node worker guards PASS.
- No-paste pairing was then verified separately: **100 headless checks PASS**
  across eight disposable-profile scenarios on CfT **157.0.8103.50**, plus
  **63 Python tests** and the Node worker ownership-race harness. This supersedes
  the earlier four-scenario pairing evidence, not the headed/device/provider gates.
  See [extension verification](CHROME_EXTENSION.md#verification-and-remaining-gates).
- Combined icon/no-paste integration: **64 Python tests PASS** across extension,
  native consent, first-run and companion ownership; Node worker ownership guards
  and extension worker/popup syntax checks PASS. Setup refresh/removal checks
  include every manifest icon asset. The long browser suite was not repeated.
- The combined source archive passed the stock validator with **zero warnings**
  and a **safe** scan. The stock-startup lifecycle probe also passed against the
  unmodified host revision above, using disposable homes and fake inference/browser.

### Urgent card/cancellation/navigation integration

On `master`, retained navigation commit `9e833bb`, cherry-picked card commit
`31a776d` as `33053c5` and cancellation commit `913e856` as `c6857c9`.
Only the changelog conflicted; both entries were retained. Overlay/panel merged
without conflicts, retaining measured card growth and request-specific Stop.

- Full unit discovery ran once: **366 tests PASS**, 15.665 seconds.
- `node --check browser/overlay.js`, `node --check browser/panel.js` and
  `node tests/extension_worker.cjs` passed. The worker harness covers classified
  lifecycle reads, terminal arbitrary evaluations and missing replies, with no replay.
- Private `probe_card_growth.py`, `probe_first_answer.py` and
  `probe_cancel_request.py` passed. Growth at 1440×900 and 800×700 preserves
  opening/manual scroll and coarse geometry. Cold readiness, late font metrics,
  selection/focus, nested code/table scrolling, follow-up/Retry/recall passed.
  Trusted active/queued Stop, synthetic Stop refusal, partial retention, paused
  FIFO/resume, website text isolation and the SDK cancellation limit passed.
- Extended `tests/stock_startup.py` passed against the unchanged disposable stock
  host with real native auth, admission and receipt APIs, scripted inference and
  synthetic browser attachment. Running cancellation produces a terminal
  **`interrupted`** receipt; already-admitted queued cancellation produces
  **`cancelled`**. Look retains partial text, cancels an exact queued follow-up,
  pauses the remaining FIFO and resumes it without replay.
  Initial fixture failures exposed a finish-before-interrupt race and the wrong
  expected receipt name; the fixture now waits for stock's actual interrupt.
- **Before classified recovery, navigation browser acceptance failed.** CfT
  157.0.8103.50 reached a
  concurrent `Runtime.evaluate` rejection, `Cannot find context with specified id`,
  during redirect/rearm and ended the generation. The first run rearmed one
  redirect and answered its question before failing on the next; diagnostic
  instrumentation then captured the terminal method/reason on the first redirect.
  This is outside the intentionally narrow frame-tree/fixed-lease read recovery.
  Arbitrary evaluation, missing replies and mutation failures remain terminal.
  Do not claim seamless navigation or an Amazon-specific fix; use the explicit
  reconnect procedure below. The test-only worker records method/reason, not
  expressions or ownership data.
- Separate focused lost-reply/host-loss browser scenarios passed **29 checks**:
  unknown mutation executes once, no reconnect/replay, input/output/task/approval
  teardown, synthetic/keyboard approval rejection and page-preserving fail-open.

Evidence: `/tmp/look-urgent-integrated/{growth,first,cancel,navigation-diagnostic}`.
The old temporary CfT path was missing; a fresh official archive was downloaded
under that evidence root, SHA256
`aceb0578a1cc3631358b164dbbef04bf8936f96c690fb78c3ac25b7655e795e8`.
No personal Chrome/profile, microphone/camera/output device, account or product
provider was used. No live gateway, staged extension or native registration was
updated. Actual headed toolbar consent, physical speech and configured-provider
recording remain user-operated checks, not established by these fixtures.

### Classified navigation recovery

Baseline `56e38d2a85c5f6c11d687cdce7e254402034fa4d` reproduced the second-redirect
terminal evaluation failure in disposable CfT 157.0.8103.50. The replacement
uses trusted Python evaluation authority, not expression matching or blanket retry.
The [caller audit](NAVIGATION_RECOVERY.md) records read, presentation and mutation
boundaries, wrapped protocol errors, pinned rearm and unchanged terminal failures.

- Targeted Python transport/ownership/action/first-run checks: **99 tests PASS**.
- `node --check extension/worker.js` and `node tests/extension_worker.cjs`: PASS.
- Local browser navigation, navigation-mutation, lost-reply and host-loss:
  **82 checks PASS**. Five redirects create fresh documents in one generation;
  six typed questions receive scripted answers. Read side effects, stale action
  owners and background private rendering are refused. In-flight mutation and
  lost-reply paths execute one POST, terminate and never reconnect/replay.
- Additional in-flight-navigation, debugger-detach and surface checks:
  **53 checks PASS** (navigation-mutation overlaps the preceding run). The server
  observes the destination document after the one POST. Actual debugger detach
  tears down capture/output/task/approval. Hostile focus suppression, private
  answer/input/selection isolation, route-and-back refusal and guarded new-tab
  ownership transfer pass. Evidence: `/tmp/look-navigation-repair/boundaries/results.json`.
- Initial post-change fixture clicks raced unmeasured private-frame geometry
  (`y=0` before the size message). The fixture now waits for nonzero measured
  card/frame geometry before using trusted Chrome clicks; no product delay,
  focus override or ownership relaxation was added.

Evidence: `/tmp/look-navigation-repair/after/results.json`; baseline failure and
intermediate fixture diagnostics are recorded in the implementation handoff.
No personal browser/profile, account, physical device, live provider or Hermes
host modification was used. Stock-facing first-run contracts pass; the full
stock-startup acceptance from the preceding integration was not rerun.

### Master integration of navigation repair

Integrated `ef53a3741430bc15ccb44a44d2224ba6dab4cd3b` onto
`5497fe5025e25a8cc7d79dcf483fbaa702cb2281` as `2d1cbc7`, without conflicts.
Public `SilentHacks/look` install instructions and their verified older pin,
card sizing, exact cancellation and untracked `docs/research/` were preserved.

- Full Python discovery ran once: **365 tests PASS**, 17.788 seconds. The repair
  removes one obsolete forwarding-only test; this is not a narrowed suite.
- Node syntax checks passed for extension worker/popup and browser
  overlay/panel/markdown. Worker ownership/classification harness and all
  **27** collector/parser/action contracts passed.
- Targeted disposable CfT **157.0.8103.50** navigation, navigation-mutation,
  lost-reply and host-loss scenarios passed **83 checks**. Five redirects and
  six scripted answers retain one generation; stale owners, side-effecting reads
  and background rendering are refused. In-flight/lost-reply mutations execute
  once, terminate and never replay. Evidence:
  `/tmp/look-navigation-master-integration/results.json`.
- Focused stock startup passed against the unchanged disposable stock host,
  using isolated state, prepared dependency imports and fake inference/browser.
  Cold startup, exact cancellation/receipts, lost-ACK reconciliation, owner
  retention and auth/reset/retirement guards passed. The initial run exposed a
  fixture barrier left set by the preceding cancellation scenario; resetting it
  before the next held request fixes the fixture. No product guard changed.

No installed Hermes, personal profile, physical device, real provider, live
gateway or staged extension was changed; no push/PR or Claude was used.
Use the stopped update procedure in [the extension guide](CHROME_EXTENSION.md#update-move-or-remove):
restart all Hermes processes on the updated plugin, open a new conversation,
rerun `/look setup extension`, Reload Look in `chrome://extensions`, then
`/look start --extension` and **Connect this tab**. Cancel unwanted processing
before `/look stop`; disconnect alone does not cancel an admitted model turn.
Real signed-in Amazon navigation/recording remains unverified. Concurrent real
mutations can still intentionally end a generation; inspect unknown outcomes
before another action and reconnect explicitly.



### Popup and tracker integration — 2026-11-10

Master retained tracker lifetime commit `f4669ef` and cherry-picked popup commit
`6dd0e2c` as `2b18bb3`. The only cherry-pick conflict was additive changelog
content; both entries remain. Untracked `docs/research/` was left untouched.
- Full project suite passed: `.venv/bin/python -m unittest discover -s tests -t .`
  — **370 tests**, **15.161 seconds**, including the native-host shutdown regression.
  The first combined run exposed four startup subtest failures: the tracker
  fixture mocked page attachment instead of an approved browser socket. The
  fixture now models socket presence/loss; no product lifetime guard was weakened.

- Node popup/worker harnesses and syntax checks passed:
  `node tests/extension_popup.cjs`, `node tests/extension_worker.cjs`,
  `node --check extension/popup.js`, `node --check extension/worker.js`.
- Headed CfT **157.0.8103.50** passed **20 checks** with a disposable profile:
  `.venv/bin/python tests/extension_setup_chrome.py --chrome '/tmp/look-urgent-integrated/browser/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing' --headed --out /tmp/look-integrated-popup-20261110`.
  The real focused toolbar popup reproduced its unfocused normal owner, then
  connected through the native host. Two windows, restricted/incognito exclusion,
  expiry, synthetic-click rejection and stopped restaging/reload passed.
  Popup owner focus is used only for connection selection; action dispatch still
  uses strict ordinary foreground guards.
- Fake-camera handoff passed **7 checks**:
  `.venv/bin/python tests/webcam_handoff_chrome.py --out /tmp/look-integrated-tracker-20261110`.
  Real fake-video inference survives missing browsing tabs, explicit fallback and
  return without replacing the tracker process; Use cursor closes only the tracker.
- A private subprocess/socket regression reproduced the old native-host shutdown
  abort (**SIGABRT**, return code `-6`) when the peer closes but Chrome's stdin
  stays open. This is actionable teardown failure, not connection authorization
  failure. Reading raw stdin avoids the buffered-reader finalization lock without
  a join delay or changes to framing, consent, foreground guards or terminal loss.

`~/.hermes/plugins/hermes-gaze` was verified as a symlink to
`/Users/Abid/Projects/hermes-gaze`. Running Hermes still needs a restart; staged
extension files still need setup and Chrome Reload. Follow the
[stopped update sequence](CHROME_EXTENSION.md#update-move-or-remove), including
gateway restart and page reload. Calibration remains intact.

The README's public pin remains `10ff13d7480e36a884084091be435a739bc1e722`;
it does not include these local fixes. No push or public-pin refresh was performed.
No personal browser/profile, accounts, real camera/microphone/speakers, provider
or Hermes host changes were used. Physical toolbar clicks, signed-in behavior,
real speech/calibration and provider answers remain user-operated acceptance.
The headed probe opens the actual popup through Chrome's action API and supplies
trusted CDP mouse input, not a physical toolbar gesture.

The declared Python/Hermes ranges and these checks are not a compatibility matrix.
No personal browser, physical device, provider inference or installed Hermes
mutation was used. The user trial below is a procedure, not completed acceptance.

## Exact remaining release gates

### Before a public source-beta announcement

1. Review the final immutable local commit and the version-specific browser
   evidence above. Headless extension acceptance is not headed/device acceptance.
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
Keep profiles, account names and terminal history out of recordings.

1. Install the public Git SHA using the [README's pinned command](../README.md#install-look),
   check `hermes plugins list --plain --no-bundled`, and set the injection/in-process
   configuration. In the old conversation, use **Stop request** for any request
   you want cancelled, wait for its outcome, then `/look stop`. Disconnect alone
   does not cancel admitted processing.
   Quit Hermes clients. From an external terminal in the same Hermes environment
   and profile, run:

   ```sh
   hermes gateway status
   hermes gateway restart
   hermes gateway status
   ```

   If using a named profile, prefix each command with `hermes -p NAME` instead of
   `hermes`. Do not use `--all` or force past a live-session refusal. A foreground
   replacement may keep the terminal occupied; leave it running. Reopen Hermes
   and start a new conversation so both plugin code and frozen guidance reload.
   Restart any other Hermes process using Look before staging the shared helper.
2. Run `/look setup extension` in that new conversation. In the intended standard
   Chrome profile, open `chrome://extensions` and **Reload** an existing Look
   installation. On first installation, enable Developer mode → Load unpacked →
   `~/Library/Application Support/Look/extension/unpacked`; review broad debugger
   permissions. Setup does not reload Chrome's worker. Reload the intended web
   page too, then connect afresh; setup is not browser consent or Store installation.
3. From this checkout, serve only local fixtures:
   `python3 -m http.server 8765 --bind 127.0.0.1 --directory benchmark`.
   Open `http://127.0.0.1:8765/benchmark_page.html`.
   In the intended new Hermes conversation, `/look start --extension`; open Look
   on that tab and choose **Connect this tab** within 120 seconds.
4. Point at a table cell, **Right Option**, type “What does this cell measure?”
   Check the private streamed answer refers to that cell. Ask a typed follow-up;
   verify recall with **Q**, selection/scroll and **Esc**.
   Ask for a longer comparison: the first words must stay at the top while the
   card grows within the viewport; scrolling up must not jump as text arrives.
   Queue two follow-ups, click **Stop request** on one, then on the active request.
   Keep the partial answer; remaining work must wait for **Continue with the rest**.
   Canonical local stock Hermes cancels the exact admission; other frontends
   explicitly require stopping processing in Hermes. An in-flight action can finish.
   Navigate to another local page and ask again. Classified frame/context read
   failures may rearm on the same connection. A terminal disconnect instead needs
   `/look stop`, `/look start --extension`, then reopen Look → **Connect this tab**.
   An unknown mutation outcome requires inspecting the page, never replaying it.
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
   Look/stop capture and output while leaving tabs open. Start a fresh connection.
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
