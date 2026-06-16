import unittest

from evals.memory.run_memory_injection_eval import summarize_injection_results
from evals.memory.run_memory_retrieval_eval import build_memory_record, compute_ranking_metrics


class MemoryRetrievalEvalHelperTests(unittest.TestCase):
    def test_compute_ranking_metrics(self):
        results = [
            {
                "expected_memory_id": "mem_a",
                "returned_memory_ids": ["mem_a", "mem_b"],
            },
            {
                "expected_memory_id": "mem_c",
                "returned_memory_ids": ["mem_a", "mem_b", "mem_c"],
            },
            {
                "expected_memory_id": "mem_missing",
                "returned_memory_ids": ["mem_a"],
            },
        ]

        metrics = compute_ranking_metrics(results)

        self.assertEqual(metrics["total"], 3)
        self.assertAlmostEqual(metrics["hit_at_1"], 1 / 3)
        self.assertAlmostEqual(metrics["hit_at_3"], 2 / 3)
        self.assertAlmostEqual(metrics["mrr"], (1.0 + (1 / 3) + 0.0) / 3)

    def test_build_memory_record_uses_pre_seeded_memory(self):
        sample = {
            "id": "sample_001",
            "pre_seeded_memory": {
                "memory_id": "mem_alert_cpu_high",
                "memory_type": "alert_pattern",
                "namespace": "memory://oncall/alert-patterns",
                "content": "CPUHigh on service-a usually caused by memory leak in cache layer.",
                "payload": {
                    "alert_name": "CPUHigh",
                    "service": "service-a",
                    "severity": "critical",
                    "signal_keys": ["cpu_usage"],
                    "metric_patterns": ["cpu > 85%"],
                    "log_patterns": ["GC overhead"],
                    "root_cause": "memory leak in cache layer",
                    "fix": "restart service and check cache config",
                    "evidence_refs": [{"session_id": "sess_001"}],
                },
            },
        }

        record = build_memory_record(sample, source="unit_test_fixture")

        self.assertEqual(record.memory_id, "mem_alert_cpu_high")
        self.assertEqual(record.namespace, "memory://oncall/alert-patterns")
        self.assertEqual(record.memory_type, "alert_pattern")
        self.assertEqual(record.status, "active")
        self.assertEqual(record.source, "unit_test_fixture")


class MemoryInjectionEvalHelperTests(unittest.TestCase):
    def test_summarize_injection_results(self):
        results = [
            {"case_id": "off", "passed": True},
            {"case_id": "shadow", "passed": False},
            {"case_id": "active", "passed": True},
        ]

        summary = summarize_injection_results(results)

        self.assertEqual(summary, {"checks_total": 3, "checks_passed": 2})


if __name__ == "__main__":
    unittest.main()
