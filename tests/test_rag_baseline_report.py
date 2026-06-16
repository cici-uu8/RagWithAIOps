import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.rag_baseline_report import build_baseline_summary


class RagBaselineReportTests(unittest.TestCase):
    def test_build_baseline_summary_marks_data_not_indexed_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "department_rag_eval.json"
            report_path.write_text(
                json.dumps(
                    {
                        "evalset_path": "evals/knowledge_base/evalsets/department_rag_20q.jsonl",
                        "generated_at": "2026-06-05T00:20:42+00:00",
                        "summary": {
                            "total": 20,
                            "status_counts": {"passed": 11, "failed": 9},
                            "failure_categories": {
                                "passed": 11,
                                "answer_wrong": 2,
                                "data_not_indexed": 7,
                            },
                            "all_source_ref_resolvable": True,
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            summary = build_baseline_summary([report_path])

        self.assertEqual(summary["total_reports"], 1)
        self.assertEqual(summary["reports"][0]["total"], 20)
        self.assertEqual(summary["reports"][0]["passed"], 11)
        self.assertEqual(summary["reports"][0]["failed"], 9)
        self.assertEqual(summary["reports"][0]["failure_categories"]["data_not_indexed"], 7)
        self.assertTrue(summary["reports"][0]["all_source_ref_resolvable"])
        self.assertTrue(summary["gates"]["data_not_indexed_present"])
        self.assertFalse(summary["gates"]["source_ref_unresolvable_present"])


if __name__ == "__main__":
    unittest.main()
