# Catalog readiness

Preparation record from 2026-11-10. The sections below retain the original
pre-publication findings; the publication update supersedes their authorization,
public-pin and screenshot status. Catalog acceptance remains a maintainer decision.

## Publication update — 2026-11-10

The owner authorized publication and an upstream catalog PR. Public source
`6ff0a462d29adb8056e144d677b5e839e541409e` was pushed by a normal fast-forward
and anonymously cloned over HTTPS at that exact commit. It includes the NVIDIA
v3 default and [six labelled fixture UI images](catalog/screenshots/README.md).
Their capture source predates v3 integration; they are not v3 setup screenshots.
No live inference, native Chrome consent or physical-device proof is implied.

The README install command and local catalog entry now reference that separately
published source. This later documentation commit cannot pin itself. The pinned
source's README installs its runtime-identical predecessor `a5a9715bbf7d23261b901098283f0f68ab70eb0b`.
The upstream submission changes only `plugin-catalog/hermes-gaze.yaml`.

Current official catalog requirements were read at Hermes
`95fc3e668fc1e13ad05d22a4f02fccc6a6d6ce02`; latest release was `v0.23.1`.
Against the anonymously fetched plugin, current stock validation passed with
safe scanner status and no warnings; declared capability lists match
14 tools, 7 hooks and 2 middleware entries. Official schema, canonical-path
confinement, self-updater and committed-payload gates passed. The 85 focused
v3/download/voice/first-run/session/inbox tests passed using synthetic fixtures
and an isolated HOME, without devices or provider inference.

NVIDIA's current release API digest/size and peeled v0.3.0 source tag match the
committed runtime manifest. This is not a local rebuild or attestation verification.
Retained converter-owned CoreML/MLX v2 distributions still require the rule 17
interpretation described below; the PR must ask explicitly, not claim approval.
Upstream CI, maintainer review and merge are not established by local checks.
Fresh current-stock `cmd_validate(..., install_deps=True)` also completed
dependency resolution/installation in isolated state and passed with a safe
scanner result and no warnings. This did not change installed Hermes.

## Fixed locally

- Public speech/model setup passes `token=False` centrally. The regression uses
  the real Hugging Face header builder with credential resolvers that fail if
  called, across all recognition/model/voice fixture repositories. No real
  credential, network download or model inference is involved.
- Manifest, README, reference and catalog draft require Hermes >=0.23.1. The
  strict audit verified native ticket/admission/receipt behavior on that release
  with fixture inference/browser attachment. Hermes 0.22.0 lacks that protocol.
- README and [PR draft](SUBMISSION_DRAFT.md) disclose action allow-all, network
  calls/costs, filesystem access, processes, background service, retention and
  asset provenance. The [entry draft](catalog/hermes-gaze.yaml) declares community
  tier, macOS beta limits and all 14 tools, 7 hooks and 2 middleware entries.

## Rule 17: source-policy finding

