"""SQLite sandbox database fixture for E6."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.enterprise.database.registry import DatabaseSchemaRegistry


def ensure_sandbox_database(path: str | Path, registry: DatabaseSchemaRegistry) -> Path:
    db_path = Path(path)
    if not db_path.exists() or not _matches_registry(db_path, registry):
        return create_sandbox_database(db_path)
    return db_path


def create_sandbox_database(path: str | Path) -> Path:
    """Create a deterministic local SQLite sandbox database.

    The DB contains a few hidden columns so the SafeSqlKernel can prove that
    table/column allowlisting blocks them before execution.
    """

    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    with closing(sqlite3.connect(db_path)) as connection:
        with connection:
            connection.executescript(
                """
                CREATE TABLE factory_access_events (
                    event_id INTEGER PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    employee_name TEXT NOT NULL,
                    department_name TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    gate_name TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    badge_id TEXT,
                    raw_device_payload TEXT
                );

                CREATE TABLE building_access_events (
                    event_id INTEGER PRIMARY KEY,
                    employee_id TEXT NOT NULL,
                    employee_name TEXT NOT NULL,
                    department_name TEXT NOT NULL,
                    building_name TEXT NOT NULL,
                    floor_name TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    access_point_name TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    device_id TEXT,
                    raw_device_payload TEXT
                );
                """
            )
            connection.executemany(
                """
                INSERT INTO factory_access_events (
                    event_id, employee_id, employee_name, department_name, direction,
                    gate_name, event_time, badge_id, raw_device_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (1001, "E001", "张伟", "研发部", "entry", "东门", "2026-06-16 08:30:00", "BADGE001", None),
                    (1002, "E001", "张伟", "研发部", "exit", "东门", "2026-06-16 18:45:00", "BADGE001", None),
                    (1003, "E002", "李娜", "运营部", "entry", "北门", "2026-06-16 02:30:00", "BADGE002", None),
                    (1004, "E002", "李娜", "运营部", "exit", "北门", "2026-06-16 03:10:00", "BADGE002", None),
                    (1005, "E003", "王强", "安保部", "entry", "西门", "2026-06-16 07:15:00", "BADGE003", None),
                    (1006, "E003", "王强", "安保部", "exit", "西门", "2026-06-16 19:30:00", "BADGE003", None),
                    (1007, "E004", "赵敏", "制造部", "entry", "南门", "2026-06-16 08:05:00", "BADGE004", None),
                    (1008, "E004", "赵敏", "制造部", "exit", "南门", "2026-06-16 20:15:00", "BADGE004", None),
                    (1009, "E005", "陈杰", "研发部", "entry", "东门", "2026-06-17 08:40:00", "BADGE005", None),
                    (1010, "E005", "陈杰", "研发部", "exit", "东门", "2026-06-17 18:20:00", "BADGE005", None),
                    (1011, "E006", "周悦", "运维部", "entry", "北门", "2026-06-17 23:50:00", "BADGE006", None),
                    (1012, "E006", "周悦", "运维部", "exit", "北门", "2026-06-18 01:20:00", "BADGE006", None),
                ],
            )
            connection.executemany(
                """
                INSERT INTO building_access_events (
                    event_id, employee_id, employee_name, department_name, building_name,
                    floor_name, direction, access_point_name, event_time, device_id, raw_device_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (2001, "E001", "张伟", "研发部", "流数楼", "3F", "entry", "3F-门禁点A", "2026-06-16 09:00:00", "DEV301", None),
                    (2002, "E001", "张伟", "研发部", "流数楼", "3F", "exit", "3F-门禁点A", "2026-06-16 18:20:00", "DEV301", None),
                    (2003, "E002", "李娜", "运营部", "运营楼", "1F", "entry", "1F-前台闸机", "2026-06-16 02:40:00", "DEV101", None),
                    (2004, "E002", "李娜", "运营部", "运营楼", "1F", "exit", "1F-前台闸机", "2026-06-16 03:05:00", "DEV101", None),
                    (2005, "E003", "王强", "安保部", "安保楼", "1F", "entry", "1F-值班室", "2026-06-16 07:20:00", "DEV-S01", None),
                    (2006, "E003", "王强", "安保部", "安保楼", "1F", "exit", "1F-值班室", "2026-06-16 19:10:00", "DEV-S01", None),
                    (2007, "E004", "赵敏", "制造部", "制造楼", "2F", "entry", "2F-车间门禁", "2026-06-16 08:20:00", "DEV205", None),
                    (2008, "E004", "赵敏", "制造部", "制造楼", "2F", "exit", "2F-车间门禁", "2026-06-16 20:00:00", "DEV205", None),
                    (2009, "E005", "陈杰", "研发部", "流数楼", "5F", "entry", "5F-实验室", "2026-06-17 09:10:00", "DEV501", None),
                    (2010, "E005", "陈杰", "研发部", "流数楼", "5F", "exit", "5F-实验室", "2026-06-17 18:05:00", "DEV501", None),
                    (2011, "E006", "周悦", "运维部", "数据中心", "B1", "entry", "B1-机房门禁", "2026-06-17 23:55:00", "DEV-B101", None),
                    (2012, "E006", "周悦", "运维部", "数据中心", "B1", "exit", "B1-机房门禁", "2026-06-18 01:15:00", "DEV-B101", None),
                ],
            )
    return db_path


def _matches_registry(path: Path, registry: DatabaseSchemaRegistry) -> bool:
    try:
        with closing(sqlite3.connect(path)) as connection:
            for table_name in registry.list_tables():
                rows = connection.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
                existing_columns = {str(row[1]).lower() for row in rows}
                if not existing_columns:
                    return False
                expected_columns = registry.allowed_column_names(table_name)
                if not expected_columns.issubset(existing_columns):
                    return False
    except sqlite3.Error:
        return False
    return True


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
