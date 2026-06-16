"""
通用 Plan-Execute-Replan 服务
基于 LangGraph 官方教程实现
"""

from collections.abc import AsyncGenerator
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from loguru import logger

from app.agent.aiops import PlanExecuteState, executor, planner, replanner
from app.agent.aiops.utils import format_traceback_for_infra
from app.agent.mcp_client import format_exception_for_infra
from app.enterprise.aiops.failure_semantics import AIOpsFailureLabel, AIOpsFailureSemantics
from app.enterprise.aiops.tool_catalog import aiops_tool_catalog
from app.enterprise.context import RequestContext, get_current_request_context
from app.models.memory_candidate import AIOpsSessionState
from app.services.session_history_accessor import AIOpsGraphStateAccessor

# 节点名称常量
NODE_PLANNER = "planner"
NODE_EXECUTOR = "executor"
NODE_REPLANNER = "replanner"


class AIOpsService:
    """通用 Plan-Execute-Replan 服务"""

    def __init__(self):
        """初始化服务"""
        self.checkpointer = MemorySaver()
        self.graph = self._build_graph()
        logger.info("Plan-Execute-Replan Service 初始化完成")

    def _build_graph(self):
        """构建 Plan-Execute-Replan 工作流"""
        logger.info("构建工作流图...")

        # 创建状态图
        workflow = StateGraph(PlanExecuteState)

        # 添加节点
        workflow.add_node(NODE_PLANNER, planner)      # 制定计划
        workflow.add_node(NODE_EXECUTOR, executor)  # 执行步骤
        workflow.add_node(NODE_REPLANNER, replanner)  # 重新规划

        # 设置入口点
        workflow.set_entry_point(NODE_PLANNER)

        # 定义边
        workflow.add_edge(NODE_PLANNER, NODE_EXECUTOR)     # planner -> executor
        workflow.add_edge(NODE_EXECUTOR, NODE_REPLANNER)   # executor -> replanner

        # replanner 的条件边
        def should_continue(state: PlanExecuteState) -> str:
            """判断是否继续执行"""
            # 如果已经生成了最终响应，结束
            if state.get("response"):
                logger.info("已生成最终响应，结束流程")
                return END

            # 如果还有计划步骤，继续执行
            plan = state.get("plan", [])
            if plan:
                logger.info(f"继续执行，剩余 {len(plan)} 个步骤")
                return NODE_EXECUTOR

            # 计划为空但没有响应，返回 replanner 生成响应
            logger.info("计划执行完毕，生成最终响应")
            return END

        workflow.add_conditional_edges(
            NODE_REPLANNER,
            should_continue,
            {
                NODE_EXECUTOR: NODE_EXECUTOR,
                END: END
            }
        )

        # 编译工作流
        compiled_graph = workflow.compile(checkpointer=self.checkpointer)

        logger.info("工作流图构建完成")
        return compiled_graph

    def get_session_state(self, session_id: str) -> AIOpsSessionState | None:
        """Return normalized graph state for explicit memory candidate extraction."""
        return AIOpsGraphStateAccessor(self.graph).get_state(session_id)

    async def execute(
        self,
        user_input: str,
        session_id: str = "default",
        memory_mode: str | None = None,
        enable_memory_guidance: bool = False,
        memory_owner_id: str = "default",
        memory_store_path: str | None = None,
        task_contract_id: str | None = None,
        aiops_scenario: str | None = None,
        aiops_service_name: str | None = None,
        aiops_required_tools: list[str] | None = None,
        eval_max_steps: int | None = None,
        eval_node_timeout_seconds: float | None = None,
        eval_executor_final_timeout_seconds: float | None = None,
        eval_deadline_monotonic: float | None = None,
        context: RequestContext | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        执行 Plan-Execute-Replan 流程

        Args:
            user_input: 用户的任务描述
            session_id: 会话ID
            memory_mode: Memory 模式 ('off' | 'shadow' | 'active')，优先于 enable_memory_guidance
            enable_memory_guidance: 是否启用 memory guidance（P5 默认关闭，优先级低于 memory_mode）
            memory_owner_id: Memory owner ID
            memory_store_path: 自定义 memory store 路径（用于 eval，None 则使用默认全局 store）
            task_contract_id: Enterprise 2.0 F1 task contract id，默认 None 不改变旧路径
            eval_max_steps: eval-only 最大执行步数；None 时不改变生产默认行为
            eval_node_timeout_seconds: eval-only 单节点超时；None 时不改变生产默认行为
            eval_executor_final_timeout_seconds: eval-only executor 工具后最终合成超时；None 时沿用 eval_node_timeout_seconds
            eval_deadline_monotonic: eval-only 样本绝对截止时间；None 时不改变生产默认行为

        Yields:
            Dict[str, Any]: 流式事件
        """
        logger.info(f"[会话 {session_id}] 开始执行任务: {user_input}")

        try:
            # 初始化状态
            initial_state: PlanExecuteState = {
                "input": user_input,
                "session_id": session_id,
                "plan": [],
                "past_steps": [],
                "response": "",
                # P5 memory guidance flags
                "memory_mode": memory_mode,
                "enable_memory_guidance": enable_memory_guidance,
                "memory_owner_id": memory_owner_id,
                "memory_store_path": memory_store_path,
                "task_contract_id": task_contract_id,
                "aiops_scenario": aiops_scenario,
                "aiops_service_name": aiops_service_name,
                "aiops_required_tools": aiops_required_tools or [],
                "aiops_executed_tools": [],
                "eval_max_steps": eval_max_steps,
                "eval_node_timeout_seconds": eval_node_timeout_seconds,
                "eval_executor_final_timeout_seconds": eval_executor_final_timeout_seconds,
                "eval_deadline_monotonic": eval_deadline_monotonic,
            }

            # 流式执行工作流
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            async for event in self.graph.astream(
                input=initial_state,
                config=config_dict,
                stream_mode="updates"
            ):
                # 解析事件
                for node_name, node_output in event.items():
                    logger.info(f"节点 '{node_name}' 输出事件")

                    # 根据节点类型生成不同的事件
                    if node_name == NODE_PLANNER:
                        yield self._with_task_contract_id(
                            self._format_planner_event(node_output),
                            task_contract_id,
                        )

                    elif node_name == NODE_EXECUTOR:
                        yield self._with_task_contract_id(
                            self._format_executor_event(node_output),
                            task_contract_id,
                        )

                    elif node_name == NODE_REPLANNER:
                        yield self._with_task_contract_id(
                            self._format_replanner_event(node_output),
                            task_contract_id,
                        )

            # 获取最终状态
            final_state = self.graph.get_state(config_dict)
            final_response = ""

            # 安全地获取响应（处理 values 可能为 None 的情况）
            if final_state and final_state.values:
                final_response = final_state.values.get("response", "")

            # 发送完成事件
            complete_event = {
                "type": "complete",
                "stage": "complete",
                "message": "任务执行完成",
                "response": final_response
            }
            if final_state and final_state.values:
                complete_event = self._with_infra_fields(complete_event, final_state.values)
            complete_event = self._with_task_contract_id(complete_event, task_contract_id)
            yield complete_event

            logger.info(f"[会话 {session_id}] 任务执行完成")

        except Exception as e:
            error_message = format_exception_for_infra(e)
            logger.error(f"[会话 {session_id}] 任务执行失败: {error_message}", exc_info=True)
            yield AIOpsFailureSemantics.to_degradation_event({
                "type": "error",
                "stage": "workflow_error",
                "message": f"任务执行出错: {error_message}",
                "infra_error": True,
                "infra_error_stage": "workflow",
                "infra_error_message": error_message,
                "infra_error_traceback": format_traceback_for_infra(e),
            })

    async def diagnose(
        self,
        session_id: str = "default",
        memory_mode: str | None = None,
        enable_memory_guidance: bool = False,
        enable_memory_evidence_ingestion: bool = False,
        memory_owner_id: str = "default",
        query: str | None = None,
        memory_store_path: str | None = None,
        memory_evidence_store_path: str | None = None,
        task_contract_id: str | None = None,
        eval_max_steps: int | None = None,
        eval_node_timeout_seconds: float | None = None,
        eval_executor_final_timeout_seconds: float | None = None,
        eval_deadline_monotonic: float | None = None,
        context: RequestContext | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        AIOps 诊断接口（兼容旧接口）

        Args:
            session_id: 会话ID
            memory_mode: Memory 模式 ('off' | 'shadow' | 'active')，优先于 enable_memory_guidance
            enable_memory_guidance: 是否启用 memory guidance（P5 默认关闭，优先级低于 memory_mode）
            enable_memory_evidence_ingestion: 是否在 diagnosis_complete 后写入 L0 evidence（P7，默认关闭）
            memory_owner_id: Memory owner ID
            query: 自定义诊断查询（用于 eval，None 则使用默认模板）
            memory_store_path: 自定义 memory store 路径（用于 eval，None 则使用默认全局 store）
            memory_evidence_store_path: 自定义 L0 evidence store 路径（P7，默认关闭时不使用）
            task_contract_id: Enterprise 2.0 F1 task contract id，默认 None 不改变旧路径
            eval_max_steps: eval-only 最大执行步数；None 时不改变生产默认行为
            eval_node_timeout_seconds: eval-only 单节点超时；None 时不改变生产默认行为
            eval_executor_final_timeout_seconds: eval-only executor 工具后最终合成超时；None 时沿用 eval_node_timeout_seconds
            eval_deadline_monotonic: eval-only 样本绝对截止时间；None 时不改变生产默认行为

        Yields:
            Dict[str, Any]: 诊断过程的流式事件
        """
        context = context or get_current_request_context()
        # 使用自定义 query 或固定的 AIOps 任务描述
        from textwrap import dedent
        if query is not None:
            aiops_task = query
        else:
            aiops_task = dedent("""诊断当前系统是否存在活跃告警，并基于工具证据生成诊断报告。

                必须按以下顺序执行：
                1. 先调用 query_active_alerts 查询当前活跃告警。
                2. 如果没有活跃告警，明确说明“没有活跃告警”或“未发现活跃告警”，并列出已检查的数据源：Alertmanager、Prometheus、CLS JSON 日志、CMDB。
                3. 如果存在活跃告警，按 severity 和 updated_at / starts_at 排序。
                4. 对每个告警调用 query_metric_series 查询相关服务的指标趋势。
                5. 对每个告警调用 search_service_logs 查询相关服务日志，并可用 analyze_log_pattern 汇总错误、慢查询、Redis backlog 等模式。
                6. 调用 get_service_info、get_recent_deployments、search_historical_tickets 和 list_service_dependencies 查询 owner、最近发布、历史工单和依赖关系。
                7. 基于查询到的告警、指标、日志、发布、工单和依赖证据输出根因判断、处理建议和风险评估。
                8. 不得编造未查询到的数据；工具失败时必须在报告中说明失败原因。

                诊断报告输出格式要求：
                ```
                # 告警分析报告

                ---

                ## 📋 活跃告警清单

                | 告警名称 | 级别 | 目标服务 | 首次触发时间 | 最新触发时间 | 状态 |
                |---------|------|----------|-------------|-------------|------|
                | [告警1名称] | [级别] | [服务名] | [时间] | [时间] | 活跃 |
                | [告警2名称] | [级别] | [服务名] | [时间] | [时间] | 活跃 |

                ---

                ## 🔍 告警根因分析1 - [告警名称]

                ### 告警详情
                - **告警级别**: [级别]
                - **受影响服务**: [服务名]
                - **持续时间**: [X分钟]

                ### 症状描述
                [根据监控指标描述症状]

                ### 日志证据
                [引用查询到的关键日志]

                ### 根因结论
                [基于证据得出的根本原因]

                ---

                ## 🛠️ 处理方案执行1 - [告警名称]

                ### 已执行的排查步骤
                1. [步骤1]
                2. [步骤2]

                ### 处理建议
                [给出具体的处理建议]

                ### 预期效果
                [说明预期的效果]

                ---

                ## 🔍 告警根因分析2 - [告警名称]
                [如果有第2个告警，重复上述格式]

                ---

                ## 📊 结论

                ### 整体评估
                [总结所有告警的整体情况]

                ### 关键发现
                - [发现1]
                - [发现2]

                ### 后续建议
                1. [建议1]
                2. [建议2]

                ### 风险评估
                [评估当前风险等级和影响范围]
                ```

                **重要提醒**：
                - 最终输出必须是纯 Markdown 文本，不要包含 JSON 结构
                - 所有内容必须基于工具查询的真实数据，严禁编造
                - 如果某个步骤失败，在结论中如实说明，不要跳过""")

        streamed_events: list[dict[str, Any]] = []
        scenario = _infer_scenario_from_user_query(query)
        required_tools: list[str] = []
        if scenario is not None:
            try:
                available_tools = await aiops_tool_catalog.bindable_tools(context)
                catalog_result = aiops_tool_catalog.validate_required_tools(
                    scenario,
                    available_tools,
                    context=context,
                )
            except Exception as exc:
                error_message = format_exception_for_infra(exc)
                failure_event = AIOpsFailureSemantics.to_degradation_event(
                    {
                        "type": "error",
                        "stage": "tool_validation",
                        "status": "failed",
                        "message": f"AIOps tool validation failed: {error_message}",
                        "scenario": scenario,
                        "infra_error": True,
                        "infra_error_stage": "tool_validation",
                        "infra_error_message": error_message,
                        "infra_error_traceback": format_traceback_for_infra(exc),
                    }
                )
                complete_event = {
                    "type": "complete",
                    "stage": "diagnosis_complete",
                    "message": "诊断流程失败：AIOps 工具校验失败",
                    "diagnosis": {
                        "status": "failed",
                        "report": "",
                        "failure_semantics": failure_event["failure_semantics"],
                    },
                    "scenario": scenario,
                    "failure_semantics": failure_event["failure_semantics"],
                    "failure_semantics_hard_failure": failure_event[
                        "failure_semantics_hard_failure"
                    ],
                    "hard_failure": failure_event["hard_failure"],
                    "degradation": failure_event["degradation"],
                }
                if task_contract_id:
                    failure_event["task_contract_id"] = task_contract_id
                    complete_event["task_contract_id"] = task_contract_id
                yield failure_event
                yield complete_event
                return
            if catalog_result.hard_failure:
                failure_event = AIOpsFailureSemantics.to_degradation_event(
                    {
                        "type": "error",
                        "stage": "tool_validation",
                        "status": "failed",
                        "message": "AIOps required tool validation failed",
                        "scenario": scenario,
                        "visible_tools": catalog_result.visible_tools,
                        "required_tools": catalog_result.required_tools,
                        "missing_required_tools": catalog_result.missing_required_tools,
                    },
                    label=catalog_result.failure_semantics,
                )
                complete_event = {
                    "type": "complete",
                    "stage": "diagnosis_complete",
                    "message": "诊断流程失败：缺少必需 AIOps 工具",
                    "diagnosis": {
                        "status": "failed",
                        "report": "",
                        "failure_semantics": failure_event["failure_semantics"],
                        "missing_required_tools": catalog_result.missing_required_tools,
                    },
                    "scenario": scenario,
                    "visible_tools": catalog_result.visible_tools,
                    "required_tools": catalog_result.required_tools,
                    "missing_required_tools": catalog_result.missing_required_tools,
                    "failure_semantics": failure_event["failure_semantics"],
                    "failure_semantics_hard_failure": failure_event[
                        "failure_semantics_hard_failure"
                    ],
                    "hard_failure": failure_event["hard_failure"],
                    "degradation": failure_event["degradation"],
                }
                if task_contract_id:
                    failure_event["task_contract_id"] = task_contract_id
                    complete_event["task_contract_id"] = task_contract_id
                yield failure_event
                yield complete_event
                return
            required_tools = catalog_result.required_tools

        async for event in self.execute(
            aiops_task,
            session_id,
            memory_mode=memory_mode,
            enable_memory_guidance=enable_memory_guidance,
            memory_owner_id=memory_owner_id,
            memory_store_path=memory_store_path,
            task_contract_id=task_contract_id,
            aiops_scenario=scenario,
            aiops_service_name=_infer_service_name_from_user_query(query),
            aiops_required_tools=required_tools,
            eval_max_steps=eval_max_steps,
            eval_node_timeout_seconds=eval_node_timeout_seconds,
            eval_executor_final_timeout_seconds=eval_executor_final_timeout_seconds,
            eval_deadline_monotonic=eval_deadline_monotonic,
        ):
            # 转换事件格式以兼容旧的 API
            if event.get("type") == "complete":
                diagnosis_event = {
                    "type": "complete",
                    "stage": "diagnosis_complete",
                    "message": "诊断流程完成",
                    "diagnosis": {
                        "status": "completed",
                        "report": event.get("response", "")
                    }
                }
                for key in (
                    "infra_error",
                    "infra_error_stage",
                    "infra_error_message",
                    "infra_error_traceback",
                    "failure_semantics",
                    "failure_semantics_hard_failure",
                    "degradation",
                ):
                    if key in event:
                        diagnosis_event[key] = event[key]
                for key, value in event.items():
                    if key.startswith("structured_output_") and value is not None:
                        diagnosis_event[key] = value
                self._apply_failure_semantics(diagnosis_event)
                if event.get("task_contract_id"):
                    diagnosis_event["task_contract_id"] = event["task_contract_id"]

                if enable_memory_evidence_ingestion:
                    memory_ingestion_event = self._ingest_memory_evidence(
                        session_id=session_id,
                        owner_id=memory_owner_id,
                        diagnosis_event=diagnosis_event,
                        key_events=streamed_events,
                        memory_evidence_store_path=memory_evidence_store_path,
                    )
                    diagnosis_event.update(memory_ingestion_event)

                yield diagnosis_event
            else:
                streamed_events.append(event)
                yield event

    def _with_task_contract_id(
        self,
        event: dict[str, Any],
        task_contract_id: str | None,
    ) -> dict[str, Any]:
        if task_contract_id:
            event["task_contract_id"] = task_contract_id
        return event

    def _with_infra_fields(
        self,
        event: dict[str, Any],
        state: dict[str, Any],
        fallback_stage: str | None = None,
        fallback_message: str | None = None,
    ) -> dict[str, Any]:
        """Copy internal node failure markers into the public event stream."""
        infra_error = bool(state.get("infra_error"))
        infra_error_stage = state.get("infra_error_stage")
        infra_error_message = state.get("infra_error_message")
        infra_error_traceback = state.get("infra_error_traceback")

        if fallback_message:
            infra_error = True
            infra_error_stage = infra_error_stage or fallback_stage
            infra_error_message = infra_error_message or fallback_message

        if infra_error:
            event["infra_error"] = True
            event["infra_error_stage"] = infra_error_stage or fallback_stage or event.get("stage")
            event["infra_error_message"] = infra_error_message or "internal node failure"
            if infra_error_traceback:
                event["infra_error_traceback"] = infra_error_traceback

        for key, value in state.items():
            if key.startswith("structured_output_") and value is not None:
                event[key] = value

        semantics = AIOpsFailureSemantics.classify_event(event)
        if event.get("infra_error") and self._event_has_report(event):
            semantics = AIOpsFailureLabel.RECOVERED_INFRA_ERROR
            event["failure_semantics"] = semantics.value
        if semantics is not None:
            event.update(
                AIOpsFailureSemantics.to_sse_error(
                    {"failure_semantics": semantics.value}
                )
            )

        return event

    def _apply_failure_semantics(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("infra_error") and self._event_has_report(event):
            event["failure_semantics"] = AIOpsFailureLabel.RECOVERED_INFRA_ERROR.value
        semantics = AIOpsFailureSemantics.classify_event(event)
        if semantics is not None:
            event.update(
                AIOpsFailureSemantics.to_sse_error(
                    {"failure_semantics": semantics.value}
                )
            )
        return event

    def _event_has_report(self, event: dict[str, Any]) -> bool:
        for key in ("response", "report"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return True
        diagnosis = event.get("diagnosis")
        if isinstance(diagnosis, dict):
            report = diagnosis.get("report")
            return isinstance(report, str) and bool(report.strip())
        return False

    def _ingest_memory_evidence(
        self,
        *,
        session_id: str,
        owner_id: str,
        diagnosis_event: dict[str, Any],
        key_events: list[dict[str, Any]],
        memory_evidence_store_path: str | None,
    ) -> dict[str, Any]:
        """Best-effort P7 L0 evidence ingestion."""

        try:
            from app.services.memory_evidence_store import MemoryEvidenceStore
            from app.services.memory_ingestion_service import MemoryIngestionService

            store = (
                MemoryEvidenceStore(store_path=memory_evidence_store_path)
                if memory_evidence_store_path
                else MemoryEvidenceStore()
            )
            ingestion_service = MemoryIngestionService(store=store)
            session_state = self.get_session_state(session_id)
            if session_state is None:
                return {
                    "memory_evidence_ingested": False,
                    "memory_evidence_error": "session state missing for ingestion",
                }

            evidence = ingestion_service.ingest_aiops_diagnosis(
                session_state,
                owner_id=owner_id,
                key_events=key_events,
                memory_observation=diagnosis_event.get("memory_observation"),
                diagnosis_status="complete" if diagnosis_event.get("diagnosis", {}).get("report") else "partial",
            )
            return {
                "memory_evidence_ingested": True,
                "memory_evidence_id": evidence.evidence_id,
            }
        except Exception as exc:
            logger.warning(
                "L0 evidence ingestion failed for session_id={}: {}",
                session_id,
                exc,
            )
            return {
                "memory_evidence_ingested": False,
                "memory_evidence_error": format_exception_for_infra(exc),
            }

    def _format_planner_event(self, state: dict | None) -> dict:
        """格式化 Planner 节点事件"""
        if not state:
            return {
                "type": "status",
                "stage": "planner",
                "message": "规划节点执行中"
            }

        plan = state.get("plan", [])

        event = {
            "type": "plan",
            "stage": "plan_created",
            "message": f"执行计划已制定，共 {len(plan)} 个步骤",
            "plan": plan
        }
        if state.get("memory_observation"):
            event["memory_observation"] = state["memory_observation"]
        return self._with_infra_fields(event, state)

    def _format_executor_event(self, state: dict | None) -> dict:
        """格式化 Executor 节点事件"""
        if not state:
            return {
                "type": "status",
                "stage": "executor",
                "message": "执行节点运行中"
            }

        plan = state.get("plan", [])
        past_steps = state.get("past_steps", [])

        if past_steps:
            last_step, last_result = past_steps[-1]
            event = {
                "type": "step_complete",
                "stage": "step_executed",
                "message": f"步骤执行完成 ({len(past_steps)}/{len(past_steps) + len(plan)})",
                "current_step": last_step,
                "remaining_steps": len(plan),
                "step_result": last_result,
            }
            fallback_message = None
            if isinstance(last_result, str) and last_result.startswith("执行失败:"):
                fallback_message = last_result
            return self._with_infra_fields(
                event,
                state,
                fallback_stage="executor",
                fallback_message=fallback_message,
            )
        else:
            return {
                "type": "status",
                "stage": "executor",
                "message": "开始执行步骤"
            }

    def _format_replanner_event(self, state: dict | None) -> dict:
        """格式化 Replanner 节点事件"""
        if not state:
            return {
                "type": "status",
                "stage": "replanner",
                "message": "评估节点运行中"
            }

        response = state.get("response", "")
        plan = state.get("plan", [])

        if response:
            # 已生成最终响应
            event = {
                "type": "report",
                "stage": "final_report",
                "message": "最终报告已生成",
                "report": response
            }
            return self._with_infra_fields(event, state)
        else:
            # 重新规划
            event = {
                "type": "status",
                "stage": "replanner",
                "message": f"评估完成，{'继续执行剩余步骤' if plan else '准备生成最终响应'}",
                "remaining_steps": len(plan)
            }
            return self._with_infra_fields(event, state)


# 全局单例
aiops_service = AIOpsService()


def _infer_scenario_from_user_query(query: str | None) -> str | None:
    """Infer known lab scenario names from an explicit user query."""

    if not query:
        return None
    normalized = "".join(ch for ch in query.lower() if ch.isalnum())
    if "cpuhigh" in normalized or "highcpu" in normalized:
        return "CPUHigh"
    if "dbslowquery" in normalized or "databaseslowquery" in normalized:
        return "DBSlowQuery"
    if "redisqueuebacklog" in normalized or "redisbacklog" in normalized:
        return "RedisQueueBacklog"
    return None


def _infer_service_name_from_user_query(query: str | None) -> str | None:
    """Infer the lab service name from an explicit user query."""

    if not query:
        return None
    normalized = query.lower()
    if "data-sync-service" in normalized or "datasyncservice" in normalized.replace("-", ""):
        return "data-sync-service"
    if "order-service" in normalized or "orderservice" in normalized.replace("-", ""):
        return "order-service"
    if "inventory-service" in normalized or "inventoryservice" in normalized.replace("-", ""):
        return "inventory-service"
    return None
