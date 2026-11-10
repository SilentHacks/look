# Navigation recovery and evaluation authority

Baseline: `56e38d2a85c5f6c11d687cdce7e254402034fa4d`.

## Failure and boundary

The disposable extension probe reproduced a terminal `Runtime.evaluate` failure on
its second same-tab redirect after answering on the first destination. Chrome's
extension debugger reported `Cannot find context with specified id` inside a JSON
protocol error string. The earlier fixed frame-tree/lease matcher neither covered
concurrent focus/render evaluations nor decoded this wrapper.

Only trusted Python assigns `_look_operation` on the private native channel. The
worker removes it before calling Chrome. Page text, model output and renderer
messages cannot supply this authority. Missing classification defaults to
`mutation`; invalid classification is refused. No expression-text heuristic exists.

| Authority | Allowed recovery | Replay |
|---|---|---|
| `read` | Explicit missing context rejection returns an error to the caller. Chrome's `throwOnSideEffect` enforces read-only evaluation. | Worker never retries. Explicit read API alone may use the existing transport reconnect path; approved extension/consent generations cannot reconnect after loss. |
| `presentation` | Explicit missing context rejection returns an error; bounded rearm or later Python-owned state publication can restore private UI. | No evaluation retry. This is idempotent private UI/lifecycle work, not a read or browser action. |
| `mutation` | Rejection/lost reply remains terminal after dispatch. | Never. `eval_js` and `eval_js_once` both default to this authority. |

Timeouts, missing replies, debugger/host/port loss and unclassified protocol errors
remain terminal for all three authorities. The existing fixed `Look.focus` probe's
unknown-on-timeout behavior is unchanged. No lease or command deadline increased.
The worker accepts only exact explicit missing-context/frame/object error messages,
plain or wrapped with protocol code `-32000`; it never retries a command.

## Evaluation caller audit

All product evaluations route through `CdpSession._eval_coro` or the one direct
`_send_cmd` frame-object read in `_init_ui`. The separate explicit camera process
in `browser/webcam.py` has its own transport and is unchanged; it does not use the
extension worker. Benchmark/test inspector evaluations are not product authority.

| Caller | Authority and reason |
|---|---|
| `CdpSession.eval_js`, `eval_js_once`; `GazeSession` and `Companion` generic forwarding | Mutation by default, including arbitrary JS supplied by trusted callers. Only an explicit Python read opts into read reconnect semantics. |
| `Companion._target`, `_watch`, `_display_pending` focus predicates; `_navigate` destination-ready predicate; `_return_from_calibration` panel/focus predicates; non-extension `recording_loss` | Read, with side-effect rejection. Extension recording ownership still uses fixed `Look.focus`, not website JS. |
| `_on_new_context` overlay-presence check; `_init_ui` frame-object lookup | Read. |
| `_on_new_context` overlay installation; `_init_ui` panel installation / `uiReady`; `_push_overlay_config` | Presentation. Configuration/nonce stays isolated; each rearm pins its document through setup and verifies it before marking ready. Duplicate rearm of an already-ready document does not replace its renderer. |
| `_render_ui`, `push_level`; `Companion._display_pending` inbox/task publication; calibration-return UI | Presentation. Only private renderer state/geometry changes; existing foreground/context/route checks remain. |
| `_ui_message` fixed `size`, `hover`, `engaged` frame notifications | Presentation. Python selects these three branches; they update geometry/reading timers only. |
| `_ui_message` other `fromPanel` traffic, including keys, submit, links, approval and controls | Mutation. No downgrade based on renderer-provided authority fields. |
| `_deliver_reply` / `onIntentResult` | Mutation: some responses emit a further explanation intent, so the general callback is not declared idempotent. |
| `_revoke_route_actions` | Presentation: removes authority/confirmation, never grants it. |
| `_shutdown_overlay` / destroy; non-extension fixed transport ping | Mutation default; shutdown and separate-browser transport behavior unchanged. Extension lease remains a fixed worker operation. |
| `Companion.capture`, navigation action capture; `SnapshotActions`; `BrowserTasks`; service table extraction/highlight/scope; `GazeSession` pins, resolution, webcam sample delivery | Mutation default. Capture routines update identity/confirmation caches; generic action dispatch can write/click/press/scroll. These paths are deliberately not blanket-classified as reads/UI. |

Fixed `Page.getFrameTree`, `DOM.describeNode`, `Runtime.releaseObject`,
`Page.createIsolatedWorld` and `Look.lease` can also return an explicit disappearing
frame/context/object rejection. These are lifecycle operations, not navigation or
input commands. `Page.navigate` and `Input.dispatchKeyEvent` remain mutations.

## Ownership and privacy

Classification never bypasses selected-tab foreground, window/profile, exact native
port/session, document, route or isolated-context ownership. A stale classified
frame is refused before evaluation. A result whose context/document/route or focus
revision changed in flight is discarded; an in-flight mutation ends the generation
rather than being treated as safely repeatable. An old generation cannot reply to
or stop a replacement port. Private content still goes only to the focused selected
tab's opaque, script-disabled frames. No website/main-world evaluation was added.

This is bounded navigation recovery, not a seamless-navigation or site-specific
guarantee. A concurrent genuine mutation can still disconnect during navigation;
inspect its outcome and explicitly reconnect rather than repeating it automatically.

## Disposable checks

`tests/extension_worker.cjs` exercises plain/wrapped context errors, classification,
side-effect enforcement parameters, stale in-flight results, foreground refusal,
debugger loss and terminal mutations without replay.

`tests/extension_chrome.py --mode navigation` uses local redirects, fresh documents,
scripted answers after each rearm, read side-effect refusal, stale action owners and
a hostile source that suppresses focus events. `--mode navigation-mutation` starts
one real local POST and navigates before its unresolved evaluation replies; the
connection must terminate and never issue a second POST. `--mode lost-reply` and
`--mode host-loss` retain the unknown-outcome and teardown checks.

No personal profile, account, physical device, provider inference, live Hermes
host modification or push is needed. Headed native focus, toolbar permissions,
physical speech and configured-provider behavior remain user-operated gates.
