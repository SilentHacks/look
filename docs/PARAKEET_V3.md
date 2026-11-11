# NVIDIA Parakeet v3 recognition

Default selection updated 2026-11-10: new native Apple Silicon installations use
NVIDIA v3. Existing explicit model choices are preserved.
V3 has vendor-origin distribution and substantially faster observed
process-cold/cache-warm preparation: 0.719 s versus 41.711 s in the comparison,
with verified v3 product loading separately measured at 1.165–1.226 s.
CoreML v2 remains faster once warm: v3 recognition was 121 ms slower (1.75×).
One fewer word error out of 200 from one speaker does not establish better accuracy.
The startup advantage and vendor distribution justify the new-install default;
this small warm-recognition difference does not override that choice.

The v2 measurements below are historical. The current product and benchmark CLI
no longer load or download CoreML/MLX v2. Raw research results remain unchanged.

## Select and prepare

Look's `whisper_model` setting defaults to `auto`: NVIDIA `parakeet-v3` on native
Apple Silicon macOS, otherwise the existing `base.en` selection. Restart Hermes
after changing it, then run `/look setup`. No configuration file is rewritten.
Explicit `base.en` or `tiny.en` now selects that Whisper model directly, including
on Apple Silicon. V2 CoreML/MLX setup, loaders and cached fallbacks were removed.
Select `parakeet-v3` or `auto` for NVIDIA v3. Existing settings are not rewritten.

V3 currently supports native Apple Silicon macOS only. No new Python product
dependency, Hermes patch, tool, listener, browser permission or microphone owner is
introduced. All input still comes from Look's existing native capture/decoded
buffer. The worker calls the vendor C ABI with a local GGUF path, never its CLI's
live capture, server, alias lookup or automatic downloader.

Explicit setup anonymously fetches the pinned official runtime from GitHub and
weights/model card from Hugging Face (`token=False`). Registration and transcription
are cache-only. The runtime archive and complete extracted tree live under
`~/Library/Caches/Look/nemo-speech/0.3.0`; weights/card use the existing shared HF
cache. Setup retains the archive's license directory. Removing the plugin does not
erase these caches. Do not delete unrelated shared HF models.

The same worker/model stays loaded across questions. Readiness checks use cached
state and process liveness, not disk/model-loader locks. The worker warms one
second of silence before publishing readiness. Failed native loading is cached;
a dead worker does not silently restart/replay its failed request. Explicit setup
may restart it. Ordinary availability/inference failures can use cached Whisper
base.en. Integrity failures propagate and do not fall through. Explicit v3 setup
prepares the selected vendor backend before trying cached Whisper and never
downloads fallback models.
A warmed fallback remains capture-ready after v3 failure. Logs identify native
failure and `_LAST_BACKEND` identifies the backend that returned the transcript.

Word milliseconds from the vendor ABI become seconds, validated against audio
duration, then receive the exact `audio_epoch`. Zero/quiet-buffer handling and
normalization remain in `voice.py`. The native worker accepts mono 8–96 kHz and
at most 30 seconds, matching native capture's ceiling. It has a 90-second startup
deadline and one 60-second request deadline shared by nonblocking header/audio
writes and reply reads. Expiry or native failure kills/reaps the worker without
restarting or replaying that native request. No audio WAV is written by this
backend: PCM crosses private stdin; text/times return on stdout.

Cancellation retains existing inbox ownership and terminal-result guards: Stop
removes the exact pending request, so a late transcript cannot submit that removed
request. Disconnect pauses admission; pending ASR and its result may be retained
in memory while disconnected. **Stop does not interrupt an already-running native
decode immediately** (also true of the old in-process recognizers). The offline
ABI has no cancellation operation. The probe
also exercises forced worker exit during decoding and explicit cached restart;
it does not establish a new user-facing immediate-cancellation guarantee. No
microphone, Chrome, account, private speech or paid provider was accessed.

## Same-audio benchmark

Apple M1, 8 GB unified memory; arm64 macOS 27.0.1; CPython 3.14.4. Backends ran
serially, one process per backend, three passes over the **same eight clips**.
No parallel inference during the final comparison. macOS `sandbox-exec` denied
network access to parent and children. Filesystem/Metal/CoreML caches were not
cleared; this is process-cold/cache-warm startup, not a reboot-cold measurement.

| Backend actually used | Word errors / 200 | WER | Load + silent warmup | First clip | Median repeated clip | Parent peak RSS | Worker peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|
| NVIDIA v3 Q8, NeMo-Speech.cpp Metal | 5 | 2.5% | 0.719 s | 0.191 s | 0.284 s | 153 MB | 214 MB |
| Current v2, CoreML/ANE | 6 | 3.0% | 41.711 s | 0.129 s | 0.163 s | 568 MB | — |
| Current faster-whisper base.en, CPU int8 | 18 | 9.0% | 1.038 s | 0.484 s | 0.512 s | 560 MB | — |

