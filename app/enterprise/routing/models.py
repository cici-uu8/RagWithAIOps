"""Models for Enterprise 2.0 F3 strategy routing shadow."""

from typing import Any, Literal

from pydantic import BaseModel, Field

RouteName = Literal["chat", "rag", "aiops", "database", "admin", "human_review"]
RoutingProviderName = Literal["rules", "classifier", "llm_shadow"]
RoutingRiskLevel = Literal["low", "medium", "high"]


class RoutingDecision(BaseModel):
    route: RouteName
    provider: RoutingProviderName
    reason: str
    risk_level: RoutingRiskLevel = "low"
    required_capabilities: list[str] = Field(default_factory=list)
    fallback_route: RouteName | None = "chat"
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoutingConfusionCase(BaseModel):
    trace_id: str
    request_id: str
    actual_route: str
    suggested_route: str
    provider: str
    reason: str


class RoutingComparisonReport(BaseModel):
    total_decisions: int
    matched_decisions: int
    match_rate: float
    confusion_cases: list[RoutingConfusionCase] = Field(default_factory=list)
    risk_mistakes: list[RoutingConfusionCase] = Field(default_factory=list)
