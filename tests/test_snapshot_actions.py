"""Snapshot policy checks against a bounded, stateful browser action adapter."""
import copy
import json
import threading
import unittest
from types import SimpleNamespace

from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.resolver.cursor_context import build_context


class BrowserActions:
    """Model live identities/epochs and record only actions actually accepted by Chrome."""
    is_connected = False
    def __init__(self):
        self.chrome = SimpleNamespace(available=lambda: False)
        self.nodes = {
            "@export": {"handle": "@export", "label": "Export CSV", "kind": "control", "tag": "button",
                        "role": "button", "type": "button", "class_name": "safe", "form_submit": False,
                        "disabled": False, "clickable": True, "fingerprint": "export:1", "connected": True},
            "@purge": {"handle": "@purge", "label": "Purge cache", "kind": "control", "tag": "button",
                       "role": "button", "type": "button", "class_name": "danger", "form_submit": False,
                       "disabled": False, "clickable": True, "fingerprint": "purge:1", "connected": True}}
        self.captures = {"snapshot-1": set(self.nodes), "snapshot-2": set(self.nodes)}
        self.active = None
        self.pending = None
        self.executed = []
        self.highlights = []
        self.after_inspect = None
        self.before_click = None
        self.fail_click = False
        self.lose_click_reply = False
        self.content_revision = 0
        self.approvals = {}

    def eval_js_once(self, expression, timeout=6, *, target=None, document=None, route=None):
        call = expression.split("window.__HERMES_GAZE_OVERLAY__.", 1)[1]
        method, args = call.split("(", 1)
        args = json.loads("[" + args.rsplit(")", 1)[0] + "]")
        if method == "clearActionConfirmation":
            self.pending = None
            return True
        if method == "activateSnapshot":
            if args[0] not in self.captures:
                return {"ok": False, "error": "expired snapshot"}
            self.active = tuple(args)
            self.pending = None
            return {"ok": True}
        if method == "requestActionConfirmation":
            self.pending = args[0]
            self.approvals[args[0]["action_id"]] = self.content_revision
            return {"ok": True}
        sid, rid, handles = args[:3]
        if (sid, rid) != self.active:
            return {"ok": False, "error": "inactive snapshot"}
        if method == "highlightSnapshot":
            if any(h not in self.captures[sid] or not self.nodes[h]["connected"] for h in handles):
                return {"ok": False, "error": "detached target"}
            self.highlights.append(list(handles))
            return {"ok": True}
        handle = handles
        node = self.nodes.get(handle)
        if handle not in self.captures[sid] or not node or not node["connected"]:
            return {"ok": False, "error": "detached target"}
        if method == "inspectSnapshot":
            result = {"ok": True, **copy.deepcopy(node)}
            if self.after_inspect:
                callback, self.after_inspect = self.after_inspect, None
                callback()
            return result
        if method == "clickSnapshot":
            if self.before_click:
                self.before_click()
            if len(args) > 4 and args[4] is not None:
                revision = self.approvals.pop(args[4], None)
                if revision is None or revision != self.content_revision:
                    return {"ok": False, "executed": False, "error": "approval content changed"}
            if self.fail_click or node["disabled"] or not node["clickable"] or node["fingerprint"] != args[3]:
                return {"ok": False, "executed": False, "error": "target changed or click rejected"}
            self.executed.append(handle)
            if self.lose_click_reply:
                raise ConnectionError("reply lost after execution")
            return {"ok": True, "executed": True}
        raise AssertionError(method)


