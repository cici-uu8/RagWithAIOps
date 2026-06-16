import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.models.memory import AlertPatternPayload, MemoryRecord
from app.models.memory_mode import MemoryMode
from app.services.memory_guidance_provider import MemoryGuidanceProvider
from app.services.memory_store import MemoryStore
from app.services.memory_trace_service import MemoryTraceService


class MemoryGuidanceProviderTests(unittest.TestCase):
    def _seed_cpu_high_memory(self, store_path: Path) -> None:
        store = MemoryStore(store_path=store_path)
        store.upsert(
            MemoryRecord(
                memory_id="mem_alert_cpu_high",
                schema_version=1,
                owner_id="default",
                namespace="memory://oncall/alert-patterns",
                memory_type="alert_pattern",
                content=(
                    "CPUHigh on service-a usually caused by memory leak in cache layer. "
                    "Check heap usage, GC overhead, recent deploy, and cache eviction config."
                ),
                summary="CPUHigh service-a memory leak cache heap GC",
                payload=AlertPatternPayload(
                    alert_name="CPUHigh",
                    service="service-a",
                    severity="critical",
                    signal_keys=["cpu_usage", "heap_usage", "gc_time"],
                    metric_patterns=["cpu > 85%", "heap > 80%"],
                    log_patterns=["OutOfMemoryError", "GC overhead"],
                    root_cause="memory leak in cache layer",
                    fix="restart service and check cache config",
                    evidence_refs=[{"session_id": "test_session", "diagnosis_id": "test_diag"}],
                ),
                status="active",
                source="unit-test-fixture",
                evidence={"source": "unit-test-fixture"},
                tags=["cpu", "cache", "heap"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )

    def _provider(self, trace_dir: Path) -> MemoryGuidanceProvider:
        return MemoryGuidanceProvider(trace_service=MemoryTraceService(trace_dir=str(trace_dir)))

    def test_provider_off_returns_empty_without_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = self._provider(Path(tmpdir) / "traces")

            result = provider.build({"input": "CPUHigh", "memory_mode": "off"})

            self.assertEqual(result.guidance_text, "")
            self.assertIsNone(result.observation)
            self.assertEqual(result.mode, MemoryMode.OFF)

    def test_provider_shadow_with_match_traces_without_guidance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            self._seed_cpu_high_memory(store_path)
            provider = self._provider(Path(tmpdir) / "traces")

            result = provider.build(
                {
                    "input": "service-a CPUHigh alert triggered again",
                    "memory_mode": "shadow",
                    "memory_owner_id": "default",
                    "memory_store_path": str(store_path),
                }
            )

            self.assertEqual(result.guidance_text, "")
            self.assertEqual(result.mode, MemoryMode.SHADOW)
            self.assertIsInstance(result.observation, dict)
            self.assertEqual(result.observation["memory_ids"], ["mem_alert_cpu_high"])

    def test_provider_shadow_without_match_returns_no_observation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            self._seed_cpu_high_memory(store_path)
            provider = self._provider(Path(tmpdir) / "traces")

            result = provider.build(
                {
                    "input": "KafkaLag partition backlog consumer group",
                    "memory_mode": "shadow",
                    "memory_owner_id": "default",
                    "memory_store_path": str(store_path),
                }
            )

            self.assertEqual(result.guidance_text, "")
            self.assertEqual(result.mode, MemoryMode.SHADOW)
            self.assertIsNone(result.observation)

    def test_provider_active_returns_guidance_when_memory_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "memory.sqlite3"
            self._seed_cpu_high_memory(store_path)
            provider = self._provider(Path(tmpdir) / "traces")

            result = provider.build(
                {
                    "input": "service-a CPUHigh alert triggered again",
                    "memory_mode": "active",
                    "memory_owner_id": "default",
                    "memory_store_path": str(store_path),
                }
            )

            self.assertEqual(result.mode, MemoryMode.ACTIVE)
            self.assertNotEqual(result.guidance_text, "")
            self.assertIn("memory leak in cache layer", result.guidance_text)
            self.assertIsInstance(result.observation, dict)
            self.assertEqual(result.observation["memory_ids"], ["mem_alert_cpu_high"])


if __name__ == "__main__":
    unittest.main()
