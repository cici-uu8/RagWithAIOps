import unittest

from evals.memory.run_p6_memory_eval import P6MemoryEvaluator


class P6MemoryEvalJudgeTests(unittest.TestCase):
    def setUp(self):
        self.evaluator = P6MemoryEvaluator(
            samples_path="evals/memory/p6_samples.jsonl",
            store_path="./uploads/_metadata/oncall_memory_p6_eval.sqlite3",
            isolate_samples=False,
        )

    def test_repeated_alert_judge_accepts_chinese_root_cause_and_plan_checks(self):
        sample = {
            "id": "p6_repeated_001",
            "expected_root_cause_keywords": ["memory leak", "cache", "heap"],
            "expected_fresh_checks": [
                "query_metrics",
                "query_logs",
                "check_recent_deploy",
            ],
        }
        guidance_record = {
            "final_response": "结合指标判断，根因很可能是缓存层内存泄漏。",
            "key_events": [
                {
                    "type": "plan",
                    "plan": [
                        "调用 query_cpu_metrics 和 query_memory_metrics 检查 service-a 指标。",
                        "使用 search_topic_by_service_name 和 search_log 查询应用日志。",
                        "检查最近部署记录，排除新版本引入的问题。",
                    ],
                }
            ],
        }

        result = self.evaluator.judge_repeated_alert(sample, "", guidance_record)

        self.assertTrue(result["passed"])
        self.assertTrue(result["guidance_mentions_root_cause"])
        self.assertEqual(result["guidance_check_rate"], 1.0)

    def test_plan_reuse_judge_accepts_expected_steps_in_plan_event(self):
        sample = {
            "id": "p6_plan_001",
            "expected_plan_steps": [
                "check network metrics",
                "check firewall rules",
                "check DNS resolution",
                "check upstream service health",
            ],
        }
        guidance_record = {
            "final_response": "最终报告只总结调查受阻。",
            "key_events": [
                {
                    "type": "plan",
                    "plan": [
                        "检查网络指标，包括 packet loss 和 latency。",
                        "检查 firewall rules 和 security groups。",
                        "检查 DNS resolution 是否正常。",
                        "检查 upstream service health。",
                    ],
                }
            ],
        }

        result = self.evaluator.judge_plan_reuse(sample, "", guidance_record)

        self.assertTrue(result["passed"])
        self.assertEqual(result["coverage"], 1.0)

    def test_stale_override_judge_accepts_chinese_new_root_cause(self):
        sample = {
            "id": "p6_stale_003",
            "expected_new_root_cause_keywords": ["large dataset", "memory", "feature"],
            "stale_memory": {
                "root_cause_keywords": ["connection pool", "leak", "database"],
            },
        }
        guidance_record = {
            "final_response": "当前不是旧的连接池问题，而是新功能加载大数据集导致内存升高。",
            "key_events": [],
        }

        result = self.evaluator.judge_stale_override(sample, "", guidance_record)

        self.assertTrue(result["passed"])
        self.assertTrue(result["guidance_mentions_new_root_cause"])
        self.assertTrue(result["guidance_not_using_stale"])


if __name__ == "__main__":
    unittest.main()
