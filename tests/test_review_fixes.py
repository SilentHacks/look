"""Regression tests for defects found by the independent branch review.

Covers: intent nonce auth, whisper audio_epoch -> wall-clock word times, falsy
``start`` handling in the temporal aligner, terminal per-tab transport teardown,
non-blocking configure, honest no-pointer/no-candidate behaviour, choose
consuming its resolution, and LLM rerank actually re-ordering ``primary_ranked``.
"""

from __future__ import annotations

import tempfile
import time
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

from hermes_gaze.runtime import service
from hermes_gaze.browser.cdp_bridge import CdpSession, GazeSession
from hermes_gaze.config import GazeConfig
from hermes_gaze.resolver import bayesian_fusion
from hermes_gaze.resolver.temporal_aligner import extract_deictic_anchors

try:
    import numpy as np
except ImportError:  # pragma: no cover - system python may lack numpy
    np = None  # type: ignore[assignment]


def _candidates() -> List[Dict[str, Any]]:
    def _btn(cid: str, label: str, rect: List[float], **extra: Any) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": cid, "tag": "button", "role": "button", "label": label,
            "selector": f"#{cid}", "rect_vp": list(rect), "rect_doc": list(rect),
            "is_interactive": True, "is_container": False, "is_destructive": False,
            "summary": f"Button: {label}", "consequence": f"Triggers {label}",
        }
        d.update(extra)
        return d

    return [
        _btn("btn-purge-cache", "Purge Cache", [352.0, 278.0, 90.0, 34.0], is_destructive=True),
        _btn("btn-export-csv", "Export CSV", [452.0, 278.0, 92.0, 34.0]),
        _btn("btn-generate-report", "Generate Report", [560.0, 278.0, 118.0, 34.0]),
    ]


def _pushed(now: float) -> Dict[str, Any]:
    return {
        "pointer": {"x_vp": 498.0, "y_vp": 295.0, "scroll_x": 0.0, "scroll_y": 0.0},
        "fixations": [
            {"x_doc": 499.0, "y_doc": 295.0, "x_vp": 499.0, "y_vp": 295.0,
             "t_start": now - 0.25, "t_end": now - 0.13, "duration_ms": 120.0,
             "sigma": 24.0, "source": "hover"},
        ],
        "candidates": _candidates(),
    }


class TestIntentNonce(unittest.TestCase):
    def setUp(self) -> None:
        self.session = GazeSession(cdp_http_url="http://127.0.0.1:1")
        self.addCleanup(self.session.close)
        service.set_runtime(GazeConfig(cdp_url="http://127.0.0.1:1"))
        patcher = mock.patch.object(service, "get_shared_session", return_value=self.session)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_or_wrong_nonce_rejected(self) -> None:
        replies: List[Dict[str, Any]] = []
        service.handle_intent({"type": "configure", "mode": "simulated"}, replies.append)
        self.assertIs(replies[-1].get("ok"), False)
        self.assertIn("unauthorized", str(replies[-1].get("error", "")))
        service.handle_intent(
            {"type": "configure", "mode": "simulated", "nonce": "forged"}, replies.append
        )
        self.assertIs(replies[-1].get("ok"), False)
        self.assertIn("unauthorized", str(replies[-1].get("error", "")))

    def test_correct_nonce_reaches_dispatch(self) -> None:
        replies: List[Dict[str, Any]] = []
        service.handle_intent(
            {"type": "configure", "mode": "simulated", "nonce": self.session._intent_nonce},
            replies.append,
        )
        # push fails on the dead port (ok False), but dispatch ran: mode was stored.
        self.assertEqual(self.session.tracker.mode, "simulated")
        self.assertNotIn("unauthorized", str(replies[-1].get("error", "")))


