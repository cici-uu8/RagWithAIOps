import asyncio
import importlib.util
import json
import unittest
from pathlib import Path

from app.config import config
from app.services.aiops_service import AIOpsService


def _load_module(module_name: str, path: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class AIOpsLabFilesTests(unittest.TestCase):
    def test_aiops_lab_contains_first_version_runtime_assets(self):
        root = Path("aiops_lab")
        required_paths = [
            root / "docker-compose.yml",
            root / "prometheus" / "prometheus.yml",
            root / "prometheus" / "alert_rules.yml",
            root / "alertmanager" / "alertmanager.yml",
            root / "services" / "lab_service" / "app.py",
            root / "services" / "lab_service" / "Dockerfile",
            root / "mysql" / "business_schema.sql",
            root / "mysql" / "seed_business_data.sql",
            root / "cmdb" / "schema.sql",
            root / "cmdb" / "seed.py",
            root / "scripts" / "inject_fault.py",
            root / "scripts" / "reset_faults.py",
            root / "scripts" / "smoke_aiops.py",
        ]

        missing = [str(path) for path in required_paths if not path.exists()]
        self.assertEqual(missing, [])

        compose_text = (root / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("data-sync-service", compose_text)
        self.assertIn("order-service", compose_text)
        self.assertIn("inventory-service", compose_text)
        self.assertIn("prometheus", compose_text)
        self.assertIn("alertmanager", compose_text)
        self.assertIn("mysql", compose_text)
        self.assertIn("redis", compose_text)

        alert_rules = (root / "prometheus" / "alert_rules.yml").read_text(encoding="utf-8")
        self.assertIn("CPUHigh", alert_rules)
        self.assertIn("DBSlowQuery", alert_rules)
        self.assertIn("RedisQueueBacklog", alert_rules)

        schema = (root / "mysql" / "business_schema.sql").read_text(encoding="utf-8")
        for table_name in [
            "sync_jobs",
            "sync_runs",
            "orders",
            "order_items",
            "inventory_items",
            "inventory_reservations",
        ]:
            self.assertIn(table_name, schema)

    def test_mcp_config_and_registered_tools_include_aiops_lab_tools(self):
        self.assertEqual(config.mcp_servers["cls"]["url"], "http://localhost:8003/mcp")
        self.assertEqual(config.mcp_servers["monitor"]["url"], "http://localhost:8004/mcp")

        monitor_server = _load_module("monitor_server_registered_tools", "mcp_servers/monitor_server.py")
        cls_server = _load_module("cls_server_registered_tools", "mcp_servers/cls_server.py")

        async def get_tool_names():
            monitor_tools = await monitor_server.mcp.get_tools()
            cls_tools = await cls_server.mcp.get_tools()
            return set(monitor_tools), set(cls_tools)

        monitor_tool_names, cls_tool_names = asyncio.run(get_tool_names())
        self.assertTrue(
            {
                "query_active_alerts",
                "query_metric_series",
                "get_service_health",
                "get_service_info",
                "get_recent_deployments",
                "search_historical_tickets",
                "list_service_dependencies",
                "query_cpu_metrics",
                "query_memory_metrics",
            }.issubset(monitor_tool_names)
        )
        self.assertTrue(
            {
                "search_service_logs",
                "analyze_log_pattern",
                "get_current_timestamp",
                "search_log",
            }.issubset(cls_tool_names)
        )

    def test_smoke_result_gate_requires_aiops_evidence_and_expected_tools(self):
        smoke_aiops = _load_module("smoke_aiops_under_test", "aiops_lab/scripts/smoke_aiops.py")
        base_result = {
            "alert_found": True,
            "infra_error": None,
            "failure_semantics": None,
            "failure_semantics_hard_failure": False,
            "diagnosis_contains_required_evidence": True,
            "diagnosis_root_cause_correct": True,
            "expected_tools": [
                "query_active_alerts",
                "query_metric_series",
                "search_service_logs",
            ],
            "required_tools": [
                "query_active_alerts",
                "query_metric_series",
                "search_service_logs",
            ],
            "actual_tools": [
                "query_active_alerts",
                "query_metric_series",
                "search_service_logs",
            ],
            "required_evidence_categories": ["metric", "log"],
            "evidence_categories": ["metric", "log"],
        }

        self.assertTrue(smoke_aiops.result_passed(base_result, skip_aiops_api=False))

        missing_tool = {**base_result, "actual_tools": ["query_active_alerts"]}
        self.assertFalse(smoke_aiops.result_passed(missing_tool, skip_aiops_api=False))

        missing_required_label = {
            **base_result,
            "failure_semantics": "missing_required_tool",
            "failure_semantics_hard_failure": True,
        }
        self.assertFalse(smoke_aiops.result_passed(missing_required_label, skip_aiops_api=False))

        missing_evidence = {**base_result, "diagnosis_contains_required_evidence": False}
        self.assertFalse(smoke_aiops.result_passed(missing_evidence, skip_aiops_api=False))

        missing_evidence_category = {**base_result, "evidence_categories": ["metric"]}
        self.assertFalse(smoke_aiops.result_passed(missing_evidence_category, skip_aiops_api=False))

        recovered_degradation = {
            **base_result,
            "failure_semantics": "structured_output_recovered",
            "failure_semantics_hard_failure": False,
            "degradation_events": [{"failure_semantics": "structured_output_recovered"}],
        }
        self.assertTrue(smoke_aiops.result_passed(recovered_degradation, skip_aiops_api=False))

        recovered_infra = {
            **base_result,
            "failure_semantics": "recovered_infra_error",
            "failure_semantics_hard_failure": False,
            "degradation_events": [{"failure_semantics": "recovered_infra_error"}],
        }
        self.assertTrue(smoke_aiops.result_passed(recovered_infra, skip_aiops_api=False))

        no_alert = {**base_result, "alert_found": False}
        self.assertFalse(smoke_aiops.result_passed(no_alert, skip_aiops_api=True))
        self.assertTrue(smoke_aiops.result_passed(base_result, skip_aiops_api=True))

    def test_smoke_failure_semantics_uses_terminal_complete_event_not_intermediate_error(self):
        smoke_aiops = _load_module(
            "smoke_aiops_terminal_semantics_under_test",
            "aiops_lab/scripts/smoke_aiops.py",
        )
        sse_raw = "\n\n".join(
            [
                "event: message\n"
                'data: {"type":"step_complete","stage":"step_executed",'
                '"infra_error":true,"failure_semantics":"infra_error",'
                '"failure_semantics_hard_failure":true}',
                "event: message\n"
                'data: {"type":"complete","stage":"diagnosis_complete",'
                '"diagnosis":{"status":"completed","report":"RedisQueueBacklog final report"},'
                '"failure_semantics":"recovered_infra_error",'
                '"failure_semantics_hard_failure":false}',
            ]
        )
        diagnosis_text = json.dumps({"raw": sse_raw}, ensure_ascii=False)

        failure_semantics, hard_failure = smoke_aiops.extract_failure_semantics(
            diagnosis_text,
            infra_error=None,
        )

        self.assertEqual(failure_semantics, "recovered_infra_error")
        self.assertFalse(hard_failure)

    def test_smoke_failure_semantics_parses_crlf_sse_blocks(self):
        smoke_aiops = _load_module(
            "smoke_aiops_terminal_semantics_crlf_under_test",
            "aiops_lab/scripts/smoke_aiops.py",
        )
        sse_raw = "\r\n\r\n".join(
            [
                "event: message\r\n"
                'data: {"type":"step_complete","stage":"step_executed",'
                '"infra_error":true,"failure_semantics":"infra_error",'
                '"failure_semantics_hard_failure":true}',
                "event: message\r\n"
                'data: {"type":"complete","stage":"diagnosis_complete",'
                '"diagnosis":{"status":"completed","report":"DBSlowQuery final report"},'
                '"failure_semantics":"recovered_infra_error",'
                '"failure_semantics_hard_failure":false}',
            ]
        )
        diagnosis_text = json.dumps({"raw": sse_raw}, ensure_ascii=False)

        failure_semantics, hard_failure = smoke_aiops.extract_failure_semantics(
            diagnosis_text,
            infra_error=None,
        )

        self.assertEqual(failure_semantics, "recovered_infra_error")
        self.assertFalse(hard_failure)

    def test_smoke_login_token_extraction_matches_enterprise_auth_response(self):
        smoke_aiops = _load_module("smoke_aiops_token_under_test", "aiops_lab/scripts/smoke_aiops.py")

        self.assertEqual(smoke_aiops.extract_access_token({"access_token": "legacy-token"}), "legacy-token")
        self.assertEqual(
            smoke_aiops.extract_access_token({"data": {"access_token": "enterprise-token"}}),
            "enterprise-token",
        )
        self.assertIsNone(smoke_aiops.extract_access_token({"code": 200, "data": {}}))

    def test_smoke_default_login_credentials_match_seed_user(self):
        smoke_aiops = _load_module("smoke_aiops_defaults_under_test", "aiops_lab/scripts/smoke_aiops.py")

        self.assertEqual(smoke_aiops.DEFAULT_USERNAME, "demo_user_dept1")
        self.assertEqual(smoke_aiops.DEFAULT_PASSWORD, "Demo123!")

    def test_smoke_cases_use_long_fault_window_and_case_specific_query(self):
        smoke_aiops = _load_module("smoke_aiops_case_query_under_test", "aiops_lab/scripts/smoke_aiops.py")

        self.assertEqual(smoke_aiops.FAULT_DURATION, "1800s")
        for case in smoke_aiops.CASES:
            self.assertIn("duration=1800s", case["inject_url"])

            query = smoke_aiops.build_case_query(case)
            self.assertIn(case["case_id"], query)
            self.assertIn(case["fault_type"], query)
            self.assertIn(case["service_name"], query)
            self.assertIn(case["expected_root_cause"], query)
            for tool_name in case["expected_tools"]:
                self.assertIn(tool_name, query)

    def test_smoke_run_case_resets_before_inject_and_sends_case_query(self):
        smoke_aiops = _load_module("smoke_aiops_run_case_under_test", "aiops_lab/scripts/smoke_aiops.py")
        calls = []

        def fake_post_json(url, payload=None, token=None):
            calls.append((url, payload, token))
            if url.endswith("/api/aiops"):
                return {
                    "raw": (
                        "query_active_alerts query_metric_series search_service_logs "
                        "CPUHigh data-sync-service"
                    )
                }
            return {}

        def fake_wait_for_alert(alert_name, service_name, timeout_seconds):
            return {"found": True, "alert": {"alert_name": alert_name, "service_name": service_name}}

        original_post_json = smoke_aiops.post_json
        original_wait_for_alert = smoke_aiops.wait_for_alert
        try:
            smoke_aiops.post_json = fake_post_json
            smoke_aiops.wait_for_alert = fake_wait_for_alert
            result = smoke_aiops.run_case(
                smoke_aiops.CASES[0],
                api_url="http://api.local",
                token="token-1",
                skip_aiops_api=False,
            )
        finally:
            smoke_aiops.post_json = original_post_json
            smoke_aiops.wait_for_alert = original_wait_for_alert

        self.assertTrue(result["alert_found"])
        self.assertEqual(calls[0][0], smoke_aiops.RESET_URL)
        self.assertEqual(calls[1][0], smoke_aiops.CASES[0]["inject_url"])
        self.assertEqual(calls[2][0], "http://api.local/api/aiops")
        self.assertIn("CPUHigh", calls[2][1]["query"])
        self.assertIn("data-sync-service", calls[2][1]["query"])


class AIOpsDefaultPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_aiops_task_starts_from_active_alerts_and_evidence_tools(self):
        captured = {}

        async def fake_execute(user_input, *args, **kwargs):
            captured["user_input"] = user_input
            yield {"type": "done", "content": "ok"}

        service = AIOpsService()
        service.execute = fake_execute

        events = []
        async for event in service.diagnose(session_id="test-session", query=None):
            events.append(event)

        self.assertEqual(events, [{"type": "done", "content": "ok"}])
        prompt = captured["user_input"]
        self.assertIn("query_active_alerts", prompt)
        self.assertIn("没有活跃告警", prompt)
        self.assertIn("query_metric_series", prompt)
        self.assertIn("search_service_logs", prompt)
        self.assertIn("get_recent_deployments", prompt)
        self.assertIn("search_historical_tickets", prompt)
        self.assertIn("不得编造", prompt)


if __name__ == "__main__":
    unittest.main()
