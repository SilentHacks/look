# Release freeze investigation — 2026-11-08

## Finding and limits

Inbox publication was not a protected-frame render barrier. The ordered service
worker could enter native shutdown while the second CDP hop was still pending.
A blocking fake reproduces this exact ordering failure; acknowledgement of the
release's own protected capsule render removes it. This does **not** establish
which operation stalls on the user's physical Mac, nor that `b569aec` introduced
that physical stall.

No real microphone, webcam, speakers, Hermes process, model or user Chrome was
used. Private Chrome runs were headless, temporary-profile, port-zero instances.

## Historical comparison

- `7995489`: `Microphone.stop()` detached input, disabled callbacks, copied PCM,
  then called `before_stop=reserve` before native `stop()`/`close()`. Its microphone
  RLock remained held through publication and shutdown. Publication could take
  the inbox RLock; a rebind took that inbox lock before cancelling the microphone.
  That was a real inverse lock order. PCM append was not protected against a
  callback already past its acceptance check.
- `86e17bd`: the release service, overlay, microphone and timing path remained the
  same. The merge changed webcam feature extraction/estimation, not the release
  ordering. The camera's estimator runs in its own worker, not synchronously from
  Space keyup. Release does synchronously ingest frozen webcam fixations.
- `b569aec`: callback PCM/status/epoch moved under a short `_audio_lock`, ahead
  of metering. Stop detached input and raised `_closing` under the microphone
  RLock, waited for an admitted callback, disabled acceptance and detached the
  bytearray, then released **both** locks before publication/native shutdown.
  The close gate lasted through shutdown. Heartbeats became lazy, weak-reference
  owned, retired when idle, and stopped on disconnect/reload. None of these changes
  inserted native stop before publication. The private-render race existed in
  `7995489` too; this investigation does not label `b569aec` its origin.

## Statement-order trace before this fix

Lock waits and ordinary blocking Python I/O release the GIL. Executing Python
collection, serialization, scoring and callback code holds the GIL between normal
interpreter scheduling points. Native calls need separate evidence: a Python
wrapper alone cannot establish whether its FFI/native implementation retains the
GIL. The GIL-holding fake below is a deliberate stress case, **not a measurement
of PortAudio or CoreML**.

1. `overlay.onWindowKey` receives trusted Space keyup, clears hold/tap state and
   calls `holdEnd`. This is Chrome JavaScript; there is no Python lock or GIL.
2. `holdEnd` finalizes tentative pointing targets, removes tentative rings,
   clears gaze/hold state, rejects too-short/cancelled holds, chooses follow-up
   versus new question, and computes the bounded subject.
3. `stopListening` clears listening/meter state; freezes cursor or noisy evidence
   synchronously; binds local pending ownership; assigns the intent ID and nonce;
   serializes and emits `record_stop`. DOM capture, hit tests/layout and JSON work
   here can stall Chrome. Browser evidence start/frozen/sent offsets isolate it.
4. Only **after** emitting stop, `holdEnd` hides the waveform, updates the local
   capsule/placement, emits `_ui_render`, and sends coach persistence. Springs,
   ring motion and timers remain browser-local. Private-frame words still require
   Python to forward the render over CDP; they are not in the website DOM.
5. The per-tab CDP asyncio pump receives `Runtime.bindingCalled`, validates the
   exact isolated context, stamps document/route, begins timing, then submits the
   service handler to its **single ordered worker**. An earlier intent can delay
   admission. The pump itself does not wait for that worker.
6. `Companion._dispatch` stamps the source tab in thread-local ownership. Service
   checks the nonce and owner, extracts frozen evidence, picks mode and creates
   `reserve`. No model or camera prediction occurs at this step.
7. `Microphone.stop` acquires the microphone RLock, checks exact owner, detaches
   stream/owner, raises `_closing`, then acquires `_audio_lock`. A callback already
   admitted can delay this acquisition. While holding both locks it disables new
   acceptance, detaches PCM and snapshots epoch/error. No native I/O occurs here.
   Both locks are released before the next step.
