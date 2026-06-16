"""
MCP 客户端管理
提供全局单例的 MCP 客户端，避免重复初始化
"""

import asyncio
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from loguru import logger
from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT, MCP_DEFAULT_TIMEOUT
from mcp.types import CallToolResult, TextContent

from app.config import config

# 全局 MCP 客户端（延迟初始化）
_mcp_client: MultiServerMCPClient | None = None
_MCP_TOOLS_CACHE_TTL_SECONDS = 300.0
_mcp_tools_cache: tuple[float, tuple[Any, ...]] | None = None


def _new_mcp_tools_metrics() -> dict[str, Any]:
    return {
        "cache_hits": 0,
        "cache_misses": 0,
        "get_tools_attempts": 0,
        "get_tools_successes": 0,
        "get_tools_failures": 0,
        "fresh_retries": 0,
        "fresh_retry_successes": 0,
        "fresh_retry_failures": 0,
        "last_tool_count": None,
        "last_error": None,
        "get_tools_latency_ms_count": 0,
        "get_tools_latency_ms_total": 0.0,
        "get_tools_latency_ms_last": None,
        "get_tools_latency_ms_min": None,
        "get_tools_latency_ms_max": None,
    }


_mcp_tools_metrics: dict[str, Any] = _new_mcp_tools_metrics()


def _clear_mcp_tools_cache() -> None:
    """Clear cached MCP tools. Intended for tests and explicit refresh paths."""
    global _mcp_tools_cache
    _mcp_tools_cache = None


def _reset_mcp_tools_metrics() -> None:
    """Reset MCP tool discovery metrics. Intended for tests and eval setup."""
    _mcp_tools_metrics.clear()
    _mcp_tools_metrics.update(_new_mcp_tools_metrics())


def _round_latency_ms(value: float) -> float:
    return round(max(value, 0.0), 3)


def _record_mcp_tools_cache_hit(tool_count: int) -> None:
    _mcp_tools_metrics["cache_hits"] += 1
    _mcp_tools_metrics["last_tool_count"] = tool_count
    _mcp_tools_metrics["last_error"] = None


def _record_mcp_tools_cache_miss() -> None:
    _mcp_tools_metrics["cache_misses"] += 1


def _record_mcp_tools_fresh_retry() -> None:
    _mcp_tools_metrics["fresh_retries"] += 1


def _record_mcp_tools_get_tools_attempt(
    *,
    success: bool,
    latency_ms: float,
    fresh_retry: bool,
    tool_count: int | None = None,
    error: BaseException | None = None,
) -> None:
    latency_ms = _round_latency_ms(latency_ms)
    _mcp_tools_metrics["get_tools_attempts"] += 1
    _mcp_tools_metrics["get_tools_latency_ms_count"] += 1
    _mcp_tools_metrics["get_tools_latency_ms_total"] += latency_ms
    _mcp_tools_metrics["get_tools_latency_ms_last"] = latency_ms

    current_min = _mcp_tools_metrics["get_tools_latency_ms_min"]
    current_max = _mcp_tools_metrics["get_tools_latency_ms_max"]
    _mcp_tools_metrics["get_tools_latency_ms_min"] = (
        latency_ms if current_min is None else min(current_min, latency_ms)
    )
    _mcp_tools_metrics["get_tools_latency_ms_max"] = (
        latency_ms if current_max is None else max(current_max, latency_ms)
    )

    if success:
        _mcp_tools_metrics["get_tools_successes"] += 1
        _mcp_tools_metrics["last_tool_count"] = tool_count
        _mcp_tools_metrics["last_error"] = None
        if fresh_retry:
            _mcp_tools_metrics["fresh_retry_successes"] += 1
        return

    _mcp_tools_metrics["get_tools_failures"] += 1
    _mcp_tools_metrics["last_error"] = (
        format_exception_for_infra(error) if error is not None else "unknown_error"
    )
    if fresh_retry:
        _mcp_tools_metrics["fresh_retry_failures"] += 1


