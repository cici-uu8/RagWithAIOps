import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from app.enterprise.observability.models import AuditEvent
from evals.enterprise.run_agent_eval_scorecard import main, run_agent_eval_scorecard

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_FIXTURE_DIR = REPO_ROOT / "evals" / "enterprise" / "fixtures" / "audit_evidence"


class EnterpriseAgentEvalScorecardTests(unittest.TestCase):
    def test_scorecard_passes_when_trace_eval_and_audit_evidence_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            report = run_agent_eval_scorecard(
                trace_evalsets=[
                    REPO_ROOT / "evals" / "enterprise" / "evalsets" / "chat_trace_evalset.jsonl"
                ],
                audit_events_path=AUDIT_FIXTURE_DIR / "pass_events.jsonl",
                output_dir=output_dir,
                write_report=True,
            )

            json_report = Path(report.report_json_path or "")
            markdown_report = Path(report.report_markdown_path or "")
            gates_by_id = {gate.gate_id: gate for gate in report.gates}

            self.assertTrue(report.passed)
            self.assertEqual(report.summary["gate_count"], 2)
            self.assertEqual(report.summary["failed_gate_count"], 0)
            self.assertTrue(gates_by_id["G-P1-TRACE-TRAJECTORY"].passed)
            self.assertTrue(gates_by_id["G-P0-AUDIT-EVIDENCE"].passed)
            self.assertEqual(gates_by_id["G-P1-TRACE-TRAJECTORY"].summary["failed"], 0)
            self.assertEqual(gates_by_id["G-P0-AUDIT-EVIDENCE"].summary["finding_count"], 0)
            self.assertTrue(json_report.exists())
            self.assertTrue(markdown_report.exists())
            self.assertIn("Agent Eval Scorecard", markdown_report.read_text(encoding="utf-8"))

    def test_main_returns_nonzero_when_audit_evidence_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = main(
                [
                    "--trace-evalset",
                    (
                        REPO_ROOT / "evals" / "enterprise" / "evalsets" / "chat_trace_evalset.jsonl"
                    ).as_posix(),
                    "--audit-events",
                    (AUDIT_FIXTURE_DIR / "fail_missing_evidence.json").as_posix(),
                    "--output-dir",
                    tmpdir,
                ]
            )

            reports = sorted(Path(tmpdir).glob("agent_eval_scorecard_*.json"))
            self.assertEqual(exit_code, 1)
            self.assertEqual(len(reports), 1)

            payload = json.loads(reports[0].read_text(encoding="utf-8"))
            gates_by_id = {gate["gate_id"]: gate for gate in payload["gates"]}

            self.assertFalse(payload["passed"])
            self.assertTrue(gates_by_id["G-P1-TRACE-TRAJECTORY"]["passed"])
            self.assertFalse(gates_by_id["G-P0-AUDIT-EVIDENCE"]["passed"])
            self.assertEqual(
                gates_by_id["G-P0-AUDIT-EVIDENCE"]["summary"]["finding_codes"],
                {
                    "audit_metadata_missing": 1,
                    "audit_reason_missing": 1,
                    "audit_request_id_missing": 1,
                },
            )

    def test_scorecard_fails_when_trace_eval_has_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            evalset_path = tmp_path / "trace_evalset.jsonl"
            evalset_path.write_text(
                json.dumps(
                    {
                        "eval_id": "scorecard_trace_failure_001",
                        "input": {"route": "chat_stream", "question": "hello"},
                        "expected": {
                            "final_status": "completed",
                            "required_stages": ["gateway", "permission"],
                            "required_audit_events": ["permission_checked"],
                        },
                        "trace_source": {
                            "kind": "inline",
                            "trace_id": "trace-scorecard-fail",
                            "request_id": "request-scorecard-fail",
                            "audit_events": [
                                AuditEvent(
                                    event_type="request_started",
                                    route="chat_stream",
                                    trace_id="trace-scorecard-fail",
                                    request_id="request-scorecard-fail",
                                    user_id="user_scorecard",
                                    decision="allowed",
                                ).model_dump(mode="json"),
                                AuditEvent(
                                    event_type="request_completed",
                                    route="chat_stream",
                                    trace_id="trace-scorecard-fail",
                                    request_id="request-scorecard-fail",
                                    user_id="user_scorecard",
                                    decision="allowed",
                                ).model_dump(mode="json"),
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            report = run_agent_eval_scorecard(
                trace_evalsets=[evalset_path],
                audit_events_path=AUDIT_FIXTURE_DIR / "pass_events.jsonl",
                output_dir=tmp_path,
                write_report=False,
            )
            gates_by_id = {gate.gate_id: gate for gate in report.gates}

            self.assertFalse(report.passed)
            self.assertFalse(gates_by_id["G-P1-TRACE-TRAJECTORY"].passed)
            self.assertTrue(gates_by_id["G-P0-AUDIT-EVIDENCE"].passed)
            self.assertEqual(gates_by_id["G-P1-TRACE-TRAJECTORY"].summary["failed"], 1)
            self.assertEqual(
                gates_by_id["G-P1-TRACE-TRAJECTORY"].summary["mismatch_codes"],
                {"missing_audit_event": 1, "missing_stage": 1},
            )

    def test_main_rejects_missing_audit_source(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stderr(stderr):
            main(
                [
                    "--trace-evalset",
                    (
                        REPO_ROOT / "evals" / "enterprise" / "evalsets" / "chat_trace_evalset.jsonl"
                    ).as_posix(),
                ]
            )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("provide an audit source", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
