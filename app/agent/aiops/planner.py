"""
Planner 节点：制定执行计划
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
from app.services.memory_guidance_provider import memory_guidance_provider
from app.services.memory_guidance_service import MemoryGuidanceService
from app.services.memory_trace_service import MemoryTraceService
from app.tools import get_current_time, retrieve_knowledge

from .state import PlanExecuteState
from .utils import (
    await_with_optional_timeout,
    format_tools_description,
    format_traceback_for_infra,
    invoke_structured_with_fallback,
)


class Plan(BaseModel):
    """计划的输出格式"""
    steps: List[str] = Field(
        description="完成任务所需的不同步骤。这些步骤应该按顺序执行，每一步都建立在前一步的基础上。"
    )


# Planner 提示词
planner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent("""
                作为一个专家级别的规划者，你需要将复杂的任务分解为可执行的步骤。

                可用工具列表（用于制定计划时参考）：

                {tools_description}

                注意：你的职责是制定计划，实际的工具调用由 Executor 负责执行。

                {experience_context}

                对于给定的任务，请创建一个简单的、逐步的计划来完成它。计划应该：
                - 将任务分解为逻辑上独立的步骤
                - 每个步骤应该明确使用哪些工具(如果需要工具的话)来获取信息, 最好能同时提供工具执行所需要的参数
                - 步骤之间应该有清晰的依赖关系
                - 步骤描述要具体、可操作
                - **如果有相关经验文档，请参考其中的方法和步骤制定计划**

                示例输入："分析当前系统的性能问题"
                示例输出（假设有对应工具）：
                步骤1: 使用 get_metrics 工具收集系统的 CPU 和内存使用情况
                步骤2: 使用 query_logs 工具检查最近的错误日志
                步骤3: 使用 query_database 工具分析慢查询日志
                步骤4: 综合以上信息生成性能分析报告
            """).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


async def _get_aiops_bindable_tools():
    from app.enterprise.aiops.tool_catalog import get_aiops_bindable_tools

    return await get_aiops_bindable_tools(
        local_tools=[get_current_time, retrieve_knowledge],
        mcp_tool_loader=get_mcp_tools_with_retry,
    )


async def _retrieve_experience_context(query: str):
    from app.enterprise.aiops.tool_catalog import retrieve_aiops_experience_context

    return await retrieve_aiops_experience_context(
        query,
        retrieve_tool=retrieve_knowledge,
    )


async def planner(state: PlanExecuteState) -> Dict[str, Any]:
    """
    规划节点：根据用户输入生成执行计划

    流程：
    1. 先查询内部文档，获取相关经验和最佳实践
    2. (可选) 查询 durable memory，获取 alert pattern / plan template guidance
    3. 基于经验文档和可用工具制定执行计划
    """
    logger.info("=== Planner：制定执行计划 ===")

    input_text = state.get("input", "")
    logger.info(f"用户输入: {input_text}")
    eval_node_timeout_seconds = state.get("eval_node_timeout_seconds")
    eval_deadline_monotonic = state.get("eval_deadline_monotonic")

    try:
        # 步骤1: 查询内部文档获取相关经验
        logger.info("查询内部文档，寻找相关经验...")
        experience_docs = ""
        try:
            # retrieve_knowledge 使用 response_format="content_and_artifact"
            # ainvoke() 只返回 content（字符串），不是元组
            context_str = await await_with_optional_timeout(
                _retrieve_experience_context(input_text),
                eval_node_timeout_seconds,
                "planner retrieve_knowledge",
                eval_deadline_monotonic=eval_deadline_monotonic,
            )
            if context_str and context_str.strip():
                experience_docs = context_str
                logger.info(f"找到相关经验文档，长度: {len(experience_docs)}")
            else:
                logger.info("未找到相关经验文档")
        except Exception as e:
            logger.warning(f"查询内部文档失败: {e}")

        # 步骤1.5: (可选) 查询 durable memory - SHADOW 和 ACTIVE 共享检索逻辑
        memory_observation = None
        memory_guidance_for_prompt = ""

        try:
            guidance = memory_guidance_provider.build(state)
            logger.info(f"Memory mode: {guidance.mode.value}")
            memory_observation = guidance.observation
            memory_guidance_for_prompt = guidance.guidance_text
            if memory_observation:
                logger.info(MemoryTraceService.format_log_summary(memory_observation))
            if memory_guidance_for_prompt:
                logger.info("Memory guidance 将注入 prompt")
        except Exception as e:
            logger.warning(f"查询 memory guidance 失败 (non-fatal): {e}")
            # memory 召回失败不影响主流程

        # 步骤2: 获取可用工具列表
        all_tools = await await_with_optional_timeout(
            _get_aiops_bindable_tools(),
            eval_node_timeout_seconds,
            "planner get_tools",
            eval_deadline_monotonic=eval_deadline_monotonic,
        )

        logger.info(f"可用工具数量: {len(all_tools)}")

        # 格式化工具描述
        tools_description = format_tools_description(all_tools)

        # 步骤3: 格式化经验文档上下文
        if experience_docs:
            experience_context = dedent(f"""
                ## 相关经验文档

                以下是从知识库中检索到的相关经验和最佳实践，请参考这些经验制定执行计划：

                {experience_docs}

                ---
            """).strip()
        else:
            experience_context = ""

        # 步骤3.5: 合并 memory guidance 和 document context
        # 只有 ACTIVE 模式才注入 memory_guidance_for_prompt
        combined_experience_context = MemoryGuidanceService.combine_memory_and_document_context(
            memory_guidance_for_prompt, experience_context
        )

        # 步骤4: 创建 LLM 并生成计划
        llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_api_base,
            temperature=0
        )

        planner_chain = planner_prompt | llm.with_structured_output(Plan)
        planner_json_chain = planner_prompt | llm.with_structured_output(
            Plan,
            method="json_mode",
        )

        # 调用 LLM 生成计划
        planner_payload = {
            "messages": [("user", input_text)],
            "tools_description": tools_description,
            "experience_context": combined_experience_context
        }
        planner_json_payload = {
            **planner_payload,
            "messages": planner_payload["messages"] + [
                ("user", '请只输出合法 JSON，格式为 {"steps":["步骤1","步骤2"]}，不要输出解释文字。')
            ],
        }
        plan_result = await invoke_structured_with_fallback(
            planner_chain,
            planner_json_chain,
            planner_payload,
            stage="planner",
            fallback_payload=planner_json_payload,
            timeout_seconds=eval_node_timeout_seconds,
            eval_deadline_monotonic=eval_deadline_monotonic,
        )

        # 提取步骤列表
        if isinstance(plan_result, Plan):
            plan_steps = plan_result.steps
        elif isinstance(plan_result, dict):
            # 如果返回的是字典，提取 steps 字段
            plan_steps = plan_result.get("steps", [])
        else:
            raise TypeError(f"planner structured output has unexpected type: {type(plan_result).__name__}")

        if not plan_steps:
            raise ValueError("planner produced no steps")

        logger.info(f"计划已生成，共 {len(plan_steps)} 个步骤")
        for i, step in enumerate(plan_steps, 1):
            logger.info(f"  步骤{i}: {step}")

        # 返回计划和 memory observation
        result = {"plan": plan_steps}
        if memory_observation:
            result["memory_observation"] = memory_observation

        return result

    except Exception as e:
        error_message = format_exception_for_infra(e)
        logger.error(f"生成计划失败: {error_message}", exc_info=True)
        # 返回一个默认计划
        return {
            "plan": [
                "收集相关信息",
                "分析数据",
                "生成报告"
            ],
            "infra_error": True,
            "infra_error_stage": "planner",
            "infra_error_message": error_message,
            "infra_error_traceback": format_traceback_for_infra(e),
        }
