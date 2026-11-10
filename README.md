# Look

Ask Hermes about what you point at in Chrome. Type a question or hold Space,
wait for **Listening**, and speak. Answers appear in a private card; browser
changes use captured controls and guarded approvals.

**Source beta for technical users, not a Chrome Web Store release.** The public
release pin and user-operated acceptance are still pending. Final isolated browser
acceptance is blocked; see [evidence, trial procedure and gates](docs/RELEASE_READINESS.md).

## Supported lane

Apple Silicon Mac, native arm64 Python, standard Google Chrome in Applications,
one display, English. Use stock Hermes's canonical local TUI/CLI/Desktop session,
with in-process plugins and explicit injection permission. No Hermes fork or
startup warmup message is required.

Python `>=3.11,<3.15` and Hermes `>=0.22.0` are metadata constraints, not a tested
version matrix. Local installation evidence used Python 3.14.9 and stock Hermes
`2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19`.
Linux and Intel/Rosetta cursor paths are unverified; Windows, alternate Chrome
builds and multiple displays are unsupported. Physical audio, camera and ordinary
signed-in browser acceptance remain user-operated checks.

## Install a reviewed local revision

**No approved public release SHA or catalogue install command is published here.**
From a reviewed Git checkout, install its committed revision with stock Hermes:

```sh
LOOK_SOURCE="$(pwd -P)"
LOOK_REF="$(git rev-parse --verify HEAD)"
hermes plugins install "file://$LOOK_SOURCE" --ref "$LOOK_REF" --enable
```

Run interactively in your intended Hermes profile. Review the scanner findings
and Python/native dependency preparation before agreeing. Do not bypass a dangerous
finding. Declining preparation leaves a new installation disabled. When ready,
`hermes plugins enable hermes-gaze` prepares and enables it; at the observed stock
revision, that explicit enable command did not ask a second dependency question.
If installation itself was refused, fix the reported cause and repeat the same
pinned install instead. Noninteractive success can mean **installed but disabled**;
check `hermes plugins list --plain --no-bundled`.

In that profile's `config.yaml`, merge:

```yaml
plugins:
  isolation: in_process
  entries:
    hermes-gaze:
      allow_gateway_injection: true
```

Quit Hermes, stop its gateway with `hermes gateway stop`, then restart it after
code/configuration changes. Use your normal terminal app. Native microphone
permission belongs to the app/process launching Hermes, not to a website.
Grant it in macOS **System Settings → Privacy & Security → Microphone** before
voice use; restart the launching app after changing permission.

## Connect, ask, stop

In the intended new Hermes conversation:

1. For your existing Chrome, use the extension setup below. For an isolated trial,
   choose the separate browser; it does not share your ordinary Chrome sign-ins.
2. Point at ordinary page text and press **Right Option** to type your first
   real question. It initializes Hermes's lazy agent; no dummy question is needed.
3. For voice, run `/look setup` to explicitly prepare local recognition, then
   hold Space, wait for **Listening**, speak and release. Text fields and
   keyboard-focused controls keep native Space. A tap scrolls.
4. **Q** recalls answers. Hold Space on an answer for a follow-up. **Esc** stops
   or dismisses. **Try again**, **Skip**, and **Continue with the rest** recover
   definite failures; never resend an unknown-outcome action automatically.
5. `/look stop` ends local capture, tracking, read-aloud, overlays and action
   approvals. It leaves tabs open and cannot undo changes or cancel a Hermes turn
   the host already accepted. Stop is shared across Look conversations on this Mac.

### Separate Look Chrome

Run `/look start --separate`. This launches/reuses a dedicated persistent profile.
Only sign in if you intend to retain that account in that profile. Stop leaves
Chrome and its local debugging port running until you exit that browser.
Do not forward the port or expose it to Hermes's generic browser tools.

### Use my existing Chrome

