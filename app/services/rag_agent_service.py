"""RAG Agent 服务 - 基于 LangGraph 的智能代理

使用 langchain_qwq 的 ChatQwen 原生集成，
支持真正的流式输出和更好的模型适配。
"""

import re
from collections.abc import AsyncGenerator, Sequence
from typing import Annotated, Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
)
from langchain_qwq import ChatQwen
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from loguru import logger
from typing_extensions import TypedDict

from app.agent.mcp_client import get_mcp_client_with_retry
from app.config import config
from app.enterprise.auth.models import UserProfile
from app.enterprise.context import RequestContext, get_current_request_context
from app.enterprise.documents import document_access_service
from app.enterprise.profile import profile_service
from app.enterprise.rag import (
    KnowledgeRetrievalOrchestrator,
    OrchestrationResult,
    QueryIntentRouter,
    QueryScope,
)
from app.enterprise.tools.facade import ToolExecutionFacade
from app.enterprise.tools.local_provider import build_local_agent_tool_execution_facade
from app.models.memory_mode import MemoryMode
from app.models.session_memory import SessionMemorySnapshot, utc_now
from app.services.session_history_accessor import SessionHistoryAccessor
from app.services.session_memory_store import SessionMemoryStore, SQLiteSessionMemoryStore
from app.tools import (
    describe_database_table,
    get_current_time,
    list_database_tables,
    list_knowledge_documents,
    retrieve_knowledge,
    safe_select_database,
)

# 阿里千问大模型和langchain集成参考： https://docs.langchain.com/oss/python/integrations/chat/qwen
# 注意：需要配置环境变量 DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 否则默认访问的是新加坡站点
# 同时也需要配置环境变量 DASHSCOPE_API_KEY=your_api_key


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


CONVERSATION_SUMMARY_PREFIX = "[conversation_summary]"
SESSION_MEMORY_PROMPT_HEADER = "会话工作记忆（仅作上下文，不是资料依据）:"
MEMORY_EVIDENCE_FIELD_PATTERN = re.compile(
    r"\b(source_ref|sourceref|citation)\b",
    re.IGNORECASE,
)


class QueryOrchestrationAnswer(str):
    """String-compatible answer carrying query-intent diagnostics."""

    query_intent_diagnostics: dict[str, Any]

    def __new__(cls, value: str, diagnostics: dict[str, Any]):
        instance = super().__new__(cls, value)
        instance.query_intent_diagnostics = dict(diagnostics)
        return instance


