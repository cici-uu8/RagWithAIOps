"""Deterministic plan verifier for task contracts."""

from __future__ import annotations

import re
from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.verifiers.base import BaseVerifier
from app.enterprise.verifiers.models import (
    VerificationFinding,
    VerificationResult,
    VerificationStatus,
)


class PlanVerifier(BaseVerifier):
    name = "PlanVerifier"

    def __init__(self, *, max_steps: int = 8):
        self.max_steps = max(1, max_steps)

    def verify(self, context: RequestContext, payload: dict[str, Any]) -> VerificationResult:
        del context
        plan = _normalize_plan(payload.get("plan"))
        contract = payload.get("task_contract") or {}
        allowed_tools = set(_contract_list(contract, "scope", "allowed_tools"))
        allowed_data_sources = set(_contract_list(contract, "scope", "allowed_data_sources"))
        forbidden_actions = _contract_list(contract, "scope", "forbidden_actions")

        findings: list[VerificationFinding] = []
        if not plan:
            findings.append(
                self._finding("plan_missing", "计划为空，无法验证任务合同覆盖。")
            )

        if len(plan) > self.max_steps:
            findings.append(
                self._finding(
                    "plan_too_many_steps",
                    "计划步骤数超过自检上限。",
                    metadata={"step_count": len(plan), "max_steps": self.max_steps},
                )
            )

        plan_text = "\n".join(plan).lower()
        for action in forbidden_actions:
            if action and action.lower() in plan_text:
                findings.append(
                    self._finding(
                        "plan_forbidden_action",
                        "计划包含任务合同禁止的动作。",
                        metadata={"forbidden_action": action},
                    )
                )

        for tool_id in _extract_scope_refs(plan, {"tool", "use_tool"}):
            if allowed_tools and tool_id not in allowed_tools:
                findings.append(
                    self._finding(
                        "plan_tool_out_of_scope",
                        "计划使用了任务合同未授权的工具。",
                        metadata={"tool_id": tool_id, "allowed_tools": sorted(allowed_tools)},
                    )
                )

        for data_source in _extract_scope_refs(plan, {"source", "data_source"}):
            if allowed_data_sources and data_source not in allowed_data_sources:
                findings.append(
                    self._finding(
                        "plan_data_source_out_of_scope",
                        "计划使用了任务合同未授权的数据源。",
                        metadata={
                            "data_source": data_source,
                            "allowed_data_sources": sorted(allowed_data_sources),
                        },
                    )
                )

        if not findings:
            return self._result(
                VerificationStatus.PASSED,
                metadata={"step_count": len(plan), "max_steps": self.max_steps},
            )

        hard_failure_codes = {
            "plan_missing",
            "plan_forbidden_action",
            "plan_tool_out_of_scope",
            "plan_data_source_out_of_scope",
        }
        status = (
            VerificationStatus.FAILED
            if any(finding.code in hard_failure_codes for finding in findings)
            else VerificationStatus.NEEDS_REVISION
        )
        return self._result(
            status,
            findings,
            metadata={"step_count": len(plan), "max_steps": self.max_steps},
        )


def _normalize_plan(plan: Any) -> list[str]:
    if plan is None:
        return []
    if isinstance(plan, str):
        return [plan] if plan.strip() else []
    normalized: list[str] = []
    if isinstance(plan, list):
        for item in plan:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = " ".join(
                    str(item.get(key, ""))
                    for key in ("step", "description", "tool", "tool_id", "data_source")
                    if item.get(key)
                ).strip()
            else:
                text = str(item).strip()
            if text:
                normalized.append(text)
    return normalized


def _contract_list(contract: Any, *path: str) -> list[str]:
    value = contract
    for part in path:
        if value is None:
            return []
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
    if value is None:
        return []
    return [str(item) for item in value]


def _extract_scope_refs(plan: list[str], prefixes: set[str]) -> set[str]:
    refs: set[str] = set()
    pattern = re.compile(r"\b(?P<prefix>[a-zA-Z_]+)\s*[:=]\s*(?P<value>[a-zA-Z0-9_.-]+)")
    for step in plan:
        for match in pattern.finditer(step):
            if match.group("prefix") in prefixes:
                refs.add(match.group("value"))
    return refs
