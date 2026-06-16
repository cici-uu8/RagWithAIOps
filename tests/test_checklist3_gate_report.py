import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_gate_report import (
    DEFAULT_REPORT_SPECS,
    build_checklist3_gate_report,
    write_checklist3_gate_report,
)


class Checklist3GateReportTests(unittest.TestCase):
    def test_build_checklist3_gate_report_passes_current_gate_shapes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = _write_gate_reports(root, generated_at="2026-06-09T01:00:00+00:00")

            report = build_checklist3_gate_report(
                _specs_for(reports),
                as_of="2026-06-09T12:00:00+00:00",
                max_age_days=7,
            )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["stale_reports"], 0)
        self.assertEqual(report["summary"]["blocking_reports"], 0)
        self.assertEqual(report["summary"]["fresh_reports"], 4)
        self.assertEqual({row["gate_status"] for row in report["reports"]}, {"passed"})

    def test_stale_report_blocks_gate_even_if_summary_passes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = _write_gate_reports(root, generated_at="2026-05-01T01:00:00+00:00")

            report = build_checklist3_gate_report(
                _specs_for(reports),
                as_of="2026-06-09T12:00:00+00:00",
                max_age_days=7,
            )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["summary"]["stale_reports"], 4)
        self.assertIn("report_stale", report["summary"]["blockers"])

    def test_scope_answer_wrong_does_not_block_when_scope_and_citation_are_clean(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = _write_gate_reports(
                root,
                generated_at="2026-06-09T01:00:00+00:00",
                scope_summary={
                    "total": 10,
                    "status_counts": {"passed": 9, "failed": 1},
                    "failure_categories": {"passed": 9, "answer_wrong": 1},
                    "not_ready": 0,
                    "asset_blocked": 0,
                    "wrong_scope_count": 0,
                    "citation_unresolvable_count": 0,
                    "all_source_ref_resolvable": True,
                },
            )

            report = build_checklist3_gate_report(
                _specs_for(reports),
                as_of="2026-06-09T12:00:00+00:00",
                max_age_days=7,
            )

        scope_row = next(row for row in report["reports"] if row["gate_id"] == "e1_scope_lock")
        self.assertEqual(scope_row["gate_status"], "passed")
        self.assertEqual(report["status"], "passed")

    def test_wrong_scope_blocks_scope_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = _write_gate_reports(
                root,
                generated_at="2026-06-09T01:00:00+00:00",
                scope_summary={
                    "total": 10,
                    "status_counts": {"passed": 9, "failed": 1},
                    "failure_categories": {"passed": 9, "wrong_scope": 1},
                    "not_ready": 0,
                    "asset_blocked": 0,
                    "wrong_scope_count": 1,
                    "citation_unresolvable_count": 0,
                    "all_source_ref_resolvable": True,
                },
            )

            report = build_checklist3_gate_report(
                _specs_for(reports),
                as_of="2026-06-09T12:00:00+00:00",
                max_age_days=7,
            )

        self.assertEqual(report["status"], "failed")
        scope_row = next(row for row in report["reports"] if row["gate_id"] == "e1_scope_lock")
        self.assertIn("wrong_scope_count_nonzero", scope_row["blockers"])

    def test_write_checklist3_gate_report_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = _write_gate_reports(root, generated_at="2026-06-09T01:00:00+00:00")
            output_json = root / "gate.json"
            output_md = root / "gate.md"

            report = write_checklist3_gate_report(
                _specs_for(reports),
                as_of="2026-06-09T12:00:00+00:00",
                max_age_days=7,
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "passed")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn("Checklist 3 Gate Report", output_md.read_text(encoding="utf-8"))

    def test_default_report_specs_point_to_current_b4_gates(self):
        gate_ids = [spec["gate_id"] for spec in DEFAULT_REPORT_SPECS]
        self.assertEqual(
            gate_ids,
            [
                "pdf_page_table_source_ref",
                "e1_permission_isolation",
                "e1_scope_lock",
                "e1_citation_accuracy",
            ],
        )


def _specs_for(paths: dict[str, Path]) -> list[dict[str, str]]:
    return [
        {
            "gate_id": "pdf_page_table_source_ref",
            "report_type": "pdf_page_table",
            "path": paths["pdf"].as_posix(),
        },
        {
            "gate_id": "e1_permission_isolation",
            "report_type": "rag_permission",
            "path": paths["permission"].as_posix(),
        },
        {
            "gate_id": "e1_scope_lock",
            "report_type": "rag_scope",
            "path": paths["scope"].as_posix(),
        },
        {
            "gate_id": "e1_citation_accuracy",
            "report_type": "rag_citation",
            "path": paths["citation"].as_posix(),
        },
    ]


def _write_gate_reports(
    root: Path,
    *,
    generated_at: str,
    scope_summary: dict | None = None,
) -> dict[str, Path]:
    paths = {
        "pdf": root / "pdf.json",
        "permission": root / "permission.json",
        "scope": root / "scope.json",
        "citation": root / "citation.json",
    }
    _write_json(
        paths["pdf"],
        {
            "generated_at": generated_at,
            "summary": {
                "total": 1,
                "page_accuracy_passed": 1,
                "table_presence_passed": 1,
                "source_ref_resolvable_passed": 1,
                "artifact_missing_count": 0,
            },
        },
    )
    _write_json(
        paths["permission"],
        {
            "generated_at": generated_at,
            "summary": {
                "total": 10,
                "status_counts": {"passed": 10},
                "failure_categories": {"passed": 10},
                "not_ready": 0,
                "asset_blocked": 0,
                "wrong_scope_count": 0,
                "citation_unresolvable_count": 0,
                "permission_filtered_passed": 10,
                "all_source_ref_resolvable": True,
            },
        },
    )
    _write_json(
        paths["scope"],
        {
            "generated_at": generated_at,
            "summary": scope_summary
            or {
                "total": 10,
                "status_counts": {"passed": 10},
                "failure_categories": {"passed": 10},
                "not_ready": 0,
                "asset_blocked": 0,
                "wrong_scope_count": 0,
                "citation_unresolvable_count": 0,
                "all_source_ref_resolvable": True,
            },
        },
    )
    _write_json(
        paths["citation"],
        {
            "generated_at": generated_at,
            "summary": {
                "total": 10,
                "status_counts": {"passed": 10},
                "failure_categories": {"passed": 10},
                "not_ready": 0,
                "asset_blocked": 0,
                "wrong_scope_count": 0,
                "citation_unresolvable_count": 0,
                "all_source_ref_resolvable": True,
            },
        },
    )
    return paths


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
