<div align="center">
  <img src="assets/look.png" width="112" height="112" alt="Look icon">
  <h1>Look</h1>
  <p><strong>Point at something in Chrome. Ask Hermes about it.</strong></p>
  <p>Type a question or speak. Read the answer beside the page.<br>Try optional eye tracking when you want to point by looking.</p>
</div>

<p align="center">
  <a href="#your-first-question">How it feels</a> ·
  <a href="#get-ready">Get ready</a> ·
  <a href="#connect-chrome">Connect Chrome</a> ·
  <a href="#try-eye-tracking">Eye tracking</a> ·
  <a href="#privacy-and-control">Privacy</a>
</p>

Look is an open-source plugin for Hermes Agent. It gives your question context
from what you point at, so “What does this mean?” can refer to a table cell,
a paragraph or a page control. Answers appear in a private card in Chrome.
You can ask follow-ups without copying the page into a chat.

| When you're… | Try asking… |
|---|---|
| Reading an unfamiliar term | “Explain this in plain language.” |
| Checking a table | “What does this column measure?” |
| Working through a form | “Help me fill this in.” |

Look can also navigate, fill supported fields and use captured page controls.
Send, Buy, Delete and ambiguous actions need your mouse click on a review card.

> [!IMPORTANT]
> **Source beta for technical users.** There is no Chrome Web Store release or
> approved public install pin yet. Headed browser, real-device and configured-model
> trials remain user-operated release gates. Start with a non-sensitive page.
> See the [release evidence and remaining checks](docs/RELEASE_READINESS.md).

## Your first question

