"""PDF baseline report helpers for parser/profile gate checks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app.services.mineru_parser_adapter as mineru_adapter_module
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_validator_service import ArtifactValidatorService
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.mineru_parser_adapter import MinerUParserAdapter
from app.services.pdf_profile_service import pdf_profile_service


def build_pdf_baseline_report(
    samples: list[dict[str, Any]],
    *,
    run_mineru: bool = False,
) -> dict[str, Any]:
    rows = [_evaluate_sample(sample, run_mineru=run_mineru) for sample in samples]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(rows),
            "profile_status_counts": dict(Counter(row["profile"].get("profile_status") for row in rows)),
            "mineru_status_counts": dict(Counter(row["mineru"].get("status") for row in rows)),
            "validator_status_counts": dict(Counter(row["validator"].get("status") for row in rows)),
        },
        "samples": rows,
    }


def write_pdf_baseline_report(
    samples: list[dict[str, Any]],
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    run_mineru: bool = False,
) -> dict[str, Any]:
    report = build_pdf_baseline_report(samples, run_mineru=run_mineru)
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDF Baseline Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Summary: {report['summary']}",
        "",
        "| sample_id | profile_status | risk_flags | mineru_status | validator_status |",
        "|---|---|---|---|---|",
    ]
    for row in report["samples"]:
        lines.append(
            "| {sample_id} | {profile_status} | {risk_flags} | {mineru_status} | {validator_status} |".format(
                sample_id=row["sample_id"],
                profile_status=row["profile"].get("profile_status", ""),
                risk_flags=row["profile"].get("risk_flags", []),
                mineru_status=row["mineru"].get("status", ""),
                validator_status=row["validator"].get("status", ""),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _evaluate_sample(sample: dict[str, Any], *, run_mineru: bool) -> dict[str, Any]:
    pdf_path = Path(sample["pdf_path"])
    if not pdf_path.exists() or not pdf_path.is_file():
        return _invalid_sample_row(sample, pdf_path, "sample_missing")
    try:
        profile = pdf_profile_service.profile_pdf(pdf_path, file_size=pdf_path.stat().st_size)
    except Exception as exc:
        return _invalid_sample_row(
            sample,
            pdf_path,
            "profile_failed",
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
    mineru = {"status": "not_run"}
    validator = {"status": "not_run", "issue_counts": {}}
    if run_mineru:
        mineru, validator = _run_temp_mineru(sample, pdf_path)
    return {
        "sample_id": sample.get("sample_id") or pdf_path.stem,
        "doc_id": sample.get("doc_id", ""),
        "kb_id": sample.get("kb_id", ""),
        "pdf_path": pdf_path.as_posix(),
        "profile": profile,
        "mineru": mineru,
        "validator": validator,
    }


def _invalid_sample_row(
    sample: dict[str, Any],
    pdf_path: Path,
    reason: str,
    *,
    error_type: str = "",
    error_message: str = "",
) -> dict[str, Any]:
    return {
        "sample_id": sample.get("sample_id") or pdf_path.stem,
        "doc_id": sample.get("doc_id", ""),
        "kb_id": sample.get("kb_id", ""),
        "pdf_path": pdf_path.as_posix(),
        "profile": {
            "profile_status": "sample_invalid",
            "reason": reason,
            "error_type": error_type,
            "error_message": error_message,
            "risk_flags": [],
        },
        "mineru": {"status": "sample_invalid", "reason": reason},
        "validator": {"status": "not_run", "issue_counts": {}},
    }


def _run_temp_mineru(sample: dict[str, Any], pdf_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="pdf-baseline-mineru-") as tmpdir:
        started = time.perf_counter()
        root = Path(tmpdir)
        local_pdf = root / "original" / pdf_path.name
        local_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf_path, local_pdf)
        artifact_dir = root / "artifacts"
        record = DocumentRecord(
            doc_id=sample.get("doc_id") or f"pdf_baseline_{pdf_path.stem}",
            kb_id=sample.get("kb_id") or "pdf_baseline",
            file_name=pdf_path.name,
            file_ext="pdf",
            original_path=local_pdf.as_posix(),
            artifact_dir=artifact_dir.as_posix(),
            parser_engine=ParserEngine.MINERU,
            status=DocumentStatus.PARSE_PENDING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        store = KnowledgeMetadataStore(root / "metadata.json")
        adapter = MinerUParserAdapter()
        adapter.method = "txt"
        adapter.enable_formula = False
        adapter.enable_table = False
        cli_status = _mineru_cli_status(adapter.cli_path)
        if cli_status["status"] != "ok":
            return (
                {
                    **cli_status,
                    "elapsed_ms": _elapsed_ms(started),
                    "parser_config": _parser_config(adapter),
                },
                {"status": "not_run", "issue_counts": {}},
            )
        try:
            with _patched_mineru_store(store):
                store.upsert_document(record)
                parsed = adapter.parse_document(record)
            validation_report = ArtifactValidatorService().validate_artifact_dir(artifact_dir)
            raw_output_dir = parsed.metadata.get("raw_output_dir", "")
            return (
                {
                    "status": parsed.status.value,
                    "elapsed_ms": _elapsed_ms(started),
                    "parser_version": parsed.parser_version,
                    "parser_config": _parser_config(adapter),
                    "raw_output_relative_dir": _relative_to_root(raw_output_dir, root),
                    "artifact_files": sorted(p.name for p in artifact_dir.iterdir() if p.is_file()),
                },
                {
                    "status": validation_report.status,
                    "parser_version": validation_report.parser_version,
                    "postprocess_version": validation_report.postprocess_version,
                    "issue_counts": validation_report.issue_counts,
                    "issues": [issue.__dict__ for issue in validation_report.issues],
                },
            )
        except Exception as exc:
            return (
                {
                    "status": _classify_mineru_failure(exc),
                    "elapsed_ms": _elapsed_ms(started),
                    "parser_config": _parser_config(adapter),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
                {"status": "not_run", "issue_counts": {}},
            )


def _mineru_cli_status(cli_path: Path) -> dict[str, Any]:
    if not cli_path.exists():
        return {
            "status": "mineru_unavailable",
            "reason": "cli_missing",
            "cli_path": cli_path.as_posix(),
        }
    if not cli_path.is_file() or not os.access(cli_path, os.X_OK):
        return {
            "status": "mineru_unavailable",
            "reason": "cli_not_executable",
            "cli_path": cli_path.as_posix(),
        }
    return {"status": "ok", "cli_path": cli_path.as_posix()}


def _classify_mineru_failure(exc: Exception) -> str:
    if isinstance(exc, (FileNotFoundError, PermissionError)):
        return "mineru_unavailable"
    return "failed"


def _parser_config(adapter: MinerUParserAdapter) -> dict[str, Any]:
    return {
        "method": adapter.method,
        "backend": adapter.backend,
        "language": adapter.language,
        "enable_formula": adapter.enable_formula,
        "enable_table": adapter.enable_table,
    }


def _relative_to_root(path: str, root: Path) -> str:
    if not path:
        return ""
    raw_path = Path(path)
    try:
        return raw_path.relative_to(root).as_posix()
    except ValueError:
        return raw_path.name


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class _patched_mineru_store:
    def __init__(self, store: KnowledgeMetadataStore):
        self.store = store
        self.original = None

    def __enter__(self):
        self.original = mineru_adapter_module.knowledge_metadata_store
        mineru_adapter_module.knowledge_metadata_store = self.store

    def __exit__(self, exc_type, exc, tb):
        mineru_adapter_module.knowledge_metadata_store = self.original


def _load_samples(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    return list(payload.get("samples") or [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PDF baseline report.")
    parser.add_argument("--samples", required=True, help="JSON file with sample list or {samples: [...]} payload.")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    parser.add_argument("--run-mineru", action="store_true")
    args = parser.parse_args()
    write_pdf_baseline_report(
        _load_samples(args.samples),
        output_json=args.output_json,
        output_md=args.output_md or None,
        run_mineru=args.run_mineru,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