class TestSessionLifecycle(unittest.TestCase):
    def test_closed_tab_cannot_reopen_on_delayed_attachment_or_read(self) -> None:
        import threading
        from hermes_gaze.browser.companion import Companion
        companion = Companion("http://127.0.0.1:1")
        tab = CdpSession(companion.http_url)
        companion._tabs["tab"] = tab
        entered, release, finished = (threading.Event() for _ in range(3))
        original = tab.connect
        connected = []
        def delayed():
            entered.set()
            release.wait(2)
            try:
                connected.append(original())
            finally:
                finished.set()
        with mock.patch.object(tab, "connect", side_effect=delayed):
            companion._attach(tab)
            self.assertTrue(entered.wait(1))
            try:
                companion.close()
            finally:
                release.set()
            self.assertTrue(finished.wait(2))
        self.assertEqual(connected, [False])
        self.assertEqual(companion._tabs, {})
        self.assertIsNone(tab._thread)
        with self.assertRaises(ConnectionError):
            tab.eval_js("true")
        self.assertIsNone(tab._thread)

    def test_close_discards_queued_capture_intents(self) -> None:
        """An old record_start cannot open the microphone after Stop returns."""
        import json
        import threading
        cdp = CdpSession("http://127.0.0.1:1")
        release, entered = threading.Event(), threading.Event()
        handler = mock.Mock()
        cdp.set_intent_handler(handler)
        def block():
            entered.set()
            release.wait(2)
        running = cdp._handler_pool.submit(block)
        self.assertTrue(entered.wait(1))
        try:
            cdp._dispatch_intent(json.dumps({"type": "record_start"}))
            cdp.close()
        finally:
            release.set()
            running.result(2)
            cdp._handler_pool.shutdown(wait=True)
        handler.assert_not_called()

    def test_configure_is_store_only_when_disconnected(self) -> None:
        """configure() never connects/injects — safe to call during plugin register()."""
        session = GazeSession(cdp_http_url="http://127.0.0.1:1")
        self.addCleanup(session.close)
        pushed = session.configure(mode="simulated", sigma_px=140.0)
        self.assertIs(pushed, False)  # no live ws -> nothing pushed
        self.assertEqual(session.tracker.mode, "simulated")
        self.assertAlmostEqual(session.tracker.sigma_px, 140.0)
        # Stored opts are what _push_overlay_config will send post-inject.
        self.assertEqual(session.cdp.overlay_config["mode"], "simulated")
        self.assertFalse(session.overlay_is_live())


class TestHonestNoPointer(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(service, "_record_path", return_value=Path(directory) / "replay.jsonl"))
        self.session = GazeSession(cdp_http_url="http://127.0.0.1:1")
        self.session.configure(mode="simulated")
        self.addCleanup(self.session.close)

    def test_fetch_returns_empty_when_unreachable(self) -> None:
        """Unreachable Chrome yields no candidates/evidence, never stale candidates."""
        self.session.last_candidates = ["stale"]  # type: ignore[list-item]
        self.assertEqual(self.session.fetch_live_state_and_candidates(), ([], {}))
        self.assertEqual(self.session.last_candidates, [])

    def test_null_pointer_records_no_fixation(self) -> None:
        """Overlay pointerX/Y are null pre-mousemove — they must not become a fixation."""
        now = time.time()
        pushed = _pushed(now)
        pushed["pointer"] = {"x_vp": None, "y_vp": None}
        res = service.resolve_now(self.session, utterance="click this", pushed=pushed)
        self.assertNotEqual(res.get("ok"), False)
        for fix in self.session.ring_buffer.snapshot(time.time()):
            self.assertGreater(fix.x_doc, 1.0)
            self.assertGreater(fix.y_doc, 1.0)

    def test_bad_mode_and_empty_utterance_fail_honestly(self) -> None:
        res = service.resolve_now(self.session, utterance="x", mode="unknown", pushed=_pushed(time.time()))
        self.assertIs(res.get("ok"), False)
        res = service.resolve_now(self.session, utterance="   ", pushed=_pushed(time.time()))
        self.assertIs(res.get("ok"), False)


class TestChooseConsumesResolution(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(service, "_record_path", return_value=Path(directory) / "replay.jsonl"))
        self.session = GazeSession(cdp_http_url="http://127.0.0.1:1")
        self.session.configure(mode="simulated")
        self.addCleanup(self.session.close)

    def test_second_choose_fails_after_success(self) -> None:
        res = service.resolve_now(self.session, utterance="click this", pushed=_pushed(time.time()))
        self.assertNotEqual(res.get("ok"), False)
        first = self.session.choose(resolution_id=self.session.resolution_id, candidate_index=1)
        self.assertIs(first.get("ok"), True)
        self.assertFalse(first["executed"])
        self.assertIsNone(self.session.last_resolution)
        second = self.session.choose(resolution_id=self.session.resolution_id, candidate_index=1)
        self.assertIs(second.get("ok"), False)


