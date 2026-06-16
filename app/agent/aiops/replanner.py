"""
Replanner 节点：重新规划或生成最终响应
基于 LangGraph 官方教程实现
"""

from textwrap import dedent
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from langchain_qwq import ChatQwen
from loguru import logger
from pydantic import BaseModel, Field

from app.agent.mcp_client import format_exception_for_infra, get_mcp_tools_with_retry
from app.config import config
from app.tools import get_current_time, retrieve_knowledge

from .state import PlanExecuteState
from .utils import (
    await_with_optional_timeout,
    format_tools_description,
    format_traceback_for_infra,
    invoke_structured_with_fallback,
)


async def _get_aiops_bindable_tools():
    from app.enterprise.aiops.tool_catalog import get_aiops_bindable_tools

    return await get_aiops_bindable_tools(
        local_tools=[get_current_time, retrieve_knowledge],
        mcp_tool_loader=get_mcp_tools_with_retry,
    )


class Response(BaseModel):
    """最终响应的格式"""
    response: str = Field(description="对用户的最终响应")


class Act(BaseModel):
    """重新规划的输出格式"""
    action: str = Field(
        description="""下一步的行动，必须是以下三种之一：
        - 'continue': 当前计划合理，继续执行下一个步骤
        - 'replan': 当前计划需要调整，提供新的步骤列表
        - 'respond': 计划已完成且信息充足，生成最终响应"""
    )
    # action 为 'replan' 时，新的步骤列表（会替换当前剩余计划）
    new_steps: List[str] = Field(
        default_factory=list,
        description="新的步骤列表（如果 action 是 'replan'，这些步骤会替换剩余计划）"
    )


def _merge_infra_error(
    update: Dict[str, Any],
    infra_error_update: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Attach a node-internal infra failure marker to a normal state update."""
    if not infra_error_update:
        return update
    merged = dict(update)
    merged.update(infra_error_update)
    return merged


def _merge_optional_updates(
    update: Dict[str, Any],
    *optional_updates: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Merge optional state fragments into one graph update."""
    merged = dict(update)
    for optional_update in optional_updates:
        if optional_update:
            merged.update(optional_update)
    return merged


def _missing_required_tools(
    required_tools: list[str] | None,
    past_steps: list[tuple],
    executed_tools: list[str] | None = None,
) -> list[str]:
    """Return required tools not yet covered by successful executor calls."""
    required = [tool for tool in required_tools or [] if tool]
    if not required:
        return []

    covered = set(executed_tools or [])
    if executed_tools is None:
        history_text = "\n".join(
            f"{step}\n{result}"
            for step, result in past_steps
        )
        covered = {tool for tool in required if tool in history_text}
    return [tool for tool in required if tool not in covered]


def _required_tool_steps(
    missing_tools: list[str],
    *,
    service_name: str | None,
    scenario: str | None,
) -> list[str]:
    return [
        _required_tool_step(tool, service_name=service_name, scenario=scenario)
        for tool in missing_tools
    ]


def _required_tool_step(
    tool: str,
    *,
    service_name: str | None,
    scenario: str | None,
) -> str:
    service = service_name or "data-sync-service"
    scenario_hint = f"；故障类型为 {scenario}" if scenario else ""
    if tool == "query_active_alerts":
        return (
            "必须调用 query_active_alerts 获取活跃告警；该工具无参数，"
            f"调用后只筛选服务 {service} 和故障类型 {scenario or '目标故障'}。"
        )
    if tool == "query_metric_series":
        return (
            "必须调用 query_metric_series 获取指标证据；"
            f"参数 service_name='{service}', metric_name='{_metric_name_for_scenario(scenario)}'"
            f"{scenario_hint}。"
        )
    if tool == "search_service_logs":
        return (
            "必须调用 search_service_logs 获取原始日志证据；"
            f"参数 service_name='{service}', keyword='{_log_keyword_for_scenario(scenario)}', limit=100"
            f"{scenario_hint}。"
        )
    if tool == "analyze_log_pattern":
        return (
            "必须调用 analyze_log_pattern 汇总日志模式；"
            f"参数 service_name='{service}'{scenario_hint}。"
        )
    if tool == "get_service_info":
        return f"必须调用 get_service_info 获取 CMDB 证据；参数 service_name='{service}'。"
    if tool == "get_recent_deployments":
        return f"必须调用 get_recent_deployments 获取发布证据；参数 service_name='{service}', limit=5。"
    if tool == "search_historical_tickets":
        return (
            "必须调用 search_historical_tickets 获取历史工单证据；"
            f"参数 service_name='{service}', alert_name='{scenario or ''}', limit=5。"
        )
    if tool == "list_service_dependencies":
        return f"必须调用 list_service_dependencies 获取依赖证据；参数 service_name='{service}'。"
    return f"必须调用 {tool} 获取 AIOps required-tool 证据。"


def _metric_name_for_scenario(scenario: str | None) -> str:
    normalized = "".join(ch for ch in str(scenario or "").lower() if ch.isalnum())
    if normalized == "dbslowquery":
        return "mysql_query_latency_seconds"
    if normalized == "redisqueuebacklog":
        return "redis_queue_length"
    return "service_cpu_percent"


def _log_keyword_for_scenario(scenario: str | None) -> str:
    normalized = "".join(ch for ch in str(scenario or "").lower() if ch.isalnum())
    if normalized == "dbslowquery":
        return "slow_query"
    if normalized == "redisqueuebacklog":
        return "redis_backlog"
    return "cpu"


# Replanner 提示词
replanner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent("""
                作为一个重新规划专家，你需要根据已执行的步骤决定下一步行动。

                可用工具列表（用于制定计划时参考）：

                {tools_description}

                注意：你的职责是制定或调整计划，实际的工具调用由 Executor 负责执行。

                你有三个选择（按优先级排序）：

                **1. 'respond' - 信息充足，立即生成最终响应** 【最高优先级】
                   - 使用场景：当前信息已经足够回答用户问题
                   - 决策标准：
                     * 已执行步骤 >= 3 且获取了关键信息
                     * 或者已执行步骤 >= 5（无论结果如何）
                     * 或者当前信息完全满足任务需求
                   - ⚠️ 不要等到"完美"才响应，"足够好"就应该立即 respond

                **2. 'continue' - 当前计划合理，继续执行** 【次优先级】
                   - 使用场景：剩余计划合理且必要
                   - 决策标准：剩余步骤确实能提供关键信息
                   - ⚠️ 如果剩余步骤不是"必需"的，应选择 respond

                **3. 'replan' - 当前计划有严重问题** 【最低优先级，谨慎使用】
                   - 使用场景：原计划明显错误或遗漏关键步骤
                   - ⚠️ **严格限制**：
                     * 新步骤数量必须 <= 当前剩余步骤数
                     * 优先简化计划，不要添加不必要的步骤
                     * 总步骤数已执行 >= 5 次时，禁止 replan，只能 respond

                评估标准：
                - 当前信息是否已经足够解决用户问题？【最关键】
                - 已执行步骤是否成功获取了核心信息？
                - 剩余步骤是否真的"必需"？
                - 已执行步骤数是否过多（>= 5）？如果是，立即 respond

                **决策优先级口诀：** 
                "优先结束 > 保持不变 > 调整计划"
                "信息足够就响应，不要追求完美"
            """).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)

