"""Deterministic recovery decisions for enterprise failures."""

from __future__ import annotations

from app.enterprise.errors.models import ErrorClass, ErrorContext, RecoveryDecision, RecoveryPlan

_SECURITY_BLOCKING = {
    ErrorClass.AUTH_FAILED,
    ErrorClass.PERMISSION_DENIED,
    ErrorClass.GUARDRAIL_BLOCKED,
    ErrorClass.SQL_BLOCKED,
}


class RecoveryStrategy:
    """Map a normalized error class to a user-safe recovery decision."""

    def decide(self, context: ErrorContext) -> RecoveryPlan:
        error_class = context.error_class
        if error_class == ErrorClass.AUTH_FAILED:
            return self._abort(context, "failed", "身份已失效，请重新登录。")
        if error_class == ErrorClass.PERMISSION_DENIED:
            return self._abort(context, "blocked", "你没有权限访问该资源。")
        if error_class == ErrorClass.GUARDRAIL_BLOCKED:
            return self._abort(context, "blocked", "请求被安全策略阻断。")
        if error_class == ErrorClass.SQL_BLOCKED:
            return self._abort(context, "blocked", "数据库查询被只读安全策略阻断。")
        if error_class == ErrorClass.MODEL_UNAVAILABLE:
            return self._model_decision(context)
        if error_class == ErrorClass.TOOL_FAILED:
            return self._tool_decision(context)
        if error_class == ErrorClass.RETRIEVAL_LOW_CONFIDENCE:
            return self._retrieval_decision(context)
        if error_class == ErrorClass.STREAM_INTERRUPTED:
            return RecoveryPlan(
                error_class=error_class,
                stage=context.stage,
                decision=RecoveryDecision.RECOVERABLE_ERROR,
                status="failed",
                user_message="流式响应已中断，可根据 trace 查询历史或重试。",
                recoverable=True,
                retryable=True,
                fallback_allowed=False,
                audit_category="system_failure",
                reason=context.reason,
            )
        return self._abort(context, "failed", "请求处理失败。")

    def _abort(self, context: ErrorContext, status: str, message: str) -> RecoveryPlan:
        return RecoveryPlan(
            error_class=context.error_class,
            stage=context.stage,
            decision=RecoveryDecision.ABORT,
            status=status,
            user_message=message,
            recoverable=False,
            retryable=False,
            fallback_allowed=False,
            audit_category=(
                "security_blocking"
                if context.error_class in _SECURITY_BLOCKING
                else "system_failure"
            ),
            reason=context.reason,
        )

    def _model_decision(self, context: ErrorContext) -> RecoveryPlan:
        fallback_available = bool(context.metadata.get("fallback_available"))
        if fallback_available:
            return RecoveryPlan(
                error_class=context.error_class,
                stage=context.stage,
                decision=RecoveryDecision.FALLBACK,
                status="degraded",
                user_message="主模型暂时不可用，正在使用备用模型。",
                recoverable=True,
                retryable=True,
                fallback_allowed=True,
                audit_category="degradation",
                reason=context.reason,
            )
        return RecoveryPlan(
            error_class=context.error_class,
            stage=context.stage,
            decision=RecoveryDecision.ABORT,
            status="failed",
            user_message="模型服务暂时不可用，请稍后重试。",
            recoverable=False,
            retryable=False,
            fallback_allowed=False,
            audit_category="system_failure",
            reason=context.reason,
        )

    def _tool_decision(self, context: ErrorContext) -> RecoveryPlan:
        if context.metadata.get("allow_partial"):
            return RecoveryPlan(
                error_class=context.error_class,
                stage=context.stage,
                decision=RecoveryDecision.PARTIAL,
                status="degraded",
                user_message="部分工具执行失败，已返回可用的部分结果。",
                recoverable=True,
                retryable=bool(context.metadata.get("retryable", True)),
                fallback_allowed=False,
                audit_category="degradation",
                reason=context.reason,
            )
        if context.metadata.get("retryable"):
            return RecoveryPlan(
                error_class=context.error_class,
                stage=context.stage,
                decision=RecoveryDecision.RETRY,
                status="retrying",
                user_message="工具暂时不可用，正在重试。",
                recoverable=True,
                retryable=True,
                fallback_allowed=False,
                audit_category="system_failure",
                reason=context.reason,
            )
        return RecoveryPlan(
            error_class=context.error_class,
            stage=context.stage,
            decision=RecoveryDecision.ABORT,
            status="failed",
            user_message="工具执行失败，请稍后重试或联系管理员查看审计记录。",
            recoverable=False,
            retryable=False,
            fallback_allowed=False,
            audit_category="system_failure",
            reason=context.reason,
        )

    def _retrieval_decision(self, context: ErrorContext) -> RecoveryPlan:
        has_partial_context = bool(context.metadata.get("has_partial_context"))
        return RecoveryPlan(
            error_class=context.error_class,
            stage=context.stage,
            decision=(
                RecoveryDecision.PARTIAL
                if has_partial_context
                else RecoveryDecision.REQUEST_MORE_INFO
            ),
            status="degraded",
            user_message=(
                "检索结果置信度较低，已基于有限资料回答。"
                if has_partial_context
                else "检索结果不足，请补充更多信息。"
            ),
            recoverable=True,
            retryable=False,
            fallback_allowed=False,
            audit_category="degradation",
            reason=context.reason,
        )
