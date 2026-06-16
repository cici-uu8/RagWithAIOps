import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.rerank_service import rerank_service


class Checklist4S4P23RankGapCProbeTests(unittest.TestCase):
    def test_classify_rank_gap_candidate_assigns_expected_verdicts(self):
        from evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe import (
            _classify_rank_gap_candidate,
        )

        proven_row = _row(
            sample_id="S4M-A-012",
            dense_doc_ids=["doc-other", "doc-target"],
            hybrid_doc_ids=["doc-other", "doc-target"],
            rerank_doc_ids=["doc-target", "doc-other"],
            rerank_status="applied",
        )
        observation_row = _row(
            sample_id="S4M-B-001",
            dense_doc_ids=["doc-other", "doc-target"],
            hybrid_doc_ids=["doc-other", "doc-target"],
            rerank_doc_ids=["doc-other", "doc-target"],
            rerank_status="applied",
        )
        no_lift_row = _row(
            sample_id="S4M-B-008",
            dense_doc_ids=["doc-other"],
            hybrid_doc_ids=["doc-other"],
            rerank_doc_ids=["doc-other"],
            rerank_status="applied",
        )
        self.assertEqual(
            _classify_rank_gap_candidate(proven_row, expected_doc_ids={"doc-target"}, top_k=3)["verdict"],
            "rank_lift_proven",
        )
        self.assertEqual(
            _classify_rank_gap_candidate(observation_row, expected_doc_ids={"doc-target"}, top_k=3)["verdict"],
            "rank_observation_only",
        )
        self.assertEqual(
            _classify_rank_gap_candidate(no_lift_row, expected_doc_ids={"doc-target"}, top_k=3)["verdict"],
            "no_rank_lift",
        )

    def test_build_rank_gap_c_probe_report_filters_samples_and_restores_rerank_flag(self):
        from evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe import (
            build_rank_gap_c_probe_report,
        )

        with TemporaryDirectory() as tmpdir:
            evalset = Path(tmpdir) / "evalset.jsonl"
            evalset.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "sample_id": "S4M-A-012",
                                "query": "CPUThrottlingHigh 告警什么时候需要处理",
                                "allowed_kb_ids": ["process_digital_dept"],
                                "expected_doc_ids": ["doc-target"],
                                "expected_answer_keywords": ["CPU Throttling High"],
                                "scope": "scoped",
                                "retrieval_mode": "dense_only",
                                "top_k": 3,
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "sample_id": "IGNORED-01",
                                "query": "ignored",
                                "allowed_kb_ids": ["process_digital_dept"],
                                "expected_doc_ids": ["doc-ignore"],
                                "expected_answer_keywords": ["ignored"],
                                "scope": "scoped",
                                "retrieval_mode": "dense_only",
                                "top_k": 3,
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            original_enabled = rerank_service.enabled

            def fake_build(samples, *, retrieval_service, modes):
                self.assertTrue(rerank_service.enabled)
                self.assertEqual(len(samples), 1)
                self.assertEqual(samples[0]["sample_id"], "S4M-A-012")
                self.assertEqual([mode.value for mode in modes], ["dense_only", "hybrid", "hybrid_rerank"])
                return {
                    "generated_at": "2026-06-10T00:00:00Z",
                    "modes": ["dense_only", "hybrid", "hybrid_rerank"],
                    "summary": {
                        "total": 1,
                        "mode_result_counts": {"dense_only": 1, "hybrid": 1, "hybrid_rerank": 1},
                        "mode_not_ready_counts": {"dense_only": 0, "hybrid": 0, "hybrid_rerank": 0},
                        "mode_wrong_scope_counts": {"dense_only": 0, "hybrid": 0, "hybrid_rerank": 0},
                        "mode_citation_incomplete_counts": {"dense_only": 0, "hybrid": 0, "hybrid_rerank": 0},
                        "mode_expected_doc_found_counts": {"dense_only": 1, "hybrid": 1, "hybrid_rerank": 1},
                        "latency_ms_by_mode": {
                            "dense_only": {"avg": 1, "p95": 1, "max": 1},
                            "hybrid": {"avg": 1, "p95": 1, "max": 1},
                            "hybrid_rerank": {"avg": 1, "p95": 1, "max": 1},
                        },
                        "rerank_status_counts_by_mode": {"hybrid_rerank": {"applied": 1}},
                        "wrong_scope_count": 0,
                        "not_ready_count": 0,
                        "citation_incomplete_count": 0,
                        "dense_result_count": 1,
                        "hybrid_result_count": 1,
                        "hybrid_added_result_count": 0,
                    },
                    "comparison": {"doc_overlap_matrix": {}, "rank_diff_matrix": {}},
                    "samples": [
                        _row(
                            sample_id="S4M-A-012",
                            dense_doc_ids=["doc-other", "doc-target"],
                            hybrid_doc_ids=["doc-other", "doc-target"],
                            rerank_doc_ids=["doc-target", "doc-other"],
                            rerank_status="applied",
                        )
                    ],
                }

            with patch(
                "evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe.build_retrieval_mode_comparison_report",
                side_effect=fake_build,
            ):
                report = build_rank_gap_c_probe_report(
                    evalset_path=evalset,
                    sample_ids=["S4M-A-012"],
                    min_effective_samples=1,
                    enable_true_rerank=True,
                )

        self.assertEqual(rerank_service.enabled, original_enabled)
        self.assertEqual(report["probe_name"], "checklist4_s4_p23_rank_gap_c_probe")
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["rank_lift_proven_count"], 1)
        self.assertEqual(report["rank_observation_only_count"], 0)
        self.assertEqual(report["no_rank_lift_count"], 0)
        self.assertTrue(report["true_rerank_applied"])
        self.assertTrue(report["eligible_for_formal_evalset"])
        self.assertEqual(report["status"], "formal_value_proven")
        self.assertEqual(report["decisions"]["create_formal_evalset"], True)
        self.assertEqual(report["decisions"]["default_switch_eligibility"], "not_eligible_for_default_switch")


def _row(
    *,
    sample_id: str,
    dense_doc_ids: list[str],
    hybrid_doc_ids: list[str],
    rerank_doc_ids: list[str],
    rerank_status: str,
) -> dict[str, object]:
    def _mode(doc_ids: list[str], *, status: str | None = None) -> dict[str, object]:
        results = []
        for doc_id in doc_ids:
            metadata: dict[str, object] = {}
            if status is not None:
                metadata["rerank_status"] = status
            results.append({"doc_id": doc_id, "metadata": metadata})
        return {"doc_ids": doc_ids, "results": results, "result_count": len(doc_ids)}

    return {
        "sample_id": sample_id,
        "query": sample_id,
        "dense_only": _mode(dense_doc_ids),
        "hybrid": _mode(hybrid_doc_ids),
        "hybrid_rerank": _mode(rerank_doc_ids, status=rerank_status),
    }


if __name__ == "__main__":
    unittest.main()
