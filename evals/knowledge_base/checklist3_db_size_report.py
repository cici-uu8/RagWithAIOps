"""Checklist 3 memory/offload SQLite size and capacity report helpers."""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "logs/enterprise_chat_sessions.sqlite"
DEFAULT_SESSION_TTL_DAYS = 30
DEFAULT_OFFLOAD_TTL_DAYS = 7
LOCAL_DB_WARNING_BYTES = 100 * 1024 * 1024
PROD_DB_ALERT_BYTES = 500 * 1024 * 1024
TABLE_ROW_WARNING_COUNT = 1_000_000

TABLE_SPECS = [
    {
        "table": "session_memory_snapshots",
        "owner_column": "owner_id",
        "time_column": "updated_at",
        "ttl_kind": "session",
        "size_expr": (
            "length(latest_summary) + length(live_tail_json) + "
            "length(metadata_json)"
        ),
    },
    {
        "table": "session_memory_archives",
        "owner_column": "owner_id",
        "time_column": "created_at",
        "ttl_kind": "session",
        "size_expr": "length(summary) + length(messages_json) + length(metadata_json)",
    },
    {
        "table": "session_tool_result_offloads",
        "owner_column": "owner_id",
        "time_column": "created_at",
        "ttl_kind": "offload",
        "size_expr": "length(content) + length(summary) + length(metadata_json)",
    },
]


def build_checklist3_db_size_report(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    as_of: str | datetime | None = None,
    session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
    offload_ttl_days: int = DEFAULT_OFFLOAD_TTL_DAYS,
    local_db_warning_bytes: int = LOCAL_DB_WARNING_BYTES,
    prod_db_alert_bytes: int = PROD_DB_ALERT_BYTES,
    table_row_warning_count: int = TABLE_ROW_WARNING_COUNT,
) -> dict[str, Any]:
    db = Path(db_path)
    as_of_dt = _as_datetime(as_of) if as_of is not None else datetime.now(timezone.utc)
    base = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of_dt.isoformat(),
        "db_path": db.as_posix(),
        "db_exists": db.exists(),
        "db_size_bytes": db.stat().st_size if db.exists() else 0,
        "thresholds": {
            "session_ttl_days": session_ttl_days,
            "offload_ttl_days": offload_ttl_days,
            "local_db_warning_bytes": local_db_warning_bytes,
            "prod_db_alert_bytes": prod_db_alert_bytes,
            "table_row_warning_count": table_row_warning_count,
        },
        "tables": [],
        "summary": {},
        "warnings": [],
    }
    if not db.exists():
        return {
            **base,
            "status": "missing",
            "summary": _summary([], db_size_bytes=0),
            "warnings": ["db_missing"],
        }

    with closing(_connect_read_only(db)) as connection:
        table_rows = [
            _inspect_table(
                connection,
                spec,
                as_of=as_of_dt,
                session_ttl_days=session_ttl_days,
                offload_ttl_days=offload_ttl_days,
            )
            for spec in TABLE_SPECS
        ]
    warnings = _warnings(
        table_rows,
        db_size_bytes=base["db_size_bytes"],
        local_db_warning_bytes=local_db_warning_bytes,
        prod_db_alert_bytes=prod_db_alert_bytes,
        table_row_warning_count=table_row_warning_count,
    )
    return {
        **base,
        "status": "warning" if warnings else "ok",
        "tables": table_rows,
        "summary": _summary(table_rows, db_size_bytes=base["db_size_bytes"]),
        "warnings": warnings,
    }


