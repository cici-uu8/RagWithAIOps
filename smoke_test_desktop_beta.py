"""
桌面端 Beta 技术冒烟测试
明确标注：这不是 Beta 测试，是技术验收
不产生"满意度"、"愿意继续用"等主观反馈
"""
import json
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "http://localhost:9900"
OUTPUT_DIR = Path("output/smoke_test")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SMOKE_STATE = {}


def redact_sensitive(value):
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if key.lower() in {"access_token", "token", "authorization"} else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def response_details(response, extra=None):
    details = dict(extra or {})
    details["status_code"] = response.status_code
    try:
        details["json"] = redact_sensitive(response.json())
    except ValueError:
        details["body"] = response.text[:800]
    return details


def find_action_option(resource, preferred_actions=None):
    preferred_actions = preferred_actions or []
    options = resource.get("action_options") or [
        {"action": action, "already_granted": False}
        for action in resource.get("actions_supported", [])
    ]
    pending = [option for option in options if not option.get("already_granted")]
    for action in preferred_actions:
        for option in pending:
            if option.get("action") == action:
                return action
    return pending[0].get("action") if pending else None


def choose_requestable_resource(resources):
    preferred = [
        ("tool", "retrieve_knowledge", ["use"]),
        ("database", "sandbox_sales", ["read", "write", "admin"]),
    ]
    for resource_type, resource_id, actions in preferred:
        for resource in resources:
            if (
                resource.get("resource_type") == resource_type
                and resource.get("resource_id") == resource_id
            ):
                action = find_action_option(resource, actions)
                if action:
                    return resource, action

    for resource in resources:
        action = find_action_option(resource)
        if action:
            return resource, action
    return None, None


def find_matching_pending_request(headers, resource_type, resource_id, action):
    response = requests.get(f"{BASE_URL}/api/permission-requests/mine", headers=headers)
    if response.status_code != 200:
        return None
    requests_payload = response.json().get("data", {}).get("permission_requests", [])
    for request in requests_payload:
        if (
            request.get("status") == "pending"
            and request.get("resource_type") == resource_type
            and request.get("resource_id") == resource_id
            and request.get("action") == action
        ):
            return request
    return None


class SmokeTestResult:
    def __init__(self):
        self.results = []
        self.passed = 0
        self.failed = 0

    def add(self, category, task, method, endpoint, expected_status, actual_status, details=None):
        if isinstance(expected_status, (list, tuple, set)):
            passed = actual_status in expected_status
            expected_payload = list(expected_status)
        else:
            passed = actual_status == expected_status
            expected_payload = expected_status
        result = {
            "category": category,
            "task": task,
            "method": method,
            "endpoint": endpoint,
            "expected_status": expected_payload,
            "actual_status": actual_status,
            "passed": passed,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
        self.results.append(result)
        if result["passed"]:
            self.passed += 1
        else:
            self.failed += 1
        return result["passed"]

    def save(self, filename):
        report = {
            "test_type": "技术冒烟测试（非 Beta 测试）",
            "note": "不包含满意度、愿意继续用等主观反馈",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total": len(self.results),
                "passed": self.passed,
                "failed": self.failed,
                "pass_rate": f"{self.passed / len(self.results) * 100:.1f}%" if self.results else "0%"
            },
            "results": self.results
        }
        output_file = OUTPUT_DIR / filename
        output_file.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\n✅ 报告已保存: {output_file}")
        return report


