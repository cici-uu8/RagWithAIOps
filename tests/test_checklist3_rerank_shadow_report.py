import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals.knowledge_base.checklist3_rerank_shadow_report import (
    build_checklist3_rerank_shadow_report,
    write_checklist3_rerank_shadow_report,
)


class Checklist3RerankShadowReportTests(unittest.TestCase):
    def test_report_explains_disabled_default_and_runs_active_shadow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = Path(tmpdir) / "comparison.json"
            comparison.write_text(
                json.dumps(
                    {
                        "summary": {
                            "total": 18,
                            "mode_result_counts": {"hybrid_rerank": 48},
                            "rerank_status_counts_by_mode": {
                                "hybrid_rerank": {"disabled": 48}
                            },
                            "not_ready_count": 0,
                            "wrong_scope_count": 0,
                            "citation_incomplete_count": 0,
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "evals.knowledge_base.checklist3_rerank_shadow_report.config.rerank_enabled",
                False,
            ):
                report = build_checklist3_rerank_shadow_report(
                    comparison_report_path=comparison,
                )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(
            report["disabled_explanation"]["reason"],
            "runtime_rerank_disabled",
        )
        self.assertTrue(report["disabled_explanation"]["is_expected_default_off_behavior"])
        self.assertEqual(
            report["latest_comparison"]["hybrid_rerank_status_counts"],
            {"disabled": 48},
        )
        self.assertFalse(
            report["config_state"]["external_dependency_required_for_current_scorer"]
        )
        self.assertTrue(report["active_shadow"]["applied"])
        self.assertTrue(report["active_shadow"]["top_k_respected"])
        self.assertEqual(report["active_shadow"]["output_count"], 2)
        self.assertEqual(report["active_shadow"]["result_ids"][0], "doc_cpu:c00001")
        self.assertTrue(report["active_shadow"]["source_ref_identity_preserved"])
        self.assertTrue(report["fallback_shadow"]["fallback"])
        self.assertTrue(report["fallback_shadow"]["error_recorded"])
        self.assertEqual(report["gaps"], [])

    def test_missing_comparison_report_is_needs_attention(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "missing.json"

            with patch(
                "evals.knowledge_base.checklist3_rerank_shadow_report.config.rerank_enabled",
                False,
            ):
                report = build_checklist3_rerank_shadow_report(
                    comparison_report_path=missing,
                )

        self.assertEqual(report["status"], "needs_attention")
        self.assertIn("latest_4mode_comparison_missing", report["gaps"])
        self.assertEqual(
            report["disabled_explanation"]["reason"],
            "comparison_report_missing",
        )
        self.assertTrue(report["active_shadow"]["applied"])

    def test_runtime_enabled_is_reported_as_attention(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            comparison = Path(tmpdir) / "comparison.json"
            comparison.write_text(
                json.dumps(
                    {
                        "summary": {
                            "rerank_status_counts_by_mode": {
                                "hybrid_rerank": {"disabled": 2}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch(
                "evals.knowledge_base.checklist3_rerank_shadow_report.config.rerank_enabled",
                True,
            ):
                report = build_checklist3_rerank_shadow_report(
                    comparison_report_path=comparison,
                )

        self.assertEqual(report["status"], "needs_attention")
        self.assertIn("runtime_rerank_enabled_not_false", report["gaps"])
        self.assertEqual(
            report["disabled_explanation"]["reason"],
            "comparison_report_contains_disabled_status_despite_runtime_enabled",
        )

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            comparison = root / "comparison.json"
            output_json = root / "rerank.json"
            output_md = root / "rerank.md"
            comparison.write_text(
                json.dumps(
                    {
                        "summary": {
                            "rerank_status_counts_by_mode": {
                                "hybrid_rerank": {"disabled": 2}
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            report = write_checklist3_rerank_shadow_report(
                comparison_report_path=comparison,
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "passed")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn(
                "Checklist 3 Rerank Shadow Report",
                output_md.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
