"""
Executor 节点：执行单个步骤
基于 LangGraph 官方教程实现
"""

from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_qwq import ChatQwen
from langgraph.prebuilt import ToolNode
from loguru import logger

from app.agent.mcp_client import format_exception_for_infra, get_mcp_tools_with_retry
from app.config import config
from app.services.session_memory_store import SessionToolResultOffloadStore
from app.tools import get_current_time, retrieve_knowledge

from .state import PlanExecuteState
from .utils import await_with_optional_timeout, format_traceback_for_infra


async def _get_aiops_bindable_tools():
    from app.enterprise.aiops.tool_catalog import get_aiops_bindable_tools

    return await get_aiops_bindable_tools(
        local_tools=[get_current_time, retrieve_knowledge],
        mcp_tool_loader=get_mcp_tools_with_retry,
    )


def _extract_tool_messages(tool_node_output: Any) -> List[Any]:
    """Normalize ToolNode output and fail clearly when its shape is unexpected."""
    if isinstance(tool_node_output, dict):
        messages = tool_node_output.get("messages")
        if isinstance(messages, list):
            return messages
        keys = ", ".join(sorted(str(key) for key in tool_node_output.keys()))
        raise ValueError(f"ToolNode returned no messages list; keys=[{keys}]")

    if isinstance(tool_node_output, list):
        return tool_node_output

    raise TypeError(f"ToolNode returned unexpected type: {type(tool_node_output).__name__}")


def _extract_tool_call_names(tool_calls: Any) -> list[str]:
    names: list[str] = []
    for tool_call in tool_calls or []:
        if isinstance(tool_call, dict):
            name = tool_call.get("name")
        else:
            name = getattr(tool_call, "name", None)
        if name:
            names.append(str(name))
    return names


def maybe_offload_aiops_step_result(
    *,
    state: PlanExecuteState,
    task: str,
    result: str,
) -> str:
    """Store long executor result out-of-prompt while keeping state JSON-safe."""
    if not getattr(config, "tool_result_offload_enabled", False):
        return result

    threshold = _positive_int_config("tool_result_offload_threshold", 2000)
    if threshold <= 0 or len(result) <= threshold:
        return result

    session_id = str(state.get("session_id") or "").strip()
    owner_id = str(state.get("memory_owner_id") or "").strip()
    if not session_id or not owner_id:
        logger.warning("AIOps tool result offload 缺少 session_id/memory_owner_id，保留原文")
        return result

    max_bytes = _positive_int_config("tool_result_offload_max_bytes", 200000)
    if len(result.encode("utf-8")) > max_bytes:
        logger.warning(
            "AIOps tool result 超过 offload 单条上限({} bytes)，保留原文",
            max_bytes,
        )
        return result

    store = SessionToolResultOffloadStore(state.get("memory_store_path"))
    _cleanup_tool_result_offloads(store, owner_id=owner_id)
    summary = _summarize_tool_result_for_prompt(result)
    try:
        ref = store.offload_result(
            session_id=session_id,
            owner_id=owner_id,
            tool_name="aiops_step_result",
            content=result,
            summary=summary,
            metadata={"task": task},
        )
    except Exception as exc:  # pragma: no cover - degraded fallback only
        logger.warning("AIOps tool result offload 写入失败，保留原文: {}", exc)
        return result

    return f"{summary}\n... [完整工具结果已 offload: {ref.result_ref}]"


def _cleanup_tool_result_offloads(
    store: SessionToolResultOffloadStore,
    *,
    owner_id: str,
) -> None:
    ttl_days = _positive_int_config("tool_result_offload_ttl_days", 7)
    try:
        store.cleanup_expired(ttl_seconds=ttl_days * 86400, owner_id=owner_id)
    except Exception as exc:  # pragma: no cover - degraded fallback only
        logger.warning("AIOps tool result offload 清理失败，继续执行: {}", exc)


def _summarize_tool_result_for_prompt(result: str) -> str:
    summary = result.strip()
    if len(summary) <= 500:
        return summary
    return f"{summary[:488].rstrip()}\n[已截断]"


def _positive_int_config(name: str, default: int) -> int:
    try:
        parsed = int(getattr(config, name, default))
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