Run `/look start --existing`, read the disclosure, then
`/look start --existing --accept` if you agree. Stable Chrome 145+ needs
`chrome://inspect/#remote-debugging` enabled and your native Chrome approval.
This grants **broad debugger access**, including signed-in pages, not merely the
pointed element. Use regular HTTP(S) tabs in the authorized profile. Look does
not silently fall back to another browser. After Stop, turn off remote debugging
in Chrome if no longer wanted. [Connection, revocation and limits](docs/REFERENCE.md#use-my-existing-chrome).

### Existing Chrome: extension beta

1. Run `/look setup extension` (shell: `hermes look setup-extension`). No extension
   ID, Python path or environment variable is needed.
2. In the intended Chrome profile, open `chrome://extensions`, enable **Developer
   mode**, choose **Load unpacked**, and select the printed folder:
   `~/Library/Application Support/Look/extension/unpacked`.
   **Command–Shift–G** accepts the path in the macOS picker. Review the broad
   **debugger**, **nativeMessaging** and **tabs** permissions; the debugging banner remains.
3. Run `/look start --extension` in the intended Hermes conversation. On an ordinary
   HTTP(S) tab, open **Look**, paste its one-use 120-second ticket, and choose
   **Connect this tab**. Use **Right Option** for private typed input; wait for
   **Listening** before speaking.
4. For another tab, open Look there and choose **Use on this tab**.
   `/look stop` disconnects and keeps Chrome/tabs open.

Setup does not install/enable the extension or bypass Chrome consent/policy.
After updating: stop Look, restart every Hermes process, rerun setup, **Reload**
Look in Chrome and pair afresh. The staged folder/ID stay fixed; rerun setup if
Hermes's Python moves. Remove with `/look setup extension uninstall`, then remove
Look in Chrome. [Setup, recovery and acceptance gates](docs/CHROME_EXTENSION.md).

## Optional eyes and read aloud

Start with a useful cursor answer. `/look calibrate` uses verified cached eye
tracking files; `/look setup eyes` explicitly permits missing downloads and
camera startup in Look's separate camera window. Grant Camera permission to your
launching app. Complete the nine-point calibration and accuracy check, move the
pointer once per page and after zoom/resize, and recalibrate after posture,
camera or eyewear changes. `/look cursor` stops the camera.

**Eye tracking is experimental broad-region input, not a precise pointer or an
accessibility guarantee.** No population accuracy has been established. It cannot
approve actions. [Setup and limits](docs/WEBCAM_GAZE.md).

Silent answers need no output model. `hermes look setup-speech` explicitly
downloads local Phonon-31M English/Russell assets without playing sound; restart
Hermes, then choose **Read aloud** on an answer. Automatic reading starts off.
[Asset sizes, licences and offline speech](docs/REFERENCE.md#runtime-downloads).

## Privacy and action limits

- Local tracking and recognition **do not mean local answers**. Your typed or
  transcribed question and bounded page evidence go to your configured Hermes
  model. Hermes can retain this evidence in `state.db`, even with plugin replay
  recording off; provider retention depends on your provider.
- Live camera images and eye features stay local; calibration is sensitive and
  saved locally. The microphone opens only while talking. Failed recordings can
  remain in memory for retry. The MLX fallback uses a temporary WAV; crashes or
  deletion failures can leave it in the OS temporary folder.
- Registration does not download models. Explicit setup fetches pinned assets;
  Hermes PM separately prepares Python/native dependencies. Optional TypeSafe
  early highlighting sends the question and static scope descriptions if its key
  is configured; extra page text is opt-in, off by default.
- Private cards isolate words and trusted input from website scripts, **not**
  other debuggers or malicious same-user/root software. Connected conversations
  replace raw code, terminal, browser and delegation tools with guarded tools.
- Send, Buy, Delete and ambiguous controls require your primary mouse click on
  the protected review card. Gaze, speech, keys, page text and model text cannot
  approve. Typing and GET navigation can themselves have effects on some sites.
  Password, payment and other secret fields are not supported.
- Cross-origin frames, canvas, unknown widgets and detached identities may be
  unavailable. Look fails rather than guessing targets or replaying mutations.

[Security/reporting](SECURITY.md) · [Downloads and detailed behavior](docs/REFERENCE.md)

## Update, recover, remove

Quit Hermes and stop its gateway before replacing plugin code. An exact SHA
installation stays pinned: reinstall the reviewed new SHA with `--force --ref`
and restart Hermes. `hermes pm install` repairs dependencies; it does not update
Look or download speech models. Keep dependency/preparation errors if repair fails.

Before removing the plugin or its Python environment, stop Look and uninstall
its native host with `/look setup extension uninstall`; remove Look in Chrome. Then:

```sh
hermes plugins remove hermes-gaze
```

Removal does not erase Hermes/provider history, model caches, calibration or the
separate Chrome profile/sign-ins. [Data locations and selective removal](docs/REFERENCE.md#daily-use-updates-and-removal).
The install/config name remains `hermes-gaze`; `/gaze` and `hermes gaze` are aliases.

## Development and evidence

[Contributing and command matrix](CONTRIBUTING.md) · [Change record](CHANGELOG.md) ·
[Release gates](docs/RELEASE_READINESS.md) · [Local submission draft](docs/SUBMISSION_DRAFT.md) ·
[Third-party notices](THIRD_PARTY_NOTICES.md) · [Agent architecture guide](AGENTS.md)

Live prompt probes require a self-contained virtualenv with Hermes and its
dependencies installed; the managed store interpreter alone is insufficient in
a disposable home. `benchmark/probe_sessions.py` requires `--prompt-only`, uses
configured inference and private credential copies, and retains answers. It does
not run the retired HUD flow or share host dependency state. Run only with explicit
provider authorization; see [probe commands](CONTRIBUTING.md#live-prompt-probes).

Historical [plan](docs/PLAN.md), [prior-art pitch](docs/PRIOR_ART_AND_PITCH.md) and
[old playbook](docs/DEMO_AND_SUBMISSION_PLAYBOOK.md) are provenance, not current
install instructions, accuracy claims or evidence of catalogue availability.
