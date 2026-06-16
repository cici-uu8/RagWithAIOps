import asyncio
import json
import os
import tempfile
import time
import unittest
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agent import mcp_client
from app.agent.aiops.executor import _extract_tool_messages, executor as aiops_executor
from app.agent.aiops.replanner import _missing_required_tools, _required_tool_steps
from app.agent.aiops.utils import (
    await_with_optional_timeout,
    invoke_structured_with_fallback,
    invoke_structured_with_retry,
)
from app.enterprise.aiops.tool_catalog import AIOpsToolCatalogResult
from app.services.aiops_service import AIOpsService
from app.services.memory_store import MemoryStore
from evals.memory.run_p6_memory_eval import P6MemoryEvaluator
from mcp_servers.cls_server import search_log


class LocalMCPProxyBypassTests(unittest.TestCase):
    def test_local_streamable_http_servers_get_no_proxy_http_client(self):
        servers = {
            "cls": {
                "transport": "streamable-http",
                "url": "http://localhost:8003/mcp",
            },
            "remote": {
                "transport": "streamable-http",
                "url": "https://example.com/mcp",
            },
        }

        normalized = mcp_client._with_localhost_proxy_bypass(servers)

        self.assertIn("httpx_client_factory", normalized["cls"])
        self.assertNotIn("httpx_client_factory", normalized["remote"])
        self.assertNotIn("httpx_client_factory", servers["cls"])

        client = normalized["cls"]["httpx_client_factory"]()
        try:
            self.assertFalse(client._trust_env)
        finally:
            asyncio.run(client.aclose())