class TestSnapshotActions(unittest.TestCase):
    def setUp(self):
        self.session = GazeSession()
        self.browser = BrowserActions()
        self.session._cdp = self.browser
        self.payload = {"ok": True, "snapshot_id": "snapshot-1", "handles": {h: {"label": n["label"]}
                       for h, n in self.browser.nodes.items()}, "utterance": "click this",
                        "context": build_context(["Export CSV"], "click this", "button Export CSV (@export)")}
        self.rid = self.session.store_hover_snapshot(self.payload)
        self.actions = self.session.actions

    def request_purge(self):
        result = self.actions.click("@purge", self.rid)
        self.assertTrue(result["confirmation_required"])
        self.assertNotIn("action_id", result)
        self.assertEqual(self.browser.executed, [])
        return dict(self.browser.pending)

    def test_safe_click_and_highlight_use_current_handles(self):
        self.assertTrue(self.actions.highlight(["@export", "@purge"], self.rid)["ok"])
        self.assertEqual(self.browser.highlights, [["@export", "@purge"]])
        self.assertTrue(self.actions.click("@export", self.rid)["executed"])
        self.assertEqual(self.browser.executed, ["@export"])
        self.assertFalse(self.actions.click("#arbitrary", self.rid)["ok"])
        self.assertFalse(self.actions.highlight(["@missing"], self.rid)["ok"])
        self.assertFalse(self.actions.click("@export", self.rid - 1)["ok"])

    def test_json_integer_epoch_accepts_decimal_not_bool_fraction_or_nonfinite(self):
        for epoch in (True, False, str(self.rid), self.rid + .5, float('nan'), float('inf'), self.rid - 1.0):
            with self.subTest(epoch=epoch):
                self.assertFalse(self.actions.click("@export", epoch)["ok"])
        self.assertEqual(self.browser.executed, [])
        self.assertTrue(self.actions.click("@export", float(self.rid))["executed"])
        pending = self.actions.request_commit("@purge", float(self.rid))
        self.assertTrue(pending["confirmation_required"])
        self.assertEqual(self.browser.executed, ["@export"])
        self.assertTrue(self.actions.confirm(self.browser.pending["action_id"], self.rid, True)["executed"])
        self.assertEqual(self.browser.executed, ["@export", "@purge"])

    def test_live_policy_ignores_utterance_and_protects_ambiguous_controls(self):
        for field, value in [("label", "Delete data"), ("label", "Do it"), ("label", "Close account"),
                             ("label", "Cancel membership"), ("class_name", "btn-danger"), ("form_submit", True)]:
            with self.subTest(field=field, value=value):
                original = copy.deepcopy(self.browser.nodes["@export"])
                self.browser.nodes["@export"][field] = value
                rid = self.session.store_hover_snapshot(copy.deepcopy(self.payload))
                self.assertTrue(self.actions.click("@export", rid)["confirmation_required"])
                self.assertEqual(self.browser.executed, [])
                self.browser.nodes["@export"].update(original)
        self.browser.nodes["@export"]["label"] = "Next"
        rid = self.session.store_hover_snapshot({**self.payload, "utterance": "do not submit or delete"})
        self.assertTrue(self.actions.click("@export", rid)["executed"])

    def test_request_commit_forces_safe_control_and_content_revision_is_atomic(self):
        result = self.actions.request_commit("@export", self.rid)
        self.assertTrue(result["confirmation_required"])
        self.assertNotIn("action_id", result)
        pending = dict(self.browser.pending)
        self.browser.before_click = lambda: setattr(self.browser, "content_revision", 2)
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        self.assertEqual(self.browser.executed, [])
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])

    def test_sensitive_live_descriptor_is_rejected_not_confirmed(self):
        self.browser.nodes["@purge"]["sensitive"] = True
        self.assertFalse(self.actions.request_commit("@purge", self.rid)["ok"])
        self.assertIsNone(self.browser.pending)

    def test_confirm_is_single_use_and_forgery_does_not_approve(self):
        pending = self.request_purge()
        self.assertFalse(self.actions.confirm("forged", self.rid, True)["ok"])
        self.assertFalse(self.actions.confirm("forged-\ud800", self.rid, True)["ok"])
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid + 1, True)["ok"])
        self.assertEqual(self.browser.executed, [])
        self.assertTrue(self.actions.confirm(pending["action_id"], self.rid, True)["executed"])
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        self.assertEqual(self.browser.executed, ["@purge"])

    def test_cancel_change_and_replacement_consume_confirmation(self):
        pending = self.request_purge()
        self.assertTrue(self.actions.confirm(pending["action_id"], self.rid, False)["cancelled"])
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        pending = self.request_purge()
        self.browser.nodes["@purge"]["fingerprint"] = "purge:changed"
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        pending = self.request_purge()
        self.session.store_hover_snapshot({**self.payload, "snapshot_id": "snapshot-2"})
        self.assertIsNone(self.browser.pending)
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        self.assertEqual(self.browser.executed, [])

    def test_unavailable_disabled_noninteractive_and_failed_click_are_honest(self):
        for field, value in [("connected", False), ("disabled", True), ("clickable", False)]:
            self.browser.nodes["@export"][field] = value
            self.assertFalse(self.actions.click("@export", self.rid)["ok"])
            self.browser.nodes["@export"][field] = not value
        self.browser.fail_click = True
        self.assertFalse(self.actions.click("@export", self.rid)["executed"])
        self.assertEqual(self.browser.executed, [])
        self.browser.nodes["@export"]["connected"] = False
        result = self.actions.highlight(["@export"], self.rid)
        self.assertFalse(result["ok"])
        self.assertNotIn("rect", result)

    def test_changed_target_between_inspect_and_click_is_not_clicked(self):
        self.browser.after_inspect = lambda: self.browser.nodes["@export"].update(fingerprint="replacement")
        self.assertFalse(self.actions.click("@export", self.rid)["executed"])
        self.assertEqual(self.browser.executed, [])
        self.browser.after_inspect = lambda: self.session.store_hover_snapshot(self.payload)
        self.assertFalse(self.actions.click("@export", self.rid)["executed"])
        self.assertEqual(self.browser.executed, [])

    def test_transport_failure_after_execution_does_not_replay(self):
        self.browser.lose_click_reply = True
        result = self.actions.click("@export", self.rid)
        self.assertFalse(result["ok"])
        self.assertIsNone(result["executed"])
        self.assertEqual(self.browser.executed, ["@export"])
        self.assertFalse(self.actions.click("@export", self.rid)["ok"])

    def test_pending_invalidated_by_simulated_resolution_and_read_only_turn(self):
        pending = self.request_purge()
        self.session.new_resolution(None)
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        rid = self.session.store_hover_snapshot({**self.payload, "actions_allowed": False})
        self.assertFalse(self.actions.click("@export", rid)["ok"])
        self.assertEqual(self.browser.executed, [])

    def test_disconnect_revokes_pending_and_safe_action_ownership(self):
        pending = self.request_purge()
        self.session.clear_hover_snapshot()
        self.assertFalse(self.actions.confirm(pending["action_id"], self.rid, True)["ok"])
        self.assertFalse(self.actions.click("@export", self.rid)["ok"])
        self.assertEqual(self.browser.executed, [])

    def test_activation_failure_and_capture_copy_and_context_bound(self):
        self.payload["handles"].clear()
        self.assertTrue(self.actions.click("@export", self.rid)["executed"])
        payload = {**self.payload, "snapshot_id": "expired"}
        rid = self.session.store_hover_snapshot(payload)
        self.assertLessEqual(len(payload["context"]), 6000)
        self.assertIn(f"\nResolution: {rid}\n", payload["context"])
        self.assertFalse(self.actions.click("@export", rid)["ok"])
        rid = self.session.store_hover_snapshot({**self.payload, "ok": False})
        self.assertFalse(self.actions.highlight(["@export"], rid)["ok"])
        malformed = {**self.payload, "context": "x" * 7000}
        rid = self.session.store_hover_snapshot(malformed)
        self.assertFalse(malformed["ok"])
        self.assertEqual(malformed["context"], "")
        self.assertFalse(self.actions.highlight(["@export"], rid)["ok"])

    def test_resolution_change_serializes_after_inflight_click(self):
        entered, release, stored = threading.Event(), threading.Event(), threading.Event()
        self.browser.before_click = lambda: (entered.set(), release.wait(2))
        click = threading.Thread(target=lambda: self.actions.click("@export", self.rid))
        def replace():
            self.session.store_hover_snapshot({**self.payload, "snapshot_id": "snapshot-2"})
            stored.set()
        replacement = threading.Thread(target=replace)
        click.start()
        try:
            self.assertTrue(entered.wait(2))
            replacement.start()
            self.assertFalse(stored.wait(.03))
        finally:
            release.set()
            click.join(2)
        replacement.join(2)
        self.assertTrue(stored.is_set())
        self.assertEqual(self.browser.executed, ["@export"])
        self.assertFalse(self.actions.click("@export", self.rid)["ok"])



if __name__ == "__main__":
    unittest.main()
