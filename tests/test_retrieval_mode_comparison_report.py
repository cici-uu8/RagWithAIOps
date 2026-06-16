import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.models import ParserEngine, RetrievalMode, RetrievalResponse, SourceRef
from app.models.knowledge import RetrievalQuery, RetrievalResult
from evals.knowledge_base.retrieval_mode_comparison_report import (
    build_retrieval_mode_comparison_report,
    main,
    write_retrieval_mode_comparison_report,
)


class FakeRetrievalService:
    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        if query.retrieval_mode == RetrievalMode.DENSE_ONLY:
            results = [_result("doc-a:c00001", "doc-a", recall_source="dense", score=0.9)]
        elif query.retrieval_mode == RetrievalMode.HYBRID:
            results = [
                _result("doc-a:c00001", "doc-a", recall_source="dense", score=0.9),
                _result("doc-b:c00001", "doc-b", recall_source="sparse", score=0.7),
            ]
        elif query.retrieval_mode == RetrievalMode.SPARSE_ONLY:
            results = [_result("doc-c:c00001", "doc-c", recall_source="sparse", score=0.8)]
        elif query.retrieval_mode == RetrievalMode.HYBRID_RERANK:
            results = [
                _result(
                    "doc-b:c00001",
                    "doc-b",
                    recall_source="hybrid_rerank",
                    score=0.95,
                    rerank_status="disabled",
                ),
                _result(
                    "doc-a:c00001",
                    "doc-a",
                    recall_source="hybrid_rerank",
                    score=0.93,
                    rerank_status="disabled",
                ),
            ]
        else:
            results = []
        return RetrievalResponse(
            query=query,
            results=results,
            context_text="\n".join(result.content for result in results),
        )


class FailingRetrievalService:
    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        raise RuntimeError(f"{query.retrieval_mode.value} unavailable")


