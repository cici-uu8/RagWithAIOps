"""JSON schemas for database tool inputs."""

from __future__ import annotations

import copy
from typing import Any


def database_list_tables_input_schema() -> dict[str, Any]:
    return _strict_object_schema(properties={}, required=[])


def database_describe_table_input_schema() -> dict[str, Any]:
    return _strict_object_schema(
        properties={
            "table_name": {
                "type": "string",
                "minLength": 1,
                "description": "Allowlisted table name to describe.",
            }
        },
        required=["table_name"],
    )


def database_safe_select_input_schema() -> dict[str, Any]:
    return _strict_object_schema(
        properties={
            "sql": {
                "type": "string",
                "minLength": 1,
                "description": "Single read-only SELECT statement.",
            }
        },
        required=["sql"],
    )


def database_prepare_operation_input_schema() -> dict[str, Any]:
    return _strict_object_schema(
        properties={
            "sql": {
                "type": "string",
                "minLength": 1,
                "description": "Single database operation statement to prepare for confirmation.",
            }
        },
        required=["sql"],
    )


def _strict_object_schema(
    *,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": copy.deepcopy(properties),
        "required": list(required),
        "additionalProperties": False,
    }
