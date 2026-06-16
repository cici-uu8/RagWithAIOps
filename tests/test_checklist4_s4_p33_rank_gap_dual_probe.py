"""Test for checklist4_s4_p33_rank_gap_dual_probe."""

import unittest

from evals.knowledge_base.checklist4_s4_p33_rank_gap_dual_probe import (
    _classify_benefit_b_verdict,
    _classify_rewrite_verdict,
    _get_rank,
)


class Checklist4S4P33RankGapDualProbeTests(unittest.TestCase):
    def test_get_rank(self):
        doc_ids = ["doc_a", "doc_b", "doc_c"]
        self.assertEqual(_get_rank("doc_a", doc_ids), 1)
        self.assertEqual(_get_rank("doc_b", doc_ids), 2)
        self.assertEqual(_get_rank("doc_c", doc_ids), 3)
        self.assertEqual(_get_rank("doc_d", doc_ids), 0)
        self.assertEqual(_get_rank(None, doc_ids), 0)

    def test_classify_rewrite_verdict(self):
        # rewrite_lift_proven: original no-hit, rewrite hit
        self.assertEqual(_classify_rewrite_verdict(0, 1), "rewrite_lift_proven")
        self.assertEqual(_classify_rewrite_verdict(0, 2), "rewrite_lift_proven")

        # rewrite_lift_proven: original rank 5, rewrite rank 1
        self.assertEqual(_classify_rewrite_verdict(5, 1), "rewrite_lift_proven")

        # rewrite_observation_only: both hit, no lift
        self.assertEqual(_classify_rewrite_verdict(2, 2), "rewrite_observation_only")

        # no_rewrite_lift: rewrite still no-hit
        self.assertEqual(_classify_rewrite_verdict(0, 0), "no_rewrite_lift")
        self.assertEqual(_classify_rewrite_verdict(0, 5), "no_rewrite_lift")

    def test_classify_benefit_b_verdict(self):
        # sparse_lift_proven: dense no-hit, sparse hit
        self.assertEqual(_classify_benefit_b_verdict(0, 1, 0), "sparse_lift_proven")

        # hybrid_lift_proven: dense no-hit, hybrid hit
        self.assertEqual(_classify_benefit_b_verdict(0, 0, 2), "hybrid_lift_proven")

        # observation_only: dense hit, sparse also hit
        self.assertEqual(_classify_benefit_b_verdict(1, 2, 1), "observation_only")

        # no_lift: all no-hit
        self.assertEqual(_classify_benefit_b_verdict(0, 0, 0), "no_lift")


if __name__ == "__main__":
    unittest.main()
