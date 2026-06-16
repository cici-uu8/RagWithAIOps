import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_long_session_shadow_report import (
    build_checklist3_long_session_shadow_report,
    write_checklist3_long_session_shadow_report,
)


class Checklist3LongSessionShadowReportTests(unittest.TestCase):
    def test_default_report_passes_shadow_active_and_stale_checks(self):
        report = build_checklist3_long_session_shadow_report()

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["long_session"]["turn_count"], 50)
        self.assertTrue(report["long_session"]["definition_met"])
        self.assertTrue(report["shadow"]["snapshot_read"])
        self.assertTrue(report["shadow"]["cleanup_called"])
        self.assertFalse(report["shadow"]["prompt_injected"])
        self.assertTrue(report["active_candidate"]["prompt_injected"])
        self.assertTrue(report["active_candidate"]["truncated"])
        self.assertTrue(report["active_candidate"]["within_max_prompt_chars"])
        self.assertEqual(report["active_candidate"]["forbidden_hits"], [])
        self.assertFalse(report["stale_candidate"]["prompt_injected"])
        self.assertFalse(report["stale_candidate"]["stale_snapshot_remaining_after_cleanup"])
        self.assertEqual(report["gaps"], [])

    def test_short_session_reports_failed_definition(self):
        report = build_checklist3_long_session_shadow_report(long_turn_count=3)

        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["long_session"]["definition_met"])
        self.assertIn("long_session_definition_not_met", report["gaps"])

    def test_report_does_not_emit_synthetic_memory_content_or_evidence_terms(self):
        report = build_checklist3_long_session_shadow_report()
        dumped = json.dumps(report, ensure_ascii=False)

        self.assertNotIn("checkout-service backlog", dumped)
        self.assertNotIn("source_ref citation SourceRef", dumped)
        self.assertNotIn("最近会话", dumped)
        self.assertEqual(report["active_candidate"]["forbidden_hits"], [])

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_json = root / "long_session.json"
            output_md = root / "long_session.md"

            report = write_checklist3_long_session_shadow_report(
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "passed")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn(
                "Checklist 3 Long Session Shadow Report",
                output_md.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
