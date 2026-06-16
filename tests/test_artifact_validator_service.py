import json
import tempfile
import unittest
from pathlib import Path

from app.services.artifact_validator_service import ArtifactValidatorService


class ArtifactValidatorServiceTests(unittest.TestCase):
    def _write_json(self, path: Path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _write_valid_artifacts(self, artifact_dir: Path):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(
            artifact_dir / "artifact_manifest.json",
            {
                "schema_version": "artifact_manifest_v1",
                "kb_id": "default",
                "doc_id": "doc_pdf",
                "source_file": "/tmp/manual.pdf",
                "artifact_dir": artifact_dir.as_posix(),
                "parser_engine": "mineru",
                "parser_version": "mineru-3.1.11",
                "postprocess_version": "pdf_eval_mineru_postprocess_v1",
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
        )
        (artifact_dir / "cleaned.md").write_text("# cleaned", encoding="utf-8")
        self._write_json(artifact_dir / "chunks.json", [{"id": "c1", "text": "正文"}])
        self._write_json(artifact_dir / "tables.json", [])
        self._write_json(artifact_dir / "blocks.json", [])
        self._write_json(artifact_dir / "quality_report.json", {"fatal_errors": [], "warnings": []})

    def test_valid_artifacts_report_pass_without_raising(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts"
            self._write_valid_artifacts(artifact_dir)

            report = ArtifactValidatorService().validate_artifact_dir(artifact_dir)

        self.assertEqual(report.status, "pass")
        self.assertEqual(report.issue_counts, {"warning": 0, "fatal_candidate": 0})
        self.assertEqual(report.parser_version, "mineru-3.1.11")
        self.assertEqual(report.postprocess_version, "pdf_eval_mineru_postprocess_v1")
        self.assertEqual(report.issues, [])

    def test_missing_required_file_is_warning_only_fatal_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts"
            self._write_valid_artifacts(artifact_dir)
            (artifact_dir / "tables.json").unlink()

            report = ArtifactValidatorService().validate_artifact_dir(artifact_dir)

        self.assertEqual(report.status, "warning")
        self.assertEqual(report.issue_counts["fatal_candidate"], 1)
        self.assertEqual(report.issues[0].code, "required_file_missing")
        self.assertIn("tables.json", report.issues[0].path)

    def test_invalid_json_is_reported_without_raising(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts"
            self._write_valid_artifacts(artifact_dir)
            (artifact_dir / "chunks.json").write_text("{bad", encoding="utf-8")

            report = ArtifactValidatorService().validate_artifact_dir(artifact_dir)

        self.assertEqual(report.status, "warning")
        self.assertEqual(report.issue_counts["fatal_candidate"], 1)
        self.assertEqual(report.issues[0].code, "invalid_json")
        self.assertIn("chunks.json", report.issues[0].path)

    def test_quality_report_fatal_errors_are_reported_as_fatal_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts"
            self._write_valid_artifacts(artifact_dir)
            self._write_json(
                artifact_dir / "quality_report.json",
                {"fatal_errors": ["ocr_failed"], "warnings": ["low_ocr_confidence"]},
            )

            report = ArtifactValidatorService().validate_artifact_dir(artifact_dir)

        self.assertEqual(report.status, "warning")
        self.assertEqual(report.issue_counts["fatal_candidate"], 1)
        self.assertEqual(report.issue_counts["warning"], 1)
        self.assertEqual(
            [issue.code for issue in report.issues],
            ["quality_report_fatal_errors", "quality_report_warnings"],
        )


if __name__ == "__main__":
    unittest.main()
