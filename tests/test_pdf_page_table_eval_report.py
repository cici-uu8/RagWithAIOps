import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models import ChunkRecord, ParserEngine, SourceRef
from evals.knowledge_base.pdf_page_table_eval_report import (
    build_pdf_page_table_eval_report,
    write_pdf_page_table_eval_report,
)


class PdfPageTableEvalReportTests(unittest.TestCase):
    def test_build_pdf_page_table_eval_report_reads_artifact_and_source_ref(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir)
            (artifact_dir / "chunks.json").write_text(
                json.dumps(
                    {
                        "chunks": [
                            {
                                "chunk_id": "doc-pdf:c00001",
                                "page_start": 2,
                                "page_end": 2,
                                "source_ref": {
                                    "kb_id": "default",
                                    "doc_id": "doc-pdf",
                                    "chunk_id": "doc-pdf:c00001",
                                    "source_file": "manual.pdf",
                                    "page_start": 2,
                                    "page_end": 2,
                                    "parser_engine": "mineru",
                                    "content_type": "text",
                                },
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (artifact_dir / "tables.json").write_text(
                json.dumps(
                    {
                        "tables": [
                            {
                                "table_id": "t00001",
                                "page_start": 4,
                                "page_end": 4,
                                "rows": [["设备", "处理"]],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = build_pdf_page_table_eval_report(
                [
                    {
                        "sample_id": "pdf-1",
                        "artifact_dir": artifact_dir.as_posix(),
                        "expected_page": 2,
                        "expected_table_id": "t00001",
                    }
                ]
            )

        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["page_accuracy_passed"], 1)
        self.assertEqual(report["summary"]["table_presence_passed"], 1)
        self.assertEqual(report["summary"]["source_ref_resolvable_passed"], 1)
        row = report["samples"][0]
        self.assertTrue(row["page_accuracy"])
        self.assertTrue(row["table_present"])
        self.assertTrue(row["source_ref_resolvable"])
        self.assertEqual(row["page_sources"], [2])

    def test_write_pdf_page_table_eval_report_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact_dir = root / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "chunks.json").write_text('{"chunks": []}', encoding="utf-8")
            (artifact_dir / "tables.json").write_text('{"tables": []}', encoding="utf-8")

            report = write_pdf_page_table_eval_report(
                [{"sample_id": "pdf-1", "artifact_dir": artifact_dir.as_posix()}],
                output_json=root / "report.json",
                output_md=root / "report.md",
            )

            self.assertTrue((root / "report.json").exists())
            self.assertTrue((root / "report.md").exists())
            self.assertIn("PDF Page/Table Eval", (root / "report.md").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["total"], 1)

    def test_build_pdf_page_table_eval_report_reads_pages_array_from_raw_chunks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir)
            (artifact_dir / "chunks.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "c00001",
                            "pages": [1],
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (artifact_dir / "tables.json").write_text(
                json.dumps(
                    [
                        {
                            "table_id": "t00001",
                            "page_start": 1,
                            "page_end": 1,
                        }
                    ],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            report = build_pdf_page_table_eval_report(
                [
                    {
                        "sample_id": "pdf-raw",
                        "artifact_dir": artifact_dir.as_posix(),
                        "expected_page": 1,
                        "expected_table_id": "t00001",
                    }
                ]
            )

        self.assertEqual(report["samples"][0]["page_sources"], [1])
        self.assertTrue(report["samples"][0]["page_accuracy"])

    def test_build_pdf_page_table_eval_report_can_resolve_source_ref_from_metadata_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir)
            (artifact_dir / "chunks.json").write_text(
                json.dumps([{"id": "c00001", "pages": [1]}], ensure_ascii=False),
                encoding="utf-8",
            )
            (artifact_dir / "tables.json").write_text(
                json.dumps([{"table_id": "t00001", "page_start": 1}], ensure_ascii=False),
                encoding="utf-8",
            )
            chunk = ChunkRecord(
                chunk_id="doc-pdf:c00001",
                doc_id="doc-pdf",
                kb_id="default",
                content="设备处理步骤",
                chunk_index=0,
                start_index=0,
                end_index=6,
                page_start=1,
                page_end=1,
                source_ref=SourceRef(
                    kb_id="default",
                    doc_id="doc-pdf",
                    chunk_id="doc-pdf:c00001",
                    source_file="manual.pdf",
                    page_start=1,
                    page_end=1,
                    parser_engine=ParserEngine.MINERU,
                ),
            )

            with patch(
                "app.services.knowledge_metadata_store.knowledge_metadata_store.list_chunks_by_doc_id",
                return_value=[chunk],
            ):
                report = build_pdf_page_table_eval_report(
                    [
                        {
                            "sample_id": "pdf-indexed",
                            "doc_id": "doc-pdf",
                            "artifact_dir": artifact_dir.as_posix(),
                            "expected_page": 1,
                            "expected_table_id": "t00001",
                        }
                    ]
                )

        self.assertEqual(report["summary"]["source_ref_resolvable_passed"], 1)
        self.assertTrue(report["samples"][0]["source_ref_resolvable"])


if __name__ == "__main__":
    unittest.main()
