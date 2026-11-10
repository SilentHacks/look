"""Native receipts, not hook timing, own Look's FIFO and uncertain attempts."""
import copy
import unittest
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
from unittest.mock import patch

from hermes_gaze.runtime.native_input import NativeError, NativeInput

from hermes_gaze.runtime.voice_turns import VoiceTurns
from tests.test_voice_turns import Chrome, snapshot


class Native:
    def __init__(self):
        self.messages = []
        self.closed = False

    def submit(self, run, callback):
        self.messages.append((run["request_id"], run["wire"]))

    def close(self):
        self.closed = True

    def cancel(self, run, callback):
        self.cancelled = run["request_id"]


class NativeReceiptOwnership(unittest.TestCase):
    def setUp(self):
        self.native = Native()
        self.turns = VoiceTurns(SimpleNamespace(), Chrome())
        self.turns.bind(session_key="route", session_id="physical", native_input=self.native)
        self.addCleanup(self.turns.close)

    def pre(self, run, turn="turn"):
        return self.turns.pre(session_id="physical", user_message=run["wire"], turn_id=turn)

    def test_end_hook_cannot_admit_next_before_terminal_receipt(self):
        self.turns.submit("first", snapshot("10"))
        first = self.turns.active
        self.turns.submit("second", snapshot("20"))
        self.pre(first)
        self.turns.post(session_id="physical", turn_id="turn", assistant_response="First answer")
        self.turns.end(session_id="physical", turn_id="turn")
        self.assertIs(self.turns.active, first)
        self.assertEqual([wire for _, wire in self.native.messages], [first["wire"]])
        self.turns.native_receipt(first, dict(status="terminal", outcome="completed",
                                            result={"final_response": "First answer"}))
        self.assertIsNot(self.turns.active, first)
        self.assertEqual(self.native.messages[1][1], self.turns.active["wire"])
        # Late duplicate delivery cannot settle or overwrite the second request.
        self.turns.native_receipt(first, dict(status="terminal", outcome="failed"))
        self.assertEqual(self.turns.active["status"], "thinking")

    def test_unknown_retains_attempt_evidence_and_forbids_replay_or_owner_transfer(self):
        self.turns.submit("first", snapshot("10"))
        first = self.turns.active
        saved = copy.deepcopy(first["snapshot"])
        self.pre(first)
        self.turns.delta(session_id="physical", turn_id="turn", delta="Retained partial")
        self.turns.native_receipt(first, dict(status="unknown"))
        for action in ("retry", "skip"):
            self.assertFalse(self.turns.control(action, first["item_id"], first["request_id"])["ok"])
        self.turns._disconnect()
        self.turns.bind(session_key="foreign", session_id="foreign", native_input=Native())
        self.assertFalse(self.turns.connected)
        self.assertIs(self.turns.active, first)
        self.assertEqual(first["snapshot"], saved)
        self.assertEqual(first["text"], "Retained partial")
        self.assertEqual(len(self.native.messages), 1)
        self.turns.native_receipt(first, dict(status="terminal", outcome="completed",
                                            result={"final_response": "Final retained answer"}))
        self.assertEqual(first["text"], "Final retained answer")
        self.assertFalse(self.turns.connected)

    def test_constructor_failure_needs_no_invented_hook_or_turn(self):
        self.turns.submit("first", snapshot("10"))
        first = self.turns.active
        self.turns.native_receipt(first, dict(status="terminal", outcome="failed",
                                            result={"failed": True}))
        self.assertIsNone(self.turns.active)
        self.assertEqual(first["turn_id"], "")
        self.assertEqual(first["status"], "failed")
        self.assertTrue(self.turns.control("retry", first["item_id"], first["request_id"])["ok"])
        self.assertNotEqual(first["request_id"], self.turns.active["request_id"])

    def test_reset_stop_and_wrong_physical_target_withhold_exact_old_wire(self):
        self.turns.submit("first", snapshot("10"))
        first = self.turns.active
        blocked = self.turns.pre(session_id="replacement", user_message=first["wire"], turn_id="foreign")
        self.assertEqual(blocked["action"], "block")
        self.assertFalse(self.turns.connected)
        self.assertEqual(first["turn_id"], "")
        self.turns.bind(session_key="route", session_id="physical", native_input=self.native)
        self.assertEqual(self.pre(first)["action"], "block")
        self.turns.session_changed(old_session_id="physical", session_id="new")
        self.assertFalse(self.turns.connected)
        self.assertEqual(len(self.native.messages), 1)

    def test_stop_retains_partial_and_exact_receipt_ownership(self):
        from hermes_gaze.browser.browser_tasks import BrowserTasks
        self.turns.session.tasks = BrowserTasks(self.turns.session)
        self.turns.submit("first", snapshot("10"))
        first = self.turns.active
        self.pre(first)
        self.turns.delta(session_id="physical", turn_id="turn", delta="Partial answer.")
        follow = self.turns.submit("follow-up", {}, item_id=first["item_id"])
        self.assertFalse(self.turns.control("cancel_request", first["item_id"], "wrong")["ok"])
        self.assertTrue(self.turns.control("cancel_request", first["item_id"], first["request_id"])["ok"])
        self.assertEqual(self.native.cancelled, first["request_id"])
        urgent = self.turns.capture(snapshot("urgent"), transcribing=True)
        self.assertTrue(urgent["ok"])
        self.assertEqual(len(self.native.messages), 1)
        self.turns.delta(session_id="physical", turn_id="turn", delta="Late text")
        self.turns.post(session_id="physical", turn_id="turn", assistant_response="Late final")
        self.turns.end(session_id="physical", turn_id="turn")
        self.assertIs(self.turns.active, first)
        self.assertEqual(first["text"], "Partial answer.")
        self.assertEqual(len(self.native.messages), 1)
        self.turns.native_receipt(first, dict(status="unknown"))
        for action in ("retry", "skip"):
            self.assertFalse(self.turns.control(action, first["item_id"], first["request_id"])["ok"])
        self.turns.native_receipt(first, dict(status="terminal", outcome="cancelled"))
        self.assertIsNone(self.turns.active)
        self.assertTrue(self.turns.paused)
        self.assertEqual(first["status"], "cancelled")
        self.assertEqual(self.turns.pending[0]["request_id"], follow["request_id"])
        self.turns.control("resume")
        self.assertEqual(len(self.native.messages), 2)

    def test_stop_before_pre_blocks_late_turn_and_not_foreign_turn(self):
        self.turns.submit("first", snapshot("10"))
        first = self.turns.active
        self.turns.control("cancel_request", first["item_id"], first["request_id"])
        self.assertIsNone(self.turns.pre(session_id="foreign", turn_id="foreign", user_message="hello"))
        self.assertEqual(self.pre(first)["action"], "block")
        self.assertIs(self.turns.active, first)
        self.turns.native_receipt(first, dict(status="terminal", outcome="cancelled"))

    def test_stop_transport_failure_still_revokes_exact_browser_task(self):
        from hermes_gaze.browser.browser_tasks import BrowserTasks
        self.turns.session.tasks = BrowserTasks(self.turns.session)
        self.turns.submit("first", snapshot("10"))
        run = self.turns.active
        self.pre(run)
        owner = dict(browser_target="tab", browser_document="doc", browser_route=1)
        self.turns.session.tasks.begin("physical", "turn", owner)
        with patch.object(self.native, "cancel", side_effect=RuntimeError("closed")):
            self.turns.control("cancel_request", run["item_id"], run["request_id"])
        self.assertTrue(self.turns.session.tasks._stopped.is_set())
        self.assertIs(self.turns.active, run)
        self.assertIn("Stop was not confirmed", run["cancel_notice"])


