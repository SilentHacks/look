"""Native-consent wire boundaries using temporary metadata and a loopback fake Chrome."""
import asyncio
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from websockets.sync.server import serve

from hermes_gaze import cli, service
from hermes_gaze.browser.cdp_bridge import CdpSession, GazeSession
from hermes_gaze.browser.consent import ConsentChrome, discovery_port
from hermes_gaze.browser.ownership import OwnedChrome, OwnershipError
from hermes_gaze.voice_turns import VoiceTurns


GUID = "12345678-1234-1234-1234-123456789abc"


def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("fake Chrome scenario deadline")


class FakeChrome:
    def __init__(self, directory, *, allow=True, address="127.0.0.1"):
        self.allow = threading.Event()
        if allow:
            self.allow.set()
        self.requested = threading.Event()
        self.ws = None
        self.upgrades = 0
        self.requests = []
        self.commands = []
        self.denied = False
        self.redirect = None
        self.preflight = 404
        self.default_context = "regular"
        self.created_context = "regular"
        self.product = "Chrome/156.0.8078.81"
        self.sessions = {}
        self.targets = {name: dict(targetId=name, type="page", url="https://example.test/" + name,
                                   browserContextId="regular") for name in ("A", "B")}
        self.targets["private"] = dict(targetId="private", type="page", url="https://private.test/", browserContextId="private")
        self.targets["file"] = dict(targetId="file", type="page", url="file:///not-read", browserContextId="regular")
        self.held = []
        self.mutations = 0
        self.scripts = set()
        self.bindings = set()
        listener = socket.socket(socket.AF_INET6 if address == "::1" else socket.AF_INET, socket.SOCK_STREAM)
        listener.bind((address, 0))
        listener.listen()
        self.server = serve(self.handle, sock=listener, process_request=self.process, open_timeout=5)
        self.port = self.server.socket.getsockname()[1]
        self.metadata = Path(directory) / "DevToolsActivePort"
        self.metadata.write_text(f"{self.port}\n/devtools/browser/{GUID}\n")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def process(self, connection, request):
        self.requests.append((request.path, request.headers.get("Origin")))
        if request.path == "/json/version":
            return connection.respond(self.preflight, "")
        self.upgrades += 1
        self.requested.set()
        self.allow.wait(5)
        if self.redirect:
            response = connection.respond(307, "")
            response.headers["Location"] = self.redirect
            return response
        if self.denied:
            return connection.respond(403, "Connection rejected")

    def emit(self, session, method, params):
        message = dict(method=method, params=params)
        if session:
            message["sessionId"] = session
        self.ws.send(json.dumps(message))

    def reply(self, message, result):
        response = dict(id=message["id"], result=result)
        if "sessionId" in message:
            response["sessionId"] = message["sessionId"]
        self.ws.send(json.dumps(response))

    def handle(self, ws):
        self.ws = ws
        try:
            for raw in ws:
                message = json.loads(raw)
                self.commands.append(message)
                method, params = message["method"], message.get("params", {})
                session = message.get("sessionId")
                target = self.sessions.get(session)
                result = {}
                if method == "Browser.getVersion":
                    result = dict(product=self.product)
                elif method == "Target.getBrowserContexts":
                    result = dict(browserContextIds=["private"], defaultBrowserContextId=self.default_context)
                elif method == "Target.getTargets":
                    result = dict(targetInfos=list(self.targets.values()))
                elif method == "Target.getTargetInfo":
                    result = dict(targetInfo=self.targets[params["targetId"]])
                elif method == "Target.attachToTarget":
                    session = "session-" + str(len(self.sessions))
                    self.sessions[session] = params["targetId"]
                    result = dict(sessionId=session)
                elif method == "Target.createTarget":
                    self.targets["created"] = dict(targetId="created", type="page", url=params["url"],
                                                   browserContextId=self.created_context)
                    result = dict(targetId="created")
                elif method == "Runtime.addBinding":
                    self.bindings.add(session)
                elif method == "Runtime.removeBinding":
                    self.bindings.discard(session)
                elif method == "Page.addScriptToEvaluateOnNewDocument":
                    self.scripts.add(session)
                    result = dict(identifier="script-" + session)
                elif method == "Page.removeScriptToEvaluateOnNewDocument":
                    self.scripts.discard(session)
                elif method == "Page.getFrameTree":
                    result = dict(frameTree=dict(frame=dict(id="main", url=self.targets[target]["url"])))
                elif method == "Page.createIsolatedWorld":
                    name = params["frameId"]
                    context = {"main": 7, "card": 8, "pill": 9}[name]
                    # Deliberately collide both numeric AND unique context IDs between targets.
                    self.emit(session, "Runtime.executionContextCreated", dict(context=dict(
                        id=context, uniqueId="document-" + name, name="hermes-gaze")))
                    result = dict(executionContextId=context)
                elif method == "DOM.describeNode":
                    result = dict(node=dict(frameId=params["objectId"]))
                elif method == "Runtime.evaluate":
                    expression = params["expression"]
                    if expression == "hold":
                        self.held.append(message)
                        continue
                    if expression == "mutation":
                        self.mutations += 1
                        ws.close()
                        break
                    if ".uiFrames." in expression:
                        result = dict(result=dict(objectId=expression.rsplit(".", 1)[1]))
                    else:
                        result = dict(result=dict(value=True))
                self.reply(message, result)
        except Exception:
            pass  # Deliberate client cancellation/loss is part of these scenarios.

    def close(self):
        self.allow.set()
        if self.ws:
            self.ws.close()
        self.server.shutdown()
        self.thread.join(3)


