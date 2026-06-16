"""
AIOps Agent 通用工具函数
"""

import asyncio
import traceback
import time
from typing import Any, List

from loguru import logger


def format_tools_description(tools: List) -> str:
    """格式化工具列表为描述文本"""
    tool_descriptions = []
    for tool in tools:
        if hasattr(tool, 'name') and hasattr(tool, 'description'):
            tool_descriptions.append(f"- {tool.name}: {tool.description}")
    return "\n".join(tool_descriptions)


async def await_with_optional_timeout(
    awaitable: Any,
    timeout_seconds: float | None,
    stage: str,
    eval_deadline_monotonic: float | None = None,
    deadline_guard_seconds: float = 2.0,
) -> Any:
    """Apply an eval-only timeout to one awaited node operation."""
    effective_timeout = timeout_seconds
    if eval_deadline_monotonic is not None:
        remaining_seconds = eval_deadline_monotonic - time.monotonic() - deadline_guard_seconds
        if effective_timeout is None or effective_timeout <= 0:
            effective_timeout = remaining_seconds
        else:
            effective_timeout = min(effective_timeout, remaining_seconds)

    if effective_timeout is None or effective_timeout <= 0:
        if eval_deadline_monotonic is not None:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise TimeoutError(
                f"{stage} timed out before start; eval deadline exhausted"
            )
        return await awaitable

    try:
        return await asyncio.wait_for(awaitable, timeout=effective_timeout)
    except TimeoutError as exc:
        raise TimeoutError(f"{stage} timed out after {effective_timeout:.3f}s") from exc


async def invoke_structured_with_retry(
    chain: Any,
    payload: dict[str, Any],
    stage: str,
    attempts: int = 2,
    timeout_seconds: float | None = None,
    eval_deadline_monotonic: float | None = None,
) -> Any:
    """Invoke a structured-output chain and retry when the parser returns None."""
    last_result = None
    for attempt in range(1, attempts + 1):
        last_result = await await_with_optional_timeout(
            chain.ainvoke(payload),
            timeout_seconds,
            f"{stage} structured output",
            eval_deadline_monotonic=eval_deadline_monotonic,
        )
        if last_result is not None:
            return last_result
        logger.warning(
            "{} structured output returned None (attempt {}/{})",
            stage,
            attempt,
            attempts,
        )

    raise ValueError(f"{stage} structured output returned None after {attempts} attempts")


async def invoke_structured_with_fallback(
    primary_chain: Any,
    fallback_chain: Any,
    payload: dict[str, Any],
    stage: str,
    fallback_payload: dict[str, Any] | None = None,
    attempts: int = 2,
    timeout_seconds: float | None = None,
    eval_deadline_monotonic: float | None = None,
    return_diagnostics: bool = False,
) -> Any:
    """Invoke structured output with a second strategy before declaring infra failure."""
    primary_error = ""
    primary_error_type = ""
    started_at = time.monotonic()
    try:
        result = await invoke_structured_with_retry(
            primary_chain,
            payload,
            stage=stage,
            attempts=attempts,
            timeout_seconds=timeout_seconds,
            eval_deadline_monotonic=eval_deadline_monotonic,
        )
        if return_diagnostics:
            return result, {
                "structured_output_recovered": False,
                "structured_output_fallback_used": False,
                "structured_output_primary_stage": stage,
                "structured_output_fallback_stage": f"{stage}_fallback",
                "structured_output_total_elapsed_ms": round(
                    (time.monotonic() - started_at) * 1000,
                    3,
                ),
            }
        return result
    except Exception as primary_exc:
        primary_error_type = type(primary_exc).__name__
        primary_error = f"{type(primary_exc).__name__}: {primary_exc}"
        logger.warning(
            "{} primary structured output failed, trying fallback: {}",
            stage,
            primary_exc,
        )

    try:
        result = await invoke_structured_with_retry(
            fallback_chain,
            fallback_payload or payload,
            stage=f"{stage}_fallback",
            attempts=attempts,
            timeout_seconds=timeout_seconds,
            eval_deadline_monotonic=eval_deadline_monotonic,
        )
        if return_diagnostics:
            return result, {
                "structured_output_recovered": True,
                "structured_output_fallback_used": True,
                "structured_output_primary_error": primary_error,
                "structured_output_primary_error_type": primary_error_type,
                "structured_output_primary_stage": stage,
                "structured_output_fallback_stage": f"{stage}_fallback",
                "structured_output_total_elapsed_ms": round(
                    (time.monotonic() - started_at) * 1000,
                    3,
                ),
            }
        return result
    except Exception as fallback_exc:
        raise RuntimeError(
            f"{stage} structured output failed in primary and fallback; "
            f"primary={primary_error}; "
            f"fallback={type(fallback_exc).__name__}: {fallback_exc}"
        ) from fallback_exc


def format_traceback_for_infra(exc: BaseException) -> str:
    """Return the full traceback text for eval/debug reports."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
