"""Behaviour contracts for service.py: intent dispatch over the __hermesGazeIntent binding.

Every test drives a REAL ``GazeSession()`` — the pushed path (pointer + wire fixations +
wire candidates carried inside the resolve intent) needs no Chrome and no CDP transport.
Sessions are pointed at a dead CDP port so the suite stays hermetic even if a debuggable
Chrome is running on :9222. ``handle_intent`` replies are callback-style: we pass
``replies.append`` and inspect the payload dict it receives.
"""

from __future__ import annotations

import base64
import time
import unittest
from typing import Any, Dict, List
from unittest import mock

from hermes_gaze import service
from hermes_gaze.browser.cdp_bridge import GazeSession
from hermes_gaze.config import GazeConfig


def _wire_candidates() -> List[Dict[str, Any]]:
    """Three toolbar buttons near the pointer (viewport coords), benchmark_page.html style."""

    def _btn(cid: str, label: str, rect: List[float], **extra: Any) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": cid,
            "tag": "button",
            "role": "button",
            "label": label,
            "selector": f"#{cid}",
            "rect_vp": list(rect),
            "rect_doc": list(rect),
            "is_interactive": True,
            "is_container": False,
            "is_destructive": False,
            "summary": f"Button: {label}",
            "consequence": f"Triggers {label}",
        }
        d.update(extra)
        return d

    return [
        _btn("btn-purge-cache", "Purge Cache", [352.0, 278.0, 90.0, 34.0], is_destructive=True),
        _btn("btn-export-csv", "Export CSV", [452.0, 278.0, 92.0, 34.0]),
        _btn("btn-generate-report", "Generate Report", [560.0, 278.0, 118.0, 34.0]),
    ]


def _pointer() -> Dict[str, float]:
    """Pointer parked inside btn-export-csv's rect (452..544 x, 278..312 y)."""
    return {"x_vp": 498.0, "y_vp": 295.0, "scroll_x": 0.0, "scroll_y": 0.0}


def _wire_fixations(now: float) -> List[Dict[str, Any]]:
    """Recent hover fixations clustered on the pointer position."""
    pts = [(496.0, 293.0), (500.0, 296.0), (499.0, 294.0)]
    return [
        {
            "x_doc": x,
            "y_doc": y,
            "x_vp": x,
            "y_vp": y,
            "t_start": now - 0.55 + i * 0.15,
            "t_end": now - 0.43 + i * 0.15,
            "duration_ms": 120.0,
            "sigma": 24.0,
            "source": "hover",
        }
        for i, (x, y) in enumerate(pts)
    ]


def _pushed(now: float) -> Dict[str, Any]:
    return {"pointer": _pointer(), "fixations": _wire_fixations(now), "candidates": _wire_candidates()}