8. `reserve` validates hover evidence. In noisy modes it calls
   `clear_hover_snapshot`: microphone cancel sees the already detached stream;
   action invalidation takes the action RLock, then session clearing takes the
   session RLock. A pending approval may add a CDP round trip.
9. Connected reservation calls `resolve_now` synchronously. Hover runs the pure
   bounded cursor resolver, then `is_chrome_reachable` performs an HTTP health
   read with a 1.2-second timeout. Noisy modes parse candidates, `session.ingest`
   takes the session RLock to normalize/dedupe frozen fixations, and Bayesian
   resolution constructs context. The webcam estimator is not called here;
   independent webcam ingestion can contend for session/companion/CDP resources.
10. `VoiceTurns.capture` acquires the inbox RLock (including the connected check),
    validates size, serializes/copies frozen evidence, reserves capture order,
    invalidates action approval under the action RLock, appends a transcribing run,
    and calls `publish` while holding the inbox lock. No microphone lock is held.
11. `publish` builds versioned inbox state, then `Companion.display` takes its
    RLock to cache it and select the source tab. On the ordered source worker,
    thread-local ownership avoids a focus scan; otherwise `_target` can do CDP
    focus reads. Display then checks foreground and delivers `onSessionEvent`
    with synchronous CDP waits (0.5/1-second evaluation timeouts). The display
    caller still holds the inbox lock. `Companion.display`'s outer RLock also
    covers `_target` if a foreground scan is needed.
12. `onSessionEvent` updates overlay state and emits another `_ui_render` binding.
    Its `Runtime.evaluate` acknowledgement only says the overlay callback ran.
    It does **not** wait for `_ui_message -> _render_ui -> panel.render` in the
    protected iframe. Those are separate asynchronous tasks/round trips.
13. `capture` returns; service marks reservation and sends `record_reserved` through
    another synchronous overlay reply. That acknowledgement likewise need not wait
    for the protected render. The inbox lock has been released at this point.
14. `Microphone.stop` enters native `stream.stop()` then `stream.close()` under
    neither microphone, PCM nor inbox lock. `_closing` excludes new native input.
    Exceptions still run close; outer `finally` clears `_closing` under the
    microphone RLock. Only then are sealed PCM bytes returned. A GIL-holding
    native call here can prevent the pending private-render task from running.
15. Service publishes capture idle; queues transcription. Connected transcription
    runs on a daemon, serialized by `_TRANSCRIBE_LOCK`. That worker can wait for
    CoreML's loader/warmup lock and execute native inference; fallback backends
    have their own loader work. None should determine initial release feedback.
    Transcription later resolves frozen evidence again, updates the reserved run,
    highlights and admits the Hermes turn. First matching text delta ends timing.
16. Independently, the CDP pump schedules `_ui_message` on render bindings;
    `_render_ui` issues the protected iframe evaluation and awaits its response.
    Only this response is a completed protected UI push. Chrome painting follows;
    a CDP acknowledgement is not proof of a compositor paint.

## Cutover

The local release render now carries its existing intent sequence ID. The
transport associates that ID and captured document with a private Event, kept
out of serialized intents and timing output. After PCM sealing, `reserve` waits
without any microphone, PCM, inbox, action or session lock. Only a successful
render in that release's protected pill context opens the gate. Wrong IDs,
replacement documents, missing frames/panels and waveform traffic cannot open it.
New-question capsules and follow-up waveform removal both send an explicit render,
including when the payload would otherwise be deduplicated.

Resolution, approval invalidation/publication, native shutdown and ASR stay after
this acknowledgement. Existing callback-tail sealing, close exclusion and lock
ordering are unchanged. If no release renderer acknowledges within the existing
five-second CDP window, capture fails explicitly and native shutdown still runs;
no ASR/admission follows. This is failure cleanup, not a fabricated UI success.

