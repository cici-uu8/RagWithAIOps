"""对话接口

提供基于 RAG Agent 的普通对话和流式对话接口
"""

import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.enterprise.adapters.chat_adapter import ChatAdapter
from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.context import get_current_request_context
from app.enterprise.errors.mapper import build_error_event, map_exception_to_error_context
from app.enterprise.gateway.request_gateway import RequestBlocked
from app.enterprise.observability.sse_contract import normalize_sse_event
from app.enterprise.sessions.service import SessionAccessError, session_access
from app.models.request import ChatRequest, ClearRequest
from app.models.response import ApiResponse, SessionInfoResponse
from app.services.rag_agent_service import rag_agent_service

router = APIRouter()
chat_adapter = ChatAdapter(rag_agent_service)


def _current_context_or_500():
    context = get_current_request_context()
    if context is None:
        raise HTTPException(status_code=500, detail="request context is required")
    return context


def _assert_or_claim_session(
    session_id: str,
    user_id: str,
    *,
    route: str,
    title: str | None = None,
) -> None:
    del user_id
    context = _current_context_or_500()
    try:
        session_access.audit_service = chat_adapter.gateway.audit_service
        session_access.claim_or_assert_owner(
            context,
            session_id,
            route=route,
            title=title,
        )
    except SessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _assert_session_owner(session_id: str, user_id: str, *, route: str, action: str) -> None:
    del user_id
    context = _current_context_or_500()
    try:
        session_access.audit_service = chat_adapter.gateway.audit_service
        if action == "read":
            session_access.assert_read(context, session_id, route=route)
        elif action == "clear":
            session_access.assert_clear(context, session_id, route=route)
        else:
            session_access.assert_write(context, session_id, route=route)
    except SessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def _append_session_message(
    session_id: str,
    *,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> None:
    context = get_current_request_context()
    if context is None:
        return
    session_access.audit_service = chat_adapter.gateway.audit_service
    session_access.append_message(
        context,
        session_id,
        role=role,
        content=content,
        metadata=metadata or {},
    )


def _session_payload(session) -> dict:
    return {
        "session_id": session.session_id,
        "id": session.session_id,
        "title": session.title,
        "kind": session.kind,
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "archived_at": session.archived_at.isoformat() if session.archived_at else None,
    }


def _message_payload(message) -> dict[str, str]:
    return {
        "message_id": message.message_id,
        "role": message.role,
        "content": message.content,
        "timestamp": message.created_at.isoformat(),
    }


@router.post("/chat")
async def chat(chat_request: ChatRequest, http_request: Request, current_user: CurrentUser):
    """快速对话接口
    {
        "code": 200,
        "message": "success",
        "data": {
            "success": true,
            "answer": "回答内容",
            "errorMessage": null
        }
    }

    Args:
        request: 对话请求

    Returns:
        统一格式的对话响应
    """
    _assert_or_claim_session(
        chat_request.id,
        current_user.user_id,
        route="chat",
        title=chat_request.question,
    )
    try:
        logger.info(f"[会话 {chat_request.id}] 收到快速对话请求: {chat_request.question}")
        _append_session_message(
            chat_request.id,
            role="user",
            content=chat_request.question,
            metadata={"source": "chat"},
        )
        response = await chat_adapter.chat(chat_request, http_request.headers)
        answer = response.get("data", {}).get("answer") if isinstance(response, dict) else None
        if answer:
            _append_session_message(
                chat_request.id,
                role="assistant",
                content=answer,
                metadata={"source": "chat"},
            )
        logger.info(f"[会话 {chat_request.id}] 快速对话完成")
        return response
    except RequestBlocked as exc:
        error_event = build_error_event(
            map_exception_to_error_context(exc, stage="guardrail"),
            trace_id=exc.trace_id,
            request_id=getattr(exc, "request_id", ""),
        )
        return JSONResponse(
            status_code=403,
            content={
                "code": 403,
                "message": "blocked",
                "data": {
                    "success": False,
                    "reason": exc.reason,
                    "trace_id": exc.trace_id,
                    "request_id": getattr(exc, "request_id", ""),
                    "error_class": error_event["error_class"],
                    "decision": error_event["decision"],
                    "user_message": error_event["data"]["user_message"],
                    "errorMessage": exc.reason,
                },
            },
        )
    except Exception as e:
        logger.error(f"对话接口错误: {e}")
        return {
            "code": 500,
            "message": "error",
            "data": {
                "success": False,
                "answer": None,
                "errorMessage": str(e)
            }
        }


@router.post("/chat_stream")
async def chat_stream(chat_request: ChatRequest, http_request: Request, current_user: CurrentUser):
    """流式对话接口（基于 RAG Agent，SSE）

    返回 SSE 格式，data 字段为 JSON：

    工具调用事件:
    event: message
    data: {"type":"tool_call","data":{"tool":"工具名","status":"start|end","input":{...}}}

    内容流式事件:
    event: message
    data: {"type":"content","data":"内容块"}

    完成事件:
    event: message
    data: {"type":"done","data":{"answer":"完整答案","tool_calls":[...]}}

    Args:
        request: 对话请求

    Returns:
        SSE 事件流
    """
    _assert_or_claim_session(
        chat_request.id,
        current_user.user_id,
        route="chat_stream",
        title=chat_request.question,
    )
    logger.info(f"[会话 {chat_request.id}] 收到流式对话请求: {chat_request.question}")
    _append_session_message(
        chat_request.id,
        role="user",
        content=chat_request.question,
        metadata={"source": "chat_stream"},
    )

    async def event_generator():
        last_trace_id = http_request.headers.get("X-Trace-Id") or str(uuid4())
        last_request_id = http_request.headers.get("X-Request-Id") or str(uuid4())
        full_response = ""
        persisted_assistant = False

        def sse_message(payload: dict) -> dict:
            nonlocal last_trace_id, last_request_id
            if payload.get("trace_id"):
                last_trace_id = payload["trace_id"]
            else:
                payload["trace_id"] = last_trace_id
            if payload.get("request_id"):
                last_request_id = payload["request_id"]
            else:
                payload["request_id"] = last_request_id
            return {
                "event": "message",
                "data": json.dumps(normalize_sse_event(payload), ensure_ascii=False),
            }

        try:
            async for chunk in chat_adapter.chat_stream(chat_request, http_request.headers):
                chunk_type = chunk.get("type", "unknown")
                chunk_data = chunk.get("data", None)
                trace_id = chunk.get("trace_id")
                request_id = chunk.get("request_id")

                def with_context_ids(
                    payload: dict,
                    current_trace_id: str | None = trace_id,
                    current_request_id: str | None = request_id,
                ) -> dict:
                    if current_trace_id:
                        payload["trace_id"] = current_trace_id
                    if current_request_id:
                        payload["request_id"] = current_request_id
                    return payload

                # 处理调试类型消息（新增）
                if chunk_type == "debug":
                    # 调试信息，可以选择发送或忽略
                    yield sse_message(
                        with_context_ids({
                            "type": "debug",
                            "node": chunk.get("node", "unknown"),
                            "message_type": chunk.get("message_type", "unknown")
                        })
                    )
                elif chunk_type == "tool_call":
                    # 发送工具调用事件（可选，前端可以显示工具调用状态）
                    yield sse_message(
                        with_context_ids({
                            "type": "tool_call",
                            "data": chunk_data
                        })
                    )
                elif chunk_type == "search_results":
                    # 发送检索结果（可选，前端可以忽略）
                    yield sse_message(
                        with_context_ids({
                            "type": "search_results",
                            "data": chunk_data
                        })
                    )
                elif chunk_type == "query_intent_diagnostics":
                    yield sse_message(
                        with_context_ids({
                            "type": "query_intent_diagnostics",
                            "data": chunk_data,
                            "node": chunk.get("node", "query_intent_orchestrator"),
                        })
                    )
                elif chunk_type == "content":
                    if chunk_data:
                        full_response += str(chunk_data)
                    # 发送内容块 - 关键：data 必须是 JSON 字符串
                    yield sse_message(
                        with_context_ids({
                            "type": "content",
                            "data": chunk_data
                        })
                    )
                elif chunk_type == "complete":
                    answer = ""
                    if isinstance(chunk_data, dict):
                        answer = str(chunk_data.get("answer") or "")
                    answer = answer or full_response
                    if answer and not persisted_assistant:
                        _append_session_message(
                            chat_request.id,
                            role="assistant",
                            content=answer,
                            metadata={"source": "chat_stream"},
                        )
                        persisted_assistant = True
                    # 发送完成信号
                    yield sse_message(
                        with_context_ids({
                            "type": "done",
                            "data": chunk_data
                        })
                    )
                elif chunk_type == "error":
                    # 发送错误信息
                    payload = {**chunk, "type": "error"}
                    if "data" not in payload:
                        payload["data"] = str(chunk_data)
                    yield sse_message(
                        with_context_ids(payload)
                    )
                elif chunk_type == "blocked":
                    payload = {**chunk, "type": "blocked"}
                    if "data" not in payload:
                        payload["data"] = chunk_data
                    yield sse_message(
                        with_context_ids(payload)
                    )

            logger.info(f"[会话 {chat_request.id}] 流式对话完成")
            if full_response and not persisted_assistant:
                _append_session_message(
                    chat_request.id,
                    role="assistant",
                    content=full_response,
                    metadata={"source": "chat_stream", "degraded": True},
                )

        except Exception as e:
            logger.error(f"流式对话接口错误: {e}")
            yield sse_message(
                build_error_event(
                    map_exception_to_error_context(e, stage="chat_stream"),
                    trace_id=last_trace_id,
                    request_id=last_request_id,
                )
            )

    return EventSourceResponse(event_generator())


@router.post("/chat/clear", response_model=ApiResponse)
async def clear_session(request: ClearRequest, http_request: Request, current_user: CurrentUser):
    """清空会话历史

    Args:
        request: 清空请求

    Returns:
        操作结果
    """
    _assert_session_owner(
        request.session_id,
        current_user.user_id,
        route="chat_session",
        action="clear",
    )
    try:
        clear_result = await chat_adapter.clear_session(request.session_id, http_request.headers)
        legacy_success = bool(clear_result.get("success"))
        context = _current_context_or_500()
        session_access.audit_service = chat_adapter.gateway.audit_service
        archive_success = session_access.archive(context, request.session_id)
        success = bool(legacy_success or archive_success)
        logger.info(f"清空会话: {request.session_id}, 结果: {success}")

        return ApiResponse(
            status="success" if success else "error",
            message="会话已清空" if success else "清空会话失败",
            data=None
        )

    except Exception as e:
        logger.error(f"清空会话错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/chat/session/{session_id}", response_model=SessionInfoResponse)
async def get_session_info(session_id: str, current_user: CurrentUser) -> SessionInfoResponse:
    """查询会话历史

    Args:
        session_id: 会话 ID

    Returns:
        会话信息
    """
    _assert_session_owner(
        session_id,
        current_user.user_id,
        route="chat_session",
        action="read",
    )
    try:
        context = _current_context_or_500()
        session_access.audit_service = chat_adapter.gateway.audit_service
        messages = session_access.get_messages(context, session_id)

        return SessionInfoResponse(
            session_id=session_id,
            message_count=len(messages),
            history=[_message_payload(message) for message in messages],
        )

    except Exception as e:
        logger.error(f"获取会话信息错误: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/chat/sessions")
async def list_chat_sessions(current_user: CurrentUser):
    """List persistent chat sessions for the current user."""
    del current_user
    context = _current_context_or_500()
    session_access.audit_service = chat_adapter.gateway.audit_service
    sessions = session_access.list_by_user(context)
    return {
        "code": 200,
        "message": "success",
        "data": {
            "sessions": [_session_payload(session) for session in sessions],
        },
    }
