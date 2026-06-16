import json
import tempfile
import unittest
from pathlib import Path

from app.enterprise.observability.audit_service import SQLiteAuditSink
from app.enterprise.observability.models import AuditEvent
from app.enterprise.tasks.models import RiskLevel, TaskContract, TaskScope, TaskStatus
from app.enterprise.tasks.repository import SQLiteTaskContractRepository
from evals.enterprise.extractors import AuditTraceExtractor
from evals.enterprise.matcher import TrajectoryMatcher
from evals.enterprise.models import ExpectedTrajectory, TraceSource
from evals.enterprise.run_trace_eval import run_trace_eval

REPO_ROOT = Path(__file__).resolve().parents[1]


def audit_event(
    event_type: str,
    *,
    trace_id: str = "trace-f2a-test",
    request_id: str = "request-f2a-test",
    route: str = "chat_stream",
    decision: str = "allowed",
    metadata: dict | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_type=event_type,
        route=route,
        trace_id=trace_id,
        request_id=request_id,
        user_id="user_f2a_test",
        decision=decision,
        metadata=metadata or {},
    )


def task_contract_event(
    event_type: str,
    *,
    task_id: str,
    trace_id: str,
    request_id: str,
    route: str = "task_contract",
    decision: str = "allowed",
    status: str = "running",
    risk_level: str = "medium",
    requires_human_approval: bool = False,
    allowed_data_sources: list[str] | None = None,
    allowed_tools: list[str] | None = None,
    forbidden_actions: list[str] | None = None,
    success_criteria: list[str] | None = None,
    expected_outputs: list[str] | None = None,
    issue_codes: list[str] | None = None,
    extra_metadata: dict | None = None,
) -> AuditEvent:
    metadata = {
        "task_id": task_id,
        "status": status,
        "risk_level": risk_level,
        "requires_human_approval": requires_human_approval,
        "allowed_data_sources": allowed_data_sources or [],
        "allowed_tools": allowed_tools or [],
        "forbidden_actions": forbidden_actions or [],
        "success_criteria": success_criteria or [],
        "expected_outputs": expected_outputs or [],
        "issue_codes": issue_codes or [],
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return AuditEvent(
        event_type=event_type,
        route=route,
        trace_id=trace_id,
        request_id=request_id,
        user_id="user_f2b_test",
        decision=decision,
        metadata=metadata,
    )


class EnterpriseTraceEvalF2aTests(unittest.TestCase):
    def test_expected_trajectory_model_validates_evalset_shape(self):
        sample = {
            "eval_id": "sample_001",
            "input": {"route": "chat_stream", "question": "hello"},
            "expected": {
                "final_status": "completed",
                "required_stages": ["gateway"],
                "forbidden_tools": ["database-demo"],
                "required_audit_events": ["request_started", "request_completed"],
                "sse": {
                    "must_include_trace_id": True,
                    "must_include_request_id": True,
                    "allowed_event_types": ["content", "done"],
                },
            },
            "trace_source": {
                "kind": "inline",
                "trace_id": "trace-model",
                "request_id": "request-model",
                "audit_events": [],
                "sse_events": [],
            },
        }

        expected = ExpectedTrajectory.model_validate(sample)

        self.assertEqual(expected.eval_id, "sample_001")
        self.assertEqual(expected.expected.final_status, "completed")
        self.assertEqual(expected.trace_source.kind, "inline")

    def test_audit_trace_extractor_loads_jsonl_and_sqlite_by_trace_id(self):
        matching = audit_event("request_started")
        terminal = audit_event("request_completed")
        other_trace = audit_event("request_started", trace_id="trace-other")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            jsonl_path = tmp_path / "audit.jsonl"
            with jsonl_path.open("w", encoding="utf-8") as file:
                for event in (matching, terminal, other_trace):
                    file.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False))
                    file.write("\n")

            sqlite_path = tmp_path / "audit.sqlite"
            sink = SQLiteAuditSink(sqlite_path)
            for event in (matching, terminal, other_trace):
                sink.emit(event)

            extractor = AuditTraceExtractor()
            jsonl_actual = extractor.extract(
                TraceSource(kind="jsonl", trace_id="trace-f2a-test", path=jsonl_path.as_posix())
            )
            sqlite_actual = extractor.extract(
                TraceSource(kind="sqlite", trace_id="trace-f2a-test", path=sqlite_path.as_posix())
            )

        self.assertEqual(jsonl_actual.observed_audit_events, ["request_started", "request_completed"])
        self.assertEqual(sqlite_actual.observed_audit_events, ["request_started", "request_completed"])
        self.assertEqual(jsonl_actual.terminal_status, "completed")
        self.assertEqual(sqlite_actual.request_id, "request-f2a-test")

    def test_matcher_detects_missing_audit_forbidden_tool_and_sse_trace_gap(self):
        expected = ExpectedTrajectory.model_validate(
            {
                "eval_id": "negative_001",
                "expected": {
                    "final_status": "completed",
                    "required_stages": ["gateway", "permission"],
                    "forbidden_tools": ["database-demo"],
                    "required_audit_events": ["permission_checked"],
                    "sse": {
                        "must_include_trace_id": True,
                        "must_include_request_id": True,
                        "allowed_event_types": ["done"],
                    },
                },
                "trace_source": {
                    "kind": "inline",
                    "trace_id": "trace-negative",
                    "request_id": "request-negative",
                    "audit_events": [
                        audit_event("request_started", trace_id="trace-negative", request_id="request-negative").model_dump(
                            mode="json"
                        ),
                        audit_event(
                            "tool_call",
                            trace_id="trace-negative",
                            request_id="request-negative",
                            route="tool_gateway",
                            metadata={"tool_id": "database_demo.safe_select"},
                        ).model_dump(mode="json"),
                        audit_event(
                            "request_completed",
                            trace_id="trace-negative",
                            request_id="request-negative",
                        ).model_dump(mode="json"),
                    ],
                    "sse_events": [
                        {
                            "type": "done",
                            "request_id": "request-negative",
                            "stage": "done",
                            "status": "completed",
                            "message": "Request completed",
                            "data": {},
                        }
                    ],
                },
            }
        )

        actual = AuditTraceExtractor().extract(expected.trace_source)
        result = TrajectoryMatcher().match(expected, actual)
        mismatch_codes = {mismatch.code for mismatch in result.mismatches}

        self.assertFalse(result.passed)
        self.assertIn("missing_audit_event", mismatch_codes)
        self.assertIn("missing_stage", mismatch_codes)
        self.assertIn("forbidden_tool_used", mismatch_codes)
        self.assertIn("sse_missing_trace_id", mismatch_codes)

    def test_runner_outputs_json_and_markdown_report(self):
        evalset_path = REPO_ROOT / "evals" / "enterprise" / "evalsets" / "chat_trace_evalset.jsonl"
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_trace_eval(
                evalset_path=evalset_path,
                output_dir=Path(tmpdir),
                write_report=True,
            )

            json_report = Path(report.report_json_path or "")
            markdown_report = Path(report.report_markdown_path or "")

            self.assertEqual(report.summary["total"], 1)
            self.assertEqual(report.summary["passed"], 1)
            self.assertEqual(report.summary["failed"], 0)
            self.assertTrue(json_report.exists())
            self.assertTrue(markdown_report.exists())
            self.assertIn("chat_doc_permission_blocked_001", markdown_report.read_text(encoding="utf-8"))

    def test_database_agent_eval_distinguishes_reference_and_live_agent_modes(self):
        evalset_path = (
            REPO_ROOT
            / "evals"
            / "enterprise"
            / "evalsets"
            / "database_agent_operations_2_0.jsonl"
        )

        reference_report = run_trace_eval(evalset_path=evalset_path, mode="reference", write_report=False)
        live_report = run_trace_eval(evalset_path=evalset_path, mode="live_agent", write_report=False)

        self.assertEqual(reference_report.mode, "reference")
        self.assertEqual(reference_report.summary["failed"], 0)
        self.assertTrue(all(result.mode == "reference" for result in reference_report.results))
        self.assertTrue(all(result.outcome == "passed" for result in reference_report.results))

        self.assertEqual(live_report.mode, "live_agent")
        self.assertEqual(live_report.summary["passed"], 0)
        self.assertEqual(live_report.summary["outcomes"], {"not_ready_live_agent": 2})
        self.assertTrue(all(result.mode == "live_agent" for result in live_report.results))
        self.assertTrue(all(result.outcome == "not_ready_live_agent" for result in live_report.results))

    def test_database_agent_eval_classifies_tool_sql_diff_audit_outcomes(self):
        base_trace = {
            "kind": "inline",
            "request_id": "request-db-outcome",
            "route": "database_demo",
            "sse_events": [
                {
                    "type": "done",
                    "trace_id": "trace-placeholder",
                    "request_id": "request-db-outcome",
                    "stage": "done",
                    "status": "completed",
                    "message": "done",
                    "data": {},
                }
            ],
        }

        def row(eval_id: str, trace_id: str, events: list[dict], expected: dict | None = None):
            sample = {
                "eval_id": eval_id,
                "input": {
                    "mode": "reference",
                    "route": "database_demo",
                    "prompt": eval_id,
                    "expected_tool": "database_demo.safe_select",
                    "expected_sql_family": "select",
                    "expected_tables": ["sandbox_sales.factory_access_events"],
                    "expected_columns": ["event_id"],
                    "expected_db_diff": "none",
                    "expected_audit_label": "database_query_allowed",
                    "expected_rejection_reason": "",
                },
                "expected": {
                    "final_status": "completed",
                    "required_stages": [],
                    "forbidden_tools": [],
                    "required_audit_events": [],
                },
                "trace_source": {
                    **base_trace,
                    "trace_id": trace_id,
                    "audit_events": events,
                    "sse_events": [
                        {**base_trace["sse_events"][0], "trace_id": trace_id},
                    ],
                },
            }
            if expected:
                sample["input"].update(expected)
            return sample

        def tool_event(trace_id: str) -> dict:
            return audit_event(
                "tool_call",
                trace_id=trace_id,
                request_id="request-db-outcome",
                route="tool_gateway",
                metadata={"tool_id": "database_demo.safe_select", "status": "success"},
            ).model_dump(mode="json")

        def database_event(trace_id: str, **metadata) -> dict:
            return audit_event(
                "database_query",
                trace_id=trace_id,
                request_id="request-db-outcome",
                route="database",
                decision=metadata.pop("decision", "allowed"),
                metadata={
                    "tool_id": "database_demo.safe_select",
                    "sql_family": "select",
                    "table_names": ["sandbox_sales.factory_access_events"],
                    "target_columns": ["event_id"],
                    "db_diff": "none",
                    "audit_label": "database_query_allowed",
                    **metadata,
                },
            ).model_dump(mode="json")

        samples = [
            row(
                "db_outcome_passed",
                "trace-db-outcome-passed",
                [tool_event("trace-db-outcome-passed"), database_event("trace-db-outcome-passed")],
            ),
            row("db_outcome_tool_not_called", "trace-db-outcome-no-tool", []),
            row(
                "db_outcome_sql_blocked",
                "trace-db-outcome-sql-blocked",
                [
                    tool_event("trace-db-outcome-sql-blocked"),
                    database_event(
                        "trace-db-outcome-sql-blocked",
                        decision="denied",
                        status="blocked",
                        blocked_reason="non_select_statement_not_allowed",
                    ),
                ],
            ),
            row(
                "db_outcome_db_diff_failed",
                "trace-db-outcome-diff",
                [
                    tool_event("trace-db-outcome-diff"),
                    database_event("trace-db-outcome-diff", db_diff="rows_changed"),
                ],
            ),
            row(
                "db_outcome_audit_missing",
                "trace-db-outcome-audit",
                [
                    tool_event("trace-db-outcome-audit"),
                    database_event("trace-db-outcome-audit", audit_label="unexpected_audit"),
                ],
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            evalset_path = Path(tmpdir) / "db_outcomes.jsonl"
            with evalset_path.open("w", encoding="utf-8") as file:
                for sample in samples:
                    file.write(json.dumps(sample, ensure_ascii=False) + "\n")

            report = run_trace_eval(evalset_path=evalset_path, mode="reference", write_report=False)

        self.assertEqual(
            [result.outcome for result in report.results],
            ["passed", "tool_not_called", "sql_blocked", "db_diff_failed", "audit_missing"],
        )
        self.assertEqual(
            report.summary["outcomes"],
            {
                "audit_missing": 1,
                "db_diff_failed": 1,
                "passed": 1,
                "sql_blocked": 1,
                "tool_not_called": 1,
            },
        )

    def test_aiops_matcher_checks_required_tools_failure_semantics_and_evidence(self):
        expected = ExpectedTrajectory.model_validate(
            {
                "eval_id": "aiops_semantics_001",
                "input": {
                    "route": "aiops",
                    "aiops_required_tools": [
                        "query_active_alerts",
                        "query_metric_series",
                        "search_service_logs",
                    ],
                    "aiops_required_evidence_categories": ["metric", "log"],
                    "expected_failure_semantics": "structured_output_recovered",
                },
                "expected": {
                    "final_status": "completed",
                    "required_stages": ["gateway", "tool"],
                    "required_audit_events": ["tool_call", "aiops_degradation", "request_completed"],
                },
                "trace_source": {
                    "kind": "inline",
                    "trace_id": "trace-aiops-semantics",
                    "request_id": "request-aiops-semantics",
                    "route": "aiops",
                    "audit_events": [
                        audit_event(
                            "request_started",
                            trace_id="trace-aiops-semantics",
                            request_id="request-aiops-semantics",
                            route="aiops",
                        ).model_dump(mode="json"),
                        audit_event(
                            "tool_call",
                            trace_id="trace-aiops-semantics",
                            request_id="request-aiops-semantics",
                            route="tool_gateway",
                            metadata={
                                "tool_id": "query_active_alerts",
                                "evidence_categories": [],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "tool_call",
                            trace_id="trace-aiops-semantics",
                            request_id="request-aiops-semantics",
                            route="tool_gateway",
                            metadata={
                                "tool_id": "query_metric_series",
                                "evidence_categories": ["metric"],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "tool_call",
                            trace_id="trace-aiops-semantics",
                            request_id="request-aiops-semantics",
                            route="tool_gateway",
                            metadata={
                                "tool_id": "search_service_logs",
                                "evidence_categories": ["log"],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "aiops_degradation",
                            trace_id="trace-aiops-semantics",
                            request_id="request-aiops-semantics",
                            route="aiops",
                            metadata={
                                "failure_semantics": "structured_output_recovered",
                                "failure_semantics_hard_failure": False,
                                "evidence_categories": ["metric", "log"],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "request_completed",
                            trace_id="trace-aiops-semantics",
                            request_id="request-aiops-semantics",
                            route="aiops",
                        ).model_dump(mode="json"),
                    ],
                    "sse_events": [
                        {
                            "type": "status",
                            "trace_id": "trace-aiops-semantics",
                            "request_id": "request-aiops-semantics",
                            "stage": "replanner",
                            "status": "running",
                            "message": "fallback recovered",
                            "data": {},
                            "failure_semantics": "structured_output_recovered",
                            "failure_semantics_hard_failure": False,
                        },
                        {
                            "type": "done",
                            "trace_id": "trace-aiops-semantics",
                            "request_id": "request-aiops-semantics",
                            "stage": "done",
                            "status": "completed",
                            "message": "done",
                            "data": {"evidence_categories": ["metric", "log"]},
                        },
                    ],
                },
            }
        )

        result = TrajectoryMatcher().match(expected, AuditTraceExtractor().extract(expected.trace_source))

        self.assertTrue(result.passed)

    def test_aiops_matcher_accepts_recovered_infra_error_with_intermediate_infra_evidence(self):
        expected = ExpectedTrajectory.model_validate(
            {
                "eval_id": "aiops_recovered_infra_001",
                "input": {
                    "route": "aiops",
                    "aiops_required_tools": [
                        "query_active_alerts",
                        "query_metric_series",
                        "search_service_logs",
                    ],
                    "aiops_required_evidence_categories": ["metric", "log"],
                    "expected_failure_semantics": "recovered_infra_error",
                },
                "expected": {
                    "final_status": "completed",
                    "required_stages": ["tool"],
                    "required_audit_events": ["tool_call"],
                },
                "trace_source": {
                    "kind": "inline",
                    "trace_id": "trace-aiops-recovered-infra",
                    "request_id": "request-aiops-recovered-infra",
                    "route": "aiops",
                    "audit_events": [
                        audit_event(
                            "tool_call",
                            trace_id="trace-aiops-recovered-infra",
                            request_id="request-aiops-recovered-infra",
                            route="tool_gateway",
                            metadata={
                                "tool_id": "query_active_alerts",
                                "evidence_categories": [],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "tool_call",
                            trace_id="trace-aiops-recovered-infra",
                            request_id="request-aiops-recovered-infra",
                            route="tool_gateway",
                            metadata={
                                "tool_id": "query_metric_series",
                                "evidence_categories": ["metric"],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "tool_call",
                            trace_id="trace-aiops-recovered-infra",
                            request_id="request-aiops-recovered-infra",
                            route="tool_gateway",
                            metadata={
                                "tool_id": "search_service_logs",
                                "evidence_categories": ["log"],
                            },
                        ).model_dump(mode="json"),
                    ],
                    "sse_events": [
                        {
                            "type": "step_complete",
                            "trace_id": "trace-aiops-recovered-infra",
                            "request_id": "request-aiops-recovered-infra",
                            "stage": "step_executed",
                            "status": "completed",
                            "message": "transient executor failure",
                            "data": {},
                            "infra_error": True,
                            "failure_semantics": "infra_error",
                            "failure_semantics_hard_failure": True,
                        },
                        {
                            "type": "complete",
                            "trace_id": "trace-aiops-recovered-infra",
                            "request_id": "request-aiops-recovered-infra",
                            "stage": "diagnosis_complete",
                            "status": "completed",
                            "message": "diagnosis complete",
                            "data": {"evidence_categories": ["metric", "log"]},
                            "failure_semantics": "recovered_infra_error",
                            "failure_semantics_hard_failure": False,
                        },
                    ],
                },
            }
        )

        result = TrajectoryMatcher().match(expected, AuditTraceExtractor().extract(expected.trace_source))

        self.assertTrue(result.passed, result.mismatches)

    def test_aiops_matcher_detects_semantics_and_evidence_mismatches(self):
        expected = ExpectedTrajectory.model_validate(
            {
                "eval_id": "aiops_semantics_negative_001",
                "input": {
                    "route": "aiops",
                    "aiops_required_tools": [
                        "query_active_alerts",
                        "query_metric_series",
                        "search_service_logs",
                    ],
                    "aiops_required_evidence_categories": ["metric", "log"],
                    "expected_failure_semantics": "structured_output_recovered",
                },
                "expected": {
                    "final_status": "completed",
                    "required_stages": ["gateway", "tool"],
                    "required_audit_events": ["tool_call", "request_completed"],
                },
                "trace_source": {
                    "kind": "inline",
                    "trace_id": "trace-aiops-semantics-negative",
                    "request_id": "request-aiops-semantics-negative",
                    "route": "aiops",
                    "audit_events": [
                        audit_event(
                            "tool_call",
                            trace_id="trace-aiops-semantics-negative",
                            request_id="request-aiops-semantics-negative",
                            route="tool_gateway",
                            metadata={
                                "tool_id": "query_active_alerts",
                                "evidence_categories": ["metric"],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "aiops_degradation",
                            trace_id="trace-aiops-semantics-negative",
                            request_id="request-aiops-semantics-negative",
                            route="aiops",
                            metadata={
                                "failure_semantics": "structured_output_recovered",
                                "failure_semantics_hard_failure": True,
                                "evidence_categories": ["metric"],
                            },
                        ).model_dump(mode="json"),
                        audit_event(
                            "request_completed",
                            trace_id="trace-aiops-semantics-negative",
                            request_id="request-aiops-semantics-negative",
                            route="aiops",
                        ).model_dump(mode="json"),
                    ],
                    "sse_events": [
                        {
                            "type": "status",
                            "trace_id": "trace-aiops-semantics-negative",
                            "request_id": "request-aiops-semantics-negative",
                            "stage": "replanner",
                            "status": "running",
                            "message": "fallback recovered",
                            "data": {},
                            "failure_semantics": "infra_error",
                            "failure_semantics_hard_failure": True,
                        },
                        {
                            "type": "done",
                            "trace_id": "trace-aiops-semantics-negative",
                            "request_id": "request-aiops-semantics-negative",
                            "stage": "done",
                            "status": "completed",
                            "message": "done",
                            "data": {"evidence_categories": ["metric"]},
                        },
                    ],
                },
            }
        )

        result = TrajectoryMatcher().match(expected, AuditTraceExtractor().extract(expected.trace_source))
        mismatch_codes = {mismatch.code for mismatch in result.mismatches}

        self.assertFalse(result.passed)
        self.assertIn("aiops_required_tool_missing", mismatch_codes)
        self.assertIn("aiops_failure_semantics_inconsistent", mismatch_codes)
        self.assertIn("aiops_degradation_hard_failure", mismatch_codes)
        self.assertIn("aiops_evidence_missing", mismatch_codes)

    def test_bundled_evalsets_are_valid_and_passing(self):
        evalset_dir = REPO_ROOT / "evals" / "enterprise" / "evalsets"
        evalsets = {
            "chat_trace_evalset.jsonl": 1,
            "aiops_trace_evalset.jsonl": 2,
            "sse_contract_evalset.jsonl": 1,
        }

        for evalset_name, expected_total in evalsets.items():
            report = run_trace_eval(
                evalset_path=evalset_dir / evalset_name,
                write_report=False,
            )
            self.assertEqual(report.summary["total"], expected_total)
            self.assertEqual(report.summary["failed"], 0)
            self.assertEqual(report.summary["passed"], expected_total)


class EnterpriseTraceEvalF2bTests(unittest.TestCase):
    def test_expected_contract_model_validates_shape(self):
        sample = {
            "eval_id": "contract_sample_001",
            "input": {"route": "aiops", "question": "diagnose alert"},
            "expected": {
                "final_status": "completed",
                "required_stages": ["gateway", "task_contract", "tool"],
                "required_audit_events": ["task_contract_created"],
                "expected_contract": {
                    "required_scope": {
                        "allowed_data_sources": ["kb-prod-runbook"],
                        "allowed_tools": ["aiops.search_logs"],
                        "forbidden_actions": ["restart_service"],
                    },
                    "forbidden_tools": ["database-demo"],
                    "requires_human_approval": False,
                    "success_criteria_keywords": ["symptoms", "evidence"],
                },
                "sse": {
                    "must_include_trace_id": True,
                    "must_include_request_id": True,
                    "allowed_event_types": ["plan", "report", "done"],
                },
            },
            "trace_source": {
                "kind": "inline",
                "trace_id": "trace-contract",
                "request_id": "request-contract",
                "audit_events": [],
                "sse_events": [],
                "task_contracts": [],
            },
        }

        expected = ExpectedTrajectory.model_validate(sample)

        self.assertEqual(expected.expected.expected_contract.required_scope.allowed_data_sources, ["kb-prod-runbook"])
        self.assertEqual(expected.expected.expected_contract.forbidden_tools, ["database-demo"])

    def test_extractor_recovers_contract_from_sqlite_repository(self):
        matching_contract = TaskContract(
            trace_id="trace-contract-sqlite",
            request_id="request-contract-sqlite",
            user_id="user_f2b_test",
            user_goal="diagnose alert",
            scope=TaskScope(
                allowed_data_sources=["kb-prod-runbook"],
                allowed_tools=["aiops.search_logs"],
                forbidden_actions=["restart_service"],
            ),
            success_criteria=["symptoms", "evidence"],
            risk_level=RiskLevel.MEDIUM,
            requires_human_approval=False,
            expected_outputs=["diagnostic_report"],
            status=TaskStatus.RUNNING,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            audit_path = tmp_path / "audit.sqlite"
            contract_path = tmp_path / "contracts.sqlite"
            audit_sink = SQLiteAuditSink(audit_path)
            contract_repo = SQLiteTaskContractRepository(contract_path)

            contract_repo.create(matching_contract)
            audit_sink.emit(
                task_contract_event(
                    "task_contract_created",
                    task_id=matching_contract.task_id,
                    trace_id=matching_contract.trace_id,
                    request_id=matching_contract.request_id,
                    status=matching_contract.status.value,
                    risk_level=matching_contract.risk_level.value,
                    allowed_data_sources=matching_contract.scope.allowed_data_sources,
                    allowed_tools=matching_contract.scope.allowed_tools,
                    forbidden_actions=matching_contract.scope.forbidden_actions,
                    success_criteria=matching_contract.success_criteria,
                    expected_outputs=matching_contract.expected_outputs,
                )
            )
            audit_sink.emit(
                audit_event(
                    "request_completed",
                    trace_id=matching_contract.trace_id,
                    request_id=matching_contract.request_id,
                    route="aiops",
                )
            )

            actual = AuditTraceExtractor().extract(
                TraceSource(
                    kind="sqlite",
                    trace_id=matching_contract.trace_id,
                    request_id=matching_contract.request_id,
                    route="aiops",
                    path=audit_path.as_posix(),
                    task_contract_path=contract_path.as_posix(),
                )
            )

        self.assertIsNotNone(actual.task_contract)
        self.assertEqual(actual.task_contract.task_contract_id, matching_contract.task_id)
        self.assertEqual(actual.task_contract.status, "running")
        self.assertEqual(actual.task_contract.allowed_tools, ["aiops.search_logs"])

    def test_matcher_detects_contract_and_success_criteria_mismatches(self):
        expected = ExpectedTrajectory.model_validate(
            {
                "eval_id": "contract_negative_001",
                "expected": {
                    "final_status": "completed",
                    "required_stages": ["gateway", "task_contract", "tool"],
                    "required_audit_events": ["task_contract_created", "task_contract_success_checked"],
                    "expected_contract": {
                        "required_scope": {
                            "allowed_data_sources": ["kb-prod-runbook"],
                            "allowed_tools": ["aiops.search_logs"],
                            "forbidden_actions": ["restart_service"],
                        },
                        "forbidden_tools": ["database-demo"],
                        "requires_human_approval": True,
                        "success_criteria_keywords": ["symptoms", "evidence"],
                    },
                    "sse": {
                        "must_include_trace_id": True,
                        "must_include_request_id": True,
                        "allowed_event_types": ["plan", "report", "done"],
                    },
                },
                "trace_source": {
                    "kind": "inline",
                    "trace_id": "trace-contract-negative",
                    "request_id": "request-contract-negative",
                    "route": "aiops",
                    "audit_events": [
                        task_contract_event(
                            "task_contract_created",
                            task_id="task-contract-negative",
                            trace_id="trace-contract-negative",
                            request_id="request-contract-negative",
                            status="running",
                            risk_level="high",
                            requires_human_approval=False,
                            allowed_data_sources=["kb-prod-runbook"],
                            allowed_tools=["aiops.search_logs"],
                            forbidden_actions=["restart_service"],
                            success_criteria=["symptoms", "evidence"],
                            expected_outputs=["diagnostic_report"],
                        ).model_dump(mode="json"),
                        audit_event(
                            "tool_call",
                            trace_id="trace-contract-negative",
                            request_id="request-contract-negative",
                            route="tool_gateway",
                            metadata={"tool_id": "database-demo.safe_select"},
                        ).model_dump(mode="json"),
                        audit_event(
                            "request_completed",
                            trace_id="trace-contract-negative",
                            request_id="request-contract-negative",
                            route="aiops",
                        ).model_dump(mode="json"),
                    ],
                    "sse_events": [
                        {
                            "type": "report",
                            "trace_id": "trace-contract-negative",
                            "request_id": "request-contract-negative",
                            "stage": "report",
                            "status": "completed",
                            "message": "Report generated",
                            "data": {"summary": "diagnosis complete"},
                        },
                        {
                            "type": "done",
                            "trace_id": "trace-contract-negative",
                            "request_id": "request-contract-negative",
                            "stage": "done",
                            "status": "completed",
                            "message": "Request completed",
                            "data": {},
                        },
                    ],
                },
            }
        )

        actual = AuditTraceExtractor().extract(expected.trace_source)
        result = TrajectoryMatcher().match(expected, actual)
        mismatch_codes = {mismatch.code for mismatch in result.mismatches}

        self.assertFalse(result.passed)
        self.assertIn("approval_missing", mismatch_codes)
        self.assertIn("scope_violation", mismatch_codes)
        self.assertIn("success_criteria_unchecked", mismatch_codes)

    def test_matcher_detects_missing_contract(self):
        expected = ExpectedTrajectory.model_validate(
            {
                "eval_id": "contract_missing_001",
                "expected": {
                    "final_status": "completed",
                    "required_stages": ["gateway", "task_contract"],
                    "expected_contract": {
                        "required_scope": {"allowed_data_sources": ["kb-prod-runbook"]},
                        "success_criteria_keywords": ["symptoms"],
                    },
                    "sse": {
                        "must_include_trace_id": True,
                        "must_include_request_id": True,
                        "allowed_event_types": ["done"],
                    },
                },
                "trace_source": {
                    "kind": "inline",
                    "trace_id": "trace-contract-missing",
                    "request_id": "request-contract-missing",
                    "route": "aiops",
                    "audit_events": [
                        audit_event(
                            "request_started",
                            trace_id="trace-contract-missing",
                            request_id="request-contract-missing",
                            route="aiops",
                        ).model_dump(mode="json"),
                        audit_event(
                            "request_completed",
                            trace_id="trace-contract-missing",
                            request_id="request-contract-missing",
                            route="aiops",
                        ).model_dump(mode="json"),
                    ],
                    "sse_events": [
                        {
                            "type": "done",
                            "trace_id": "trace-contract-missing",
                            "request_id": "request-contract-missing",
                            "stage": "done",
                            "status": "completed",
                            "message": "Request completed",
                            "data": {},
                        }
                    ],
                },
            }
        )

        result = TrajectoryMatcher().match(expected, AuditTraceExtractor().extract(expected.trace_source))
        self.assertFalse(result.passed)
        self.assertTrue(any(mismatch.code == "contract_missing" for mismatch in result.mismatches))

    def test_bundled_evalsets_are_valid_and_passing(self):
        evalset_dir = REPO_ROOT / "evals" / "enterprise" / "evalsets"
        evalsets = {
            "chat_trace_evalset.jsonl": 1,
            "aiops_trace_evalset.jsonl": 2,
            "sse_contract_evalset.jsonl": 1,
            "db_trace_evalset.jsonl": 2,
            "admin_trace_evalset.jsonl": 1,
            "database_agent_operations_2_0.jsonl": 2,
        }

        for evalset_name, expected_total in evalsets.items():
            report = run_trace_eval(
                evalset_path=evalset_dir / evalset_name,
                write_report=False,
            )
            self.assertEqual(report.summary["total"], expected_total)
            self.assertEqual(report.summary["failed"], 0)
            self.assertEqual(report.summary["passed"], expected_total)


if __name__ == "__main__":
    unittest.main()
