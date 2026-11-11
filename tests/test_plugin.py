"""Unit tests for look: Bayesian reference resolution, temporal alignment, data extraction, and plugin registration."""

from __future__ import annotations

import unittest

from look.benchmark.run_benchmark import build_synthetic_dashboard_candidates
from look.resolver.bayesian_fusion import resolve_candidates
from look.resolver.data_extractor import extract_structured_data, render_svg_scatter
from look.resolver.temporal_aligner import extract_deictic_anchors, has_deictic_pronoun
from look.tracker.recalibrator import OnlineRecalibrator
from look.tracker.simulated_gaze import FixationSample


class TestLookPlugin(unittest.TestCase):
    def test_deictic_detection_and_temporal_anchors(self) -> None:
        self.assertTrue(has_deictic_pronoun("What happens if I press this?"))
        self.assertTrue(has_deictic_pronoun("Export these results"))
        self.assertFalse(has_deictic_pronoun("Hello world"))

        anchors = extract_deictic_anchors(
            "Compare this one with this one",
            t_arm=10.0,
            word_timestamps=[
                {"word": "Compare", "start": 8.5, "end": 8.8},
                {"word": "this", "start": 8.9, "end": 9.1},
                {"word": "one", "start": 9.1, "end": 9.3},
                {"word": "with", "start": 9.4, "end": 9.6},
                {"word": "this", "start": 9.7, "end": 9.9},
            ],
        )
        self.assertEqual(len(anchors), 2)
        self.assertAlmostEqual(anchors[0].t_anchor, 8.9)
        self.assertAlmostEqual(anchors[1].t_anchor, 9.7)

    def test_bayesian_resolution_and_granularity_promotion(self) -> None:
        candidates = build_synthetic_dashboard_candidates()

        # Scene 2: Pointing near Purge Cache (x=910, y=44) and asking read-only question
        fix_purge = [
            FixationSample(
                x_doc=905.0,
                y_doc=42.0,
                x_vp=905.0,
                y_vp=42.0,
                t_start=9.6,
                t_end=9.9,
                duration_ms=300.0,
                sigma_x=80.0,
                sigma_y=80.0,
            )
        ]
        res_readonly = resolve_candidates(candidates, fix_purge, "What happens if I press this?", t_arm=10.0)
        self.assertEqual(res_readonly.intent_class, "read_only")
        self.assertEqual(res_readonly.decision, "pin_immediate")
        self.assertIsNotNone(res_readonly.top)
        self.assertEqual(res_readonly.top.candidate.id, "btn-purge-cache")

        # Scene 3: Pointing midway between Export CSV (center ~1022) and Generate Report (center ~1135) with noisy gaze
        fix_ambig = [
            FixationSample(
                x_doc=1072.0,
                y_doc=44.0,
                x_vp=1072.0,
                y_vp=44.0,
                t_start=9.6,
                t_end=9.9,
                duration_ms=250.0,
                sigma_x=130.0,
                sigma_y=130.0,
            )
        ]
        res_ambig = resolve_candidates(candidates, fix_ambig, "Click this", t_arm=10.0)
        self.assertEqual(res_ambig.decision, "open_semantic_lens")

        # Scene 4: Pointing at table area and saying plural data verb "Export these results"
        fix_table = [
            FixationSample(
                x_doc=350.0,
                y_doc=220.0,
                x_vp=350.0,
                y_vp=220.0,
                t_start=9.6,
                t_end=9.9,
                duration_ms=280.0,
                sigma_x=120.0,
                sigma_y=120.0,
            )
        ]
        res_table = resolve_candidates(candidates, fix_table, "Export these results and chart Spend vs ROAS", t_arm=10.0)
        self.assertIsNotNone(res_table.top)
        self.assertEqual(res_table.top.candidate.id, "campaigns-table")

    def test_leaf_header_vs_container_resolution(self) -> None:
        from look.resolver.bayesian_fusion import CandidateElement

        section_cand = CandidateElement(
            id="panel-campaigns",
            tag="section",
            role="section",
            label="Q4 Acquisition Campaigns",
            selector="#panel-campaigns",
            rect_doc=(20.0, 60.0, 800.0, 400.0),
            rect_vp=(20.0, 60.0, 800.0, 400.0),
            is_container=True,
            is_interactive=False,
            summary="Section panel: Q4 Acquisition Campaigns",
        )
        table_cand = CandidateElement(
            id="campaigns-table",
            tag="table",
            role="table",
            label="Campaign Performance Table",
            selector="#campaigns-table",
            rect_doc=(36.0, 120.0, 740.0, 260.0),
            rect_vp=(36.0, 120.0, 740.0, 260.0),
            is_container=True,
            is_interactive=False,
            summary="Table: 6 columns (Campaign, Channel, Clicks, CTR, Spend, ROAS), 5 rows",
        )
        th_ctr_cand = CandidateElement(
            id="th-ctr",
            tag="th",
            role="columnheader",
            label="CTR",
            selector="#campaigns-table th:nth-child(4)",
            rect_doc=(330.0, 125.0, 65.0, 30.0),
            rect_vp=(330.0, 125.0, 65.0, 30.0),
            is_container=False,
            is_interactive=False,
            summary="Column header \"CTR\" in Campaign Performance Table",
        )
        cands = [section_cand, table_cand, th_ctr_cand]

        # User hovers directly over "CTR" header (x=350, y=140) in hover mode (sigma=20px)
        fix_hover_ctr = [
            FixationSample(
                x_doc=350.0,
                y_doc=140.0,
                x_vp=350.0,
                y_vp=140.0,
                t_start=9.7,
                t_end=10.0,
                duration_ms=300.0,
                sigma_x=20.0,
                sigma_y=20.0,
                source="hover",
            )
        ]

        # 1. "What does this mean?" -> Must resolve to th-ctr (NOT table, NOT section)
        res_what = resolve_candidates(cands, fix_hover_ctr, "What does this mean?", t_arm=10.0)
        self.assertEqual(res_what.intent_class, "read_only")
        self.assertIsNotNone(res_what.top)
        self.assertEqual(res_what.top.candidate.id, "th-ctr")
        self.assertEqual(res_what.top.candidate.label, "CTR")
        self.assertIn("Column header", res_what.top.consequence_preview)

        # 2. "Export these results and chart Spend vs ROAS" on the same spot -> Promotes to parent table
        res_export = resolve_candidates(cands, fix_hover_ctr, "Export these results and chart Spend vs ROAS", t_arm=10.0)
        self.assertIsNotNone(res_export.top)
        self.assertEqual(res_export.top.candidate.id, "campaigns-table")

    def test_online_recalibrator_and_data_extractor(self) -> None:
        recal = OnlineRecalibrator()
        accepted = recal.update(est_x=520.0, est_y=310.0, true_x=500.0, true_y=300.0, sigma=120.0, weight=0.25)
        self.assertTrue(accepted)
        self.assertAlmostEqual(recal.offset[0], 5.0)
        self.assertAlmostEqual(recal.offset[1], 2.5)

        csv_out = extract_structured_data(
            {"headers": ["Campaign", "Spend", "ROAS"], "rows": [["Launch", "$4,200", "6.4x"]]},
            fmt="csv",
        )
        self.assertIn("Campaign,Spend,ROAS", csv_out)
        svg = render_svg_scatter(["Campaign", "Spend", "ROAS"], [["Launch", "$4,200", "6.4x"], ["Dev", "$1,850", "5.1x"]])
        self.assertIn("<svg", svg)


if __name__ == "__main__":
    unittest.main()