class RetrievalModeComparisonReportTests(unittest.TestCase):
    def test_build_retrieval_mode_comparison_report_compares_dense_and_hybrid(self):
        report = build_retrieval_mode_comparison_report(
            [
                {
                    "sample_id": "R1",
                    "query": "现场设备故障怎么处理",
                    "allowed_kb_ids": ["craft_dept"],
                    "expected_doc_ids": ["doc-a"],
                    "top_k": 3,
                }
            ],
            retrieval_service=FakeRetrievalService(),
        )

        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["hybrid_added_result_count"], 1)
        self.assertEqual(report["modes"], ["dense_only", "hybrid"])
        self.assertEqual(report["summary"]["mode_result_counts"]["dense_only"], 1)
        self.assertEqual(report["summary"]["mode_result_counts"]["hybrid"], 2)
        self.assertEqual(report["samples"][0]["dense_only"]["result_count"], 1)
        self.assertEqual(report["samples"][0]["hybrid"]["result_count"], 2)
        self.assertEqual(report["samples"][0]["dense_only"]["source_ref_complete"], True)
        self.assertEqual(report["samples"][0]["hybrid"]["source_ref_complete"], True)
        self.assertEqual(report["samples"][0]["hybrid"]["recall_sources"], {"dense": 1, "sparse": 1})
        self.assertEqual(report["samples"][0]["expected_doc_found"]["dense_only"], True)
        self.assertEqual(report["samples"][0]["expected_doc_found"]["hybrid"], True)
        self.assertIn("doc_overlap_matrix", report["comparison"])

    def test_build_retrieval_mode_comparison_report_compares_four_modes(self):
        report = build_retrieval_mode_comparison_report(
            [
                {
                    "sample_id": "R1",
                    "query": "现场设备故障怎么处理",
                    "allowed_kb_ids": ["craft_dept"],
                    "expected_doc_ids": ["doc-a"],
                    "top_k": 3,
                }
            ],
            retrieval_service=FakeRetrievalService(),
            modes=[
                RetrievalMode.DENSE_ONLY,
                RetrievalMode.SPARSE_ONLY,
                RetrievalMode.HYBRID,
                RetrievalMode.HYBRID_RERANK,
            ],
        )

        self.assertEqual(
            report["modes"],
            ["dense_only", "sparse_only", "hybrid", "hybrid_rerank"],
        )
        self.assertEqual(report["summary"]["mode_result_counts"]["sparse_only"], 1)
        self.assertEqual(report["summary"]["mode_result_counts"]["hybrid_rerank"], 2)
        self.assertEqual(report["summary"]["mode_expected_doc_found_counts"]["sparse_only"], 0)
        self.assertEqual(report["summary"]["mode_expected_doc_found_counts"]["hybrid_rerank"], 1)
        self.assertEqual(report["summary"]["not_ready_count"], 0)
        self.assertEqual(
            report["summary"]["rerank_status_counts_by_mode"]["hybrid_rerank"],
            {"disabled": 2},
        )
        self.assertIn("sparse_only", report["samples"][0])
        self.assertIn("hybrid_rerank", report["samples"][0])
        self.assertEqual(
            report["samples"][0]["doc_overlap_matrix"]["dense_only"]["hybrid_rerank"],
            0.5,
        )
        self.assertEqual(
            report["samples"][0]["rank_diff_matrix"]["dense_only"]["hybrid_rerank"],
            1.0,
        )
        self.assertIn("latency_ms_by_mode", report["summary"])

    def test_write_retrieval_mode_comparison_report_writes_json_and_markdown(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report = write_retrieval_mode_comparison_report(
                [
                    {
                        "sample_id": "R1",
                        "query": "现场设备故障怎么处理",
                        "allowed_kb_ids": ["craft_dept"],
                        "expected_doc_ids": ["doc-a"],
                    }
                ],
                output_json=root / "report.json",
                output_md=root / "report.md",
                retrieval_service=FakeRetrievalService(),
            )

            self.assertTrue((root / "report.json").exists())
            self.assertTrue((root / "report.md").exists())
            self.assertIn("Retrieval Mode Comparison", (root / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["total"], 1)

    def test_build_retrieval_mode_comparison_report_marks_not_ready_when_retrieval_fails(self):
        report = build_retrieval_mode_comparison_report(
            [
                {
                    "sample_id": "R1",
                    "query": "现场设备故障怎么处理",
                    "allowed_kb_ids": ["craft_dept"],
                }
            ],
            retrieval_service=FailingRetrievalService(),
        )

        self.assertEqual(report["summary"]["not_ready_count"], 2)
        self.assertEqual(report["samples"][0]["dense_only"]["status"], "not_ready")
        self.assertEqual(report["samples"][0]["hybrid"]["status"], "not_ready")
        self.assertEqual(report["samples"][0]["dense_only"]["blocked_error_type"], "RuntimeError")

    def test_main_accepts_jsonl_evalset_modes_and_output_alias(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evalset = root / "samples.jsonl"
            output = root / "report.json"
            evalset.write_text(
                '{"sample_id":"R1","query":"现场设备故障怎么处理","allowed_kb_ids":["craft_dept"],"expected_doc_ids":["doc-a"]}\n',
                encoding="utf-8",
            )
            argv = [
                "retrieval_mode_comparison_report",
                "--evalset",
                str(evalset),
                "--modes",
                "dense_only",
                "sparse_only",
                "hybrid",
                "hybrid_rerank",
                "--output",
                str(output),
            ]

            with (
                patch("sys.argv", argv),
                patch(
                    "evals.knowledge_base.retrieval_mode_comparison_report._default_retrieval_service",
                    return_value=FakeRetrievalService(),
                ),
            ):
                exit_code = main()

            self.assertEqual(exit_code, 0)
            self.assertTrue(output.exists())


def _result(
    chunk_id: str,
    doc_id: str,
    *,
    recall_source: str,
    score: float,
    rerank_status: str = "",
) -> RetrievalResult:
    source_ref = SourceRef(
        kb_id="craft_dept",
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file="现场设备工艺版.pdf",
        page_start=2,
        page_end=2,
        parser_engine=ParserEngine.MINERU,
    )
    metadata = {
        "recall_source": recall_source,
        "source_ref": source_ref.model_dump(mode="json"),
    }
    if rerank_status:
        metadata["rerank_status"] = rerank_status
    return RetrievalResult(
        kb_id="craft_dept",
        doc_id=doc_id,
        chunk_id=chunk_id,
        content=f"{doc_id} content",
        score=score,
        source_ref=source_ref,
        citation_text="来源: 现场设备工艺版.pdf\n页码: 2",
        metadata=metadata,
    )


if __name__ == "__main__":
    unittest.main()
