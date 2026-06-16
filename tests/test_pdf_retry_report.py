import json
import tempfile
import unittest
from pathlib import Path

from app.models import DocumentRecord, DocumentStatus, ParserEngine
from evals.knowledge_base.pdf_retry_report import build_pdf_retry_report


class FakeMetadataStore:
    def __init__(self, document=None):
        self.document = document

    def get_document(self, doc_id):
        if self.document and self.document.doc_id == doc_id:
            return self.document
        return None


class FakeWorkflow:
    def __init__(self, result):
        self.result = result
        self.processed_doc_ids = []

    def process_deferred_document(self, doc_id):
        self.processed_doc_ids.append(doc_id)
        return self.result


def _document(root: Path, *, status=DocumentStatus.INDEX_FAILED, parser_engine=ParserEngine.MINERU):
    original = root / "manual.pdf"
    original.write_bytes(b"%PDF-1.4 mock")
    return DocumentRecord(
        doc_id="doc_pdf",
        kb_id="craft_dept",
        file_name="manual.pdf",
        file_ext="pdf",
        original_path=original.as_posix(),
        artifact_dir=(root / "artifacts").as_posix(),
        parser_engine=parser_engine,
        status=status,
    )


def _write_valid_artifacts(artifact_dir: Path):
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "artifact_manifest_v1",
                "kb_id": "craft_dept",
                "doc_id": "doc_pdf",
                "source_file": "/tmp/manual.pdf",
                "artifact_dir": artifact_dir.as_posix(),
                "parser_engine": "mineru",
                "parser_version": "mineru-test",
                "postprocess_version": "postprocess-test",
                "status": "parsed",
                "required_files": {
                    "cleaned_md": "cleaned.md",
                    "chunks_json": "chunks.json",
                    "tables_json": "tables.json",
                    "blocks_json": "blocks.json",
                    "quality_report_json": "quality_report.json",
                },
                "created_at": "2026-06-08T00:00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (artifact_dir / "cleaned.md").write_text("# cleaned", encoding="utf-8")
    for name, payload in {
        "chunks.json": [],
        "tables.json": [],
        "blocks.json": [],
        "quality_report.json": {"fatal_errors": [], "warnings": []},
    }.items():
        (artifact_dir / name).write_text(json.dumps(payload), encoding="utf-8")


class PdfRetryReportTests(unittest.TestCase):
    def test_dry_run_reports_retryable_failed_pdf_without_calling_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            document = _document(root)
            _write_valid_artifacts(Path(document.artifact_dir))
            workflow = FakeWorkflow(document)

            report = build_pdf_retry_report(
                "doc_pdf",
                metadata_store=FakeMetadataStore(document),
                workflow=workflow,
                apply=False,
            )

        self.assertEqual(report["status"], "dry_run")
        self.assertTrue(report["would_retry"])
        self.assertEqual(report["document"]["status_before"], "index_failed")
        self.assertEqual(report["action"], "run_process_deferred_document")
        self.assertEqual(report["artifact_validation"]["status"], "pass")
        self.assertEqual(report["artifact_validation"]["issue_counts"], {"warning": 0, "fatal_candidate": 0})
        self.assertEqual(workflow.processed_doc_ids, [])

    def test_blocks_non_mineru_or_non_pdf_without_calling_workflow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            document = _document(root, parser_engine=ParserEngine.PLAIN_TEXT)
            workflow = FakeWorkflow(document)

            report = build_pdf_retry_report(
                "doc_pdf",
                metadata_store=FakeMetadataStore(document),
                workflow=workflow,
                apply=True,
            )

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["reason"], "unsupported_parser_engine")
        self.assertFalse(report["would_retry"])
        self.assertEqual(workflow.processed_doc_ids, [])

    def test_apply_calls_workflow_and_reports_status_after(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            before = _document(root)
            after = before.model_copy(
                update={
                    "status": DocumentStatus.INDEXED,
                    "status_source": "FakeWorkflow.process_deferred_document",
                    "status_detail": "indexed by fake workflow",
                }
            )
            workflow = FakeWorkflow(after)

            report = build_pdf_retry_report(
                "doc_pdf",
                metadata_store=FakeMetadataStore(before),
                workflow=workflow,
                apply=True,
            )

        self.assertEqual(report["status"], "applied")
        self.assertEqual(report["document"]["status_before"], "index_failed")
        self.assertEqual(report["document"]["status_after"], "indexed")
        self.assertEqual(workflow.processed_doc_ids, ["doc_pdf"])


if __name__ == "__main__":
    unittest.main()
