import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evals.knowledge_base.pdf_baseline_report import build_pdf_baseline_report


class PdfBaselineReportTests(unittest.TestCase):
    def test_build_pdf_baseline_report_dry_run_profiles_without_mineru(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4 mock")

            with patch(
                "evals.knowledge_base.pdf_baseline_report.pdf_profile_service.profile_pdf",
                return_value={
                    "profile_status": "ok",
                    "page_count": 1,
                    "is_encrypted": False,
                    "risk_flags": ["native_text"],
                },
            ):
                report = build_pdf_baseline_report(
                    [
                        {
                            "sample_id": "sample",
                            "pdf_path": pdf.as_posix(),
                            "doc_id": "doc_sample",
                            "kb_id": "default",
                        }
                    ],
                    run_mineru=False,
                )

        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["profile_status_counts"], {"ok": 1})
        self.assertEqual(report["summary"]["mineru_status_counts"], {"not_run": 1})
        self.assertEqual(report["samples"][0]["sample_id"], "sample")
        self.assertEqual(report["samples"][0]["profile"]["risk_flags"], ["native_text"])
        self.assertEqual(report["samples"][0]["mineru"]["status"], "not_run")

    def test_build_pdf_baseline_report_marks_missing_mineru_cli_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pdf = root / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4 mock")

            with (
                patch(
                    "evals.knowledge_base.pdf_baseline_report.pdf_profile_service.profile_pdf",
                    return_value={
                        "profile_status": "ok",
                        "page_count": 1,
                        "is_encrypted": False,
                        "risk_flags": ["native_text"],
                    },
                ),
                patch(
                    "evals.knowledge_base.pdf_baseline_report.MinerUParserAdapter",
                ) as adapter_cls,
            ):
                adapter = adapter_cls.return_value
                adapter.cli_path = root / "missing-mineru"
                adapter.method = "txt"
                adapter.backend = "pipeline"
                adapter.language = "ch"
                adapter.enable_formula = False
                adapter.enable_table = False

                report = build_pdf_baseline_report(
                    [
                        {
                            "sample_id": "sample",
                            "pdf_path": pdf.as_posix(),
                            "doc_id": "doc_sample",
                            "kb_id": "default",
                        }
                    ],
                    run_mineru=True,
                )

        self.assertEqual(report["summary"]["mineru_status_counts"], {"mineru_unavailable": 1})
        self.assertEqual(report["samples"][0]["mineru"]["reason"], "cli_missing")
        self.assertEqual(report["samples"][0]["validator"]["status"], "not_run")

    def test_build_pdf_baseline_report_marks_missing_sample_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_pdf = Path(tmpdir) / "missing.pdf"
            report = build_pdf_baseline_report(
                [
                    {
                        "sample_id": "missing",
                        "pdf_path": missing_pdf.as_posix(),
                        "doc_id": "doc_missing",
                        "kb_id": "default",
                    }
                ],
                run_mineru=True,
            )

        self.assertEqual(report["summary"]["profile_status_counts"], {"sample_invalid": 1})
        self.assertEqual(report["summary"]["mineru_status_counts"], {"sample_invalid": 1})
        self.assertEqual(report["samples"][0]["profile"]["reason"], "sample_missing")
        self.assertEqual(report["samples"][0]["validator"]["status"], "not_run")


if __name__ == "__main__":
    unittest.main()