class TestServiceIntents(unittest.TestCase):
    def setUp(self) -> None:
        # Port 1 is never a debuggable Chrome: keeps every pull path deterministic.
        self.session = GazeSession(cdp_http_url="http://127.0.0.1:1")
        self.addCleanup(self.session.close)
        service.set_runtime(GazeConfig(cdp_url="http://127.0.0.1:1"))
        # service.handle_intent reads its session via service.get_shared_session —
        # point it at our real GazeSession (kept live all test for async dispatch).
        patcher = mock.patch.object(service, "get_shared_session", return_value=self.session)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- helpers ---------------------------------------------------------

    def _await_reply(self, replies: List[Dict[str, Any]], timeout: float = 2.0) -> Dict[str, Any]:
        deadline = time.time() + timeout
        while not replies and time.time() < deadline:
            time.sleep(0.01)
        self.assertTrue(replies, "handle_intent produced no reply")
        return replies[-1]

    def _resolve_via_intent(self) -> Dict[str, Any]:
        replies: List[Dict[str, Any]] = []
        service.handle_intent(
            {
                "id": 41,
                "type": "resolve",
                "utterance": "what does this do",
                **_pushed(time.time()),
            },
            replies.append,
        )
        return self._await_reply(replies)

    # -- resolve ----------------------------------------------------------

    def test_resolve_now_pushed_path(self) -> None:
        before = self.session.resolution_id
        res = service.resolve_now(
            self.session, utterance="what does this do", pushed=_pushed(time.time())
        )
        self.assertNotEqual(res.get("ok"), False)
        self.assertEqual(res["intent_class"], "read_only")
        self.assertEqual(res["decision"], "pin_immediate")
        self.assertTrue(res["ranked"])
        self.assertEqual(res["top"]["id"], "btn-export-csv")
        self.assertIn("chrome_connected", res)
        self.assertIn("mode", res)
        # Resolution epoch bumped + stored so a later choose can validate against it.
        self.assertGreater(self.session.resolution_id, before)
        self.assertIsNotNone(self.session.last_resolution)

    def test_handle_intent_resolve_reply_needs_explain(self) -> None:
        reply = self._resolve_via_intent()
        self.assertIs(reply.get("ok"), True)
        # "what does this do" is read_only -> pin_immediate -> overlay should ask for an explanation.
        self.assertIs(reply.get("needs_explain"), True)
        self.assertGreaterEqual(self.session.resolution_id, 1)

    # -- choose ------------------------------------------------------------

    def test_choose_epoch_guard(self) -> None:
        self._resolve_via_intent()
        self.assertGreaterEqual(self.session.resolution_id, 1)

        replies: List[Dict[str, Any]] = []
        service.handle_intent(
            {
                "id": 50,
                "type": "choose",
                "resolution_id": self.session.resolution_id + 99,
                "candidate_index": 1,
                "modality": "semantic_lens",
                "execute": True,
            },
            replies.append,
        )
        stale_reply = self._await_reply(replies)
        self.assertIs(stale_reply.get("ok"), False)
        self.assertIn("stale", str(stale_reply.get("error", "")).lower())

        replies.clear()
        service.handle_intent(
            {
                "id": 51,
                "type": "choose",
                "resolution_id": self.session.resolution_id,
                "candidate_index": 1,
                "modality": "semantic_lens",
                "execute": True,
            },
            replies.append,
        )
        ok_reply = self._await_reply(replies)
        self.assertIs(ok_reply.get("ok"), True)

    def test_choose_without_active_resolution(self) -> None:
        replies: List[Dict[str, Any]] = []
        service.handle_intent(
            {
                "id": 52,
                "type": "choose",
                "resolution_id": 1,
                "candidate_index": 1,
                "modality": "semantic_lens",
                "execute": True,
            },
            replies.append,
        )
        reply = self._await_reply(replies)
        self.assertIs(reply.get("ok"), False)
        self.assertIn("no active resolution", str(reply.get("error", "")).lower())

    # -- transcribe ---------------------------------------------------------

    def test_transcribe_over_bound_rejected(self) -> None:
        """A ~24MB base64 payload is far over the ~16MB bound and must be rejected, not decoded."""
        replies: List[Dict[str, Any]] = []
        service.handle_intent(
            {
                "id": 60,
                "type": "transcribe",
                "audio_base64": "QUJD" * 6_000_000,
                "mime_type": "audio/webm",
                "sample_rate": 16000,
            },
            replies.append,
        )
        reply = self._await_reply(replies)
        self.assertIs(reply.get("ok"), False)

    def test_transcribe_small_garbage_degrades_to_reply(self) -> None:
        """Tiny undecodable audio must reply (ok False, or ok True with empty text) — never raise."""
        replies: List[Dict[str, Any]] = []
        service.handle_intent(
            {
                "id": 61,
                "type": "transcribe",
                "audio_base64": base64.b64encode(b"not real audio").decode("ascii"),
                "mime_type": "audio/webm",
                "sample_rate": 16000,
            },
            replies.append,
        )
        reply = self._await_reply(replies, timeout=120.0)
        if reply.get("ok"):
            self.assertFalse(str(reply.get("text") or "").strip())
        else:
            self.assertIs(reply.get("ok"), False)

    # -- configure / unknown --------------------------------------------------

    def test_configure_intent_flips_mode(self) -> None:
        replies: List[Dict[str, Any]] = []
        service.handle_intent(
            {
                "id": 70,
                "type": "configure",
                "mode": "simulated",
                "sigma_px": 140.0,
            },
            replies.append,
        )
        reply = self._await_reply(replies)
        self.assertIs(reply.get("ok"), True)
        self.assertEqual(self.session.tracker.mode, "simulated")
        self.assertAlmostEqual(self.session.tracker.sigma_px, 140.0)

    def test_unknown_intent_type_replies_ok_false(self) -> None:
        replies: List[Dict[str, Any]] = []
        service.handle_intent({"id": 80, "type": "frobnicate"}, replies.append)
        reply = self._await_reply(replies)
        self.assertIs(reply.get("ok"), False)
        self.assertIn("unknown", str(reply.get("error", "")).lower())

    # -- ingest watermark + no fabricated fallbacks ------------------------------

    def test_ingest_watermark_dedup(self) -> None:
        """Re-ingesting identical wire fixations must not grow the ring buffer."""
        now = time.time()
        fixations = [
            {
                "x_doc": 100.0 + i * 80.0,
                "y_doc": 100.0 + i * 80.0,
                "x_vp": 100.0 + i * 80.0,
                "y_vp": 100.0 + i * 80.0,
                "t_start": now - 3.0 + i * 0.5 - 0.12,
                "t_end": now - 3.0 + i * 0.5,
                "duration_ms": 120.0,
                "sigma": 24.0,
            }
            for i in range(4)
        ]
        self.session.ingest(fixations)
        first = len(self.session.ring_buffer.snapshot(now))
        self.assertEqual(first, 4)
        self.session.ingest(fixations)
        self.session.ingest(list(fixations))
        self.assertEqual(len(self.session.ring_buffer.snapshot(now)), first)

    def test_no_fabricated_fallbacks(self) -> None:
        """Empty candidates/fixations produce {"ok": False}, never a synthetic dashboard stand-in."""
        res = service.resolve_now(
            self.session,
            utterance="x",
            pushed={"pointer": _pointer(), "fixations": [], "candidates": []},
        )
        self.assertIs(res.get("ok"), False)
        # Pull path on a dead CDP port must fail honestly too (no candidates fetched).
        res_pull = service.resolve_now(self.session, utterance="x")
        self.assertIs(res_pull.get("ok"), False)


if __name__ == "__main__":
    unittest.main()
