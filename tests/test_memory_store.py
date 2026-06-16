import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from app.models.memory import (
    AlertPatternPayload,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    PlanTemplatePayload,
    PreferencePayload,
)
from app.services.memory_store import MemoryStore


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memory_synthetic" / "p1_memory_records.json"


class MemoryStoreTests(unittest.TestCase):
    def _load_fixture_records(self) -> list[MemoryRecord]:
        payloads = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        return [MemoryRecord.model_validate(payload) for payload in payloads]

    def test_persists_typed_memory_records_in_sqlite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
            records = self._load_fixture_records()

            for record in records:
                store.upsert(record)

            reloaded = MemoryStore(Path(tmpdir) / "memory.sqlite3")
            alert = reloaded.get("mem_alert_high_memory")
            plan = reloaded.get("mem_plan_slow_response")
            preference = reloaded.get("mem_preference_report_style")

            self.assertIsNotNone(alert)
            self.assertIsInstance(alert.payload, AlertPatternPayload)
            self.assertEqual(alert.payload.alert_name, "HighMemoryUsage")
            self.assertEqual(alert.owner_id, "default")
            self.assertEqual(alert.schema_version, 1)

            self.assertIsNotNone(plan)
            self.assertIsInstance(plan.payload, PlanTemplatePayload)
            self.assertEqual(plan.payload.alert_type, "SlowResponse")

            self.assertIsNotNone(preference)
            self.assertIsInstance(preference.payload, PreferencePayload)
            self.assertEqual(preference.payload.preference_scope, "oncall_diagnosis_report")

    def test_filters_by_namespace_type_and_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
            for record in self._load_fixture_records():
                store.upsert(record)

            active_alerts = store.list_memories(
                namespace="memory://oncall/alert-patterns",
                memory_type=MemoryType.ALERT_PATTERN,
                status=MemoryStatus.ACTIVE,
            )
            candidate_plans = store.list_memories(
                namespace="memory://oncall/plan-templates",
                memory_type=MemoryType.PLAN_TEMPLATE,
                status=MemoryStatus.CANDIDATE,
            )

            self.assertEqual([record.memory_id for record in active_alerts], ["mem_alert_high_memory"])
            self.assertEqual([record.memory_id for record in candidate_plans], ["mem_plan_slow_response"])

    def test_updates_status_and_access_lifecycle_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
            record = self._load_fixture_records()[1]
            review_deadline = datetime.now() + timedelta(days=7)
            record = record.model_copy(update={"candidate_review_deadline": review_deadline})
            store.upsert(record)

            promoted = store.update_status("mem_plan_slow_response", MemoryStatus.ACTIVE)
            touched = store.record_access("mem_plan_slow_response")

            self.assertIsNotNone(promoted)
            self.assertEqual(promoted.status, MemoryStatus.ACTIVE)
            self.assertIsNotNone(touched.last_accessed_at)
            self.assertEqual(touched.access_count, 1)

            reloaded = MemoryStore(Path(tmpdir) / "memory.sqlite3").get("mem_plan_slow_response")
            self.assertEqual(reloaded.status, MemoryStatus.ACTIVE)
            self.assertEqual(reloaded.access_count, 1)
            self.assertIsNotNone(reloaded.candidate_review_deadline)

    def test_record_access_preserves_content_updated_at(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
            stale_updated_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
            record = self._load_fixture_records()[0].model_copy(
                update={
                    "created_at": stale_updated_at,
                    "updated_at": stale_updated_at,
                }
            )
            store.upsert(record, preserve_timestamps=True)

            touched = store.record_access(record.memory_id)

            self.assertIsNotNone(touched)
            self.assertEqual(touched.access_count, 1)
            self.assertIsNotNone(touched.last_accessed_at)
            self.assertEqual(touched.updated_at, stale_updated_at)

            reloaded = MemoryStore(Path(tmpdir) / "memory.sqlite3").get(record.memory_id)
            self.assertEqual(reloaded.updated_at, stale_updated_at)
            self.assertEqual(reloaded.access_count, 1)

    def test_rejects_bare_payload_dict_and_mismatched_payload_type(self):
        base = self._load_fixture_records()[0].model_dump(mode="json")

        bare_payload = {**base, "payload": {"anything": "raw"}}
        with self.assertRaises(ValidationError):
            MemoryRecord.model_validate(bare_payload)

        wrong_payload = {
            **base,
            "memory_type": "plan_template",
            "payload": base["payload"],
        }
        with self.assertRaises(ValidationError):
            MemoryRecord.model_validate(wrong_payload)

    def test_rejects_empty_evidence_and_raw_memory_saver_history(self):
        base = self._load_fixture_records()[0].model_dump(mode="json")

        with self.assertRaises(ValidationError):
            MemoryRecord.model_validate({**base, "evidence": {}})

        with self.assertRaises(ValidationError):
            MemoryRecord.model_validate(
                {
                    **base,
                    "evidence": {
                        "evidence_type": "synthetic_design_fixture",
                        "raw_messages": ["human", "assistant"],
                    },
                }
            )

    def test_validation_policy_status_counts_unique_aiops_diagnoses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            store = MemoryStore(store_path)

            for index in range(20):
                result = store.record_aiops_diagnosis(
                    f"diagnosis-{index:03d}",
                    owner_id="ops-team",
                    note="local operator-counted diagnosis",
                )
                self.assertTrue(result["recorded"])

            duplicate = store.record_aiops_diagnosis(
                "diagnosis-000",
                owner_id="ops-team",
                note="duplicate should not inflate count",
            )
            self.assertFalse(duplicate["recorded"])

            reloaded = MemoryStore(store_path).get_validation_policy_status(owner_id="ops-team")
            self.assertEqual(reloaded["diagnosis_use_count"], 20)
            self.assertEqual(reloaded["diagnoses_remaining_to_review"], 0)
            self.assertTrue(reloaded["review_due_by_diagnosis_count"])


if __name__ == "__main__":
    unittest.main()