def get_mcp_tools_metrics() -> dict[str, Any]:
    """Return a JSON-friendly snapshot of MCP tool discovery metrics."""
    snapshot = dict(_mcp_tools_metrics)
    latency_count = int(snapshot.pop("get_tools_latency_ms_count"))
    latency_total = float(snapshot.pop("get_tools_latency_ms_total"))
    latency_last = snapshot.pop("get_tools_latency_ms_last")
    latency_min = snapshot.pop("get_tools_latency_ms_min")
    latency_max = snapshot.pop("get_tools_latency_ms_max")
    latency_avg = None
    if latency_count:
        latency_avg = _round_latency_ms(latency_total / latency_count)

    snapshot["get_tools_latency_ms"] = {
        "count": latency_count,
        "last": latency_last,
        "avg": latency_avg,
        "min": latency_min,
        "max": latency_max,
    }
    return snapshot


def _should_use_mcp_tools_cache(
    servers: dict[str, dict[str, str]] | None,
    tool_interceptors: list | None,
    force_new_first: bool,
) -> bool:
    return servers is None and tool_interceptors is None and not force_new_first


def _get_cached_mcp_tools(now: float | None = None) -> list[Any] | None:
    """Return cached MCP tools if the TTL is still valid."""
    global _mcp_tools_cache
    if _mcp_tools_cache is None:
        return None

    cached_at, cached_tools = _mcp_tools_cache
    current_time = now if now is not None else time.monotonic()
    if current_time - cached_at > _MCP_TOOLS_CACHE_TTL_SECONDS:
        _mcp_tools_cache = None
        return None

    return list(cached_tools)


def _store_cached_mcp_tools(tools: list[Any]) -> None:
    """Store MCP tools in the process cache."""
    global _mcp_tools_cache
    _mcp_tools_cache = (time.monotonic(), tuple(tools))


async def retry_interceptor(
    request: MCPToolCallRequest,
    handler,
    max_retries: int = 3,
    delay: float = 1.0,
):
    """MCP 工具调用重试拦截器

    当工具调用失败时，使用指数退避策略自动重试。
    如果所有重试都失败，返回包含错误信息的结果而不是抛出异常。

    MCPToolCallRequest 结构：
    - name: str - 工具名称
    - args: dict[str, Any] - 工具参数
    - server_name: str - 服务器名称

    Args:
        request: MCP 工具调用请求
        handler: 实际的工具调用处理器
        max_retries: 最大重试次数（默认3次）
        delay: 初始延迟时间（秒，默认1秒）

    Returns:
        CallToolResult: 工具调用结果或错误信息
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.info(
                f"调用 MCP 工具: {request.name} "
                f"(服务器: {request.server_name}, 第 {attempt + 1}/{max_retries} 次尝试)"
            )
            result = await handler(request)
            logger.info(f"MCP 工具 {request.name} 调用成功")
            return result

        except Exception as e:
            last_error = e
            logger.warning(
                f"MCP 工具 {request.name} 调用失败 "
                f"(第 {attempt + 1}/{max_retries} 次): {str(e)}"
            )

            # 如果不是最后一次尝试，等待后重试
            if attempt < max_retries - 1:
                wait_time = delay * (2 ** attempt)  # 指数退避
                logger.info(f"等待 {wait_time:.1f} 秒后重试...")
                await asyncio.sleep(wait_time)

    # 所有重试都失败，返回错误结果而不是抛出异常
    error_msg = f"工具 {request.name} 在 {max_retries} 次重试后仍然失败: {str(last_error)}"
    logger.error(error_msg)
    return CallToolResult(
        content=[TextContent(type="text", text=error_msg)],
        isError=True
    )


# 使用配置文件中定义的完整 MCP 服务器配置
DEFAULT_MCP_SERVERS = config.mcp_servers


def _local_mcp_httpx_client_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """Create an MCP HTTP client that bypasses proxy env vars for localhost."""
    kwargs: dict[str, Any] = {
        "follow_redirects": True,
        "trust_env": False,
        "timeout": timeout or httpx.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT),
    }
    if headers is not None:
        kwargs["headers"] = headers
    if auth is not None:
        kwargs["auth"] = auth
    return httpx.AsyncClient(**kwargs)


def _is_local_url(url: str) -> bool:
    hostname = urlparse(url).hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _with_localhost_proxy_bypass(
    servers: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Copy MCP server config and make local HTTP transports ignore proxy env vars."""
    normalized = {}
    for server_name, server_config in servers.items():
        copied = dict(server_config)
        transport = copied.get("transport")
        url = str(copied.get("url", ""))

        if (
            transport in {"sse", "streamable_http", "streamable-http", "http"}
            and _is_local_url(url)
            and "httpx_client_factory" not in copied
        ):
            copied["httpx_client_factory"] = _local_mcp_httpx_client_factory

        normalized[server_name] = copied
    return normalized


