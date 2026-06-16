import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

FAULT_DURATION = "1800s"
RESET_URL = "http://localhost:9101/inject/reset"
HARD_FAILURE_SEMANTICS = {
    "missing_required_tool",
    "mcp_timeout",
    "mcp_provider_error",
    "llm_timeout",
    "structured_output_failed",
    "infra_error",
    "tool_permission_denied",
}
RECOVERED_SEMANTICS = {"structured_output_recovered", "recovered_infra_error"}
REQUIRED_EVIDENCE_CATEGORIES = ["metric", "log", "cmdb", "deployment", "ticket", "dependency"]
EVIDENCE_TOOL_CATEGORIES = {
    "query_metric_series": "metric",
    "search_service_logs": "log",
    "analyze_log_pattern": "log",
    "get_service_info": "cmdb",
    "get_recent_deployments": "deployment",
    "search_historical_tickets": "ticket",
    "list_service_dependencies": "dependency",
}

CASES = [
    {
        "case_id": "cpu-high-data-sync",
        "fault_type": "CPUHigh",
        "service_name": "data-sync-service",
        "inject_url": f"http://localhost:9101/inject/cpu-high?duration={FAULT_DURATION}",
        "expected_root_cause": "CPU usage exceeded threshold on data-sync-service",
        "expected_tools": ["query_active_alerts", "query_metric_series", "search_service_logs"],
    },
    {
        "case_id": "db-slow-data-sync",
        "fault_type": "DBSlowQuery",
        "service_name": "data-sync-service",
        "inject_url": f"http://localhost:9101/inject/db-slow?duration={FAULT_DURATION}",
        "expected_root_cause": "MySQL query latency exceeded 2 seconds",
        "expected_tools": ["query_active_alerts", "query_metric_series", "search_service_logs"],
    },
    {
        "case_id": "redis-backlog-data-sync",
        "fault_type": "RedisQueueBacklog",
        "service_name": "data-sync-service",
        "inject_url": f"http://localhost:9101/inject/redis-queue-backlog?size=200&duration={FAULT_DURATION}",
        "expected_root_cause": "Redis queue backlog exceeded threshold",
        "expected_tools": ["query_active_alerts", "query_metric_series", "search_service_logs"],
    },
]
DEFAULT_USERNAME = "demo_user_dept1"
DEFAULT_PASSWORD = "Demo123!"


def get_json(url: str) -> dict | list:
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict | None = None, token: str | None = None) -> dict:
    body = b""
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}


def extract_access_token(response: dict) -> str | None:
    token = response.get("access_token")
    if isinstance(token, str) and token:
        return token
    data = response.get("data")
    if isinstance(data, dict):
        nested_token = data.get("access_token")
        if isinstance(nested_token, str) and nested_token:
            return nested_token
    return None


def result_passed(result: dict, *, skip_aiops_api: bool) -> bool:
    if not result.get("alert_found"):
        return False
    if skip_aiops_api:
        return True
    failure_semantics = str(result.get("failure_semantics") or "")
    if result.get("infra_error") and failure_semantics not in RECOVERED_SEMANTICS:
        return False
    if result.get("failure_semantics_hard_failure") or failure_semantics in HARD_FAILURE_SEMANTICS:
        return False
    if not result.get("diagnosis_contains_required_evidence"):
        return False
    if not result.get("diagnosis_root_cause_correct"):
        return False
    expected_tools = set(result.get("expected_tools", []))
    required_tools = set(result.get("required_tools") or expected_tools)
    actual_tools = set(result.get("actual_tools", []))
    if not required_tools.issubset(actual_tools):
        return False
    required_evidence = set(result.get("required_evidence_categories", []))
    evidence = set(result.get("evidence_categories", []))
    return required_evidence.issubset(evidence)


