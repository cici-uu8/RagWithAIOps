import unittest

from app.enterprise.adapters.aiops_adapter import AIOpsAdapter
from app.enterprise.context import RequestContext
from app.enterprise.gateway.guardrail_providers import NoOpGuardrailProvider
from app.enterprise.gateway.guardrail_service import GuardrailService
from app.enterprise.gateway.rate_limit_service import NoOpRateLimitService
from app.enterprise.gateway.request_gateway import RequestGateway
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.enterprise.tasks.models import RiskLevel, TaskContractCreate, TaskScope, TaskStatus
from app.enterprise.tasks.repository import InMemoryTaskContractRepository
from app.enterprise.tasks.service import TaskContractService
from app.enterprise.tasks.validator import ContractValidator
from app.models.aiops import AIOpsRequest


def request_context() -> RequestContext:
    return RequestContext(
        request_id="request-f1",
        trace_id="trace-f1",
        user_id="user_f1",
        username="user_f1",
        department_id="ops",
        department_name="Operations",
        roles=["operator"],
    )


def grant(resource_type: str, resource_id: str, action: str) -> ResourceGrant:
    return ResourceGrant(
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        principal_type=PrincipalType.USER,
        principal_id="user_f1",
        effect=GrantEffect.ALLOW,
        reason="test_allow",
    )


def build_contract_service(
    *,
    grants: list[ResourceGrant] | None = None,
):
    sink = InMemoryAuditSink()
    permissions = PermissionService(
        repository=InMemoryGovernanceRepository(grants=grants or []),
        audit_service=AuditService(sinks=[sink]),
    )
    service = TaskContractService(
        repository=InMemoryTaskContractRepository(),
        validator=ContractValidator(permissions),
        audit_service=AuditService(sinks=[sink]),
    )
    return service, sink


def valid_contract_create(**updates) -> TaskContractCreate:
    payload = {
        "user_goal": "diagnose current production alert",
        "scope": TaskScope(
            allowed_data_sources=["kb-prod-runbook"],
            allowed_tools=["retrieve_knowledge"],
            forbidden_actions=["restart_service"],
        ),
        "success_criteria": ["explain symptoms", "cite evidence"],
        "risk_level": RiskLevel.MEDIUM,
        "requires_human_approval": False,
        "expected_outputs": ["diagnostic_report"],
    }
    payload.update(updates)
    return TaskContractCreate(**payload)


class FakeAIOpsService:
    def __init__(self):
        self.calls: list[dict] = []

    async def diagnose(self, **kwargs):
        self.calls.append(kwargs)
        yield {
            "type": "complete",
            "stage": "diagnosis_complete",
            "message": "done",
            "diagnosis": {"status": "completed", "report": "ok"},
        }


