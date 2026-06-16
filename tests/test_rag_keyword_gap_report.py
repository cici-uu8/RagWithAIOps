import json
import tempfile
import unittest
from pathlib import Path

from app.models import ChunkRecord, ParserEngine, SourceRef
from evals.knowledge_base.rag_keyword_gap_report import (
    build_keyword_gap_report,
    write_keyword_gap_report,
)


class FakeMetadataStore:
    def __init__(self, chunks_by_doc):
        self.chunks_by_doc = chunks_by_doc

    def list_chunks_by_doc_id(self, doc_id):
        return list(self.chunks_by_doc.get(doc_id, []))


class RagKeywordGapReportTests(unittest.TestCase):
    def test_build_keyword_gap_report_classifies_absent_keyword_and_context_gap(self):
        chunks_by_doc = {
            "doc-handbook": [
                _chunk("doc-handbook:c00001", "doc-handbook", 1, "工具排查 Runbook 索引"),
                _chunk("doc-handbook:c00002", "doc-handbook", 2, "API 异常升级矩阵"),
            ]
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evalset_path = root / "evalset.jsonl"
            evalset_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "sample_id": "RAG-06",
                                "query": "MCP 工具调用失败怎么排查",
                                "allowed_kb_ids": ["process_digital_dept"],
                                "expected_doc_ids": ["doc-handbook"],
                                "expected_answer_keywords": ["MCP", "工具"],
                                "scope": "scoped",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "sample_id": "RAG-07",
                                "query": "API 异常时 on-call 如何升级",
                                "allowed_kb_ids": ["process_digital_dept"],
                                "expected_doc_ids": ["doc-handbook"],
                                "expected_answer_keywords": ["API", "升级"],
                                "scope": "scoped",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            rag_report_path = root / "rag_report.json"
            rag_report_path.write_text(
                json.dumps(
                    {
                        "evalset_path": str(evalset_path),
                        "results": [
                            _result("RAG-06", ["MCP", "工具"], ["doc-handbook:c00001"]),
                            _result("RAG-07", ["API", "升级"], ["doc-handbook:c00001"]),
                            {
                                "sample_id": "RAG-OK",
                                "failure_category": "passed",
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_keyword_gap_report(
                rag_report_path,
                metadata_store=FakeMetadataStore(chunks_by_doc),
            )

        self.assertEqual(report["summary"]["total_keyword_gap_rows"], 2)
        rows = {row["sample_id"]: row for row in report["rows"]}
        self.assertEqual(rows["RAG-06"]["verdict"], "expected_keyword_absent_from_expected_doc")
        self.assertEqual(rows["RAG-06"]["missing_in_expected_doc"], ["MCP"])
        self.assertEqual(rows["RAG-07"]["verdict"], "expected_keyword_available_outside_top_context")
        self.assertEqual(rows["RAG-07"]["missing_in_all_retrieved_context"], ["API", "升级"])
        self.assertEqual(rows["RAG-07"]["missing_in_retrieved_expected_doc_chunks"], ["API", "升级"])
        self.assertEqual(
            rows["RAG-07"]["candidate_chunks_by_keyword"]["API"][0]["chunk_id"],
            "doc-handbook:c00002",
        )

    def test_write_keyword_gap_report_writes_json_and_markdown(self):
        chunks_by_doc = {"doc-handbook": [_chunk("doc-handbook:c00001", "doc-handbook", 1, "API 升级")]}
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evalset_path = root / "evalset.jsonl"
            evalset_path.write_text(
                json.dumps(
                    {
                        "sample_id": "RAG-07",
                        "query": "API 异常时 on-call 如何升级",
                        "allowed_kb_ids": ["process_digital_dept"],
                        "expected_doc_ids": ["doc-handbook"],
                        "expected_answer_keywords": ["API", "升级"],
                        "scope": "scoped",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            rag_report_path = root / "rag_report.json"
            rag_report_path.write_text(
                json.dumps(
                    {
                        "evalset_path": str(evalset_path),
                        "results": [_result("RAG-07", ["API", "升级"], ["doc-handbook:c00001"])],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = write_keyword_gap_report(
                rag_report_path,
                output_json=root / "keyword_gap.json",
                output_md=root / "keyword_gap.md",
                metadata_store=FakeMetadataStore(chunks_by_doc),
            )
            json_exists = (root / "keyword_gap.json").exists()
            markdown = (root / "keyword_gap.md").read_text(encoding="utf-8")

        self.assertEqual(report["rows"][0]["verdict"], "retrieved_expected_doc_chunks_contain_all_keywords")
        self.assertTrue(json_exists)
        self.assertIn("RAG Keyword Gap", markdown)


def _result(sample_id, keywords, chunk_ids):
    return {
        "sample_id": sample_id,
        "query": sample_id,
        "failure_category": "answer_wrong",
        "answer_score": 0.5,
        "expected_doc_ids": ["doc-handbook"],
        "actual_doc_ids": ["doc-handbook"],
        "source_ref": [
            {
                "kb_id": "process_digital_dept",
                "doc_id": "doc-handbook",
                "chunk_id": chunk_id,
                "source_file": "superbiz_oncall_handbook.md",
                "heading_path": ["handbook"],
                "parser_engine": "plain_text",
            }
            for chunk_id in chunk_ids
        ],
        "expected_answer_keywords": keywords,
    }


def _chunk(chunk_id, doc_id, chunk_index, content):
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        kb_id="process_digital_dept",
        content=content,
        chunk_index=chunk_index,
        start_index=0,
        end_index=len(content),
        heading_path=["handbook"],
        source_ref=SourceRef(
            kb_id="process_digital_dept",
            doc_id=doc_id,
            chunk_id=chunk_id,
            source_file="superbiz_oncall_handbook.md",
            parser_engine=ParserEngine.PLAIN_TEXT,
        ),
    )


if __name__ == "__main__":
    unittest.main()