class Discovery(unittest.TestCase):
    def test_bounded_regular_same_user_metadata_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DevToolsActivePort"
            for data in (b"", b"1", b"0\n", b"65536\n", b"x" * 4097,
                         f"0\n/devtools/browser/{GUID}".encode(),
                         f"65536\n/devtools/browser/{GUID}".encode(),
                         f"1\nws://remote/devtools/browser/{GUID}".encode(),
                         b"1\n/devtools/browser/../../other", b"1\n/devtools/page/A",
                         f"1\n/devtools/browser/{GUID}\nextra".encode()):
                path.write_bytes(data)
                with self.assertRaises(OwnershipError):
                    discovery_port(path)
            path.write_text(f"65535\n/devtools/browser/{GUID}")
            self.assertEqual(discovery_port(path), 65535)
            path.chmod(0o666)
            with self.assertRaises(OwnershipError):
                discovery_port(path)
            path.chmod(0o600)
            with patch("hermes_gaze.browser.consent.os.getuid", return_value=os.getuid() + 1):
                with self.assertRaises(OwnershipError):
                    discovery_port(path)
            link = Path(directory) / "link"
            link.symlink_to(path)
            for invalid in (link, Path(directory), Path(directory) / "absent"):
                with self.assertRaises(OwnershipError):
                    discovery_port(invalid)
            fifo = Path(directory) / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(OwnershipError):
                discovery_port(fifo)