The repetition median pools the 16 requests in passes two and three. All paths
receive identical decoded float32 and Look gain normalization. Token/timestamp
conversion is included. Fixture decode and asset checksum verification are outside
the benchmark timing; startup includes model load and silent inference. The v3
benchmark constructs the verified downloaded runtime directly; actual cache-only
product loading, including verification, was separately 1.165 s in the native
probe. Prior v2 startup's 41.7 seconds is a preparation wait, not a per-question
cost. Readiness prevents opening capture before preparation completes.

An initial exploratory v3 startup took 25.562 seconds, then JFK transcription
0.433 seconds. Its subsequent cached startup was much shorter. No reboot/cache
purge isolated shader compilation from other first-load work, so the cause is
unverified. Initial CoreML startup was 38.428 seconds. Those exploratory runs are
not mixed into the final table. Isolated explicit v3 setup, including download,
verification, extraction, loading and warmup, took 20.191 seconds; transfer speed
and existing OS caches affect that number.

RSS comes from macOS `getrusage` (bytes), worker peak after reap and parent peak
separately. Do not sum these as exact total memory: peaks need not coincide,
shared mappings can overlap, and Metal/ANE/device allocations are not fully
represented. No accelerator-memory or system-wide peak measurement is claimed.
No end-to-end model answer latency was measured; the 121 ms recognition difference
is not a measured full-answer difference. MLX was not benchmarked.

### Sample and license

