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
