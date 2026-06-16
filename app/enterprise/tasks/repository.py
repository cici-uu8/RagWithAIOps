"""Task contract repositories for Enterprise 2.0 F1."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.config import config
from app.enterprise.tasks.models import TaskContract, TaskStatus


class InMemoryTaskContractRepository:
    def __init__(self):
        self._contracts: dict[str, TaskContract] = {}

    def create(self, contract: TaskContract) -> TaskContract:
        self._contracts[contract.task_id] = contract
        return contract

    def get(self, task_id: str) -> TaskContract | None:
        return self._contracts.get(task_id)

    def update_status(self, task_id: str, status: TaskStatus) -> TaskContract | None:
        contract = self._contracts.get(task_id)
        if contract is None:
            return None
        updated = contract.with_status(status)
        self._contracts[task_id] = updated
        return updated

    def list_by_trace(self, trace_id: str) -> list[TaskContract]:
        return [
            contract
            for contract in self._contracts.values()
            if contract.trace_id == trace_id
        ]


class SQLiteTaskContractRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.enterprise_task_contract_sqlite_path)
        self._initialized = False

    def create(self, contract: TaskContract) -> TaskContract:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute(
                    """
                    INSERT OR REPLACE INTO enterprise_task_contracts (
                        task_id, trace_id, request_id, user_id, status, contract_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        contract.task_id,
                        contract.trace_id,
                        contract.request_id,
                        contract.user_id,
                        contract.status.value,
                        contract.model_dump_json(),
                    ),
                )
        return contract

    def get(self, task_id: str) -> TaskContract | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            row = connection.execute(
                """
                SELECT contract_json
                FROM enterprise_task_contracts
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return TaskContract.model_validate(json.loads(row[0]))

    def update_status(self, task_id: str, status: TaskStatus) -> TaskContract | None:
        contract = self.get(task_id)
        if contract is None:
            return None
        updated = contract.with_status(status)
        return self.create(updated)

    def list_by_trace(self, trace_id: str) -> list[TaskContract]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(
                """
                SELECT contract_json
                FROM enterprise_task_contracts
                WHERE trace_id = ?
                ORDER BY task_id ASC
                """,
                (trace_id,),
            ).fetchall()
        return [TaskContract.model_validate(json.loads(row[0])) for row in rows]

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS enterprise_task_contracts (
                task_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                contract_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_enterprise_task_contracts_trace
            ON enterprise_task_contracts(trace_id)
            """
        )
        self._initialized = True
