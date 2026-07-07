import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from app.enterprise.observability.audit_service import SQLiteAuditSink
from app.enterprise.observability.models import AuditEvent
from evals.enterprise.run_audit_evidence_gate import main, run_audit_evidence_gate

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1] / "evals" / "enterprise" / "fixtures" / "audit_evidence"
)


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
            self.assertEqual(report.source_kind, "audit_events")
            self.assertEqual(report.source_path, audit_path.as_posix())
            self.assertIsNone(report.trace_id)
            self.assertIsNone(report.request_id)
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

    def test_fixture_examples_match_gate_expectations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            pass_report = run_audit_evidence_gate(
                audit_events_path=FIXTURE_DIR / "pass_events.jsonl",
                output_dir=output_dir,
                write_report=True,
            )
            fail_report = run_audit_evidence_gate(
                audit_events_path=FIXTURE_DIR / "fail_missing_evidence.json",
                output_dir=output_dir,
                write_report=True,
            )

            self.assertTrue(pass_report.passed)
            self.assertEqual(pass_report.summary["event_count"], 5)
            self.assertEqual(pass_report.summary["finding_count"], 0)
            self.assertFalse(fail_report.passed)
            self.assertEqual(fail_report.summary["event_count"], 2)
            self.assertEqual(
                fail_report.summary["finding_codes"],
                {
                    "audit_metadata_missing": 1,
                    "audit_reason_missing": 1,
                    "audit_request_id_missing": 1,
                },
            )

    def test_runner_loads_jsonl_trace_source_and_reports_source_fields(self):
        target_trace = "trace-source-jsonl"
        target_request = "request-source-jsonl"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            audit_path = tmp_path / "audit.jsonl"
            events = [
                AuditEvent(
                    event_type="permission_checked",
                    route="permission",
                    trace_id=target_trace,
                    request_id=target_request,
                    user_id="user_gate",
                    decision="allowed",
                    metadata={
                        "resource_type": "tool",
                        "resource_id": "local_echo",
                        "action": "use",
                    },
                ),
                AuditEvent(
                    event_type="tool_call",
                    route="tool_gateway",
                    trace_id=target_trace,
                    request_id=target_request,
                    user_id="user_gate",
                    decision="allowed",
                    metadata={"tool_id": "local_echo", "status": "success"},
                ),
                AuditEvent(
                    event_type="permission_checked",
                    route="permission",
                    trace_id="trace-other",
                    request_id="request-other",
                    user_id="user_gate",
                    decision="allowed",
                    metadata={},
                ),
            ]
            audit_path.write_text(
                "\n".join(
                    json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                    for event in events
                )
                + "\n",
                encoding="utf-8",
            )

            report = run_audit_evidence_gate(
                source_kind="jsonl",
                source_path=audit_path,
                trace_id=target_trace,
                request_id=target_request,
                output_dir=tmp_path,
                write_report=True,
            )

            self.assertTrue(report.passed)
            self.assertEqual(report.source_kind, "jsonl")
            self.assertEqual(report.source_path, audit_path.as_posix())
            self.assertEqual(report.trace_id, target_trace)
            self.assertEqual(report.request_id, target_request)
            self.assertEqual(report.summary["event_count"], 2)
            self.assertEqual(report.summary["finding_count"], 0)

            payload = json.loads(Path(report.report_json_path or "").read_text(encoding="utf-8"))
            self.assertEqual(payload["source_kind"], "jsonl")
            self.assertEqual(payload["source_path"], audit_path.as_posix())
            self.assertEqual(payload["trace_id"], target_trace)
            self.assertEqual(payload["request_id"], target_request)

    def test_runner_loads_sqlite_trace_source_with_request_filter(self):
        target_trace = "trace-source-sqlite"
        target_request = "request-source-sqlite"
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sqlite_path = tmp_path / "audit.sqlite"
            sink = SQLiteAuditSink(sqlite_path)
            sink.emit(
                AuditEvent(
                    event_type="permission_checked",
                    route="permission",
                    trace_id=target_trace,
                    request_id=target_request,
                    user_id="user_gate",
                    decision="allowed",
                    metadata={
                        "resource_type": "tool",
                        "resource_id": "local_echo",
                        "action": "use",
                    },
                )
            )
            sink.emit(
                AuditEvent(
                    event_type="permission_checked",
                    route="permission",
                    trace_id=target_trace,
                    request_id="request-other",
                    user_id="user_gate",
                    decision="allowed",
                    metadata={},
                )
            )

            report = run_audit_evidence_gate(
                source_kind="sqlite",
                source_path=sqlite_path,
                trace_id=target_trace,
                request_id=target_request,
                output_dir=tmp_path,
                write_report=False,
            )

            self.assertTrue(report.passed)
            self.assertEqual(report.source_kind, "sqlite")
            self.assertEqual(report.source_path, sqlite_path.as_posix())
            self.assertEqual(report.trace_id, target_trace)
            self.assertEqual(report.request_id, target_request)
            self.assertEqual(report.summary["event_count"], 1)
            self.assertEqual(report.summary["finding_count"], 0)

    def test_main_returns_nonzero_when_trace_source_has_no_matching_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            audit_path = tmp_path / "audit.jsonl"
            audit_path.write_text(
                json.dumps(
                    AuditEvent(
                        event_type="permission_checked",
                        route="permission",
                        trace_id="trace-other",
                        request_id="request-other",
                        user_id="user_gate",
                        decision="allowed",
                        metadata={
                            "resource_type": "tool",
                            "resource_id": "local_echo",
                            "action": "use",
                        },
                    ).model_dump(mode="json"),
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "--source-kind",
                    "jsonl",
                    "--path",
                    audit_path.as_posix(),
                    "--trace-id",
                    "trace-missing",
                    "--output-dir",
                    tmpdir,
                ]
            )

            reports = sorted(tmp_path.glob("audit_evidence_gate_*.json"))
            self.assertEqual(exit_code, 1)
            self.assertEqual(len(reports), 1)
            payload = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertFalse(payload["passed"])
            self.assertEqual(payload["source_kind"], "jsonl")
            self.assertEqual(payload["trace_id"], "trace-missing")
            self.assertEqual(payload["summary"]["event_count"], 0)
            self.assertEqual(payload["summary"]["finding_codes"], {"audit_events_missing": 1})

    def test_main_rejects_mixed_audit_events_and_trace_source_args(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stderr(stderr):
            main(
                [
                    "--audit-events",
                    (FIXTURE_DIR / "pass_events.jsonl").as_posix(),
                    "--source-kind",
                    "jsonl",
                    "--path",
                    (FIXTURE_DIR / "pass_events.jsonl").as_posix(),
                    "--trace-id",
                    "trace-gate-pass",
                ]
            )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--audit-events cannot be combined", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
