"""SQLite-backed source-of-truth store for durable oncall memory records."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, List, Optional

from loguru import logger

from app.models.memory import MemoryRecord, MemoryStatus, MemoryType


AI_OPS_DIAGNOSIS_EVENT_TYPE = "aiops_diagnosis_completed"
DIAGNOSIS_REVIEW_THRESHOLD = 20


class MemoryStore:
    """Persist durable oncall memory records without touching document RAG state."""

    def __init__(self, store_path: str | Path = "./uploads/_metadata/oncall_memory.sqlite3"):
        self.store_path = Path(store_path).resolve()
        self._lock = RLock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.store_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    memory_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_filter "
                "ON memory_records(owner_id, namespace, memory_type, status)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_policy_events (
                    owner_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_ref TEXT NOT NULL,
                    note TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, event_type, event_ref)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_policy_events_owner_type "
                "ON memory_policy_events(owner_id, event_type)"
            )
            conn.commit()

    def upsert(self, record: MemoryRecord, *, preserve_timestamps: bool = False) -> MemoryRecord:
        updated = record if preserve_timestamps else record.model_copy(update={"updated_at": datetime.now()})
        payload = updated.model_dump_json()
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_records (
                    memory_id, owner_id, namespace, memory_type, status, updated_at, record_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    namespace = excluded.namespace,
                    memory_type = excluded.memory_type,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    record_json = excluded.record_json
                """,
                (
                    updated.memory_id,
                    updated.owner_id,
                    updated.namespace,
                    updated.memory_type.value,
                    updated.status.value,
                    updated.updated_at.isoformat(),
                    payload,
                ),
            )
            conn.commit()
        logger.debug("MemoryStore upserted memory_id={} status={}", updated.memory_id, updated.status)
        return updated.model_copy(deep=True)

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT record_json FROM memory_records WHERE memory_id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            return None
        return MemoryRecord.model_validate(json.loads(row["record_json"]))

    def list_memories(
        self,
        *,
        owner_id: str = "default",
        namespace: str | None = None,
        memory_type: MemoryType | None = None,
        status: MemoryStatus | None = None,
    ) -> List[MemoryRecord]:
        clauses = ["owner_id = ?"]
        params: list[str] = [owner_id]

        if namespace is not None:
            clauses.append("namespace = ?")
            params.append(namespace)
        if memory_type is not None:
            clauses.append("memory_type = ?")
            params.append(memory_type.value)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)

        query = (
            "SELECT record_json FROM memory_records "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY updated_at ASC, memory_id ASC"
        )
        with self._lock, self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [MemoryRecord.model_validate(json.loads(row["record_json"])) for row in rows]

    def update_status(self, memory_id: str, status: MemoryStatus) -> Optional[MemoryRecord]:
        record = self.get(memory_id)
        if record is None:
            return None
        return self.upsert(record.model_copy(update={"status": status}))

    def record_access(self, memory_id: str) -> Optional[MemoryRecord]:
        record = self.get(memory_id)
        if record is None:
            return None
        return self.upsert(
            record.model_copy(
                update={
                    "last_accessed_at": datetime.now(),
                    "access_count": record.access_count + 1,
                }
            ),
            preserve_timestamps=True,
        )

    def get_validation_policy_status(self, *, owner_id: str = "default") -> dict[str, Any]:
        owner_id = self._require_text(owner_id, "owner_id")
        with self._lock, self._connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM memory_policy_events
                WHERE owner_id = ? AND event_type = ?
                """,
                (owner_id, AI_OPS_DIAGNOSIS_EVENT_TYPE),
            ).fetchone()

        diagnosis_count = int(row["count"]) if row is not None else 0
        remaining = max(DIAGNOSIS_REVIEW_THRESHOLD - diagnosis_count, 0)
        return {
            "owner_id": owner_id,
            "gate_a1_real_oncall_evidence": "not_passed",
            "gate_a2_pre_launch_product_bet": "passed",
            "milestone": "first_gray_deployment_plus_30_days_or_20_aiops_diagnoses",
            "diagnosis_use_count": diagnosis_count,
            "diagnosis_review_threshold": DIAGNOSIS_REVIEW_THRESHOLD,
            "diagnoses_remaining_to_review": remaining,
            "review_due_by_diagnosis_count": diagnosis_count >= DIAGNOSIS_REVIEW_THRESHOLD,
            "review_owner": "runtime owner TBD",
            "p5_prompt_integration": "blocked_default_off",
        }

    def record_aiops_diagnosis(
        self,
        diagnosis_id: str,
        *,
        owner_id: str = "default",
        note: str = "",
    ) -> dict[str, Any]:
        owner_id = self._require_text(owner_id, "owner_id")
        diagnosis_id = self._require_text(diagnosis_id, "diagnosis_id")
        note = note.strip()
        recorded_at = datetime.now().isoformat()

        with self._lock, self._connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO memory_policy_events (
                    owner_id, event_type, event_ref, note, recorded_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner_id, AI_OPS_DIAGNOSIS_EVENT_TYPE, diagnosis_id, note, recorded_at),
            )
            conn.commit()
            recorded = cursor.rowcount == 1

        return {
            "recorded": recorded,
            "event_type": AI_OPS_DIAGNOSIS_EVENT_TYPE,
            "diagnosis_id": diagnosis_id,
            "status": self.get_validation_policy_status(owner_id=owner_id),
        }

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if value is None or not str(value).strip():
            raise ValueError(f"{field_name} is required")
        return str(value).strip()


memory_store = MemoryStore()