def test_普通用户任务():
    """普通用户任务清单"""
    result = SmokeTestResult()

    # 准备测试用户 token
    login_response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "demo_user_dept1", "password": "Demo123!"}
    )

    print("\n=== 普通用户任务测试 ===\n")

    # Task 1: 登录
    result.add(
        "认证", "登录", "POST", "/api/auth/login",
        200, login_response.status_code,
        response_details(login_response, {"username": "demo_user_dept1"})
    )

    if login_response.status_code != 200:
        print(f"❌ 登录失败，无法继续测试: {login_response.text}")
        return result.save("普通用户任务_smoke_test.json")

    token = login_response.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Task 2: 查看 profile
    profile_resp = requests.get(f"{BASE_URL}/api/me/profile", headers=headers)
    result.add(
        "认证", "查看 profile", "GET", "/api/me/profile",
        200, profile_resp.status_code,
        response_details(profile_resp)
    )

    # Task 3: 提问 - 知识库问题
    chat_payload = {
        "Id": f"smoke-chat-{int(time.time())}",
        "Question": "CPU 使用率过高怎么办",
        "SelectedKbIds": ["process_digital_dept"],
        "ScopeSource": "user_selected",
    }
    chat_resp = requests.post(
        f"{BASE_URL}/api/chat",
        headers=headers,
        json=chat_payload
    )
    result.add(
        "对话", "知识库问答", "POST", "/api/chat",
        200, chat_resp.status_code,
        response_details(chat_resp, {"payload": chat_payload})
    )

    # Task 4: 查看会话历史
    sessions_resp = requests.get(f"{BASE_URL}/api/chat/sessions", headers=headers)
    result.add(
        "对话", "会话历史", "GET", "/api/chat/sessions",
        200, sessions_resp.status_code,
        response_details(sessions_resp)
    )

    # Task 5: 上传文档
    files = {"file": ("smoke_test.md", b"# Smoke Test\n\nThis is a smoke test document.", "text/markdown")}
    data = {"kb_id": "process_digital_dept"}
    upload_resp = requests.post(
        f"{BASE_URL}/api/upload",
        headers=headers,
        files=files,
        data=data
    )
    result.add(
        "文档", "上传文档", "POST", "/api/upload",
        200, upload_resp.status_code,
        response_details(upload_resp)
    )

    # Task 6: 查看文档列表
    time.sleep(2)  # 等待 indexed
    docs_resp = requests.get(f"{BASE_URL}/api/documents", headers=headers)
    result.add(
        "文档", "文档列表", "GET", "/api/documents",
        200, docs_resp.status_code,
        response_details(docs_resp)
    )

    # Task 7: 查看文档健康度
    if upload_resp.status_code == 200:
        doc_id = upload_resp.json()["data"]["doc_id"]
        time.sleep(3)  # 等待健康检查
        health_resp = requests.get(f"{BASE_URL}/api/documents/{doc_id}/health", headers=headers)
        result.add(
            "文档", "健康检查", "GET", f"/api/documents/{doc_id}/health",
            200, health_resp.status_code,
            response_details(health_resp)
        )

    # Task 8: 查看可申请资源
    resources_resp = requests.get(
        f"{BASE_URL}/api/permission-requests/resources",
        headers=headers,
    )
    result.add(
        "权限", "可申请资源", "GET", "/api/permission-requests/resources",
        200, resources_resp.status_code,
        response_details(resources_resp)
    )

    # Task 9: 申请权限。资源必须来自真实 catalog，不能硬编码不存在的 resource_id。
    perm_req_resp = None
    selected_resource = None
    selected_action = None
    if resources_resp.status_code == 200:
        resources = resources_resp.json().get("data", {}).get("resources", [])
        selected_resource, selected_action = choose_requestable_resource(resources)

    if selected_resource and selected_action:
        permission_payload = {
            "resource_type": selected_resource["resource_type"],
            "resource_id": selected_resource["resource_id"],
            "action": selected_action,
            "reason": "desktop beta smoke test permission request",
        }
        perm_req_resp = requests.post(
            f"{BASE_URL}/api/permission-requests",
            headers=headers,
            json=permission_payload
        )
        if perm_req_resp.status_code == 200:
            permission_request = perm_req_resp.json()["data"]["permission_request"]
            SMOKE_STATE["permission_request_id"] = permission_request["request_id"]
        elif perm_req_resp.status_code == 400:
            pending = find_matching_pending_request(
                headers,
                permission_payload["resource_type"],
                permission_payload["resource_id"],
                permission_payload["action"],
            )
            if pending and perm_req_resp.json().get("detail") == "permission_request_duplicate_pending":
                SMOKE_STATE["permission_request_id"] = pending["request_id"]
    else:
        permission_payload = {"error": "no requestable ungranted resource found"}

    permission_status = perm_req_resp.status_code if perm_req_resp is not None else 409
    permission_expected = [200, 400] if SMOKE_STATE.get("permission_request_id") else 200
    result.add(
        "权限", "申请权限", "POST", "/api/permission-requests",
        permission_expected, permission_status,
        response_details(perm_req_resp, {"payload": permission_payload})
        if perm_req_resp is not None
        else {"payload": permission_payload}
    )

    # Task 10: 查看我的申请
    my_reqs_resp = requests.get(f"{BASE_URL}/api/permission-requests/mine", headers=headers)
    result.add(
        "权限", "我的申请", "GET", "/api/permission-requests/mine",
        200, my_reqs_resp.status_code,
        response_details(my_reqs_resp)
    )

    # Task 11: 登出
    logout_resp = requests.post(f"{BASE_URL}/api/auth/logout", headers=headers)
    result.add(
        "认证", "登出", "POST", "/api/auth/logout",
        200, logout_resp.status_code,
        response_details(logout_resp)
    )

    return result.save("普通用户任务_smoke_test.json")


