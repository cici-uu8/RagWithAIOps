import tempfile
import unittest
from pathlib import Path

from app.enterprise.adapters.aiops_adapter import AIOpsAdapter
from app.enterprise.context import RequestContext
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import (
    AuditService,
    InMemoryAuditSink,
    SQLiteAuditSink,
)
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tasks.repository import InMemoryTaskContractRepository
from app.enterprise.tasks.service import TaskContractService
from app.enterprise.tasks.validator import ContractValidator
from app.enterprise.verifiers import (
    CitationVerifier,
    PlanVerifier,
    SqlResultVerifier,
    VerificationService,
    VerificationStatus,
)
from app.models import ParserEngine, RetrievalQuery, RetrievalResponse, RetrievalResult, SourceRef
from app.models.aiops import AIOpsRequest


def request_context() -> RequestContext:
    return RequestContext(
        request_id="request-f4",
        trace_id="trace-f4",
        user_id="user_f4",
        username="user_f4",
        department_id="ops",
        department_name="Operations",
        roles=["operator"],
    )


def source_ref(doc_id: str, *, source_file: str) -> SourceRef:
    return SourceRef(
        kb_id="kb-main",
        doc_id=doc_id,
        chunk_id=f"{doc_id}:c0001",
        source_file=source_file,
        parser_engine=ParserEngine.PLAIN_TEXT,
    )


def retrieval_result(
    *,
    doc_id: str,
    source_doc_id: str,
    citation_text: str,
) -> RetrievalResult:
    ref = source_ref(source_doc_id, source_file=f"{source_doc_id}.md")
    return RetrievalResult(
        kb_id="kb-main",
        doc_id=doc_id,
        chunk_id=f"{doc_id}:c0001",
        content="diagnostic evidence",
        score=0.5,
        source_ref=ref,
        citation_text=citation_text,
    )


def build_contract_service(audit_service: AuditService) -> TaskContractService:
    permission_service = PermissionService(
        repository=InMemoryGovernanceRepository(),
        audit_service=audit_service,
    )
    permission_service.grant_access(
        ResourceGrant(
            resource_type="tool",
            resource_id="retrieve_knowledge",
            action="use",
            principal_type=PrincipalType.USER,
            principal_id="user_f4",
            effect=GrantEffect.ALLOW,
        )
    )
    return TaskContractService(
        repository=InMemoryTaskContractRepository(),
        validator=ContractValidator(permission_service),
        audit_service=audit_service,
    )


class FakePlanThenCompleteAIOpsService:
    async def diagnose(self, **_kwargs):
        yield {
            "type": "plan",
            "stage": "plan_created",
            "message": "plan ready",
            "plan": [
                "tool:restart_service",
                "collect alert context",
            ],
        }
        yield {
            "type": "complete",
            "stage": "diagnosis_complete",
            "message": "should not be emitted after verifier failure",
        }