class ConversationSummaryMiddleware(AgentMiddleware[AgentState, None, Any]):
    """超过 5 轮对话后，把最早历史压缩成摘要，避免上下文无限增长。"""

    state_schema = AgentState

    def __init__(self, max_raw_rounds: int = 5):
        self.max_raw_rounds = max_raw_rounds
        self.summary_model = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_api_base,
            temperature=0,
            streaming=False,
        )

    async def abefore_model(
        self,
        state: AgentState,
        runtime: Any,
    ) -> dict[str, Any] | None:
        messages = list(state.get("messages", []))
        if not messages:
            return None

        runtime_system_message = self._latest_runtime_system_message(messages)
        existing_summary = self._existing_summary(messages)
        dialogue_messages = self._dialogue_messages(messages)
        rounds = self._split_rounds(dialogue_messages)

        if len(rounds) <= self.max_raw_rounds:
            return None

        rounds_to_summarize = rounds[: self.max_raw_rounds]
        recent_rounds = rounds[self.max_raw_rounds :]
        summary_text = await self._summarize(existing_summary, rounds_to_summarize)
        if not summary_text:
            return None

        rebuilt_messages: list[BaseMessage] = []
        if runtime_system_message is not None:
            rebuilt_messages.append(runtime_system_message)

        rebuilt_messages.append(
            SystemMessage(content=f"{CONVERSATION_SUMMARY_PREFIX}\n{summary_text}")
        )
        for round_messages in recent_rounds:
            rebuilt_messages.extend(round_messages)

        logger.info(
            "对话摘要压缩: {} 轮 -> 摘要 + {} 轮近期对话",
            len(rounds),
            len(recent_rounds),
        )

        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *rebuilt_messages,
            ]
        }

    def _latest_runtime_system_message(self, messages: list[BaseMessage]) -> SystemMessage | None:
        system_messages = [
            message
            for message in messages
            if isinstance(message, SystemMessage) and not self._is_summary_message(message)
        ]
        return system_messages[-1] if system_messages else None

    def _existing_summary(self, messages: list[BaseMessage]) -> str:
        summary_messages = [
            message for message in messages if self._is_summary_message(message)
        ]
        if not summary_messages:
            return ""
        content = self._message_content_to_text(summary_messages[-1].content)
        if content.startswith(CONVERSATION_SUMMARY_PREFIX):
            content = content[len(CONVERSATION_SUMMARY_PREFIX) :].strip()
        return content

    def _dialogue_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        return [
            message
            for message in messages
            if not self._is_summary_message(message)
            and not isinstance(message, SystemMessage)
        ]

    def _split_rounds(self, messages: list[BaseMessage]) -> list[list[BaseMessage]]:
        rounds: list[list[BaseMessage]] = []
        current_round: list[BaseMessage] = []

        for message in messages:
            if isinstance(message, HumanMessage) and current_round:
                rounds.append(current_round)
                current_round = [message]
                continue
            current_round.append(message)

        if current_round:
            rounds.append(current_round)

        return rounds

    async def _summarize(
        self,
        existing_summary: str,
        rounds_to_summarize: list[list[BaseMessage]],
    ) -> str:
        history_text = "\n\n".join(
            self._format_round(index + 1, round_messages)
            for index, round_messages in enumerate(rounds_to_summarize)
        )
        prompt = [
            SystemMessage(
                content=(
                    "你是对话总结 Agent。你的任务是把历史对话压缩成可继续对话的摘要。"
                    "必须保留用户目标、已确认事实、文件名、ID、系统名、指标、决定和未解决问题。"
                    "不要编造，不要加入新的事实。"
                    "输出要简洁，但要足够支撑后续回答。"
                )
            ),
            HumanMessage(
                content=(
                    f"已有摘要：\n{existing_summary or '无'}\n\n"
                    f"需要压缩的历史对话：\n{history_text}\n\n"
                    "请输出更新后的摘要。"
                )
            ),
        ]

        try:
            response = await self.summary_model.ainvoke(prompt)
        except Exception as exc:  # pragma: no cover - summary fallback only
            logger.warning("总结对话失败，保留原始历史: {}", exc)
            return ""

        return self._message_content_to_text(getattr(response, "content", response))

    def _format_round(self, index: int, round_messages: list[BaseMessage]) -> str:
        lines = [f"第 {index} 轮："]
        for message in round_messages:
            role = self._message_role(message)
            content = self._message_content_to_text(getattr(message, "content", ""))
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _message_role(self, message: BaseMessage) -> str:
        message_type = str(getattr(message, "type", type(message).__name__)).lower()
        if message_type == "human":
            return "user"
        if message_type == "ai":
            return "assistant"
        if message_type == "tool":
            return "tool"
        return message_type

    def _is_summary_message(self, message: BaseMessage) -> bool:
        if not isinstance(message, SystemMessage):
            return False
        content = self._message_content_to_text(getattr(message, "content", ""))
        return content.startswith(CONVERSATION_SUMMARY_PREFIX)

    def _message_content_to_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if text is not None:
                        parts.append(str(text))
                    else:
                        parts.append(str(item))
                else:
                    parts.append(str(item))
            return " ".join(part for part in parts if part).strip()
        return str(content).strip()


