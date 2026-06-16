"""Database operation confirmation preparation for DB-Ops-6."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import sqlglot
from pydantic import BaseModel, Field
from sqlglot import exp

from app.config import config
from app.enterprise.context import RequestContext
from app.enterprise.database.operation_permissions import (
    DatabaseOperationPermissionChecker,
    DatabaseOperationPermissionResult,
)
from app.enterprise.database.permissions import (
    database_column_resource_id,
    database_operation_resource_id,
    database_table_resource_id,
)
from app.enterprise.database.registry import DatabaseSchemaRegistry
from app.enterprise.observability.audit_service import AuditService
from app.enterprise.observability.models import AuditEvent
from app.enterprise.permissions.service import PermissionService

SQL_HASH_VERSION = "dbops-sql-hash-v1"
NORMALIZATION_VERSION = "sqlglot-normalize-v1"
PENDING_TTL_MINUTES = 15
EXECUTION_DEADLINE_MINUTES = 2


class DatabaseOperationPrepareDenied(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class DatabaseOperationConfirmationDenied(Exception):
    def __init__(self, reason: str, *, status_code: int = 403):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


class DatabaseOperationDirectExecuteDenied(Exception):
    def __init__(self, reason: str, *, status_code: int = 403):
        self.reason = reason
        self.status_code = status_code
        super().__init__(reason)


class DatabaseOperationConfirmationStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"


class DatabaseOperationRiskSummary(BaseModel):
    estimated_affected_rows: int | None = None
    estimate_reliable: bool = False
    estimate_reason: str
    target_tables: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)


class DatabaseOperationConfirmationRecord(BaseModel):
    confirmation_id: str = Field(default_factory=lambda: f"dbconf_{uuid4().hex}")
    user_id: str
    username: str
    database_id: str
    status: DatabaseOperationConfirmationStatus = DatabaseOperationConfirmationStatus.PENDING
    operation_level: str
    operation_type: str
    risk_level: str
    sql: str
    normalized_sql: str
    sql_hash: str
    parameters_hash: str
    sql_hash_version: str = SQL_HASH_VERSION
    normalization_version: str = NORMALIZATION_VERSION
    reason: str | None = None
    permission_reason: str
    target_tables: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    summary: DatabaseOperationRiskSummary
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    confirmed_at: datetime | None = None
    cancelled_at: datetime | None = None
    executing_at: datetime | None = None
    executed_at: datetime | None = None
    failed_at: datetime | None = None
    execution_deadline_at: datetime | None = None
    failure_reason: str | None = None
    execution_result: dict[str, Any] | None = None


class DatabaseOperationPrepareResult(BaseModel):
    confirmation_id: str
    requires_confirmation: bool = True
    database_id: str
    operation_level: str
    operation_type: str
    risk_level: str
    summary: DatabaseOperationRiskSummary
    expires_at: datetime


class DatabaseOperationDirectExecuteResult(BaseModel):
    requires_confirmation: bool = False
    database_id: str
    operation_level: str
    operation_type: str
    status: str = "executed"
    sql_hash: str
    parameters_hash: str
    target_tables: list[str] = Field(default_factory=list)
    target_columns: list[str] = Field(default_factory=list)
    execution_result: dict[str, Any]


class DatabaseOperationExecutor(Protocol):
    database_id: str
    dialect: str

    def supports_operation(self, operation_type: str) -> bool:
        ...

    def count_matching_rows(self, sql: str, table_name: str) -> int | None:
        ...

    def execute(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> dict[str, Any]:
        ...


class DatabaseOperationDirectExecutor(Protocol):
    database_id: str
    dialect: str

    def supports_direct_operation(self, operation_type: str) -> bool:
        ...

    def execute_sql(
        self,
        sql: str,
        *,
        database_id: str,
        operation_type: str,
    ) -> dict[str, Any]:
        ...


class DatabaseOperationConfirmationRepository(Protocol):
    def create(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> DatabaseOperationConfirmationRecord:
        ...

    def get(self, confirmation_id: str) -> DatabaseOperationConfirmationRecord | None:
        ...

    def list_pending(self, *, user_id: str | None = None) -> list[DatabaseOperationConfirmationRecord]:
        ...

    def list_for_user(
        self,
        user_id: str,
        *,
        status: DatabaseOperationConfirmationStatus | None = None,
    ) -> list[DatabaseOperationConfirmationRecord]:
        ...

    def update(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> DatabaseOperationConfirmationRecord:
        ...

    def transition_pending_to_executing(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
        *,
        executing_at: datetime,
        execution_deadline_at: datetime,
    ) -> DatabaseOperationConfirmationRecord | None:
        ...


class SQLiteDatabaseOperationConfirmationRepository:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or config.enterprise_database_confirmation_sqlite_path)
        self._initialized = False

    def create(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> DatabaseOperationConfirmationRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                connection.execute(
                    """
                    INSERT INTO enterprise_database_operation_confirmations (
                        confirmation_id, user_id, database_id, status, operation_type,
                        created_at, expires_at, confirmation_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        confirmation.confirmation_id,
                        confirmation.user_id,
                        confirmation.database_id,
                        confirmation.status.value,
                        confirmation.operation_type,
                        confirmation.created_at.isoformat(),
                        confirmation.expires_at.isoformat(),
                        confirmation.model_dump_json(),
                    ),
                )
        return confirmation

    def get(self, confirmation_id: str) -> DatabaseOperationConfirmationRecord | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            row = connection.execute(
                """
                SELECT confirmation_json
                FROM enterprise_database_operation_confirmations
                WHERE confirmation_id = ?
                """,
                (confirmation_id,),
            ).fetchone()
        if row is None:
            return None
        return DatabaseOperationConfirmationRecord.model_validate(json.loads(row[0]))

    def list_pending(self, *, user_id: str | None = None) -> list[DatabaseOperationConfirmationRecord]:
        if not self.path.exists():
            return []
        clauses = ["status = ?"]
        params: list[str] = [DatabaseOperationConfirmationStatus.PENDING.value]
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(
                f"""
                SELECT confirmation_json
                FROM enterprise_database_operation_confirmations
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
        return [
            DatabaseOperationConfirmationRecord.model_validate(json.loads(row[0]))
            for row in rows
        ]

    def list_for_user(
        self,
        user_id: str,
        *,
        status: DatabaseOperationConfirmationStatus | None = None,
    ) -> list[DatabaseOperationConfirmationRecord]:
        if not self.path.exists():
            return []
        clauses = ["user_id = ?"]
        params: list[str] = [user_id]
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        with closing(sqlite3.connect(self.path)) as connection:
            self._init_schema(connection)
            rows = connection.execute(
                f"""
                SELECT confirmation_json
                FROM enterprise_database_operation_confirmations
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()
        return [
            DatabaseOperationConfirmationRecord.model_validate(json.loads(row[0]))
            for row in rows
        ]

    def update(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> DatabaseOperationConfirmationRecord:
        if not self.path.exists():
            raise KeyError(confirmation.confirmation_id)
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                cursor = connection.execute(
                    """
                    UPDATE enterprise_database_operation_confirmations
                    SET status = ?, confirmation_json = ?
                    WHERE confirmation_id = ?
                    """,
                    (
                        confirmation.status.value,
                        confirmation.model_dump_json(),
                        confirmation.confirmation_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(confirmation.confirmation_id)
        return confirmation

    def transition_pending_to_executing(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
        *,
        executing_at: datetime,
        execution_deadline_at: datetime,
    ) -> DatabaseOperationConfirmationRecord | None:
        if not self.path.exists():
            return None
        updated = confirmation.model_copy(
            update={
                "status": DatabaseOperationConfirmationStatus.EXECUTING,
                "confirmed_at": executing_at,
                "executing_at": executing_at,
                "execution_deadline_at": execution_deadline_at,
            },
        )
        with closing(sqlite3.connect(self.path)) as connection:
            with connection:
                self._init_schema(connection)
                cursor = connection.execute(
                    """
                    UPDATE enterprise_database_operation_confirmations
                    SET status = ?, confirmation_json = ?
                    WHERE confirmation_id = ? AND user_id = ? AND status = ?
                    """,
                    (
                        updated.status.value,
                        updated.model_dump_json(),
                        confirmation.confirmation_id,
                        confirmation.user_id,
                        DatabaseOperationConfirmationStatus.PENDING.value,
                    ),
                )
                if cursor.rowcount != 1:
                    return None
        return updated

    def _init_schema(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS enterprise_database_operation_confirmations (
                confirmation_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                database_id TEXT NOT NULL,
                status TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                confirmation_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_database_operation_confirmations_user_status
            ON enterprise_database_operation_confirmations(user_id, status)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_database_operation_confirmations_status
            ON enterprise_database_operation_confirmations(status)
            """
        )
        self._initialized = True


class SQLiteDatabaseOperationExecutor:
    dialect = "sqlite"

    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        database_path: str | Path,
    ):
        self.registry = registry
        self.database_id = registry.database_id
        self.database_path = Path(database_path)

    def supports_operation(self, operation_type: str) -> bool:
        return operation_type in {
            "insert",
            "update",
            "delete",
            "truncate",
            "drop_table",
            "ddl",
        }

    def supports_direct_operation(self, operation_type: str) -> bool:
        return False

    def execute_sql(
        self,
        sql: str,
        *,
        database_id: str,
        operation_type: str,
    ) -> dict[str, Any]:
        raise RuntimeError("database_direct_operation_not_supported")

    def count_matching_rows(self, sql: str, table_name: str) -> int | None:
        try:
            statement = sqlglot.parse_one(sql.strip(), read=self.dialect)
        except Exception:
            return None
        if not isinstance(statement, (exp.Update, exp.Delete)):
            return None

        try:
            table = self.registry.require_table(table_name)
        except KeyError:
            return None

        where = statement.args.get("where")
        where_sql = ""
        if isinstance(where, exp.Where):
            where_sql = f" WHERE {where.this.sql(dialect=self.dialect, normalize=True)}"
        query = f'SELECT COUNT(*) FROM "{table.name}"{where_sql}'
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(query).fetchone()
        if row is None:
            return None
        return int(row[0])

    def execute(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> dict[str, Any]:
        with closing(sqlite3.connect(self.database_path, timeout=2.0)) as connection:
            with connection:
                cursor = connection.execute(confirmation.normalized_sql)
                rows_affected = cursor.rowcount if cursor.rowcount >= 0 else None
        return {
            "rows_affected": rows_affected,
            "database_id": confirmation.database_id,
            "operation_type": confirmation.operation_type,
            "isolation_level": "sqlite_default_transaction",
        }


class DatabaseOperationPrepareService:
    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        database_path: str | Path | None,
        permission_service: PermissionService,
        repository: DatabaseOperationConfirmationRepository,
        audit_service: AuditService,
        dialect: str = "sqlite",
        operation_executor: DatabaseOperationExecutor | None = None,
    ):
        self.registry = registry
        self.database_path = Path(database_path) if database_path is not None else None
        self.permission_checker = DatabaseOperationPermissionChecker(
            registry=registry,
            permission_service=permission_service,
            dialect=dialect,
        )
        self.repository = repository
        self.audit_service = audit_service
        self.dialect = dialect
        if operation_executor is None:
            if self.database_path is None:
                raise ValueError("database_path_required_without_operation_executor")
            operation_executor = SQLiteDatabaseOperationExecutor(
                registry=registry,
                database_path=self.database_path,
            )
        self.operation_executor = operation_executor

    def prepare(
        self,
        context: RequestContext,
        *,
        database_id: str,
        sql: str,
        reason: str | None = None,
    ) -> DatabaseOperationPrepareResult:
        if database_id.strip() != self.registry.database_id:
            self._record_audit(
                context,
                event_type="database_operation_prepare_rejected",
                decision="denied",
                reason="database_not_configured",
                metadata={"database_id": database_id},
            )
            raise DatabaseOperationPrepareDenied("database_not_configured")

        permission_result = self.permission_checker.check_sql(context, sql)
        if not permission_result.allowed:
            self._record_audit(
                context,
                event_type="database_operation_prepare_rejected",
                decision="denied",
                reason=permission_result.reason,
                metadata=_permission_metadata(permission_result),
            )
            raise DatabaseOperationPrepareDenied(permission_result.reason)

        classification = permission_result.classification
        if not self.operation_executor.supports_operation(classification.operation_type):
            reason = (
                "database_operation_requires_confirmation"
                if classification.is_delete_like
                else "database_operation_does_not_require_confirmation"
            )
            self._record_audit(
                context,
                event_type="database_operation_prepare_rejected",
                decision="denied",
                reason=reason,
                metadata={
                    **_permission_metadata(permission_result),
                    "operation_type": classification.operation_type,
                },
            )
            raise DatabaseOperationPrepareDenied(reason)

        normalized_sql = _normalize_sql(sql, self.dialect)
        summary = self._build_summary(sql, classification)
        risk_level = _risk_level(classification.operation_level)
        created_at = datetime.now(UTC)
        confirmation = DatabaseOperationConfirmationRecord(
            user_id=context.user_id,
            username=context.username,
            database_id=self.registry.database_id,
            operation_level=classification.operation_level,
            operation_type=classification.operation_type,
            risk_level=risk_level,
            sql=sql,
            normalized_sql=normalized_sql,
            sql_hash=_hash_text(normalized_sql),
            parameters_hash=_hash_json({}),
            reason=reason,
            permission_reason=permission_result.reason,
            target_tables=classification.tables,
            target_columns=classification.columns,
            summary=summary,
            created_at=created_at,
            expires_at=created_at + timedelta(minutes=PENDING_TTL_MINUTES),
        )
        self.repository.create(confirmation)
        self._record_audit(
            context,
            event_type="database_operation_prepare_created",
            decision="allowed",
            reason=permission_result.reason,
            metadata={
                **self._confirmation_audit_metadata(confirmation),
                "summary": confirmation.summary.model_dump(mode="json"),
            },
        )
        return DatabaseOperationPrepareResult(
            confirmation_id=confirmation.confirmation_id,
            database_id=confirmation.database_id,
            operation_level=confirmation.operation_level,
            operation_type=confirmation.operation_type,
            risk_level=confirmation.risk_level,
            summary=confirmation.summary,
            expires_at=confirmation.expires_at,
        )

    def list_confirmations(
        self,
        context: RequestContext,
        *,
        status: DatabaseOperationConfirmationStatus | None = None,
    ) -> list[DatabaseOperationConfirmationRecord]:
        return self.repository.list_for_user(context.user_id, status=status)

    def get_confirmation(
        self,
        context: RequestContext,
        confirmation_id: str,
    ) -> DatabaseOperationConfirmationRecord:
        confirmation = self.repository.get(confirmation_id)
        if confirmation is None or confirmation.user_id != context.user_id:
            raise DatabaseOperationConfirmationDenied(
                "confirmation_not_found",
                status_code=404,
            )
        return confirmation

    def cancel(
        self,
        context: RequestContext,
        confirmation_id: str,
    ) -> DatabaseOperationConfirmationRecord:
        confirmation = self.get_confirmation(context, confirmation_id)
        if confirmation.status != DatabaseOperationConfirmationStatus.PENDING:
            raise DatabaseOperationConfirmationDenied(
                "confirmation_not_pending",
                status_code=409,
            )
        cancelled_at = datetime.now(UTC)
        updated = confirmation.model_copy(
            update={
                "status": DatabaseOperationConfirmationStatus.CANCELLED,
                "cancelled_at": cancelled_at,
            },
        )
        self.repository.update(updated)
        self._record_audit(
            context,
            event_type="database_operation_confirmation_cancelled",
            decision="allowed",
            reason="cancelled_by_owner",
            metadata=self._confirmation_audit_metadata(updated),
            route="/api/database/confirmations/{confirmation_id}/cancel",
        )
        return updated

    def confirm(
        self,
        context: RequestContext,
        confirmation_id: str,
    ) -> DatabaseOperationConfirmationRecord:
        confirmation = self.get_confirmation(context, confirmation_id)
        if confirmation.status != DatabaseOperationConfirmationStatus.PENDING:
            raise DatabaseOperationConfirmationDenied(
                "confirmation_not_pending",
                status_code=409,
            )
        now = datetime.now(UTC)
        if confirmation.expires_at <= now:
            expired = confirmation.model_copy(
                update={
                    "status": DatabaseOperationConfirmationStatus.EXPIRED,
                    "failure_reason": "confirmation_expired",
                },
            )
            self.repository.update(expired)
            self._record_audit(
                context,
                event_type="database_operation_confirmation_expired",
                decision="denied",
                reason="confirmation_expired",
                metadata=self._confirmation_audit_metadata(expired),
                route="/api/database/confirmations/{confirmation_id}/confirm",
            )
            raise DatabaseOperationConfirmationDenied(
                "confirmation_expired",
                status_code=409,
            )

        recheck_reason = self._confirmation_recheck_reason(context, confirmation)
        if recheck_reason is not None:
            failed = self._mark_failed(context, confirmation, recheck_reason)
            raise DatabaseOperationConfirmationDenied(
                failed.failure_reason or recheck_reason,
                status_code=403,
            )

        executing = self.repository.transition_pending_to_executing(
            confirmation,
            executing_at=now,
            execution_deadline_at=now + timedelta(minutes=EXECUTION_DEADLINE_MINUTES),
        )
        if executing is None:
            raise DatabaseOperationConfirmationDenied(
                "confirmation_not_pending",
                status_code=409,
            )

        self._record_audit(
            context,
            event_type="database_operation_confirmation_confirmed",
            decision="allowed",
            reason="confirmed_by_owner",
            metadata=self._confirmation_audit_metadata(executing),
            route="/api/database/confirmations/{confirmation_id}/confirm",
        )
        try:
            execution_result = self.operation_executor.execute(executing)
        except Exception:
            failed = self._mark_failed(
                context,
                executing,
                "database_operation_execution_failed",
            )
            raise DatabaseOperationConfirmationDenied(
                failed.failure_reason or "database_operation_execution_failed",
                status_code=500,
            ) from None

        executed_at = datetime.now(UTC)
        executed = executing.model_copy(
            update={
                "status": DatabaseOperationConfirmationStatus.EXECUTED,
                "executed_at": executed_at,
                "execution_result": execution_result,
            },
        )
        self.repository.update(executed)
        self._record_audit(
            context,
            event_type="database_operation_executed",
            decision="allowed",
            reason="executed",
            metadata={
                **self._confirmation_audit_metadata(executed),
                **execution_result,
            },
            route="/api/database/confirmations/{confirmation_id}/confirm",
        )
        return executed

    def _confirmation_recheck_reason(
        self,
        context: RequestContext,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> str | None:
        if confirmation.database_id != self.registry.database_id:
            return "database_mismatch"
        if not self.operation_executor.supports_operation(confirmation.operation_type):
            return "database_operation_execution_unsupported_for_database"
        try:
            normalized_sql = _normalize_sql(confirmation.sql, self.dialect)
        except Exception:
            return "sql_parse_failed"
        if _hash_text(normalized_sql) != confirmation.sql_hash:
            return "sql_hash_mismatch"
        if _hash_json({}) != confirmation.parameters_hash:
            return "parameters_hash_mismatch"

        permission_result = self.permission_checker.check_sql(context, confirmation.sql)
        if not permission_result.allowed:
            return permission_result.reason

        classification = permission_result.classification
        if classification.tables != confirmation.target_tables:
            return "target_tables_changed"
        if classification.columns != confirmation.target_columns:
            return "target_columns_changed"

        summary = self._build_summary(confirmation.sql, classification)
        if (
            confirmation.summary.estimate_reliable
            and summary.estimate_reliable
            and summary.estimated_affected_rows
            != confirmation.summary.estimated_affected_rows
        ):
            return "preview_summary_changed"
        return None

    def _mark_failed(
        self,
        context: RequestContext,
        confirmation: DatabaseOperationConfirmationRecord,
        reason: str,
    ) -> DatabaseOperationConfirmationRecord:
        failed_at = datetime.now(UTC)
        failed = confirmation.model_copy(
            update={
                "status": DatabaseOperationConfirmationStatus.FAILED,
                "failed_at": failed_at,
                "failure_reason": reason,
            },
        )
        self.repository.update(failed)
        self._record_audit(
            context,
            event_type="database_operation_execution_failed",
            decision="denied",
            reason=reason,
            metadata=self._confirmation_audit_metadata(failed),
            route="/api/database/confirmations/{confirmation_id}/confirm",
        )
        return failed

    def _confirmation_audit_metadata(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> dict[str, Any]:
        return {
            "confirmation_id": confirmation.confirmation_id,
            "database_id": confirmation.database_id,
            "operation_level": confirmation.operation_level,
            "operation_type": confirmation.operation_type,
            "risk_level": confirmation.risk_level,
            "sql_hash": confirmation.sql_hash,
            "parameters_hash": confirmation.parameters_hash,
            "sql_hash_version": confirmation.sql_hash_version,
            "normalization_version": confirmation.normalization_version,
            "target_tables": confirmation.target_tables,
            "target_columns": confirmation.target_columns,
            "resource_ids": self._confirmation_resource_ids(confirmation),
        }

    def _confirmation_resource_ids(
        self,
        confirmation: DatabaseOperationConfirmationRecord,
    ) -> list[str]:
        resource_ids = [
            database_operation_resource_id(
                confirmation.database_id,
                confirmation.operation_type,
            )
        ]
        for table_name in confirmation.target_tables:
            try:
                table = self.registry.require_table(table_name)
                canonical_table_name = table.name
            except KeyError:
                canonical_table_name = table_name
            resource_ids.append(
                database_table_resource_id(confirmation.database_id, canonical_table_name)
            )
            for column_name in confirmation.target_columns:
                try:
                    column = self.registry.require_column(canonical_table_name, column_name)
                except KeyError:
                    continue
                resource_ids.append(
                    database_column_resource_id(
                        confirmation.database_id,
                        canonical_table_name,
                        column.name,
                    )
                )
        return sorted(set(resource_ids))

    def _build_summary(self, sql: str, classification) -> DatabaseOperationRiskSummary:
        estimate = self._estimate_affected_rows(sql, classification)
        return DatabaseOperationRiskSummary(
            estimated_affected_rows=estimate["rows"],
            estimate_reliable=estimate["reliable"],
            estimate_reason=estimate["reason"],
            target_tables=classification.tables,
            target_columns=classification.columns,
        )

    def _estimate_affected_rows(self, sql: str, classification) -> dict[str, Any]:
        if classification.operation_type in {"update", "delete"} and len(classification.tables) == 1:
            rows = self._count_matching_rows(sql, classification.tables[0])
            if rows is not None:
                return {
                    "rows": rows,
                    "reliable": True,
                    "reason": "where_count_preview",
                }
        if classification.operation_type == "insert":
            rows = _insert_values_count(sql, self.dialect)
            if rows is not None:
                return {
                    "rows": rows,
                    "reliable": True,
                    "reason": "insert_values_count_preview",
                }
        return {
            "rows": None,
            "reliable": False,
            "reason": "preview_not_supported_for_operation",
        }

    def _count_matching_rows(self, sql: str, table_name: str) -> int | None:
        return self.operation_executor.count_matching_rows(sql, table_name)

    def _record_audit(
        self,
        context: RequestContext,
        *,
        event_type: str,
        decision: str,
        reason: str,
        metadata: dict[str, Any],
        route: str = "/api/database/operations/prepare",
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type=event_type,
                route=route,
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision,
                reason=reason,
                metadata=metadata,
            )
        )


class DatabaseOperationDirectExecuteService:
    def __init__(
        self,
        *,
        registry: DatabaseSchemaRegistry,
        permission_service: PermissionService,
        audit_service: AuditService,
        operation_executor: DatabaseOperationDirectExecutor,
        dialect: str = "sqlite",
    ):
        self.registry = registry
        self.permission_checker = DatabaseOperationPermissionChecker(
            registry=registry,
            permission_service=permission_service,
            dialect=dialect,
        )
        self.audit_service = audit_service
        self.operation_executor = operation_executor
        self.dialect = dialect

    def execute(
        self,
        context: RequestContext,
        *,
        database_id: str,
        sql: str,
    ) -> DatabaseOperationDirectExecuteResult:
        if database_id.strip() != self.registry.database_id:
            self._record_audit(
                context,
                event_type="database_operation_direct_execute_rejected",
                decision="denied",
                reason="database_not_configured",
                metadata={"database_id": database_id},
            )
            raise DatabaseOperationDirectExecuteDenied("database_not_configured")

        permission_result = self.permission_checker.check_sql(context, sql)
        if not permission_result.allowed:
            self._record_audit(
                context,
                event_type="database_operation_direct_execute_rejected",
                decision="denied",
                reason=permission_result.reason,
                metadata=_permission_metadata(permission_result),
            )
            raise DatabaseOperationDirectExecuteDenied(permission_result.reason)

        classification = permission_result.classification
        if classification.is_delete_like:
            self._record_audit(
                context,
                event_type="database_operation_direct_execute_rejected",
                decision="denied",
                reason="database_operation_requires_confirmation",
                metadata=_permission_metadata(permission_result),
            )
            raise DatabaseOperationDirectExecuteDenied(
                "database_operation_requires_confirmation",
            )

        if not self.operation_executor.supports_direct_operation(classification.operation_type):
            self._record_audit(
                context,
                event_type="database_operation_direct_execute_rejected",
                decision="denied",
                reason="database_operation_execution_unsupported_for_database",
                metadata=_permission_metadata(permission_result),
            )
            raise DatabaseOperationDirectExecuteDenied(
                "database_operation_execution_unsupported_for_database",
            )

        normalized_sql = _normalize_sql(sql, self.dialect)
        sql_hash = _hash_text(normalized_sql)
        parameters_hash = _hash_json({})
        metadata = {
            **_permission_metadata(permission_result),
            "sql_hash": sql_hash,
            "parameters_hash": parameters_hash,
            "sql_hash_version": SQL_HASH_VERSION,
            "normalization_version": NORMALIZATION_VERSION,
            "target_tables": classification.tables,
            "target_columns": classification.columns,
            "resource_ids": _operation_resource_ids(
                registry=self.registry,
                operation_resource_id=permission_result.operation_resource_id,
                target_tables=classification.tables,
                target_columns=classification.columns,
            ),
        }

        try:
            execution_result = self.operation_executor.execute_sql(
                normalized_sql,
                database_id=self.registry.database_id,
                operation_type=classification.operation_type,
            )
        except Exception:
            self._record_audit(
                context,
                event_type="database_operation_direct_execution_failed",
                decision="denied",
                reason="database_operation_execution_failed",
                metadata=metadata,
            )
            raise DatabaseOperationDirectExecuteDenied(
                "database_operation_execution_failed",
                status_code=500,
            ) from None

        self._record_audit(
            context,
            event_type="database_operation_direct_executed",
            decision="allowed",
            reason="executed",
            metadata={**metadata, **execution_result},
        )
        return DatabaseOperationDirectExecuteResult(
            database_id=self.registry.database_id,
            operation_level=classification.operation_level,
            operation_type=classification.operation_type,
            sql_hash=sql_hash,
            parameters_hash=parameters_hash,
            target_tables=classification.tables,
            target_columns=classification.columns,
            execution_result=execution_result,
        )

    def _record_audit(
        self,
        context: RequestContext,
        *,
        event_type: str,
        decision: str,
        reason: str,
        metadata: dict[str, Any],
        route: str = "/api/database/operations/execute",
    ) -> None:
        self.audit_service.record(
            AuditEvent(
                event_type=event_type,
                route=route,
                trace_id=context.trace_id,
                request_id=context.request_id,
                user_id=context.user_id,
                decision=decision,
                reason=reason,
                metadata=metadata,
            )
        )


def _permission_metadata(permission_result: DatabaseOperationPermissionResult) -> dict[str, Any]:
    return {
        "database_id": permission_result.classification.database_id,
        "operation_level": permission_result.classification.operation_level,
        "operation_type": permission_result.classification.operation_type,
        "operation_resource_id": permission_result.operation_resource_id,
        "denied_tables": permission_result.denied_tables,
        "denied_columns": permission_result.denied_columns,
    }


def _operation_resource_ids(
    *,
    registry: DatabaseSchemaRegistry,
    operation_resource_id: str | None,
    target_tables: list[str],
    target_columns: list[str],
) -> list[str]:
    resource_ids = []
    if operation_resource_id is not None:
        resource_ids.append(operation_resource_id)
    for table_name in target_tables:
        try:
            table = registry.require_table(table_name)
            canonical_table_name = table.name
        except KeyError:
            canonical_table_name = table_name
        resource_ids.append(database_table_resource_id(registry.database_id, canonical_table_name))
        for column_name in target_columns:
            try:
                column = registry.require_column(canonical_table_name, column_name)
            except KeyError:
                continue
            resource_ids.append(
                database_column_resource_id(
                    registry.database_id,
                    canonical_table_name,
                    column.name,
                )
            )
    return sorted(set(resource_ids))


def _normalize_sql(sql: str, dialect: str) -> str:
    statement = sqlglot.parse_one(sql.strip(), read=dialect)
    return statement.sql(dialect=dialect, normalize=True)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_text(payload)


def _insert_values_count(sql: str, dialect: str) -> int | None:
    try:
        statement = sqlglot.parse_one(sql.strip(), read=dialect)
    except Exception:
        return None
    if not isinstance(statement, exp.Insert):
        return None
    values = statement.args.get("expression")
    if not isinstance(values, exp.Values):
        return None
    return len(values.expressions)


def _risk_level(operation_level: str) -> str:
    if operation_level == "L3":
        return "medium"
    if operation_level == "L4":
        return "high"
    if operation_level == "L5":
        return "high"
    return "unknown"