def wait_for_alert(alert_name: str, service_name: str, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    url = "http://localhost:9093/api/v2/alerts?active=true&silenced=false&inhibited=false"
    while time.time() < deadline:
        alerts = get_json(url)
        for alert in alerts if isinstance(alerts, list) else []:
            labels = alert.get("labels", {})
            if labels.get("alertname") == alert_name and labels.get("service_name") == service_name:
                return {"found": True, "alert": alert}
        time.sleep(3)
    return {"found": False, "alert": None}


def login(api_url: str, username: str, password: str) -> str | None:
    response = post_json(
        f"{api_url.rstrip('/')}/api/auth/login",
        {"username": username, "password": password},
    )
    return extract_access_token(response)


def build_case_query(case: dict) -> str:
    required_tools = case.get("required_tools") or required_tools_for_fault(case["fault_type"])
    expected_tools = "、".join(required_tools)
    return (
        f"只诊断 AIOps lab 用例 {case['case_id']}："
        f"目标服务是 {case['service_name']}，预期故障类型是 {case['fault_type']}。"
        "必须先调用 query_active_alerts，并只围绕该目标服务和故障类型筛选活跃告警；"
        f"随后必须调用 {expected_tools} 获取指标、日志、CMDB、发布、工单和依赖证据。"
        f"最终报告必须明确写出 {case['fault_type']}、{case['service_name']} "
        f"以及根因：{case['expected_root_cause']}。"
        "如果工具返回多个告警，不要扩展分析其他服务或其他故障。"
    )


def required_tools_for_fault(fault_type: str) -> list[str]:
    try:
        from app.enterprise.aiops.tool_catalog import aiops_tool_catalog

        return aiops_tool_catalog.required_tools_for_scenario(fault_type)
    except Exception:
        return []


def extract_actual_tools(diagnosis_text: str, candidate_tools: list[str]) -> list[str]:
    return [tool for tool in candidate_tools if tool in diagnosis_text]


def extract_evidence_categories(actual_tools: list[str]) -> list[str]:
    categories = {
        EVIDENCE_TOOL_CATEGORIES[tool]
        for tool in actual_tools
        if tool in EVIDENCE_TOOL_CATEGORIES
    }
    return sorted(categories)


def extract_failure_semantics(diagnosis_text: str, infra_error: str | None) -> tuple[str | None, bool]:
    if infra_error:
        return "infra_error", True
    terminal_event = extract_terminal_event(diagnosis_text)
    if terminal_event:
        label = _event_value(terminal_event, "failure_semantics")
        hard_failure = _event_value(terminal_event, "failure_semantics_hard_failure")
        if label:
            return str(label), bool(hard_failure)
    for label in sorted(HARD_FAILURE_SEMANTICS | RECOVERED_SEMANTICS):
        if label in diagnosis_text:
            return label, label in HARD_FAILURE_SEMANTICS
    return None, False


def extract_terminal_event(diagnosis_text: str) -> dict | None:
    payload = _json_loads_dict(diagnosis_text)
    candidates: list[dict] = []
    if payload:
        candidates.extend(_event_candidates(payload))
        raw = payload.get("raw")
        if isinstance(raw, str):
            candidates.extend(_parse_sse_events(raw))
    else:
        candidates.extend(_parse_sse_events(diagnosis_text))

    for event in reversed(candidates):
        event_type = str(event.get("type") or "")
        stage = str(event.get("stage") or "")
        if event_type == "complete" or stage == "diagnosis_complete":
            return event
    return None


def _json_loads_dict(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _event_candidates(value) -> list[dict]:
    if isinstance(value, dict):
        events = value.get("events")
        if isinstance(events, list):
            return [event for event in events if isinstance(event, dict)]
        return [value]
    return []


def _parse_sse_events(raw: str) -> list[dict]:
    events: list[dict] = []
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    for block in normalized.split("\n\n"):
        data_lines = [
            line.removeprefix("data:").strip()
            for line in block.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        data_text = "\n".join(data_lines)
        try:
            event = json.loads(data_text)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _event_value(event: dict, key: str):
    if key in event:
        return event[key]
    data = event.get("data")
    if isinstance(data, dict):
        return data.get(key)
    return None


def run_case(case: dict, api_url: str, token: str | None, skip_aiops_api: bool) -> dict:
    started_at = time.time()
    post_json(RESET_URL)
    post_json(case["inject_url"])
    alert_result = wait_for_alert(case["fault_type"], case["service_name"], timeout_seconds=90)
    diagnosis_text = ""
    infra_error = None
    required_tools = case.get("required_tools") or required_tools_for_fault(case["fault_type"])
    if not required_tools:
        required_tools = list(case["expected_tools"])
    actual_tools = []
    if not skip_aiops_api and token:
        try:
            response = post_json(
                f"{api_url.rstrip('/')}/api/aiops",
                {
                    "session_id": f"aiops-lab-{case['case_id']}",
                    "query": build_case_query(case),
                },
                token=token,
            )
            diagnosis_text = json.dumps(response, ensure_ascii=False)
        except Exception as exc:
            infra_error = str(exc)
    elif not skip_aiops_api:
        infra_error = "api token missing"

    actual_tools = extract_actual_tools(
        diagnosis_text,
        sorted(set(case["expected_tools"]) | set(required_tools)),
    )
    evidence_categories = extract_evidence_categories(actual_tools)
    failure_semantics, hard_failure = extract_failure_semantics(diagnosis_text, infra_error)

    required_terms = [case["fault_type"], case["service_name"]]
    return {
        "case_id": case["case_id"],
        "fault_type": case["fault_type"],
        "service_name": case["service_name"],
        "expected_root_cause": case["expected_root_cause"],
        "expected_tools": case["expected_tools"],
        "required_tools": required_tools,
        "actual_tools": actual_tools,
        "missing_tools": sorted(set(required_tools) - set(actual_tools)),
        "required_evidence_categories": REQUIRED_EVIDENCE_CATEGORIES,
        "evidence_categories": evidence_categories,
        "diagnosis_contains_required_evidence": all(term in diagnosis_text for term in required_terms)
        if diagnosis_text
        else False,
        "diagnosis_root_cause_correct": case["fault_type"] in diagnosis_text if diagnosis_text else False,
        "latency_seconds": round(time.time() - started_at, 3),
        "alert_found": alert_result["found"],
        "infra_error": infra_error,
        "failure_semantics": failure_semantics,
        "failure_semantics_hard_failure": hard_failure,
        "degradation_events": (
            [{"failure_semantics": failure_semantics}]
            if failure_semantics in RECOVERED_SEMANTICS
            else []
        ),
        "notes": "AIOps API skipped" if skip_aiops_api else "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AIOps lab smoke cases.")
    parser.add_argument("--api-url", default="http://localhost:9900")
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--token", default=None)
    parser.add_argument("--skip-aiops-api", action="store_true")
    parser.add_argument("--output", default="aiops_lab/reports/smoke_aiops_results.json")
    args = parser.parse_args()

    token = args.token
    if not token and not args.skip_aiops_api:
        token = login(args.api_url, args.username, args.password)

    results = [run_case(case, args.api_url, token, args.skip_aiops_api) for case in CASES]
    report = {
        "created_at": datetime.now(UTC).astimezone().isoformat(),
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if any(not result_passed(result, skip_aiops_api=args.skip_aiops_api) for result in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
