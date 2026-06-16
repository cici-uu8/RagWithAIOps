import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.rag_answer_failure_triage_report import (
    build_answer_failure_triage_report,
    write_answer_failure_triage_report,
)


class RagAnswerFailureTriageReportTests(unittest.TestCase):
    def test_build_answer_failure_triage_report_classifies_keyword_gap_and_pending_asset(self):
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
                                "sample_id": "RAG-12",
                                "query": "土壤地下水监测资料属于哪个方向",
                                "allowed_kb_ids": ["craft_dept"],
                                "expected_doc_ids": [],
                                "expected_answer_keywords": ["土壤", "地下水"],
                                "scope": "scoped",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            manifest_path = root / "original_files_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "orig-soil",
                                "file_name": "2025_中车长春轨道客车_土壤地下水自行监测方案.pdf",
                                "relative_path": "downloads/2025_中车长春轨道客车_土壤地下水自行监测方案.pdf",
                                "kb_id": "craft_dept",
                                "review_status": "pending",
                                "import_enabled": False,
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            report_path = root / "rag_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "evalset_path": str(evalset_path),
                        "results": [
                            {
                                "sample_id": "RAG-06",
                                "query": "MCP 工具调用失败怎么排查",
                                "failure_category": "answer_wrong",
                                "answer_score": 0.5,
                                "expected_doc_ids": ["doc-handbook"],
                                "actual_doc_ids": ["doc-handbook", "doc-news"],
                                "source_ref": [
                                    {"source_file": "superbiz_oncall_handbook.md"},
                                    {"source_file": "2024_news.md"},
                                ],
                            },
                            {
                                "sample_id": "RAG-12",
                                "query": "土壤地下水监测资料属于哪个方向",
                                "failure_category": "answer_wrong",
                                "answer_score": 0.0,
                                "expected_doc_ids": [],
                                "actual_doc_ids": ["doc-current"],
                                "source_ref": [{"source_file": "线上故障处理_现场设备工艺版.pdf"}],
                            },
                            {
                                "sample_id": "RAG-01",
                                "query": "正常样本",
                                "failure_category": "passed",
                                "answer_score": 1.0,
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_answer_failure_triage_report(
                report_path,
                original_manifest_path=manifest_path,
            )

        self.assertEqual(report["summary"]["total_answer_wrong"], 2)
        self.assertEqual(
            report["summary"]["classification_counts"],
            {
                "expected_doc_retrieved_keyword_gap": 1,
                "eval_asset_pending_review_import": 1,
            },
        )
        self.assertEqual(report["rows"][0]["sample_id"], "RAG-06")
        self.assertEqual(report["rows"][0]["classification"], "expected_doc_retrieved_keyword_gap")
        self.assertEqual(report["rows"][1]["sample_id"], "RAG-12")
        self.assertEqual(report["rows"][1]["classification"], "eval_asset_pending_review_import")
        self.assertEqual(report["rows"][1]["evidence"]["matched_assets"][0]["asset_id"], "orig-soil")

    def test_write_answer_failure_triage_report_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_path = root / "rag_report.json"
            report_path.write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "sample_id": "RAG-X",
                                "query": "missing context",
                                "failure_category": "answer_wrong",
                                "source_ref": [],
                                "actual_doc_ids": [],
                                "expected_doc_ids": [],
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            report = write_answer_failure_triage_report(
                report_path,
                output_json=root / "triage.json",
                output_md=root / "triage.md",
            )

            self.assertTrue((root / "triage.json").exists())
            self.assertTrue((root / "triage.md").exists())
            self.assertEqual(report["rows"][0]["classification"], "retrieval_empty_or_missing_context")
            self.assertIn("RAG Answer Failure Triage", (root / "triage.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
