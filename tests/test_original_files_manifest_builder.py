import tempfile
import unittest
from pathlib import Path


class OriginalFilesManifestBuilderTests(unittest.TestCase):
    def test_build_manifest_skips_hidden_archives_and_unsupported_logs(self):
        from scripts.knowledge_assets.import_original_files import (
            build_manifest,
            write_manifest_files,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_root = root / "原始文件"
            process_dir = source_root / "07_部门知识库" / "流程与数字化部知识库"
            craft_dir = source_root / "07_部门知识库" / "工艺部知识库"
            logs_dir = source_root / "03_日志与告警样例"
            process_dir.mkdir(parents=True)
            craft_dir.mkdir(parents=True)
            logs_dir.mkdir(parents=True)
            (process_dir / "中车长客数字化转型.md").write_text("数字化转型资料", encoding="utf-8")
            (craft_dir / "线上故障处理_现场设备工艺版.pdf").write_bytes(b"%PDF-1.4\n")
            (logs_dir / "OpenStack_2k.log").write_text("unsupported", encoding="utf-8")
            (source_root / ".DS_Store").write_text("", encoding="utf-8")
            (source_root / "archive.zip").write_bytes(b"zip")

            rows = build_manifest(source_root)
            output_dir = root / "data" / "knowledge_ingestion"
            write_manifest_files(rows, output_dir)

            self.assertEqual([row.relative_path for row in rows], [
                "07_部门知识库/工艺部知识库/线上故障处理_现场设备工艺版.pdf",
                "07_部门知识库/流程与数字化部知识库/中车长客数字化转型.md",
            ])
            self.assertEqual(rows[0].kb_id, "craft_dept")
            self.assertEqual(rows[1].kb_id, "process_digital_dept")
            self.assertEqual(rows[0].review_status, "pending")
            self.assertTrue((output_dir / "original_files_manifest.tsv").exists())
            self.assertTrue((output_dir / "original_files_manifest_review.tsv").exists())
            self.assertTrue((output_dir / "original_files_manifest.json").exists())

    def test_existing_review_status_is_preserved_when_rebuilding(self):
        from scripts.knowledge_assets.import_original_files import build_manifest, write_review_tsv

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_root = root / "原始文件"
            source_root.mkdir()
            (source_root / "runbook.md").write_text("runbook", encoding="utf-8")
            initial_rows = build_manifest(source_root)
            review_path = root / "review.tsv"
            review_path.write_text(
                "asset_id\treview_status\tkb_id\timport_enabled\tnotes\n"
                f"{initial_rows[0].asset_id}\tapproved\tprocess_digital_dept\ttrue\tseed\n",
                encoding="utf-8",
            )

            rows = build_manifest(source_root, review_path=review_path)
            write_review_tsv(rows, review_path)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].review_status, "approved")
            self.assertTrue(rows[0].import_enabled)
            self.assertIn("approved", review_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
