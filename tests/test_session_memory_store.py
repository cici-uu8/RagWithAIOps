import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.models import SessionMemorySnapshot as ExportedSessionMemorySnapshot
from app.models.session_memory import SessionMemoryMessage, SessionMemorySnapshot, utc_now
from app.services.session_memory_store import (
    InMemorySessionMemoryStore,
    SessionMemoryArchive,
    SessionToolResultOffloadStore,
    SQLiteSessionMemoryStore,
)


class SessionMemoryStoreTests(unittest.TestCase):
    def test_session_memory_snapshot_is_exported_from_models_package(self):
        self.assertIs(ExportedSessionMemorySnapshot, SessionMemorySnapshot)

    def test_sqlite_snapshot_persists_after_reopen(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "enterprise_chat_sessions.sqlite"
            store = SQLiteSessionMemoryStore(db_path)
            snapshot = SessionMemorySnapshot(
                session_id="session-1",
                owner_id="user-1",
                latest_summary="昨天已经定位到 Redis backlog",
                live_tail=[
                    SessionMemoryMessage(role="user", content="继续排查"),
                    SessionMemoryMessage(role="assistant", content="先看队列长度"),
                ],
            )

            store.upsert_snapshot(snapshot)
            reopened = SQLiteSessionMemoryStore(db_path)

            loaded = reopened.get_snapshot("session-1", "user-1")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.latest_summary, "昨天已经定位到 Redis backlog")
            self.assertEqual([message.role for message in loaded.live_tail], ["user", "assistant"])

    def test_sqlite_snapshot_is_owner_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionMemoryStore(Path(tmpdir) / "sessions.sqlite")
            store.upsert_snapshot(
                SessionMemorySnapshot(
                    session_id="session-1",
                    owner_id="user-1",
                    latest_summary="owner only",
                )
            )

            self.assertIsNone(store.get_snapshot("session-1", "user-2"))
            self.assertIsNotNone(store.get_snapshot("session-1", "user-1"))

    def test_sqlite_live_tail_append_is_bounded_and_does_not_write_chat_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "enterprise_chat_sessions.sqlite"
            store = SQLiteSessionMemoryStore(db_path)

            store.append_live_message("session-1", "user-1", role="user", content="m1", max_tail=2)
            store.append_live_message("session-1", "user-1", role="assistant", content="m2", max_tail=2)
            store.append_live_message("session-1", "user-1", role="user", content="m3", max_tail=2)

            loaded = store.get_snapshot("session-1", "user-1")
            self.assertIsNotNone(loaded)
            self.assertEqual([message.content for message in loaded.live_tail], ["m2", "m3"])

            with sqlite3.connect(db_path) as connection:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            self.assertIn("session_memory_snapshots", table_names)
            self.assertNotIn("chat_messages", table_names)

    def test_in_memory_store_matches_owner_and_live_tail_behavior(self):
        store = InMemorySessionMemoryStore()

        store.append_live_message("session-1", "user-1", role="user", content="m1", max_tail=1)
        store.append_live_message("session-1", "user-1", role="assistant", content="m2", max_tail=1)

        self.assertIsNone(store.get_snapshot("session-1", "user-2"))
        loaded = store.get_snapshot("session-1", "user-1")
        self.assertIsNotNone(loaded)
        self.assertEqual([message.content for message in loaded.live_tail], ["m2"])

    def test_in_memory_cleanup_expired_is_owner_scoped(self):
        store = InMemorySessionMemoryStore()
        old_time = utc_now() - timedelta(days=2)
        store.upsert_snapshot(
            SessionMemorySnapshot(
                session_id="session-old",
                owner_id="user-1",
                latest_summary="old",
                updated_at=old_time,
            )
        )
        store.upsert_snapshot(
            SessionMemorySnapshot(
                session_id="session-other",
                owner_id="user-2",
                latest_summary="other",
                updated_at=old_time,
            )
        )

        removed = store.cleanup_expired(ttl_seconds=3600, owner_id="user-1")

        self.assertEqual(removed, 1)
        self.assertIsNone(store.get_snapshot("session-old", "user-1"))
        self.assertIsNotNone(store.get_snapshot("session-other", "user-2"))

    def test_sqlite_archive_rolls_old_tail_into_summary_and_keeps_recent_tail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionMemoryStore(Path(tmpdir) / "sessions.sqlite")
            store.upsert_snapshot(
                SessionMemorySnapshot(
                    session_id="session-1",
                    owner_id="user-1",
                    latest_summary="已有摘要",
                    live_tail=[
                        SessionMemoryMessage(role="user", content="m1"),
                        SessionMemoryMessage(role="assistant", content="m2"),
                        SessionMemoryMessage(role="user", content="m3"),
                        SessionMemoryMessage(role="assistant", content="m4"),
                    ],
                )
            )

            archive = store.archive_live_tail(
                "session-1",
                "user-1",
                keep_tail=2,
                archive_summary="旧消息归档摘要",
                archive_metadata={"reason": "threshold"},
            )
            loaded = store.get_snapshot("session-1", "user-1")

            self.assertIsInstance(archive, SessionMemoryArchive)
            self.assertEqual([message.content for message in archive.messages], ["m1", "m2"])
            self.assertEqual(archive.metadata["reason"], "threshold")
            self.assertIsNotNone(loaded)
            self.assertEqual([message.content for message in loaded.live_tail], ["m3", "m4"])
            self.assertIn("已有摘要", loaded.latest_summary)
            self.assertIn("旧消息归档摘要", loaded.latest_summary)

            reopened = SQLiteSessionMemoryStore(Path(tmpdir) / "sessions.sqlite")
            archives = reopened.list_archives("session-1", "user-1")
            self.assertEqual(len(archives), 1)
            self.assertEqual(archives[0].archive_id, archive.archive_id)

    def test_sqlite_cleanup_expired_removes_snapshot_and_archive_by_owner(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteSessionMemoryStore(Path(tmpdir) / "sessions.sqlite")
            old_time = utc_now() - timedelta(days=2)
            store.upsert_snapshot(
                SessionMemorySnapshot(
                    session_id="session-old",
                    owner_id="user-1",
                    latest_summary="old",
                    updated_at=old_time,
                )
            )
            store.upsert_snapshot(
                SessionMemorySnapshot(
                    session_id="session-other",
                    owner_id="user-2",
                    latest_summary="other",
                    updated_at=old_time,
                )
            )
            store.archive_live_tail(
                "session-old",
                "user-1",
                keep_tail=0,
                archive_summary="old archive",
            )
            with sqlite3.connect(store.path) as connection:
                connection.execute(
                    """
                    UPDATE session_memory_archives
                    SET created_at = ?
                    WHERE session_id = ? AND owner_id = ?
                    """,
                    (old_time.isoformat(), "session-old", "user-1"),
                )
                connection.execute(
                    """
                    UPDATE session_memory_snapshots
                    SET updated_at = ?
                    WHERE session_id = ? AND owner_id = ?
                    """,
                    (old_time.isoformat(), "session-old", "user-1"),
                )

            removed = store.cleanup_expired(ttl_seconds=3600, owner_id="user-1")

            self.assertGreaterEqual(removed, 1)
            self.assertIsNone(store.get_snapshot("session-old", "user-1"))
            self.assertIsNotNone(store.get_snapshot("session-other", "user-2"))
            self.assertEqual(store.list_archives("session-old", "user-1"), [])

    def test_tool_result_offload_persists_large_result_and_returns_short_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionToolResultOffloadStore(Path(tmpdir) / "sessions.sqlite")
            content = "line 1\nline 2\nline 3\n"

            ref = store.offload_result(
                session_id="session-1",
                owner_id="user-1",
                tool_name="search_service_logs",
                content=content,
                summary="3 lines from service logs",
                metadata={"trace_id": "trace-1"},
            )
            loaded = store.get_result(ref.result_ref, owner_id="user-1")

            self.assertTrue(ref.result_ref.startswith("tool_result:"))
            self.assertTrue(
                ref.prompt_stub().startswith("[search_service_logs] 3 lines from service logs")
            )
            self.assertIn(ref.result_ref, ref.prompt_stub())
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.content, content)
            self.assertEqual(loaded.metadata["trace_id"], "trace-1")
            self.assertIsNone(store.get_result(ref.result_ref, owner_id="user-2"))

    def test_tool_result_offload_cleanup_expired_is_owner_scoped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionToolResultOffloadStore(Path(tmpdir) / "sessions.sqlite")
            old_time = utc_now() - timedelta(days=2)
            ref_old = store.offload_result(
                session_id="session-1",
                owner_id="user-1",
                tool_name="search_service_logs",
                content="old",
                summary="old",
            )
            ref_other = store.offload_result(
                session_id="session-2",
                owner_id="user-2",
                tool_name="search_service_logs",
                content="other",
                summary="other",
            )
            with sqlite3.connect(store.path) as connection:
                connection.execute(
                    """
                    UPDATE session_tool_result_offloads
                    SET created_at = ?
                    """,
                    (old_time.isoformat(),),
                )

            removed = store.cleanup_expired(ttl_seconds=3600, owner_id="user-1")

            self.assertEqual(removed, 1)
            self.assertIsNone(store.get_result(ref_old.result_ref, owner_id="user-1"))
            self.assertIsNotNone(store.get_result(ref_other.result_ref, owner_id="user-2"))


if __name__ == "__main__":
    unittest.main()