class EnterpriseTaskContractF1Tests(unittest.IsolatedAsyncioTestCase):
    def test_complex_task_contract_is_created_persisted_and_audited(self):
        service, sink = build_contract_service(
            grants=[
                grant("document", "kb-prod-runbook", "read"),
                grant("tool", "retrieve_knowledge", "use"),
            ]
        )

        result = service.create_contract(request_context(), valid_contract_create())

        self.assertTrue(result.can_execute)
        self.assertEqual(result.contract.status, TaskStatus.RUNNING)
        self.assertEqual(service.get_contract(result.contract.task_id), result.contract)
        self.assertEqual(service.list_by_trace("trace-f1"), [result.contract])
        task_events = [event for event in sink.events if event.event_type == "task_contract_created"]
        self.assertEqual(len(task_events), 1)
        self.assertEqual(task_events[0].decision, "allowed")
        self.assertEqual(task_events[0].metadata["task_id"], result.contract.task_id)

    def test_unauthorized_data_source_rejects_contract_and_writes_audit(self):
        service, sink = build_contract_service(
            grants=[grant("tool", "retrieve_knowledge", "use")]
        )

        result = service.create_contract(request_context(), valid_contract_create())

        self.assertFalse(result.can_execute)
        self.assertEqual(result.contract.status, TaskStatus.REJECTED)
        self.assertEqual(result.reason, "data_source_permission_denied")
        rejected = [event for event in sink.events if event.event_type == "task_contract_rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].decision, "denied")
        self.assertEqual(rejected[0].metadata["issue_codes"], ["data_source_permission_denied"])

    def test_high_risk_contract_requires_approval_before_execution(self):
        service, sink = build_contract_service(
            grants=[
                grant("document", "kb-prod-runbook", "read"),
                grant("tool", "retrieve_knowledge", "use"),
            ]
        )

        result = service.create_contract(
            request_context(),
            valid_contract_create(
                risk_level=RiskLevel.HIGH,
                requires_human_approval=True,
            ),
        )

        self.assertFalse(result.can_execute)
        self.assertEqual(result.decision, "pending_approval")
        self.assertEqual(result.contract.status, TaskStatus.PENDING)
        created = [event for event in sink.events if event.event_type == "task_contract_created"]
        self.assertEqual(created[-1].decision, "pending_approval")

    async def test_simple_aiops_request_keeps_legacy_path_without_contract(self):
        audit_sink = InMemoryAuditSink()
        gateway = RequestGateway(
            audit_service=AuditService(sinks=[audit_sink]),
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        fake_aiops = FakeAIOpsService()
        contract_service, _sink = build_contract_service()
        adapter = AIOpsAdapter(
            fake_aiops,
            gateway=gateway,
            contract_service=contract_service,
        )

        events = []
        async for event in adapter.diagnose_stream(
            AIOpsRequest(session_id="session-simple"),
            headers={"X-Trace-Id": "trace-simple", "X-Request-Id": "request-simple"},
            session_id="session-simple",
            memory_mode="off",
        ):
            events.append(event)

        self.assertEqual(len(fake_aiops.calls), 1)
        self.assertIsNone(fake_aiops.calls[0]["task_contract_id"])
        self.assertEqual(events[-1]["type"], "complete")
        self.assertNotIn("task_contract_id", events[-1])

    async def test_complex_aiops_request_passes_task_contract_id_to_execution(self):
        audit_sink = InMemoryAuditSink()
        gateway = RequestGateway(
            audit_service=AuditService(sinks=[audit_sink]),
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        fake_aiops = FakeAIOpsService()
        contract_service, contract_audit = build_contract_service(
            grants=[
                grant("document", "kb-prod-runbook", "read"),
                grant("tool", "retrieve_knowledge", "use"),
            ]
        )
        adapter = AIOpsAdapter(
            fake_aiops,
            gateway=gateway,
            contract_service=contract_service,
        )

        events = []
        async for event in adapter.diagnose_stream(
            AIOpsRequest(
                session_id="session-complex",
                query="diagnose alert",
                task_contract={
                    "user_goal": "diagnose alert",
                    "scope": {
                        "allowed_data_sources": ["kb-prod-runbook"],
                        "allowed_tools": ["retrieve_knowledge"],
                        "forbidden_actions": ["restart_service"],
                    },
                    "success_criteria": ["explain symptoms"],
                    "risk_level": "medium",
                    "expected_outputs": ["diagnostic_report"],
                },
            ),
            headers={
                "X-Trace-Id": "trace-complex",
                "X-Request-Id": "request-complex",
                "X-User-Id": "user_f1",
            },
            session_id="session-complex",
            memory_mode="off",
        ):
            events.append(event)

        contract_event = [
            event
            for event in contract_audit.events
            if event.event_type == "task_contract_created"
        ][0]
        task_contract_id = contract_event.metadata["task_id"]
        self.assertEqual(len(fake_aiops.calls), 1)
        self.assertEqual(fake_aiops.calls[0]["task_contract_id"], task_contract_id)
        self.assertEqual(events[-1]["task_contract_id"], task_contract_id)

    async def test_rejected_aiops_contract_returns_sse_error_without_planner_call(self):
        audit_sink = InMemoryAuditSink()
        gateway = RequestGateway(
            audit_service=AuditService(sinks=[audit_sink]),
            guardrail_service=GuardrailService(providers=[NoOpGuardrailProvider()]),
            rate_limit_service=NoOpRateLimitService(),
        )
        fake_aiops = FakeAIOpsService()
        contract_service, contract_audit = build_contract_service()
        adapter = AIOpsAdapter(
            fake_aiops,
            gateway=gateway,
            contract_service=contract_service,
        )

        events = []
        async for event in adapter.diagnose_stream(
            AIOpsRequest(
                session_id="session-denied",
                task_contract={
                    "user_goal": "diagnose alert",
                    "scope": {
                        "allowed_data_sources": ["kb-prod-runbook"],
                        "allowed_tools": ["retrieve_knowledge"],
                    },
                    "success_criteria": ["explain symptoms"],
                    "risk_level": "medium",
                },
            ),
            headers={
                "X-Trace-Id": "trace-denied",
                "X-Request-Id": "request-denied",
                "X-User-Id": "user_f1",
            },
            session_id="session-denied",
            memory_mode="off",
        ):
            events.append(event)

        self.assertEqual(fake_aiops.calls, [])
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["reason"], "data_source_permission_denied,tool_permission_denied")
        rejected = [
            event
            for event in contract_audit.events
            if event.event_type == "task_contract_rejected"
        ]
        self.assertEqual(len(rejected), 1)


if __name__ == "__main__":
    unittest.main()
