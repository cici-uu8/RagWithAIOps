import json
import tempfile
import unittest
from pathlib import Path

from evals.enterprise.run_audit_evidence_gate import main, run_audit_evidence_gate


class EnterpriseAuditEvidenceGateTests(unittest.TestCase):
    def test_runner_outputs_json_and_markdown_for_complete_audit_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit_events.jsonl"
            audit_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_type": "permission_checked",
                                "route": "permission",
                                "trace_id": "trace-gate-pass",
                                "request_id": "request-gate-pass",
                                "user_id": "user_gate",
                                "decision": "allowed",
                                "reason": "matched_grant",
                                "metadata": {
                                    "resource_type": "tool",
                                    "resource_id": "local_echo",
                                    "action": "use",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "event_type": "tool_call",
                                "route": "tool_gateway",
                                "trace_id": "trace-gate-pass",
                                "request_id": "request-gate-pass",
                                "user_id": "user_gate",
                                "decision": "allowed",
                                "metadata": {"tool_id": "local_echo", "status": "success"},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            report = run_audit_evidence_gate(
                audit_events_path=audit_path,
                output_dir=Path(tmpdir),
                write_report=True,
            )

            json_report = Path(report.report_json_path or "")
            markdown_report = Path(report.report_markdown_path or "")

            self.assertTrue(report.passed)
            self.assertEqual(report.summary["event_count"], 2)
            self.assertEqual(report.summary["finding_count"], 0)
            self.assertTrue(json_report.exists())
            self.assertTrue(markdown_report.exists())
            self.assertIn("G-P0-AUDIT-EVIDENCE", markdown_report.read_text(encoding="utf-8"))

    def test_main_returns_nonzero_for_missing_audit_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit_events.json"
            audit_path.write_text(
                json.dumps(
                    {
                        "audit_events": [
                            {
                                "event_type": "tool_blocked",
                                "route": "tool_gateway",
                                "trace_id": "trace-gate-fail",
                                "request_id": "",
                                "user_id": "user_gate",
                                "decision": "denied",
                                "metadata": {"tool_id": "hidden_tool", "status": "blocked"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--audit-events",
                    audit_path.as_posix(),
                    "--output-dir",
                    tmpdir,
                ]
            )

            reports = sorted(Path(tmpdir).glob("audit_evidence_gate_*.json"))
            self.assertEqual(exit_code, 1)
            self.assertEqual(len(reports), 1)
            payload = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertFalse(payload["passed"])
            self.assertEqual(
                payload["summary"]["finding_codes"],
                {
                    "audit_request_id_missing": 1,
                    "audit_reason_missing": 1,
                },
            )


if __name__ == "__main__":
    unittest.main()
