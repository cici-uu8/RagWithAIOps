import json

from evals.knowledge_base.beta_readiness_smoke import (
    FEEDBACK_ANSWER_ISSUES,
    REQUIRED_FEEDBACK_FIELDS,
    run_smoke,
    validate_feedback_record,
)


def test_beta_readiness_smoke_covers_minimum_production_loop(tmp_path):
    report_path = tmp_path / "beta_readiness_smoke.json"

    report = run_smoke(output_path=report_path)

    assert report["summary"]["status"] == "passed"
    assert report["baseline"] == {
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
    assert report["config_defaults"] == {
        "rag_default_retrieval_mode": "dense_only",
        "rag_query_rewrite_mode": "off",
        "rerank_enabled": False,
        "rag_top_k": 3,
    }

    checks = {check["name"]: check for check in report["checks"]}
    assert set(checks) == {
        "auth_login",
        "rag_qa_controlled",
        "source_ref_lookup",
        "permission_filtering",
        "audit_logging",
        "feedback_schema",
        "config_defaults",
    }
    assert all(check["status"] == "passed" for check in checks.values())

    assert checks["auth_login"]["evidence"]["user_id"] == "user_admin"
    assert checks["rag_qa_controlled"]["evidence"]["retrieved_doc_ids"] == ["doc-visible"]
    assert "authorized restart procedure" in checks["rag_qa_controlled"]["evidence"]["answer"]
    assert checks["source_ref_lookup"]["evidence"]["resolvable"] is True
    assert checks["source_ref_lookup"]["evidence"]["chunk_id"] == "doc-visible:c00001"
    assert checks["permission_filtering"]["evidence"]["blocked_doc_ids"] == ["doc-hidden"]
    assert "permission_checked" in checks["audit_logging"]["evidence"]["event_types"]
    assert "rag_retrieval" in checks["audit_logging"]["evidence"]["event_types"]
    assert checks["feedback_schema"]["evidence"]["required_fields"] == list(
        REQUIRED_FEEDBACK_FIELDS
    )

    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["summary"] == report["summary"]


def test_feedback_record_validation_requires_real_feedback_fields():
    valid_record = {
        "timestamp": "2026-06-12T10:00:00+08:00",
        "user_id": "user_demo_dept1",
        "session_id": "session-001",
        "query": "Redis 内存打满怎么办",
        "retrieved_docs": [{"doc_id": "doc-redis", "source_file": "redis.md"}],
        "answer": "先确认 used_memory 与 maxmemory。",
        "answer_issue": "answer_incomplete",
        "missing_facts": ["未说明 evicted_keys"],
        "source_refs": [{"doc_id": "doc-redis", "chunk_id": "doc-redis:c00001"}],
        "source_ref_resolvable": True,
        "permission_scope_issue": False,
        "followup_decision": "queue_for_review",
    }

    assert validate_feedback_record(valid_record) == []
    assert "none" in FEEDBACK_ANSWER_ISSUES

    no_issue_record = dict(valid_record)
    no_issue_record["answer_issue"] = "none"
    no_issue_record["missing_facts"] = []
    no_issue_record["followup_decision"] = "no_action"

    assert validate_feedback_record(no_issue_record) == []

    invalid_record = dict(valid_record)
    invalid_record.pop("source_ref_resolvable")
    invalid_record["query"] = ""
    invalid_record["answer_issue"] = "missing_fact"

    errors = validate_feedback_record(invalid_record)

    assert "missing_required_field:source_ref_resolvable" in errors
    assert "empty_required_field:query" in errors
    assert "invalid_enum:answer_issue:missing_fact" in errors
