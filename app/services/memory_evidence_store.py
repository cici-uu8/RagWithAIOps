"""SQLite metadata plus refs store for L0 raw memory evidence."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from pydantic import BaseModel

from app.models.memory_evidence import EvidenceRef, EvidenceRefType, L0Evidence


class MemoryEvidenceStore:
    """Persist L0 evidence metadata and large raw payload refs."""

    def __init__(
        self,
        store_path: str | Path = "./uploads/_metadata/oncall_memory_evidence.sqlite3",
        refs_dir: str | Path | None = None,
    ):
        self.store_path = Path(store_path).resolve()
        self.refs_dir = Path(refs_dir).resolve() if refs_dir else self.store_path.parent / "oncall_memory_evidence_refs"
        self._lock = RLock()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.refs_dir.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS memory_l0_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    service TEXT,
                    alert_name TEXT,
                    environment TEXT,
                    diagnosis_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    evidence_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_l0_evidence_owner_session "
                "ON memory_l0_evidence(owner_id, session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_l0_evidence_scope "
                "ON memory_l0_evidence(owner_id, service, alert_name, created_at)"
            )
            conn.commit()

    def save(self, evidence: L0Evidence) -> L0Evidence:
        """Upsert one L0 evidence metadata record."""

        payload = evidence.model_dump_json()
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_l0_evidence (
                    evidence_id, owner_id, session_id, source_type, service, alert_name,
                    environment, diagnosis_status, created_at, evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    owner_id = excluded.owner_id,
                    session_id = excluded.session_id,
                    source_type = excluded.source_type,
                    service = excluded.service,
                    alert_name = excluded.alert_name,
                    environment = excluded.environment,
                    diagnosis_status = excluded.diagnosis_status,
                    created_at = excluded.created_at,
                    evidence_json = excluded.evidence_json
                """,
                (
                    evidence.evidence_id,
                    evidence.owner_id,
                    evidence.session_id,
                    evidence.source_type,
                    evidence.service,
                    evidence.alert_name,
                    evidence.environment,
                    evidence.diagnosis_status,
                    evidence.created_at.isoformat(),
                    payload,
                ),
            )
            conn.commit()
        return evidence.model_copy(deep=True)

    def get(self, evidence_id: str) -> L0Evidence | None:
        """Load one evidence record without silently checking refs."""

        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT evidence_json FROM memory_l0_evidence WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            return None
        return L0Evidence.model_validate(json.loads(row["evidence_json"]))

    def list_evidence(
        self,
        *,
        owner_id: str = "default",
        session_id: str | None = None,
        service: str | None = None,
        alert_name: str | None = None,
        diagnosis_status: str | None = None,
    ) -> list[L0Evidence]:
        """List L0 evidence by common metadata filters."""

        clauses = ["owner_id = ?"]
        params: list[str] = [owner_id]
        for column, value in (
            ("session_id", session_id),
            ("service", service),
            ("alert_name", alert_name),
            ("diagnosis_status", diagnosis_status),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)

        query = (
            "SELECT evidence_json FROM memory_l0_evidence "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at ASC, evidence_id ASC"
        )
        with self._lock, self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [L0Evidence.model_validate(json.loads(row["evidence_json"])) for row in rows]

    def create_aiops_evidence(
        self,
        *,
        session_id: str,
        owner_id: str = "default",
        query: str,
        plan: list[str],
        past_steps: list[Any],
        final_response: str,
        key_events: list[dict[str, Any]] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        memory_observation: dict[str, Any] | None = None,
        service: str | None = None,
        alert_name: str | None = None,
        environment: str | None = None,
        diagnosis_status: str = "complete",
        evidence_id: str | None = None,
        created_at: datetime | None = None,
    ) -> L0Evidence:
        """Create one AIOps L0 evidence record with external raw refs."""

        evidence_id = evidence_id or f"l0_aiops_{uuid.uuid4().hex}"
        created_at = created_at or datetime.now()
        temp_refs: list[tuple[Path, Path]] = []
        final_paths: list[Path] = []

        try:
            final_response_ref, temp_pair = self._prepare_ref(
                evidence_id=evidence_id,
                ref_type=EvidenceRefType.FINAL_RESPONSE,
                payload=final_response,
                created_at=created_at,
            )
            temp_refs.append(temp_pair)
            final_paths.append(Path(final_response_ref.path))

            past_steps_ref, temp_pair = self._prepare_ref(
                evidence_id=evidence_id,
                ref_type=EvidenceRefType.PAST_STEPS,
                payload=past_steps,
                created_at=created_at,
            )
            temp_refs.append(temp_pair)
            final_paths.append(Path(past_steps_ref.path))

            key_events_ref = None
            if key_events is not None:
                key_events_ref, temp_pair = self._prepare_ref(
                    evidence_id=evidence_id,
                    ref_type=EvidenceRefType.KEY_EVENTS,
                    payload=key_events,
                    created_at=created_at,
                )
                temp_refs.append(temp_pair)
                final_paths.append(Path(key_events_ref.path))

            tool_results_ref = None
            if tool_results is not None:
                tool_results_ref, temp_pair = self._prepare_ref(
                    evidence_id=evidence_id,
                    ref_type=EvidenceRefType.TOOL_RESULTS,
                    payload=tool_results,
                    created_at=created_at,
                )
                temp_refs.append(temp_pair)
                final_paths.append(Path(tool_results_ref.path))

            memory_observation_json = None
            memory_observation_ref = None
            if memory_observation is not None:
                memory_observation_json = _dumps(memory_observation)
                memory_observation_ref, temp_pair = self._prepare_ref(
                    evidence_id=evidence_id,
                    ref_type=EvidenceRefType.MEMORY_OBSERVATION,
                    payload=memory_observation,
                    created_at=created_at,
                )
                temp_refs.append(temp_pair)
                final_paths.append(Path(memory_observation_ref.path))

            refs = [
                ref
                for ref in (
                    final_response_ref,
                    past_steps_ref,
                    key_events_ref,
                    tool_results_ref,
                    memory_observation_ref,
                )
                if ref is not None
            ]
            refs_manifest_json = _dumps(
                {
                    "evidence_id": evidence_id,
                    "refs": [ref.model_dump(mode="json") for ref in refs],
                }
            )
            evidence = L0Evidence(
                evidence_id=evidence_id,
                session_id=_require_text(session_id, "session_id"),
                owner_id=_require_text(owner_id, "owner_id"),
                query=_require_text(query, "query"),
                service=_optional_text(service),
                alert_name=_optional_text(alert_name),
                environment=_optional_text(environment),
                final_response_preview=_truncate(final_response),
                final_response_ref=final_response_ref,
                plan_json=_dumps(plan),
                past_steps_ref=past_steps_ref,
                key_events_ref=key_events_ref,
                tool_results_ref=tool_results_ref,
                memory_observation_json=memory_observation_json,
                diagnosis_status=diagnosis_status,
                created_at=created_at,
                evidence_size_bytes=sum(ref.size_bytes for ref in refs) + len(refs_manifest_json.encode("utf-8")),
                refs_manifest_json=refs_manifest_json,
            )

            self.save(evidence)
            for temp_path, final_path in temp_refs:
                os.replace(temp_path, final_path)
            return evidence
        except Exception:
            self._delete_metadata(evidence_id)
            for temp_path, final_path in temp_refs:
                _unlink_if_exists(temp_path)
                _unlink_if_exists(final_path)
            for path in final_paths:
                _unlink_if_exists(path)
            raise

    def check_integrity(self, evidence_id: str) -> dict[str, Any]:
        """Validate that refs listed by metadata still exist and match hashes."""

        evidence = self.get(evidence_id)
        if evidence is None:
            return {"ok": False, "evidence_id": evidence_id, "missing_evidence": True}

        refs = self._manifest_refs(evidence)
        missing_refs: list[dict[str, Any]] = []
        checksum_mismatches: list[dict[str, Any]] = []

        for ref in refs:
            path = Path(ref["path"])
            if not path.exists():
                missing_refs.append({"ref_type": ref["ref_type"], "path": str(path)})
                continue
            actual_sha = _sha256(path)
            actual_size = path.stat().st_size
            if actual_sha != ref["sha256"] or actual_size != ref["size_bytes"]:
                checksum_mismatches.append(
                    {
                        "ref_type": ref["ref_type"],
                        "path": str(path),
                        "expected_sha256": ref["sha256"],
                        "actual_sha256": actual_sha,
                        "expected_size_bytes": ref["size_bytes"],
                        "actual_size_bytes": actual_size,
                    }
                )

        return {
            "ok": not missing_refs and not checksum_mismatches,
            "evidence_id": evidence_id,
            "refs_checked": len(refs),
            "missing_refs": missing_refs,
            "checksum_mismatches": checksum_mismatches,
        }

    def cleanup_expired_evidence(
        self,
        *,
        retention_days: int = 30,
        owner_id: str = "default",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Build or apply a retention cleanup plan for L0 evidence."""

        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        cutoff = datetime.now() - timedelta(days=retention_days)
        records = [
            evidence
            for evidence in self.list_evidence(owner_id=owner_id)
            if _strip_tz(evidence.created_at) < cutoff
        ]
        planned = [
            {
                "evidence_id": evidence.evidence_id,
                "session_id": evidence.session_id,
                "created_at": evidence.created_at.isoformat(),
                "refs": [ref["path"] for ref in self._manifest_refs(evidence)],
            }
            for evidence in records
        ]

        deleted_count = 0
        if not dry_run:
            for evidence in records:
                for ref in self._manifest_refs(evidence):
                    _unlink_if_exists(Path(ref["path"]))
                self._delete_metadata(evidence.evidence_id)
                deleted_count += 1

        return {
            "dry_run": dry_run,
            "retention_days": retention_days,
            "owner_id": owner_id,
            "planned_delete_count": len(planned),
            "deleted_count": deleted_count,
            "records": planned,
        }

    def _prepare_ref(
        self,
        *,
        evidence_id: str,
        ref_type: EvidenceRefType,
        payload: Any,
        created_at: datetime,
    ) -> tuple[EvidenceRef, tuple[Path, Path]]:
        final_path = self.refs_dir / f"{evidence_id}_{ref_type.value}.jsonl"
        temp_path = self.refs_dir / f"{evidence_id}_{ref_type.value}.jsonl.tmp"
        lines = _payload_lines(payload)
        with temp_path.open("w", encoding="utf-8") as f:
            for line in lines:
                f.write(_dumps(line))
                f.write("\n")
        ref = EvidenceRef(
            ref_id=f"{evidence_id}:{ref_type.value}",
            evidence_id=evidence_id,
            ref_type=ref_type,
            path=str(final_path),
            sha256=_sha256(temp_path),
            size_bytes=temp_path.stat().st_size,
            created_at=created_at,
        )
        return ref, (temp_path, final_path)

    def _manifest_refs(self, evidence: L0Evidence) -> list[dict[str, Any]]:
        manifest = json.loads(evidence.refs_manifest_json)
        refs = manifest.get("refs", [])
        return [ref for ref in refs if isinstance(ref, dict)]

    def _delete_metadata(self, evidence_id: str) -> None:
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM memory_l0_evidence WHERE evidence_id = ?", (evidence_id,))
            conn.commit()


def _payload_lines(payload: Any) -> list[dict[str, Any]]:
    normalized = _jsonable(payload)
    if isinstance(normalized, list):
        return [{"seq": index, "payload": item} for index, item in enumerate(normalized)]
    return [{"seq": 0, "payload": normalized}]


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def _dumps(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truncate(text: str, limit: int = 400) -> str:
    text = str(text or "").strip()
    if not text:
        return "(empty final response)"
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3]}..."


def _require_text(value: str, field_name: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"{field_name} is required")
    return str(value).strip()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _strip_tz(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


memory_evidence_store = MemoryEvidenceStore()
