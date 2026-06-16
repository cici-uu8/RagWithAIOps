"""Ingestion workflow result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DirectoryIngestionResult:
    """Result returned after a directory is submitted through the ingestion layer."""

    success: bool = False
    directory_path: str = ""
    kb_id: str = ""
    recursive: bool = True
    total_files: int = 0
    success_count: int = 0
    queued_count: int = 0
    fail_count: int = 0
    document_ids: list[str] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    error_message: str = ""
    failed_files: dict[str, str] = field(default_factory=dict)

    def increment_success_count(self) -> None:
        self.success_count += 1

    def increment_fail_count(self) -> None:
        self.fail_count += 1

    def add_failed_file(self, file_path: str, error: str) -> None:
        self.failed_files[file_path] = error

    def get_duration_ms(self) -> int:
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "directory_path": self.directory_path,
            "kb_id": self.kb_id,
            "recursive": self.recursive,
            "total_files": self.total_files,
            "success_count": self.success_count,
            "queued_count": self.queued_count,
            "fail_count": self.fail_count,
            "duration_ms": self.get_duration_ms(),
            "error_message": self.error_message,
            "failed_files": self.failed_files,
            "document_ids": self.document_ids,
        }
