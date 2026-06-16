import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_pdf_artifact_inventory_report import (
    build_checklist3_pdf_artifact_inventory_report,
    write_checklist3_pdf_artifact_inventory_report,
)


class Checklist3PdfArtifactInventoryReportTests(unittest.TestCase):
    def test_build_report_classifies_single_good_pdf_as_corpus_limited(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact_dir = _write_pdf_artifacts(root, doc_id="doc_pdf")
            metadata = _write_metadata_store(root, artifact_dir=artifact_dir)
            import_state = _write_import_state(root)

            report = build_checklist3_pdf_artifact_inventory_report(
                metadata_store_path=metadata,
                import_state_path=import_state,
            )

        self.assertEqual(report["status"], "corpus_limited")
        self.assertEqual(report["summary"]["indexed_pdf_count"], 1)
        self.assertEqual(report["summary"]["page_sample_candidates"], 1)
        self.assertEqual(report["summary"]["table_sample_candidates"], 1)
        self.assertIn("indexed_pdf_corpus_single_doc", report["coverage_gaps"])
        self.assertIn("pdf_table_eval_candidate_single_doc", report["coverage_gaps"])
        doc = report["documents"][0]
        self.assertEqual(doc["blocks"]["page_coverage_rate"], 1.0)
        self.assertEqual(doc["tables"]["table_ids"], ["t00001"])
        self.assertIn("table_eval_candidate", doc["suitability"])

    def test_missing_blocks_makes_pdf_not_suitable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact_dir = root / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "tables.json").write_text("[]\n", encoding="utf-8")
            metadata = _write_metadata_store(root, artifact_dir=artifact_dir)
            import_state = _write_import_state(root)

            report = build_checklist3_pdf_artifact_inventory_report(
                metadata_store_path=metadata,
                import_state_path=import_state,
            )

        doc = report["documents"][0]
        self.assertIn("blocks_json_missing", doc["issues"])
        self.assertIn("not_suitable", doc["suitability"])
        self.assertIn("no_pdf_page_eval_candidates", report["coverage_gaps"])

    def test_non_pdf_documents_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metadata = root / "metadata.json"
            metadata.write_text(
                json.dumps(
                    {
                        "documents": {
                            "doc_md": {
                                "doc_id": "doc_md",
                                "kb_id": "kb",
                                "file_name": "runbook.md",
                                "file_ext": "md",
                                "status": "indexed",
                                "artifact_dir": str(root / "artifacts"),
                                "original_path": str(root / "runbook.md"),
                                "parser_engine": "plain_text",
                            }
                        },
                        "chunks_by_doc": {},
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            report = build_checklist3_pdf_artifact_inventory_report(
                metadata_store_path=metadata,
                import_state_path=root / "missing_import_state.json",
            )

        self.assertEqual(report["summary"]["indexed_pdf_count"], 0)
        self.assertEqual(report["documents"], [])

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifact_dir = _write_pdf_artifacts(root, doc_id="doc_pdf")
            metadata = _write_metadata_store(root, artifact_dir=artifact_dir)
            import_state = _write_import_state(root)
            output_json = root / "report.json"
            output_md = root / "report.md"

            report = write_checklist3_pdf_artifact_inventory_report(
                metadata_store_path=metadata,
                import_state_path=import_state,
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "corpus_limited")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn("Checklist 3 PDF Artifact Inventory Report", output_md.read_text(encoding="utf-8"))


def _write_pdf_artifacts(root: Path, *, doc_id: str) -> Path:
    artifact_dir = root / doc_id / "artifacts"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "blocks.json").write_text(
        json.dumps(
            [
                {"id": "b1", "type": "heading", "text": "Title", "page": 1},
                {"id": "b2", "type": "text", "text": "Body", "page": 1},
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "tables.json").write_text(
        json.dumps(
            [
                {
                    "table_id": "t00001",
                    "page": 1,
                    "rows": [["字段", "值"], ["部门", "工艺部"]],
                    "markdown": "| 字段 | 值 |",
                }
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return artifact_dir


def _write_metadata_store(root: Path, *, artifact_dir: Path) -> Path:
    path = root / "metadata.json"
    path.write_text(
        json.dumps(
            {
                "documents": {
                    "doc_pdf": {
                        "doc_id": "doc_pdf",
                        "kb_id": "craft_dept",
                        "file_name": "sample.pdf",
                        "file_ext": "pdf",
                        "status": "indexed",
                        "artifact_dir": str(artifact_dir),
                        "original_path": str(root / "sample.pdf"),
                        "parser_engine": "mineru",
                    }
                },
                "chunks_by_doc": {},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_import_state(root: Path) -> Path:
    path = root / "import_state.json"
    path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "doc_id": "doc_pdf",
                        "kb_id": "craft_dept",
                        "file_name": "sample.pdf",
                        "file_ext": "pdf",
                        "status": "indexed",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
