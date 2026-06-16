"""Lightweight pre-parse PDF diagnostics.

The profile is document metadata only. It does not create or repair parser
artifacts and must not decide whether indexing is allowed.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


class PdfProfileService:
    profile_version = "pdf_profile_v1"

    def profile_pdf(self, original_path: str | Path, *, file_size: int | None = None) -> dict[str, Any]:
        path = Path(original_path)
        profile: dict[str, Any] = {
            "profile_status": "ok",
            "profile_version": self.profile_version,
            "file_size": file_size if file_size is not None else self._safe_size(path),
            "page_count": None,
            "is_encrypted": None,
            "text_layer_sample_chars": 0,
            "risk_flags": [],
            "generated_at": datetime.now().isoformat(),
        }

        try:
            from pypdf import PdfReader
        except ImportError:
            return {
                **profile,
                "profile_status": "unavailable",
                "risk_flags": ["profile_dependency_missing"],
                "error_type": "ImportError",
                "error_message": "pypdf is not installed",
            }

        reader = PdfReader(str(path))
        is_encrypted = bool(reader.is_encrypted)
        if is_encrypted:
            return {
                **profile,
                "page_count": None,
                "is_encrypted": True,
                "text_layer_sample_chars": 0,
                "risk_flags": ["encrypted"],
            }

        page_count = len(reader.pages)
        sample_chars = 0
        for page in reader.pages[: min(page_count, 3)]:
            text = page.extract_text() or ""
            sample_chars += len(text.strip())

        risk_flags = self._risk_flags(
            page_count=page_count,
            is_encrypted=is_encrypted,
            text_layer_sample_chars=sample_chars,
        )
        return {
            **profile,
            "page_count": page_count,
            "is_encrypted": is_encrypted,
            "text_layer_sample_chars": sample_chars,
            "risk_flags": risk_flags,
        }

    def _risk_flags(
        self,
        *,
        page_count: int,
        is_encrypted: bool,
        text_layer_sample_chars: int,
    ) -> list[str]:
        flags: list[str] = []
        if page_count == 0:
            flags.append("empty_pdf")
        if is_encrypted:
            flags.append("encrypted")
        elif text_layer_sample_chars == 0:
            flags.append("scanned_or_no_text_layer")
        elif text_layer_sample_chars < 80:
            flags.append("low_text_layer")
        else:
            flags.append("native_text")
        return flags

    def _safe_size(self, path: Path) -> int | None:
        try:
            return path.stat().st_size
        except OSError:
            return None


pdf_profile_service = PdfProfileService()