class TestTemporalAlignmentEpochs(unittest.TestCase):
    def test_word_start_zero_is_a_real_timestamp(self) -> None:
        """start: 0.0 must not fall back to t_arm (the old `or` falsy trap)."""
        anchors = extract_deictic_anchors(
            "press this", t_arm=1000.0,
            word_timestamps=[{"word": "this", "start": 0.0, "end": 0.4}],
        )
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0].t_anchor, 0.0)

    def test_epoch_shifted_words_anchor_correctly(self) -> None:
        epoch = 1_700_000_000.0
        anchors = extract_deictic_anchors(
            "what does this do", t_arm=epoch + 3.2,
            word_timestamps=[{"word": "this", "start": epoch + 1.5, "end": epoch + 1.8}],
        )
        self.assertEqual(anchors[0].t_anchor, epoch + 1.5)

    @unittest.skipIf(np is None, "numpy not installed")
    def test_transcribe_shifts_words_by_audio_epoch(self) -> None:
        from hermes_gaze.audio import voice

        seg = types.SimpleNamespace(
            text="press this",
            words=[
                types.SimpleNamespace(word="press", start=0.2, end=0.5),
                types.SimpleNamespace(word="this", start=0.6, end=0.9),
            ],
        )

        class _FakeModel:
            def transcribe(self, audio: Any, **kw: Any) -> Any:
                return [seg], {}

        audio = np.array([0.1, -0.1] * 4000, dtype=np.float32)
        with mock.patch.object(voice, "decode_audio_to_float32", return_value=audio), \
                mock.patch.object(voice, "_get_coreml_runner", return_value=None), \
                mock.patch.object(voice, "_get_parakeet_model", return_value=None), \
                mock.patch.object(voice, "get_whisper_model", return_value=_FakeModel()):
            epoch = 1_700_000_000.0
            _text, words = voice.transcribe_audio_buffer(b"\x01\x02", audio_epoch=epoch)
            self.assertAlmostEqual(words[0]["start"], epoch + 0.2)
            self.assertAlmostEqual(words[1]["end"], epoch + 0.9)
            # without an epoch the raw audio-relative values come through unchanged
            _t2, words2 = voice.transcribe_audio_buffer(b"\x01\x02")
            self.assertAlmostEqual(words2[0]["start"], 0.2)


class TestLlmRerankReorders(unittest.TestCase):
    def test_rerank_sorts_primary_ranked(self) -> None:
        """The LLM rerank must reorder resolve_candidates' own list, not a slice copy."""
        now = time.time()
        # Three near-identical candidates around the fixation -> ambiguous -> rerank fires.
        candidates = [
            bayesian_fusion.CandidateElement.from_wire(
                {"id": f"c{i}", "tag": "button", "role": "button", "label": f"Option {i}",
                 "selector": f"#c{i}", "rect_vp": [450.0, 280.0 + i * 40, 90, 30],
                 "rect_doc": [450.0, 280.0 + i * 40, 90, 30], "is_interactive": True}
            )
            for i in range(3)
        ]
        fixations = [
            bayesian_fusion.FixationSample(  # type: ignore[attr-defined]
                x_doc=495.0, y_doc=335.0, x_vp=495.0, y_vp=335.0,
                t_start=now - 0.2, t_end=now - 0.1, duration_ms=120.0,
                sigma_x=160.0, sigma_y=160.0, source="hover",
            )
        ] if hasattr(bayesian_fusion, "FixationSample") else []
        if not fixations:
            from hermes_gaze.tracker.simulated_gaze import FixationSample

            fixations = [
                FixationSample(
                    x_doc=495.0, y_doc=335.0, x_vp=495.0, y_vp=335.0,
                    t_start=now - 0.2, t_end=now - 0.1, duration_ms=120.0,
                    sigma_x=160.0, sigma_y=160.0, source="hover",
                )
            ]

        class _Llm:
            def complete_structured(self, **kw: Any) -> Any:
                return types.SimpleNamespace(parsed={
                    "candidates": [
                        {"id": "c0", "score": 0.05},
                        {"id": "c1", "score": 0.05},
                        {"id": "c2", "score": 1.0, "consequence": "opens the thing"},
                    ]
                })

        res = bayesian_fusion.resolve_candidates(
            candidates, fixations, "click this", t_arm=now, llm_client=_Llm()
        )
        self.assertEqual(res.ranked[0].candidate.id, "c2")
        self.assertEqual(res.ranked[0].consequence_preview, "opens the thing")


