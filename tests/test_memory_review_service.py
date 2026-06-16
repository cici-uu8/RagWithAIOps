import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.cli.memory_operator import main as memory_operator_main
from app.models.memory import (
    CandidateSummaryPayload,
    MemoryRecord,
    MemoryReviewDecision,
    MemoryStatus,
    MemoryType,
    PlanTemplatePayload,
)
from app.services.memory_review_service import MemoryReviewService
from app.services.memory_store import MemoryStore


class MemoryReviewServiceTests(unittest.TestCase):
    def _store(self, tmpdir: str) -> MemoryStore:
        return MemoryStore(Path(tmpdir) / "memory.sqlite3")

    def test_review_queue_lists_only_candidate_and_conflict_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            store.upsert(self._plan_record("mem_active", MemoryStatus.ACTIVE))
            store.upsert(self._plan_record("mem_candidate", MemoryStatus.CANDIDATE))
            store.upsert(self._plan_record("mem_conflict", MemoryStatus.CONFLICT))
            store.upsert(self._plan_record("mem_deprecated", MemoryStatus.DEPRECATED))

            queue = service.list_review_queue()

            self.assertEqual(
                [record.memory_id for record in queue],
                ["mem_candidate", "mem_conflict"],
            )

    def test_approve_candidate_requires_reviewer_and_decision_note(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            store.upsert(self._plan_record("mem_plan_cpu", MemoryStatus.CANDIDATE))

            with self.assertRaises(ValueError):
                service.approve_candidate("mem_plan_cpu", reviewer_id="", decision_note="validated")
            with self.assertRaises(ValueError):
                service.approve_candidate("mem_plan_cpu", reviewer_id="ops-lead", decision_note=" ")

            self.assertEqual(store.get("mem_plan_cpu").status, MemoryStatus.CANDIDATE)

    def test_approve_plan_template_candidate_adds_review_audit_and_promotes_to_active(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            deadline = datetime.now() + timedelta(days=3)
            store.upsert(
                self._plan_record(
                    "mem_plan_cpu",
                    MemoryStatus.CANDIDATE,
                    candidate_review_deadline=deadline,
                )
            )

            approved = service.approve_candidate(
                "mem_plan_cpu",
                reviewer_id="ops-lead",
                decision_note="validated against local controlled baseline",
            )

            self.assertEqual(approved.status, MemoryStatus.ACTIVE)
            self.assertIsNone(approved.candidate_review_deadline)
            self.assertIsNotNone(approved.review)
            self.assertEqual(approved.review.decision, MemoryReviewDecision.APPROVED)
            self.assertEqual(approved.review.reviewer_id, "ops-lead")
            self.assertEqual(approved.review.previous_status, MemoryStatus.CANDIDATE)
            self.assertEqual(approved.review.decision_source, "operator-workflow")
            self.assertNotIn("raw_messages", approved.evidence)

            reloaded = store.get("mem_plan_cpu")
            self.assertEqual(reloaded.status, MemoryStatus.ACTIVE)
            self.assertEqual(reloaded.review.decision, MemoryReviewDecision.APPROVED)

    def test_candidate_summary_cannot_be_approved_as_active_memory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            store.upsert(self._candidate_summary_record("mem_rag_summary"))

            with self.assertRaises(ValueError):
                service.approve_candidate(
                    "mem_rag_summary",
                    reviewer_id="ops-lead",
                    decision_note="summary is not a reusable memory payload",
                )

            self.assertEqual(store.get("mem_rag_summary").status, MemoryStatus.CANDIDATE)

    def test_reject_candidate_deprecates_record_with_review_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            store.upsert(self._plan_record("mem_plan_cpu", MemoryStatus.CONFLICT))

            rejected = service.reject_candidate(
                "mem_plan_cpu",
                reviewer_id="ops-lead",
                decision_note="conflicts with fresher incident evidence",
            )

            self.assertEqual(rejected.status, MemoryStatus.DEPRECATED)
            self.assertEqual(rejected.review.decision, MemoryReviewDecision.REJECTED)
            self.assertEqual(rejected.review.previous_status, MemoryStatus.CONFLICT)
            self.assertIn("fresher incident", rejected.review.decision_note)

    def test_owner_deprecation_plan_lists_only_owner_non_deprecated_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            store.upsert(self._plan_record("mem_active", MemoryStatus.ACTIVE, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_candidate", MemoryStatus.CANDIDATE, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_conflict", MemoryStatus.CONFLICT, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_deprecated", MemoryStatus.DEPRECATED, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_other_owner", MemoryStatus.ACTIVE, owner_id="other-team"))

            plan = service.build_owner_deprecation_plan(owner_id="ops-team")

            self.assertEqual(plan["owner_id"], "ops-team")
            self.assertFalse(plan["destructive_delete"])
            self.assertEqual(plan["records_to_deprecate"], 3)
            self.assertEqual(
                [item["memory_id"] for item in plan["records"]],
                ["mem_active", "mem_candidate", "mem_conflict"],
            )

    def test_deprecate_owner_memories_preserves_records_with_review_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._store(tmpdir)
            service = MemoryReviewService(store=store)
            store.upsert(self._plan_record("mem_active", MemoryStatus.ACTIVE, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_candidate", MemoryStatus.CANDIDATE, owner_id="ops-team"))
            store.upsert(self._plan_record("mem_other_owner", MemoryStatus.ACTIVE, owner_id="other-team"))

            deprecated = service.deprecate_owner_memories(
                owner_id="ops-team",
                reviewer_id="runtime-owner",
                decision_note="Gate A.2 review failed: no validated reuse evidence",
            )

            self.assertEqual([record.memory_id for record in deprecated], ["mem_active", "mem_candidate"])
            self.assertEqual(store.get("mem_active").status, MemoryStatus.DEPRECATED)
            self.assertEqual(store.get("mem_candidate").status, MemoryStatus.DEPRECATED)
            self.assertEqual(store.get("mem_other_owner").status, MemoryStatus.ACTIVE)
            self.assertEqual(store.get("mem_active").review.decision, MemoryReviewDecision.DEPRECATED)
            self.assertEqual(store.get("mem_active").review.previous_status, MemoryStatus.ACTIVE)
            self.assertIn("Gate A.2 review failed", store.get("mem_active").review.decision_note)

    def test_cli_approve_uses_operator_cli_review_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            store = MemoryStore(store_path)
            store.upsert(self._plan_record("mem_plan_cpu", MemoryStatus.CANDIDATE))

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "approve",
                        "mem_plan_cpu",
                        "--reviewer-id",
                        "ops-lead",
                        "--note",
                        "operator reviewed controlled baseline",
                    ]
                )

            self.assertEqual(exit_code, 0)
            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(printed["memory_id"], "mem_plan_cpu")
            reloaded = MemoryStore(store_path).get("mem_plan_cpu")
            self.assertEqual(reloaded.status, MemoryStatus.ACTIVE)
            self.assertEqual(reloaded.review.decision_source, "operator-cli")

    def _plan_record(
        self,
        memory_id: str,
        status: MemoryStatus,
        *,
        candidate_review_deadline: datetime | None = None,
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
            candidate_review_deadline=candidate_review_deadline,
        )

    def _candidate_summary_record(self, memory_id: str) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            owner_id="default",
            namespace="memory://candidate/session",
            memory_type=MemoryType.CANDIDATE_SUMMARY,
            content="CPUHigh chat summary only.",
            summary="CPUHigh chat summary only",
            payload=CandidateSummaryPayload(
                candidate_kind="rag_chat_summary",
                summary="CPUHigh chat summary only",
                evidence_refs=[
                    {
                        "evidence_type": "session_message_ref",
                        "session_id": "session-rag-1",
                    }
                ],
            ),
            source="session-candidate, NOT reviewed active memory",
            evidence={
                "evidence_type": "session_candidate",
                "session_id": "session-rag-1",
                "source_type": "rag_chat",
            },
            status=MemoryStatus.CANDIDATE,
        )


if __name__ == "__main__":
    unittest.main()
