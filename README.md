<div align="center">
  <img src="assets/look.png" width="112" height="112" alt="Look icon">
  <h1>Look</h1>
  <p><strong>Point at something in Chrome. Ask Hermes about it.</strong></p>
</div>

Look is an open-source [Hermes Agent](https://github.com/NousResearch/hermes-agent)
plugin. Ask about a paragraph, table cell or page control without copying it into
chat. Answers and follow-ups stay in a private card beside the page.

**Source beta for Apple Silicon Mac.** Use one display, native arm64 Python
3.11–3.14, current stable Google Chrome in Applications, Git and Hermes 0.22.0
or newer with a model configured. Start with a non-sensitive page.

## Install

Run interactively in a terminal. Review the scanner findings and dependency
preparation before agreeing:

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

Speech recognition and eye processing stay local. With an optional TypeSafe key,
highlighting also sends your question and scope descriptions to TypeSafe.
Additional page evidence is opt-in.

Website scripts cannot read the cards or typed questions. Other debuggers and
malicious local software are outside that protection. Browser actions can change
sites, including through typing or navigation. Password, payment and other secret
fields are unsupported. Some frames and custom controls are unavailable.
Screen-reader compatibility is unverified.

[Guide: recovery, updates and removal](docs/REFERENCE.md) · [MIT licence](LICENSE)