The pinned public [HF LibriSpeech dummy validation subset](https://huggingface.co/datasets/hf-internal-testing/librispeech_asr_dummy/tree/5be91486e11a2d616f4ec5db8d3fd248585ac07a)
is a 9,192,059-byte Parquet file with actual `text` references and embedded audio.
SHA-256: `4e69a06fa5edc90921e5e7e39a7084881f8b3ed9c805c574f4f39c6fde27c603`.
Selection fixed before comparison: first eight rows, IDs `1272-128104-0000` through
`1272-128104-0007`, speaker 1272, 86.345 seconds total, 200 reference words. Three
passes are **24 requests per backend, not 24 independent samples**. References are
from the dataset, not ASR output. WER uses lowercase alphanumeric words with internal
apostrophes, ignores other punctuation, and ordinary Levenshtein word edits.

[LibriSpeech/OpenSLR 12](https://www.openslr.org/12) is **CC BY 4.0**. Credit
Vassil Panayotov, Guoguo Chen, Daniel Povey and Sanjeev Khudanpur; corpus derived
from LibriVox public-domain audiobook readings. Audio remains outside the repo;
public reference/hypothesis text and measured times are retained in
[`benchmark/asr_comparison_results.json`](../benchmark/asr_comparison_results.json).
One clean read-English speaker, tiny sample, possible training overlap and no
conversational/browser-command/noisy/multilingual coverage: **not a general WER
ranking or proof of v3 superiority**.

The native lifecycle probe additionally uses upstream's MIT-attributed
[JFK fixture](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/20999cc921d2b14aa58708f61756a8b2e787ba20/test_files/asr/wav/test/jfk.wav),
SHA-256 `59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e`.
It is not counted in the WER table. NVIDIA's third-party notice traces it to
whisper.cpp commit `23ee03506a91ac3d3f0071b40e66a430eebdfa1d`.

## Distribution and policy

- **Weights:** NVIDIA-hosted, unmodified `parakeet-tdt-0.6b-v3.q8_0.gguf`, revision
  `541d1f99c6b0c3cd0b11a95167540bb8edefd82b`, 713,975,456 bytes, SHA-256
  `e3880d0aaaaf2c308ea2c35016b2b895c423eb3fda924c1b463d1c19b7f4d32e`.
  [Pinned model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3/blob/541d1f99c6b0c3cd0b11a95167540bb8edefd82b/README.md):
  CC-BY-4.0, NVIDIA attribution; [license terms](https://creativecommons.org/licenses/by/4.0/).
  The card is downloaded and checksum-pinned too. This is not the unrelated
  FluidInference CoreML-v3 conversion with contradictory card terms.
- **Runtime:** NVIDIA's official [v0.3.0 release](https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.3.0),
  `nemo-speech-0.3.0-macos-aarch64-metal.tar.gz`, 7,239,335 bytes, SHA-256
  `2b972ed8b5dba07492212acf8cb75cbf34ecb141198ffa1997febe84b7c4d9ed`.
  Downloaded bytes matched the GitHub release digest. Regular extracted payload
  is 19,730,497 bytes (excluding symlink duplicates). Both archive and extracted
  file checksums are pinned in `audio/asr/parakeet_v3_runtime.json` and verified
  before native loading; paths escaping the cache are rejected.
- **Source:** release tag resolves to `20999cc921d2b14aa58708f61756a8b2e787ba20`.
  [Official source archive](https://codeload.github.com/NVIDIA/NeMo-Speech.cpp/tar.gz/20999cc921d2b14aa58708f61756a8b2e787ba20),
  3,096,203 bytes, SHA-256
  `2e02f2486a0ce9e5bcbd57d04721b849f9572857a6862c9daf5076549982d0c2`.
  This archive does not include submodule contents. Its gitlinks pin llama.cpp
  `bd4f514db14d87fded667787a7a963bfbaa98e89` and cpp-httplib
  `62d899feac3cf9215a55f2b43da250fdd98d2156`; release scripts pin SentencePiece
  and ITN dependencies. The [release workflow at that source](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/20999cc921d2b14aa58708f61756a8b2e787ba20/.github/workflows/release.yml)
  builds macOS CPU/Metal archives, initializes required submodules and packages
  notices. **No local rebuild, reproducible-build equivalence, code-signature
  verification or artifact attestation verification was performed.**
- **Terms:** NVIDIA-authored runtime Apache-2.0, copyright 2026 NVIDIA CORPORATION
  & AFFILIATES. The complete downloaded `share/licenses/nemo-speech` tree retains
  LICENSE, NOTICE and THIRD_PARTY_NOTICES.md, including ggml/llama.cpp MIT,
  cpp-httplib MIT, miniaudio Unlicense/MIT-0; SentencePiece/Abseil Apache-2.0,
  protobuf-lite/Darts-clone BSD; OpenFST/Sparrowhawk Apache-2.0 and protobuf/RE2 BSD.
  The aggregate notice also discusses optional components such as KenLM LGPL,
  CUDA and other builds; do not describe every optional component as linked into
  this Metal archive. Its packaged source notice is the authoritative component
  inventory, not a blanket relicensing as Apache. Look retains it unchanged.

[Catalog rule 17](https://github.com/NousResearch/hermes-agent/blob/main/plugin-catalog/README.md#admission-policy)
permits checksum-pinned, disclosed setup-time native downloads **from the upstream
tool's official source**, not opaque payloads committed to the plugin. This design
uses that exception: no binary/library/GGUF/audio archive is committed and no
unofficial runtime mirror or mutable installer executes. It does not use the
separate plugin-repository-built/attested bundled-binary route. Vendor hosting and
hashes improve provenance; they are **not catalog admission or legal clearance**.
Maintainers must still resolve retained converter-owned v2 fallback acceptance,
model-artifact policy interpretation, scanner results and final distribution
review. Weight licensing does not clear training data. No PR/submission/contact
or host Hermes/config modification was performed.

## Reproduce

From this checkout, create an isolated native-arm64 Python environment. No paid
inference and no speech uploads are involved; setup downloads only public product
assets and explicitly requested public fixtures.

```sh
python3 -m venv /tmp/look-v3-venv
P=/tmp/look-v3-venv/bin/python
$P -m pip install 'numpy>=1.26,<3' 'huggingface_hub>=0.23,<2' \
  'faster-whisper>=1,<2' 'websockets>=15,<16' pyarrow soundfile
# Explicitly prepare Whisper for comparison (no microphone).
$P -c 'import tests; from look.audio.asset_cache import prepare,WHISPER; prepare(WHISPER["base.en"],download=True)'
# Isolated v3 product setup, without importing plugin registration.
V3_HOME=/tmp/look-v3-home
V3_HF=/tmp/look-v3-hf
env HOME="$V3_HOME" HF_HOME="$V3_HF" $P -c 'import tests; from look.audio.asr.parakeet_v3 import get_runner; get_runner(download=True).close()'
# Explicit public fixture fetch, then compare (use the selected local GGUF path).
R="$V3_HOME/Library/Caches/Look/nemo-speech/0.3.0/nemo-speech-0.3.0-macos-aarch64-metal"
M="$V3_HF/hub/models--nvidia--parakeet-tdt-0.6b-v3/snapshots/541d1f99c6b0c3cd0b11a95167540bb8edefd82b/parakeet-tdt-0.6b-v3.q8_0.gguf"
$P -c 'import tests; from look.benchmark.asr_compare import main; main()' \
  --fetch --fixtures /tmp/look-reference.parquet --backend v3 --runtime "$R" \
  --model "$M" --out /tmp/look-v3.json
# Run serially against the existing Whisper cache.
$P -c 'import tests; from look.benchmark.asr_compare import main; main()' \
  --fixtures /tmp/look-reference.parquet --backend whisper --out /tmp/look-whisper.json
$P -m unittest tests.test_parakeet_v3 tests.test_pinned_downloads \
  tests.test_voice_decode tests.test_session_delivery
```

After fetching fixtures/assets, prefix **each benchmark command** with
`/usr/bin/sandbox-exec -p '(version 1)(allow default)(deny network*)'` to reproduce
the final network-denied conditions (omit `--fetch`). For the product lifecycle
probe, download the pinned JFK fixture explicitly, then run with the experiment's
HOME/HF_HOME under the same network-denying sandbox:

```sh
env HOME="$V3_HOME" HF_HOME="$V3_HF" $P -m tests.parakeet_v3_offline --audio /path/to/jfk.wav
```

Backend-branch verification (2026-11-10, before the new default integration):
- **66 focused tests passed:** the four modules above plus `tests.test_voice_turns`,
  with external and loopback networking denied.
- **382 tests passed** in the final `unittest discover -s tests -t .` run. The
  sandbox denied external networking but allowed loopback/Unix sockets for local
  transport tests; HOME/HF_HOME pointed to the isolated experiment caches.
- Actual offline native probe: verified cache load/warmup **1.226 s**, exact epoch
  shift, singleton readiness, native silence, 8-kHz resampling, 30-second input,
  over-limit rejection, forced native exit/no implicit restart and explicit offline
  cached restart. First word: `And`, start `1700000000.24`, end `1700000000.56`.
- Device-free regressions exercise a live non-reading child with 30-second PCM,
  a child consuming PCM but withholding its reply, and delayed writes/reads that
  must share one deadline. Each timeout kills/reaps the child and prevents implicit
  restart. Startup timeout and fresh empty-singleton cached Whisper
  fallback preparation are covered, including explicit setup and terminal integrity
  failure.
- Called the actual setup guide with each selection and mocked preparation:
  v3 discloses ~721 MB, NVIDIA weights, the official native runtime, Hugging Face,
  GitHub and cache-only fallbacks; explicit legacy setup retains its v2-chain disclosure.
  No download or device initialization was needed for this copy check.

No full fresh Hermes installation, Linux/Intel execution, multilingual accuracy,
semantic word-alignment quality, real capture, TUI/UI journey or catalog
admission was tested. The comparison was retained, not rerun; the integration probe
is not a new multi-backend benchmark.

Measured dependency versions: NumPy 2.5.4, huggingface_hub 1.33.0,
faster-whisper 1.2.1, CTranslate2 4.8.5, PyObjC/CoreML 13.0, PyArrow 26.0.1,
soundfile 0.14.0. PyArrow/soundfile are benchmark-only; no product requirements
changed. Model/binary/fixture downloads and local inference incurred **$0 service
charges**; local compute, bandwidth and disk usage are not monetary estimates.
Downloaded payloads can remain in the explicit experiment caches. Benchmark
scripts do not open the microphone or upload audio.

## Default integration verification — 2026-11-10

Merged backend head `4483bc53f203b37a5843dfd5d1bf7348cb022a16` into local master.
No stored configuration is migrated or rewritten. An unset/`auto` selection uses
v3 on native Apple Silicon; explicit prior selections retain their behavior.
V3 setup now prepares the vendor backend before loading legacy cached models.

- 85 targeted tests passed: `tests.test_parakeet_v3`, `tests.test_pinned_downloads`,
  `tests.test_voice_decode`, `tests.test_first_run`, `tests.test_session_delivery`,
  `tests.test_voice_turns`, with all network denied.
- Added regressions for unset/auto platform mapping, preservation of explicit
  base.en/tiny.en/parakeet-v3, and selected-v3 setup before legacy cache access.
- The registered `/look setup` handler ran against cached NVIDIA assets with
  all network denied, real asynchronous preparation and a fixture session.
  It disclosed NVIDIA/Hugging Face/GitHub/~721 MB and became capture-ready
  without accessing legacy models. No real Chrome or Hermes host was modified.
- The actual `tests.parakeet_v3_offline` probe passed against the existing public
  JFK fixture and pinned runtime/model caches, with all network denied:
  load/warmup 1.254 s; epoch first word `And`, 1700000000.24–1700000000.56;
  silence, 8-kHz resampling, 30-second bounds, forced exit/no implicit restart
  and explicit cached restart passed.
- Final suite was justified by changing shared configuration defaults:
  `python -m unittest discover -s tests -t .`, **384 tests passed**.
  It used an isolated temporary HOME/HF_HOME, short TMPDIR and external-network
  denial with local sockets allowed.

Existing runtime/model manifests retain their exact revisions and checksum pins.
No new downloads, personal devices/accounts/audio, paid inference, installed-host
changes, push or publication occurred. `docs/research/` remains untracked.
Linux/Intel/Rosetta mapping is regression-tested, not executed on those systems;
fresh online installation, live voice and immediate decode cancellation remain
unverified. Converter-owned v2 sources still need catalog-policy clarification;
the NVIDIA default does not remove explicit legacy choices or cached fallbacks.