# 最终响应生成提示词
response_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent("""
                根据原始任务和已执行步骤的结果，生成一个全面的最终响应。

                响应要求：
                - 清晰、结构化
                - 基于实际数据，不要编造
                - 如果某些步骤失败，要诚实说明
                - 使用 Markdown 格式
            """).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


async def replanner(state: PlanExecuteState) -> Dict[str, Any]:
    """
    重新规划节点：决定是继续、调整计划还是生成最终响应

    三种决策：
    1. continue - 继续执行当前计划
    2. replan - 调整计划（替换剩余步骤）
    3. respond - 生成最终响应
    """
    logger.info("=== Replanner：重新规划 ===")

    input_text = state.get("input", "")
    plan = state.get("plan", [])
    past_steps = state.get("past_steps", [])
    required_tools = state.get("aiops_required_tools") or []
    executed_tools = state.get("aiops_executed_tools") or []
    aiops_service_name = state.get("aiops_service_name")
    aiops_scenario = state.get("aiops_scenario")
    eval_node_timeout_seconds = state.get("eval_node_timeout_seconds")
    eval_deadline_monotonic = state.get("eval_deadline_monotonic")
    infra_error_update = None

    logger.info(f"剩余计划步骤: {len(plan)}")
    logger.info(f"已执行步骤: {len(past_steps)}")

    # ⚠️ 强制限制：如果已执行步骤过多，直接生成响应。
    # eval_max_steps 只由评估链路传入；生产场景如有 required tools，
    # 默认上限随 required tool 数量扩展，避免还没覆盖就过早结束。
    max_steps = state.get("eval_max_steps") or max(8, len(required_tools) + 2)
    if len(past_steps) >= max_steps:
        logger.warning(f"已执行 {len(past_steps)} 个步骤，超过最大限制 {max_steps}，强制生成最终响应")
        llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_api_base,
            temperature=0
        )
        return await _generate_response(state, llm, eval_node_timeout_seconds)

    missing_required_tools = _missing_required_tools(
        required_tools,
        past_steps,
        executed_tools,
    )
    if missing_required_tools:
        forced_steps = _required_tool_steps(
            missing_required_tools,
            service_name=aiops_service_name,
            scenario=aiops_scenario,
        )
        logger.info(
            "AIOps required tools not covered yet, forcing remaining steps: {}",
            missing_required_tools,
        )
        return {"plan": forced_steps}

    # 获取可用工具列表
    try:
        all_tools = await await_with_optional_timeout(
            _get_aiops_bindable_tools(),
            eval_node_timeout_seconds,
            "replanner get_tools",
            eval_deadline_monotonic=eval_deadline_monotonic,
        )
        logger.info(f"可用工具数量: {len(all_tools)}")

        # 格式化工具描述
        tools_description = format_tools_description(all_tools)
    except Exception as e:
        error_message = format_exception_for_infra(e)
        logger.warning(f"获取工具列表失败: {error_message}")
        tools_description = "无法获取工具列表"
        infra_error_update = {
            "infra_error": True,
            "infra_error_stage": "replanner",
            "infra_error_message": f"get_tools failed: {error_message}",
            "infra_error_traceback": format_traceback_for_infra(e),
        }

    # 创建 LLM
    llm = ChatQwen(
        model=config.rag_model,
        api_key=config.dashscope_api_key,
        base_url=config.dashscope_api_base,
        temperature=0
    )

    # 格式化已执行的步骤
    steps_summary = "\n".join([
        f"步骤: {step}\n结果: {result[:300]}..."
        for step, result in past_steps
    ])

    # 如果还有剩余计划，进行决策
    if plan:
        logger.info("还有剩余计划，评估下一步行动")

        replanner_chain = replanner_prompt | llm.with_structured_output(Act)
        replanner_json_chain = replanner_prompt | llm.with_structured_output(
            Act,
            method="json_mode",
        )
        structured_output_update: Dict[str, Any] = {}

        try:
            messages = [
                ("user", f"原始任务: {input_text}"),
                ("user", f"已执行的步骤:\n{steps_summary}"),
                ("user", f"剩余计划: {', '.join(plan)}"),
                ("user", f"⚠️ 重要提示：已执行 {len(past_steps)} 个步骤，请优先考虑是否信息已足够生成响应（respond）")
            ]

            replanner_payload = {
                "messages": messages,
                "tools_description": tools_description
            }
            replanner_json_payload = {
                **replanner_payload,
                "messages": messages + [
                    (
                        "user",
                        '请只输出合法 JSON，格式为 {"action":"respond","new_steps":[]}。'
                        "action 只能是 continue、replan、respond。",
                    )
                ],
            }
            act, structured_output_update = await invoke_structured_with_fallback(
                replanner_chain,
                replanner_json_chain,
                replanner_payload,
                stage="replanner",
                fallback_payload=replanner_json_payload,
                timeout_seconds=eval_node_timeout_seconds,
                eval_deadline_monotonic=eval_deadline_monotonic,
                return_diagnostics=True,
            )
            structured_output_update = {
                key: value
                for key, value in structured_output_update.items()
                if value is not None
            }

            # 处理返回结果
            if isinstance(act, Act):
                action = act.action
                new_steps = act.new_steps
            elif isinstance(act, dict):
                # 如果返回的是字典
                action = act.get("action", "continue")
                new_steps = act.get("new_steps", [])
            else:
                raise TypeError(f"replanner structured output has unexpected type: {type(act).__name__}")

            if action not in {"continue", "replan", "respond"}:
                raise ValueError(f"replanner returned invalid action: {action}")

            logger.info(f"Replanner 决策: {action}")

            if action == "respond":
                logger.info("决定生成最终响应")
                response_update = await _generate_response(state, llm, eval_node_timeout_seconds)
                return _merge_optional_updates(
                    _merge_infra_error(response_update, infra_error_update),
                    structured_output_update,
                )

            elif action == "replan":
                # ⚠️ 强制限制：新步骤数不能超过当前剩余步骤数
                if len(new_steps) > len(plan):
                    logger.warning(
                        f"新步骤数 {len(new_steps)} > 剩余步骤数 {len(plan)}，"
                        f"强制截断为 {len(plan)} 个步骤"
                    )
                    new_steps = new_steps[:len(plan)]
                
                # ⚠️ 二次检查：如果已执行步骤 >= 5，禁止 replan
                if len(past_steps) >= 5:
                    logger.warning(f"已执行 {len(past_steps)} 个步骤，禁止重新规划，强制生成响应")
                    response_update = await _generate_response(state, llm, eval_node_timeout_seconds)
                    return _merge_optional_updates(
                        _merge_infra_error(response_update, infra_error_update),
                        structured_output_update,
                    )
                
                logger.info(f"决定调整计划，新步骤数量: {len(new_steps)}")
                if new_steps:
                    # 替换剩余计划
                    return _merge_optional_updates(
                        _merge_infra_error({"plan": new_steps}, infra_error_update),
                        structured_output_update,
                    )
                else:
                    logger.warning("replan 但未提供新步骤，继续执行原计划")
                    return _merge_optional_updates(
                        _merge_infra_error({}, infra_error_update),
                        structured_output_update,
                    )

            else:  # action == "continue"
                logger.info("决定继续执行当前计划")
                return _merge_optional_updates(
                    _merge_infra_error({}, infra_error_update),
                    structured_output_update,
                )  # 不修改状态，继续执行

        except Exception as e:
            error_message = format_exception_for_infra(e)
            logger.error(f"重新规划失败: {error_message}, 继续执行剩余计划")
            return _merge_optional_updates(
                _merge_infra_error(
                    {},
                    {
                        "infra_error": True,
                        "infra_error_stage": "replanner",
                        "infra_error_message": error_message,
                        "infra_error_traceback": format_traceback_for_infra(e),
                    },
                ),
                structured_output_update,
            )

    else:
        # 没有剩余计划，生成最终响应
        logger.info("计划已执行完毕，生成最终响应")
        response_update = await _generate_response(state, llm, eval_node_timeout_seconds)
        return _merge_infra_error(response_update, infra_error_update)


