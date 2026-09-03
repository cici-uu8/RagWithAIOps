"""Checklist 4 mixed Markdown/PDF RAG eval readiness report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_IMPORT_STATE = "data/knowledge_ingestion/current_import_state.json"
DEFAULT_MIXED_EVALSET: str | None = None

DEFAULT_TARGETS = {
    "min_indexed_documents": 10,
    "min_indexed_kb_count": 2,
    "min_indexed_pdf_documents": 5,
    "min_indexed_markdown_documents": 5,
    "min_total_samples": 50,
    "min_markdown_samples": 20,
    "min_pdf_samples": 15,
    "min_expression_gap_samples": 10,
    "min_permission_scope_samples": 5,
}


def build_mixed_rag_eval_readiness_report(
    *,
    import_state_path: str | Path = DEFAULT_IMPORT_STATE,
    evalset_path: str | Path | None = DEFAULT_MIXED_EVALSET,
    targets: dict[str, int] | None = None,
) -> dict[str, Any]:
    target_values = {**DEFAULT_TARGETS, **(targets or {})}
    import_state = _load_json(Path(import_state_path))
    indexed_docs = [
        doc for doc in import_state.get("documents", []) if str(doc.get("status")) == "indexed"
    ]
    doc_index = {str(doc.get("doc_id")): doc for doc in indexed_docs}
    corpus = _summarize_corpus(indexed_docs, target_values)
    evalset = _summarize_evalset(Path(evalset_path) if evalset_path else None, doc_index, target_values)
    gaps = _collect_gaps(corpus, evalset)
    status = _status_from_gaps(gaps)
    return {
        "schema_version": "checklist4_mixed_rag_eval_readiness_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "ready_for_mixed_baseline": status == "ready_for_mixed_baseline",
        "targets": target_values,
        "corpus": corpus,
        "evalset": evalset,
        "gaps": gaps,
        "next_actions": _next_actions(gaps),
    }


def write_mixed_rag_eval_readiness_report(
    *,
    import_state_path: str | Path = DEFAULT_IMPORT_STATE,
    evalset_path: str | Path | None = DEFAULT_MIXED_EVALSET,
    targets: dict[str, int] | None = None,
    output_json: str | Path,
    output_md: str | Path | None = None,
) -> dict[str, Any]:
    report = build_mixed_rag_eval_readiness_report(
        import_state_path=import_state_path,
        evalset_path=evalset_path,
        targets=targets,
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
    corpus = report["corpus"]
    evalset = report["evalset"]
    lines = [
        "# Checklist 4 Mixed RAG Eval Readiness Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Ready for mixed baseline: `{str(report['ready_for_mixed_baseline']).lower()}`",
        f"- Gaps: {report['gaps'] or []}",
        "",
        "## Corpus",
        "",
        f"- Indexed documents: {corpus['indexed_document_count']}",
        f"- Indexed KB count: {corpus['indexed_kb_count']}",
        f"- Indexed Markdown documents: {corpus['indexed_markdown_count']}",
        f"- Indexed PDF documents: {corpus['indexed_pdf_count']}",
        f"- Source refs resolvable: `{str(corpus['source_ref_resolvable']).lower()}`",
        f"- Artifact missing count: {corpus['artifact_missing_count']}",
        "",
        "## Evalset",
        "",
        f"- Path: `{evalset['path']}`",
        f"- Status: `{evalset['status']}`",
        f"- Total samples: {evalset['sample_count']}",
        f"- Markdown samples: {evalset['markdown_sample_count']}",
        f"- PDF samples: {evalset['pdf_sample_count']}",
        f"- Expression-gap samples: {evalset['expression_gap_sample_count']}",
        f"- Permission/scope samples: {evalset['permission_scope_sample_count']}",
        "",
        "## Next Actions",
        "",
    ]
    for action in report["next_actions"]:
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def _summarize_corpus(indexed_docs: list[dict[str, Any]], targets: dict[str, int]) -> dict[str, Any]:
    ext_counts = Counter(str(doc.get("file_ext") or "").lower() for doc in indexed_docs)
    kb_ids = sorted({str(doc.get("kb_id")) for doc in indexed_docs if doc.get("kb_id")})
    source_ref_missing = _source_ref_missing(indexed_docs)
    artifact_missing = _artifact_missing(indexed_docs)
    gates = {
        "indexed_documents": len(indexed_docs) >= targets["min_indexed_documents"],
        "indexed_kb_count": len(kb_ids) >= targets["min_indexed_kb_count"],
        "indexed_pdf_documents": ext_counts["pdf"] >= targets["min_indexed_pdf_documents"],
        "indexed_markdown_documents": ext_counts["md"] >= targets["min_indexed_markdown_documents"],
        "source_ref_resolvable": not source_ref_missing,
        "artifact_missing_count": not artifact_missing,
    }
    return {
        "indexed_document_count": len(indexed_docs),
        "indexed_kb_count": len(kb_ids),
        "indexed_kb_ids": kb_ids,
        "file_ext_counts": dict(sorted(ext_counts.items())),
        "indexed_markdown_count": ext_counts["md"],
        "indexed_pdf_count": ext_counts["pdf"],
        "source_ref_resolvable": not source_ref_missing,
        "source_ref_missing": source_ref_missing,
        "artifact_missing_count": len(artifact_missing),
        "artifact_missing": artifact_missing,
        "gates": gates,
    }


def _summarize_evalset(
    evalset_path: Path | None,
    doc_index: dict[str, dict[str, Any]],
    targets: dict[str, int],
) -> dict[str, Any]:
    if evalset_path is None:
        return _missing_evalset("", "not_configured")
    if not evalset_path.exists():
        return _missing_evalset(evalset_path.as_posix(), "missing")

    samples = _load_samples(evalset_path)
    sample_exts = Counter()
    failure_classes = Counter()
    missing_expected_docs: list[dict[str, Any]] = []
    for sample in samples:
        failure_class = str(sample.get("failure_class") or sample.get("eval_type") or "")
        if failure_class:
            failure_classes[failure_class] += 1
        expected_doc_ids = _as_list(sample.get("expected_doc_ids") or sample.get("doc_id"))
        expected_exts = set()
        for doc_id in expected_doc_ids:
            document = doc_index.get(str(doc_id))
            if document is None:
                missing_expected_docs.append(
                    {
                        "sample_id": str(sample.get("sample_id") or ""),
                        "doc_id": str(doc_id),
                    }
                )
                continue
            expected_exts.add(str(document.get("file_ext") or "").lower())
        for file_ext in expected_exts or {"unknown"}:
            sample_exts[file_ext] += 1

    expression_gap_count = sum(
        count for key, count in failure_classes.items() if "expression" in key or "rewrite" in key
    )
    permission_scope_count = sum(
        count
        for key, count in failure_classes.items()
        if "permission" in key or "scope" in key or "wrong_scope" in key
    )
    gates = {
        "total_samples": len(samples) >= targets["min_total_samples"],
        "markdown_samples": sample_exts["md"] >= targets["min_markdown_samples"],
        "pdf_samples": sample_exts["pdf"] >= targets["min_pdf_samples"],
        "expression_gap_samples": expression_gap_count >= targets["min_expression_gap_samples"],
        "permission_scope_samples": permission_scope_count >= targets["min_permission_scope_samples"],
        "expected_docs_indexed": not missing_expected_docs,
    }
    return {
        "path": evalset_path.as_posix(),
        "status": "loaded",
        "sample_count": len(samples),
        "sample_file_ext_counts": dict(sorted(sample_exts.items())),
        "markdown_sample_count": sample_exts["md"],
        "pdf_sample_count": sample_exts["pdf"],
        "failure_class_counts": dict(sorted(failure_classes.items())),
        "expression_gap_sample_count": expression_gap_count,
        "permission_scope_sample_count": permission_scope_count,
        "missing_expected_docs": missing_expected_docs,
        "gates": gates,
    }


def _missing_evalset(path: str, status: str) -> dict[str, Any]:
    return {
        "path": path,
        "status": status,
        "sample_count": 0,
        "sample_file_ext_counts": {},
        "markdown_sample_count": 0,
        "pdf_sample_count": 0,
        "failure_class_counts": {},
        "expression_gap_sample_count": 0,
        "permission_scope_sample_count": 0,
        "missing_expected_docs": [],
        "gates": {
            "total_samples": False,
            "markdown_samples": False,
            "pdf_samples": False,
            "expression_gap_samples": False,
            "permission_scope_samples": False,
            "expected_docs_indexed": False,
        },
    }


def _collect_gaps(corpus: dict[str, Any], evalset: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if not corpus["gates"]["indexed_documents"]:
        gaps.append("indexed_document_count_below_target")
    if not corpus["gates"]["indexed_kb_count"]:
        gaps.append("indexed_kb_count_below_target")
    if not corpus["gates"]["indexed_pdf_documents"]:
        gaps.append("indexed_pdf_count_below_target")
    if not corpus["gates"]["indexed_markdown_documents"]:
        gaps.append("indexed_markdown_count_below_target")
    if not corpus["gates"]["source_ref_resolvable"]:
        gaps.append("source_ref_not_resolvable")
    if not corpus["gates"]["artifact_missing_count"]:
        gaps.append("pdf_artifact_missing")
    if evalset["status"] == "missing":
        gaps.append("mixed_evalset_missing")
    elif evalset["status"] == "not_configured":
        gaps.append("mixed_evalset_not_configured")
    for gate_name, passed in evalset["gates"].items():
        if not passed:
            gaps.append(f"mixed_evalset_{gate_name}_below_target")
    return gaps


def _status_from_gaps(gaps: list[str]) -> str:
    if any(gap.startswith("indexed_pdf") for gap in gaps):
        return "blocked_pdf_corpus_insufficient"
    if any(gap.startswith("indexed_") or gap in {"source_ref_not_resolvable", "pdf_artifact_missing"} for gap in gaps):
        return "blocked_corpus_insufficient"
    if any(gap.startswith("mixed_evalset") for gap in gaps):
        return "blocked_mixed_evalset_incomplete"
    return "ready_for_mixed_baseline"


def _next_actions(gaps: list[str]) -> list[str]:
    actions: list[str] = []
    if "indexed_pdf_count_below_target" in gaps:
        actions.append("Approve and index more in-scope PDFs before claiming mixed RAG coverage.")
    if "mixed_evalset_missing" in gaps or "mixed_evalset_not_configured" in gaps:
        actions.append("Create a mixed Markdown/PDF evalset draft only after corpus support exists.")
    if any(gap.startswith("mixed_evalset_") and gap.endswith("_below_target") for gap in gaps):
        actions.append("Balance mixed eval samples across Markdown, PDF, expression-gap, and permission/scope cases.")
    if "source_ref_not_resolvable" in gaps:
        actions.append("Fix source_ref paths before running baseline.")
    if "pdf_artifact_missing" in gaps:
        actions.append("Repair PDF artifacts before adding PDF samples.")
    if not actions:
        actions.append("Run dense_only mixed baseline, then use failure classes to choose hybrid/rerank/rewrite work.")
    return actions


def _source_ref_missing(indexed_docs: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for doc in indexed_docs:
        source_ref = dict(doc.get("source_ref") or {})
        source_uri = str(source_ref.get("source_uri") or doc.get("original_path") or "")
        if not source_uri or not Path(source_uri).exists():
            missing.append(
                {
                    "doc_id": str(doc.get("doc_id") or ""),
                    "file_name": str(doc.get("file_name") or ""),
                    "source_uri": source_uri,
                }
            )
    return missing


def _artifact_missing(indexed_docs: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for doc in indexed_docs:
        if str(doc.get("file_ext") or "").lower() != "pdf":
            continue
        evidence = dict(doc.get("status_evidence") or {})
        artifact_dir = str(evidence.get("artifact_dir") or doc.get("artifact_dir") or "")
        if not artifact_dir or not Path(artifact_dir).exists():
            missing.append(
                {
                    "doc_id": str(doc.get("doc_id") or ""),
                    "file_name": str(doc.get("file_name") or ""),
                    "artifact_dir": artifact_dir,
                }
            )
    return missing


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_samples(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    payload = _load_json(path)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        samples = payload.get("samples") or payload.get("cases") or []
        if isinstance(samples, list):
            return [sample for sample in samples if isinstance(sample, dict)]
    return []


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Checklist 4 mixed RAG eval readiness report.")
    parser.add_argument("--import-state", default=DEFAULT_IMPORT_STATE)
    parser.add_argument("--evalset", default=DEFAULT_MIXED_EVALSET)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    write_mixed_rag_eval_readiness_report(
        import_state_path=args.import_state,
        evalset_path=args.evalset,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