class NativeCancellationTransport(unittest.IsolatedAsyncioTestCase):
    async def test_stop_racing_submit_uses_only_its_admission(self):
        import asyncio
        from unittest.mock import AsyncMock
        client = NativeInput.__new__(NativeInput)
        client.logical_id = "owned"
        client.loop = asyncio.get_running_loop()
        client.receipt_admission = ""
        client.identity = ("instance", 7)
        client.home = "/profile"
        client.plugin_id = "hermes-gaze"
        client.changed = asyncio.Event()
        run = dict(request_id="request", wire="exact wire", cancel_requested=True)
        client._rpc = AsyncMock(side_effect=[
            {"admission_id": "only-this-admission"},
            {"status": "started"},
            {"status": "terminal", "ref": {"profile_id": "/profile", "session_id": "owned"},
             "authority_epoch": 7, "outcome": "cancelled"}])
        receipts = []
        with patch("hermes_gaze.runtime.native_input.consent", return_value=True):
            await asyncio.wrap_future(client.submit(run, lambda r, receipt: receipts.append(receipt)))
        self.assertEqual(client._rpc.await_args_list[1].args, ("prompt.cancel",))
        self.assertEqual(client._rpc.await_args_list[1].kwargs,
                         {"session_id": "owned", "admission_id": "only-this-admission"})
        self.assertEqual(receipts[0]["outcome"], "cancelled")

    async def test_lost_stop_reply_does_not_settle_or_replay(self):
        from unittest.mock import AsyncMock
        client = NativeInput.__new__(NativeInput)
        client.logical_id = "owned"
        client._rpc = AsyncMock(side_effect=TimeoutError)
        run = {"admission_id": "exact"}
        receipts = []
        await client._cancel(run, lambda r, receipt: receipts.append(receipt))
        await client._cancel(run, lambda r, receipt: receipts.append(receipt))
        self.assertEqual(receipts, [{"status": "cancel_unconfirmed"}])
        self.assertEqual(client._rpc.await_count, 1)
        self.assertNotIn("ended", run)


class NativeAuthTransport(unittest.TestCase):
    def test_redirect_cannot_forward_native_ticket(self):
        visited = []
        class Destination(BaseHTTPRequestHandler):
            def do_GET(self):
                visited.append(self.headers.get("Sec-WebSocket-Protocol"))
                self.send_error(403)

            def log_message(self, *args):
                pass

        destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)
        class Redirect(Destination):
            def do_GET(self):
                self.send_response(307)
                self.send_header("Location", f"ws://127.0.0.1:{destination.server_port}/api/ws")
                self.end_headers()

        redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
        for server in (destination, redirect):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(thread.join, 2)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as home:
            client = NativeInput(home, "hermes-gaze", "logical")
            with patch.object(client, "_bootstrap", return_value=(
                    ("fixture", 1), f"ws://127.0.0.1:{redirect.server_port}/api/ws", "private-ticket")):
                with self.assertRaises(NativeError):
                    client.open()
            client.close()
            client.thread.join(2)
            self.assertFalse(client.thread.is_alive())
            self.assertTrue(client.loop.is_closed())
        self.assertEqual(visited, [], "An auth ticket followed a redirect")


if __name__ == "__main__":
    unittest.main()