async def _generate_response(
    state: PlanExecuteState,
    llm: ChatQwen,
    timeout_seconds: float | None = None,
) -> Dict[str, Any]:
    """生成最终响应"""
    logger.info("生成最终响应...")

    input_text = state.get("input", "")
    past_steps = state.get("past_steps", [])
    eval_deadline_monotonic = state.get("eval_deadline_monotonic")

    # 格式化执行历史
    execution_history = "\n\n".join([
        f"### 步骤: {step}\n**结果:**\n{result}"
        for step, result in past_steps
    ])

    response_gen = response_prompt | llm.with_structured_output(Response)
    response_json_gen = response_prompt | llm.with_structured_output(
        Response,
        method="json_mode",
    )

    try:
        messages = [
            ("user", f"原始任务: {input_text}"),
            ("user", f"执行历史:\n{execution_history}"),
            ("user", "请基于以上信息生成全面的最终响应")
        ]

        response_payload = {"messages": messages}
        response_json_payload = {
            "messages": messages + [
                ("user", '请只输出合法 JSON，格式为 {"response":"最终响应 Markdown 文本"}。')
            ]
        }
        response_obj = await invoke_structured_with_fallback(
            response_gen,
            response_json_gen,
            response_payload,
            stage="response",
            fallback_payload=response_json_payload,
            timeout_seconds=timeout_seconds,
            eval_deadline_monotonic=eval_deadline_monotonic,
        )

        # 处理返回结果
        if isinstance(response_obj, Response):
            final_response = response_obj.response
        elif isinstance(response_obj, dict):
            # 如果返回的是字典
            final_response = response_obj.get("response", "")
        else:
            raise TypeError(f"response structured output has unexpected type: {type(response_obj).__name__}")

        logger.info(f"最终响应生成完成，长度: {len(final_response)}")

        return {"response": final_response}

    except Exception as e:
        error_message = format_exception_for_infra(e)
        logger.error(f"生成响应失败: {error_message}")
        # 生成简单的后备响应
        fallback_response = f"""# 任务执行结果

## 原始任务
{input_text}

## 执行的步骤
{_format_simple_steps(past_steps)}

## 说明
由于系统异常，无法生成完整响应。以上是已收集的信息。
"""
        return {
            "response": fallback_response,
            "infra_error": True,
            "infra_error_stage": "replanner",
            "infra_error_message": f"generate_response failed: {error_message}",
            "infra_error_traceback": format_traceback_for_infra(e),
        }


def _format_simple_steps(past_steps: list) -> str:
    """格式化步骤列表（简单版）"""
    if not past_steps:
        return "无"

    formatted = []
    for i, (step, result) in enumerate(past_steps, 1):
        result_preview = result[:200] + "..." if len(result) > 200 else result
        formatted.append(f"{i}. **{step}**\n   {result_preview}\n")

    return "\n".join(formatted)
