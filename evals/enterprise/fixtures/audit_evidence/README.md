---
feature_ids:
  - agent-eval-gate-scorecard
  - audit-evidence-verifier
topics:
  - audit-evidence
  - enterprise-eval
  - offline-gate
doc_kind: fixture_readme
created: 2026-07-07
status: offline_fixture
---

# Audit Evidence Gate Fixtures

这个目录给 `G-P0-AUDIT-EVIDENCE` 离线 gate 提供最小可读样例。
它不是生产审计数据，也不会接入运行链路。

## Passing Example

```bash
uv run python -m evals.enterprise.run_audit_evidence_gate \
  --audit-events evals/enterprise/fixtures/audit_evidence/pass_events.jsonl \
  --output-dir /tmp/audit_evidence_gate_reports
```

预期结果：

- exit code: `0`
- `passed=true`
- `findings=0`

## Failing Example

```bash
uv run python -m evals.enterprise.run_audit_evidence_gate \
  --audit-events evals/enterprise/fixtures/audit_evidence/fail_missing_evidence.json \
  --output-dir /tmp/audit_evidence_gate_reports
```

预期结果：

- exit code: `1`
- `passed=false`
- finding codes 包含 `audit_request_id_missing`、`audit_reason_missing`、`audit_metadata_missing`

## 样例覆盖

`pass_events.jsonl` 覆盖完整证据链：

- `permission_checked`
- `tool_call`
- `database_operation_executed`
- `human_review_rejected`
- `verification_result`

`fail_missing_evidence.json` 覆盖常见缺口：

- 阻断类事件缺 `request_id`
- 阻断类事件缺 `reason`
- 权限检查缺 `metadata.resource_id` / `metadata.action`
