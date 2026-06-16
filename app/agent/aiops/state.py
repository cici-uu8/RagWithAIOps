"""
通用 Plan-Execute-Replan 状态定义
基于 LangGraph 官方教程实现
"""

import operator
from typing import Annotated, Any, TypedDict


class PlanExecuteState(TypedDict, total=False):
    """Plan-Execute-Replan 状态"""

    # 用户输入（任务描述）
    input: str

    # 会话 ID（用于 session-scoped memory/offload）
    session_id: str

    # 执行计划（步骤列表）
    plan: list[str]

    # 已执行的步骤历史
    # 使用 operator.add 实现追加式更新（而非覆盖）
    past_steps: Annotated[list[tuple], operator.add]

    # 最终响应/报告
    response: str

    # P5 memory guidance 相关字段
    # memory_mode: "off" | "shadow" | "active" (默认 "off")
    memory_mode: str | None

    # 兼容旧 API 的 bool flag (优先级低于 memory_mode)
    enable_memory_guidance: bool | None

    # Memory owner ID
    memory_owner_id: str | None

    # Enterprise 2.0 F1 task contract id. Observability-only in F1; planner,
    # executor and replanner routing stay unchanged.
    task_contract_id: str | None

    # Memory observation trace (planner 返回)
    memory_observation: dict[str, Any] | None

    # Custom memory store path (用于 eval，None 则使用默认全局 store)
    memory_store_path: str | None

    # Eval-only execution cap. Production flows leave this unset.
    eval_max_steps: int | None

    # Eval-only per-node timeout. Production flows leave this unset.
    eval_node_timeout_seconds: float | None

    # Eval-only timeout for executor final LLM synthesis after tool results.
    # This call can be slower than tool selection because it receives tool output.
    eval_executor_final_timeout_seconds: float | None

    # Eval-only absolute sample deadline from time.monotonic().
    # Production flows leave this unset.
    eval_deadline_monotonic: float | None

    # Infra failure marker for eval/reporting. Nodes may continue with a
    # fallback, but eval must still know that the run is not behavior-valid.
    infra_error: bool | None
    infra_error_stage: str | None
    infra_error_message: str | None
    infra_error_traceback: str | None

    # Runtime AIOps required-tool coverage guard. `aiops_required_tools` is
    # set by the API service after catalog validation; executor appends
    # successfully invoked tools so replanner cannot finish before coverage.
    aiops_scenario: str | None
    aiops_service_name: str | None
    aiops_required_tools: list[str] | None
    aiops_executed_tools: Annotated[list[str], operator.add]

    # Recovered structured-output fallback metadata. These fields are
    # observability-only and do not change node routing or fallback behavior.
    structured_output_recovered: bool | None
    structured_output_fallback_used: bool | None
    structured_output_primary_error: str | None
    structured_output_primary_error_type: str | None
    structured_output_primary_stage: str | None
    structured_output_fallback_stage: str | None
    structured_output_total_elapsed_ms: float | None
