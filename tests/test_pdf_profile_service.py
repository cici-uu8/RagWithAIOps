import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from app.services.pdf_profile_service import PdfProfileService


class PdfProfileServiceTests(unittest.TestCase):
    def test_profile_blank_pdf_reports_page_count_and_no_text_layer_risk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            with path.open("wb") as output:
                writer.write(output)

            profile = PdfProfileService().profile_pdf(path, file_size=path.stat().st_size)

        self.assertEqual(profile["profile_status"], "ok")
        self.assertEqual(profile["page_count"], 1)
        self.assertFalse(profile["is_encrypted"])
        self.assertEqual(profile["text_layer_sample_chars"], 0)
        self.assertEqual(profile["risk_flags"], ["scanned_or_no_text_layer"])

    def test_profile_encrypted_pdf_reports_encrypted_without_page_access(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "encrypted.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.encrypt("secret")
            with path.open("wb") as output:
                writer.write(output)

            profile = PdfProfileService().profile_pdf(path, file_size=path.stat().st_size)

        self.assertEqual(profile["profile_status"], "ok")
        self.assertIsNone(profile["page_count"])
        self.assertTrue(profile["is_encrypted"])
        self.assertEqual(profile["text_layer_sample_chars"], 0)
        self.assertEqual(profile["risk_flags"], ["encrypted"])


if __name__ == "__main__":
    unittest.main()
