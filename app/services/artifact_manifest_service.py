"""Artifact manifest creation and validation for parsed document outputs."""

from __future__ import annotations

import json
from pathlib import Path

from app.models import ArtifactManifest, DocumentRecord


class ArtifactManifestService:
    """Write and validate the fixed parsed-artifact contract."""

    MANIFEST_FILENAME = "artifact_manifest.json"
    SCHEMA_VERSION = "artifact_manifest_v1"
    POSTPROCESS_VERSION = "pdf_eval_mineru_postprocess_v1"
    REQUIRED_FILES = {
        "cleaned_md": "cleaned.md",
        "chunks_json": "chunks.json",
        "tables_json": "tables.json",
        "blocks_json": "blocks.json",
        "quality_report_json": "quality_report.json",
    }

    def build_manifest(self, document_record: DocumentRecord) -> ArtifactManifest:
        return ArtifactManifest(
            schema_version=self.SCHEMA_VERSION,
            kb_id=document_record.kb_id,
            doc_id=document_record.doc_id,
            source_file=document_record.original_path,
            artifact_dir=document_record.artifact_dir,
            parser_engine=document_record.parser_engine,
            parser_version=document_record.parser_version or "",
            postprocess_version=self.POSTPROCESS_VERSION,
            status="parsed",
            required_files=dict(self.REQUIRED_FILES),
            created_at=document_record.updated_at or document_record.created_at,
        )

    def write_manifest(self, document_record: DocumentRecord) -> Path:
        artifact_dir = Path(document_record.artifact_dir)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        manifest = self.build_manifest(document_record)
        path = artifact_dir / self.MANIFEST_FILENAME
        path.write_text(
            json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def load_manifest(self, artifact_dir: str | Path) -> ArtifactManifest:
        path = Path(artifact_dir) / self.MANIFEST_FILENAME
        if not path.exists():
            raise FileNotFoundError(f"缺少 artifact manifest: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ArtifactManifest.model_validate(payload)

    def validate_manifest(self, artifact_dir: str | Path) -> ArtifactManifest:
        base = Path(artifact_dir)
        manifest = self.load_manifest(base)
        if manifest.status != "parsed":
            raise ValueError(f"artifact manifest 状态不是 parsed: {manifest.status}")

        for key, relative_path in manifest.required_files.items():
            target = base / relative_path
            if not target.exists():
                raise FileNotFoundError(f"artifact 缺少必需文件 {key}: {target}")

        return manifest


artifact_manifest_service = ArtifactManifestService()
