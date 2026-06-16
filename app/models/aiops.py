"""AIOps 请求和响应模型."""

from typing import Any

from pydantic import BaseModel, Field


class AIOpsTaskScope(BaseModel):
    """复杂 AIOps 任务的合同范围."""

    allowed_data_sources: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)


class AIOpsTaskContractInput(BaseModel):
    """复杂 AIOps 请求显式传入的任务合同."""

    user_goal: str | None = None
    scope: AIOpsTaskScope = Field(default_factory=AIOpsTaskScope)
    success_criteria: list[str] = Field(default_factory=list)
    risk_level: str = "low"
    requires_human_approval: bool = False
    latency_budget_ms: int = 30000
    cost_budget: dict[str, Any] | None = None
    expected_outputs: list[str] = Field(default_factory=list)
    task_id: str | None = Field(
        default=None,
        description="F6 human-review resume task id",
    )
    review_id: str | None = Field(
        default=None,
        description="F6 human-review approval id",
    )


class AIOpsRequest(BaseModel):
    """AIOps 诊断请求"""

    session_id: str | None = Field(
        default="default",
        description="会话ID，用于追踪诊断历史"
    )

    # P5 memory mode (优先于 enable_memory_guidance)
    memory_mode: str | None = Field(
        default=None,
        description="Memory 模式: 'off' | 'shadow' | 'active' (默认 None，由 enable_memory_guidance 决定)"
    )

    # P5 memory guidance flags (兼容旧 API，优先级低于 memory_mode)
    enable_memory_guidance: bool = Field(
        default=False,
        description="是否启用 memory guidance（P5 默认关闭，优先级低于 memory_mode）"
    )

    memory_owner_id: str = Field(
        default="default",
        description="Memory owner ID，用于多租户隔离"
    )

    query: str | None = Field(
        default=None,
        description="可选自定义诊断任务描述；为空时使用默认 AIOps 模板",
    )

    task_contract: AIOpsTaskContractInput | None = Field(
        default=None,
        description="复杂任务显式 task contract；为空时保持普通 AIOps 路径",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "session-123",
                "memory_mode": "shadow",
                "enable_memory_guidance": False,
                "memory_owner_id": "default",
                "task_contract": {
                    "user_goal": "诊断当前系统告警并生成报告",
                    "scope": {
                        "allowed_data_sources": ["kb-prod-runbook"],
                        "allowed_tools": ["retrieve_knowledge", "get_current_time"],
                        "forbidden_actions": ["restart_service"],
                    },
                    "success_criteria": ["说明告警现象", "列出证据来源"],
                    "risk_level": "medium",
                    "requires_human_approval": False,
                    "expected_outputs": ["diagnostic_report"],
                },
            }
        }


class AlertInfo(BaseModel):
    """告警信息"""
    alertname: str
    severity: str
    instance: str
    duration: str
    description: str | None = None


class DiagnosisResponse(BaseModel):
    """诊断响应（非流式）"""

    code: int = 200
    message: str = "success"
    data: dict[str, Any]

    class Config:
        json_schema_extra = {
            "example": {
                "code": 200,
                "message": "success",
                "data": {
                    "status": "completed",
                    "target_alert": {
                        "alertname": "HighCPUUsage",
                        "severity": "critical"
                    },
                    "diagnosis": {
                        "root_cause": "数据库连接池耗尽",
                        "recommendations": ["扩容数据库连接池", "优化SQL查询"]
                    }
                }
            }
        }
