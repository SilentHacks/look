# Look Chrome extension — source beta

Use selected tabs in your existing Google Chrome, with stock Hermes unchanged.
Supported lane: Apple Silicon macOS, current stable Google Chrome, regular HTTP(S) tabs.
This is an unpacked developer installation, not a Chrome Web Store release.

## Set up once

1. Install and enable Look in stock Hermes using the README. Restart Hermes after
   updating Look. In a Hermes conversation, run:

   ```text
   /look setup extension
   ```

   No Python path, extension ID or environment variable is needed. Setup copies
   Look's extension and stdlib native host to
   `~/Library/Application Support/Look/extension/`, and registers only
   `org.look.companion.json` in Google Chrome's user-level
   `NativeMessagingHosts/` directory. It uses that Hermes process's Python.
   Shell equivalent: `hermes look setup-extension` (unavailable in Hermes host
   isolation; use the slash command there).

2. In the Chrome profile you want to use, open **chrome://extensions**, enable
   **Developer mode**, choose **Load unpacked**, and select the folder printed by
   setup:

   ```text
   ~/Library/Application Support/Look/extension/unpacked
   ```

   In the macOS folder picker, **Command–Shift–G** accepts this path. Pin Look in
   Chrome's Extensions menu if you want it in the toolbar.

3. Review Look's permissions in Chrome. Look needs **debugger**, **nativeMessaging**
   and **tabs**. Debugger grants broad page access, not a read-only or
   pointed-element-only permission. Chrome's debugging banner remains.

Setup does not launch Chrome, change browser settings, install/enable an extension,
copy a profile, open a device, or patch Hermes. Installation and permissions remain
Chrome's user-controlled steps. Unmanaged macOS cannot use an unpublished local
CRX as a consumer-install shortcut ([Chrome distribution rules][distribution]).

The manifest's public `key` fixes the beta ID to
`onaibmgfpfkhhdmblanemokijinknifa`, independent of checkout location. It is a
public development identity, not a secret, profile identity, Store reservation or
publisher-authentication claim ([Chrome identity guidance][identity]). Do not
change it on updates. There is no Store listing or automatic extension update.

## Connect to this conversation

1. Stop any previous connection with `/look stop`. In the intended running Hermes
   conversation, run **`/look start --extension`**. This approves one connection
   for **120 seconds**; the existing Look input permission is still required.
2. On the desired ordinary web tab, open **Look** from Chrome's Extensions menu
   and choose **Connect this tab**. No ticket or second Hermes approval is needed.
3. Return to the page. `/look status` reports readiness. Point and hold Space;
   wait for **Listening** before speaking. The configured compose shortcut opens
   the private typed-input card. Microphone/speech setup is separate.
4. For another tab in this profile, open Look there and choose **Use on this tab**.
   Unselected tabs are not instrumented. Guarded new tabs retain the exact selected
   source window/profile; there is no all-tabs grant.

The command pins the issuing Hermes conversation/profile. Private local discovery
reveals only that pending generation to the popup; opening a popup cannot attach.
The click consumes it once and pins that popup's native port and foreground tab.
If two profiles click, only one can win; the other fails without attaching or
switching the winner. Stop before changing conversations or runtimes: Look's
browser/microphone owner is account-wide. An expired, cancelled or stale popup
cannot use a replacement request. Run `/look stop`, `/look start --extension`,
then reopen Look to connect again.

The extension ID is not a Chrome profile identity. The private capability stays
in the native transport, never the popup, clipboard, URL or website. There is no
auto-pairing, cloud relay or background reconnect. Same-user malicious code or a
debugger remains outside this website/other-user boundary.

## Update, move or remove

- **Update:** `/look stop` in every running Hermes process using Look; update the
  plugin, restart Hermes, and run `/look setup extension` again. In
  `chrome://extensions`, **Reload** Look, then pair afresh. Repeated setup is safe;
  it refreshes only Look's owned files and exact-origin registration. A live or
  waiting Look runtime refuses setup/removal. A conflicting registration or
  symlink is refused rather than overwritten.
  All browser sources now share the account-scoped runtime path
  `~/.cache/hermes-gaze/chrome-profile`, not Hermes-profile data. Restart every
  Hermes process when upgrading; earlier per-profile separate-browser folders are
  left untouched, not copied or deleted.
- **Moved checkout:** the staged extension/native host do not depend on its old
  source path. If Hermes's Python environment moves or is replaced, restart
  Hermes in the working environment and rerun setup to refresh the launcher.
  Do not move/delete the Python environment and expect an old launcher to work.
  The Chrome-loaded folder and extension ID stay fixed.
- **Migrating the older manual-ID beta:** stop Look, run
  `/look setup extension uninstall`, remove the old Look entry in
  `chrome://extensions`, and follow setup above. Setup refuses to silently switch
  an already registered, different extension ID.
