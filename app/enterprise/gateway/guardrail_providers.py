"""Guardrail provider implementations for E2."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from app.enterprise.gateway.models import GatewayRequest, GuardrailDecision


class NoOpGuardrailProvider:
    async def evaluate(self, _request: GatewayRequest) -> GuardrailDecision:
        return GuardrailDecision()


@dataclass(frozen=True)
class GuardrailRule:
    pattern: str
    pattern_type: Literal["keyword", "regex"] = "keyword"
    reason: str = "Request blocked by guardrail"
    rule_id: str | None = None


class RuleGuardrailProvider:
    def __init__(self, rules: Iterable[GuardrailRule]):
        self.rules = list(rules)

    @classmethod
    def from_keywords(
        cls,
        keywords: Iterable[str],
        *,
        reason: str = "Request blocked by guardrail",
    ) -> RuleGuardrailProvider:
        return cls(
            GuardrailRule(
                pattern=keyword,
                pattern_type="keyword",
                reason=reason,
                rule_id=f"keyword:{keyword}",
            )
            for keyword in keywords
        )

    async def evaluate(self, request: GatewayRequest) -> GuardrailDecision:
        text = self._payload_text(request.payload)
        for rule in self.rules:
            if self._matches(rule, text):
                return GuardrailDecision(
                    allowed=False,
                    decision="blocked",
                    reason=rule.reason,
                    rule_id=rule.rule_id or rule.pattern,
                )
        return GuardrailDecision()

    def _payload_text(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _matches(self, rule: GuardrailRule, text: str) -> bool:
        if rule.pattern_type == "keyword":
            return rule.pattern in text
        return re.search(rule.pattern, text) is not None
