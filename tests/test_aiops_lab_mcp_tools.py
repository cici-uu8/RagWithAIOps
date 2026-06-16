import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


def _load_module(module_name: str, path: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


monitor_server = _load_module("monitor_server_under_test", "mcp_servers/monitor_server.py")
cls_server = _load_module("cls_server_under_test", "mcp_servers/cls_server.py")


class FakeHttpResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class AIOpsLabMCPToolsTests(unittest.TestCase):
    def test_query_active_alerts_normalizes_alertmanager_payload(self):
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append((url, params, timeout))
            return FakeHttpResponse(
                [
                    {
                        "labels": {
                            "alertname": "DBSlowQuery",
                            "service_name": "data-sync-service",
                            "severity": "warning",
                        },
                        "annotations": {"summary": "DB latency is high"},
                        "startsAt": "2026-06-02T10:02:00+08:00",
                        "updatedAt": "2026-06-02T10:03:00+08:00",
                        "status": {"state": "active"},
                    },
                    {
                        "labels": {
                            "alertname": "CPUHigh",
                            "service_name": "data-sync-service",
                            "severity": "critical",
                        },
                        "annotations": {"summary": "CPU usage is high"},
                        "startsAt": "2026-06-02T10:00:00+08:00",
                        "updatedAt": "2026-06-02T10:01:00+08:00",
                        "status": {"state": "active"},
                    }
                ]
            )

        result = monitor_server._query_active_alerts(
            alertmanager_url="http://alertmanager:9093",
            http_get=fake_get,
        )

        self.assertEqual(calls[0][0], "http://alertmanager:9093/api/v2/alerts")
        self.assertEqual(calls[0][1]["active"], "true")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["alerts"][0]["alert_name"], "CPUHigh")
        self.assertEqual(result["alerts"][0]["service_name"], "data-sync-service")
        self.assertEqual(result["alerts"][0]["severity"], "critical")
        self.assertEqual(result["alerts"][0]["summary"], "CPU usage is high")
        self.assertEqual(result["alerts"][1]["alert_name"], "DBSlowQuery")

    def test_query_metric_series_returns_prometheus_points_and_summary(self):
        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append((url, params, timeout))
            return FakeHttpResponse(
                {
                    "status": "success",
                    "data": {
                        "result": [
                            {
                                "metric": {
                                    "__name__": "service_cpu_percent",
                                    "service_name": "data-sync-service",
                                },
                                "values": [
                                    [1780365600.0, "42.5"],
                                    [1780365660.0, "91.0"],
                                ],
                            }
                        ]
                    },
                }
            )

        result = monitor_server._query_metric_series(
            prometheus_url="http://prometheus:9090",
            service_name="data-sync-service",
            metric_name="service_cpu_percent",
            start_time="2026-06-02T10:00:00+08:00",
            end_time="2026-06-02T10:02:00+08:00",
            http_get=fake_get,
        )

        self.assertEqual(calls[0][0], "http://prometheus:9090/api/v1/query_range")
        self.assertIn('service_name="data-sync-service"', calls[0][1]["query"])
        self.assertEqual(result["metric_name"], "service_cpu_percent")
        self.assertEqual(result["service_name"], "data-sync-service")
        self.assertEqual(result["statistics"]["max"], 91.0)
        self.assertEqual(result["statistics"]["avg"], 66.75)
        self.assertEqual(len(result["data_points"]), 2)

    def test_cmdb_helpers_return_service_context_from_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "cmdb.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE services (
                      service_name TEXT PRIMARY KEY,
                      owner_team TEXT,
                      owner_user TEXT,
                      environment TEXT,
                      dependencies TEXT,
                      runbook_url TEXT
                    );
                    CREATE TABLE deployments (
                      deployment_id TEXT PRIMARY KEY,
                      service_name TEXT,
                      version TEXT,
                      deployed_at TEXT,
                      operator TEXT,
                      change_summary TEXT
                    );
                    CREATE TABLE tickets (
                      ticket_id TEXT PRIMARY KEY,
                      service_name TEXT,
                      alert_name TEXT,
                      root_cause TEXT,
                      resolution TEXT,
                      created_at TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT INTO services VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "data-sync-service",
                        "platform-team",
                        "alice",
                        "lab",
                        '["mysql", "redis"]',
                        "https://runbooks.local/data-sync",
                    ),
                )
                conn.execute(
                    "INSERT INTO deployments VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "dep-001",
                        "data-sync-service",
                        "v1.2.3",
                        "2026-06-02T09:30:00+08:00",
                        "bob",
                        "metadata sync tuning",
                    ),
                )
                conn.execute(
                    "INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "inc-001",
                        "data-sync-service",
                        "CPUHigh",
                        "CPU-bound sync loop",
                        "limit worker concurrency",
                        "2026-05-20T10:00:00+08:00",
                    ),
                )

            service = monitor_server._get_service_info_from_db(str(db_path), "data-sync-service")
            deployments = monitor_server._get_recent_deployments_from_db(
                str(db_path), "data-sync-service", limit=5
            )
            tickets = monitor_server._search_historical_tickets_from_db(
                str(db_path), "data-sync-service", alert_name="CPUHigh", limit=5
            )
            dependencies = monitor_server._list_service_dependencies_from_db(
                str(db_path), "data-sync-service"
            )

        self.assertEqual(service["owner_team"], "platform-team")
        self.assertEqual(deployments["deployments"][0]["version"], "v1.2.3")
        self.assertEqual(tickets["tickets"][0]["root_cause"], "CPU-bound sync loop")
        self.assertEqual(dependencies["dependencies"], ["mysql", "redis"])

    def test_search_service_logs_filters_jsonl_by_service_time_level_and_keyword(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            log_path = logs_dir / "data-sync-service.jsonl"
            entries = [
                {
                    "timestamp": "2026-06-02T10:00:00+08:00",
                    "service_name": "data-sync-service",
                    "instance_id": "data-sync-1",
                    "level": "INFO",
                    "trace_id": "trace-ok",
                    "event_type": "heartbeat",
                    "message": "service heartbeat",
                },
                {
                    "timestamp": "2026-06-02T10:01:00+08:00",
                    "service_name": "data-sync-service",
                    "instance_id": "data-sync-1",
                    "level": "ERROR",
                    "trace_id": "trace-slow",
                    "event_type": "db_slow_query",
                    "message": "metadata sync query exceeded latency threshold",
                    "latency_ms": 3200,
                },
            ]
            log_path.write_text("\n".join(json.dumps(item) for item in entries), encoding="utf-8")

            result = cls_server._search_service_logs_from_jsonl(
                logs_dir=str(logs_dir),
                service_name="data-sync-service",
                start_time="2026-06-02T10:00:30+08:00",
                end_time="2026-06-02T10:02:00+08:00",
                level="ERROR",
                keyword="latency threshold",
                limit=10,
            )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["logs"][0]["trace_id"], "trace-slow")
        self.assertEqual(result["logs"][0]["event_type"], "db_slow_query")

    def test_analyze_log_pattern_counts_error_and_fault_events(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir)
            (logs_dir / "data-sync-service.jsonl").write_text(
                "\n".join(
                    json.dumps(item)
                    for item in [
                        {
                            "timestamp": "2026-06-02T10:00:00+08:00",
                            "service_name": "data-sync-service",
                            "level": "ERROR",
                            "event_type": "db_slow_query",
                            "message": "slow query",
                        },
                        {
                            "timestamp": "2026-06-02T10:01:00+08:00",
                            "service_name": "data-sync-service",
                            "level": "WARN",
                            "event_type": "redis_backlog",
                            "message": "redis queue backlog",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = cls_server._analyze_log_pattern_from_jsonl(
                logs_dir=str(logs_dir),
                service_name="data-sync-service",
                start_time="2026-06-02T09:59:00+08:00",
                end_time="2026-06-02T10:02:00+08:00",
            )

        self.assertEqual(result["patterns"]["error_count"], 1)
        self.assertEqual(result["patterns"]["slow_query_count"], 1)
        self.assertEqual(result["patterns"]["redis_backlog_count"], 1)


if __name__ == "__main__":
    unittest.main()
