import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.cli.memory_operator import main as memory_operator_main
from app.models.memory import MemoryRecord, MemoryReviewDecision, PlanTemplatePayload
from app.models.memory import MemoryStatus, MemoryType
from app.services.memory_store import MemoryStore


class MemoryOperatorCliTests(unittest.TestCase):
    def test_cli_status_reports_pre_launch_review_counter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "status",
                        "--owner-id",
                        "ops-team",
                    ]
                )

            self.assertEqual(exit_code, 0)
            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(printed["owner_id"], "ops-team")
            self.assertEqual(printed["gate_a1_real_oncall_evidence"], "not_passed")
            self.assertEqual(printed["gate_a2_pre_launch_product_bet"], "passed")
            self.assertEqual(printed["diagnosis_use_count"], 0)
            self.assertEqual(printed["diagnosis_review_threshold"], 20)
            self.assertEqual(printed["diagnoses_remaining_to_review"], 20)
            self.assertFalse(printed["review_due_by_diagnosis_count"])
            self.assertEqual(printed["p5_prompt_integration"], "blocked_default_off")

    def test_cli_records_aiops_diagnosis_once_per_diagnosis_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "record-aiops-diagnosis",
                        "diagnosis-001",
                        "--owner-id",
                        "ops-team",
                        "--note",
                        "operator verified local AIOps diagnosis run",
                    ]
                )

            self.assertEqual(exit_code, 0)
            first = json.loads(print_mock.call_args.args[0])
            self.assertTrue(first["recorded"])
            self.assertEqual(first["status"]["diagnosis_use_count"], 1)
            self.assertEqual(first["status"]["diagnoses_remaining_to_review"], 19)

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "record-aiops-diagnosis",
                        "diagnosis-001",
                        "--owner-id",
                        "ops-team",
                        "--note",
                        "duplicate operator retry should not inflate counter",
                    ]
                )

            self.assertEqual(exit_code, 0)
            second = json.loads(print_mock.call_args.args[0])
            self.assertFalse(second["recorded"])
            self.assertEqual(second["status"]["diagnosis_use_count"], 1)

    def test_cli_preview_deprecate_owner_memories_outputs_auditable_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            store = MemoryStore(store_path)
            store.upsert(_plan_record("mem_active", MemoryStatus.ACTIVE, owner_id="ops-team"))
            store.upsert(_plan_record("mem_candidate", MemoryStatus.CANDIDATE, owner_id="ops-team"))
            store.upsert(_plan_record("mem_other_owner", MemoryStatus.ACTIVE, owner_id="other-team"))

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "preview-deprecate-owner-memories",
                        "--owner-id",
                        "ops-team",
                    ]
                )

            self.assertEqual(exit_code, 0)
            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(printed["owner_id"], "ops-team")
            self.assertFalse(printed["destructive_delete"])
            self.assertEqual(printed["records_to_deprecate"], 2)
            self.assertEqual(
                [record["memory_id"] for record in printed["records"]],
                ["mem_active", "mem_candidate"],
            )
            self.assertEqual(MemoryStore(store_path).get("mem_active").status, MemoryStatus.ACTIVE)

    def test_cli_deprecate_owner_memories_requires_confirm_owner_and_audits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            store = MemoryStore(store_path)
            store.upsert(_plan_record("mem_active", MemoryStatus.ACTIVE, owner_id="ops-team"))
            store.upsert(_plan_record("mem_other_owner", MemoryStatus.ACTIVE, owner_id="other-team"))

            with self.assertRaises(SystemExit) as exit_context:
                memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "deprecate-owner-memories",
                        "--owner-id",
                        "ops-team",
                        "--confirm-owner-id",
                        "wrong-team",
                        "--reviewer-id",
                        "runtime-owner",
                        "--note",
                        "Gate A.2 review failed",
                    ]
                )
            self.assertEqual(exit_context.exception.code, 2)
            self.assertEqual(MemoryStore(store_path).get("mem_active").status, MemoryStatus.ACTIVE)

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "deprecate-owner-memories",
                        "--owner-id",
                        "ops-team",
                        "--confirm-owner-id",
                        "ops-team",
                        "--reviewer-id",
                        "runtime-owner",
                        "--note",
                        "Gate A.2 review failed",
                    ]
                )

            self.assertEqual(exit_code, 0)
            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(printed["deprecated_count"], 1)
            reloaded = MemoryStore(store_path)
            self.assertEqual(reloaded.get("mem_active").status, MemoryStatus.DEPRECATED)
            self.assertEqual(reloaded.get("mem_other_owner").status, MemoryStatus.ACTIVE)
            self.assertEqual(reloaded.get("mem_active").review.decision, MemoryReviewDecision.DEPRECATED)

    def test_cli_extracts_rag_session_candidate_from_history_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            store_path = tmp_path / "memory.sqlite3"
            history_path = tmp_path / "rag_history.json"
            history_path.write_text(
                json.dumps(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": "CPUHigh 第二次又从零开始了",
                                "message_index": 0,
                            },
                            {
                                "role": "assistant",
                                "content": "这次先看 CPU 指标和最近发布",
                                "message_index": 1,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "extract-rag-session",
                        "session-rag-1",
                        "--history-json",
                        str(history_path),
                    ]
                )

            self.assertEqual(exit_code, 0)
            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(printed["action"], "created")
            self.assertEqual(printed["source_type"], "rag_chat")
            self.assertEqual(printed["records"][0]["memory_type"], "candidate_summary")

            record = MemoryStore(store_path).get(printed["records"][0]["memory_id"])
            self.assertEqual(record.status, MemoryStatus.CANDIDATE)
            self.assertEqual(record.memory_type, MemoryType.CANDIDATE_SUMMARY)
            self.assertEqual(record.evidence["session_id"], "session-rag-1")
            self.assertEqual(record.evidence["source_type"], "rag_chat")
            self.assertNotIn("raw_messages", record.evidence)

    def test_cli_extracts_aiops_session_candidate_from_state_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            store_path = tmp_path / "memory.sqlite3"
            state_path = tmp_path / "aiops_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "input": "CPUHigh on checkout-api",
                        "plan": ["检查 CPU 利用率", "检查最近发布", "检查错误日志"],
                        "past_steps": [],
                        "response": "根因结论: 最近发布导致 CPU 飙高。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch("builtins.print") as print_mock:
                exit_code = memory_operator_main(
                    [
                        "--store-path",
                        str(store_path),
                        "extract-aiops-session",
                        "session-aiops-1",
                        "--state-json",
                        str(state_path),
                        "--owner-id",
                        "ops-team",
                    ]
                )

            self.assertEqual(exit_code, 0)
            printed = json.loads(print_mock.call_args.args[0])
            self.assertEqual(printed["action"], "created")
            self.assertEqual(printed["source_type"], "aiops_diagnosis")
            self.assertEqual(printed["records"][0]["memory_type"], "plan_template")

            record = MemoryStore(store_path).get(printed["records"][0]["memory_id"])
            self.assertEqual(record.owner_id, "ops-team")
            self.assertEqual(record.status, MemoryStatus.CANDIDATE)
            self.assertEqual(record.memory_type, MemoryType.PLAN_TEMPLATE)
            self.assertEqual(record.payload.alert_type, "CPUHigh on checkout-api")
            self.assertEqual(record.payload.plan_steps, ["检查 CPU 利用率", "检查最近发布", "检查错误日志"])
            self.assertNotIn("raw_memory_saver_history", record.evidence)


def _plan_record(memory_id: str, status: MemoryStatus, *, owner_id: str) -> MemoryRecord:
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
