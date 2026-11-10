# Changelog

## 0.1.0: unreleased source beta

No public release, catalogue admission, Store listing or release date is asserted.

- Eye tracking now stays in its owned camera window when browsing destinations
  disappear or reattach, while the approved browser connection remains live.
  An explicit separate-browser start-page fallback becomes the next return target.
  Disconnect, browser replacement, Stop and Use cursor still revoke the camera.
- Fixed macOS toolbar-popup connection rejection when the focused popup leaves
  its ordinary owner window unfocused. Selection uses that popup's exact window;
  normal page-action foreground checks and one-use connection consent remain.
  Added headed disposable-Chrome coverage for actual popup pairing, two windows,
  restricted/incognito exclusion, expiry recovery and staged updates.

- Native-host transport loss no longer risks Python aborting at shutdown while
  Chrome's input pipe remains open. Input framing and terminal-loss handling stay
  unchanged; the reader uses unbuffered stdin.
- Removed the native-consent start command. Use the extension for your usual
  Chrome or `start --separate` for Look's browser.
- Added connection-scoped `/look actions allow-all` to execute requested actions
  without Look approval prompts. Default review, captured ownership, secret-field
  exclusions and no-replay handling remain. Stop and reconnect restore review.

- The extension popup refreshes pending connection state without retargeting an
  offered conversation or tab. Expiry and foreground changes remove Connect.
  Browser connection no longer advertises speech while recognition is preparing;
  the protected page announces completed cache warmup/setup without a host-message API.

- Installation now uses the public `SilentHacks/look` repository at an
  anonymously verified immutable commit. Documents stock Hermes profile setup,
  installation limits and the need to refresh the pin after local fixes are published.

- Streamed answer cards reserve viewport-bounded reading room for long answers
  while keeping short answers compact and preserving top/manual scroll.
- Extension navigation recovery uses trusted Python read/presentation/mutation
  authority, decodes Chrome's wrapped context errors and pins renderer rearm to
  its document. Classified reads reject side effects; private UI can recover.
  Mutations, missing replies and host/debugger failures retain terminal/no-replay
  handling. Added repeated redirect/answer and in-flight navigation regressions.
- Added request-specific **Stop request** controls for active and queued questions.
  Stock canonical Hermes cancellation keeps exact receipt ownership, partial text
  and paused follow-ups. Other frontends report that processing must be stopped
  in Hermes. In-flight browser actions are not rolled back or replayed.
- Refreshed help, setup, settings, error messages and current user guides.
  Privacy disclosures, user choices and browser-action safeguards are unchanged.
- Grouped audio, runtime and browser internals into packages while keeping the
  stock plugin entry point and manifest at the root. Updated source paths in
  contributor guidance, asset notices and technical documentation. Removed the
  obsolete root redirects to historical documents, which remain in `docs/`.

- Look provides exact cursor evidence, private streamed cards, local voice input,
  guarded captured-control actions and experimental personal eye calibration.
- Browser lanes: separate Look Chrome and an unpacked extension/native host.
  `/look setup extension` stages fixed source files and the current Python
  launcher with a stable development ID. Stopped update, relocation, scoped
  removal and cross-profile ownership are covered.
- The approved Look artwork brands the README, Chrome extension/action, popup and
  separate-browser start page. Transparent PNG icons ship with extension setup.
  The private companion cards and controls remain icon-free.
- Extension connection is no-paste: `/look start --extension` approves one
  120-second request. **Connect this tab** consumes it through private local
  discovery. Stale popups, competing profiles, Stop and transport loss cannot
  transfer the selected native port or silently reconnect.
- Release preparation separates onboarding from technical evidence. Adds
  contributor/security guidance, local submission copy and a scoped publication
  audit/isolated-install record. Historical pitch/playbook/scoreboard claims are
  labelled at their source.
- Stock Hermes local-pin validation, declined-preparation recovery, enabled-state
  discovery, isolated doctor registration and scoped removal were exercised on
  the baseline. See [versions, limits and remaining gates](docs/RELEASE_READINESS.md).
- Retired HUD probe automation and wording/source-spelling tests removed.
  Collector wire contracts exercise the actual JS producer. Live session probes
  require `--prompt-only` and self-contained Hermes dependencies, without private
  host dependency-state sharing.
- No-paste extension acceptance: 100 headless checks pass across eight scenarios
  on stable CfT 157.0.8103.50. The older CfT 145.0.7632.6 mouse-driver stall
  reproduces without Look. No product timeout, ownership or replay policy changed.
  Headed/device/provider acceptance remains user-operated.

Earlier measurements and design iterations remain in dated docs and Git history.
They are not current platform, hardware, provider or population-accuracy guarantees.
