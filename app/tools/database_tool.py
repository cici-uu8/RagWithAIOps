"""Read-only database tools exposed to the RAG agent."""

from typing import Any

from langchain_core.tools import tool
from loguru import logger

from app.enterprise.context import get_current_request_context
from app.enterprise.database.context_builder import DatabaseContextBuilder
from app.enterprise.database.error_hints import (
    build_safe_sql_error_hint,
    format_safe_sql_blocked_message,
)
from app.enterprise.database.safe_sql import DatabaseExecutionError, SafeSqlBlocked
from app.enterprise.tools.gateway import ToolAccessDenied, ToolExecutionError


@tool
async def list_database_tables(database_id: str = "sandbox_sales") -> dict[str, Any]:
    """列出当前用户有权限查看的数据库表。

    Args:
        database_id: 数据源 ID，默认 sandbox_sales；真实 MySQL 只读源使用配置中的 database_id。

    Returns:
        结构化表清单。无权限时返回 status=denied，不生成数据库确认项。
    """

    return await _execute_read_only_database_tool(database_id, "list_tables", {})


@tool
async def describe_database_table(
    table_name: str,
    database_id: str = "sandbox_sales",
) -> dict[str, Any]:
    """查看当前用户有权限访问的数据库表结构。

    Args:
        table_name: 表名。
        database_id: 数据源 ID，默认 sandbox_sales；真实 MySQL 只读源使用配置中的 database_id。

    Returns:
        结构化表字段信息。只返回当前用户有权限查看的列。
    """

    return await _execute_read_only_database_tool(
        database_id,
        "describe_table",
        {"table_name": table_name},
    )


@tool
async def safe_select_database(
    sql: str,
    database_id: str = "sandbox_sales",
) -> dict[str, Any]:
    """执行受权限和 SQL kernel 保护的只读 SELECT 查询。

    Args:
        sql: 单条只读 SELECT 语句。UPDATE、DELETE、DROP 等写入或 DDL 会被后端阻断。
        database_id: 数据源 ID，默认 sandbox_sales；真实 MySQL 只读源使用配置中的 database_id。

    Returns:
        查询结果或结构化拒绝原因。不会执行写入、删除、DDL，也不会生成确认项。
    """

    return await _execute_read_only_database_tool(database_id, "safe_select", {"sql": sql})


@tool
async def retrieve_database_context(
    query: str,
    database_id: str = "sandbox_sales",
) -> dict[str, Any]:
    """检索当前用户可见的数据库上下文，用于辅助生成安全 SQL。

    Args:
        query: 用户的自然语言数据库问题。
        database_id: 数据源 ID，默认 sandbox_sales。

    Returns:
        结构化上下文，包含相关 Q-SQL 示例、已授权表列和安全限制。不执行 SQL。
    """

    normalized_database_id = (database_id or "sandbox_sales").strip() or "sandbox_sales"
    tool_id = _database_tool_id(normalized_database_id, "retrieve_context")
    context = get_current_request_context()
    if context is None:
        return _tool_result(
            status="error",
            reason="request_context_missing",
            database_id=normalized_database_id,
            tool_id=tool_id,
            message="当前请求缺少用户上下文，无法检索数据库上下文。",
        )

    from app.enterprise.database.routes import get_database_tool_gateway

    gateway = get_database_tool_gateway()
    context_payload = DatabaseContextBuilder(
        permission_service=gateway.permission_service,
    ).build_context(
        context,
        question=query,
        database_id=normalized_database_id,
    )
    context_payload["tool_id"] = tool_id
    return context_payload


async def _execute_read_only_database_tool(
    database_id: str,
    operation: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    normalized_database_id = (database_id or "sandbox_sales").strip() or "sandbox_sales"
    tool_id = _database_tool_id(normalized_database_id, operation)
    context = get_current_request_context()
    if context is None:
        return _tool_result(
            status="error",
            reason="request_context_missing",
            database_id=normalized_database_id,
            tool_id=tool_id,
            message="当前请求缺少用户上下文，无法查询数据库。",
        )

    try:
        from app.enterprise.database.routes import get_database_tool_gateway

        result = await get_database_tool_gateway().execute(context, tool_id, arguments)
    except ToolAccessDenied as exc:
        return _tool_result(
            status="denied",
            reason=exc.reason,
            database_id=normalized_database_id,
            tool_id=tool_id,
            message="当前用户没有使用该数据库工具的权限。",
        )
    except ToolExecutionError as exc:
        logger.warning("RAG database tool failed: tool_id={}, error={}", tool_id, exc)
        if isinstance(exc.cause, SafeSqlBlocked):
            sql = str(arguments.get("sql", "")) if operation == "safe_select" else ""
            return _tool_result(
                status="denied",
                reason=exc.cause.reason,
                database_id=normalized_database_id,
                tool_id=tool_id,
                message=format_safe_sql_blocked_message(exc.cause.reason, sql=sql),
                error_hint=build_safe_sql_error_hint(exc.cause.reason, sql=sql),
            )
        if isinstance(exc.cause, DatabaseExecutionError):
            return _tool_result(
                status="error",
                reason="database_execution_failed",
                database_id=normalized_database_id,
                tool_id=tool_id,
                message="数据库执行失败。",
            )
        return _tool_result(
            status="error",
            reason="database_tool_execution_failed",
            database_id=normalized_database_id,
            tool_id=tool_id,
            message="数据库工具执行失败。",
        )

    if isinstance(result, dict):
        return result
    return _tool_result(
        status="success",
        reason="",
        database_id=normalized_database_id,
        tool_id=tool_id,
        result=result,
    )


def _database_tool_id(database_id: str, operation: str) -> str:
    if database_id == "sandbox_sales":
        return f"database_demo.{operation}"
    return f"database_mysql.{database_id}.{operation}"


def _tool_result(
    *,
    status: str,
    reason: str,
    database_id: str,
    tool_id: str,
    message: str = "",
    result: Any | None = None,
    error_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "reason": reason,
        "database_id": database_id,
        "tool_id": tool_id,
    }
    if message:
        payload["message"] = message
    if result is not None:
        payload["result"] = result
    if error_hint is not None:
        payload["error_hint"] = error_hint
    return payload