This protects the **first** update from this release's expensive work. It cannot
keep all Python interactions responsive during a later GIL-holding native call,
or prevent unrelated, already-running work from monopolizing the interpreter.
Process isolation should follow a real diagnostic identifying such a call, not
this deliberately adversarial fake alone.

## Reproduction and checks

- Ordinary blocking fake stop, close and ASR did not reproduce the freeze:
  protected processing pushes were 15–20 ms with headless Chrome.
- A 100 ms delayed private-render hop plus `ctypes.PyDLL(None).sleep(2)` in fake
  stream stop reproduced it before the fix: processing push **2032.17 ms**, with
  the protected pill still saying `Listening` when Python first resumed.
- Same scenario after the fix: processing push **104.59 ms**; native stop started
  at **108.88 ms** and returned at **2114.59 ms**. The watchdog retained a
  **2016.93 ms** scheduling gap and code-location stacks.
- Blocked webcam fixation ingestion with injected synthetic webcam samples:
  processing push **15.63 ms**, before capture resolution entered the blocked
  ingestion. No camera/estimator process was launched.
- The permanent blocking-stream unit regression failed before the fix with
  `native_saw_ui == [False]`; it passed after, requiring `[True]`.
- `tests/ui_review/probe_release.py` now exercises blocking stop/close/ASR,
  GIL-holding stop/close/ASR with delayed CDP, and blocked webcam ingestion through
  the real headless protected renderer. Timing is measured at completed render;
  main-thread observation after a GIL stall is deliberately reported separately.
- Final verification: `.venv/bin/python -m unittest discover -s tests -t .` —
  **225 tests in 4.821 seconds, OK**; `node --check browser/overlay.js` — exit 0.
- All twelve `tests/ui_review/probe_*.py` ran serially in headless/local-only mode:
  every exit code was 0 and no probe log contained a traceback/error record.
  The final seven-case release matrix acknowledged its release render in
  **54.82–102.85 ms**, before the blocked work. Stop/close/ASR/webcam cases also
  exercised page scrolling, typing and timers while blocked. GIL-held cases
  intentionally could not exercise Python interaction during the two-second hold.
  External media/news visits were omitted; no physical-device result is claimed.

## Reading real-machine diagnostics

`/gaze timing` retains the last eight releases in memory. Look for the largest
adjacent stage interval and inspect `slow_release`:

- Browser evidence start/frozen/sent: synchronous page evidence work.
- Binding to worker: ordered-intent admission.
- Microphone lock wait/acquired, PCM lock wait/sealed: state or callback contention.
- Release UI wait/render start/push/ready: private-frame dispatch/CDP acknowledgement.
- Capture revoke/resolve, inbox lock, approval revoke, inbox publish: reservation work.
- Stream stop and mic close start/end: native shutdown, individually.
- ASR queued/lock wait/started/model ready/inference/end and answer resolve: speech work.

The existing 20 ms heartbeat also takes one all-thread Python stack sample once a
release exceeds 500 ms, through its first delta/failure/completion. Each frame
contains only basename, function name and line number (up to 64 frames per thread).
It never formats source lines or captures locals, arguments, exception messages,
audio, transcript, URLs, identities, features or gaze samples. Samples are not
persisted, logged, pushed to Chrome or sent to a provider. Disconnect/unload/reload
and idle retirement retain the existing worker lifecycle.

A Python watchdog cannot acquire the GIL while another native call retains it.
Such a sample is late: `scheduler_gap_ms`, `sampled_ms`, `after_stage`,
`current_stage` and `sampled_after_finish` make that limitation explicit. Use the
recorded stage intervals as well; a resumed stack alone does not identify the
native instruction that held the GIL. Browser/Python clocks remain separate;
subtract offsets within their own group, never across clocks.

Confidence: high in the reproduced render/publication race and its fix; low in
attributing the user's physical-machine freeze to that race without a fresh
real-machine trace. The user's earlier successful build and later recurrence
remain observations, not a controlled bisect proving an offending commit.
