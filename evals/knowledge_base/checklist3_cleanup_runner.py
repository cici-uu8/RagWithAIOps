"""Checklist 3 memory/offload cleanup runner.

Default mode is dry-run. Apply mode must be explicitly requested with
``--apply`` and never creates missing DB files or tables.
"""

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


def build_checklist3_cleanup_report(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    as_of: str | datetime | None = None,
    session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
    offload_ttl_days: int = DEFAULT_OFFLOAD_TTL_DAYS,
    owner_id: str | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    db = Path(db_path)
    as_of_dt = _as_datetime(as_of) if as_of is not None else datetime.now(timezone.utc)
    base = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of_dt.isoformat(),
        "mode": "apply" if apply else "dry_run",
        "db_path": db.as_posix(),
        "db_exists": db.exists(),
        "owner_id": owner_id or "",
        "ttl": {
            "session_ttl_days": session_ttl_days,
            "offload_ttl_days": offload_ttl_days,
        },
        "tables": [],
        "summary": {},
        "warnings": [],
    }
    if not db.exists():
        return {
            **base,
            "status": "missing",
            "summary": _summary([]),
            "warnings": ["db_missing"],
        }

    with closing(_connect(db, read_only=not apply)) as connection:
        if apply:
            with connection:
                table_rows = [
                    _cleanup_table(
                        connection,
                        spec,
                        as_of=as_of_dt,
                        session_ttl_days=session_ttl_days,
                        offload_ttl_days=offload_ttl_days,
                        owner_id=owner_id,
                        apply=apply,
                    )
                    for spec in TABLE_SPECS
                ]
        else:
            table_rows = [
                _cleanup_table(
                    connection,
                    spec,
                    as_of=as_of_dt,
                    session_ttl_days=session_ttl_days,
                    offload_ttl_days=offload_ttl_days,
                    owner_id=owner_id,
                    apply=apply,
                )
                for spec in TABLE_SPECS
            ]
    warnings = _warnings(table_rows)
    return {
        **base,
        "status": "warning" if warnings else ("applied" if apply else "dry_run"),
        "tables": table_rows,
        "summary": _summary(table_rows),
        "warnings": warnings,
    }


def write_checklist3_cleanup_report(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    as_of: str | datetime | None = None,
    session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
    offload_ttl_days: int = DEFAULT_OFFLOAD_TTL_DAYS,
    owner_id: str | None = None,
    apply: bool = False,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    report = build_checklist3_cleanup_report(
        db_path=db_path,
        as_of=as_of,
        session_ttl_days=session_ttl_days,
        offload_ttl_days=offload_ttl_days,
        owner_id=owner_id,
        apply=apply,
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
        "# Checklist 3 Cleanup Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- As of: `{report['as_of']}`",
        f"- Mode: `{report['mode']}`",
        f"- DB path: `{report['db_path']}`",
        f"- Owner filter: `{report['owner_id'] or 'all'}`",
        f"- Status: `{report['status']}`",
        f"- Summary: {report['summary']}",
        f"- Warnings: {report['warnings'] or []}",
        "",
        "| table | exists | expired | deleted | owners | estimated bytes | warnings |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for row in report["tables"]:
        lines.append(
            "| {table} | {exists} | {expired_count} | {deleted_count} | {owner_count} | {estimated_bytes_to_free} | {warnings} |".format(
                table=row["table"],
                exists=row["exists"],
                expired_count=row["expired_count"],
                deleted_count=row["deleted_count"],
                owner_count=row["owner_count"],
                estimated_bytes_to_free=row["estimated_bytes_to_free"],
                warnings=", ".join(row["warnings"]) or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _cleanup_table(
    connection: sqlite3.Connection,
    spec: dict[str, str],
    *,
    as_of: datetime,
    session_ttl_days: int,
    offload_ttl_days: int,
    owner_id: str | None,
    apply: bool,
) -> dict[str, Any]:
    table = spec["table"]
    if not _table_exists(connection, table):
        return {
            "table": table,
            "exists": False,
            "expired_count": 0,
            "deleted_count": 0,
            "owner_count": 0,
            "estimated_bytes_to_free": 0,
            "ttl_cutoff": "",
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
    where_sql = f"{time_column} < ?"
    params: list[Any] = [cutoff.isoformat()]
    if owner_id:
        where_sql += f" AND {owner_column} = ?"
        params.append(owner_id)

    row = connection.execute(
        f"""
        SELECT
            count(*),
            count(DISTINCT {owner_column}),
            coalesce(sum({spec["size_expr"]}), 0)
        FROM {table}
        WHERE {where_sql}
        """,
        params,
    ).fetchone()
    owners = connection.execute(
        f"""
        SELECT
            {owner_column},
            count(*),
            coalesce(sum({spec["size_expr"]}), 0)
        FROM {table}
        WHERE {where_sql}
        GROUP BY {owner_column}
        ORDER BY count(*) DESC, {owner_column}
        """,
        params,
    ).fetchall()
    deleted_count = 0
    if apply:
        cursor = connection.execute(
            f"DELETE FROM {table} WHERE {where_sql}",
            params,
        )
        deleted_count = int(cursor.rowcount or 0)
    expired_count = int(row[0] or 0)
    return {
        "table": table,
        "exists": True,
        "expired_count": expired_count,
        "deleted_count": deleted_count,
        "owner_count": int(row[1] or 0),
        "estimated_bytes_to_free": int(row[2] or 0),
        "ttl_cutoff": cutoff.isoformat(),
        "owners": [
            {
                "owner_id": owner[0],
                "expired_count": int(owner[1] or 0),
                "estimated_bytes_to_free": int(owner[2] or 0),
            }
            for owner in owners
        ],
        "warnings": [],
    }


def _summary(table_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "expired_rows": sum(row["expired_count"] for row in table_rows),
        "deleted_rows": sum(row["deleted_count"] for row in table_rows),
        "estimated_bytes_to_free": sum(row["estimated_bytes_to_free"] for row in table_rows),
        "existing_tables": sum(1 for row in table_rows if row["exists"]),
        "missing_tables": sum(1 for row in table_rows if not row["exists"]),
        "affected_owners": sorted(
            {
                owner["owner_id"]
                for row in table_rows
                for owner in row["owners"]
            }
        ),
    }


def _warnings(table_rows: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    for row in table_rows:
        if not row["exists"]:
            warnings.append(f"{row['table']}_missing")
    return warnings


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        uri = f"file:{path.resolve()}?mode=ro"
        return sqlite3.connect(uri, uri=True)
    return sqlite3.connect(path)


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
    parser = argparse.ArgumentParser(description="Run Checklist 3 memory/offload cleanup.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--session-ttl-days", type=int, default=DEFAULT_SESSION_TTL_DAYS)
    parser.add_argument("--offload-ttl-days", type=int, default=DEFAULT_OFFLOAD_TTL_DAYS)
    parser.add_argument("--owner-id", default="")
    parser.add_argument("--apply", action="store_true", help="Delete expired rows. Omit for dry-run.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_checklist3_cleanup_report(
        db_path=args.db_path,
        as_of=args.as_of or None,
        session_ttl_days=args.session_ttl_days,
        offload_ttl_days=args.offload_ttl_days,
        owner_id=args.owner_id or None,
        apply=args.apply,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