async def executor(state: PlanExecuteState) -> Dict[str, Any]:
    """
    执行节点：执行计划中的下一个步骤
    
    使用 LangGraph 的 ToolNode 自动处理工具调用
    """
    logger.info("=== Executor：执行步骤 ===")

    plan = state.get("plan", [])
    eval_node_timeout_seconds = state.get("eval_node_timeout_seconds")
    eval_executor_final_timeout_seconds = state.get("eval_executor_final_timeout_seconds")
    if eval_executor_final_timeout_seconds is None:
        eval_executor_final_timeout_seconds = eval_node_timeout_seconds
    eval_deadline_monotonic = state.get("eval_deadline_monotonic")

    # 如果计划为空，不执行
    if not plan:
        logger.info("计划为空，跳过执行")
        return {}

    # 取出第一个步骤
    task = plan[0]
    logger.info(f"当前任务: {task}")

    try:
        all_tools = await await_with_optional_timeout(
            _get_aiops_bindable_tools(),
            eval_node_timeout_seconds,
            "executor get_tools",
            eval_deadline_monotonic=eval_deadline_monotonic,
        )
        logger.info(f"可用工具数量: {len(all_tools)}")

        # 创建 LLM（绑定工具）
        llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_api_base,
            temperature=0
        )
        llm_with_tools = llm.bind_tools(all_tools)

        # 创建工具节点（自动执行工具调用）
        tool_node = ToolNode(all_tools)

        # 构建消息（只包含当前步骤，避免原始任务干扰）
        messages = [
            SystemMessage(content="""你是一个能力强大的助手，负责执行具体的任务步骤。

你可以使用各种工具来完成任务。对于每个步骤：
1. 理解步骤的目标
2. 选择合适的工具，如果已经指定了工具，则使用指定的工具
3. 调用工具获取信息
4. 返回执行结果

注意：
- 如果工具调用失败，请说明失败原因
- 不要编造数据，只返回实际获取的信息
- 执行结果要清晰、准确
- 专注于当前步骤，不要考虑其他任务"""),
            HumanMessage(content=f"请执行以下任务: {task}")
        ]

        # 第一步：LLM 决定是否调用工具
        llm_response = await await_with_optional_timeout(
            llm_with_tools.ainvoke(messages),
            eval_node_timeout_seconds,
            "executor llm tool selection",
            eval_deadline_monotonic=eval_deadline_monotonic,
        )
        logger.info(f"LLM 响应类型: {type(llm_response)}")

        # 第二步：如果有工具调用，执行工具
        tool_call_names: list[str] = []
        if hasattr(llm_response, "tool_calls") and llm_response.tool_calls:
            logger.info(f"检测到 {len(llm_response.tool_calls)} 个工具调用")
            tool_call_names = _extract_tool_call_names(llm_response.tool_calls)
            
            # 使用 ToolNode 自动执行工具
            messages.append(llm_response)
            tool_messages = await await_with_optional_timeout(
                tool_node.ainvoke({"messages": messages}),
                eval_node_timeout_seconds,
                "executor tool invocation",
                eval_deadline_monotonic=eval_deadline_monotonic,
            )
            
            # 第三步：将工具结果返回给 LLM 生成最终答案
            messages.extend(_extract_tool_messages(tool_messages))
            final_response = await await_with_optional_timeout(
                llm_with_tools.ainvoke(messages),
                eval_executor_final_timeout_seconds,
                "executor final llm response",
                eval_deadline_monotonic=eval_deadline_monotonic,
            )
            result = final_response.content if hasattr(final_response, 'content') else str(final_response)
        else:
            # 没有工具调用，直接使用 LLM 的输出
            logger.info("LLM 未调用工具，直接返回结果")
            result = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)

        logger.info(f"步骤执行完成，结果长度: {len(result)}")
        result_for_state = maybe_offload_aiops_step_result(
            state=state,
            task=task,
            result=str(result),
        )

        # 返回更新：移除已执行的步骤，添加执行历史
        return {
            "plan": plan[1:],  # 移除第一个步骤
            "past_steps": [(task, result_for_state)],  # 使用 operator.add 追加
            "aiops_executed_tools": tool_call_names,
        }

    except Exception as e:
        error_message = format_exception_for_infra(e)
        logger.error(f"执行步骤失败: {error_message}", exc_info=True)
        return {
            "plan": plan[1:],
            "past_steps": [(task, f"执行失败: {error_message}")],
            "infra_error": True,
            "infra_error_stage": "executor",
            "infra_error_message": error_message,
            "infra_error_traceback": format_traceback_for_infra(e),
        }