async def get_mcp_client(
    servers: dict[str, dict[str, str]] | None = None,
    tool_interceptors: list | None = None,
    force_new: bool = False
) -> MultiServerMCPClient:
    """
    获取或初始化 MCP 客户端（不带重试拦截器）

    这是一个单例模式，确保整个应用只有一个 MCP 客户端实例（除非 force_new=True）

    从 langchain-mcp-adapters 0.1.0 开始，MultiServerMCPClient 不再支持作为上下文管理器使用。
    直接创建实例即可使用。

    Args:
        servers: MCP 服务器配置，默认使用 DEFAULT_MCP_SERVERS
        tool_interceptors: 自定义工具拦截器列表
        force_new: 是否强制创建新实例（用于特殊场景，如需要不同配置）

    Returns:
        MultiServerMCPClient: MCP 客户端实例
    """
    global _mcp_client

    # 如果请求新实例，直接创建并返回（不缓存）
    if force_new:
        logger.info("创建新的 MCP 客户端实例（非单例）")
        client = _create_mcp_client(
            _with_localhost_proxy_bypass(servers or DEFAULT_MCP_SERVERS),
            tool_interceptors
        )
        # 不再需要 __aenter__()，直接返回即可
        return client

    # 单例模式：如果已存在，直接返回
    if _mcp_client is None:
        logger.info("初始化全局 MCP 客户端...")
        _mcp_client = _create_mcp_client(
            _with_localhost_proxy_bypass(servers or DEFAULT_MCP_SERVERS),
            tool_interceptors
        )
        # 不再需要 __aenter__()，直接使用即可
        logger.info("全局 MCP 客户端初始化完成")

    return _mcp_client


async def get_mcp_client_with_retry(
    servers: dict[str, dict[str, str]] | None = None,
    tool_interceptors: list | None = None,
    force_new: bool = False
) -> MultiServerMCPClient:
    """
    获取或初始化带重试功能的 MCP 客户端

    这是一个单例模式，确保整个应用只有一个 MCP 客户端实例（除非 force_new=True）
    重试拦截器会自动添加到拦截器列表的开头

    Args:
        servers: MCP 服务器配置，默认使用 DEFAULT_MCP_SERVERS
        tool_interceptors: 自定义工具拦截器列表（会在重试拦截器之后添加）
        force_new: 是否强制创建新实例（用于特殊场景，如需要不同配置）

    Returns:
        MultiServerMCPClient: 带重试功能的 MCP 客户端实例
    """
    # 构建拦截器列表：重试拦截器在最前面
    interceptors = [retry_interceptor]
    if tool_interceptors:
        interceptors.extend(tool_interceptors)

    return await get_mcp_client(
        servers=servers,
        tool_interceptors=interceptors,
        force_new=force_new
    )


