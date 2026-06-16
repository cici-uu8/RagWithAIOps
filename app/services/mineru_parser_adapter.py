"""MinerU parser adapter for the formal P2 ingestion path."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from app.config import config
from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.knowledge_metadata_store import knowledge_metadata_store


class MinerUParserAdapter:
    """Run local MinerU CLI and reuse pdf_eval postprocess semantics."""

    def __init__(self):
        self.cli_path = Path(config.mineru_cli_path)
        self.api_url = config.mineru_api_url.strip()
        self.method = config.mineru_method
        self.backend = config.mineru_backend
        self.language = config.mineru_language
        self.enable_formula = config.mineru_enable_formula
        self.enable_table = config.mineru_enable_table
        self.mplconfigdir = config.mineru_mplconfigdir
        self.postprocess_script_path = Path(config.mineru_postprocess_script_path)

    def parse_document(self, document_record: DocumentRecord) -> DocumentRecord:
        if document_record.parser_engine != ParserEngine.MINERU:
            raise ValueError(
                f"MinerUParserAdapter 仅支持 mineru 文档: {document_record.parser_engine.value}"
            )

        source_path = Path(document_record.original_path).resolve()
        artifact_dir = Path(document_record.artifact_dir).resolve()
        raw_parent = artifact_dir / "raw"

        if not source_path.exists() or not source_path.is_file():
            raise ValueError(f"原始文件不存在: {document_record.original_path}")

        knowledge_metadata_store.upsert_document(document_record)
        parsing_record = knowledge_metadata_store.transition_document_status(
            document_record.doc_id,
            DocumentStatus.PARSING,
            status_source="MinerUParserAdapter.parse_document",
            status_detail="MinerU CLI parsing has started for the source document",
            status_evidence={
                "parser_engine": document_record.parser_engine.value,
                "source_path": source_path.as_posix(),
                "artifact_dir": artifact_dir.as_posix(),
                "raw_parent": raw_parent.as_posix(),
            },
        )
        if parsing_record is None:
            raise ValueError(f"文档不存在: {document_record.doc_id}")

        try:
            raw_source_dir = self._run_mineru_cli(source_path, raw_parent)
            markdown_path = self._locate_markdown_output(raw_source_dir, source_path.stem)
            images_dir = raw_source_dir / "images"
            postprocess_report = self._run_postprocess(raw_source_dir, artifact_dir, source_path)

            parsed_metadata = {
                "raw_output_dir": raw_source_dir.as_posix(),
                "markdown_path": markdown_path.as_posix(),
                "images_dir": images_dir.as_posix() if images_dir.exists() else "",
                "mineru_backend": self.backend,
                "mineru_method": self.method,
                "mineru_language": self.language,
                "postprocess_report": postprocess_report,
            }
            parsed_record = knowledge_metadata_store.transition_document_status(
                document_record.doc_id,
                DocumentStatus.PARSED,
                status_source="MinerUParserAdapter.parse_document",
                status_detail="MinerU raw output and postprocess artifacts were generated",
                status_evidence={
                    "raw_output_dir": raw_source_dir.as_posix(),
                    "markdown_path": markdown_path.as_posix(),
                    "postprocess_report_keys": sorted(postprocess_report.keys()),
                },
                parser_version=self._resolve_parser_version(),
                metadata_update=parsed_metadata,
            )
            if parsed_record is None:
                raise ValueError(f"文档不存在: {document_record.doc_id}")
            manifest_path = artifact_manifest_service.write_manifest(parsed_record)
            _ = artifact_manifest_service.validate_manifest(parsed_record.artifact_dir)

            index_pending_record = knowledge_metadata_store.transition_document_status(
                document_record.doc_id,
                DocumentStatus.INDEX_PENDING,
                status_source="MinerUParserAdapter.parse_document",
                status_detail="parsed artifact manifest was written and validated for indexing",
                status_evidence={
                    "artifact_manifest_path": manifest_path.as_posix(),
                    "artifact_dir": parsed_record.artifact_dir,
                },
                metadata_update={
                    "artifact_manifest_path": manifest_path.as_posix(),
                },
            )
            if index_pending_record is None:
                raise ValueError(f"文档不存在: {document_record.doc_id}")
            logger.info(
                "MinerU 解析完成: doc_id={}, raw_output_dir={}, artifact_dir={}",
                document_record.doc_id,
                raw_source_dir,
                artifact_dir,
            )
            return index_pending_record
        except Exception as exc:
            knowledge_metadata_store.transition_document_status(
                document_record.doc_id,
                DocumentStatus.PARSE_FAILED,
                status_source="MinerUParserAdapter.parse_document",
                status_detail="MinerU parsing or artifact validation failed",
                status_evidence={
                    "source_path": source_path.as_posix(),
                    "artifact_dir": artifact_dir.as_posix(),
                    "error_type": type(exc).__name__,
                },
                error_message=str(exc),
            )
            logger.error("MinerU 解析失败: doc_id={}, 错误={}", document_record.doc_id, exc)
            raise

    def _run_mineru_cli(self, source_path: Path, output_parent: Path) -> Path:
        output_parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(self.cli_path),
            "-p",
            str(source_path),
            "-o",
            str(output_parent),
            "-m",
            self.method,
            "-b",
            self.backend,
            "-l",
            self.language,
            "-f",
            str(self.enable_formula).lower(),
            "-t",
            str(self.enable_table).lower(),
        ]
        if self.api_url:
            cmd.extend(["--api-url", self.api_url])

        env = {**os.environ}
        if self.mplconfigdir:
            env["MPLCONFIGDIR"] = self.mplconfigdir

        logger.info("执行 MinerU CLI: {}", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            details = "\n".join(part for part in [stdout, stderr] if part)
            raise RuntimeError(
                "MinerU CLI failed"
                + (f": {details}" if details else f" with exit code {result.returncode}")
            )
        source_dir = self._locate_raw_output_dir(output_parent, source_path.stem)
        return source_dir

    def _locate_raw_output_dir(self, output_parent: Path, stem: str) -> Path:
        candidates = []
        if self.method:
            candidates.append(output_parent / stem / self.method)
        candidates.append(output_parent / stem / "auto")
        candidates.extend(sorted((output_parent / stem).glob("*")))

        seen: set[Path] = set()
        for source_dir in candidates:
            if source_dir in seen or not source_dir.is_dir():
                continue
            seen.add(source_dir)
            content_list = source_dir / f"{stem}_content_list.json"
            if content_list.exists():
                return source_dir
        expected = output_parent / stem / self.method / f"{stem}_content_list.json"
        raise FileNotFoundError(f"MinerU 原始输出不完整，缺少 content_list: {expected}")

    def _locate_markdown_output(self, source_dir: Path, stem: str) -> Path:
        preferred = source_dir / f"{stem}.md"
        if preferred.exists():
            return preferred

        candidates = sorted(source_dir.glob("*.md"))
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"MinerU 原始输出缺少 Markdown 文件: {source_dir}")

    def _run_postprocess(self, source_dir: Path, artifact_dir: Path, source_path: Path) -> dict[str, Any]:
        module = self._load_postprocess_module()
        report = module.postprocess(source_dir, artifact_dir, source_file=source_path)
        return report if isinstance(report, dict) else {"report": report}

    def _load_postprocess_module(self):
        module_name = "superbiz_mineru_postprocess"
        if module_name in sys.modules:
            return sys.modules[module_name]

        spec = importlib.util.spec_from_file_location(module_name, self.postprocess_script_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载 MinerU postprocess 脚本: {self.postprocess_script_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _resolve_parser_version(self) -> str:
        try:
            from importlib.metadata import version

            return f"mineru-{version('mineru')}"
        except Exception:
            return "mineru_cli"

mineru_parser_adapter = MinerUParserAdapter()
