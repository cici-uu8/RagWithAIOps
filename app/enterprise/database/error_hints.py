"""Friendly hints for SafeSqlBlocked reasons."""

from __future__ import annotations

from typing import Any

ERROR_HINTS: dict[str, dict[str, Any]] = {
    "parse_failed": {
        "message": "SQL 解析失败。",
        "suggestion": "请生成一条语法完整的单表 SELECT 语句，并先调用 retrieve_database_context 查看示例。",
        "example_ids": ["F01", "B01"],
    },
    "multi_statement_not_allowed": {
        "message": "禁止一次执行多条 SQL 语句。",
        "suggestion": "每次只提交一条 SELECT 查询。",
        "example_ids": ["F01"],
    },
    "non_select_statement_not_allowed": {
        "message": "当前数据库工具只允许 SELECT 查询。",
        "suggestion": "不要使用 INSERT、UPDATE、DELETE、DROP 或 CREATE。需要变更数据时走受控确认流程。",
        "example_ids": ["F01", "B01"],
    },
    "locking_select_not_allowed": {
        "message": "禁止使用带锁 SELECT。",
        "suggestion": "移除 FOR UPDATE / LOCK IN SHARE MODE 等锁语义，只做普通只读查询。",
        "example_ids": ["F01"],
    },
    "join_not_allowed": {
        "message": "禁止使用 JOIN 操作。",
        "suggestion": "当前安全策略只允许单表查询。如需多表信息，请拆成多次单表查询。",
        "example_ids": ["F01", "B01"],
    },
    "subquery_not_allowed": {
        "message": "禁止使用子查询或 UNION。",
        "suggestion": "请改写为简单单表 SELECT，并把复杂筛选放到应用层处理。",
        "example_ids": ["F03", "B01"],
    },
    "select_star_not_allowed": {
        "message": "禁止使用 SELECT *，必须显式列出列名。",
        "suggestion": "请调用 retrieve_database_context 查看已授权字段，然后显式列出需要的列。",
        "example_ids": ["F01", "B01"],
    },
    "function_not_allowed": {
        "message": "禁止使用 SQL 函数或聚合函数。",
        "suggestion": "当前策略不支持 COUNT/SUM/AVG/strftime 等函数。请先查询明细数据，再在应用层统计。",
        "example_ids": ["F01", "F04"],
    },
    "single_table_required": {
        "message": "查询必须明确且只引用一张表。",
        "suggestion": "请从 retrieve_database_context 返回的可见表中选择一张表，并生成单表 SELECT。",
        "example_ids": ["F01", "B01"],
    },
    "unauthorized_table": {
        "message": "查询的表不在当前数据库 allowlist 中。",
        "suggestion": "请调用 retrieve_database_context 查看可用表，当前门禁场景通常使用 factory_access_events 或 building_access_events。",
        "example_ids": ["F01", "B01"],
    },
    "columns_required": {
        "message": "查询必须包含至少一个明确字段。",
        "suggestion": "请显式列出需要的已授权列，不要生成空 SELECT 或只包含表达式的 SELECT。",
        "example_ids": ["F01"],
    },
    "unauthorized_column": {
        "message": "查询包含不在 allowlist 中或被禁止访问的字段。",
        "suggestion": "请调用 retrieve_database_context 或 describe_database_table 查看可查询字段，移除 raw_device_payload 等禁止字段。",
        "example_ids": ["F01", "B07"],
    },
    "limit_exceeds_max": {
        "message": "查询 LIMIT 超过当前安全上限。",
        "suggestion": "请降低 LIMIT，或省略 LIMIT 让系统使用默认上限。",
        "example_ids": ["F01", "B01"],
    },
    "column_alias_not_allowed": {
        "message": "禁止使用字段别名。",
        "suggestion": "请直接返回原始字段名，不要使用 AS 或别名表达式。",
        "example_ids": ["F01"],
    },
    "simple_column_select_required": {
        "message": "SELECT 列表只能包含简单字段。",
        "suggestion": "请不要在 SELECT 中使用表达式、计算列或函数；每一项都应是一个已授权字段名。",
        "example_ids": ["F01", "B01"],
    },
    "result_size_exceeds_max": {
        "message": "查询结果超过当前安全大小限制。",
        "suggestion": "请缩小时间范围、降低 LIMIT，或选择更少字段。",
        "example_ids": ["F01", "B01"],
    },
    "database_table_denied": {
        "message": "当前用户没有当前表的读取权限。",
        "suggestion": "请申请表级 read 权限，或改用 retrieve_database_context 中已经可见的表。",
        "example_ids": ["F01", "B01"],
    },
    "database_not_allowed": {
        "message": "当前数据库源不在受控 allowlist 中。",
        "suggestion": "请改用 sandbox_sales / database_demo，或先确认该数据库是否已纳入当前只读治理范围。",
        "example_ids": ["F01", "B01"],
    },
    "database_column_denied": {
        "message": "当前用户没有当前字段的读取权限。",
        "suggestion": "请调用 retrieve_database_context 查看已授权字段，并只查询返回列表中的列。",
        "example_ids": ["F01"],
    },
    "sql_result_verification_failed": {
        "message": "SQL 结果未通过授权列校验。",
        "suggestion": "请重新调用 retrieve_database_context，按当前授权列重新生成简单 SELECT。",
        "example_ids": ["F01"],
    },
}


def build_safe_sql_error_hint(reason: str, *, sql: str = "") -> dict[str, Any]:
    hint = ERROR_HINTS.get(
        reason,
        {
            "message": f"数据库查询被安全策略阻断：{reason}",
            "suggestion": "请调用 retrieve_database_context 查看可用表、授权列和安全 SQL 示例。",
            "example_ids": [],
        },
    )
    payload = {
        "reason": reason,
        "message": hint["message"],
        "suggestion": hint["suggestion"],
        "example_ids": list(hint.get("example_ids", [])),
    }
    if sql:
        payload["sql_excerpt"] = _sql_excerpt(sql)
    return payload


def format_safe_sql_blocked_message(reason: str, *, sql: str = "") -> str:
    hint = build_safe_sql_error_hint(reason, sql=sql)
    parts = [hint["message"], f"建议：{hint['suggestion']}"]
    if hint["example_ids"]:
        parts.append(f"相关示例：{', '.join(hint['example_ids'])}")
    return "\n".join(parts)


def _sql_excerpt(sql: str) -> str:
    normalized = " ".join(sql.strip().split())
    if len(normalized) <= 160:
        return normalized
    return f"{normalized[:157]}..."