def test_admin任务():
    """Admin 任务清单"""
    result = SmokeTestResult()

    # 准备 admin token
    login_response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "Admin123!"}
    )

    print("\n=== Admin 任务测试 ===\n")

    # Task 1: 登录
    result.add(
        "认证", "Admin 登录", "POST", "/api/auth/login",
        200, login_response.status_code,
        response_details(login_response)
    )

    if login_response.status_code != 200:
        print(f"❌ Admin 登录失败，无法继续测试: {login_response.text}")
        return result.save("Admin任务_smoke_test.json")

    token = login_response.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Task 2: 用户管理
    users_resp = requests.get(f"{BASE_URL}/api/admin/users", headers=headers)
    result.add(
        "用户管理", "用户列表", "GET", "/api/admin/users",
        200, users_resp.status_code,
        response_details(users_resp)
    )

    # Task 3: 权限申请审批列表
    pending_resp = requests.get(
        f"{BASE_URL}/api/admin/permission-requests",
        headers=headers
    )
    result.add(
        "权限审批", "待审批列表", "GET", "/api/admin/permission-requests",
        200, pending_resp.status_code,
        response_details(pending_resp)
    )

    # Task 4: 审批权限申请
    request_id = SMOKE_STATE.get("permission_request_id")
    if request_id is None and pending_resp.status_code == 200:
        pending_requests = pending_resp.json().get("data", {}).get("permission_requests", [])
        if pending_requests:
            request_id = pending_requests[0]["request_id"]
    approve_status = 404
    approve_details = {"error": "no pending permission request available"}
    if request_id:
        approve_resp = requests.post(
            f"{BASE_URL}/api/admin/permission-requests/{request_id}/approve",
            headers=headers,
            json={"reason": "approved by desktop beta smoke test"},
        )
        approve_status = approve_resp.status_code
        approve_details = response_details(approve_resp, {"request_id": request_id})
    result.add(
        "权限审批", "审批通过", "POST", "/api/admin/permission-requests/{request_id}/approve",
        200, approve_status,
        approve_details
    )

    # Task 5: Audit 日志
    audit_resp = requests.get(f"{BASE_URL}/api/admin/audit", headers=headers)
    result.add(
        "审计", "Audit 日志", "GET", "/api/admin/audit",
        200, audit_resp.status_code,
        response_details(audit_resp)
    )

    # Task 6: Trace 查询
    # 先获取一个 trace_id（从 audit）
    if audit_resp.status_code == 200:
        audit_events = audit_resp.json().get("data", {}).get("events", [])
        if audit_events:
            trace_id = audit_events[0].get("trace_id")
            if trace_id:
                trace_resp = requests.get(f"{BASE_URL}/api/admin/traces/{trace_id}", headers=headers)
                result.add(
                    "可观测", "Trace 查询", "GET", f"/api/admin/traces/{trace_id}",
                    200, trace_resp.status_code,
                    response_details(trace_resp)
                )
            else:
                print("⚠️  Audit 数据中没有 trace_id，跳过 Trace 查询测试")
        else:
            print("⚠️  Audit 数据为空，跳过 Trace 查询测试")

    # Task 7: 数据库 catalog
    catalog_resp = requests.get(f"{BASE_URL}/api/database/catalog", headers=headers)
    result.add(
        "数据库", "Catalog", "GET", "/api/database/catalog",
        200, catalog_resp.status_code,
        response_details(catalog_resp)
    )

    # Task 8: 执行看板静态入口
    dashboard_resp = requests.get(f"{BASE_URL}/static/enterprise-dashboard.html", headers=headers)
    result.add(
        "执行看板", "页面加载", "GET", "/static/enterprise-dashboard.html",
        200, dashboard_resp.status_code,
        response_details(dashboard_resp)
    )

    return result.save("Admin任务_smoke_test.json")


