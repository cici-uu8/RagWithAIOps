import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_db_size_report import (
    build_checklist3_db_size_report,
    write_checklist3_db_size_report,
)


class Checklist3DbSizeReportTests(unittest.TestCase):
    def test_missing_db_returns_missing_status_without_creating_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "missing.sqlite"

            report = build_checklist3_db_size_report(db_path=db_path)

            self.assertEqual(report["status"], "missing")
            self.assertFalse(db_path.exists())
            self.assertIn("db_missing", report["warnings"])

    def test_report_counts_rows_expired_rows_and_owner_aggregates_without_content_leak(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite"
            _write_sample_db(db_path)
            before_bytes = db_path.read_bytes()

            report = build_checklist3_db_size_report(
                db_path=db_path,
                as_of="2026-06-09T00:00:00+00:00",
                session_ttl_days=30,
                offload_ttl_days=7,
            )

            self.assertEqual(db_path.read_bytes(), before_bytes)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["summary"]["total_rows"], 5)
            self.assertEqual(report["summary"]["total_expired_rows"], 3)
            self.assertEqual(report["summary"]["owners"], ["owner-1", "owner-2"])
            dumped = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("SECRET_TOOL_RESULT_CONTENT", dumped)
            self.assertNotIn("live tail secret", dumped)
            self.assertNotIn("archive secret", dumped)

            offloads = _table(report, "session_tool_result_offloads")
            self.assertEqual(offloads["row_count"], 2)
            self.assertEqual(offloads["expired_count"], 1)
            self.assertEqual(offloads["owner_count"], 2)

    def test_missing_tables_are_reported_as_warnings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite"
            sqlite3.connect(db_path).close()

            report = build_checklist3_db_size_report(db_path=db_path)

            self.assertEqual(report["status"], "warning")
            self.assertIn("session_memory_snapshots_missing", report["warnings"])
            self.assertIn("session_memory_archives_missing", report["warnings"])
            self.assertIn("session_tool_result_offloads_missing", report["warnings"])

    def test_row_count_threshold_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "sessions.sqlite"
            _write_sample_db(db_path)

            report = build_checklist3_db_size_report(
                db_path=db_path,
                table_row_warning_count=1,
            )

            self.assertEqual(report["status"], "warning")
            self.assertIn("session_tool_result_offloads_row_count_over_warning", report["warnings"])

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "sessions.sqlite"
            _write_sample_db(db_path)
            output_json = root / "report.json"
            output_md = root / "report.md"

            report = write_checklist3_db_size_report(
                db_path=db_path,
                as_of="2026-06-09T00:00:00+00:00",
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["summary"]["total_rows"], 5)
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn("Checklist 3 DB Size Report", output_md.read_text(encoding="utf-8"))


def _table(report: dict, table_name: str) -> dict:
    return next(row for row in report["tables"] if row["table"] == table_name)


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
                'tool_result:old',
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
                'tool_result:new',
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


if __name__ == "__main__":
    unittest.main()