The [official catalog rules](https://github.com/NousResearch/hermes-agent/blob/3d4dd108cf52e26cf0d7fb218461e53623a8ec2d/plugin-catalog/README.md)
were checked alongside current upstream main. Rule 17 distinguishes committed
opaque payloads from setup downloads. The latter must come from the upstream
tool's official source, be checksum-pinned and disclosed. It does not explicitly
say whether a converter's own original distribution counts as that official
source. A passing committed-tree scan cannot answer that question. No maintainer
was contacted and no approval is claimed.

| Asset source | Evidence and decision |
|---|---|
| NVIDIA Parakeet v3 Q8 / NeMo-Speech.cpp | New native Apple Silicon default uses NVIDIA's pinned model and official runtime release. [Payload, licences and remaining policy questions](PARAKEET_V3.md). Explicit legacy choices and cached v2 fallbacks remain; the default change does not approve those sources. |
| FluidInference CoreML v2 | The [pinned model card](https://huggingface.co/FluidInference/parakeet-tdt-0.6b-v2-coreml/blob/ee09c569f73759e6d44c9bd16766f477b2b36d39/README.md) credits FluidInference's conversion. [FluidAudio](https://github.com/FluidInference/FluidAudio) identifies its own Hugging Face organization as the source of its optimized models. The [vendored runner's upstream README](https://github.com/WT-MM/silicon-asr/blob/e8f2e021007eab99031183bed484a82bdfc22a28/README.md) explicitly uses these conversions. This is a first-party converter distribution, not an observed rehosting mirror. It is not NVIDIA's original distribution or endorsement. Official-source acceptance remains a reviewer decision. |
| mlx-community MLX v2 | The [pinned card](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v2/blob/8ae155301e23d820d82aa60d24817c900e69e487/README.md) identifies NVIDIA and links the converter's script. [parakeet-mlx upstream](https://github.com/senstella/parakeet-mlx/blob/master/README.md) documents the mlx-community collection and models. That supports runtime-designated distribution, not NVIDIA publication or Hermes approval. |
| SYSTRAN faster-whisper | The runtime and its converted models come from SYSTRAN, the upstream tool publisher. These are OpenAI-derived conversions, not OpenAI-hosted weights. Both selected English models have pinned revisions/hashes. |
| Gradium Phonon and voices | Published by Gradium, the runtime/model publisher. The selected 31M model and catalogue voices are Apache-2.0. Noncommercial 40M siblings are not selected. |
| Google MediaPipe and Face Landmarker | Official Google npm package and Google storage model. Exact version/checksums and setup-only behavior are disclosed. No live camera is needed for source review. |

Full revisions, file sizes, hashes and terms remain in
[the download table](REFERENCE.md#runtime-downloads),
[audio/assets.json](../audio/assets.json) and
[third-party notices](../THIRD_PARTY_NOTICES.md).

### Practical paths without removing voice or eyes

**Current default:** NVIDIA's v3 weights/runtime on native Apple Silicon.
Existing explicit v2 choices remain available. The converter/runtime provenance
above still needs human review when outbound communication is authorized: ask
whether the converter's original release and runtime-designated model collection
satisfy the official-source exception. No acceptance is inferred from the v3 default.

**If rejected:** build locally from NVIDIA's pinned original v2 checkpoint using
reviewed, pinned conversion source, then compile CoreML on the user's Mac. There
is an actual [FluidInference v2 export/validation pipeline](https://github.com/FluidInference/mobius/tree/main/models/stt/parakeet-tdt-v2-0.6b/coreml),
including `convert-parakeet.py`, `compile_modelc.py`, component parity tools and
quantization. Its README accepts `--nemo-path` and emits fixed 15-second CoreML
components. The [MLX card](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v2/blob/8ae155301e23d820d82aa60d24817c900e69e487/README.md)
links its conversion source too. This is a concrete source-build route, not an
implemented or verified replacement here. It needs a separately pinned conversion
environment, original-file hashes, output/runner shape verification and recorded
fixture-audio parity/latency proof before adoption. Local compiled outputs cannot
be required to match publisher-compiled byte hashes. Existing manifest verification
must remain strict for downloaded assets, with separate local-build provenance.

Do not add an untested converter launcher, fetch mutable remote scripts, relabel
a mirror as official, remove the MLX fallback, or force tiny Whisper to manufacture
a policy pass. Those changes would either weaken review or compromise voice.
The original NVIDIA NeMo path adds a different runtime and does not by itself
preserve the existing ANE performance. No model download/conversion was run here.
CoreML v3 is still excluded because of its contradictory published licence text.

## Sanitized screenshot plan

Status: no UI screenshots captured or fabricated. This task forbids private
Chrome, real devices, accounts and provider inference. Existing icons are not
UI proof. No historical image is relabelled as this candidate.

After authorization, capture the actual installed product on a disposable,
non-sensitive local fixture page. Record the exact source SHA and browser lane
beside every image. Use typed input, no microphone/camera or signed-in site.

1. Extension consent with its real permissions and connection action. Hide profile
   names, tab history and native ticket material by choosing a clean environment,
   not by fabricating UI.
2. Protected question input beside a small local table with invented sample data.
3. An answer card and typed follow-up. If using an offline scripted answer, label
   it "Fixture-backed UI, scripted answer, no provider inference" in the PR.
4. A real protected action review for a local fixture Submit control in confirm
   mode. Do not approve a real send, purchase, publish or deletion.

Inspect full-resolution images for names, URLs, keys, terminal history and private
content. Crop browser chrome only when it does not hide the relevant consent or
state. Do not composite or redraw product states. Keep English beta limits visible
in the caption. Add at most six HTTPS GitHub-hosted image URLs, pinned to the same
public SHA as the catalog entry. The optional gallery may be omitted, but the UI
PR still needs screenshots. A fixture image proves rendering, not live-model or
physical-device performance.

## Remaining release gates

- Human ruling on converted CoreML/MLX official-source status, or a verified local
  source-build replacement. No approval is inferred from licenses/checksums.
- Explicit authorization to publish the intended fixed commit. Verify anonymous
  reachability, then align the README install command, catalog SHA and evidence.
  The current README command installs historical `341c68b20ef689661b9d88f8bf23e213e5b25338`.
  Public master checked during this task was `484bb30e2372e120c972add57043da616586ae95`.
  Work began from local master `87cc84439e6da83603a4c272b599d4beffec594f`.
  None is the final fixed public candidate. The checked-in YAML intentionally has
  an empty pin rather than advertising an old vulnerable candidate.
- Repeat final anonymously fetched candidate validation and pinned-source CI on
  Ubuntu. Local macOS source checks and fresh dependency preparation are not
  upstream CI or a complete install/enable/doctor/removal journey.
- Capture the real sanitized UI images above. Physical voice/camera and live
  provider acceptance remain unverified for claims that require those journeys.
- Owner/major-contributor submission, green upstream CI and human maintainer
  review/merge. No PR, post, contact, push or submission is authorized here.
- Verify a usable private vulnerability-reporting route before announcement.
  This remains release hygiene, not an invented extra catalog admission rule.

## Local verification receipts

Machine-local logs are retained outside the product tree under
`/Users/Abid/.agents/coordinator/hermes-gaze/catalog-implementation`.
The coordinator's final report there records the exact committed candidate,
commands, results, stderr, failures and cost limits. Do not copy isolated runtimes,
caches or temporary build output into the source submission.

| Check on the working candidate | Result |
|---|---|
| Targeted pinned-download/native-input/layering modules | 28 tests passed, synthetic files and credentials only |
| Fresh stock `cmd_validate(..., install_deps=True)` in isolated state with native Git | Dependency resolution and installation completed, validator safe with no warnings |
| Direct imports from the newly prepared runtime | arm64 Python 3.14.9, psutil 7.2.2 and hub 1.33.0 imported |
| Full unittest discovery in that runtime | 372 tests passed with a short isolated temporary root |
| Stock validator from prepared runtime and neutral cwd | Safe, no warnings, declared capability lists match registration |
| Stock-main native lifecycle harness | Passed, real temporary local protocol with fixture browser/inference |

Failures retained in the receipts: an initial toolchain command used unsupported
`command -v -a` syntax. A first full-suite run hit 12 macOS AF_UNIX path-length
errors because this task's isolated TMPDIR was too long. Using a short private
temporary root fixed that environment issue without a product change. A direct
validator run from the plugin root imported its `tools.py` instead of stock
`tools`, then failed relative import. Running from neutral cwd fixed that import
shadowing. The first dependency-preparation validator also printed two missing
psutil tool-import messages from its bootstrap process. Direct prepared-runtime
imports and neutral-cwd validation were clean. No failure is counted as a pass.