def test_observer任务():
    """观察员任务清单"""
    result = SmokeTestResult()

    # 准备 admin token（代替部门经理，因为 seed 中没有部门经理）
    login_response = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": "admin", "password": "Admin123!"}
    )

    print("\n=== 观察员任务测试 ===\n")

    if login_response.status_code != 200:
        print(f"❌ 登录失败，无法继续测试: {login_response.text}")
        return result.save("观察员任务_smoke_test.json")

    token = login_response.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Task 1: 查看部门列表与资源范围
    members_resp = requests.get(f"{BASE_URL}/api/admin/departments", headers=headers)
    result.add(
        "部门管理", "部门列表", "GET", "/api/admin/departments",
        200, members_resp.status_code,
        response_details(members_resp)
    )

    # Task 2: Shadow metrics
    metrics_resp = requests.get(f"{BASE_URL}/api/shadow-metrics", headers=headers)
    result.add(
        "可观测", "Shadow metrics", "GET", "/api/shadow-metrics",
        200, metrics_resp.status_code,
        response_details(metrics_resp)
    )

    return result.save("观察员任务_smoke_test.json")


if __name__ == "__main__":
    print("=" * 60)
    print("桌面端 Beta 技术冒烟测试")
    print("明确标注：这不是 Beta 测试，是技术验收")
    print("=" * 60)

    # 测试普通用户任务
    report1 = test_普通用户任务()
    print(f"\n普通用户任务: {report1['summary']['passed']}/{report1['summary']['total']} 通过")

    # 测试 Admin 任务
    report2 = test_admin任务()
    print(f"Admin 任务: {report2['summary']['passed']}/{report2['summary']['total']} 通过")

    # 测试观察员任务
    report3 = test_observer任务()
    print(f"观察员任务: {report3['summary']['passed']}/{report3['summary']['total']} 通过")

    # 汇总
    total_passed = report1['summary']['passed'] + report2['summary']['passed'] + report3['summary']['passed']
    total_tests = report1['summary']['total'] + report2['summary']['total'] + report3['summary']['total']

    print("\n" + "=" * 60)
    print(f"总计: {total_passed}/{total_tests} 通过 ({total_passed/total_tests*100:.1f}%)")
    print("=" * 60)
    print("\n注意：此测试仅验证功能可用性（200/404/500）")
    print("不包含满意度、体验评价等主观反馈")
    print("真实 Beta 测试需要真实用户参与")
