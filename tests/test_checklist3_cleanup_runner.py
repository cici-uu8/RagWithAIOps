import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_cleanup_runner import (
    build_checklist3_cleanup_report,
    write_checklist3_cleanup_report,
)


class Checklist3CleanupRunnerTests(unittest.TestCase):
    def test_dry_run_reports_expired_rows_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite"
            _write_sample_db(db_path)

            report = build_checklist3_cleanup_report(
                db_path=db_path,
                as_of="2026-06-09T00:00:00+00:00",
                session_ttl_days=30,
                offload_ttl_days=7,
            )

            self.assertEqual(report["status"], "dry_run")
            self.assertEqual(report["mode"], "dry_run")
            self.assertEqual(report["summary"]["expired_rows"], 4)
            self.assertEqual(report["summary"]["deleted_rows"], 0)
            self.assertEqual(_row_count(db_path, "session_memory_snapshots"), 2)
            self.assertEqual(_row_count(db_path, "session_memory_archives"), 1)
            self.assertEqual(_row_count(db_path, "session_tool_result_offloads"), 3)
            dumped = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("SECRET_TOOL_RESULT_CONTENT", dumped)
            self.assertNotIn("live tail secret", dumped)
            self.assertNotIn("archive secret", dumped)

    def test_apply_deletes_expired_rows_for_owner_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite"
            _write_sample_db(db_path)

            report = build_checklist3_cleanup_report(
                db_path=db_path,
                as_of="2026-06-09T00:00:00+00:00",
                session_ttl_days=30,
                offload_ttl_days=7,
                owner_id="owner-1",
                apply=True,
            )

            self.assertEqual(report["status"], "applied")
            self.assertEqual(report["mode"], "apply")
            self.assertEqual(report["summary"]["expired_rows"], 3)
            self.assertEqual(report["summary"]["deleted_rows"], 3)
            self.assertEqual(_owner_count(db_path, "session_memory_snapshots", "owner-1"), 0)
            self.assertEqual(_owner_count(db_path, "session_memory_snapshots", "owner-2"), 1)
            self.assertEqual(_owner_count(db_path, "session_tool_result_offloads", "owner-1"), 0)
            self.assertEqual(_owner_count(db_path, "session_tool_result_offloads", "owner-2"), 2)

    def test_missing_db_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "missing.sqlite"

            report = build_checklist3_cleanup_report(db_path=db_path)

            self.assertEqual(report["status"], "missing")
            self.assertFalse(db_path.exists())
            self.assertIn("db_missing", report["warnings"])

    def test_missing_tables_are_reported_without_creating_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite"
            sqlite3.connect(db_path).close()

            report = build_checklist3_cleanup_report(db_path=db_path, apply=True)

            self.assertEqual(report["status"], "warning")
            self.assertEqual(report["summary"]["deleted_rows"], 0)
            self.assertIn("session_memory_snapshots_missing", report["warnings"])
            self.assertEqual(_table_names(db_path), set())

    def test_write_cleanup_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "sessions.sqlite"
            _write_sample_db(db_path)
            output_json = root / "cleanup.json"
            output_md = root / "cleanup.md"

            report = write_checklist3_cleanup_report(
                db_path=db_path,
                as_of="2026-06-09T00:00:00+00:00",
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "dry_run")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn("Checklist 3 Cleanup Report", output_md.read_text(encoding="utf-8"))


def _write_sample_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE session_memory_snapshots (
                session_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                latest_summary TEXT NOT NULL,
                live_tail_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, owner_id)
            );
            CREATE TABLE session_memory_archives (
                archive_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                summary TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE session_tool_result_offloads (
                result_ref TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                owner_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO session_memory_snapshots VALUES (
                'session-old',
                'owner-1',
                'old summary',
                '[{"content":"live tail secret"}]',
                '{}',
                '2026-04-01T00:00:00+00:00',
                '2026-04-01T00:00:00+00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO session_memory_snapshots VALUES (
                'session-new',
                'owner-2',
                'new summary',
                '[]',
                '{}',
                '2026-06-08T00:00:00+00:00',
                '2026-06-08T00:00:00+00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO session_memory_archives VALUES (
                'archive-old',
                'session-old',
                'owner-1',
                'archive secret',
                '[]',
                '{}',
                '2026-04-01T00:00:00+00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO session_tool_result_offloads VALUES (
                'tool_result:old-owner-1',
                'session-old',
                'owner-1',
                'logs',
                'SECRET_TOOL_RESULT_CONTENT',
                'old logs',
                '{}',
                '2026-05-01T00:00:00+00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO session_tool_result_offloads VALUES (
                'tool_result:old-owner-2',
                'session-other-old',
                'owner-2',
                'logs',
                'other old content',
                'other old logs',
                '{}',
                '2026-05-01T00:00:00+00:00'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO session_tool_result_offloads VALUES (
                'tool_result:new-owner-2',
                'session-new',
                'owner-2',
                'logs',
                'fresh content',
                'new logs',
                '{}',
                '2026-06-08T00:00:00+00:00'
            )
            """
        )


def _row_count(path: Path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _owner_count(path: Path, table: str, owner_id: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE owner_id = ?",
                (owner_id,),
            ).fetchone()[0]
        )


def _table_names(path: Path) -> set[str]:
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }


if __name__ == "__main__":
    unittest.main()
