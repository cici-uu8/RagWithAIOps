import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_eval_coverage_report import (
    DEFAULT_EVALSET_SPECS,
    build_checklist3_eval_coverage_report,
    write_checklist3_eval_coverage_report,
)


class Checklist3EvalCoverageReportTests(unittest.TestCase):
    def test_build_report_inventory_detects_current_coverage_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_evalsets(root)
            smoke = _write_pdf_smoke(root / "smoke.json")

            report = build_checklist3_eval_coverage_report(
                _specs_for(paths),
                pdf_smoke_report=smoke,
            )

        self.assertEqual(report["status"], "needs_expansion")
        self.assertEqual(report["summary"]["total_evalsets"], 4)
        self.assertEqual(report["summary"]["total_samples"], 31)
        self.assertEqual(report["summary"]["pdf_page_table_doc_count"], 1)
        self.assertTrue(report["summary"]["pdf_smoke_denied_no_leak"])
        self.assertIn("permission_filtered", report["summary"]["key_coverage"])
        self.assertIn("wrong_scope_guard", report["summary"]["key_coverage"])
        self.assertIn("citation_resolvable", report["summary"]["key_coverage"])
        self.assertIn("pdf_page_table_eval_needs_more_samples", report["coverage_gaps"])
        self.assertIn("pdf_page_table_eval_needs_more_docs", report["coverage_gaps"])

    def test_missing_pdf_smoke_report_is_recorded_as_coverage_gap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_evalsets(root)

            report = build_checklist3_eval_coverage_report(
                _specs_for(paths),
                pdf_smoke_report=root / "missing.json",
            )

        self.assertIn("pdf_tool_denied_no_leak_smoke_missing", report["coverage_gaps"])
        self.assertEqual(report["pdf_smoke"]["status"], "missing")

    def test_write_report_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            paths = _write_evalsets(root)
            smoke = _write_pdf_smoke(root / "smoke.json")
            output_json = root / "coverage.json"
            output_md = root / "coverage.md"

            report = write_checklist3_eval_coverage_report(
                _specs_for(paths),
                pdf_smoke_report=smoke,
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "needs_expansion")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn("Checklist 3 Eval Coverage Report", output_md.read_text(encoding="utf-8"))

    def test_default_specs_keep_expected_coverage_ids(self):
        self.assertEqual(
            [spec["coverage_id"] for spec in DEFAULT_EVALSET_SPECS],
            [
                "e1_permission_isolation",
                "e1_scope_lock",
                "e1_citation_accuracy",
                "pdf_page_table_source_ref",
            ],
        )


def _specs_for(paths: dict[str, Path]) -> list[dict[str, str]]:
    return [
        {
            "coverage_id": "e1_permission_isolation",
            "eval_type": "permission",
            "path": paths["permission"].as_posix(),
        },
        {
            "coverage_id": "e1_scope_lock",
            "eval_type": "scope",
            "path": paths["scope"].as_posix(),
        },
        {
            "coverage_id": "e1_citation_accuracy",
            "eval_type": "citation",
            "path": paths["citation"].as_posix(),
        },
        {
            "coverage_id": "pdf_page_table_source_ref",
            "eval_type": "pdf_page_table",
            "path": paths["pdf"].as_posix(),
        },
    ]


def _write_evalsets(root: Path) -> dict[str, Path]:
    paths = {
        "permission": root / "permission.jsonl",
        "scope": root / "scope.jsonl",
        "citation": root / "citation.jsonl",
        "pdf": root / "pdf.json",
    }
    _write_jsonl(
        paths["permission"],
        [
            {
                "sample_id": f"PERM-{index:02d}",
                "query": "blocked query",
                "allowed_kb_ids": ["process_digital_dept"],
                "expected_failure": "permission_filtered",
                "target_kb_id": "craft_dept",
                "retrieval_mode": "sparse_only",
            }
            for index in range(1, 11)
        ],
    )
    _write_jsonl(
        paths["scope"],
        [
            {
                "sample_id": f"SCOPE-{index:02d}",
                "query": "scoped query",
                "allowed_kb_ids": ["craft_dept"],
                "expected_doc_ids": ["doc_craft"],
                "retrieved_must_not_contain_kb": ["process_digital_dept"],
                "retrieval_mode": "sparse_only",
            }
            for index in range(1, 11)
        ],
    )
    _write_jsonl(
        paths["citation"],
        [
            {
                "sample_id": f"CITE-{index:02d}",
                "query": "citation query",
                "allowed_kb_ids": ["craft_dept"],
                "expected_doc_ids": ["doc_craft"],
                "citation_must_resolvable": True,
                "expected_source_ref_fields": ["kb_id", "doc_id", "chunk_id"],
                "retrieval_mode": "sparse_only",
            }
            for index in range(1, 11)
        ],
    )
    paths["pdf"].write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "PDF-01",
                        "doc_id": "doc_craft_pdf",
                        "expected_page": 1,
                        "expected_table_id": "t00001",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return paths


def _write_pdf_smoke(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "stage": "B4-G7",
                "doc_id": "doc_craft_pdf",
                "schema_has_no_context_or_owner": True,
                "authorized_page_read": {"status": "success"},
                "authorized_table_extract": {"status": "success"},
                "denied_page_read": {
                    "status": "error",
                    "error": "permission_denied",
                    "leak_detected": False,
                },
                "denied_table_extract": {
                    "status": "error",
                    "error": "permission_denied",
                    "leak_detected": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
