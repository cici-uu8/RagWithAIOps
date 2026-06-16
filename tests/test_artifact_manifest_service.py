import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.models import DocumentRecord, DocumentStatus, ParserEngine
from app.services.artifact_manifest_service import artifact_manifest_service


class ArtifactManifestServiceTests(unittest.TestCase):
    def test_write_and_validate_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            for name in ["cleaned.md", "chunks.json", "tables.json", "blocks.json", "quality_report.json"]:
                (artifact_dir / name).write_text("{}", encoding="utf-8")

            record = DocumentRecord(
                doc_id="doc_1",
                kb_id="default",
                file_name="sample.pdf",
                file_ext="pdf",
                original_path="/tmp/sample.pdf",
                artifact_dir=artifact_dir.as_posix(),
                parser_engine=ParserEngine.MINERU,
                status=DocumentStatus.PARSED,
                parser_version="mineru-3.1.11",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            path = artifact_manifest_service.write_manifest(record)
            self.assertTrue(path.exists())
            manifest = artifact_manifest_service.validate_manifest(artifact_dir)
            self.assertEqual(manifest.doc_id, "doc_1")
            self.assertEqual(manifest.required_files["blocks_json"], "blocks.json")

    def test_validate_manifest_rejects_missing_required_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact_dir = Path(tmpdir) / "artifacts"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            for name in ["cleaned.md", "chunks.json", "tables.json", "blocks.json", "quality_report.json"]:
                (artifact_dir / name).write_text("{}", encoding="utf-8")

            record = DocumentRecord(
                doc_id="doc_1",
                kb_id="default",
                file_name="sample.pdf",
                file_ext="pdf",
                original_path="/tmp/sample.pdf",
                artifact_dir=artifact_dir.as_posix(),
                parser_engine=ParserEngine.MINERU,
                status=DocumentStatus.PARSED,
                parser_version="mineru-3.1.11",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            artifact_manifest_service.write_manifest(record)
            (artifact_dir / "tables.json").unlink()

            with self.assertRaises(FileNotFoundError):
                artifact_manifest_service.validate_manifest(artifact_dir)


if __name__ == "__main__":
    unittest.main()
