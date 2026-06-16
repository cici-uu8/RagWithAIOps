"""Build reviewed manifests and import approved original-file assets."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.document_ingestion_service import DocumentIngestionService

SUPPORTED_EXTENSIONS = {"md", "txt", "pdf", "docx", "xlsx"}
MANIFEST_FIELDS = [
    "asset_id",
    "relative_path",
    "file_name",
    "file_ext",
    "kb_id",
    "review_status",
    "import_enabled",
    "metadata_only",
    "file_size",
    "sha1",
    "notes",
]
REVIEW_FIELDS = [
    "asset_id",
    "relative_path",
    "kb_id",
    "review_status",
    "import_enabled",
    "metadata_only",
    "notes",
]


@dataclass(frozen=True)
class OriginalFileAsset:
    asset_id: str
    relative_path: str
    file_name: str
    file_ext: str
    kb_id: str
    review_status: str = "pending"
    import_enabled: bool = False
    metadata_only: bool = False
    file_size: int = 0
    sha1: str = ""
    notes: str = ""

    def to_manifest_row(self) -> dict[str, str]:
        payload = asdict(self)
        payload["import_enabled"] = _bool_text(self.import_enabled)
        payload["metadata_only"] = _bool_text(self.metadata_only)
        payload["file_size"] = str(self.file_size)
        return {field: str(payload.get(field, "")) for field in MANIFEST_FIELDS}

    def to_review_row(self) -> dict[str, str]:
        payload = asdict(self)
        payload["import_enabled"] = _bool_text(self.import_enabled)
        payload["metadata_only"] = _bool_text(self.metadata_only)
        return {field: str(payload.get(field, "")) for field in REVIEW_FIELDS}


def build_manifest(
    source_root: str | Path,
    *,
    review_path: str | Path | None = None,
) -> list[OriginalFileAsset]:
    root = Path(source_root).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"source root not found: {root}")

    review_rows = _load_review_rows(Path(review_path).resolve()) if review_path else {}
    loose_review_rows = [row for row in review_rows.values() if not row.get("relative_path")]

    assets: list[OriginalFileAsset] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _is_hidden_path(path, root):
            continue
        file_ext = path.suffix.lower().lstrip(".")
        if file_ext not in SUPPORTED_EXTENSIONS:
            continue

        relative_path = path.relative_to(root).as_posix()
        asset_id = _asset_id(relative_path)
        review = review_rows.get(asset_id) or review_rows.get(relative_path) or {}
        if not review and len(loose_review_rows) == 1:
            # Compatibility for early hand-written review files that only had asset_id.
            review = loose_review_rows[0]

        assets.append(
            OriginalFileAsset(
                asset_id=asset_id,
                relative_path=relative_path,
                file_name=path.name,
                file_ext=file_ext,
                kb_id=str(review.get("kb_id") or _infer_kb_id(relative_path)),
                review_status=str(review.get("review_status") or "pending"),
                import_enabled=_parse_bool(review.get("import_enabled")),
                metadata_only=_parse_bool(review.get("metadata_only")),
                file_size=path.stat().st_size,
                sha1=_file_sha1(path),
                notes=str(review.get("notes") or ""),
            )
        )
    return assets


def write_manifest_files(rows: list[OriginalFileAsset], output_dir: str | Path) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_manifest_tsv(rows, output / "original_files_manifest.tsv")
    write_review_tsv(rows, output / "original_files_manifest_review.tsv")
    write_manifest_json(rows, output / "original_files_manifest.json")


def write_manifest_tsv(rows: list[OriginalFileAsset], path: str | Path) -> None:
    _write_tsv([row.to_manifest_row() for row in rows], Path(path), MANIFEST_FIELDS)


def write_review_tsv(rows: list[OriginalFileAsset], path: str | Path) -> None:
    _write_tsv([row.to_review_row() for row in rows], Path(path), REVIEW_FIELDS)


def write_manifest_json(rows: list[OriginalFileAsset], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "original_files_manifest_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "total": len(rows),
        "assets": [asdict(row) for row in rows],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_reviewed_files(
    *,
    source_root: str | Path,
    review_path: str | Path,
    apply: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    root = Path(source_root).resolve()
    rows = _read_review_assets(Path(review_path).resolve())
    eligible = [
        row
        for row in rows
        if row.review_status == "approved"
        and row.import_enabled
        and not row.metadata_only
        and row.file_ext in SUPPORTED_EXTENSIONS
    ]
    selected = eligible[:limit] if limit is not None and limit >= 0 else eligible
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry_run",
        "source_root": root.as_posix(),
        "review_path": Path(review_path).resolve().as_posix(),
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "total_review_rows": len(rows),
            "eligible": len(eligible),
            "selected": len(selected),
            "imported": 0,
            "failed": 0,
            "skipped_pending_review": sum(1 for row in rows if row.review_status == "pending"),
            "skipped_disabled": sum(1 for row in rows if not row.import_enabled),
            "skipped_metadata_only": sum(1 for row in rows if row.metadata_only),
        },
        "imported": [],
        "failed": [],
        "selected_assets": [row.to_manifest_row() for row in selected],
    }
    if not apply:
        return report

    ingestion_service = DocumentIngestionService()
    for row in selected:
        path = root / row.relative_path
        try:
            document = ingestion_service.ingest_upload(
                filename=path.name,
                content=path.read_bytes(),
                kb_id=row.kb_id,
            )
            status = getattr(document.status, "value", document.status)
            evidence = dict(getattr(document, "status_evidence", {}) or {})
            job_id = evidence.get("processing_job_id") or evidence.get("job_id") or ""
            report["imported"].append(
                {
                    "asset_id": row.asset_id,
                    "relative_path": row.relative_path,
                    "kb_id": getattr(document, "kb_id", row.kb_id),
                    "doc_id": getattr(document, "doc_id", ""),
                    "status": str(status),
                    "source_ref": {
                        "kb_id": getattr(document, "kb_id", row.kb_id),
                        "doc_id": getattr(document, "doc_id", ""),
                        "source_file": row.file_name,
                        "source_uri": path.as_posix(),
                    },
                    "job_id": str(job_id),
                }
            )
        except Exception as exc:
            report["failed"].append(
                {
                    "asset_id": row.asset_id,
                    "relative_path": row.relative_path,
                    "kb_id": row.kb_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    report["summary"]["imported"] = len(report["imported"])
    report["summary"]["failed"] = len(report["failed"])
    return report


def freeze_import_state(
    *,
    metadata_store=None,
    kb_ids: list[str] | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    if metadata_store is None:
        from app.services.knowledge_metadata_store import knowledge_metadata_store

        metadata_store = knowledge_metadata_store
    allowed_kb_ids = set(kb_ids or ["process_digital_dept", "craft_dept"])
    documents = [
        document
        for document in metadata_store.list_documents()
        if not allowed_kb_ids or document.kb_id in allowed_kb_ids
    ]
    rows: list[dict[str, Any]] = []
    for document in sorted(documents, key=lambda item: (item.kb_id, item.file_name, item.doc_id)):
        status = getattr(document.status, "value", document.status)
        evidence = dict(document.status_evidence or {})
        job_id = evidence.get("processing_job_id") or evidence.get("job_id") or ""
        rows.append(
            {
                "doc_id": document.doc_id,
                "kb_id": document.kb_id,
                "file_name": document.file_name,
                "file_ext": document.file_ext,
                "status": str(status),
                "source_ref": {
                    "kb_id": document.kb_id,
                    "doc_id": document.doc_id,
                    "source_file": document.file_name,
                    "source_uri": document.original_path,
                },
                "job_id": str(job_id),
                "status_evidence": evidence,
                "parser_engine": getattr(document.parser_engine, "value", document.parser_engine),
                "original_path": document.original_path,
            }
        )
    state = {
        "schema_version": "current_import_state_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "kb_ids": sorted(allowed_kb_ids),
        "summary": {
            "total_documents": len(rows),
            "status_counts": dict(Counter(row["status"] for row in rows)),
            "pdf_documents": sum(1 for row in rows if row["file_ext"] == "pdf"),
            "pdf_with_job_id": sum(1 for row in rows if row["file_ext"] == "pdf" and row["job_id"]),
        },
        "documents": rows,
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def _read_review_assets(path: Path) -> list[OriginalFileAsset]:
    if not path.exists():
        raise FileNotFoundError(f"review file not found: {path}")
    rows: list[OriginalFileAsset] = []
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")
        for raw in reader:
            relative_path = str(raw.get("relative_path") or "").strip()
            file_name = Path(relative_path).name
            file_ext = Path(relative_path).suffix.lower().lstrip(".")
            rows.append(
                OriginalFileAsset(
                    asset_id=str(raw.get("asset_id") or _asset_id(relative_path)),
                    relative_path=relative_path,
                    file_name=file_name,
                    file_ext=file_ext,
                    kb_id=str(raw.get("kb_id") or _infer_kb_id(relative_path)),
                    review_status=str(raw.get("review_status") or "pending"),
                    import_enabled=_parse_bool(raw.get("import_enabled")),
                    metadata_only=_parse_bool(raw.get("metadata_only")),
                    notes=str(raw.get("notes") or ""),
                )
            )
    return rows


def _load_review_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file, delimiter="\t")
        for row in reader:
            normalized = {key: str(value or "") for key, value in row.items()}
            asset_id = normalized.get("asset_id", "")
            relative_path = normalized.get("relative_path", "")
            if asset_id:
                rows[asset_id] = normalized
            if relative_path:
                rows[relative_path] = normalized
    return rows


def _write_tsv(rows: list[dict[str, str]], path: Path, fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
            quoting=csv.QUOTE_ALL,
        )
        writer.writeheader()
        writer.writerows(rows)


def _is_hidden_path(path: Path, root: Path) -> bool:
    return any(part.startswith(".") for part in path.relative_to(root).parts)


def _infer_kb_id(relative_path: str) -> str:
    text = relative_path.lower()
    if any(keyword in relative_path for keyword in ("工艺", "设备", "土壤", "监测", "环保")):
        return "craft_dept"
    if any(keyword in text for keyword in ("process", "digital", "oncall", "sre")):
        return "process_digital_dept"
    if any(keyword in relative_path for keyword in ("流程", "数字化", "中车长客", "长客")):
        return "process_digital_dept"
    return "process_digital_dept"


def _asset_id(relative_path: str) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"orig_{digest}"


def _file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/import reviewed original-file assets.")
    parser.add_argument("--source-root", default="原始文件")
    parser.add_argument("--output-dir", default="data/knowledge_ingestion")
    parser.add_argument("--review-path", default="")
    parser.add_argument("--build-manifest", action="store_true")
    parser.add_argument("--snapshot-state", action="store_true")
    parser.add_argument(
        "--snapshot-output",
        default="data/knowledge_ingestion/current_import_state.json",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    review_path = Path(args.review_path) if args.review_path else output_dir / "original_files_manifest_review.tsv"
    rows = build_manifest(args.source_root, review_path=review_path if review_path.exists() else None)
    if args.build_manifest or not review_path.exists():
        write_manifest_files(rows, output_dir)

    report = import_reviewed_files(
        source_root=args.source_root,
        review_path=review_path,
        apply=args.apply,
        limit=args.limit,
    )
    if args.snapshot_state:
        report["current_import_state"] = freeze_import_state(output_path=args.snapshot_output)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
