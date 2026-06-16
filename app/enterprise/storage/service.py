"""Local StorageService inspired by WeKnora's provider:// file boundary."""

from __future__ import annotations

from pathlib import Path

from app.enterprise.storage.models import StoredObject


class LocalStorageService:
    """Store objects under a local base directory and expose local:// URIs.

    New uploads use ``local://`` provider URIs. Reads keep legacy absolute-path
    fallback so existing DocumentRecord.original_path values remain usable.
    """

    provider = "local"
    scheme = "local://"

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).resolve()

    def save_bytes(self, *, relative_path: str, content: bytes) -> StoredObject:
        target = self._resolve_relative_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        normalized_relative = self._normalize_relative_path(relative_path)
        return StoredObject(
            storage_uri=f"{self.scheme}{normalized_relative}",
            local_path=target.as_posix(),
            provider=self.provider,
            relative_path=normalized_relative,
        )

    def ensure_directory(self, relative_path: str) -> str:
        target = self._resolve_relative_path(relative_path)
        target.mkdir(parents=True, exist_ok=True)
        return target.as_posix()

    def read_bytes(self, file_ref: str) -> bytes:
        return self.resolve_path(file_ref).read_bytes()

    def exists(self, file_ref: str) -> bool:
        return self.resolve_path(file_ref).exists()

    def resolve_path(self, file_ref: str) -> Path:
        if file_ref.startswith(self.scheme):
            relative = file_ref.removeprefix(self.scheme)
            return self._resolve_relative_path(relative)

        candidate = Path(file_ref)
        if candidate.is_absolute():
            return candidate
        return self._resolve_relative_path(file_ref)

    def _resolve_relative_path(self, relative_path: str) -> Path:
        normalized = self._normalize_relative_path(relative_path)
        target = (self.base_dir / normalized).resolve()
        if not self._is_under_base(target):
            raise ValueError(f"storage path escapes base_dir: {relative_path}")
        return target

    def _normalize_relative_path(self, relative_path: str) -> str:
        clean = Path(relative_path).as_posix().strip("/")
        if not clean or clean == ".":
            raise ValueError("relative_path must not be empty")
        return clean

    def _is_under_base(self, path: Path) -> bool:
        try:
            path.relative_to(self.base_dir)
            return True
        except ValueError:
            return False
