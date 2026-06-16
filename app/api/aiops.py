"""
AIOps 智能运维接口
"""

import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.enterprise.adapters.aiops_adapter import AIOpsAdapter
from app.enterprise.auth.dependencies import CurrentUser
from app.enterprise.context import get_current_request_context
from app.enterprise.errors.mapper import build_error_event, map_exception_to_error_context
from app.enterprise.observability.sse_contract import normalize_sse_event
from app.enterprise.sessions.service import SessionAccessError, session_access
from app.models.aiops import AIOpsRequest
from app.services.aiops_service import aiops_service
from app.services.shadow_mode_metrics import shadow_metrics

router = APIRouter()
aiops_adapter = AIOpsAdapter(aiops_service)


def _effective_aiops_session_id(session_id: str | None, user_id: str) -> str:
    if not session_id or session_id == "default":
        return f"aiops:{user_id}:default"
    return session_id


@router.post("/aiops")
async def diagnose_stream(request: AIOpsRequest, http_request: Request, current_user: CurrentUser):
    """
    AIOps 故障诊断接口（流式 SSE）

    **功能说明：**
    - 自动获取当前系统的活动告警
    - 使用 Plan-Execute-Replan 模式进行智能诊断
    - 流式返回诊断过程和结果

    **SSE 事件类型：**

    1. `status` - 状态更新
       ```json
       {
         "type": "status",
         "stage": "fetching_alerts",
         "message": "正在获取系统告警信息..."
       }
       ```

    2. `plan` - 诊断计划制定完成
       ```json
       {
         "type": "plan",
         "stage": "plan_created",
         "message": "诊断计划已制定，共 6 个步骤",
         "target_alert": {...},
         "plan": ["步骤1: ...", "步骤2: ..."]
       }
       ```

    3. `step_complete` - 步骤执行完成
       ```json
       {
         "type": "step_complete",
         "stage": "step_executed",
         "message": "步骤执行完成 (2/6)",
         "current_step": "查询系统日志",
         "result_preview": "...",
         "remaining_steps": 4
       }
       ```

    4. `report` - 最终诊断报告
       ```json
       {
         "type": "report",
         "stage": "final_report",
         "message": "最终诊断报告已生成",
         "report": "# 故障诊断报告\\n...",
         "evidence": {...}
       }
       ```

    5. `complete` - 诊断完成
       ```json
       {
         "type": "complete",
         "stage": "diagnosis_complete",
         "message": "诊断流程完成",
         "diagnosis": {...}
       }
       ```

    6. `error` - 错误信息
       ```json
       {
         "type": "error",
         "stage": "error",
         "message": "诊断过程发生错误: ..."
       }
       ```

    **使用示例：**
    ```bash
    curl -X POST "http://localhost:9900/api/aiops" \\
      -H "Content-Type: application/json" \\
      -d '{"session_id": "session-123"}' \\
      --no-buffer
    ```

    **前端使用示例：**
    ```javascript
    const eventSource = new EventSource('/api/aiops');

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);

      if (data.type === 'plan') {
        console.log('诊断计划:', data.plan);
      } else if (data.type === 'step_complete') {
        console.log('步骤完成:', data.current_step);
      } else if (data.type === 'report') {
        console.log('最终报告:', data.report);
      } else if (data.type === 'complete') {
        console.log('诊断完成');
        eventSource.close();
      }
    };
    ```

    Args:
        request: AIOps 诊断请求

    Returns:
        SSE 事件流
    """
    session_id = _effective_aiops_session_id(request.session_id, current_user.user_id)
    context = get_current_request_context()
    if context is None:
        raise HTTPException(status_code=500, detail="request context is required")
    session_access.audit_service = aiops_adapter.gateway.audit_service
    try:
        session_access.claim_or_assert_owner(
            context,
            session_id,
            kind="aiops",
            title=request.query or "AIOps 诊断",
            route="aiops",
        )
    except SessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    session_access.append_message(
        context,
        session_id,
        role="user",
        content=request.query or "AIOps 诊断",
        metadata={"source": "aiops"},
    )

    # P5 Shadow Mode 流量控制
    from app.config import config
    from app.services.shadow_mode_controller import ShadowModeController

    # 解析白名单
    allowlist = [owner.strip() for owner in config.memory_shadow_allowlist.split(",") if owner.strip()]
    controller = ShadowModeController(
        allowlist=allowlist,
        sampling_rate=config.memory_shadow_sampling_rate
    )

    # 解析最终 memory_mode
    final_memory_mode = controller.resolve_memory_mode(
        requested_mode=request.memory_mode,
        owner_id=request.memory_owner_id,
        enable_memory_guidance=request.enable_memory_guidance
    )

    # 记录指标
    hit_allowlist = request.memory_owner_id in allowlist
    hit_sampling = (
        not hit_allowlist
        and request.memory_mode == "shadow"
        and final_memory_mode == "shadow"
    )
    shadow_metrics.record_request(
        memory_mode=final_memory_mode,
        owner_id=request.memory_owner_id or "unknown",
        hit_allowlist=hit_allowlist,
        hit_sampling=hit_sampling
    )

    logger.info(
        f"[会话 {session_id}] 收到 AIOps 诊断请求（流式）, "
        f"requested_mode={request.memory_mode}, final_mode={final_memory_mode}, "
        f"owner={request.memory_owner_id}"
    )

    async def event_generator():
        last_trace_id = http_request.headers.get("X-Trace-Id") or str(uuid4())
        last_request_id = http_request.headers.get("X-Request-Id") or str(uuid4())
        final_report = ""
        final_message = ""
        persisted_aiops_result = False

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
            async for event in aiops_adapter.diagnose_stream(
                request,
                headers=http_request.headers,
                session_id=session_id,
                memory_mode=final_memory_mode,
            ):
                if isinstance(event, dict):
                    if event.get("type") == "report":
                        final_report = str(
                            event.get("report")
                            or event.get("diagnosis")
                            or event.get("message")
                            or ""
                        )
                    elif event.get("type") == "complete":
                        final_message = str(
                            event.get("message")
                            or event.get("diagnosis")
                            or ""
                        )
                # 发送事件
                yield sse_message(event)

            logger.info(f"[会话 {session_id}] AIOps 诊断流式响应完成")
            result_content = final_report or final_message
            if result_content and not persisted_aiops_result:
                active_context = get_current_request_context() or context
                session_access.append_message(
                    active_context,
                    session_id,
                    role="assistant",
                    content=result_content,
                    metadata={"source": "aiops"},
                )
                persisted_aiops_result = True

        except Exception as e:
            logger.error(f"[会话 {session_id}] AIOps 诊断流式响应异常: {e}", exc_info=True)
            yield sse_message(
                build_error_event(
                    map_exception_to_error_context(e, stage="aiops_stream"),
                    trace_id=last_trace_id,
                    request_id=last_request_id,
                )
            )

    return EventSourceResponse(event_generator())