- **Uninstall:** `/look stop`, then **Disconnect** if the popup is still connected;
  run `/look setup extension uninstall` (shell:
  `hermes look setup-extension --uninstall`). Remove Look in
  `chrome://extensions`. Repeating removal is safe. Only Look's exact native
  registration and managed files are removed; unknown files and browser data stay.
  Empty setup directories/the setup lock can remain. Removal alone cannot kill an
  already running host. To reinstall, rerun setup and Load unpacked again.

## Recovery

| Problem | Action |
|---|---|
| Popup asks for setup / native host unavailable | `/look stop`; rerun `/look setup extension` in the intended Hermes environment, Reload Look, then start and pair again. Use stable Google Chrome's normal user-data location; custom `--user-data-dir`, other channels and managed policies are not this setup command's supported lane. |
| Request used, cancelled or expired | Stop and start again in the intended conversation, then reopen Look on the desired tab. |
| Chrome refuses debugging | Choose an ordinary HTTP(S) tab in a regular window. Close DevTools/another debugger on that tab. Respect Chrome policy and its Stop banner; Look does not bypass them. |
| Setup refuses existing registration/files | Keep them intact. If they are your older Look install, use Look's uninstall first. Otherwise resolve the conflicting installation explicitly; do not delete another application's registration. |
| Setup interrupted / file access error | Stop Look, check access to the two documented user-level directories and rerun setup. Ordinary replacement failures restore previously replaced files; crash/power-loss recovery is rerunning setup. Do not edit Chrome profile preferences. |
| Browser connected but voice/model unavailable | Check `/look diagnostics` and the separate speech/input/provider setup. Attachment alone does not establish their readiness. |

Host/worker/port loss, debugger detach, extension disable/reload/update, selected-tab
close/move or restricted frames can end a generation. Stop cancels capture, output,
tasks and pending approvals, removes overlays and detaches; user tabs and Chrome
stay open. An already admitted Hermes model turn can still finish. The page's
four-second Python-renewed lease releases intercepted input even if cleanup cannot
run. No reconnect, fallback-tab attachment or mutation replay occurs. A missing
mutation reply means **unknown outcome**: inspect the website before another action.

The alternative without an extension remains `/look start --existing`, then
`/look start --existing --accept` with native Chrome consent. After Stop,
`/look start --separate` explicitly selects Look's separate browser. No source is
substituted silently.

## Privacy and ownership

Only the focused selected tab's opaque-origin, script-disabled private renderer
receives new private content. Python retains captured identities, connection /
document / route / task epochs, exact user-turn ownership, live risk classification
and single-use protected mouse approval. Neither popup, page text nor model can
approve an action. The extension has no content scripts, host permissions,
externally connectable API, web-accessible resources or model-accessible debugger
interface. It does not use remote debugging settings/ports/discovery files.

Page evidence you ask about goes to your configured model and may remain in Hermes
history. Native microphone permissions belong to Hermes, not Chrome. No browser
camera/microphone permission is requested by this extension.

## Verification and remaining gates

```sh
python -m unittest tests.test_extension tests.test_chrome_consent tests.test_first_run tests.test_companion_ownership
node tests/extension_worker.cjs
python tests/extension_chrome.py --chrome '/absolute/path/to/Chrome for Testing executable' --out /tmp/look-extension-evidence
```

The browser probe uses disposable Chrome for Testing profiles, temporary native
registration, local pages, a test-only worker driver/inspector and fake
frontend/device objects. It exercises real plugin registration, setup, native
discovery, competing profile clicks, expiry, Stop, stale requests and private
renderer/keyboard ownership. Automatic fixture pairing is not shipped; the actual
toolbar popup gesture remains a user-operated gate.

No-paste headless acceptance: **100 checks PASS** across eight scenarios, plus
**63 Python tests** and the Node ownership-race harness. Official mac-arm64
Chrome for Testing **157.0.8103.50** (stable at verification). Chrome 145 is a
protocol floor, not a verified compatibility matrix: CfT **145.0.7632.6** stalls
the probe's debugger `mouseMoved` command even without Look installed. That build
is not accepted here; headed/physical behavior on 145 is unverified. Use current
stable Chrome for the trial. See the [release evidence](RELEASE_READINESS.md#integrated-verification--2026-11-10).

Headless checks do not establish headed macOS foreground behavior, physical input,
signed-in acceptance, multiple personal profiles/windows, other extensions,
managed policy or actual Chrome permission/banner/update UX. Those remain
user-operated gates. Store publication additionally needs publisher-owned identity,
privacy disclosures, packaging, payment/registration and Google's approval; no
approval date or Store availability is promised. Native-consent Allow/deny/revoke
acceptance is separate.

Runtime has no extension subscription/cloud relay fee. Existing model/audio/tracker
costs remain. Development verification uses no paid product/provider calls or
purchases; assistant/reviewer billing is not exposed.

[distribution]: https://developer.chrome.com/docs/extensions/how-to/distribute/install-extensions
[identity]: https://developer.chrome.com/docs/extensions/reference/manifest/key
