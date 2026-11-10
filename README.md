<div align="center">
  <img src="assets/look.png" width="112" height="112" alt="Look icon">
  <h1>Look</h1>
  <p><strong>Point at something in Chrome. Ask Hermes about it.</strong></p>
</div>

Look is an open-source [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin. Ask about a paragraph, table cell or page control without copying it into
chat. Answers and follow-ups stay in a private card beside the page.

**Source beta for Apple Silicon Mac.** Use one display, native arm64 Python
3.11–3.14, current stable Google Chrome in Applications, Git and Hermes 0.23.1
or newer with a model configured. Start with a non-sensitive page.

## Install

Run interactively in a terminal. Review the scanner findings and dependency
preparation before agreeing:

This published pin predates the local catalog-readiness fixes. It is not the
submission candidate. Replace it only after the fixed commit is published and
anonymously verified.

```sh
hermes plugins install https://github.com/SilentHacks/look.git --ref 341c68b20ef689661b9d88f8bf23e213e5b25338 --enable
hermes config set plugins.isolation in_process
hermes config set plugins.entries.hermes-gaze.allow_gateway_injection true
hermes plugins doctor hermes-gaze --ci
```

For a named profile, use `hermes -p NAME` instead of `hermes` throughout.
Quit Hermes, run `hermes gateway stop`, then restart and open a new local TUI,
CLI or Desktop conversation.

## Connect and ask

Choose one browser. Run `/look` commands in the Hermes conversation that should
receive your questions. Your question and page evidence go to your configured
model and may remain in Hermes history.

### Your usual Chrome

1. Run `/look setup extension` in Hermes.
2. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**
   and select:

   ```text
   ~/Library/Application Support/Look/extension/unpacked
   ```

   **Command–Shift–G** opens path entry in the folder picker.
3. Review **debugger**, **nativeMessaging** and **tabs** permissions.
   Debugger permission grants broad page access, including signed-in pages,
   not just what you point at.
4. Run `/look start --extension`. Within 120 seconds, open **Look** from Chrome's
   Extensions menu on an HTTP(S) tab and choose **Connect this tab**.

For another tab, choose **Use on this tab** in Look.

### A separate Look browser

Run `/look start --separate`, then open a page in the dedicated Chrome window.
Its profile keeps any accounts you sign into. It exposes a local debugging port.
Do not forward that port or share it with other browser tools.
`/look stop` leaves this Chrome instance and its port running until you exit it.

### Ask your first question

Point at text or a table cell. Press **Right Option**, type “What does this mean?”
and submit. Follow up on the answer card, or point elsewhere for a new question.
**Q** recalls answers. **Esc** stops or dismisses the current interaction.
`/look stop` disconnects Look without closing tabs.

### Browser actions

Look asks for approval before sending, buying, deleting or using an ambiguous
control. Run `/look actions allow-all` to execute requested actions without Look
approval prompts for this connection. This can send, buy or delete immediately,
including if page instructions mislead the model. `/look actions confirm` restores
prompts. Stopping or reconnecting resets the mode.

## Optional voice and eyes

- **Speak:** run `/look setup` to download local English recognition. Grant
  microphone access to the app launching Hermes, not Chrome. Hold **Space**, wait
  for **Listening**, speak and release. Text fields keep normal Space behavior.
- **Listen:** quit Hermes, run `hermes look setup-speech`, then restart and choose
  **Read aloud** on an answer.
- **Eye tracking:** run `/look setup eyes`, allow camera access in its separate
  window and follow calibration. It is experimental, not a precise pointer
  replacement. [Calibration guide](docs/WEBCAM_GAZE.md).
  `/look eyes` activates saved calibration after reconnecting or using the cursor;
  `/look cursor` stops the camera. `/look status` shows the selected source and
  whether fresh gaze is reaching a page.

## Privacy and limits

Speech recognition and eye processing stay local. Questions and bounded page
evidence go to your configured model, including an auxiliary scope-selection call
when needed. Those calls can incur provider costs and remain in Hermes/provider
history. Optional TypeSafe highlighting sends the question, pointer structure and
scope descriptions to TypeSafe. Page text is opt-in. TypeSafe can add service
costs. Its retention policy has not been verified.

Website scripts cannot read the cards or typed questions. Other debuggers and
malicious local software are outside that protection. Browser actions can change
sites, including through typing or navigation. Password, payment and other secret
fields are unsupported. Some frames and custom controls are unavailable.
Screen-reader compatibility is unverified.

## Installation disclosures

- Registration starts a background GET-only demo/status server at
  `127.0.0.1:9111` and cache-only speech warmup. Connected sessions keep browser,
  input and speech workers running. There is no Look telemetry service.
- Look reads the connecting Hermes profile's permission/isolation config and uses
  a same-user local socket and one-use session ticket. Extension setup writes
  reviewed extension files, a Python native host and Chrome native-messaging
  registration under your user account. It does not read vendor login stores.
- Separate-browser and eye modes launch Chrome processes. Speech may launch
  `ffmpeg` to decode audio or macOS `/usr/bin/say` before playback starts.
  Python/native dependencies are installed separately through Hermes.
- Explicit setup downloads public, pinned, checksum-verified assets anonymously
  from Hugging Face and its storage redirects: FluidInference's NVIDIA Parakeet
  CoreML conversion (465 MB), mlx-community's MLX fallback (2.47 GB), SYSTRAN's
  OpenAI Whisper fallback (148 MB, or 78.1 MB for tiny.en), and Gradium's Phonon
  read-aloud model (65 MB plus about 0.26 MB per voice). Eye setup fetches Google's
  MediaPipe runtime from npm (6.6 MB compressed) and Face Landmarker from Google
  storage (3.76 MB). These are downloads, not hosted speech or eye inference.
  Converter-owned CoreML/MLX catalog source-policy acceptance is unresolved.
- Optional `parakeet-v3` recognition downloads NVIDIA's Parakeet v3 Q8 GGUF
  (714 MB) and official NeMo-Speech.cpp v0.3.0 Metal runtime (7.24 MB compressed)
  from Hugging Face and GitHub. It starts a local Python/native worker with no
  network listener; audio crosses a private pipe, not a temporary recording.
  It is not the default. [Setup, benchmarks and provenance](docs/PARAKEET_V3.md).
- Local storage includes shared model caches, sensitive biometric calibration,
  extension/native-host files and the separate Chrome profile with any sign-ins.
  The MLX fallback uses a temporary WAV, deleted after transcription where
  possible. A crash or deletion failure can leave it behind. Development-only
  `record_trials`, off by default, writes page evidence to local replay logs.
  Removing the plugin does not erase these files, Hermes history or provider
  records.

See [download provenance and sizes](docs/REFERENCE.md#runtime-downloads),
[removal and retained data](docs/REFERENCE.md#daily-use-updates-and-removal) and
[third-party terms](THIRD_PARTY_NOTICES.md).

[Guide: recovery, updates and removal](docs/REFERENCE.md) · [MIT licence](LICENSE)