class ConsentWire(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.fake = FakeChrome(self.directory)
        self.addCleanup(self.fake.close)
        self.root = ConsentChrome(metadata_path=self.fake.metadata, lease_dir=Path(self.directory) / "look")
        self.addCleanup(self.root.close)
        self.tabs = []

    async def asyncTearDown(self):
        for tab in self.tabs:
            await tab._shutdown_overlay()
            tab.close()

    async def start(self, **kwargs):
        await asyncio.to_thread(self.root.start, **kwargs)

    async def tab(self, target):
        tab = CdpSession(owner=self.root)
        tab.tab = dict(id=target)
        tab.intent_nonce = "nonce"
        self.tabs.append(tab)
        self.assertTrue(await tab._connect_async())
        return tab

    async def test_one_approval_precedes_all_page_access_and_stop_cleans_sessions(self):
        self.fake.allow.clear()
        attempt = asyncio.create_task(self.start())
        await asyncio.to_thread(self.fake.requested.wait, 2)
        self.assertEqual(self.fake.commands, [])
        self.assertFalse(self.root.live)
        self.fake.allow.set()
        await attempt
        a, b = await self.tab("A"), await self.tab("B")
        self.assertNotEqual(a._context_unique_id, b._context_unique_id)
        self.assertEqual(self.fake.upgrades, 1)
        self.assertEqual(self.fake.requests, [("/json/version", None), ("/devtools/browser", None)])
        self.assertFalse(any(c["method"] == "Browser.getBrowserCommandLine" for c in self.fake.commands))
        for tab in (a, b):
            await tab._shutdown_overlay()
        self.assertEqual(self.fake.scripts, set())
        self.assertEqual(self.fake.bindings, set())
        self.assertEqual(sum(c["method"] == "Target.detachFromTarget" for c in self.fake.commands), 2)
        self.assertEqual(set(self.fake.targets), {"A", "B", "private", "file"})
        self.root.close()
        self.assertFalse(self.root.live)
        self.assertFalse(any(c["method"] in ("Browser.close", "Target.closeTarget", "Page.navigate") for c in self.fake.commands))

    async def test_colliding_contexts_interleaved_replies_wrong_session_and_stale_generation(self):
        await self.start()
        a, b = await self.tab("A"), await self.tab("B")
        events_a, events_b = [], []
        a.set_intent_handler(lambda intent, reply: events_a.append(intent))
        b.set_intent_handler(lambda intent, reply: events_b.append(intent))
        pending_a = asyncio.create_task(a._eval_coro("hold", 2))
        pending_b = asyncio.create_task(b._eval_coro("hold", 2))
        await asyncio.to_thread(until, lambda: len(self.fake.held) == 2)
        held_a = next(m for m in self.fake.held if m["sessionId"] == a._ws.session)
        held_b = next(m for m in self.fake.held if m["sessionId"] == b._ws.session)
        # A correct command ID on the wrong session must not settle A's request.
        self.fake.ws.send(json.dumps(dict(id=held_a["id"], sessionId=b._ws.session,
                                          result=dict(result=dict(value="wrong")))))
        self.fake.reply(held_b, dict(result=dict(value="B")))
        self.fake.reply(held_a, dict(result=dict(value="A")))
        self.assertEqual(await asyncio.gather(pending_a, pending_b), ["A", "B"])
        payload = json.dumps(dict(type="ask", nonce="nonce", utterance="question"))
        params = dict(name="__hermesGazeIntent", executionContextId=7, payload=payload)
        self.fake.emit("unknown-session", "Runtime.bindingCalled", params)
        self.fake.emit(b._ws.session, "Runtime.bindingCalled", params)
        await asyncio.to_thread(until, lambda: len(events_b) == 1)
        self.assertEqual(events_a, [])
        self.assertEqual(events_b[0]["_browser_document"], b._context_unique_id)
        with self.assertRaises(ConnectionError):
            await b._eval_coro("true", 1, context_id=a._context_unique_id)
        old = a._context_unique_id
        old_channel = a._ws
        self.fake.emit(None, "Target.detachedFromTarget", dict(sessionId=old_channel.session, targetId="A"))
        await asyncio.to_thread(until, lambda: not old_channel.live)
        self.fake.emit(old_channel.session, "Runtime.bindingCalled", params)
        await a._drop_ws()
        self.assertTrue(await a._connect_async())
        with self.assertRaises(ConnectionError):
            await a._eval_coro("true", 1, context_id=old)
        self.assertEqual(events_a, [])
        self.root.abort()
        with self.assertRaises(OwnershipError):
            await old_channel.send(json.dumps(dict(id=9, method="Runtime.evaluate", params={})))
        self.assertEqual(self.fake.upgrades, 1)
        previous_root = self.root
        self.root = ConsentChrome(metadata_path=self.fake.metadata, lease_dir=Path(self.directory) / "look")
        previous_root.close()
        self.addCleanup(self.root.close)
        await self.start()
        replacement = await self.tab("A")
        with self.assertRaises(ConnectionError):
            await replacement._eval_coro("true", 1, context_id=old)

    async def test_web_tab_navigating_to_local_file_stops_page_access(self):
        await self.start()
        tab = await self.tab("A")
        self.fake.targets["A"]["url"] = "file:///not-read"
        before = len(self.fake.commands)
        self.assertFalse(await tab._on_new_context())
        operations = [command["method"] for command in self.fake.commands[before:]]
        self.assertEqual(operations, ["Page.getFrameTree"])
        self.assertFalse(tab.is_connected)
        self.fake.targets["A"]["url"] = "https://example.test/returned"
        self.assertTrue(await tab._on_new_context())
        self.assertTrue(tab.is_connected)

    async def test_unknown_mutation_runs_once_root_loss_settles_pending_and_no_reconsent(self):
        await self.start()
        tab = await self.tab("A")
        pending = asyncio.create_task(tab._eval_coro("hold", 2))
        await asyncio.to_thread(until, lambda: len(self.fake.held) == 1)
        with self.assertRaises(ConnectionError):
            await tab._eval_coro("mutation", 2)
        with self.assertRaises(ConnectionError):
            await pending
        self.assertEqual(self.fake.mutations, 1)
        self.assertFalse(self.root.available())
        with self.assertRaises(OwnershipError):
            self.root.attach()
        with self.assertRaises(OwnershipError):
            await self.root.channel("A")
        self.assertEqual(self.fake.upgrades, 1)

    async def test_private_file_and_unidentified_profiles_fail_before_runtime(self):
        await self.start()
        for target in ("private", "file"):
            with self.assertRaises(OwnershipError):
                await self.root.channel(target)
        self.assertFalse(any(c["method"] == "Runtime.enable" for c in self.fake.commands))

    async def test_source_context_new_tab_and_default_drift_or_wrong_returned_context(self):
        await self.start()
        tab = await self.tab("A")
        companion = GazeSession(profile_dir=Path(self.directory) / "unused").cdp
        self.addCleanup(companion.close)
        companion.source, companion.chrome = "existing", self.root
        self.assertEqual(await asyncio.to_thread(companion._create_target, "https://example.test/new", tab), "created")
        creates = [c for c in self.fake.commands if c["method"] == "Target.createTarget"]
        self.assertEqual(creates[0]["params"]["browserContextId"], "regular")
        self.fake.default_context = "different"
        with self.assertRaises(OwnershipError):
            await asyncio.to_thread(companion._create_target, "https://example.test/new", tab)
        self.assertEqual(sum(c["method"] == "Target.createTarget" for c in self.fake.commands), 1)
        self.fake.default_context, self.fake.created_context = "regular", "different"
        with self.assertRaisesRegex(OwnershipError, "outcome unknown"):
            await asyncio.to_thread(companion._create_target, "https://example.test/new", tab)
        self.assertEqual(sum(c["method"] == "Target.createTarget" for c in self.fake.commands), 2)

    async def test_denial_timeout_cancel_late_allow_and_no_background_retry(self):
        for outcome in ("denied", "timeout", "cancel"):
            with self.subTest(outcome=outcome):
                root = ConsentChrome(metadata_path=self.fake.metadata, lease_dir=Path(self.directory) / "look")
                self.fake.requested.clear()
                self.fake.allow.clear()
                self.fake.denied = outcome == "denied"
                attempt = asyncio.create_task(asyncio.to_thread(root.start, timeout=.15 if outcome == "timeout" else 2))
                await asyncio.to_thread(self.fake.requested.wait, 2)
                if outcome == "cancel":
                    root.close()
                if outcome == "denied":
                    self.fake.allow.set()
                with self.assertRaises(OwnershipError):
                    await attempt
                self.fake.allow.set()  # Late server approval cannot install anything.
                self.assertFalse(root.live)
                self.assertEqual(self.fake.commands, [])
                root.close()
        self.assertEqual(self.fake.upgrades, 3)

    async def test_legacy_and_redirects_are_refused_without_destination_contact(self):
        self.fake.preflight = 200
        with self.assertRaises(OwnershipError):
            await self.start()
        self.assertEqual(self.fake.upgrades, 0)
        self.fake.preflight = 404
        self.fake.redirect = f"ws://127.0.0.1:{self.fake.port}/redirected"
        other = ConsentChrome(metadata_path=self.fake.metadata, lease_dir=Path(self.directory) / "look")
        try:
            with patch.dict(os.environ, {"HTTP_PROXY": "http://not-used.invalid:80", "ALL_PROXY": "http://not-used.invalid:80"}):
                with self.assertRaises(OwnershipError):
                    await asyncio.to_thread(other.start)
            self.assertFalse(any(path == "/redirected" for path, _ in self.fake.requests))
            self.assertEqual(self.fake.upgrades, 1)
        finally:
            other.close()

    async def test_missing_context_and_old_version_fail_before_target_attachment(self):
        for context, product in ((None, "Chrome/156.0.8078.81"), ("private", "Chrome/156.0.8078.81"),
                                 ("regular", "Chrome/143.0.1")):
            root = ConsentChrome(metadata_path=self.fake.metadata, lease_dir=Path(self.directory) / "look")
            self.fake.default_context, self.fake.product = context, product
            with self.assertRaises(OwnershipError):
                await asyncio.to_thread(root.start)
            root.close()
        self.assertFalse(any(c["method"] == "Target.attachToTarget" for c in self.fake.commands))


class Integration(unittest.TestCase):
    def test_disclosure_does_not_read_discovery_and_source_change_is_explicit(self):
        session = GazeSession("http://127.0.0.1:1")
        self.addCleanup(session.close)
        with patch.object(cli, "get_shared_session", return_value=session), \
             patch("hermes_gaze.browser.consent.discovery_port", side_effect=AssertionError("personal read")):
            text = cli._handle_slash_command("start --existing")
            self.assertIn("broad debugger access", text)
            self.assertIn("--accept", text)
            self.assertEqual(session.cdp.source, "owned")
            self.assertFalse(session.cdp._tabs)

    def test_stop_during_renderer_initialization_cleans_before_root_close(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeChrome(directory)
            self.addCleanup(fake.close)
            session = GazeSession("http://127.0.0.1:1", profile_dir=Path(directory) / "look")
            self.addCleanup(session.close)
            entered = threading.Event()
            async def blocked_ui(tab):
                entered.set()  # Full overlay exists; private renderer initialization is pending.
                while not tab._closed:
                    await asyncio.sleep(.01)
                raise ConnectionError("Stopped during renderer initialization")
            with patch.object(CdpSession, "_init_ui", blocked_ui):
                session.cdp.start_existing(metadata_path=fake.metadata)
                self.assertTrue(entered.wait(5))
                session.close()
            methods = [message["method"] for message in fake.commands]
            self.assertIn("Page.removeScriptToEvaluateOnNewDocument", methods)
            destroyed = [message for message in fake.commands if message["method"] == "Runtime.evaluate"
                         and "?.destroy()" in message["params"]["expression"]]
            self.assertTrue(destroyed, "Stop must destroy the live DOM before detaching authority")
            self.assertFalse(fake.scripts)
            self.assertFalse(fake.bindings)

    def test_root_loss_cancels_capture_speech_approval_but_retains_host_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeChrome(directory)
            self.addCleanup(fake.close)
            session = GazeSession("http://127.0.0.1:1", profile_dir=Path(directory) / "look")
            self.addCleanup(session.close)
            turns = VoiceTurns(SimpleNamespace(), session)
            self.addCleanup(turns.close)
            with patch.object(service, "_VOICE_TURNS", turns):
                ready = threading.Event()
                session.cdp.start_existing(metadata_path=fake.metadata, on_ready=ready.set)
                self.assertTrue(ready.wait(5))
                turns.bind(session_key="key", session_id="session")
                turns.host_session, turns.host_turn = "session", "busy"
                turns._speech_cancel = speech = threading.Event()
                turns.capture(dict(utterance="queued", context=""), transcribing=True)
                queued = list(turns.pending)
                session.actions._pending = dict(action_id="pending")
                session.last_hover_snapshot = dict(browser_target="A", browser_document="old")
                session.microphone._stream = stream = Mock()
                session.microphone._audio.extend(b"private bytes")
                fake.ws.close()
                until(lambda: not turns.connected)
                self.assertTrue(speech.is_set())
                self.assertIsNone(session.actions._pending)
                self.assertIsNone(session.last_hover_snapshot)
                self.assertIsNone(session.microphone._stream)
                stream.abort.assert_called_once()
                stream.close.assert_called_once()
                self.assertEqual(turns.host_turn, "busy")
                self.assertEqual(turns.pending, queued)
                self.assertTrue(turns.paused)
                self.assertFalse(session.ensure_connected())
                self.assertEqual(fake.upgrades, 1)

    def test_cancel_pending_shared_attempt_and_runtime_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeChrome(directory, allow=False)
            self.addCleanup(fake.close)
            session = GazeSession("http://127.0.0.1:1", profile_dir=Path(directory) / "look")
            self.addCleanup(session.close)
            session.cdp.start_existing(metadata_path=fake.metadata)
            self.assertTrue(fake.requested.wait(2))
            first = session.cdp.chrome
            session.cdp.start_existing(metadata_path=fake.metadata)
            self.assertIs(session.cdp.chrome, first)
            competitor = OwnedChrome("http://127.0.0.1:1", Path(directory) / "look")
            with self.assertRaises(OwnershipError):
                competitor._acquire()
            session.close()
            fake.allow.set()
            session.cdp._consent_worker.join(3)
            self.assertFalse(first.live)
            self.assertFalse(session.cdp._tabs)
            self.assertEqual(fake.commands, [])
            self.assertEqual(fake.upgrades, 1)
            competitor._acquire()
            competitor.close()
            with self.assertRaises(OwnershipError):
                session.cdp.start()  # A stopped borrowed source cannot silently launch the companion.

    def test_ipv6_only_loopback_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            try:
                fake = FakeChrome(directory, address="::1")
            except OSError:
                self.skipTest("IPv6 loopback unavailable")
            self.addCleanup(fake.close)
            root = ConsentChrome(metadata_path=fake.metadata, lease_dir=Path(directory) / "look")
            self.addCleanup(root.close)
            root.start()
            self.assertTrue(root.live)
            self.assertEqual(fake.upgrades, 1)


if __name__ == "__main__":
    unittest.main()
