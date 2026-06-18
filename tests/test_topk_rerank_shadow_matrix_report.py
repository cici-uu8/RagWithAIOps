import json
import tempfile
import unittest
from pathlib import Path

from app.models import ParserEngine, RetrievalQuery, RetrievalResponse, RetrievalResult, SourceRef
from evals.knowledge_base.topk_rerank_shadow_matrix_report import (
    build_topk_rerank_shadow_matrix_report,
    write_topk_rerank_shadow_matrix_report,
)


class TopkRerankShadowMatrixReportTests(unittest.TestCase):
    def test_build_report_separates_retrieval_rerank_and_final_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evalset = Path(tmpdir) / "retrieval.jsonl"
            evalset.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")

            report = build_topk_rerank_shadow_matrix_report(
                evalset,
                scenarios=[
                    {
                        "scenario_id": "dense_k3_ctx3_default",
                        "retrieval_top_k": 3,
                        "rerank_mode": "off",
                        "rerank_top_n": None,
                        "final_context_k": 3,
                    },
                    {
                        "scenario_id": "dense_k5_lexical_rn4_ctx2",
                        "retrieval_top_k": 5,
                        "rerank_mode": "local_lexical",
                        "rerank_top_n": 4,
                        "final_context_k": 2,
                    },
                ],
                retrieval_provider=StaticDenseProvider(),
                metadata_store=None,
                external_scorer=None,
                prior_answer_shadow_path=Path(tmpdir) / "missing.json",
            )

        self.assertEqual(report["summary"]["sample_count"], 1)
        self.assertEqual(report["summary"]["baseline_scenario_id"], "dense_k3_ctx3_default")
        scenario = report["scenarios"][1]
        row = scenario["rows"][0]
        self.assertEqual(len(row["retrieval_pool_doc_ids"]), 5)
        self.assertEqual(len(row["reranked_doc_ids"]), 4)
        self.assertEqual(len(row["final_doc_ids"]), 2)
        self.assertEqual(row["rerank_status"], "applied")
        self.assertEqual(row["retrieval_metrics"]["pool_expected_doc_hit"], True)
        self.assertEqual(row["retrieval_metrics"]["final_expected_doc_hit"], True)
        self.assertGreaterEqual(row["rerank_metrics"]["rank_lift"], 1)

    def test_context_pollution_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evalset = Path(tmpdir) / "retrieval.jsonl"
            evalset.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")

            report = build_topk_rerank_shadow_matrix_report(
                evalset,
                scenarios=[
                    {
                        "scenario_id": "dense_k3_ctx3_default",
                        "retrieval_top_k": 3,
                        "rerank_mode": "off",
                        "rerank_top_n": None,
                        "final_context_k": 3,
                    },
                    {
                        "scenario_id": "dense_k5_ctx1_no_rerank",
                        "retrieval_top_k": 5,
                        "rerank_mode": "off",
                        "rerank_top_n": None,
                        "final_context_k": 1,
                    },
                ],
                retrieval_provider=PollutingDenseProvider(),
                metadata_store=None,
                external_scorer=None,
                prior_answer_shadow_path=Path(tmpdir) / "missing.json",
            )

        scenario = report["scenarios"][1]
        row = scenario["rows"][0]
        self.assertTrue(row["diagnostics"]["context_pollution"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(scenario["summary"]["gate_decision"], "reject")

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evalset = root / "retrieval.jsonl"
            evalset.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")

            report = write_topk_rerank_shadow_matrix_report(
                evalset,
                output_json=root / "matrix.json",
                scenarios=[
                    {
                        "scenario_id": "dense_k3_ctx3_default",
                        "retrieval_top_k": 3,
                        "rerank_mode": "off",
                        "rerank_top_n": None,
                        "final_context_k": 3,
                    }
                ],
                retrieval_provider=StaticDenseProvider(),
                metadata_store=None,
                external_scorer=None,
                prior_answer_shadow_path=root / "missing.json",
            )

            self.assertTrue((root / "matrix.json").exists())
            self.assertTrue((root / "matrix.md").exists())
            self.assertEqual(report["report_json_path"], str(root / "matrix.json"))
            self.assertIn(
                "Top-K / Rerank Shadow Matrix Report",
                (root / "matrix.md").read_text(encoding="utf-8"),
            )


class StaticDenseProvider:
    def __call__(self, case, top_k: int):
        results = [
            _result("doc-noise-1", "noise alpha", "chunk-1"),
            _result("doc-noise-2", "noise bravo", "chunk-2"),
            _result("doc-expected", "expected keyword anchor", "chunk-3"),
            _result("doc-expected", "expected keyword detail", "chunk-4"),
            _result("doc-noise-3", "noise charlie", "chunk-5"),
        ][:top_k]
        return {
            "response": RetrievalResponse(
                query=RetrievalQuery(query=str(case["query"]), top_k=top_k),
                results=results,
                context_text="",
            ),
            "latency_ms": 25,
            "embedding_api_calls": 1,
            "error": None,
        }


class PollutingDenseProvider:
    def __call__(self, case, top_k: int):
        results = [
            _result("doc-noise-1", "noise alpha", "chunk-1"),
            _result("doc-expected", "expected keyword anchor", "chunk-2"),
            _result("doc-noise-2", "noise bravo", "chunk-3"),
            _result("doc-noise-3", "noise charlie", "chunk-4"),
            _result("doc-noise-4", "noise delta", "chunk-5"),
        ][:top_k]
        return {
            "response": RetrievalResponse(
                query=RetrievalQuery(query=str(case["query"]), top_k=top_k),
                results=results,
                context_text="",
            ),
            "latency_ms": 30,
            "embedding_api_calls": 1,
            "error": None,
        }


def _sample() -> dict:
    return {
        "sample_id": "RAG-X",
        "query": "expected keyword remediation",
        "allowed_kb_ids": ["process_digital_dept"],
        "expected_doc_ids": ["doc-expected"],
        "expected_answer_keywords": ["expected keyword"],
        "scope": "scoped",
        "retrieval_mode": "dense_only",
        "top_k": 3,
    }


def _result(doc_id: str, content: str, chunk_suffix: str) -> RetrievalResult:
    source_ref = SourceRef(
        kb_id="process_digital_dept",
        doc_id=doc_id,
        chunk_id=f"{doc_id}:{chunk_suffix}",
        source_file=f"{doc_id}.md",
        heading_path=["Runbook"],
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RetrievalResult(
        kb_id="process_digital_dept",
        doc_id=doc_id,
        chunk_id=f"{doc_id}:{chunk_suffix}",
        content=content,
        score=0.1,
        source_ref=source_ref,
        citation_text=f"[来源: {doc_id}.md, chunk: {doc_id}:{chunk_suffix}]",
        metadata={
            "heading_path": ["Runbook"],
            "source_ref": source_ref.model_dump(mode="json"),
        },
    )


if __name__ == "__main__":
    unittest.main()
