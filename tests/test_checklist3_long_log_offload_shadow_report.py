import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_long_log_offload_shadow_report import (
    TAIL_SENTINEL,
    build_checklist3_long_log_offload_shadow_report,
    write_checklist3_long_log_offload_shadow_report,
)


class Checklist3LongLogOffloadShadowReportTests(unittest.TestCase):
    def test_default_report_passes_owner_lookup_and_no_summary_only_checks(self):
        report = build_checklist3_long_log_offload_shadow_report()

        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["long_log"]["definition_met"])
        self.assertGreater(report["long_log"]["original_result_bytes"], 10 * 1024)
        self.assertTrue(report["prompt_payload"]["is_string"])
        self.assertTrue(report["prompt_payload"]["json_string_compatible"])
        self.assertTrue(report["prompt_payload"]["result_ref_present"])
        self.assertTrue(report["prompt_payload"]["contains_offload_notice"])
        self.assertFalse(report["prompt_payload"]["tail_sentinel_leaked"])
        self.assertFalse(report["prompt_payload"]["equals_original_result"])
        self.assertTrue(report["retrieval"]["owner_can_read_full_original"])
        self.assertFalse(report["retrieval"]["other_owner_can_read"])
        self.assertTrue(report["evidence"]["full_original_preserved"])
        self.assertFalse(report["evidence"]["summary_only_state"])
        self.assertEqual(report["gaps"], [])

    def test_short_log_reports_failed_definition_and_no_offload(self):
        report = build_checklist3_long_log_offload_shadow_report(
            result_bytes=1024,
            threshold=2000,
        )

        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["long_log"]["definition_met"])
        self.assertFalse(report["long_log"]["exceeds_threshold"])
        self.assertFalse(report["prompt_payload"]["result_ref_present"])
        self.assertIn("long_log_definition_not_met", report["gaps"])
        self.assertIn("tool_result_ref_missing", report["gaps"])

    def test_report_does_not_emit_full_log_tail(self):
        report = build_checklist3_long_log_offload_shadow_report()
        dumped = json.dumps(report, ensure_ascii=False)

        self.assertNotIn(TAIL_SENTINEL, dumped)
        self.assertFalse(report["evidence"]["report_leaks_full_tail"])

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_json = root / "long_log.json"
            output_md = root / "long_log.md"

            report = write_checklist3_long_log_offload_shadow_report(
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "passed")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn(
                "Checklist 3 Long Log Offload Shadow Report",
                output_md.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