class EnterpriseVerifierF4Tests(unittest.IsolatedAsyncioTestCase):
    def test_citation_verifier_uses_source_ref_not_display_citation_text(self):
        response = RetrievalResponse(
            query=RetrievalQuery(query="restart procedure"),
            results=[
                retrieval_result(
                    doc_id="doc-visible",
                    source_doc_id="doc-hidden",
                    citation_text="visible.md#Visible SOP",
                )
            ],
            context_text="diagnostic evidence",
        )

        result = CitationVerifier().verify(
            request_context(),
            {
                "response": response,
                "allowed_document_ids": ["doc-visible"],
            },
        )

        self.assertEqual(result.status, VerificationStatus.FAILED)
        self.assertEqual(result.findings[0].code, "citation_source_not_authorized")
        self.assertEqual(result.findings[0].metadata["source_doc_id"], "doc-hidden")

    def test_sql_result_verifier_requires_safe_sql_provenance_and_authorized_columns(self):
        verifier = SqlResultVerifier()

        missing_provenance = verifier.verify(
            request_context(),
            {
                "result": {
                    "status": "success",
                    "columns": ["order_id"],
                    "rows": [{"order_id": 1001}],
                },
                "authorized_columns": ["order_id"],
            },
        )
        unauthorized_column = verifier.verify(
            request_context(),
            {
                "result": {
                    "status": "success",
                    "safe_sql_verified": True,
                    "columns": ["order_id", "customer_email"],
                    "rows": [{"order_id": 1001, "customer_email": "a***@example.com"}],
                },
                "authorized_columns": ["order_id"],
            },
        )
        passed = verifier.verify(
            request_context(),
            {
                "result": {
                    "status": "success",
                    "safe_sql_verified": True,
                    "columns": ["order_id"],
                    "rows": [{"order_id": 1001}],
                },
                "authorized_columns": ["order_id"],
            },
        )

        self.assertEqual(missing_provenance.status, VerificationStatus.FAILED)
        self.assertEqual(missing_provenance.findings[0].code, "sql_result_not_safe_sql_verified")
        self.assertEqual(unauthorized_column.status, VerificationStatus.FAILED)
        self.assertEqual(unauthorized_column.findings[0].code, "sql_result_column_not_authorized")
        self.assertEqual(passed.status, VerificationStatus.PASSED)

    def test_verification_service_records_traceable_audit_and_original_error_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = SQLiteAuditSink(Path(tmpdir) / "audit.sqlite3")
            service = VerificationService(audit_service=AuditService(sinks=[sink]))
            original_error = RuntimeError("planner emitted invalid plan")

            result = service.verify(
                request_context(),
                PlanVerifier(max_steps=1),
                {
                    "plan": ["collect context", "tool:retrieve_knowledge"],
                    "task_contract": {
                        "user_goal": "diagnose alert",
                        "scope": {
                            "allowed_tools": ["retrieve_knowledge"],
                            "forbidden_actions": [],
                        },
                    },
                },
                original_error=original_error,
                revision_attempts=1,
            )

            events = sink.query(trace_id="trace-f4", event_type="verification_result")

        self.assertEqual(result.status, VerificationStatus.NEEDS_REVISION)
        self.assertTrue(service.should_stop(result, revision_attempts=1))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].trace_id, "trace-f4")
        self.assertEqual(events[0].error_class, "RuntimeError")
        self.assertIn("invalid plan", events[0].error_message)
        self.assertEqual(events[0].metadata["max_revision_attempts"], 1)
        self.assertEqual(events[0].metadata["findings"][0]["code"], "plan_too_many_steps")

    async def test_aiops_adapter_blocks_contract_plan_violation_and_audits_verifier(self):
        sink = InMemoryAuditSink()
        audit_service = AuditService(sinks=[sink])
        gateway = RequestGateway(
            audit_service=audit_service,
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        adapter = AIOpsAdapter(
            FakePlanThenCompleteAIOpsService(),
            gateway=gateway,
            contract_service=build_contract_service(audit_service),
            verification_service=VerificationService(audit_service=audit_service),
        )

        events = []
        async for event in adapter.diagnose_stream(
            AIOpsRequest(
                session_id="session-f4",
                query="diagnose alert",
                task_contract={
                    "user_goal": "diagnose alert",
                    "scope": {
                        "allowed_tools": ["retrieve_knowledge"],
                        "forbidden_actions": ["restart_service"],
                    },
                    "risk_level": "medium",
                },
            ),
            headers={
                "X-Trace-Id": "trace-f4-adapter",
                "X-Request-Id": "request-f4-adapter",
                "X-User-Id": "user_f4",
            },
            session_id="session-f4",
            memory_mode="off",
        ):
            events.append(event)

        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["stage"], "verifier")
        self.assertEqual(events[-1]["status"], "failed")
        self.assertIn("plan_forbidden_action", events[-1]["data"]["finding_codes"])
        self.assertNotIn("diagnosis_complete", [event.get("stage") for event in events])
        verifier_events = [event for event in sink.events if event.event_type == "verification_result"]
        self.assertEqual(len(verifier_events), 1)
        self.assertEqual(verifier_events[0].trace_id, "trace-f4-adapter")
        self.assertEqual(verifier_events[0].decision, "failed")


if __name__ == "__main__":
    unittest.main()
