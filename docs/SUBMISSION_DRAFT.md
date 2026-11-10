# Look catalog submission draft

Owner review only. Nothing has been posted or submitted. Submit exactly one
`plugin-catalog/hermes-gaze.yaml` file to NousResearch/hermes-agent after the
[release gates](CATALOG_READINESS.md) close. The draft entry is
[catalog/hermes-gaze.yaml](catalog/hermes-gaze.yaml). Its empty SHA deliberately
blocks submission until a fixed public commit is verified.

## PR title

Add Look browser companion

## PR body

Look lets you ask Hermes about what you point at in Chrome, with answers and
follow-ups in private cards. It supports typed input, local English speech,
local read-aloud, guarded browser actions and optional experimental eye tracking.
This is an Apple Silicon macOS source beta for one display. Eye tracking is not
a precise pointer replacement and has no established real-camera accuracy.

The plugin uses native Python tools, seven hooks, two middleware registrations,
commands, CLI, a bundled skill and frozen system guidance. Fourteen declared
browser/evidence tools use captured identities and exact user-turn authority.
The supported native lane requires Hermes 0.23.1 or newer, an in-process local
POSIX gateway and explicit profile input permission. It uses the public same-user
control socket, one-use interactive session ticket and exact terminal receipts.
It does not start Hermes or modify an installed host.

### Installation and privacy disclosures

- Questions and bounded page evidence go to the configured Hermes model and may
  remain in Hermes/provider history. An auxiliary scope-selection call can add
  provider cost. Optional TypeSafe highlighting sends the question, pointer
  structure and scope descriptions to TypeSafe. Page text is opt-in. TypeSafe
  can add service costs. Its retention policy has not been verified. Its key
  comes through Hermes's profile-scoped secret API. No mandatory API key exists.
- Chrome debugger access is broad, including signed-in pages. The unpacked
  extension uses debugger, nativeMessaging and tabs permissions. Setup stages
  reviewed extension files, a Python native host and Chrome native-messaging
  registration under the user account. Look reads the connecting profile's
  permission/isolation config. Public asset downloads disable HF authentication
  and do not resolve vendor login credentials.
- Separate-browser and eye modes launch Chrome. The separate browser retains
  sign-ins and exposes a loopback debugging port until Chrome exits, even after
  Look stops. Speech may spawn ffmpeg or macOS /usr/bin/say. Registration starts
  a background GET-only demo/status server on 127.0.0.1:9111 and cache-only speech
  warmup. Browser/input/speech workers run while connected. Python/native package
  preparation is separate through Hermes. There is no Look telemetry service.
- Explicit setup fetches pinned, checksum-verified public assets from Hugging
  Face and its storage redirects: FluidInference's NVIDIA Parakeet CoreML
  conversion (465 MB), mlx-community's MLX conversion (2.47 GB), SYSTRAN's OpenAI
  Whisper fallback (148 MB base.en or 78.1 MB tiny.en), and Gradium's Phonon model
  (65 MB plus about 0.26 MB per voice). Eye setup fetches Google's MediaPipe
  runtime from npm (6.6 MB compressed) and Face Landmarker from Google storage
  (3.76 MB). Speech and eye inference stay local. Converter-owned CoreML/MLX
  acceptance under rule 17 remains unresolved, not approved by these checks.
- Shared model caches, sensitive biometric calibration, native-host files and
  Chrome profile/sign-ins persist outside the plugin tree. MLX uses a temporary
  WAV, deleted after transcription where possible. Crashes/deletion failures
  can leave it behind. Opt-in development record_trials writes local replay
  evidence, not audio. Plugin removal does not erase these files or
  Hermes/provider history. Detailed paths and removal steps are in the README
  and technical reference.
- Default action mode requires protected mouse approval for sending, buying,
  deleting and ambiguous controls. Explicit /look actions allow-all skips Look's
  approval cards for requested actions during that connection. It can send,
  buy or delete immediately, including if page instructions mislead the model.
  Stop/reconnect restores confirmation. Hermes approvals, ownership checks,
  secret-field exclusions and unknown-outcome/no-replay rules remain enforced.
  Typing and navigation can themselves have site effects. Unsupported secret
  fields, frames and custom controls fail rather than being rematched.
- Card words and typed questions live in opaque, script-disabled frames, not
  readable website DOM. This is not protection from another authorized debugger
  or malicious local software. Screen-reader compatibility is unverified.

### Provenance and verification

MIT source with retained third-party notices. No model weights, native binaries,
WASM or bytecode are bundled. Exact revisions, file hashes, publishers, sizes and
licences are documented in the technical reference and third-party notices.
See CATALOG_READINESS.md for the actual checks and unresolved source-policy gate.
Do not replace this paragraph with a claim of catalog approval.

Before posting, attach receipts for the final public pin, dependency preparation,
stock validation, source/payload checks and upstream Ubuntu CI. Local fixture
inference is not a live provider, physical-device or signed-in-site test.

### Screenshots

Not captured. The required real UI images and sanitization procedure are listed
in CATALOG_READINESS.md. Do not submit an icon, mockup or scripted state as a
live user result. Any fixture-backed image must be labelled as such.

## Publication controls

Only the repository owner or a major contributor should submit. Owner approval
is still required for publishing a commit, opening a PR, contacting maintainers,
posting or submitting. Catalog updates use a newly reviewed SHA-bump PR and
Hermes's update mechanism, never a plugin self-updater.

The README's current published install pin predates these fixes. Align the
README, catalog SHA, source receipts and any image URLs only after the intended
fixed commit is publicly reachable. An internal candidate cannot be presented as
an installable public release.