def format_exception_for_infra(exc: BaseException) -> str:
    """Return an infra-friendly exception string, including ExceptionGroup detail."""
    if isinstance(exc, BaseExceptionGroup):
        sub_errors = [
            f"{type(sub_exc).__name__}: {sub_exc}"
            for sub_exc in exc.exceptions[:3]
        ]
        suffix = "; ".join(sub_errors)
        if len(exc.exceptions) > 3:
            suffix += f"; ... {len(exc.exceptions) - 3} more"
        return f"{type(exc).__name__}: {exc}; sub-exceptions: {suffix}"
    return f"{type(exc).__name__}: {exc}"


def _len_or_none(value: Any) -> int | None:
    try:
        return len(value)
    except TypeError:
        return None


async def _get_tools_with_metrics(client: Any, *, fresh_retry: bool):
    started_at = time.perf_counter()
    try:
        tools = await client.get_tools()
    except Exception as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000
        _record_mcp_tools_get_tools_attempt(
            success=False,
            latency_ms=latency_ms,
            fresh_retry=fresh_retry,
            error=exc,
        )
        logger.info(
            "MCP get_tools metrics event=failure fresh_retry={} snapshot={}",
            fresh_retry,
            get_mcp_tools_metrics(),
        )
        raise

    latency_ms = (time.perf_counter() - started_at) * 1000
    _record_mcp_tools_get_tools_attempt(
        success=True,
        latency_ms=latency_ms,
        fresh_retry=fresh_retry,
        tool_count=_len_or_none(tools),
    )
    logger.info(
        "MCP get_tools metrics event=success fresh_retry={} snapshot={}",
        fresh_retry,
        get_mcp_tools_metrics(),
    )
    return tools


async def get_mcp_tools_with_retry(
    servers: dict[str, dict[str, str]] | None = None,
    tool_interceptors: list | None = None,
    force_new_first: bool = False,
):
    """Fetch MCP tools, retrying once with a fresh client if the singleton is stale."""
    use_cache = _should_use_mcp_tools_cache(servers, tool_interceptors, force_new_first)
    if use_cache:
        cached_tools = _get_cached_mcp_tools()
        if cached_tools is not None:
            _record_mcp_tools_cache_hit(len(cached_tools))
            logger.info("Reusing cached MCP tools (count={})", len(cached_tools))
            logger.info("MCP tools cache metrics event=hit snapshot={}", get_mcp_tools_metrics())
            return cached_tools
        _record_mcp_tools_cache_miss()
        logger.info("MCP tools cache metrics event=miss snapshot={}", get_mcp_tools_metrics())

    try:
        client = await get_mcp_client_with_retry(
            servers=servers,
            tool_interceptors=tool_interceptors,
            force_new=force_new_first,
        )
        tools = await _get_tools_with_metrics(client, fresh_retry=False)
        if use_cache:
            _store_cached_mcp_tools(tools)
        return tools
    except Exception as first_exc:
        if force_new_first:
            raise

        logger.warning(
            "MCP get_tools() failed on cached client, retrying with a fresh client: {}",
            format_exception_for_infra(first_exc),
        )
        _record_mcp_tools_fresh_retry()
        client = await get_mcp_client_with_retry(
            servers=servers,
            tool_interceptors=tool_interceptors,
            force_new=True,
        )
        tools = await _get_tools_with_metrics(client, fresh_retry=True)
        if use_cache:
            _store_cached_mcp_tools(tools)
        return tools


def _create_mcp_client(
    servers: dict[str, dict[str, str]],
    tool_interceptors: list | None = None
) -> MultiServerMCPClient:
    """
    创建 MCP 客户端实例

    Args:
        servers: MCP 服务器配置
        tool_interceptors: 工具拦截器列表

    Returns:
        MultiServerMCPClient: 未初始化的客户端实例
    """
    # MultiServerMCPClient 的第一个参数直接接收 servers 配置字典
    # 格式: {server_name: {"transport": "...", "url": "..."}}
    kwargs: dict[str, Any] = {}

    if tool_interceptors:
        kwargs["tool_interceptors"] = tool_interceptors

    # 第一个参数是 servers 配置，直接传递
    return MultiServerMCPClient(servers, **kwargs)  # type: ignore[arg-type]