class RagAgentService:
    """RAG Agent 服务 - 使用 LangGraph + ChatQwen 原生集成"""

    def __init__(
        self,
        streaming: bool = True,
        *,
        tool_execution_facade: ToolExecutionFacade | None = None,
        retrieval_orchestrator: KnowledgeRetrievalOrchestrator | None = None,
        query_intent_router: QueryIntentRouter | None = None,
        session_memory_store: SessionMemoryStore | None = None,
    ):
        """初始化 RAG Agent 服务

        Args:
            streaming: 是否启用流式输出，默认为 True
        """
        self.model_name = config.rag_model
        self.streaming = streaming
        self.system_prompt = self._build_system_prompt()


        self.model = ChatQwen(
            model=self.model_name,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_api_base,
            temperature=0.7,
            streaming=streaming,
        )

        # 定义基础工具
        self.tools = [
            retrieve_knowledge,
            list_knowledge_documents,
            get_current_time,
            list_database_tables,
            describe_database_table,
            safe_select_database,
        ]

        # MCP 客户端（延迟初始化，使用全局管理）
        self.mcp_tools: list = []
        self.tool_execution_facade = (
            tool_execution_facade or build_local_agent_tool_execution_facade()
        )
        self.query_intent_router = query_intent_router or QueryIntentRouter()
        self.retrieval_orchestrator = (
            retrieval_orchestrator
            or KnowledgeRetrievalOrchestrator(
                tool_execution_facade=self.tool_execution_facade,
            )
        )
        self.session_memory_store = session_memory_store or SQLiteSessionMemoryStore()

        # 创建内存检查点（用于会话管理）
        self.checkpointer = MemorySaver()
        self.summary_middleware = ConversationSummaryMiddleware(max_raw_rounds=5)

        # Agent 初始化（会在异步方法中完成）
        self.agent = None
        self._agent_initialized = False

        logger.info(f"RAG Agent 服务初始化完成 (ChatQwen), model={self.model_name}, streaming={streaming}")

    async def _initialize_agent(self):
        """异步初始化 Agent（包括 MCP 工具）"""
        if self._agent_initialized:
            return

        # 使用全局 MCP 客户端管理器（带重试拦截器）
        mcp_client = await get_mcp_client_with_retry()

        # 获取 MCP 工具
        mcp_tools = await mcp_client.get_tools()
        logger.info(f"成功加载 {len(mcp_tools)} 个 MCP 工具")

        # 将 MCP 工具添加到实例变量中
        self.mcp_tools = mcp_tools

        # 合并所有工具
        all_tools = self.tools + self.mcp_tools

        self.agent = create_agent(
            self.model,
            tools=all_tools,
            checkpointer=self.checkpointer,
            middleware=[self.summary_middleware],
        )

        self._agent_initialized = True


        if all_tools:
            tool_names = [tool.name if hasattr(tool, "name") else str(tool) for tool in all_tools]
            logger.info(f"可用工具列表: {', '.join(tool_names)}")

    def _resolve_request_context(
        self,
        context: RequestContext | None = None,
    ) -> RequestContext | None:
        return context or get_current_request_context()

    async def _build_request_agent(self, context: RequestContext | None = None):
        context = self._resolve_request_context(context)
        if context is None:
            await self._initialize_agent()
            return self.agent

        bindable_tools = await self.tool_execution_facade.get_bindable_tools(
            context,
            capability="rag",
        )
        self.mcp_tools = []
        agent = create_agent(
            self.model,
            tools=bindable_tools,
            checkpointer=self.checkpointer,
            middleware=[self.summary_middleware],
        )
        if bindable_tools:
            tool_names = [
                tool.name if hasattr(tool, "name") else str(tool)
                for tool in bindable_tools
            ]
            logger.info(
                "企业上下文 RAG Agent 工具来自 ToolExecutionFacade: {}",
                ", ".join(tool_names),
            )
        return agent

    def _build_system_prompt(self) -> str:
        """
        构建系统提示词

        注意：LangChain 框架会自动将工具信息传递给 LLM，
        因此系统提示词中无需列举具体的工具列表。

        Returns:
            str: 系统提示词
        """
        from textwrap import dedent

        return dedent("""
            你是一个专业的AI助手，能够使用多种工具来帮助用户解决问题。

            工作原则:
            1. 理解用户需求，选择合适的工具来完成任务
            2. 当需要获取实时信息或专业知识时，主动使用相关工具
            3. 当用户询问“知识库有什么资料/文件/文档”时，优先调用 list_knowledge_documents
            4. 当用户询问某个具体文件讲了什么时，先确认文件名或 doc_id，再用 retrieve_knowledge 的 file_name/doc_id 限定检索
            5. 基于工具返回的结果提供准确、专业的回答
            6. 如果工具无法提供足够信息，请诚实地告知用户

            回答要求:
            - 保持友好、专业的语气
            - 回答简洁明了，重点突出
            - 基于事实，不编造信息
            - 如有不确定的地方，明确说明

            请根据用户的问题，灵活使用可用工具，提供高质量的帮助。
        """).strip()

    async def _build_runtime_system_prompt(
        self,
        *,
        session_id: str | None = None,
        memory_mode: MemoryMode | None = None,
        context: RequestContext | None = None,
    ) -> str:
        context = self._resolve_request_context(context)
        if context is None:
            return self.system_prompt

        user = UserProfile(
            user_id=context.user_id,
            username=context.username,
            department_id=context.department_id,
            department_name=context.department_name,
            roles=list(context.roles),
        )
        try:
            profile = await profile_service.build_profile(
                context,
                include_gateway_tools=False,
            )
        except Exception as exc:  # pragma: no cover - prompt fallback only
            logger.warning("构建运行时 profile 提示失败: {}", exc)
            profile = {
                "user": user.model_dump(mode="json"),
                "visible_tools": ["retrieve_knowledge", "list_knowledge_documents", "get_current_time"],
                "visible_kb_ids": [],
                "feature_flags": {},
                "unavailable_reasons": {},
            }

        user_payload = profile.get("user", user.model_dump(mode="json"))
        visible_tools = ", ".join(profile.get("visible_tools", [])) or "无"
        visible_kb_ids = ", ".join(profile.get("visible_kb_ids", [])) or "无"
        unavailable = profile.get("unavailable_reasons", {})
        unavailable_text = ", ".join(f"{key}({value})" for key, value in unavailable.items()) or "无"

        prompt = (
            f"{self.system_prompt}\n\n"
            "当前用户 Profile（仅用于能力解释，不能替代后端权限检查）:\n"
            f"- username: {user_payload.get('username', '')}\n"
            f"- user_id: {user_payload.get('user_id', '')}\n"
            f"- roles: {', '.join(user_payload.get('roles', [])) or '无'}\n"
            f"- department: {user_payload.get('department_name', '')}\n"
            f"- visible_kb_ids: {visible_kb_ids}\n"
            f"- visible_tools: {visible_tools}\n"
            f"- unavailable: {unavailable_text}\n\n"
            "当用户问“你能干什么”“我是谁”“我有什么权限”时，只基于当前 Profile 回答。"
            "如果功能不可用，说明当前未授权或当前入口未启用，不要说系统完全没有该能力。"
        )
        return self._append_session_memory_prompt(
            prompt,
            session_id=session_id,
            memory_mode=memory_mode,
            context=context,
        )

    def _append_session_memory_prompt(
        self,
        prompt: str,
        *,
        session_id: str | None,
        memory_mode: MemoryMode | None = None,
        context: RequestContext | None = None,
    ) -> str:
        context = self._resolve_request_context(context)
        if context is None or not session_id:
            return prompt

        mode = memory_mode or self._rag_session_memory_mode()
        if mode == MemoryMode.OFF:
            return prompt

        snapshot = self._load_session_memory_snapshot(
            session_id=session_id,
            owner_id=context.user_id,
        )
        if mode == MemoryMode.SHADOW:
            if snapshot is not None:
                logger.debug(
                    "[会话 {}] RAG session memory shadow 命中 owner={}",
                    session_id,
                    context.user_id,
                )
            return prompt

        if snapshot is None or self._is_session_memory_stale(snapshot):
            return prompt

        memory_context = self._bounded_session_memory_context(snapshot)
        if not memory_context:
            return prompt
        return f"{prompt}\n\n{SESSION_MEMORY_PROMPT_HEADER}\n{memory_context}"

    def _load_session_memory_snapshot(
        self,
        *,
        session_id: str,
        owner_id: str,
    ) -> SessionMemorySnapshot | None:
        self._cleanup_session_memory(owner_id=owner_id)
        try:
            return self.session_memory_store.get_snapshot(session_id, owner_id)
        except Exception as exc:  # pragma: no cover - degraded fallback only
            logger.warning("读取 RAG session memory 失败，跳过注入: {}", exc)
            return None

    def _record_session_memory_turn(
        self,
        *,
        session_id: str,
        question: str,
        answer: str,
        context: RequestContext | None = None,
    ) -> None:
        context = self._resolve_request_context(context)
        if context is None or not session_id or not answer:
            return

        mode = self._rag_session_memory_mode()
        if mode == MemoryMode.OFF:
            return

        self._cleanup_session_memory(owner_id=context.user_id)
        max_tail = self._session_memory_max_tail()
        try:
            self.session_memory_store.append_live_message(
                session_id,
                context.user_id,
                role="user",
                content=question,
                metadata={"source": "rag_agent"},
                max_tail=max_tail,
            )
            self.session_memory_store.append_live_message(
                session_id,
                context.user_id,
                role="assistant",
                content=answer,
                metadata={"source": "rag_agent"},
                max_tail=max_tail,
            )
        except Exception as exc:  # pragma: no cover - degraded fallback only
            logger.warning("写入 RAG session memory 失败，保留主流程: {}", exc)

    def _cleanup_session_memory(self, *, owner_id: str) -> None:
        try:
            self.session_memory_store.cleanup_expired(
                ttl_seconds=self._session_memory_ttl_seconds(),
                owner_id=owner_id,
            )
        except Exception as exc:  # pragma: no cover - degraded fallback only
            logger.warning("清理 RAG session memory 失败，保留主流程: {}", exc)

    def _bounded_session_memory_context(
        self,
        snapshot: SessionMemorySnapshot,
    ) -> str:
        memory_context = _sanitize_session_memory_context(snapshot.to_prompt_context())
        if not memory_context:
            return ""
        max_chars = self._session_memory_max_prompt_chars()
        if len(memory_context) <= max_chars:
            return memory_context
        if max_chars <= 20:
            return ""
        return f"{memory_context[: max_chars - 12].rstrip()}\n[已截断]"

    def _is_session_memory_stale(self, snapshot: SessionMemorySnapshot) -> bool:
        ttl_seconds = self._session_memory_ttl_seconds()
        return (utc_now() - snapshot.updated_at).total_seconds() > ttl_seconds

    def _rag_session_memory_mode(self) -> MemoryMode:
        mode = MemoryMode.from_config(getattr(config, "rag_session_memory_mode", "off"))
        if mode != MemoryMode.OFF and not self._session_memory_gate_configured():
            logger.warning("RAG session memory 配置不完整，降级为 off")
            return MemoryMode.OFF
        return mode

    def _session_memory_gate_configured(self) -> bool:
        return (
            self._session_memory_ttl_seconds() > 0
            and self._session_memory_max_prompt_chars() > 0
            and self._session_memory_max_tail() >= 0
            and hasattr(self.session_memory_store, "cleanup_expired")
        )

    def _session_memory_ttl_seconds(self) -> int:
        return max(1, int(getattr(config, "rag_session_memory_snapshot_ttl_seconds", 1)))

    def _session_memory_max_prompt_chars(self) -> int:
        return max(0, int(getattr(config, "rag_session_memory_max_prompt_chars", 0)))

    def _session_memory_max_tail(self) -> int:
        return max(0, int(getattr(config, "rag_session_memory_max_tail_messages", 0)))

    async def query(
        self,
        question: str,
        session_id: str,
        *,
        selected_kb_ids: list[str] | None = None,
        scope_source: str = "auto_visible",
        context: RequestContext | None = None,
    ) -> str:
        """
        非流式处理用户问题（一次性返回完整答案）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Returns:
            str: 完整答案
        """
        try:
            orchestration_result = await self._try_query_orchestration(
                question,
                selected_kb_ids=selected_kb_ids,
                scope_source=scope_source,
                context=context,
            )
            if orchestration_result is not None:
                logger.info("[会话 {}] QueryIntentRouter 编排完成（非流式）", session_id)
                self._record_session_memory_turn(
                    session_id=session_id,
                    question=question,
                    answer=orchestration_result.answer,
                    context=context,
                )
                return QueryOrchestrationAnswer(
                    orchestration_result.answer,
                    orchestration_result.diagnostics,
                )

            agent = await self._build_request_agent(context=context)

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（非流式）: {question}")

            # 构建消息列表（系统提示 + 用户问题）
            messages = [
                SystemMessage(
                    content=await self._build_runtime_system_prompt(
                        session_id=session_id,
                        context=context,
                    )
                ),
                HumanMessage(content=question)
            ]

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            result = await agent.ainvoke(
                input=agent_input,
                config=config_dict,
            )

            # 提取最终答案
            messages_result = result.get("messages", [])
            if messages_result:
                last_message = messages_result[-1]
                answer = last_message.content if hasattr(last_message, 'content') else str(last_message)

                # 记录工具调用
                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    tool_names = [tc.get("name", "unknown") for tc in last_message.tool_calls]
                    logger.info(f"[会话 {session_id}] Agent 调用了工具: {tool_names}")

                logger.info(f"[会话 {session_id}] RAG Agent 查询完成（非流式）")
                self._record_session_memory_turn(
                    session_id=session_id,
                    question=question,
                    answer=str(answer),
                    context=context,
                )
                return answer

            logger.warning(f"[会话 {session_id}] Agent 返回结果为空")
            return ""

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（非流式）: {e}")
            raise

    async def query_stream(
        self,
        question: str,
        session_id: str,
        *,
        selected_kb_ids: list[str] | None = None,
        scope_source: str = "auto_visible",
        context: RequestContext | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        流式处理用户问题（逐步返回答案片段）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Yields:
            Dict[str, Any]: 包含流式数据的字典
                - type: "content" | "tool_call" | "complete" | "error"
                - data: 具体内容
        """
        try:
            orchestration_result = await self._try_query_orchestration(
                question,
                selected_kb_ids=selected_kb_ids,
                scope_source=scope_source,
                context=context,
            )
            if orchestration_result is not None:
                logger.info("[会话 {}] QueryIntentRouter 编排完成（流式）", session_id)
                self._record_session_memory_turn(
                    session_id=session_id,
                    question=question,
                    answer=orchestration_result.answer,
                    context=context,
                )
                yield {
                    "type": "query_intent_diagnostics",
                    "data": orchestration_result.diagnostics,
                    "node": "query_intent_orchestrator",
                }
                if orchestration_result.answer:
                    yield {
                        "type": "content",
                        "data": orchestration_result.answer,
                        "node": "query_intent_orchestrator",
                    }
                yield {"type": "complete"}
                return

            agent = await self._build_request_agent(context=context)

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（流式）: {question}")

            # 构建消息列表（系统提示 + 用户问题）
            messages = [
                SystemMessage(
                    content=await self._build_runtime_system_prompt(
                        session_id=session_id,
                        context=context,
                    )
                ),
                HumanMessage(content=question)
            ]

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            answer_parts: list[str] = []
            async for token, metadata in agent.astream(
                input=agent_input,
                config=config_dict,
                stream_mode="messages",
            ):
                node_name = metadata.get('langgraph_node', 'unknown') if isinstance(metadata, dict) else 'unknown'
                message_type = type(token).__name__

                if message_type in ("AIMessage", "AIMessageChunk"):
                    content_blocks = getattr(token, 'content_blocks', None)

                    if content_blocks and isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                text_content = block.get('text', '')
                                if text_content:
                                    answer_parts.append(text_content)
                                    yield {
                                        "type": "content",
                                        "data": text_content,
                                        "node": node_name
                                    }

            logger.info(f"[会话 {session_id}] RAG Agent 查询完成（流式）")
            self._record_session_memory_turn(
                session_id=session_id,
                question=question,
                answer="".join(answer_parts),
                context=context,
            )
            yield {"type": "complete"}

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（流式）: {e}")
            yield {
                "type": "error",
                "data": str(e)
            }
            raise

    async def _try_query_orchestration(
        self,
        question: str,
        *,
        selected_kb_ids: list[str] | None = None,
        scope_source: str = "auto_visible",
        context: RequestContext | None = None,
    ) -> OrchestrationResult | None:
        context = self._resolve_request_context(context)
        if context is None:
            return None

        scope = QueryScope(
            selected_kb_ids=list(selected_kb_ids or []),
            visible_kb_ids=document_access_service.visible_kb_ids(context),
            scope_source="user_selected" if scope_source == "user_selected" else "auto_visible",
        )
        decision = self.query_intent_router.classify(
            question,
            context=context,
            scope=scope,
        )
        if decision.intent == "plain_chat":
            return None

        return await self.retrieval_orchestrator.execute(
            context,
            query=question,
            decision=decision,
        )

    def get_session_history(self, session_id: str) -> list:
        """
        获取会话历史（通过稳定 accessor 读取）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            list: 消息历史列表 [{"role": "user|assistant", "content": "...", "timestamp": "..."}]
        """
        return SessionHistoryAccessor(self.checkpointer).get_history_dicts(session_id)

    def clear_session(self, session_id: str) -> bool:
        """
        清空会话历史（从 MemorySaver checkpointer 中删除）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            bool: 是否成功
        """
        try:
            # 使用 checkpointer 的 delete_thread 方法删除该 thread 的所有检查点
            self.checkpointer.delete_thread(session_id)

            logger.info(f"已清除会话历史: {session_id}")
            return True

        except Exception as e:
            logger.error(f"清空会话历史失败: {session_id}, 错误: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        try:
            logger.info("清理 RAG Agent 服务资源...")
            # MCP 客户端由全局管理器统一管理，无需手动清理
            logger.info("RAG Agent 服务资源已清理")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")


# 全局单例 - 启用流式输出
rag_agent_service = RagAgentService(streaming=True)


def _sanitize_session_memory_context(text: str) -> str:
    return MEMORY_EVIDENCE_FIELD_PATTERN.sub("[会话记忆非证据字段]", text).strip()
