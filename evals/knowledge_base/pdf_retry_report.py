"""Controlled retry report for failed PDF document processing.

Default mode is dry-run: it inspects the real document record and reports
whether the document is eligible for a controlled retry. Use ``--apply`` to
run the existing DocumentProcessingWorkflow path.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_validator_service import ArtifactValidatorService

RETRYABLE_STATUSES = {DocumentStatus.INDEX_FAILED, DocumentStatus.PARSE_FAILED}


def build_pdf_retry_report(
    doc_id: str,
    *,
    metadata_store=None,
    workflow=None,
    apply: bool = False,
) -> dict[str, Any]:
    metadata_store = metadata_store or _default_metadata_store()
    document = metadata_store.get_document(doc_id)
    generated_at = datetime.now(timezone.utc).isoformat()
    if document is None:
        return _blocked_report(generated_at, doc_id, "document_missing")

    blocker = _retry_blocker(document)
    if blocker:
        return _blocked_report(generated_at, doc_id, blocker, document=document)

    if not apply:
        return {
            "generated_at": generated_at,
            "doc_id": doc_id,
            "status": "dry_run",
            "would_retry": True,
            "action": "run_process_deferred_document",
            "document": _document_payload(document),
            "artifact_validation": _artifact_validation_payload(document),
        }

    workflow = workflow or _default_workflow()
    try:
        after = workflow.process_deferred_document(doc_id)
    except Exception as exc:
        return {
            "generated_at": generated_at,
            "doc_id": doc_id,
            "status": "apply_failed",
            "would_retry": True,
            "action": "run_process_deferred_document",
            "document": _document_payload(document),
            "artifact_validation": _artifact_validation_payload(document),
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    return {
        "generated_at": generated_at,
        "doc_id": doc_id,
        "status": "applied",
        "would_retry": True,
        "action": "run_process_deferred_document",
        "document": _document_payload(document, after=after),
        "artifact_validation": _artifact_validation_payload(after),
    }


def write_pdf_retry_report(
    doc_id: str,
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    apply: bool = False,
    metadata_store=None,
    workflow=None,
) -> dict[str, Any]:
    report = build_pdf_retry_report(
        doc_id,
        metadata_store=metadata_store,
        workflow=workflow,
        apply=apply,
    )
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    document = report.get("document") or {}
    lines = [
        "# PDF Retry Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Doc ID: `{report['doc_id']}`",
        f"- Status: `{report['status']}`",
        f"- Would retry: `{report.get('would_retry', False)}`",
    ]
    if report.get("reason"):
        lines.append(f"- Reason: `{report['reason']}`")
    if document:
        lines.extend(
            [
                f"- KB: `{document.get('kb_id', '')}`",
                f"- File: `{document.get('file_name', '')}`",
                f"- Status before: `{document.get('status_before', '')}`",
                f"- Status after: `{document.get('status_after', '')}`",
                f"- Parser engine: `{document.get('parser_engine', '')}`",
                f"- Original exists: `{document.get('original_exists', False)}`",
            ]
        )
    artifact_validation = report.get("artifact_validation") or {}
    if artifact_validation:
        lines.extend(
            [
                f"- Artifact validation: `{artifact_validation.get('status', '')}`",
                f"- Artifact issue counts: `{artifact_validation.get('issue_counts', {})}`",
            ]
        )
    if report.get("error_message"):
        lines.append(f"- Error: `{report['error_type']}: {report['error_message']}`")
    lines.append("")
    return "\n".join(lines)


def _retry_blocker(document: DocumentRecord) -> str:
    if document.file_ext.lower() != "pdf":
        return "unsupported_file_ext"
    if document.parser_engine != ParserEngine.MINERU:
        return "unsupported_parser_engine"
    if document.status not in RETRYABLE_STATUSES:
        return "status_not_retryable"
    original_path = Path(document.original_path)
    if not original_path.exists() or not original_path.is_file():
        return "original_missing"
    return ""


def _blocked_report(
    generated_at: str,
    doc_id: str,
    reason: str,
    *,
    document: DocumentRecord | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "doc_id": doc_id,
        "status": "blocked",
        "reason": reason,
        "would_retry": False,
        "action": "none",
        "document": _document_payload(document) if document else {},
    }


def _document_payload(document: DocumentRecord, *, after: DocumentRecord | None = None) -> dict[str, Any]:
    original_path = Path(document.original_path)
    artifact_dir = Path(document.artifact_dir)
    return {
        "kb_id": document.kb_id,
        "doc_id": document.doc_id,
        "file_name": document.file_name,
        "file_ext": document.file_ext,
        "parser_engine": document.parser_engine.value,
        "status_before": document.status.value,
        "status_after": after.status.value if after else "",
        "status_source_before": document.status_source,
        "status_source_after": after.status_source if after else "",
        "original_path": original_path.as_posix(),
        "original_exists": original_path.exists() and original_path.is_file(),
        "artifact_dir": artifact_dir.as_posix(),
        "artifact_dir_exists": artifact_dir.exists() and artifact_dir.is_dir(),
    }


def _artifact_validation_payload(document: DocumentRecord) -> dict[str, Any]:
    try:
        report = ArtifactValidatorService().validate_artifact_dir(document.artifact_dir)
    except Exception as exc:
        return {
            "status": "validator_failed",
            "issue_counts": {},
            "error_type": type(exc).__name__,
            "error_message": str(exc),
        }
    return {
        "status": report.status,
        "parser_version": report.parser_version,
        "postprocess_version": report.postprocess_version,
        "issue_counts": report.issue_counts,
        "issues": [issue.__dict__ for issue in report.issues],
    }


def _default_metadata_store():
    from app.services.knowledge_metadata_store import knowledge_metadata_store

    return knowledge_metadata_store


def _default_workflow():
    from app.services.document_processing_workflow import document_processing_workflow

    return document_processing_workflow


def main() -> int:
    parser = argparse.ArgumentParser(description="Build controlled PDF retry report for a document.")
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--apply", action="store_true", help="Run the existing workflow instead of dry-run.")
    args = parser.parse_args()
    write_pdf_retry_report(
        args.doc_id,
        output_json=args.output_json,
        output_md=args.output_md or None,
        apply=args.apply,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