def write_checklist3_db_size_report(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    as_of: str | datetime | None = None,
    session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
    offload_ttl_days: int = DEFAULT_OFFLOAD_TTL_DAYS,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    report = build_checklist3_db_size_report(
        db_path=db_path,
        as_of=as_of,
        session_ttl_days=session_ttl_days,
        offload_ttl_days=offload_ttl_days,
    )
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Checklist 3 DB Size Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- As of: `{report['as_of']}`",
        f"- DB path: `{report['db_path']}`",
        f"- Status: `{report['status']}`",
        f"- Summary: {report['summary']}",
        f"- Warnings: {report['warnings'] or []}",
        "",
        "| table | exists | rows | expired | owners | oldest | newest | estimated bytes | warnings |",
        "|---|---|---:|---:|---:|---|---|---:|---|",
    ]
    for row in report["tables"]:
        lines.append(
            "| {table} | {exists} | {row_count} | {expired_count} | {owner_count} | {oldest_at} | {newest_at} | {estimated_bytes} | {warnings} |".format(
                table=row["table"],
                exists=row["exists"],
                row_count=row["row_count"],
                expired_count=row["expired_count"],
                owner_count=row["owner_count"],
                oldest_at=row["oldest_at"] or "-",
                newest_at=row["newest_at"] or "-",
                estimated_bytes=row["estimated_bytes"],
                warnings=", ".join(row["warnings"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _inspect_table(
    connection: sqlite3.Connection,
    spec: dict[str, str],
    *,
    as_of: datetime,
    session_ttl_days: int,
    offload_ttl_days: int,
) -> dict[str, Any]:
    table = spec["table"]
    if not _table_exists(connection, table):
        return {
            "table": table,
            "exists": False,
            "row_count": 0,
            "owner_count": 0,
            "expired_count": 0,
            "estimated_bytes": 0,
            "oldest_at": "",
            "newest_at": "",
            "owners": [],
            "warnings": ["table_missing"],
        }

    owner_column = spec["owner_column"]
    time_column = spec["time_column"]
    cutoff = _cutoff(
        as_of,
        session_ttl_days=session_ttl_days,
        offload_ttl_days=offload_ttl_days,
        ttl_kind=spec["ttl_kind"],
    )
    row = connection.execute(
        f"""
        SELECT
            count(*),
            count(DISTINCT {owner_column}),
            coalesce(sum({spec["size_expr"]}), 0),
            min({time_column}),
            max({time_column}),
            sum(CASE WHEN {time_column} < ? THEN 1 ELSE 0 END)
        FROM {table}
        """,
        (cutoff.isoformat(),),
    ).fetchone()
    owners = connection.execute(
        f"""
        SELECT
            {owner_column},
            count(*),
            coalesce(sum({spec["size_expr"]}), 0),
            min({time_column}),
            max({time_column}),
            sum(CASE WHEN {time_column} < ? THEN 1 ELSE 0 END)
        FROM {table}
        GROUP BY {owner_column}
        ORDER BY count(*) DESC, {owner_column}
        """,
        (cutoff.isoformat(),),
    ).fetchall()
    return {
        "table": table,
        "exists": True,
        "row_count": int(row[0] or 0),
        "owner_count": int(row[1] or 0),
        "estimated_bytes": int(row[2] or 0),
        "oldest_at": row[3] or "",
        "newest_at": row[4] or "",
        "expired_count": int(row[5] or 0),
        "ttl_cutoff": cutoff.isoformat(),
        "owners": [
            {
                "owner_id": owner[0],
                "row_count": int(owner[1] or 0),
                "estimated_bytes": int(owner[2] or 0),
                "oldest_at": owner[3] or "",
                "newest_at": owner[4] or "",
                "expired_count": int(owner[5] or 0),
            }
            for owner in owners
        ],
        "warnings": [],
    }


def _summary(table_rows: list[dict[str, Any]], *, db_size_bytes: int) -> dict[str, Any]:
    return {
        "db_size_bytes": db_size_bytes,
        "total_rows": sum(row["row_count"] for row in table_rows),
        "total_expired_rows": sum(row["expired_count"] for row in table_rows),
        "total_estimated_payload_bytes": sum(row["estimated_bytes"] for row in table_rows),
        "existing_tables": sum(1 for row in table_rows if row["exists"]),
        "missing_tables": sum(1 for row in table_rows if not row["exists"]),
        "owners": sorted(
            {
                owner["owner_id"]
                for row in table_rows
                for owner in row["owners"]
            }
        ),
    }


def _warnings(
    table_rows: list[dict[str, Any]],
    *,
    db_size_bytes: int,
    local_db_warning_bytes: int,
    prod_db_alert_bytes: int,
    table_row_warning_count: int,
) -> list[str]:
    warnings: list[str] = []
    if db_size_bytes > local_db_warning_bytes:
        warnings.append("db_size_over_local_warning")
    if db_size_bytes > prod_db_alert_bytes:
        warnings.append("db_size_over_prod_alert")
    for row in table_rows:
        if not row["exists"]:
            warnings.append(f"{row['table']}_missing")
        if row["row_count"] > table_row_warning_count:
            warnings.append(f"{row['table']}_row_count_over_warning")
    return warnings


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _cutoff(
    as_of: datetime,
    *,
    session_ttl_days: int,
    offload_ttl_days: int,
    ttl_kind: str,
) -> datetime:
    days = offload_ttl_days if ttl_kind == "offload" else session_ttl_days
    return as_of - timedelta(days=int(days))


def _as_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Checklist 3 memory/offload DB size report.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--session-ttl-days", type=int, default=DEFAULT_SESSION_TTL_DAYS)
    parser.add_argument("--offload-ttl-days", type=int, default=DEFAULT_OFFLOAD_TTL_DAYS)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_checklist3_db_size_report(
        db_path=args.db_path,
        as_of=args.as_of or None,
        session_ttl_days=args.session_ttl_days,
        offload_ttl_days=args.offload_ttl_days,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
