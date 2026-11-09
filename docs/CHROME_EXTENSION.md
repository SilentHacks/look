# Look Chrome extension — local development

Alternative to [native Chrome consent](../README.md#use-my-existing-chrome).
Stock Hermes stays unmodified. This is an unpacked development installation,
not a Chrome Web Store release or a production-security certification.
Initial lane: Apple Silicon macOS, Google Chrome 145+, regular HTTP(S) tabs.

## Install explicitly

Use the same stable Look checkout and Python environment that run the plugin.
Do not move/delete either while this native host is registered.

1. Install/enable Look in stock Hermes as described in the README. Restart Hermes
   after updating the plugin. Its existing input permission is still required.
2. In the intended Chrome profile, open `chrome://extensions`, enable **Developer
   mode**, choose **Load unpacked**, and select this checkout's `extension/`
   directory. Copy **Look**'s 32-letter extension ID from that page.
3. From this checkout, using the plugin environment's Python:

   ```sh
   /absolute/path/to/venv/bin/python browser/extension_host.py install --extension-id THE_EXACT_EXTENSION_ID
   ```

   This explicitly writes only Look's user-level launcher/configuration under
   `~/Library/Application Support/Look/extension/` and its exact-origin
   `org.look.companion.json` registration under
   `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`.
   No sudo, Chrome settings changes, profile copy, Hermes patch or automatic
   extension installation. Importing Look does not install anything.

Chrome requires **debugger**, **nativeMessaging** and **tabs** permissions. The
Debugger API grants broad page access, not read-only/pointed-element permission;
Chrome's debugging banner remains. The extension has no content scripts, host
permissions, externally connectable API, web-accessible resources, cloud relay
or model-accessible debugger interface. Disabling remote debugging is fine:
this connection does not use its setting, port or discovery file.

## Connect to a conversation

1. In the intended running Hermes conversation, stop any previous Look connection
   with `/look stop`, then run **`/look start --extension`**.
2. In Chrome, return to an ordinary web tab, open **Look** from the Extensions
   menu, paste that command's pairing ticket, and choose **Connect this tab**.
3. Return to the page. `/look status` reports readiness. Point and hold Space;
   wait for **Listening** before speaking. The configured compose shortcut also
   opens the existing private typed-input card.
4. For another tab in this Chrome profile, open Look there and choose **Use on
   this tab**. Unselected tabs are not instrumented. Guarded new-tab operations
   retain the exact selected source window/profile; there is no all-tabs grant.

The ticket selects the particular running Look instance and the conversation /
Hermes profile that issued it. It expires after 120 seconds, is consumed once,
and is not saved by the extension. Do not share it or paste it as a model
question. It cannot resume a disconnected generation. The native port pins the
Chrome extension-profile instance; the extension ID alone is **not** a Chrome
profile identity. A same-user debugger or malicious local program is outside
this website/other-user isolation boundary, just as for the native-consent lane.
Look's browser/microphone owner is machine-scoped: stop it before choosing a
second runtime or conversation.

Only the focused selected tab's protected renderer receives new private content.
Python retains evidence and action policy: captured identity, connection/document/
route/task epochs, exact user turn, risk classification and single-use protected
mouse approval. Neither the extension popup, page text nor the model approves an
action. Page evidence you ask about goes to your configured model and may remain
in Hermes history. Browser attachment does not prove provider, audio or gaze
readiness. Camera/microphone setup remains a separate explicit choice.

## Stop, recover, update, uninstall

- `/look stop` or **Disconnect** ends the paired generation, cancels local
  capture/output/tasks/approvals, removes overlays and detaches. User tabs and
  Chrome stay open. Stop cannot cancel an already admitted Hermes model turn.
- Host/worker/port loss and Chrome debugger detach are terminal. No reconnect,
  reattach or action replay. A missing mutation reply means **unknown outcome**;
  inspect the website before issuing another action.
- The page's four-second Python-renewed input lease expires even if cleanup
  cannot run; it removes the surface and releases intercepted input. The worker
  also ends the connection when Python stops responding. Background renewals carry
  only liveness, never private renderer content or action authority.
  Native recording checks tab/window focus through a fixed browser-API operation,
  not a background page evaluation. Slow checks remain unknown; definite loss cancels.
- DevTools, Chrome's Stop banner, another debugger, tab close/move, browser policy,
  extension disable/reload/update, and restricted embedded frames can end access.
  Look does not work around Chrome policy or attach another tab as a fallback.
- After a failure: `/look stop`, fix the reported setup/Chrome problem, then
  `/look start --extension` and pair again. Old approvals and tickets stay dead.
- Update in place only while stopped: update Look, reload its unpacked extension,
  restart Hermes, and pair afresh. If the checkout or Python environment moves,
  uninstall then run the install command from the new location. Reinstall also
  after the unpacked ID changes. Existing registration is never silently replaced.
- To uninstall, first `/look stop` and **Disconnect**, then run:

  ```sh
  /absolute/path/to/venv/bin/python browser/extension_host.py uninstall
  ```

  Remove Look in `chrome://extensions`. The command removes only Look's exact
  native registration/configuration/launcher; no browser directory or data.
  Removing the registration alone does not terminate an already running host.

The native-consent option remains `/look start --existing` then
`/look start --existing --accept`. `/look start --separate` explicitly selects
Look's separate browser after Stop. No source is substituted silently.

## Reviewer checks and limits

```sh
python -m unittest tests.test_extension tests.test_chrome_consent tests.test_profile_highlight tests.test_first_run
node tests/extension_worker.cjs
python tests/extension_chrome.py --chrome '/absolute/path/to/Chrome for Testing executable' --out /tmp/look-extension-evidence
```

Observed on 2026-11-09: **42 Python tests**, the Node ownership-race checks and
**54 named headless browser checks** passed, including native-host loss,
worker reload, pending-approval cancellation and a deliberately lost mutation
reply with exactly one execution. The settled private answer was inspected
visually. The browser was official Chrome for Testing **157.0.8103.50**, mac-arm64:
[Google archive](https://storage.googleapis.com/chrome-for-testing-public/157.0.8103.50/mac-arm64/chrome-mac-arm64.zip),
196,583,703 bytes, SHA-256
`aceb0578a1cc3631358b164dbbef04bf8936f96c690fb78c3ac25b7655e795e8`.
Archive size/checksum matched the preceding research run; no verified bundle
signature, system installation or personal-browser trial is claimed.

One independent GPT review found three P1 defects: late tab creation crossing a
replacement pairing, cached activation across a window-state await, and background
evaluation blocking recording-loss detection. All three were corrected and covered
by deterministic race checks plus real-browser native-watchdog cancellation with
page focus-loss listeners suppressed. No second review or production acceptance
claim is implied.

The browser probe creates its own temporary profile, native-host registration,
local pages and a test-only extension driver/inspector. The shipped extension
has neither its automatic fixture pairing nor its raw inspector operations.
No remote-debugging flag/pipe/setting, real device, account, provider request or
installed-Hermes mutation is used. Fake device objects exercise cancellation,
not physical hardware. The registered plugin and real native host/transport are
used; model admission is a local frontend stub, not a real model call.

Headless browser API focus is not headed macOS foreground acceptance. Physical
input, personal signed-in tabs, multiple real Chrome profiles/windows, managed
policies, coexistence with other extensions, actual disable/update/Chrome-banner
UX, real devices and Store distribution still need user-operated acceptance.
Do not interpret these development checks as those trials.

Runtime needs no cloud relay or extension subscription. Existing model/audio/
tracker costs remain. Store registration/review and consumer packaging are not
implemented; no Store approval or publication is claimed.
Development verification made no paid product/provider calls or Store purchases.
Assistant/reviewer model billing is not exposed.
