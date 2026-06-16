"""Read-only database tools exposed to the RAG agent."""

from typing import Any

from langchain_core.tools import tool
from loguru import logger

from app.enterprise.context import get_current_request_context
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
            return _tool_result(
                status="denied",
                reason=exc.cause.reason,
                database_id=normalized_database_id,
                tool_id=tool_id,
                message="数据库查询被安全策略阻断。",
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
    return payload
