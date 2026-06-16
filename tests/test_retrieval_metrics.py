"""Tests for app/services/retrieval_metrics.

Layer 1: WeKnora upstream test cases reproduced 1:1 (recall/precision/mrr/map,
exact expected values from `internal/application/service/metric/*_test.go`).
This is a port-correctness lock — any drift here means the Python implementation
diverged from the Go semantics.

Layer 2: NDCG cases (WeKnora has no test file for NDCG; expected values are
hand-computed from the documented formula DCG/IDCG with binary relevance and
log2(i+2) discount).

Layer 3: Python-port-specific behavior (k=None vs explicit k, string chunk_id
support, edge cases not covered in upstream).
"""

import math
import unittest

from app.services.retrieval_metrics import (
    map_at_k,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


class RecallTests(unittest.TestCase):
    """1:1 with WeKnora `recall_test.go`."""

    def test_perfect_recall_all_gt_retrieved(self):
        # WeKnora: gt=[[1,2,3]] retrieved=[1,2,3,4] expected=1.0
        self.assertAlmostEqual(recall_at_k([[1, 2, 3]], [1, 2, 3, 4]), 1.0)

    def test_partial_recall(self):
        # WeKnora: gt=[[1,2,3], [4,5]] retrieved=[1,4,6] expected=(1/3 + 1/2) / 2
        self.assertAlmostEqual(
            recall_at_k([[1, 2, 3], [4, 5]], [1, 4, 6]),
            (1 / 3 + 1 / 2) / 2,
        )

    def test_no_recall(self):
        self.assertAlmostEqual(recall_at_k([[1, 2, 3]], [4, 5, 6]), 0.0)

    def test_empty_retrieval(self):
        self.assertAlmostEqual(recall_at_k([[1, 2, 3]], []), 0.0)

    def test_multiple_gt_sets(self):
        # WeKnora: gt=[[1,2],[3,4],[5,6]] retrieved=[1,3,7] expected=1/3
        # 命中前两个 set 各 1 个 → (1/2 + 1/2 + 0) / 3 = 1/3
        self.assertAlmostEqual(
            recall_at_k([[1, 2], [3, 4], [5, 6]], [1, 3, 7]),
            1 / 3,
        )


class PrecisionTests(unittest.TestCase):
    """1:1 with WeKnora `precision_test.go`."""

    def test_perfect_match(self):
        self.assertAlmostEqual(precision_at_k([[1, 3, 5]], [1, 3, 5]), 1.0)

    def test_half_match(self):
        # WeKnora: gt=[[1,2,3]] retrieved=[1,4,2] expected=2/3
        self.assertAlmostEqual(precision_at_k([[1, 2, 3]], [1, 4, 2]), 2 / 3)

    def test_no_match(self):
        self.assertAlmostEqual(precision_at_k([[1, 2, 3]], [4, 5, 6]), 0.0)

    def test_empty_retrieval(self):
        self.assertAlmostEqual(precision_at_k([[1, 2, 3]], []), 0.0)

    def test_multiple_gt_sets(self):
        # WeKnora: gt=[[1,2],[3,4]] retrieved=[1,3,5] expected=1/3
        # set1 命中 1 → 1/3; set2 命中 1 → 1/3; mean=1/3
        self.assertAlmostEqual(precision_at_k([[1, 2], [3, 4]], [1, 3, 5]), 1 / 3)


class MRRTests(unittest.TestCase):
    """1:1 with WeKnora `mrr_test.go`."""

    def test_first_position(self):
        self.assertAlmostEqual(mrr_at_k([[1, 2]], [1, 2, 3]), 1.0)

    def test_second_position(self):
        self.assertAlmostEqual(mrr_at_k([[1, 2]], [3, 1, 2]), 0.5)

    def test_no_match(self):
        self.assertAlmostEqual(mrr_at_k([[1, 2]], [3, 4]), 0.0)

    def test_multiple_queries(self):
        # WeKnora: gt=[[1,2],[3,4]] retrieved=[1,3,2,4] expected=(1/1 + 1/2)/2 = 0.75
        self.assertAlmostEqual(mrr_at_k([[1, 2], [3, 4]], [1, 3, 2, 4]), 0.75)

    def test_empty_gt(self):
        self.assertAlmostEqual(mrr_at_k([], [1, 2]), 0.0)


class MAPTests(unittest.TestCase):
    """1:1 with WeKnora `map_test.go`."""

    def test_total_match(self):
        self.assertAlmostEqual(map_at_k([[2, 4, 6]], [2, 4, 6]), 1.0)

    def test_no_match(self):
        self.assertAlmostEqual(map_at_k([[1, 2]], [3, 4]), 0.0)

    def test_partial_match(self):
        # WeKnora: gt=[[1,2,3]] retrieved=[2,5,1,3]
        # ranks: 2 hit (1/1), 1 hit (2/3), 3 hit (3/4); AP = (1 + 2/3 + 3/4)/3
        self.assertAlmostEqual(
            map_at_k([[1, 2, 3]], [2, 5, 1, 3]),
            (1 + 2 / 3 + 3 / 4) / 3,
        )

    def test_empty_gt(self):
        self.assertAlmostEqual(map_at_k([], [1, 2]), 0.0)

    def test_multiple_queries(self):
        # WeKnora: gt=[[1,2],[3,4]] retrieved=[1,3,2,4]
        # query1: hit at 1, hit at 3 → AP=(1/1 + 2/3)/2
        # query2: hit at 2, hit at 4 → AP=(1/2 + 2/4)/2 = 0.5
        # MAP = (q1 + q2) / 2
        q1 = (1 / 1 + 2 / 3) / 2
        q2 = (1 / 2 + 2 / 4) / 2
        self.assertAlmostEqual(
            map_at_k([[1, 2], [3, 4]], [1, 3, 2, 4]),
            (q1 + q2) / 2,
        )


class NDCGTests(unittest.TestCase):
    """NDCG semantics: WeKnora unions all gt_sets, binary relevance,
    DCG = sum (2^rel - 1) / log2(i+2), IDCG places relevant first.
    Expected values hand-computed from formula."""

    def test_perfect_ranking_returns_1(self):
        # All retrieved are relevant, in any order → DCG == IDCG → 1.0
        self.assertAlmostEqual(ndcg_at_k([[1, 2, 3]], [1, 2, 3]), 1.0)

    def test_no_relevant_returns_0(self):
        self.assertAlmostEqual(ndcg_at_k([[1, 2]], [3, 4, 5]), 0.0)

    def test_empty_retrieved_returns_0(self):
        self.assertAlmostEqual(ndcg_at_k([[1, 2, 3]], []), 0.0)

    def test_empty_gt_returns_0(self):
        self.assertAlmostEqual(ndcg_at_k([], [1, 2, 3]), 0.0)

    def test_relevant_after_irrelevant_lower_dcg(self):
        # gt={1,2}, retrieved=[3, 1, 2]
        # DCG = 0/log2(2) + 1/log2(3) + 1/log2(4) = 1/log2(3) + 0.5
        # IDCG = 1/log2(2) + 1/log2(3) = 1 + 1/log2(3)
        retrieved = [3, 1, 2]
        gt = [[1, 2]]
        dcg = 0 + 1 / math.log2(3) + 1 / math.log2(4)
        idcg = 1 / math.log2(2) + 1 / math.log2(3)
        self.assertAlmostEqual(ndcg_at_k(gt, retrieved), dcg / idcg)

    def test_unions_multiple_gt_sets(self):
        # WeKnora ndcg: gt=[[1],[2]] should treat both 1 and 2 as relevant
        # retrieved=[1,2,3] → all front 2 relevant → ratio = 1.0
        # (since IDCG fills 2 ones at front, DCG also has 1s at first 2)
        self.assertAlmostEqual(ndcg_at_k([[1], [2]], [1, 2, 3]), 1.0)


class KTruncationTests(unittest.TestCase):
    """k parameter — Python port adds k uniformly across all 5 metrics
    (WeKnora upstream only exposes k on NDCG)."""

    def test_recall_at_k_truncates(self):
        # gt=[[1,2,3]], retrieved=[4,5,1,2,3]
        # k=2 → retrieved[:2]=[4,5] → 0 hits → recall=0
        self.assertAlmostEqual(recall_at_k([[1, 2, 3]], [4, 5, 1, 2, 3], k=2), 0.0)
        # k=5 (or None) → all → 3/3 = 1
        self.assertAlmostEqual(recall_at_k([[1, 2, 3]], [4, 5, 1, 2, 3], k=5), 1.0)
        self.assertAlmostEqual(recall_at_k([[1, 2, 3]], [4, 5, 1, 2, 3], k=None), 1.0)

    def test_precision_at_k_uses_k_as_denominator(self):
        # retrieved=[1,2,3,4,5], gt=[[1,2]], k=3 → hits=2, denom=3 → 2/3
        self.assertAlmostEqual(precision_at_k([[1, 2]], [1, 2, 3, 4, 5], k=3), 2 / 3)

    def test_mrr_at_k_does_not_count_match_past_k(self):
        # retrieved=[3,4,5,1], k=3 → no hit in [3,4,5] → 0
        self.assertAlmostEqual(mrr_at_k([[1]], [3, 4, 5, 1], k=3), 0.0)
        # k=4 includes 1 at position 4 → 1/4
        self.assertAlmostEqual(mrr_at_k([[1]], [3, 4, 5, 1], k=4), 0.25)

    def test_ndcg_at_k_truncates_window(self):
        # gt=[[1,2,3]], retrieved=[1,2,3,4]
        # k=3 → top-3 has 3 relevant; ideal also 3 → NDCG=1.0
        self.assertAlmostEqual(ndcg_at_k([[1, 2, 3]], [1, 2, 3, 4], k=3), 1.0)

    def test_negative_k_raises(self):
        with self.assertRaises(ValueError):
            recall_at_k([[1]], [1, 2], k=-1)


class StringIdentifierTests(unittest.TestCase):
    """Our chunk_id are strings, not ints. Confirm no regression on str ids."""

    def test_recall_with_string_ids(self):
        gt = [["doc:c1", "doc:c2"]]
        retrieved = ["doc:c1", "doc:other", "doc:c2"]
        self.assertAlmostEqual(recall_at_k(gt, retrieved), 1.0)

    def test_precision_with_string_ids(self):
        self.assertAlmostEqual(
            precision_at_k([["a", "b"]], ["a", "x", "y"], k=3),
            1 / 3,
        )

    def test_mrr_with_mixed_hashable(self):
        # Tuples too, since chunk_id might be (kb, doc, chunk) downstream
        self.assertAlmostEqual(
            mrr_at_k([[("kb", "d1", "c1")]], [("kb", "d0", "c0"), ("kb", "d1", "c1")]),
            0.5,
        )


class EdgeCaseTests(unittest.TestCase):
    """Edge cases not in WeKnora upstream tests."""

    def test_empty_gt_set_inside_gt_sets_recall(self):
        # gt_sets=[[1,2], []] — empty inner is skipped (would 0/0 otherwise)
        # set1 hits 1: recall=1/2; set2 has no GT → contributes 0
        # mean = (0.5 + 0) / 2 = 0.25
        self.assertAlmostEqual(recall_at_k([[1, 2], []], [1]), 0.25)

    def test_duplicates_in_retrieved_count_each(self):
        # WeKnora `Hit` counts each occurrence, not just set membership.
        # retrieved=[1,1,1], gt=[[1,2,3]] → hits=3, but recall caps at len(gt)
        # recall = 3/3 = 1 (per WeKnora `Hit` that returns 3, then 3/3=1.0)
        self.assertAlmostEqual(recall_at_k([[1, 2, 3]], [1, 1, 1]), 1.0)

    def test_k_zero_returns_zero(self):
        # Empty truncated window
        self.assertAlmostEqual(recall_at_k([[1]], [1, 2], k=0), 0.0)
        self.assertAlmostEqual(precision_at_k([[1]], [1, 2], k=0), 0.0)
        self.assertAlmostEqual(mrr_at_k([[1]], [1, 2], k=0), 0.0)
        self.assertAlmostEqual(map_at_k([[1]], [1, 2], k=0), 0.0)
        self.assertAlmostEqual(ndcg_at_k([[1]], [1, 2], k=0), 0.0)


if __name__ == "__main__":
    unittest.main()
