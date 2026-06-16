import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist4_mixed_rag_eval_readiness_report import (
    build_mixed_rag_eval_readiness_report,
    write_mixed_rag_eval_readiness_report,
)


class Checklist4MixedRagEvalReadinessReportTests(unittest.TestCase):
    def test_current_shape_blocks_on_pdf_corpus_and_missing_evalset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            import_state = _write_import_state(root, md_count=12, pdf_count=1)

            report = build_mixed_rag_eval_readiness_report(
                import_state_path=import_state,
                evalset_path=root / "missing.jsonl",
            )

        self.assertEqual(report["status"], "blocked_pdf_corpus_insufficient")
        self.assertFalse(report["ready_for_mixed_baseline"])
        self.assertEqual(report["corpus"]["indexed_document_count"], 13)
        self.assertEqual(report["corpus"]["indexed_pdf_count"], 1)
        self.assertTrue(report["corpus"]["gates"]["indexed_documents"])
        self.assertFalse(report["corpus"]["gates"]["indexed_pdf_documents"])
        self.assertIn("indexed_pdf_count_below_target", report["gaps"])
        self.assertIn("mixed_evalset_missing", report["gaps"])

    def test_ready_when_corpus_and_mixed_evalset_meet_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            import_state = _write_import_state(root, md_count=8, pdf_count=5)
            evalset = _write_mixed_evalset(root / "mixed.jsonl", md_count=30, pdf_count=20)

            report = build_mixed_rag_eval_readiness_report(
                import_state_path=import_state,
                evalset_path=evalset,
            )

        self.assertEqual(report["status"], "ready_for_mixed_baseline")
        self.assertTrue(report["ready_for_mixed_baseline"])
        self.assertEqual(report["gaps"], [])
        self.assertEqual(report["evalset"]["sample_count"], 50)
        self.assertGreaterEqual(report["evalset"]["pdf_sample_count"], 15)
        self.assertGreaterEqual(report["evalset"]["expression_gap_sample_count"], 10)
        self.assertGreaterEqual(report["evalset"]["permission_scope_sample_count"], 5)

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            import_state = _write_import_state(root, md_count=12, pdf_count=1)
            output_json = root / "report.json"
            output_md = root / "report.md"

            report = write_mixed_rag_eval_readiness_report(
                import_state_path=import_state,
                evalset_path=root / "missing.jsonl",
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "blocked_pdf_corpus_insufficient")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn("Mixed RAG Eval Readiness", output_md.read_text(encoding="utf-8"))


def _write_import_state(root: Path, *, md_count: int, pdf_count: int) -> Path:
    docs = []
    for index in range(1, md_count + 1):
        source = root / f"doc_md_{index}.md"
        source.write_text(f"# Markdown {index}\n", encoding="utf-8")
        docs.append(_document(index, source, file_ext="md", kb_id="process_digital_dept"))
    for index in range(1, pdf_count + 1):
        source = root / f"doc_pdf_{index}.pdf"
        source.write_bytes(b"%PDF-1.4\n")
        artifact_dir = root / f"artifacts_pdf_{index}"
        artifact_dir.mkdir()
        docs.append(
            _document(
                index,
                source,
                file_ext="pdf",
                kb_id="craft_dept",
                artifact_dir=artifact_dir,
            )
        )
    path = root / "current_import_state.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "current_import_state_v1",
                "summary": {"total_documents": len(docs), "status_counts": {"indexed": len(docs)}},
                "documents": docs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _document(
    index: int,
    source: Path,
    *,
    file_ext: str,
    kb_id: str,
    artifact_dir: Path | None = None,
) -> dict:
    doc_id = f"doc_{file_ext}_{index}"
    evidence = {
        "child_chunk_count": 2,
        "parent_chunk_count": 0,
        "vector_document_count": 2,
        "original_path": source.as_posix(),
    }
    if artifact_dir is not None:
        evidence["artifact_dir"] = artifact_dir.as_posix()
    return {
        "doc_id": doc_id,
        "kb_id": kb_id,
        "file_name": source.name,
        "file_ext": file_ext,
        "status": "indexed",
        "source_ref": {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "source_file": source.name,
            "source_uri": source.as_posix(),
        },
        "status_evidence": evidence,
        "parser_engine": "mineru" if file_ext == "pdf" else "plain_text",
        "original_path": source.as_posix(),
    }


def _write_mixed_evalset(path: Path, *, md_count: int, pdf_count: int) -> Path:
    rows = []
    for index in range(1, md_count + 1):
        rows.append(
            {
                "sample_id": f"MIX-MD-{index:02d}",
                "query": f"markdown query {index}",
                "expected_doc_ids": [f"doc_md_{((index - 1) % 8) + 1}"],
                "allowed_kb_ids": ["process_digital_dept"],
                "failure_class": "expression_gap" if index <= 10 else "content_recall",
            }
        )
    for index in range(1, pdf_count + 1):
        rows.append(
            {
                "sample_id": f"MIX-PDF-{index:02d}",
                "query": f"pdf query {index}",
                "expected_doc_ids": [f"doc_pdf_{((index - 1) % 5) + 1}"],
                "allowed_kb_ids": ["craft_dept"],
                "failure_class": "permission_scope" if index <= 5 else "pdf_page_source_ref",
            }
        )
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


if __name__ == "__main__":
    unittest.main()
