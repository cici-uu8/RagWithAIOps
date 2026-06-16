import json
import tempfile
import unittest
from pathlib import Path

from app.models import ParserEngine, RetrievalQuery, RetrievalResponse, RetrievalResult, SourceRef
from evals.knowledge_base.run_answer_context_shadow_eval import (
    build_answer_context_shadow_report,
    write_answer_context_shadow_report,
)


class AnswerContextShadowEvalTests(unittest.TestCase):
    def test_build_report_detects_top_k_context_lift_without_llm_or_gate_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evalset = Path(tmpdir) / "answer.jsonl"
            evalset.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")

            report = build_answer_context_shadow_report(
                evalset,
                sample_ids=["C6A-X"],
                top_ks=[3, 5],
                retrieval_service=StaticRetrievalService(),
                metadata_store=None,
            )

        self.assertTrue(report["scope"]["shadow_only"])
        self.assertFalse(report["scope"]["calls_llm_answer_generator"])
        self.assertFalse(report["scope"]["changes_main_gate"])
        self.assertFalse(report["scope"]["changes_default_top_k"])
        self.assertEqual(report["summary"]["promotion_clears_default_context_missing_sample_ids"], ["C6A-X"])
        result = report["results"][0]
        self.assertEqual(result["top_k_results"]["3"]["missing_context_facts"], ["bravo"])
        self.assertEqual(result["top_k_results"]["5"]["missing_context_facts"], [])

    def test_write_report_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evalset = root / "answer.jsonl"
            evalset.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")

            report = write_answer_context_shadow_report(
                evalset,
                sample_ids=["C6A-X"],
                top_ks=[3, 5],
                output_json=root / "shadow.json",
                retrieval_service=StaticRetrievalService(),
                metadata_store=None,
            )

            self.assertTrue((root / "shadow.json").exists())
            self.assertTrue((root / "shadow.md").exists())
            self.assertEqual(report["report_json_path"], str(root / "shadow.json"))
            self.assertIn("Answer Context Shadow Report", (root / "shadow.md").read_text(encoding="utf-8"))


class StaticRetrievalService:
    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        content = "alpha"
        if query.top_k >= 5:
            content = "alpha\nbravo"
        result = _retrieval_result(content)
        return RetrievalResponse(
            query=query,
            results=[result],
            context_text=f"【参考资料 1】\n来源: sample.md\n内容:\n{content}",
        )


def _sample() -> dict:
    return {
        "sample_id": "C6A-X",
        "layer": "answer",
        "query": "how to handle sample",
        "allowed_kb_ids": ["process_digital_dept"],
        "expected_doc_ids": ["doc-sample"],
        "scope": "scoped",
        "retrieval_mode": "dense_only",
        "reference_answer": "alpha and bravo",
        "must_include_facts": ["alpha", "bravo"],
        "must_not_include_claims": ["forbidden"],
        "required_citations": [
            {
                "doc_id": "doc-sample",
                "source_file": "sample.md",
                "expected_in_answer": "sample.md",
            }
        ],
        "context_policy": "retrieved_context_only",
    }


def _retrieval_result(content: str) -> RetrievalResult:
    source_ref = SourceRef(
        kb_id="process_digital_dept",
        doc_id="doc-sample",
        chunk_id="chunk-sample-1",
        source_file="sample.md",
        heading_path=["Sample"],
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RetrievalResult(
        kb_id="process_digital_dept",
        doc_id="doc-sample",
        chunk_id="chunk-sample-1",
        content=content,
        score=0.1,
        source_ref=source_ref,
        citation_text="[来源: sample.md, 章节: Sample, chunk: chunk-sample-1]",
        metadata={},
    )


if __name__ == "__main__":
    unittest.main()
