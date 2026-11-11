"""Companion identity and loopback trust boundaries; no Chrome or devices."""
import asyncio
import http.server
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from look.browser.cdp_bridge import CdpSession, GazeSession
from look.browser.ownership import OwnedChrome, OwnershipError
from look.browser.companion import Companion
from look.config import GazeConfig


class Endpoint(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(self.path)
        self.send_response(self.server.status)
        if self.server.status == 302:
            self.send_header("Location", "http://untrusted.invalid/json/version")
        self.end_headers()
        self.wfile.write(json.dumps(self.server.version).encode())

    def log_message(self, *args):
        pass


class Ownership(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.profile = Path(self.directory) / "companion"
        self.profile.mkdir(mode=0o700)

    def owner(self, endpoint="http://127.0.0.1:1"):
        owner = OwnedChrome(endpoint, self.profile)
        self.addCleanup(owner.close)
        return owner

    def token(self):
        token = self.profile / ".look-owner"
        token.write_text("a" * 64)
        token.chmod(0o600)

    def endpoint(self, version, status=200):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
        server.version, server.status, server.requests = version, status, []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        return server, f"http://127.0.0.1:{server.server_port}"

    def test_config_and_runtime_reject_indirect_or_remote_endpoints_before_io(self):
        for url in ("https://untrusted.invalid:9333", "http://192.168.1.1:9333", "http://0.0.0.0:9333",
                    "http://[::1]:9333", "http://127.0.0.1:0", "http://127.0.0.1:65536",
                    "http://localhost:9333/path", "http://u:p@localhost:9333", "http://localhost:9333?q=1",
                    "http://localhost:9333#fragment", "http://localhost.evil:9333"):
            with self.subTest(url=url), patch("socket.socket") as network:
                for build in (lambda: GazeConfig(cdp_url=url), lambda: GazeSession(url)):
                    with self.assertRaises(ValueError):
                        build()
                network.assert_not_called()
        self.assertEqual(GazeConfig(cdp_url="http://localhost:9444/").cdp_url, "http://127.0.0.1:9444")
        session = GazeSession("http://127.0.0.1:1", profile_dir=self.profile)
        self.addCleanup(session.close)
        with self.assertRaises(ValueError):
            session.cdp_http_url = "http://remote.invalid:9333"
        self.assertEqual(session.cdp_http_url, "http://127.0.0.1:1")

    def test_non_chrome_200_and_remote_websocket_fail_without_launch_or_injection(self):
        self.token()  # A stale launch record is not permission to trust this occupant.
        for version in ({}, {"Browser": "Chrome/156"},
                        {"webSocketDebuggerUrl": "ws://untrusted.invalid/devtools/browser/id"}):
            server, endpoint = self.endpoint(version)
            session = GazeSession(endpoint, profile_dir=self.profile)
            try:
                with patch("subprocess.Popen") as launch, patch("websockets.sync.client.connect") as ws:
                    with self.assertRaises(OwnershipError):
                        session.cdp.start()
                    self.assertFalse(session.ensure_overlay())
                    self.assertFalse(session.cdp._tabs)
                    launch.assert_not_called()
                    ws.assert_not_called()
                self.assertEqual(set(server.requests), {"/json/version"})
            finally:
                session.close()

    def test_redirect_is_not_followed_and_proxy_is_not_used(self):
        self.token()
        server, endpoint = self.endpoint({}, status=302)
        with patch.dict("os.environ", {"http_proxy": "http://untrusted.invalid:9", "no_proxy": ""}):
            with self.assertRaisesRegex(OwnershipError, "redirected"):
                self.owner(endpoint).start()
        self.assertEqual(server.requests, ["/json/version"])

    def test_unrecorded_occupied_port_is_left_alone(self):
        server, endpoint = self.endpoint({})
        with patch("subprocess.Popen") as launch:
            with self.assertRaisesRegex(OwnershipError, "not a verified Look companion"):
                self.owner(endpoint).start()
            launch.assert_not_called()
        self.assertFalse(server.requests)
        self.assertFalse((self.profile / ".look-owner").exists())

    def test_exclusive_lease_releases_on_stop_or_failed_verification(self):
        first, second = self.owner(), self.owner()
        first._acquire()
        with self.assertRaisesRegex(OwnershipError, "Another Look runtime"):
            second._acquire()
        first.close()
        second._acquire()
        second.close()
        with self.assertRaises(OwnershipError):
            first.attach()
        second._acquire()  # A failed attach must not strand the lock.

    def test_failed_warm_reuse_keeps_lease_until_input_transports_stop(self):
        first, second = self.owner(), self.owner()
        first._acquire()
        with patch.object(first, "_listening", return_value=True), \
             patch.object(first, "_verify", side_effect=OwnershipError("lost identity")):
            with self.assertRaises(OwnershipError):
                first.start()
        with self.assertRaisesRegex(OwnershipError, "Another Look runtime"):
            second._acquire()
        first.close()
        second._acquire()

    def test_launch_identity_checks_token_profile_port_and_automation(self):
        owner = self.owner()
        owner._token = "a" * 64
        args = ["chrome", "--enable-automation", f"--user-data-dir={self.profile}",
                "--remote-debugging-port=1", "--look-owner=" + "a" * 64]
        owner.verify_arguments({"arguments": args})
        for index in range(1, len(args)):
            with self.subTest(index=index), self.assertRaises(OwnershipError):
                owner.verify_arguments({"arguments": args[:index] + args[index + 1:]})

    def test_occupied_after_probe_cannot_become_a_verified_launch(self):
        owner = self.owner()
        process = Mock()
        process.poll.side_effect = [None, 1]
        with patch("socket.socket") as probe, patch("subprocess.Popen", return_value=process), \
             patch.object(owner, "_verify", side_effect=OwnershipError("wrong browser")):
            probe.return_value.__enter__.return_value.connect_ex.return_value = 1
            with self.assertRaisesRegex(OwnershipError, "did not start"):
                owner.start()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        self.assertIsNone(owner._lease)

    def test_mutation_lost_reply_is_never_replayed(self):
        owner = self.owner()
        ws = Mock()
        owner._ws = ws
        owner._acquire()
        ws.recv.side_effect = TimeoutError
        with self.assertRaises(OwnershipError):
            owner.command("Target.createTarget", {"url": "about:blank"})
        self.assertEqual(ws.send.call_count, 1)
        self.assertIsNone(owner._ws)

    def test_stop_waits_for_detached_transport_cleanup_before_releasing_lease(self):
        companion = Companion("http://127.0.0.1:1", profile_dir=self.profile)
        self.addCleanup(companion.close)
        companion.chrome._acquire()
        entered, release, closed = (threading.Event() for _ in range(3))
        def slow_close():
            entered.set()
            release.wait(3)
        tab = Mock()
        tab.close.side_effect = slow_close
        companion._tabs["detached"] = tab
        worker = threading.Thread(target=companion._watch)
        companion._thread = worker
        with patch.object(companion.chrome, "command", side_effect=OwnershipError("lost")):
            worker.start()
            self.assertTrue(entered.wait(1))
            join = worker.join
            # Fast-forward any bounded join deadline while real cleanup is held.
            with patch.object(worker, "join", side_effect=lambda timeout=None: join(0 if timeout is not None else None)):
                stopper = threading.Thread(target=lambda: (companion.close(), closed.set()))
                stopper.start()
                try:
                    self.assertFalse(closed.wait(.05))
                    second = self.owner()
                    with self.assertRaises(OwnershipError):
                        second._acquire()
                finally:
                    release.set()
                    stopper.join(3)
            self.assertTrue(closed.is_set())
            second._acquire()


class PageTransport(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_browser_on_page_socket_fails_before_binding_or_scripts(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = OwnedChrome("http://127.0.0.1:1", Path(directory))
            owner._token = "a" * 64
            tab = CdpSession(owner.http_url, owner=owner)
            tab.tab = {"id": "captured-target", "webSocketDebuggerUrl": "ws://remote.invalid/danger"}
            ws = Mock(close=AsyncMock())
            try:
                with patch("websockets.connect", new_callable=AsyncMock, return_value=ws) as connect, \
                     patch.object(tab, "_send_cmd", new_callable=AsyncMock, return_value={"arguments": []}) as send, \
                     patch.object(tab, "_pump", new_callable=AsyncMock):
                    with self.assertRaises(OwnershipError):
                        await tab._connect_async()
                    connect.assert_awaited_once_with("ws://127.0.0.1:1/devtools/page/captured-target",
                                                     max_size=32 * 1024 * 1024, proxy=None, host="127.0.0.1", port=1)
                    self.assertEqual([call.args[0] for call in send.await_args_list], ["Browser.getBrowserCommandLine"])
            finally:
                tab.close()
                owner.close()

    async def test_page_socket_does_not_follow_cross_origin_redirect(self):
        contacts = []
        async def destination(reader, writer):
            contacts.append(True)
            writer.close()
            await writer.wait_closed()
        async with await asyncio.start_server(destination, "127.0.0.1", 0) as sink:
            port = sink.sockets[0].getsockname()[1]
            async def redirect(reader, writer):
                await reader.readuntil(b"\r\n\r\n")
                writer.write(f"HTTP/1.1 307 Temporary Redirect\r\nLocation: ws://127.0.0.1:{port}/other\r\nContent-Length: 0\r\n\r\n".encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            async with await asyncio.start_server(redirect, "127.0.0.1", 0) as origin:
                local = origin.sockets[0].getsockname()[1]
                tab = CdpSession(f"http://127.0.0.1:{local}", owner=Mock())
                tab.tab = {"id": "captured"}
                try:
                    with self.assertRaisesRegex(ValueError, "cannot follow cross-origin redirect"):
                        await tab._connect_async()
                    self.assertFalse(contacts)
                finally:
                    tab.close()


if __name__ == "__main__":
    unittest.main()