Once [installed](#install-from-a-reviewed-checkout) and [connected](#connect-chrome):

1. **Point.** Move the pointer over ordinary text or a table cell.
2. **Ask.** Press **Right Option**, type “What does this mean?” and submit.
   For voice, hold **Space**, wait for **Listening**, speak, then release.
3. **Keep going.** Read the answer on the page. Hold Space on its card to ask
   a follow-up, or point elsewhere for a new question.

| Control | What it does |
|---|---|
| **Right Option** | Open a private typed question |
| Hold **Space** | Talk, after local speech setup |
| **Q** | Recall answers |
| **Esc** | Stop or dismiss the current interaction |
| **Stop request** | Cancel that question or follow-up; keep its partial answer |
| `/look stop` | Disconnect Look and stop local capture, tracking and read-aloud |

Text fields and keyboard-focused page controls keep their normal Space key.
Click ordinary page text before talking. A quick Space tap scrolls instead.
The first real question starts Hermes's lazy agent. No warmup question is needed.

Use **Stop request** beside a question to stop processing. Canonical local Hermes
connections cancel that exact admission through the stock host API. Other
frontends stop browser actions and ask you to stop processing in Hermes.
An action already in progress may still finish; Stop cannot undo it. Queued
questions and follow-ups stay paused until **Continue with the rest**. You can
record another question while waiting, but it waits for the active request's
terminal receipt. An unknown outcome stays owned and cannot be retried or skipped.

## Get ready

The supported beta setup is:

- **An Apple Silicon Mac**, native arm64 Python and one display.
- **Current stable Google Chrome**, installed in Applications.
- **Stock Hermes**, with a configured model and a canonical local TUI, CLI or
  Desktop conversation. Use in-process plugins and explicitly allow Look input.
- **English** for local speech recognition and read-aloud.

No Hermes fork is needed. Python `>=3.11,<3.15` and Hermes `>=0.22.0` are package
constraints, not a tested compatibility matrix. Recorded local installation used
Python 3.14.9 and stock Hermes `2bd378ed1b8d6bf2192cb26e0a55ff3091e6bd19`.
Linux and Intel/Rosetta cursor paths are unverified. Windows, alternate Chrome
builds and multiple displays are unsupported.

### Install from a reviewed checkout

There is no published release command to paste yet. If you have a reviewed Git
checkout, run this **from its root** to install its committed revision into your
intended Hermes profile:

```sh
LOOK_SOURCE="$(pwd -P)"
LOOK_REF="$(git rev-parse --verify HEAD)"
hermes plugins install "file://$LOOK_SOURCE" --ref "$LOOK_REF" --enable
```

Run interactively. Review the scanner findings and dependency preparation before
agreeing. Do not bypass a dangerous finding. A noninteractive install or declined
preparation can leave Look installed but disabled. Check with
`hermes plugins list --plain --no-bundled`. When ready,
`hermes plugins enable hermes-gaze` prepares and enables it. At the recorded stock
revision, explicit enable did not ask a second dependency question. If installation
was refused, resolve the reported cause and repeat the pinned install.

Merge this into that Hermes profile's `config.yaml`:

```yaml
plugins:
  isolation: in_process
  entries:
    hermes-gaze:
      allow_gateway_injection: true
```

Quit Hermes, run `hermes gateway stop`, then restart Hermes and open a new
conversation. Repeat this restart after code or configuration changes.

### Set up voice when you want it

Typed questions need no microphone or speech models. For voice, run `/look setup`
in Hermes to explicitly prepare local recognition. The initial Apple Silicon
recognition download is approximately 465 MB, with fallbacks up to 2.47 GB.
Wait for recognition to be ready before holding Space.

In macOS **System Settings → Privacy & Security → Microphone**, grant permission
to the app or process launching Hermes, not Chrome. Restart the launching app
after changing permission. Each recording has a 30-second limit.
[Downloads and licences](docs/REFERENCE.md#runtime-downloads).

## Connect Chrome

Choose where you want to browse. Start commands belong in the Hermes conversation
that should receive your questions.

### Your existing Chrome

Use the unpacked extension beta to select tabs in your usual Chrome profile.
It keeps your existing sign-ins.

1. Run `/look setup extension` in Hermes.
2. Open `chrome://extensions` in the Chrome profile you want. Enable **Developer
   mode**, choose **Load unpacked**, and select the folder printed by setup:

   ```text
   ~/Library/Application Support/Look/extension/unpacked
   ```

   **Command–Shift–G** opens path entry in the macOS folder picker.
3. Review Chrome's **debugger**, **nativeMessaging** and **tabs** permissions.
   **Debugger access is broad page access, not just the element you point at.**
   Chrome keeps its debugging banner visible.
4. Run `/look start --extension` in your intended Hermes conversation. Within
   120 seconds, open **Look** from Chrome's Extensions menu on an ordinary HTTP(S)
   tab and choose **Connect this tab**.
5. Return to the page and [ask your first question](#your-first-question).
   For another tab, open Look there and choose **Use on this tab**.

Setup prepares the files but does not install or enable the extension for you.
There is no automatic extension update.
[Extension setup, updates and recovery](docs/CHROME_EXTENSION.md).

<details>
<summary>Existing Chrome without an extension</summary>

The native-consent beta requires stable Chrome 145 or newer. That is a protocol
floor, not a verified version matrix. Use current stable Chrome.

Open `chrome://inspect/#remote-debugging` and enable remote debugging. In Hermes,
run `/look start --existing`, read the disclosure, then run
`/look start --existing --accept` if you agree. Approve the native Chrome request
you just initiated. Use regular HTTP(S) tabs in that authorized profile.

This grants broad debugger access, including signed-in pages. It does not
silently switch to a separate browser if connection fails. After `/look stop`,
turn off remote debugging in Chrome if you no longer want it enabled.
[Connection, consent and limits](docs/REFERENCE.md#use-my-existing-chrome).

</details>

### A separate Look browser

Run `/look start --separate` in Hermes. Look launches or reuses a dedicated Chrome
profile, separate from your ordinary sign-ins. Open a page there and ask a question.

This profile persists. Only sign in if you want the account retained there.
`/look stop` leaves its browser and local debugging port running until you exit
that Chrome instance. Do not forward the port or give it to Hermes's generic
browser tools.

## Try eye tracking

Start with a useful cursor answer, then try looking at broad regions of a page.
Eye tracking is optional and experimental, not a precise pointer replacement.

1. Run `/look setup eyes` on first use. This explicitly permits about 11 MB of
   downloads and opens Look's separate camera window. Allow its camera access
   when prompted. Later, `/look calibrate` uses verified cached files.
2. Maximize the camera window at 100% zoom. Choose **Start calibration**.
   Look at each dot, tap **Space**, and keep looking until it moves.
3. After nine accepted points, choose **Start accuracy check**. A new calibration
   is saved only if its check passes.
4. Choose **Return to browsing** or **Skip practice**. Move the pointer once on
   each page to establish its position, and again after zooming or resizing.
5. Look at a broad page region and ask. Use `/look cursor` to turn off the camera
   and return to pointer input.

Use good light and one display. Recalibrate after changing posture, camera or
glasses. No real-camera population accuracy has been established.
[Calibration, practice and limitations](docs/WEBCAM_GAZE.md).

## Reading and accessibility

You can type instead of speaking and use the pointer instead of eye tracking.
The cards respect reduced-motion and reduced-transparency preferences.

For local read-aloud, quit Hermes and run:

```sh
hermes look setup-speech
```

This explicitly downloads the English Phonon voice, about 65 MB plus voice files,
without playing sound. Restart Hermes and choose **Read aloud** on an answer.
Automatic reading starts off. [Speech details](docs/REFERENCE.md#optional-read-aloud).

**This beta is not an accessibility guarantee or a hands-free browser.**
Action approval requires a primary mouse click. Eye tracking is experimental,
and screen-reader compatibility has not been established by the release evidence.

## Privacy and control

- **Local sensing, configured-model answers.** Questions and bounded page evidence
  go to your Hermes model. Hermes can retain that evidence in `state.db` even with
  plugin replay recording off. Provider retention depends on your provider.
- **Camera and audio.** Live eye images and features stay local. Calibration is
  sensitive and saved locally. The microphone opens only while talking. Failed
  recordings may remain in memory for retry. The MLX recognition fallback uses
  a temporary WAV that can remain after a crash or deletion failure.
- **Downloads and extra inference.** Registration does not download models.
  Explicit setup fetches pinned assets. Optional TypeSafe early highlighting sends
  the question and static scope descriptions when its key is configured. Additional
  page text is opt-in and off by default.
- **Private cards.** Website scripts cannot read the card's words or typed input.
  This boundary does not protect against other debuggers or malicious same-user
  or root software. Connected conversations use guarded tools instead of raw code,
  terminal, generic browser and delegation tools.
- **Actions need care.** Protected review cards require your mouse click for Send,
  Buy, Delete and ambiguous controls. Typing and navigation can themselves have
  effects on some sites. Password, payment and other secret fields are unsupported.
  Cross-origin frames, canvas, unknown widgets and detached targets can be unavailable.

`/look stop` ends local capture, tracking, read-aloud, overlays and approvals.
It leaves tabs open and cannot undo changes. Disconnect is not request cancellation;
use **Stop request** before disconnecting. Look's browser and microphone ownership
is shared across conversations on this Mac. [Security policy](SECURITY.md).

## Troubleshooting, updates and removal

Use `/look status` for connection state and `/look diagnostics` for technical
details. Failure cards offer **Try again**, **Skip** and **Continue with the rest**.
Do not automatically resend a question or action with an unknown outcome.

Before updating, stop Look, quit every Hermes process using it and run
`hermes gateway stop`. Reinstall the reviewed new commit with `--force --ref`
and restart Hermes. For the extension, rerun `/look setup extension`, **Reload**
Look in Chrome and pair again. `hermes pm install` repairs dependencies, not Look
code or speech models.

To remove Look, stop it and run `/look setup extension uninstall` if you set up
the extension. Remove Look in Chrome before removing the plugin:

```sh
hermes plugins remove hermes-gaze
```

Removal leaves Hermes/provider history, model caches, calibration and the separate
Chrome profile and sign-ins intact.
[Data locations and selective removal](docs/REFERENCE.md#daily-use-updates-and-removal).

## Explore the project

[Technical reference](docs/REFERENCE.md) · [Contributing](CONTRIBUTING.md) ·
[Release evidence](docs/RELEASE_READINESS.md) · [Changelog](CHANGELOG.md) ·
[MIT licence](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)

The plugin's install/config name remains `hermes-gaze`. `/gaze` and `hermes gaze`
remain aliases. Historical plans and pitches in `docs/` are background, not current
installation instructions or accuracy claims.
