"""Beta-readiness smoke for the current RAG production-facing baseline.

This smoke is intentionally small and deterministic. It exercises the same
service boundaries that production uses for auth, RAG permission filtering,
source references, config defaults, and audit, but uses a controlled in-memory
document corpus so the check does not depend on external LLM or Milvus uptime.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
from app.config import config
from app.enterprise.adapters.rag_adapter import RagAdapter
from app.enterprise.auth.service import auth_service
from app.enterprise.context import RequestContext
from app.enterprise.observability.audit_service import AuditService, InMemoryAuditSink
from app.enterprise.permissions.models import GrantEffect, PrincipalType, ResourceGrant
from app.enterprise.permissions.repository import InMemoryGovernanceRepository
from app.enterprise.permissions.service import PermissionService
from app.models import (
    ChunkRecord,
    DocumentRecord,
    DocumentStatus,
    ParserEngine,
    RetrievalQuery,
    SourceRef,
)
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.retrieval_service import RetrievalService
from app.services.vector_search_service import SearchResult as RawSearchResult

CURRENT_BASELINE: dict[str, Any] = {
    "indexed_docs": 30,
    "retrieval_evalset": "department_rag_mixed_markdown_pdf_54q_after_c6_p2",
    "retrieval_passed": 45,
    "retrieval_total": 54,
    "wrong_scope_count": 0,
    "citation_unresolvable_count": 0,
    "all_source_ref_resolvable": True,
    "answer_hard_gates_clean": True,
    "answer_coverage": "limited",
}

REQUIRED_FEEDBACK_FIELDS: tuple[str, ...] = (
    "timestamp",
    "user_id",
    "session_id",
    "query",
    "retrieved_docs",
    "answer",
    "answer_issue",
    "missing_facts",
    "source_refs",
    "source_ref_resolvable",
    "permission_scope_issue",
    "followup_decision",
)

FEEDBACK_ANSWER_ISSUES: tuple[str, ...] = (
    "none",
    "answer_incomplete",
    "answer_wrong",
    "source_ref_unresolvable",
    "permission_scope_issue",
    "retrieval_no_hit",
    "retrieval_wrong_doc",
    "expression_gap",
    "other",
)

FEEDBACK_FOLLOWUP_DECISIONS: tuple[str, ...] = (
    "no_action",
    "queue_for_review",
    "reproduce",
    "open_answer_revisit",
    "open_retrieval_triage",
    "open_security_bug",
)


def run_smoke(output_path: str | Path | None = None) -> dict[str, Any]:
    """Run the deterministic beta-readiness smoke and optionally persist JSON."""

    auth_check = _check_auth_login()
    rag_bundle = _check_controlled_rag()
    feedback_check = _check_feedback_schema()
    config_check = _check_config_defaults()
    checks = [
        auth_check,
        rag_bundle["rag_qa_controlled"],
        rag_bundle["source_ref_lookup"],
        rag_bundle["permission_filtering"],
        rag_bundle["audit_logging"],
        feedback_check,
        config_check,
    ]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "status": "passed" if all(check["status"] == "passed" for check in checks) else "failed",
            "check_count": len(checks),
            "passed_count": sum(1 for check in checks if check["status"] == "passed"),
            "failed_count": sum(1 for check in checks if check["status"] != "passed"),
            "scope": "beta_readiness_minimum_loop",
            "external_llm_called": False,
            "external_vector_db_called": False,
        },
        "baseline": dict(CURRENT_BASELINE),
        "config_defaults": _config_defaults(),
        "checks": checks,
        "next_optimization_trigger": {
            "source": "real_user_feedback_only",
            "answer_revisit_rule": (
                "If real feedback clusters around incomplete answers, reopen S5 Answer revisit "
                "with a narrow pilot first; do not jump directly to Answer 50q."
            ),
        },
    }
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def validate_feedback_record(record: Mapping[str, Any]) -> list[str]:
    """Validate the required user-feedback intake fields."""

    errors: list[str] = []
    for field in REQUIRED_FEEDBACK_FIELDS:
        if field not in record:
            errors.append(f"missing_required_field:{field}")
            continue
        value = record[field]
        if isinstance(value, str) and not value.strip():
            errors.append(f"empty_required_field:{field}")
        elif value is None:
            errors.append(f"empty_required_field:{field}")
    for list_field in ("retrieved_docs", "missing_facts", "source_refs"):
        if list_field in record and not isinstance(record[list_field], list):
            errors.append(f"invalid_type:{list_field}:expected_list")
    for bool_field in ("source_ref_resolvable", "permission_scope_issue"):
        if bool_field in record and not isinstance(record[bool_field], bool):
            errors.append(f"invalid_type:{bool_field}:expected_bool")
    answer_issue = record.get("answer_issue")
    if isinstance(answer_issue, str) and answer_issue not in FEEDBACK_ANSWER_ISSUES:
        errors.append(f"invalid_enum:answer_issue:{answer_issue}")
    followup_decision = record.get("followup_decision")
    if isinstance(followup_decision, str) and followup_decision not in FEEDBACK_FOLLOWUP_DECISIONS:
        errors.append(f"invalid_enum:followup_decision:{followup_decision}")
    return errors


def _check_auth_login() -> dict[str, Any]:
    auth_service.clear_blacklist()
    app = FastAPI()
    app.include_router(auth_api.router, prefix="/api")
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "Admin123!"},
    )
    payload = response.json()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    passed = (
        response.status_code == 200
        and payload.get("code") == 200
        and bool(data.get("access_token"))
        and data.get("token_type") == "bearer"
        and data.get("user", {}).get("user_id") == "user_admin"
    )
    return _check(
        "auth_login",
        passed,
        {
            "status_code": response.status_code,
            "user_id": data.get("user", {}).get("user_id"),
            "department_id": data.get("user", {}).get("department_id"),
            "roles": data.get("user", {}).get("roles", []),
            "token_type": data.get("token_type"),
        },
    )


def _check_controlled_rag() -> dict[str, dict[str, Any]]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        metadata_store = KnowledgeMetadataStore(root / "metadata.json")
        _seed_documents(metadata_store, root)

        sink = InMemoryAuditSink()
        audit_service = AuditService(sinks=[sink])
        permission_service = PermissionService(
            repository=InMemoryGovernanceRepository(),
            audit_service=audit_service,
        )
        permission_service.grant_access(
            ResourceGrant(
                resource_type="document",
                resource_id="doc-visible",
                action="read",
                principal_type=PrincipalType.USER,
                principal_id="user_demo_dept1",
                effect=GrantEffect.ALLOW,
                reason="beta-smoke-visible-doc",
            )
        )

        adapter = RagAdapter(
            RetrievalService(),
            permission_service=permission_service,
            metadata_store=metadata_store,
            audit_service=audit_service,
        )
        context = RequestContext(
            request_id="request-beta-smoke",
            trace_id="trace-beta-smoke",
            user_id="user_demo_dept1",
            username="demo_user_dept1",
            department_id="dept_1",
            department_name="Department 1",
            roles=["user"],
        )
        raw_hits = [
            _raw_hit(
                kb_id="process_digital_dept",
                doc_id="doc-hidden",
                chunk_id="doc-hidden:c00001",
                source_file="hidden.md",
                heading_path=["Hidden Root Cause"],
                content="hidden remediation password rotation",
            ),
            _raw_hit(
                kb_id="process_digital_dept",
                doc_id="doc-visible",
                chunk_id="doc-visible:c00001",
                source_file="visible.md",
                heading_path=["Visible SOP"],
                content="authorized restart procedure",
            ),
        ]
        query = RetrievalQuery(
            query="restart procedure",
            top_k=3,
            retrieval_mode=config.rag_default_retrieval_mode,
            knowledge_base_ids=["process_digital_dept"],
        )
        with patch(
            "app.services.retrieval_service.vector_search_service.search_similar_documents",
            return_value=raw_hits,
        ):
            response = adapter.retrieve(context, query)

        result_doc_ids = [result.doc_id for result in response.results]
        answer = _controlled_answer(response.context_text)
        source_ref = response.results[0].source_ref if response.results else None
        source_lookup = _resolve_source_ref(metadata_store, source_ref)
        event_types = [event.event_type for event in sink.events]
        retrieval_events = [event for event in sink.events if event.event_type == "rag_retrieval"]
        retrieval_metadata = retrieval_events[-1].metadata if retrieval_events else {}
        blocked_doc_ids = retrieval_metadata.get("blocked_doc_ids", [])

    return {
        "rag_qa_controlled": _check(
            "rag_qa_controlled",
            result_doc_ids == ["doc-visible"] and "authorized restart procedure" in answer,
            {
                "query": query.query,
                "retrieved_doc_ids": result_doc_ids,
                "answer": answer,
                "llm_called": False,
            },
        ),
        "source_ref_lookup": _check(
            "source_ref_lookup",
            bool(source_lookup.get("resolvable")),
            source_lookup,
        ),
        "permission_filtering": _check(
            "permission_filtering",
            blocked_doc_ids == ["doc-hidden"] and result_doc_ids == ["doc-visible"],
            {
                "allowed_doc_ids": retrieval_metadata.get("allowed_doc_ids", []),
                "blocked_doc_ids": blocked_doc_ids,
                "result_doc_ids": retrieval_metadata.get("result_doc_ids", []),
            },
        ),
        "audit_logging": _check(
            "audit_logging",
            "permission_checked" in event_types and "rag_retrieval" in event_types,
            {
                "event_count": len(event_types),
                "event_types": event_types,
                "trace_id": "trace-beta-smoke",
            },
        ),
    }


def _check_feedback_schema() -> dict[str, Any]:
    sample = {
        "timestamp": datetime.now(UTC).isoformat(),
        "user_id": "user_demo_dept1",
        "session_id": "session-beta-smoke",
        "query": "Redis 内存打满怎么办",
        "retrieved_docs": [{"doc_id": "doc-redis", "source_file": "redis.md"}],
        "answer": "先确认 used_memory 和 maxmemory。",
        "answer_issue": "answer_incomplete",
        "missing_facts": ["未覆盖 evicted_keys"],
        "source_refs": [{"doc_id": "doc-redis", "chunk_id": "doc-redis:c00001"}],
        "source_ref_resolvable": True,
        "permission_scope_issue": False,
        "followup_decision": "queue_for_review",
    }
    errors = validate_feedback_record(sample)
    return _check(
        "feedback_schema",
        not errors,
        {
            "required_fields": list(REQUIRED_FEEDBACK_FIELDS),
            "validation_errors": errors,
        },
    )


def _check_config_defaults() -> dict[str, Any]:
    expected = {
        "rag_default_retrieval_mode": "dense_only",
        "rag_query_rewrite_mode": "off",
        "rerank_enabled": False,
        "rag_top_k": 3,
    }
    return _check("config_defaults", _config_defaults() == expected, _config_defaults())


def _config_defaults() -> dict[str, Any]:
    return {
        "rag_default_retrieval_mode": str(config.rag_default_retrieval_mode),
        "rag_query_rewrite_mode": str(config.rag_query_rewrite_mode),
        "rerank_enabled": bool(config.rerank_enabled),
        "rag_top_k": int(config.rag_top_k),
    }


def _check(name: str, passed: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def _seed_documents(metadata_store: KnowledgeMetadataStore, root: Path) -> None:
    visible = _document("doc-visible", "process_digital_dept", "visible.md", root)
    hidden = _document("doc-hidden", "process_digital_dept", "hidden.md", root)
    metadata_store.upsert_document(visible)
    metadata_store.upsert_document(hidden)
    metadata_store.replace_chunks(
        visible.doc_id,
        [
            _chunk(
                kb_id=visible.kb_id,
                doc_id=visible.doc_id,
                chunk_id="doc-visible:c00001",
                source_file=visible.file_name,
                heading_path=["Visible SOP"],
                content="authorized restart procedure",
            )
        ],
    )
    metadata_store.replace_chunks(
        hidden.doc_id,
        [
            _chunk(
                kb_id=hidden.kb_id,
                doc_id=hidden.doc_id,
                chunk_id="doc-hidden:c00001",
                source_file=hidden.file_name,
                heading_path=["Hidden Root Cause"],
                content="hidden remediation password rotation",
            )
        ],
    )


def _document(doc_id: str, kb_id: str, filename: str, root: Path) -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        kb_id=kb_id,
        file_name=filename,
        file_ext=filename.rsplit(".", 1)[-1],
        original_path=(root / filename).as_posix(),
        artifact_dir=(root / doc_id / "artifacts").as_posix(),
        parser_engine=ParserEngine.PLAIN_TEXT,
        status=DocumentStatus.INDEXED,
    )


def _chunk(
    *,
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    source_file: str,
    heading_path: list[str],
    content: str,
) -> ChunkRecord:
    source_ref = SourceRef(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=source_file,
        heading_path=heading_path,
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        kb_id=kb_id,
        content=content,
        chunk_index=0,
        start_index=0,
        end_index=len(content),
        heading_path=heading_path,
        source_ref=source_ref,
    )


def _raw_hit(
    *,
    kb_id: str,
    doc_id: str,
    chunk_id: str,
    source_file: str,
    heading_path: list[str],
    content: str,
) -> RawSearchResult:
    source_ref = SourceRef(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=source_file,
        heading_path=heading_path,
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RawSearchResult(
        id=chunk_id,
        content=content,
        score=0.1,
        metadata={
            "kb_id": kb_id,
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "_file_name": source_file,
            "heading_path": heading_path,
            "parser_engine": "plain_text",
            "source_ref": source_ref.model_dump(mode="json"),
        },
    )


def _controlled_answer(context_text: str) -> str:
    if "authorized restart procedure" in context_text:
        return "根据 visible.md，当前可回答的处理步骤是 authorized restart procedure。"
    return "未找到可回答的授权上下文。"


def _resolve_source_ref(
    metadata_store: KnowledgeMetadataStore,
    source_ref: SourceRef | None,
) -> dict[str, Any]:
    if source_ref is None:
        return {"resolvable": False, "reason": "missing_source_ref"}
    for chunk in metadata_store.list_chunks_by_doc_id(source_ref.doc_id):
        if chunk.chunk_id == source_ref.chunk_id:
            return {
                "resolvable": True,
                "kb_id": source_ref.kb_id,
                "doc_id": source_ref.doc_id,
                "chunk_id": source_ref.chunk_id,
                "source_file": source_ref.source_file,
                "content_preview": chunk.content[:80],
            }
    return {
        "resolvable": False,
        "kb_id": source_ref.kb_id,
        "doc_id": source_ref.doc_id,
        "chunk_id": source_ref.chunk_id,
        "reason": "chunk_not_found",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="evals/knowledge_base/reports/beta_readiness_smoke_20260612.json",
        help="Path for the JSON smoke report.",
    )
    args = parser.parse_args()
    report = run_smoke(output_path=args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if report["summary"]["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
