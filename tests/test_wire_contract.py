"""Wire-contract tests: the overlay's candidate dicts -> CandidateElement.from_wire.

Pins the JS->Python candidate mapping (including ``is_direct_hit``) so a schema drift
in overlay.js's ``extractCandidatesNear`` fails loudly instead of silently degrading
resolution quality.
"""

from __future__ import annotations

import unittest

from hermes_gaze.resolver.bayesian_fusion import (
    BONUS_DIRECT_HIT,
    CandidateElement,
    ScoredCandidate,
    resolve_candidates,
)
from hermes_gaze.tracker.simulated_gaze import FixationSample


def _twin(cid: str, is_direct_hit: bool) -> CandidateElement:
    rect = (100.0, 100.0, 80.0, 32.0)
    return CandidateElement(
        id=cid,
        tag="button",
        role="button",
        label="Export CSV",
        selector="#btn-export-csv",
        rect_doc=rect,
        rect_vp=rect,
        is_interactive=True,
        is_direct_hit=is_direct_hit,
        summary="Button: Export CSV",
        consequence="Downloads rows as .csv",
    )


class TestWireContract(unittest.TestCase):
    def test_from_wire_full_key_mapping(self) -> None:
        raw = {
            "id": "cand-7",
            "tag": "a",
            "role": "link",
            "label": "Docs",
            "selector": "a.docs",
            "rect_vp": [10.0, 20.0, 130.0, 44.0],
            "rect_doc": [10.0, 220.0, 130.0, 44.0],
            "is_container": False,
            "is_interactive": True,
            "is_destructive": True,
            "is_direct_hit": True,
            "summary": "Link: Docs",
            "consequence": "Opens the docs page",
        }
        el = CandidateElement.from_wire(raw)
        self.assertEqual(el.id, "cand-7")
        self.assertEqual(el.tag, "a")
        self.assertEqual(el.role, "link")
        self.assertEqual(el.label, "Docs")
        self.assertEqual(el.selector, "a.docs")
        self.assertEqual(el.rect_vp, (10.0, 20.0, 130.0, 44.0))
        self.assertEqual(el.rect_doc, (10.0, 220.0, 130.0, 44.0))
        self.assertIs(el.is_container, False)
        self.assertIs(el.is_interactive, True)
        self.assertIs(el.is_destructive, True)
        self.assertIs(el.is_direct_hit, True)
        self.assertEqual(el.summary, "Link: Docs")
        self.assertEqual(el.consequence, "Opens the docs page")

    def test_from_wire_defaults_for_missing_keys(self) -> None:
        el = CandidateElement.from_wire({})
        self.assertEqual(el.id, "cand")
        self.assertEqual(el.role, "button")
        self.assertIs(el.is_interactive, True)
        self.assertIs(el.is_direct_hit, False)
        self.assertEqual(el.rect_vp, (0.0, 0.0, 40.0, 24.0))
        self.assertEqual(el.rect_doc, el.rect_vp)
        # Sparse wire dicts must still be shaped: short rects pad to 4, missing doc rect falls back to vp.
        el2 = CandidateElement.from_wire({"rect_vp": [5.0, 6.0]})
        self.assertEqual(el2.rect_vp, (5.0, 6.0, 0.0, 0.0))
        self.assertEqual(el2.rect_doc, el2.rect_vp)

    def test_scored_candidate_to_dict_round_trips_direct_hit(self) -> None:
        sc = ScoredCandidate(
            candidate=_twin("hit", True),
            probability=0.9,
            spatial_score=-4.0,
            semantic_score=3.5,
            prior_score=1.2,
            consequence_preview="Downloads rows as .csv",
        )
        d = sc.to_dict()
        self.assertIs(d["is_direct_hit"], True)
        self.assertEqual(d["id"], "hit")
        self.assertAlmostEqual(d["probability"], 0.9)

    def test_direct_hit_scores_above_identical_twin(self) -> None:
        """BONUS_DIRECT_HIT must actually reach the semantic score (parity with the old JS resolver)."""
        hit = _twin("hit", is_direct_hit=True)
        twin = _twin("twin", is_direct_hit=False)
        fix = FixationSample(
            x_doc=140.0,
            y_doc=116.0,
            x_vp=140.0,
            y_vp=116.0,
            t_start=9.8,
            t_end=9.9,
            duration_ms=120.0,
            sigma_x=24.0,
            sigma_y=24.0,
            source="hover",
        )
        res = resolve_candidates([hit, twin], [fix], "what is this", t_arm=10.0)
        by_id = {sc.candidate.id: sc for sc in res.ranked}
        self.assertIn("hit", by_id)
        self.assertIn("twin", by_id)
        self.assertAlmostEqual(
            by_id["hit"].semantic_score - by_id["twin"].semantic_score,
            BONUS_DIRECT_HIT,
        )
        self.assertGreater(by_id["hit"].probability, by_id["twin"].probability)
        self.assertIsNotNone(res.top)
        self.assertEqual(res.top.candidate.id, "hit")


if __name__ == "__main__":
    unittest.main()