class TestParakeetBackend(unittest.TestCase):
    def test_tokens_to_words_groups_sentencepiece_boundaries(self) -> None:
        from hermes_gaze.audio import voice

        toks = [
            types.SimpleNamespace(text="▁What", start=0.0),
            types.SimpleNamespace(text="▁happ", start=0.319),
            types.SimpleNamespace(text="ens", start=0.479),
            types.SimpleNamespace(text="▁this", start=1.356),
            types.SimpleNamespace(text="?", start=1.915),
        ]
        words = voice._tokens_to_words(toks, end_s=2.5, epoch_off=0.0)
        self.assertEqual([w["word"] for w in words], ["What", "happens", "this?"])
        self.assertAlmostEqual(words[1]["start"], 0.319)
        self.assertAlmostEqual(words[1]["end"], 1.356)
        self.assertAlmostEqual(words[-1]["end"], 2.5)

    def test_tokens_to_words_word_level_tokens(self) -> None:
        """parakeet-mlx emits word-level tokens without ▁ markers — each stays its own word."""
        from hermes_gaze.audio import voice

        toks = [
            types.SimpleNamespace(text="What", start=0.0, end=0.3),
            types.SimpleNamespace(text="does", start=0.35, end=0.6),
            types.SimpleNamespace(text="this", start=0.65, end=0.9),
        ]
        words = voice._tokens_to_words(toks, end_s=1.0, epoch_off=0.0)
        self.assertEqual([w["word"] for w in words], ["What", "does", "this"])
        self.assertAlmostEqual(words[2]["start"], 0.65)
        self.assertAlmostEqual(words[2]["end"], 0.9)

    def test_tokens_to_words_leading_space_boundaries(self) -> None:
        """parakeet-mlx subwords mark word starts with a leading space."""
        from hermes_gaze.audio import voice

        toks = [
            types.SimpleNamespace(text=" C", start=0.16, end=0.24),
            types.SimpleNamespace(text="om", start=0.24, end=0.32),
            types.SimpleNamespace(text="p", start=0.32, end=0.40),
            types.SimpleNamespace(text="are", start=0.40, end=0.56),
            types.SimpleNamespace(text=" this", start=0.56, end=0.72),
            types.SimpleNamespace(text=".", start=1.60, end=1.92),
        ]
        words = voice._tokens_to_words(toks, end_s=1.92, epoch_off=0.0)
        self.assertEqual([w["word"] for w in words], ["Compare", "this."])
        self.assertAlmostEqual(words[0]["start"], 0.16)
        self.assertAlmostEqual(words[0]["end"], 0.56)
        self.assertAlmostEqual(words[1]["end"], 1.92)

    def test_tokens_to_words_applies_epoch_offset(self) -> None:
        from hermes_gaze.audio import voice

        toks = [types.SimpleNamespace(text="▁this", start=0.5)]
        words = voice._tokens_to_words(toks, end_s=1.0, epoch_off=1_700_000_000.0)
        self.assertAlmostEqual(words[0]["start"], 1_700_000_000.5)

    @unittest.skipIf(np is None, "numpy not installed")
    def test_parakeet_result_maps_to_contract(self) -> None:
        """The auto backend must return (text, [{word,start,end}]) from a runner result."""
        from hermes_gaze.audio import voice

        res = types.SimpleNamespace(
            text="press this",
            sentences=[types.SimpleNamespace(
                text="press this", start=0.0, end=1.5,
                tokens=[
                    types.SimpleNamespace(text="▁press", start=0.2, end=0.8),
                    types.SimpleNamespace(text="▁this", start=0.9, end=1.4),
                ],
            )],
        )

        class _Model:
            def transcribe(self, path: str) -> Any:
                return res

        audio = np.array([0.1, -0.1] * 4000, dtype=np.float32)
        with mock.patch.object(voice, "decode_audio_to_float32", return_value=audio), \
                mock.patch.object(voice, "_get_coreml_runner", return_value=None), \
                mock.patch.object(voice, "_get_parakeet_model", return_value=_Model()):
            text, words = voice.transcribe_audio_buffer(b"\x01\x02", audio_epoch=100.0)
            self.assertEqual(text, "press this")
            self.assertEqual([w["word"] for w in words], ["press", "this"])
            self.assertAlmostEqual(words[1]["start"], 100.9)
            self.assertAlmostEqual(words[1]["end"], 101.4)

    @unittest.skipIf(np is None, "numpy not installed")
    def test_coreml_result_maps_to_contract(self) -> None:
        """A TranscriptionResult must map to (text, [{word,start,end}]) via the ▁ grouping."""
        from hermes_gaze.audio import voice

        res = types.SimpleNamespace(
            text="press this",
            tokens=[
                types.SimpleNamespace(text="▁press", start=0.2),
                types.SimpleNamespace(text="▁this", start=0.9),
            ],
            segments=[types.SimpleNamespace(start=0.2, end=1.5, text="press this")],
        )

        class _Runner:
            def transcribe_array(self, audio: Any) -> Any:
                return res

        audio = np.array([0.1, -0.1] * 4000, dtype=np.float32)
        with mock.patch.object(voice, "decode_audio_to_float32", return_value=audio), \
                mock.patch.object(voice, "_get_coreml_runner", return_value=_Runner()):
            text, words = voice.transcribe_audio_buffer(b"\x01\x02", audio_epoch=100.0)
            self.assertEqual(text, "press this")
            self.assertEqual([w["word"] for w in words], ["press", "this"])
            self.assertAlmostEqual(words[1]["start"], 100.9)
            self.assertAlmostEqual(words[1]["end"], 101.5)

    @unittest.skipIf(np is None, "numpy not installed")
    def test_coreml_failure_falls_to_parakeet_mlx(self) -> None:
        """When the CoreML runner raises the auto chain must reach parakeet-mlx."""
        from hermes_gaze.audio import voice

        res = types.SimpleNamespace(
            text="this",
            sentences=[types.SimpleNamespace(
                text="this", start=0.0, end=0.5,
                tokens=[types.SimpleNamespace(text=" this", start=0.1, end=0.4)],
            )],
        )

        class _Model:
            def transcribe(self, path: str) -> Any:
                return res

        class _Runner:
            def transcribe_array(self, audio: Any) -> Any:
                raise RuntimeError("ANE blew up")

        audio = np.array([0.1] * 4000, dtype=np.float32)
        with mock.patch.object(voice, "decode_audio_to_float32", return_value=audio), \
                mock.patch.object(voice, "_get_coreml_runner", return_value=_Runner()), \
                mock.patch.object(voice, "_get_parakeet_model", return_value=_Model()):
            text, words = voice.transcribe_audio_buffer(b"\x01\x02")
            self.assertEqual(text, "this")
            self.assertEqual(words[0]["word"], "this")

    @unittest.skipIf(np is None, "numpy not installed")
    def test_parakeet_failure_falls_back_to_whisper(self) -> None:
        from hermes_gaze.audio import voice

        seg = types.SimpleNamespace(
            text="this",
            words=[types.SimpleNamespace(word="this", start=0.1, end=0.4)],
        )

        class _Whisper:
            def transcribe(self, audio: Any, **kw: Any) -> Any:
                return [seg], {}

        audio = np.array([0.1] * 4000, dtype=np.float32)
        with mock.patch.object(voice, "decode_audio_to_float32", return_value=audio), \
                mock.patch.object(voice, "_get_coreml_runner", return_value=None), \
                mock.patch.object(voice, "_get_parakeet_model", return_value=None), \
                mock.patch.object(voice, "get_whisper_model", return_value=_Whisper()):
            text, words = voice.transcribe_audio_buffer(b"\x01\x02")
            self.assertEqual(text, "this")
            self.assertEqual(words[0]["word"], "this")


if __name__ == "__main__":
    unittest.main()
