import tempfile
import unittest
from pathlib import Path

from app.enterprise.admin.memory_operator_adapter import MemoryOperatorAdapter
from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.models.memory import (
    MemoryRecord,
    MemoryReviewDecision,
    MemoryStatus,
    MemoryType,
    PlanTemplatePayload,
)
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore


class MemoryOperatorAdapterTests(unittest.TestCase):
    def _context(self) -> RequestContext:
        return RequestContext(
            request_id="request-memory-adapter",
            trace_id="trace-memory-adapter",
            user_id="user_admin",
            username="admin",
            department_id="platform",
            department_name="Platform",
            roles=("admin",),
        )

    def _adapter(self, tmpdir: str):
        store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
        review_service = MemoryReviewService(store=store)
        sink = InMemoryAuditSink()
        adapter = MemoryOperatorAdapter(
            review_service=review_service,
            store=store,
            audit_service=AuditService(sinks=[sink]),
        )
        return adapter, store, sink

    def test_approve_uses_context_user_as_reviewer_and_records_domain_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter, store, sink = self._adapter(tmpdir)
            store.upsert(self._plan_record("mem_candidate", MemoryStatus.CANDIDATE))

            result = adapter.approve(
                self._context(),
                "mem_candidate",
                decision_note="validated by operator",
            )

            self.assertEqual(result["record"]["status"], "active")
            reviewed = store.get("mem_candidate")
            self.assertEqual(reviewed.review.reviewer_id, "user_admin")
            self.assertEqual(reviewed.review.decision, MemoryReviewDecision.APPROVED)
            self.assertEqual(sink.events[-1].event_type, "memory_review")
            self.assertEqual(sink.events[-1].decision, "approved")
            self.assertEqual(sink.events[-1].metadata["memory_id"], "mem_candidate")

    def test_deprecation_preview_does_not_mutate_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter, store, _sink = self._adapter(tmpdir)
            store.upsert(self._plan_record("mem_active", MemoryStatus.ACTIVE, owner_id="ops-team"))

            preview = adapter.deprecation_preview(self._context(), owner_id="ops-team")

            self.assertEqual(preview["plan"]["records_to_deprecate"], 1)
            self.assertFalse(preview["plan"]["destructive_delete"])
            self.assertEqual(store.get("mem_active").status, MemoryStatus.ACTIVE)

    def test_deprecate_owner_requires_confirmation_and_marks_only_owner_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter, store, sink = self._adapter(tmpdir)
            store.upsert(self._plan_record("mem_active", MemoryStatus.ACTIVE, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_other", MemoryStatus.ACTIVE, owner_id="other-team"))

            with self.assertRaises(ValueError):
                adapter.deprecate_owner(
                    self._context(),
                    owner_id="ops-team",
                    confirm_owner_id="wrong-team",
                    decision_note="retire owner records",
                )

            deprecated = adapter.deprecate_owner(
                self._context(),
                owner_id="ops-team",
                confirm_owner_id="ops-team",
                decision_note="retire owner records",
            )

            self.assertEqual([record["memory_id"] for record in deprecated["records"]], ["mem_active"])
            self.assertEqual(store.get("mem_active").status, MemoryStatus.DEPRECATED)
            self.assertEqual(store.get("mem_active").review.reviewer_id, "user_admin")
            self.assertEqual(store.get("mem_other").status, MemoryStatus.ACTIVE)
            self.assertEqual(sink.events[-1].decision, "deprecated")
            self.assertFalse(sink.events[-1].metadata["destructive_delete"])

    def _plan_record(
        self,
        memory_id: str,
        status: MemoryStatus,
        *,
        owner_id: str = "default",
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            owner_id=owner_id,
            namespace="memory://oncall/plan-templates",
            memory_type=MemoryType.PLAN_TEMPLATE,
            content="CPUHigh diagnosis should check CPU metrics and recent rollout.",
            summary=f"{memory_id} CPUHigh metrics rollout",
            payload=PlanTemplatePayload(
                alert_type="CPUHigh",
                plan_steps=["Check CPU metrics", "Check recent rollout"],
                evidence_refs=[
                    {
                        "evidence_type": "session_candidate",
                        "session_id": "session-aiops-1",
                    }
                ],
            ),
            source="session-candidate, NOT reviewed active memory",
            evidence={
                "evidence_type": "session_candidate",
                "session_id": "session-aiops-1",
                "source_type": "aiops_diagnosis",
            },
            status=status,
        )


if __name__ == "__main__":
    unittest.main()
