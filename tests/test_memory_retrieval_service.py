import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.memory import AlertPatternPayload
from app.models.memory import MemoryRecord, MemoryStatus
from app.services.memory_retrieval_service import MemoryRetrievalQuery, MemoryRetrievalService
from app.services.memory_store import MemoryStore


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memory_synthetic" / "p1_memory_records.json"
P2_LEXICAL_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "memory_synthetic" / "p2_lexical_recall_cases.json"
)


class MemoryRetrievalServiceTests(unittest.TestCase):
    def _build_store(self, tmpdir: str) -> MemoryStore:
        store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
        for payload in json.loads(FIXTURE_PATH.read_text(encoding="utf-8")):
            store.upsert(MemoryRecord.model_validate(payload))

        deprecated = MemoryRecord.model_validate(
            {
                **json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0],
                "memory_id": "mem_alert_deprecated",
                "status": "deprecated",
                "summary": "Deprecated memory usage alert should never be returned",
            }
        )
        store.upsert(deprecated)
        return store

    def test_retrieves_active_alert_pattern_by_synonym_query(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = MemoryRetrievalService(self._build_store(tmpdir))

            response = service.retrieve(
                MemoryRetrievalQuery(
                    query="OOM 之后怎么排查",
                    namespaces=["memory://oncall/alert-patterns"],
                    memory_types=["alert_pattern"],
                    top_k=3,
                )
            )

            self.assertEqual([result.memory_id for result in response.memory_results], ["mem_alert_high_memory"])
            self.assertEqual(response.memory_results[0].memory_type, "alert_pattern")
            self.assertEqual(response.memory_results[0].status, MemoryStatus.ACTIVE)
            self.assertGreater(response.memory_results[0].score, 0)
            self.assertIn("oom", response.memory_results[0].matched_terms)
            self.assertEqual(response.trace["candidate_count"], 1)

    def test_ignores_candidate_and_deprecated_records_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = MemoryRetrievalService(self._build_store(tmpdir))

            response = service.retrieve(
                MemoryRetrievalQuery(
                    query="SlowResponse plan metrics logs dependency rollout",
                    namespaces=["memory://oncall/plan-templates"],
                    memory_types=["plan_template"],
                    top_k=3,
                )
            )

            self.assertEqual(response.memory_results, [])
            self.assertEqual(response.empty_message, "No active memory matched the query.")
            self.assertEqual(response.trace["candidate_count"], 0)

    def test_owner_namespace_and_type_filters_are_applied_before_ranking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = self._build_store(tmpdir)
            other_owner = MemoryRecord.model_validate(
                {
                    **json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0],
                    "memory_id": "mem_alert_other_owner",
                    "owner_id": "team-b",
                    "summary": "OOM memory usage other owner",
                }
            )
            store.upsert(other_owner)
            service = MemoryRetrievalService(store)

            response = service.retrieve(
                MemoryRetrievalQuery(
                    query="OOM memory usage",
                    owner_id="team-b",
                    namespaces=["memory://oncall/alert-patterns"],
                    memory_types=["alert_pattern"],
                    top_k=3,
                )
            )

            self.assertEqual([result.memory_id for result in response.memory_results], ["mem_alert_other_owner"])
            self.assertEqual(response.trace["candidate_count"], 1)

    def test_returns_independent_memory_results_not_rag_citations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            service = MemoryRetrievalService(self._build_store(tmpdir))

            response = service.retrieve(
                MemoryRetrievalQuery(
                    query="中文 简洁 证据边界",
                    namespaces=["memory://runtime/user-preferences"],
                    memory_types=["preference"],
                    top_k=1,
                )
            )

            result_payload = response.memory_results[0].model_dump()
            self.assertIn("evidence_refs", result_payload)
            self.assertNotIn("source_ref", result_payload)
            self.assertNotIn("citation_text", result_payload)
            self.assertEqual(response.namespaces, ["memory://runtime/user-preferences"])
            self.assertEqual(response.memory_types, ["preference"])

    def test_p2_lexical_recall_gate_meets_frozen_threshold(self):
        fixture = json.loads(P2_LEXICAL_FIXTURE_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmpdir:
            store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
            for payload in fixture["records"]:
                store.upsert(MemoryRecord.model_validate(payload))
            service = MemoryRetrievalService(store)

            passed = 0
            for case in fixture["queries"]:
                response = service.retrieve(
                    MemoryRetrievalQuery(
                        query=case["query"],
                        namespaces=["memory://oncall/alert-patterns"],
                        memory_types=["alert_pattern"],
                        top_k=1,
                    )
                )
                actual_memory_id = response.memory_results[0].memory_id if response.memory_results else None
                if actual_memory_id == case["expected_memory_id"]:
                    passed += 1

            self.assertEqual(len(fixture["queries"]), fixture["threshold"]["total_queries"])
            self.assertGreaterEqual(passed, fixture["threshold"]["min_expected_hits"])

    def test_uses_injected_scorer_for_ranking(self):
        class FixedMemoryScorer:
            retrieval_mode = "fixed-test"

            def score(self, record, query):
                if record.memory_id == "mem_alert_high_memory":
                    return 7.0, ["fixed-match"]
                return 0.0, []

        with tempfile.TemporaryDirectory() as tmpdir:
            service = MemoryRetrievalService(
                self._build_store(tmpdir),
                scorer=FixedMemoryScorer(),
            )

            response = service.retrieve(
                MemoryRetrievalQuery(
                    query="query text ignored by fixed scorer",
                    namespaces=["memory://oncall/alert-patterns"],
                    memory_types=["alert_pattern"],
                    top_k=3,
                )
            )

            self.assertEqual([result.memory_id for result in response.memory_results], ["mem_alert_high_memory"])
            self.assertEqual(response.memory_results[0].score, 7.0)
            self.assertEqual(response.memory_results[0].matched_terms, ["fixed-match"])
            self.assertEqual(response.trace["retrieval_mode"], "fixed-test")

    def _stale_record(
        self,
        *,
        memory_id: str,
        updated_at: datetime,
        summary: str = "service-a CPUHigh cache memory leak",
    ) -> MemoryRecord:
        return MemoryRecord(
            memory_id=memory_id,
            schema_version=1,
            owner_id="default",
            namespace="memory://oncall/alert-patterns",
            memory_type="alert_pattern",
            content=summary,
            summary=summary,
            payload=AlertPatternPayload(
                alert_name="CPUHigh",
                service="service-a",
                severity="critical",
                signal_keys=["cpu"],
                metric_patterns=[],
                log_patterns=[],
                root_cause="cache memory leak",
                fix="restart cache worker",
                evidence_refs=[{"source_type": "unit-test"}],
            ),
            source="unit-test",
            evidence={"source_type": "unit-test"},
            status="active",
            tags=["cpu", "cache"],
            created_at=updated_at,
            updated_at=updated_at,
        )

    def test_stale_cue_penalizes_old_memory_without_deleting_it(self):
        now = datetime.now(timezone.utc)
        old_record = self._stale_record(
            memory_id="mem_old_cpu_high",
            updated_at=now - timedelta(days=14),
        )
        new_record = self._stale_record(
            memory_id="mem_new_cpu_high",
            updated_at=now - timedelta(days=1),
        )

        class FakeStore:
            def list_memories(self, **kwargs):
                return [old_record, new_record]

            def record_access(self, memory_id):
                return None

        class EqualScorer:
            retrieval_mode = "equal-test"

            def score(self, record, query):
                return 2.0, ["service-a", "CPUHigh"]

        service = MemoryRetrievalService(
            FakeStore(),
            scorer=EqualScorer(),
            stale_age_days=7,
            stale_penalty=0.5,
        )

        response = service.retrieve(
            MemoryRetrievalQuery(
                query="service-a CPUHigh fixed last week but alert triggered again",
                top_k=2,
            )
        )

        self.assertEqual(
            [result.memory_id for result in response.memory_results],
            ["mem_new_cpu_high", "mem_old_cpu_high"],
        )
        self.assertEqual(response.memory_results[0].score, 2.0)
        self.assertEqual(response.memory_results[1].score, 1.0)
        self.assertEqual(response.trace["stale_policy"]["cue_detected"], True)
        self.assertIn("fixed last week", response.trace["stale_policy"]["matched_cues"])
        self.assertEqual(response.trace["stale_policy"]["penalized_memory_ids"], ["mem_old_cpu_high"])
        self.assertEqual(
            response.trace["stale_policy"]["score_adjustments"][0]["memory_id"],
            "mem_old_cpu_high",
        )

    def test_negative_stale_cue_filter_prevents_false_positive_penalty(self):
        now = datetime.now(timezone.utc)
        old_record = self._stale_record(
            memory_id="mem_old_cpu_high",
            updated_at=now - timedelta(days=14),
        )
        new_record = self._stale_record(
            memory_id="mem_new_cpu_high",
            updated_at=now - timedelta(days=1),
        )

        class FakeStore:
            def list_memories(self, **kwargs):
                return [old_record, new_record]

            def record_access(self, memory_id):
                return None

        class EqualScorer:
            retrieval_mode = "equal-test"

            def score(self, record, query):
                return 2.0, ["service-a", "CPUHigh"]

        service = MemoryRetrievalService(
            FakeStore(),
            scorer=EqualScorer(),
            stale_age_days=7,
            stale_penalty=0.5,
        )

        response = service.retrieve(
            MemoryRetrievalQuery(
                query="最近有没有类似案例 service-a CPUHigh 最近变更",
                top_k=2,
            )
        )

        self.assertEqual(
            [result.memory_id for result in response.memory_results],
            ["mem_old_cpu_high", "mem_new_cpu_high"],
        )
        self.assertEqual([result.score for result in response.memory_results], [2.0, 2.0])
        self.assertEqual(response.trace["stale_policy"]["cue_detected"], False)
        self.assertIn("最近变更", response.trace["stale_policy"]["matched_cues"])
        self.assertIn("最近有没有类似案例", response.trace["stale_policy"]["negative_cues"])
        self.assertEqual(response.trace["stale_policy"]["penalized_memory_ids"], [])

    def test_p6_stale_override_state_change_cues_are_detected(self):
        now = datetime.now(timezone.utc)
        old_record = self._stale_record(
            memory_id="mem_old_cpu_high",
            updated_at=now - timedelta(days=14),
        )
        new_record = self._stale_record(
            memory_id="mem_new_cpu_high",
            updated_at=now - timedelta(days=1),
        )

        class FakeStore:
            def list_memories(self, **kwargs):
                return [old_record, new_record]

            def record_access(self, memory_id):
                return None

        class EqualScorer:
            retrieval_mode = "equal-test"

            def score(self, record, query):
                return 2.0, ["service-a", "CPUHigh"]

        service = MemoryRetrievalService(
            FakeStore(),
            scorer=EqualScorer(),
            stale_age_days=7,
            stale_penalty=0.5,
        )

        queries = [
            "service-a CPUHigh alert, but recent deploy changed architecture",
            "DiskHigh alert on service-b, but log rotation was fixed last week",
            "HighMemoryUsage alert on service-c, but connection pool config was updated",
            "SlowResponse alert on service-d, but database index was added yesterday",
        ]

        for query in queries:
            with self.subTest(query=query):
                response = service.retrieve(MemoryRetrievalQuery(query=query, top_k=2))

                self.assertTrue(response.trace["stale_policy"]["cue_detected"])
                self.assertEqual(
                    response.trace["stale_policy"]["penalized_memory_ids"],
                    ["mem_old_cpu_high"],
                )

    def test_mixed_timezone_updated_at_sorting_does_not_break_retrieval(self):
        aware_record = self._stale_record(
            memory_id="mem_aware_cpu_high",
            updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        naive_record = self._stale_record(
            memory_id="mem_naive_cpu_high",
            updated_at=datetime(2026, 5, 2),
        )

        class FakeStore:
            def list_memories(self, **kwargs):
                return [naive_record, aware_record]

            def record_access(self, memory_id):
                return None

        class EqualScorer:
            retrieval_mode = "equal-test"

            def score(self, record, query):
                return 2.0, ["service-a", "CPUHigh"]

        service = MemoryRetrievalService(
            FakeStore(),
            scorer=EqualScorer(),
        )

        response = service.retrieve(
            MemoryRetrievalQuery(
                query="service-a CPUHigh alert triggered again",
                top_k=2,
            )
        )

        self.assertEqual(
            [result.memory_id for result in response.memory_results],
            ["mem_aware_cpu_high", "mem_naive_cpu_high"],
        )


if __name__ == "__main__":
    unittest.main()