class P6MemoryEvalInfraTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if hasattr(mcp_client, "_clear_mcp_tools_cache"):
            mcp_client._clear_mcp_tools_cache()
        if hasattr(mcp_client, "_reset_mcp_tools_metrics"):
            mcp_client._reset_mcp_tools_metrics()

    def tearDown(self):
        if hasattr(mcp_client, "_clear_mcp_tools_cache"):
            mcp_client._clear_mcp_tools_cache()
        if hasattr(mcp_client, "_reset_mcp_tools_metrics"):
            mcp_client._reset_mcp_tools_metrics()

    def _evaluator(self) -> P6MemoryEvaluator:
        return P6MemoryEvaluator(
            samples_path="evals/memory/p6_samples.jsonl",
            store_path="./uploads/_metadata/oncall_memory_p6_eval.sqlite3",
            isolate_samples=False,
        )

    def test_replanner_required_tool_guard_detects_missing_tools(self):
        missing = _missing_required_tools(
            ["query_active_alerts", "search_service_logs"],
            [
                (
                    "调用 query_active_alerts 查询 data-sync-service 活跃告警",
                    "query_active_alerts returned DBSlowQuery",
                )
            ],
        )

        self.assertEqual(missing, ["search_service_logs"])

    def test_replanner_required_tool_guard_builds_missing_tool_steps(self):
        steps = _required_tool_steps(
            ["search_service_logs", "query_metric_series"],
            service_name="data-sync-service",
            scenario="DBSlowQuery",
        )

        self.assertEqual(len(steps), 2)
        self.assertIn("search_service_logs", steps[0])
        self.assertIn("data-sync-service", steps[0])
        self.assertIn("DBSlowQuery", steps[0])

    def test_internal_infra_event_marks_sample_as_error(self):
        evaluator = self._evaluator()
        event = {
            "type": "plan",
            "stage": "plan_created",
            "infra_error": True,
            "infra_error_stage": "planner",
            "infra_error_message": "get_tools failed",
            "plan": ["收集相关信息"],
        }

        self.assertTrue(evaluator._event_has_infra_failure(event))

        record = evaluator._build_response_record(
            query="service-a CPUHigh alert triggered again",
            response_text="完整最终报告",
            events=[event],
            session_id="p6_guidance_case",
            has_error=False,
        )

        self.assertTrue(record["has_error"])
        self.assertEqual(record["response"], "完整最终报告")
        self.assertEqual(record["response_length"], len("完整最终报告"))
        self.assertEqual(record["events"][0]["infra_error_stage"], "planner")
        self.assertEqual(record["error_stage"], "planner")
        self.assertEqual(record["error_message"], "get_tools failed")

    def test_pre_seed_memory_preserves_fixture_timestamps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store_path = Path(tmpdir) / "p6_memory.sqlite3"
            evaluator = P6MemoryEvaluator(
                samples_path="evals/memory/p6_samples.jsonl",
                store_path=str(store_path),
                isolate_samples=False,
            )
            evaluator.samples = [
                {
                    "id": "p6_stale_timestamp",
                    "category": "stale_override",
                    "query": "DiskHigh alert, but log rotation was fixed last week",
                    "pre_seeded_memory": {
                        "memory_id": "mem_alert_disk_high_stale",
                        "memory_type": "alert_pattern",
                        "namespace": "memory://oncall/alert-patterns",
                        "content": "DiskHigh previously caused by log rotation failure.",
                        "created_at": "2026-05-01T00:00:00+00:00",
                        "updated_at": "2026-05-01T00:00:00+00:00",
                        "payload": {
                            "alert_name": "DiskHigh",
                            "service": "service-b",
                            "severity": "warning",
                            "signal_keys": ["disk_usage"],
                            "metric_patterns": ["disk > 90%"],
                            "log_patterns": ["log rotation failure"],
                            "root_cause": "log rotation failure",
                            "fix": "fix logrotate",
                            "evidence_refs": [{"session_id": "sess_stale"}],
                        },
                    },
                }
            ]

            evaluator.pre_seed_memory()

            record = MemoryStore(str(store_path)).get("mem_alert_disk_high_stale")
            self.assertIsNotNone(record)
            self.assertEqual(record.updated_at.isoformat(), "2026-05-01T00:00:00+00:00")
            self.assertEqual(record.created_at.tzinfo, UTC)

    def test_response_record_exposes_primary_infra_failure_at_top_level(self):
        evaluator = self._evaluator()
        event = {
            "type": "error",
            "stage": "sample_timeout",
            "message": "Sample timed out after 120s",
            "infra_error": True,
            "infra_error_stage": "sample_timeout",
            "infra_error_message": "sample timed out after 120s",
            "infra_error_traceback": "Sample timed out at eval guard.\nsession_id=case-1",
            "last_events_before_timeout": [
                {"type": "plan", "stage": "plan_created", "plan": ["step"]}
            ],
        }

        record = evaluator._build_response_record(
            query="HighMemoryUsage alert on service-c",
            response_text="",
            events=[event],
            session_id="case-1",
            has_error=False,
            sample_id="p6_repeated_003",
            duration_seconds=120.5,
        )

        self.assertEqual(record["sample_id"], "p6_repeated_003")
        self.assertTrue(record["has_error"])
        self.assertEqual(record["duration_seconds"], 120.5)
        self.assertEqual(record["error_stage"], "sample_timeout")
        self.assertEqual(record["error_message"], "sample timed out after 120s")
        self.assertIn("case-1", record["infra_error_traceback"])
        self.assertEqual(
            record["last_events_before_timeout"][0]["stage"],
            "plan_created",
        )

    def test_missing_ssl_cert_env_is_repaired_with_certifi_for_eval(self):
        evaluator = self._evaluator()
        missing_cert = "/tmp/p6-missing-cacert.pem"

        with patch.dict(
            os.environ,
            {
                "SSL_CERT_FILE": missing_cert,
                "REQUESTS_CA_BUNDLE": missing_cert,
            },
            clear=False,
        ):
            result = evaluator._ensure_valid_ssl_cert_env()

            self.assertTrue(result["changed"])
            self.assertIn("SSL_CERT_FILE", result["missing_vars"])
            self.assertTrue(Path(os.environ["SSL_CERT_FILE"]).exists())
            self.assertEqual(os.environ["SSL_CERT_FILE"], os.environ["REQUESTS_CA_BUNDLE"])

    def test_caught_node_failure_with_final_response_is_degraded_not_hard_failure(self):
        evaluator = self._evaluator()
        executor_event = {
            "type": "step_complete",
            "stage": "step_executed",
            "current_step": "查询 CPU 指标",
            "step_result": "执行失败: TimeoutError: executor final llm response timed out after 60s",
            "infra_error": True,
            "infra_error_stage": "executor",
            "infra_error_message": "TimeoutError: executor final llm response timed out after 60s",
            "infra_error_traceback": "Traceback (most recent call last):\nexecutor timeout\n",
        }
        final_event = {
            "type": "complete",
            "stage": "diagnosis_complete",
            "diagnosis": {
                "status": "completed",
                "report": "最终报告已经由后续步骤恢复生成。",
            },
        }

        record = evaluator._build_response_record(
            query="service-a CPUHigh alert triggered again",
            response_text="最终报告已经由后续步骤恢复生成。",
            events=[executor_event, final_event],
            session_id="recovered-node-failure",
            has_error=False,
        )

        self.assertFalse(record["has_error"])
        self.assertTrue(record["has_degradation"])
        self.assertEqual(record["degradation_events"][0]["infra_error_stage"], "executor")
        self.assertEqual(record["infra_failure_events"], [])
        self.assertEqual(record["response"], "最终报告已经由后续步骤恢复生成。")

    def test_recovered_executor_get_tools_timeout_is_degraded_not_hard_failure(self):
        evaluator = self._evaluator()
        get_tools_event = {
            "type": "step_complete",
            "stage": "step_executed",
            "current_step": "查询 CPU 指标",
            "step_result": "执行失败: TimeoutError: executor get_tools timed out after 25.000s",
            "infra_error": True,
            "infra_error_stage": "executor",
            "infra_error_message": "TimeoutError: executor get_tools timed out after 25.000s",
        }
        final_event = {
            "type": "complete",
            "stage": "diagnosis_complete",
            "diagnosis": {
                "status": "completed",
                "report": "后续重试成功，最终报告已生成。",
            },
        }

        record = evaluator._build_response_record(
            query="service-a CPUHigh alert triggered again",
            response_text="后续重试成功，最终报告已生成。",
            events=[get_tools_event, final_event],
            session_id="recovered-get-tools-timeout",
            has_error=False,
        )

        self.assertFalse(record["has_error"])
        self.assertTrue(record["has_degradation"])
        self.assertEqual(record["degradation_events"][0]["infra_error_stage"], "executor")
        self.assertEqual(record["infra_failure_events"], [])

    def test_recovered_node_degradation_does_not_make_full_eval_invalid(self):
        evaluator = self._evaluator()
        evaluator.samples = [
            {"id": "p6_plan_001", "category": "plan_reuse"},
        ]
        evaluator.results = [
            {"sample_id": "p6_plan_001", "category": "plan_reuse", "passed": True}
        ]
        evaluator.preflight = {"ok": True, "tool_count": 7}
        evaluator.baseline_responses = {
            "p6_plan_001": evaluator._build_response_record(
                query="NetworkTimeout alert on service-e",
                response_text="baseline response",
                events=[],
                session_id="baseline",
                has_error=False,
            )
        }
        evaluator.guidance_responses = {
            "p6_plan_001": evaluator._build_response_record(
                query="NetworkTimeout alert on service-e",
                response_text="guidance recovered response",
                events=[
                    {
                        "type": "step_complete",
                        "stage": "step_executed",
                        "step_result": "执行失败: TimeoutError: executor final llm response timed out",
                        "infra_error": True,
                        "infra_error_stage": "executor",
                        "infra_error_message": "TimeoutError: executor final llm response timed out",
                    },
                    {
                        "type": "complete",
                        "stage": "diagnosis_complete",
                        "diagnosis": {
                            "status": "completed",
                            "report": "guidance recovered response",
                        },
                    },
                ],
                session_id="guidance",
                has_error=False,
            )
        }
        metrics = {
            "plan_reuse": {"passed": 1, "total": 1, "success_rate": 1.0},
            "repeated_alert": {"passed": 0, "total": 0, "success_rate": 0.0},
            "stale_override": {"passed": 0, "total": 0, "success_rate": 0.0},
            "overall": {"passed": 1, "total": 1, "success_rate": 1.0},
        }

        decision = evaluator.judge_continue_rollout(metrics)

        self.assertEqual(decision["eval_status"], "valid")
        self.assertEqual(decision["infra_summary"]["hard_failure_count"], 0)
        self.assertEqual(decision["infra_summary"]["degraded_sample_count"], 1)
        self.assertEqual(decision["infra_summary"]["stage_counts"], {})
        self.assertEqual(decision["infra_summary"]["degradation_stage_counts"]["executor"], 1)

    def test_executor_failed_step_event_keeps_infra_evidence(self):
        service = AIOpsService.__new__(AIOpsService)

        event = service._format_executor_event(
            {
                "plan": [],
                "past_steps": [("查询 CPU 指标", "执行失败: All connection attempts failed")],
                "infra_error": True,
                "infra_error_stage": "executor",
                "infra_error_message": "All connection attempts failed",
            }
        )

        self.assertTrue(event["infra_error"])
        self.assertEqual(event["infra_error_stage"], "executor")
        self.assertEqual(event["step_result"], "执行失败: All connection attempts failed")

    def test_planner_event_preserves_memory_observation_for_p6_trace(self):
        service = AIOpsService.__new__(AIOpsService)
        memory_observation = {
            "mode": "active",
            "memory_ids": ["mem_alert_cpu_high_stale"],
            "retrieval_trace": {
                "stale_policy": {
                    "cue_detected": True,
                    "matched_cues": ["fixed last week"],
                    "penalized_memory_ids": ["mem_alert_cpu_high_stale"],
                    "score_adjustments": [
                        {
                            "memory_id": "mem_alert_cpu_high_stale",
                            "base_score": 2.0,
                            "final_score": 1.0,
                        }
                    ],
                }
            },
        }

        event = service._format_planner_event(
            {
                "plan": ["检查当前指标"],
                "memory_observation": memory_observation,
            }
        )

        self.assertEqual(event["memory_observation"], memory_observation)

        evaluator = self._evaluator()
        compact = evaluator._compact_event(event)

        self.assertEqual(compact["memory_observation"], memory_observation)
        self.assertTrue(
            compact["memory_observation"]["retrieval_trace"]["stale_policy"]["cue_detected"]
        )

    def test_tool_node_output_without_messages_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "ToolNode returned no messages list"):
            _extract_tool_messages({"error": "tool node failed"})

    async def test_mcp_preflight_get_tools_failure_is_invalid(self):
        evaluator = self._evaluator()

        fake_client = AsyncMock()
        fake_client.get_tools = AsyncMock(side_effect=RuntimeError("get_tools failed"))

        evaluator.ensure_mcp_services = lambda: {"ok": True, "services": []}

        with patch(
            "app.agent.mcp_client.get_mcp_client_with_retry",
            new=AsyncMock(return_value=fake_client),
        ):
            preflight = await evaluator.preflight_mcp()

        self.assertFalse(preflight["ok"])
        self.assertEqual(preflight["failure_stage"], "get_tools")
        self.assertIn("get_tools failed", preflight["error"])

    async def test_milvus_connect_failure_generates_infra_failed_report(self):
        evaluator = self._evaluator()
        evaluator.preflight_mcp = AsyncMock(return_value={"ok": True, "tool_count": 7})

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "app.core.milvus_client.milvus_manager.connect",
            side_effect=RuntimeError("Milvus unavailable"),
        ):
            result = await evaluator.run(str(Path(tmpdir) / "reports"))

            self.assertFalse(result)
            reports = list(Path(tmpdir).glob("p6_memory_eval_*.json"))
            self.assertEqual(len(reports), 1)
            with open(reports[0], encoding="utf-8") as f:
                report = json.load(f)

        decision = report["decision"]
        self.assertEqual(decision["eval_status"], "infra_failed")
        self.assertEqual(decision["infra_failure_reason"], "milvus_preflight_failed")
        self.assertEqual(decision["infra_summary"]["hard_failure_count"], 1)
        self.assertEqual(decision["infra_summary"]["stage_counts"], {"milvus_connect": 1})
        self.assertIn(
            "Milvus unavailable",
            decision["infra_summary"]["hard_failures"][0]["message"],
        )
        self.assertIn(
            "RuntimeError",
            decision["infra_summary"]["hard_failures"][0]["traceback"],
        )

    async def test_mcp_get_tools_retries_with_fresh_client(self):
        cached_client = AsyncMock()
        cached_client.get_tools = AsyncMock(side_effect=RuntimeError("stale session"))
        fresh_client = AsyncMock()
        fresh_client.get_tools = AsyncMock(return_value=["tool-a"])

        calls = []

        async def fake_get_client(**kwargs):
            calls.append(kwargs.get("force_new"))
            return fresh_client if kwargs.get("force_new") else cached_client

        with patch(
            "app.agent.mcp_client.get_mcp_client_with_retry",
            new=AsyncMock(side_effect=fake_get_client),
        ):
            tools = await mcp_client.get_mcp_tools_with_retry()

        self.assertEqual(tools, ["tool-a"])
        self.assertEqual(calls, [False, True])

    async def test_structured_output_none_is_retried(self):
        class FakeChain:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, _payload):
                self.calls += 1
                return None if self.calls == 1 else {"steps": ["ok"]}

        chain = FakeChain()

        result = await invoke_structured_with_retry(
            chain,
            {"messages": []},
            stage="planner",
        )

        self.assertEqual(result, {"steps": ["ok"]})
        self.assertEqual(chain.calls, 2)

    async def test_structured_output_uses_fallback_after_primary_failure(self):
        class NoneChain:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, _payload):
                self.calls += 1
                return None

        class FallbackChain:
            def __init__(self):
                self.payload = None

            async def ainvoke(self, payload):
                self.payload = payload
                return {"steps": ["fallback ok"]}

        primary = NoneChain()
        fallback = FallbackChain()

        result = await invoke_structured_with_fallback(
            primary,
            fallback,
            {"messages": [("user", "primary")]},
            stage="planner",
            fallback_payload={"messages": [("user", "fallback")]},
        )

        self.assertEqual(result, {"steps": ["fallback ok"]})
        self.assertEqual(primary.calls, 2)
        self.assertEqual(fallback.payload["messages"][0][1], "fallback")

    async def test_structured_output_fallback_returns_recovery_diagnostics(self):
        class SlowPrimaryChain:
            async def ainvoke(self, _payload):
                await asyncio.sleep(0.1)
                return {"action": "continue"}

        class FastFallbackChain:
            async def ainvoke(self, payload):
                return {"action": payload["action"]}

        result, diagnostics = await invoke_structured_with_fallback(
            SlowPrimaryChain(),
            FastFallbackChain(),
            {"action": "primary"},
            stage="replanner",
            fallback_payload={"action": "continue"},
            timeout_seconds=0.01,
            return_diagnostics=True,
        )

        self.assertEqual(result, {"action": "continue"})
        self.assertTrue(diagnostics["structured_output_recovered"])
        self.assertTrue(diagnostics["structured_output_fallback_used"])
        self.assertEqual(
            diagnostics["structured_output_primary_error_type"],
            "TimeoutError",
        )
        self.assertIn(
            "replanner structured output timed out",
            diagnostics["structured_output_primary_error"],
        )
        self.assertEqual(diagnostics["structured_output_primary_stage"], "replanner")
        self.assertEqual(diagnostics["structured_output_fallback_stage"], "replanner_fallback")

    async def test_structured_output_reports_primary_and_fallback_failures(self):
        class NoneChain:
            async def ainvoke(self, _payload):
                return None

        with self.assertRaisesRegex(RuntimeError, "primary and fallback"):
            await invoke_structured_with_fallback(
                NoneChain(),
                NoneChain(),
                {"messages": []},
                stage="planner",
            )

    async def test_sample_timeout_is_recorded_as_infra_failure(self):
        evaluator = self._evaluator()
        evaluator.sample_timeout_seconds = 0.01

        async def slow_diagnose(**_kwargs):
            await asyncio.sleep(1)
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "diagnosis": {"status": "completed", "report": "too late"},
            }

        with patch(
            "evals.memory.run_p6_memory_eval.aiops_service",
            new=SimpleNamespace(diagnose=slow_diagnose),
        ):
            record = await evaluator._run_diagnosis_sample(
                session_id="timeout-case",
                query="slow sample",
                enable_memory_guidance=False,
            )

        self.assertTrue(record["has_error"])
        self.assertEqual(record["infra_failure_events"][0]["stage"], "sample_timeout")
        self.assertIn("timed out", record["infra_failure_events"][0]["infra_error_message"])
        self.assertIn("timeout-case", record["infra_failure_events"][0]["infra_error_traceback"])

    async def test_sample_timeout_keeps_last_events_for_debugging(self):
        evaluator = self._evaluator()
        evaluator.sample_timeout_seconds = 0.01

        async def slow_diagnose(**_kwargs):
            yield {
                "type": "step_complete",
                "stage": "step_executed",
                "current_step": "查询日志主题",
                "step_result": "未找到服务日志主题",
            }
            await asyncio.sleep(1)

        with patch(
            "evals.memory.run_p6_memory_eval.aiops_service",
            new=SimpleNamespace(diagnose=slow_diagnose),
        ):
            record = await evaluator._run_diagnosis_sample(
                session_id="timeout-with-events",
                query="service-h cache alert",
                enable_memory_guidance=True,
            )

        timeout_event = record["infra_failure_events"][0]
        self.assertEqual(timeout_event["stage"], "sample_timeout")
        self.assertIn("events_seen=1", timeout_event["infra_error_traceback"])
        self.assertEqual(
            timeout_event["last_events_before_timeout"][0]["current_step"],
            "查询日志主题",
        )

    async def test_wall_clock_timeout_is_recorded_when_blocking_call_finishes_late(self):
        evaluator = self._evaluator()
        evaluator.sample_timeout_seconds = 0.01

        async def blocking_diagnose(**_kwargs):
            yield {
                "type": "plan",
                "stage": "plan_created",
                "message": "执行计划已制定，共 1 个步骤",
                "plan": ["查询内存指标"],
            }
            time.sleep(0.03)
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "diagnosis": {
                    "status": "completed",
                    "report": "late but complete report",
                },
            }

        with patch(
            "evals.memory.run_p6_memory_eval.aiops_service",
            new=SimpleNamespace(diagnose=blocking_diagnose),
        ):
            record = await evaluator._run_diagnosis_sample(
                session_id="wall-clock-timeout",
                query="HighMemoryUsage alert on service-c",
                enable_memory_guidance=False,
                sample_id="p6_repeated_003",
            )

        self.assertTrue(record["has_error"])
        self.assertEqual(record["response"], "late but complete report")
        self.assertEqual(record["error_stage"], "sample_wall_clock_timeout")
        self.assertIn("elapsed_seconds", record["infra_error_traceback"])
        self.assertGreater(record["duration_seconds"], evaluator.sample_timeout_seconds)

    async def test_subprocess_hard_timeout_kills_child_and_preserves_progress(self):
        evaluator = self._evaluator()
        evaluator.isolate_samples = True
        evaluator.sample_timeout_seconds = 1.0

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            def sample_paths(session_id):
                return {
                    "payload": tmp_path / f"{session_id}.payload.json",
                    "output": tmp_path / f"{session_id}.record.json",
                    "progress": tmp_path / f"{session_id}.events.jsonl",
                    "log": tmp_path / f"{session_id}.log",
                }

            evaluator._sample_artifact_paths = sample_paths
            started_at = time.monotonic()

            record = await evaluator._run_diagnosis_sample_in_subprocess(
                session_id="child-hard-timeout",
                query="blocking child sample",
                enable_memory_guidance=False,
                sample_id="p6_timeout_child",
                child_extra_payload={"simulate_child_sleep_seconds": 5},
            )

            elapsed = time.monotonic() - started_at

        self.assertTrue(record["has_error"])
        self.assertLess(elapsed, 3.0)
        self.assertEqual(record["error_stage"], "sample_timeout")
        self.assertIn("child process exceeded eval hard timeout", record["infra_error_traceback"])
        self.assertIsNotNone(record["child_log_path"])
        self.assertIsNotNone(record["child_progress_path"])
        self.assertIn("child_log_path", record["infra_failure_events"][0])
        self.assertIn("child_progress_path", record["infra_failure_events"][0])
        self.assertEqual(
            record["last_events_before_timeout"][0]["stage"],
            "child_simulation",
        )
        self.assertIn(
            "simulate child blocking call",
            record["last_events_before_timeout"][0]["current_step"],
        )

    def test_child_artifact_paths_are_backfilled_for_internal_failures(self):
        evaluator = self._evaluator()
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = {
                "log": Path(tmpdir) / "sample.log",
                "progress": Path(tmpdir) / "sample.events.jsonl",
            }
            record = {
                "duration_seconds": None,
                "child_log_path": None,
                "child_progress_path": None,
                "infra_failure_events": [
                    {
                        "infra_error": True,
                        "infra_error_stage": "executor",
                        "infra_error_message": "APITimeoutError: Request timed out.",
                    }
                ],
                "key_events": [
                    {
                        "infra_error": True,
                        "infra_error_stage": "executor",
                        "infra_error_message": "APITimeoutError: Request timed out.",
                    }
                ],
                "events": [
                    {
                        "infra_error": True,
                        "infra_error_stage": "executor",
                        "infra_error_message": "APITimeoutError: Request timed out.",
                    }
                ],
            }

            updated = evaluator._attach_child_artifact_paths(
                record,
                paths,
                elapsed_seconds=12.3456,
            )

        self.assertEqual(updated["duration_seconds"], 12.346)
        self.assertTrue(updated["child_log_path"].endswith("sample.log"))
        self.assertTrue(updated["child_progress_path"].endswith("sample.events.jsonl"))
        self.assertEqual(
            updated["infra_failure_events"][0]["child_log_path"],
            updated["child_log_path"],
        )
        self.assertEqual(
            updated["key_events"][0]["child_progress_path"],
            updated["child_progress_path"],
        )
        self.assertEqual(
            updated["events"][0]["child_log_path"],
            updated["child_log_path"],
        )

    async def test_p6_eval_passes_eval_max_steps_to_diagnose(self):
        evaluator = self._evaluator()
        evaluator.eval_node_timeout_seconds = 7
        evaluator.eval_executor_final_timeout_seconds = 11
        captured_kwargs = {}

        async def fake_diagnose(**kwargs):
            captured_kwargs.update(kwargs)
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "diagnosis": {"status": "completed", "report": "done"},
            }

        with patch(
            "evals.memory.run_p6_memory_eval.aiops_service",
            new=SimpleNamespace(diagnose=fake_diagnose),
        ):
            record = await evaluator._run_diagnosis_sample(
                session_id="max-steps-case",
                query="service-a CPUHigh alert",
                enable_memory_guidance=True,
            )

        self.assertFalse(record["has_error"])
        self.assertEqual(captured_kwargs["eval_max_steps"], 3)
        self.assertEqual(captured_kwargs["eval_node_timeout_seconds"], 7)
        self.assertEqual(captured_kwargs["eval_executor_final_timeout_seconds"], 11)

    async def test_p6_eval_passes_sample_deadline_to_diagnose(self):
        evaluator = self._evaluator()
        evaluator.sample_timeout_seconds = 30
        captured_kwargs = {}

        async def fake_diagnose(**kwargs):
            captured_kwargs.update(kwargs)
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "diagnosis": {"status": "completed", "report": "done"},
            }

        started_at = time.monotonic()
        with patch(
            "evals.memory.run_p6_memory_eval.aiops_service",
            new=SimpleNamespace(diagnose=fake_diagnose),
        ):
            record = await evaluator._run_diagnosis_sample(
                session_id="deadline-case",
                query="service-a CPUHigh alert",
                enable_memory_guidance=False,
            )

        self.assertFalse(record["has_error"])
        self.assertIn("eval_deadline_monotonic", captured_kwargs)
        self.assertGreater(captured_kwargs["eval_deadline_monotonic"], started_at)
        self.assertLessEqual(
            captured_kwargs["eval_deadline_monotonic"],
            started_at + evaluator.sample_timeout_seconds + 0.5,
        )

    async def test_eval_deadline_shortens_optional_timeout(self):
        started_at = time.monotonic()

        with self.assertRaisesRegex(TimeoutError, "deadline-shortened stage timed out"):
            await await_with_optional_timeout(
                asyncio.sleep(1),
                timeout_seconds=5,
                stage="deadline-shortened stage",
                eval_deadline_monotonic=started_at + 0.03,
                deadline_guard_seconds=0,
            )

        self.assertLess(time.monotonic() - started_at, 0.5)

    async def test_executor_eval_node_timeout_marks_infra_failure(self):
        class SlowBoundLLM:
            async def ainvoke(self, _messages):
                await asyncio.sleep(1)
                return "too late"

        class FakeLLM:
            def __init__(self, **_kwargs):
                pass

            def bind_tools(self, _tools):
                return SlowBoundLLM()

        with (
            patch("app.agent.aiops.executor.ChatQwen", FakeLLM),
            patch(
                "app.agent.aiops.executor.get_mcp_tools_with_retry",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await aiops_executor({
                "plan": ["查询 service-f 日志主题"],
                "past_steps": [],
                "eval_node_timeout_seconds": 0.01,
            })

        self.assertTrue(result["infra_error"])
        self.assertEqual(result["infra_error_stage"], "executor")
        self.assertIn("timed out", result["infra_error_message"])
        self.assertIn("Traceback (most recent call last):", result["infra_error_traceback"])

    def test_replanner_event_exposes_structured_output_recovery_metadata(self):
        service = AIOpsService()

        event = service._format_replanner_event({
            "plan": ["继续检查缓存配置"],
            "structured_output_recovered": True,
            "structured_output_fallback_used": True,
            "structured_output_primary_error": (
                "TimeoutError: replanner structured output timed out after 25.000s"
            ),
            "structured_output_primary_error_type": "TimeoutError",
            "structured_output_primary_stage": "replanner",
            "structured_output_fallback_stage": "replanner_fallback",
            "structured_output_total_elapsed_ms": 25012.3,
        })

        self.assertEqual(event["type"], "status")
        self.assertEqual(event["stage"], "replanner")
        self.assertTrue(event["structured_output_recovered"])
        self.assertEqual(event["structured_output_primary_error_type"], "TimeoutError")
        self.assertIn("timed out", event["structured_output_primary_error"])

    def test_recovered_replanner_structured_output_is_degraded_not_hard_failure(self):
        evaluator = self._evaluator()
        replanner_event = {
            "type": "status",
            "stage": "replanner",
            "message": "评估完成，继续执行剩余步骤",
            "remaining_steps": 3,
            "structured_output_recovered": True,
            "structured_output_fallback_used": True,
            "structured_output_primary_error": (
                "TimeoutError: replanner structured output timed out after 25.000s"
            ),
            "structured_output_primary_error_type": "TimeoutError",
            "structured_output_primary_stage": "replanner",
            "structured_output_fallback_stage": "replanner_fallback",
            "structured_output_total_elapsed_ms": 25012.3,
        }
        final_event = {
            "type": "complete",
            "stage": "diagnosis_complete",
            "diagnosis": {
                "status": "completed",
                "report": "fallback 恢复后生成的最终报告。",
            },
        }

        record = evaluator._build_response_record(
            query="CacheHitRateLow alert on service-h",
            response_text="fallback 恢复后生成的最终报告。",
            events=[replanner_event, final_event],
            session_id="recovered-replanner-fallback",
            has_error=False,
        )

        self.assertFalse(record["has_error"])
        self.assertTrue(record["has_degradation"])
        self.assertEqual(record["infra_failure_events"], [])
        self.assertEqual(record["degradation_events"][0]["stage"], "replanner")
        self.assertTrue(record["degradation_events"][0]["structured_output_recovered"])
        self.assertIn("timed out", record["degradation_message"])

    async def test_executor_eval_node_timeout_marks_infra_failure_duplicate_removed_anchor(self):
        class SlowBoundLLM:
            async def ainvoke(self, _messages):
                await asyncio.sleep(1)
                return "too late"

        class FakeLLM:
            def __init__(self, **_kwargs):
                pass

            def bind_tools(self, _tools):
                return SlowBoundLLM()

        with (
            patch("app.agent.aiops.executor.ChatQwen", FakeLLM),
            patch(
                "app.agent.aiops.executor.get_mcp_tools_with_retry",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await aiops_executor({
                "plan": ["查询 service-f 日志主题"],
                "past_steps": [],
                "eval_node_timeout_seconds": 0.01,
            })

        self.assertTrue(result["infra_error"])
        self.assertEqual(result["infra_error_stage"], "executor")
        self.assertIn("timed out", result["infra_error_message"])
        self.assertIn("Traceback (most recent call last):", result["infra_error_traceback"])

    async def test_executor_final_llm_response_uses_dedicated_timeout(self):
        class FakeToolCallResponse:
            content = ""
            tool_calls = [{"name": "fake_tool", "args": {}, "id": "call-1"}]

        class FakeFinalResponse:
            content = "final response"
            tool_calls = []

        class FakeBoundLLM:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, _messages):
                self.calls += 1
                if self.calls == 1:
                    return FakeToolCallResponse()
                await asyncio.sleep(0.03)
                return FakeFinalResponse()

        class FakeLLM:
            bound = FakeBoundLLM()

            def __init__(self, **_kwargs):
                pass

            def bind_tools(self, _tools):
                return self.bound

        class FakeToolNode:
            def __init__(self, _tools):
                pass

            async def ainvoke(self, _payload):
                return {"messages": []}

        with (
            patch("app.agent.aiops.executor.ChatQwen", FakeLLM),
            patch("app.agent.aiops.executor.ToolNode", FakeToolNode),
            patch(
                "app.agent.aiops.executor.get_mcp_tools_with_retry",
                new=AsyncMock(return_value=[]),
            ),
        ):
            result = await aiops_executor({
                "plan": ["查询 service-f 日志主题"],
                "past_steps": [],
                "eval_node_timeout_seconds": 0.01,
                "eval_executor_final_timeout_seconds": 0.2,
            })

        self.assertNotIn("infra_error", result)
        self.assertEqual(result["past_steps"][0][1], "final response")

    async def test_flavor_runs_apply_sample_timeout_guard(self):
        evaluator = self._evaluator()
        evaluator.sample_timeout_seconds = 0.01
        evaluator.samples = [
            {
                "id": "p6_timeout_001",
                "category": "plan_reuse",
                "query": "slow sample",
            }
        ]

        async def slow_diagnose(**_kwargs):
            await asyncio.sleep(1)
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "diagnosis": {"status": "completed", "report": "too late"},
            }

        with patch(
            "evals.memory.run_p6_memory_eval.aiops_service",
            new=SimpleNamespace(diagnose=slow_diagnose),
        ):
            await evaluator.run_baseline_flavor()
            await evaluator.run_guidance_flavor()

        baseline = evaluator.baseline_responses["p6_timeout_001"]
        guidance = evaluator.guidance_responses["p6_timeout_001"]
        self.assertTrue(baseline["has_error"])
        self.assertTrue(guidance["has_error"])
        self.assertEqual(baseline["infra_failure_events"][0]["stage"], "sample_timeout")
        self.assertEqual(guidance["infra_failure_events"][0]["stage"], "sample_timeout")

    async def test_flavor_runs_do_not_stop_on_degraded_recovered_sample(self):
        evaluator = self._evaluator()
        evaluator.samples = [
            {"id": "p6_degraded_001", "category": "plan_reuse", "query": "first"},
            {"id": "p6_clean_002", "category": "plan_reuse", "query": "second"},
        ]

        async def recovered_diagnose(**kwargs):
            if kwargs["query"] == "first":
                yield {
                    "type": "step_complete",
                    "stage": "step_executed",
                    "step_result": "执行失败: TimeoutError: executor final llm response timed out",
                    "infra_error": True,
                    "infra_error_stage": "executor",
                    "infra_error_message": "TimeoutError: executor final llm response timed out",
                }
            yield {
                "type": "complete",
                "stage": "diagnosis_complete",
                "diagnosis": {"status": "completed", "report": f"done {kwargs['query']}"},
            }

        with patch(
            "evals.memory.run_p6_memory_eval.aiops_service",
            new=SimpleNamespace(diagnose=recovered_diagnose),
        ):
            await evaluator.run_baseline_flavor()

        self.assertEqual(
            set(evaluator.baseline_responses),
            {"p6_degraded_001", "p6_clean_002"},
        )
        self.assertFalse(evaluator.baseline_responses["p6_degraded_001"]["has_error"])
        self.assertTrue(evaluator.baseline_responses["p6_degraded_001"]["has_degradation"])

    def test_unrecovered_internal_infra_failure_makes_full_eval_invalid(self):
        evaluator = self._evaluator()
        evaluator.samples = [
            {"id": "p6_plan_001", "category": "plan_reuse"},
        ]
        evaluator.results = [
            {"sample_id": "p6_plan_001", "category": "plan_reuse", "passed": True}
        ]
        evaluator.preflight = {"ok": True, "tool_count": 7}
        evaluator.baseline_responses = {
            "p6_plan_001": evaluator._build_response_record(
                query="NetworkTimeout alert on service-e",
                response_text="baseline response",
                events=[],
                session_id="baseline",
                has_error=False,
            )
        }
        evaluator.guidance_responses = {
            "p6_plan_001": evaluator._build_response_record(
                query="NetworkTimeout alert on service-e",
                response_text="guidance response",
                events=[
                    {
                        "type": "plan",
                        "stage": "plan_created",
                        "infra_error": True,
                        "infra_error_stage": "planner",
                        "infra_error_message": "get_tools failed: All connection attempts failed",
                    }
                ],
                session_id="guidance",
                has_error=False,
            )
        }
        metrics = {
            "plan_reuse": {"passed": 1, "total": 1, "success_rate": 1.0},
            "repeated_alert": {"passed": 0, "total": 0, "success_rate": 0.0},
            "stale_override": {"passed": 0, "total": 0, "success_rate": 0.0},
            "overall": {"passed": 1, "total": 1, "success_rate": 1.0},
        }

        decision = evaluator.judge_continue_rollout(metrics)

        self.assertEqual(decision["eval_status"], "infra_failed")
        self.assertIsNone(decision["continue_rollout"])
        self.assertEqual(decision["infra_failure_reason"], "mcp_get_tools_failed_during_eval")
        self.assertEqual(decision["baseline_failures"], 0)
        self.assertEqual(decision["guidance_failures"], 1)
        self.assertEqual(decision["infra_summary"]["stage_counts"]["planner"], 1)

    def test_infra_summary_deduplicates_same_failure_per_sample(self):
        evaluator = self._evaluator()
        evaluator.samples = [
            {"id": "p6_plan_002", "category": "plan_reuse"},
        ]
        repeated_event = {
            "type": "plan",
            "stage": "plan_created",
            "infra_error": True,
            "infra_error_stage": "planner",
            "infra_error_message": "ValueError: planner structured output returned None after 2 attempts",
        }
        complete_event = {
            "type": "complete",
            "stage": "diagnosis_complete",
            "infra_error": True,
            "infra_error_stage": "planner",
            "infra_error_message": "ValueError: planner structured output returned None after 2 attempts",
            "diagnosis": {"status": "completed", "report": "fallback report"},
        }
        evaluator.baseline_responses = {
            "p6_plan_002": evaluator._build_response_record(
                query="DatabaseConnectionError alert on service-f",
                response_text="fallback report",
                events=[repeated_event, complete_event],
                session_id="baseline",
                has_error=False,
            )
        }

        summary = evaluator._collect_infra_summary()

        self.assertEqual(summary["baseline_failures"], 0)
        self.assertEqual(summary["hard_failure_count"], 0)
        self.assertEqual(summary["degraded_sample_count"], 1)
        self.assertEqual(summary["degradation_stage_counts"]["planner"], 1)

    async def test_execute_top_level_exception_preserves_infra_error_type(self):
        class BrokenGraph:
            async def astream(self, **_kwargs):
                raise KeyError("error")
                yield {}

        service = AIOpsService.__new__(AIOpsService)
        service.graph = BrokenGraph()

        events = [
            event
            async for event in service.execute(
                user_input="DiskHigh alert on service-b",
                session_id="top-level-error",
            )
        ]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertEqual(events[0]["stage"], "workflow_error")
        self.assertTrue(events[0]["infra_error"])
        self.assertEqual(events[0]["infra_error_stage"], "workflow")
        self.assertIn("KeyError", events[0]["infra_error_message"])
        self.assertIn("Traceback (most recent call last):", events[0]["infra_error_traceback"])
        self.assertIn("astream", events[0]["infra_error_traceback"])
        self.assertIn("KeyError: 'error'", events[0]["infra_error_traceback"])

    async def test_diagnose_complete_event_preserves_node_traceback(self):
        service = AIOpsService.__new__(AIOpsService)

        async def fake_execute(*_args, **_kwargs):
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": "fallback report",
                "infra_error": True,
                "infra_error_stage": "planner",
                "infra_error_message": "ValueError: planner structured output returned None after 2 attempts",
                "infra_error_traceback": "Traceback (most recent call last):\n  planner stack\nValueError: planner structured output returned None after 2 attempts\n",
            }

        service.execute = fake_execute

        events = [
            event
            async for event in service.diagnose(
                query="HighMemoryUsage alert on service-c",
                session_id="traceback-case",
            )
        ]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "complete")
        self.assertEqual(events[0]["stage"], "diagnosis_complete")
        self.assertTrue(events[0]["infra_error"])
        self.assertEqual(events[0]["infra_error_stage"], "planner")
        self.assertIn("planner stack", events[0]["infra_error_traceback"])

    async def test_diagnose_complete_marks_prior_infra_error_as_recovered_when_report_exists(self):
        service = AIOpsService.__new__(AIOpsService)

        async def fake_execute(*_args, **_kwargs):
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": "RedisQueueBacklog final report with complete evidence",
                "infra_error": True,
                "infra_error_stage": "executor",
                "infra_error_message": "ToolExecutionError: transient tool node failure",
                "infra_error_traceback": "Traceback (most recent call last):\n  executor stack\n",
            }

        service.execute = fake_execute

        events = [
            event
            async for event in service.diagnose(
                query="generic recovered diagnosis",
                session_id="recovered-infra-case",
            )
        ]

        self.assertEqual(events[0]["stage"], "diagnosis_complete")
        self.assertEqual(
            events[0]["diagnosis"]["report"],
            "RedisQueueBacklog final report with complete evidence",
        )
        self.assertTrue(events[0]["infra_error"])
        self.assertEqual(events[0]["failure_semantics"], "recovered_infra_error")
        self.assertFalse(events[0]["failure_semantics_hard_failure"])
        self.assertTrue(events[0]["degradation"])

    async def test_diagnose_complete_keeps_empty_report_infra_error_as_hard_failure(self):
        service = AIOpsService.__new__(AIOpsService)

        async def fake_execute(*_args, **_kwargs):
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": "",
                "infra_error": True,
                "infra_error_stage": "executor",
                "infra_error_message": "ToolExecutionError: terminal failure",
            }

        service.execute = fake_execute

        events = [
            event
            async for event in service.diagnose(
                query="generic terminal infra failure",
                session_id="terminal-infra-case",
            )
        ]

        self.assertEqual(events[0]["stage"], "diagnosis_complete")
        self.assertEqual(events[0]["failure_semantics"], "infra_error")
        self.assertTrue(events[0]["failure_semantics_hard_failure"])
        self.assertFalse(events[0]["degradation"])

    async def test_diagnose_passes_eval_max_steps_to_execute(self):
        service = AIOpsService.__new__(AIOpsService)
        captured_kwargs = {}

        async def fake_execute(*_args, **kwargs):
            captured_kwargs.update(kwargs)
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": "done",
            }

        service.execute = fake_execute

        events = [
            event
            async for event in service.diagnose(
                query="HighMemoryUsage alert on service-c",
                session_id="eval-max-steps-case",
                eval_max_steps=2,
                eval_node_timeout_seconds=9,
                eval_deadline_monotonic=12345.0,
            )
        ]

        self.assertEqual(events[0]["diagnosis"]["report"], "done")
        self.assertEqual(captured_kwargs["eval_max_steps"], 2)
        self.assertEqual(captured_kwargs["eval_node_timeout_seconds"], 9)
        self.assertEqual(captured_kwargs["eval_deadline_monotonic"], 12345.0)

    async def test_diagnose_passes_aiops_required_tools_to_execute(self):
        service = AIOpsService.__new__(AIOpsService)
        captured_kwargs = {}

        async def fake_execute(*_args, **kwargs):
            captured_kwargs.update(kwargs)
            yield {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": "done",
            }

        service.execute = fake_execute

        catalog_result = AIOpsToolCatalogResult(
            visible_tools=["query_active_alerts", "search_service_logs"],
            bindable_tools=[],
            required_tools=["query_active_alerts", "search_service_logs"],
        )
        with (
            patch("app.services.aiops_service.aiops_tool_catalog.bindable_tools", new=AsyncMock(return_value=[])),
            patch("app.services.aiops_service.aiops_tool_catalog.validate_required_tools", return_value=catalog_result),
        ):
            events = [
                event
                async for event in service.diagnose(
                    query="CPUHigh on data-sync-service",
                    session_id="required-tools-case",
                )
            ]

        self.assertEqual(events[0]["diagnosis"]["report"], "done")
        self.assertEqual(captured_kwargs["aiops_scenario"], "CPUHigh")
        self.assertEqual(captured_kwargs["aiops_service_name"], "data-sync-service")
        self.assertIn("query_active_alerts", captured_kwargs["aiops_required_tools"])
        self.assertIn("search_service_logs", captured_kwargs["aiops_required_tools"])

    def test_report_saves_full_response_and_key_events(self):
        evaluator = self._evaluator()
        evaluator.samples = [
            {"id": "p6_plan_001", "category": "plan_reuse"},
        ]
        full_response = "这是完整 final response，不只是长度。"
        event = {
            "type": "report",
            "stage": "final_report",
            "message": "最终报告已生成",
            "report": full_response,
        }
        evaluator.baseline_responses = {
            "p6_plan_001": evaluator._build_response_record(
                query="database connection alert",
                response_text=full_response,
                events=[event],
                session_id="baseline",
                has_error=False,
            )
        }
        evaluator.guidance_responses = {
            "p6_plan_001": evaluator._build_response_record(
                query="database connection alert",
                response_text=full_response,
                events=[event],
                session_id="guidance",
                has_error=False,
            )
        }
        evaluator.results = [
            {"sample_id": "p6_plan_001", "category": "plan_reuse", "passed": True}
        ]
        metrics = {
            "plan_reuse": {"passed": 1, "total": 1, "success_rate": 1.0},
            "repeated_alert": {"passed": 0, "total": 0, "success_rate": 0.0},
            "stale_override": {"passed": 0, "total": 0, "success_rate": 0.0},
            "overall": {"passed": 1, "total": 1, "success_rate": 1.0},
        }
        decision = {
            "eval_status": "valid",
            "continue_rollout": True,
            "citation_invariance_ok": True,
            "repeated_alert_lift": 0.0,
            "plan_reuse_lift": 1.0,
            "stale_override_lift": 0.0,
            "categories_passed": 1,
            "threshold": 0.20,
            "token_overhead": 0.15,
            "token_overhead_ok": True,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path, _ = evaluator.generate_report(metrics, decision, str(Path(tmpdir) / "report"))
            report = json.loads(Path(json_path).read_text(encoding="utf-8"))

        saved = report["baseline_responses"]["p6_plan_001"]
        self.assertEqual(saved["response"], full_response)
        self.assertEqual(saved["final_response"], full_response)
        self.assertEqual(saved["response_length"], len(full_response))
        self.assertEqual(saved["events"][0]["stage"], "final_report")
        self.assertIn("report_preview", saved["events"][0])
        self.assertEqual(saved["key_events"][0]["stage"], "final_report")

    def test_infra_traceback_is_not_truncated_in_report_events(self):
        evaluator = self._evaluator()
        long_traceback = (
            "Traceback (most recent call last):\n"
            + "\n".join(f"  frame {i}: detail {'x' * 80}" for i in range(60))
            + "\nValueError: planner structured output returned None after 2 attempts\n"
        )
        event = {
            "type": "plan",
            "stage": "plan_created",
            "infra_error": True,
            "infra_error_stage": "planner",
            "infra_error_message": "ValueError: planner structured output returned None after 2 attempts",
            "infra_error_traceback": long_traceback,
            "plan": ["收集相关信息"],
        }

        record = evaluator._build_response_record(
            query="HighMemoryUsage alert on service-c",
            response_text="fallback report",
            events=[event],
            session_id="traceback-case",
            has_error=False,
        )

        self.assertEqual(
            record["infra_failure_events"][0]["infra_error_traceback"],
            long_traceback,
        )
        self.assertEqual(
            record["key_events"][0]["infra_error_traceback"],
            long_traceback,
        )
        self.assertNotIn("truncated", record["infra_failure_events"][0]["infra_error_traceback"])

    def test_report_persists_successful_preflight(self):
        evaluator = self._evaluator()
        evaluator.samples = [
            {"id": "p6_plan_001", "category": "plan_reuse"},
        ]
        evaluator.preflight = {
            "ok": True,
            "tool_count": 7,
            "tools": ["query_cpu_metrics"],
        }
        evaluator.results = [
            {"sample_id": "p6_plan_001", "category": "plan_reuse", "passed": False}
        ]
        evaluator.baseline_responses = {
            "p6_plan_001": {"response": "", "has_error": True}
        }
        evaluator.guidance_responses = {
            "p6_plan_001": {"response": "", "has_error": True}
        }
        metrics = {
            "plan_reuse": {"passed": 0, "total": 1, "success_rate": 0.0},
            "repeated_alert": {"passed": 0, "total": 0, "success_rate": 0.0},
            "stale_override": {"passed": 0, "total": 0, "success_rate": 0.0},
            "overall": {"passed": 0, "total": 1, "success_rate": 0.0},
        }
        decision = evaluator._infra_failed_decision(
            reason="sample_internal_failure_rate_gt_50pct",
            infra_failure_rate=1.0,
            baseline_failures=1,
            guidance_failures=1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path, _ = evaluator.generate_report(metrics, decision, str(Path(tmpdir) / "report"))
            report = json.loads(Path(json_path).read_text(encoding="utf-8"))

        self.assertTrue(report["preflight"]["ok"])
        self.assertEqual(report["preflight"]["tool_count"], 7)


class P6MCPServerFixtureTests(unittest.TestCase):
    def test_search_log_accepts_symbolic_timestamp_strings(self):
        result = search_log.fn(
            topic_id="topic-001",
            start_time="current_ts - (15 * 60 * 1000)",
            end_time="current_ts",
            limit=2,
        )

        self.assertEqual(result["topic_id"], "topic-001")
        self.assertEqual(result["total"], 2)
        self.assertIsInstance(result["start_time"], int)
        self.assertIsInstance(result["end_time"], int)


if __name__ == "__main__":
    unittest.main()
