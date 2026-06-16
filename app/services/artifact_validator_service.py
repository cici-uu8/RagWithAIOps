"""Warning-only validator for parsed document artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactValidationIssue:
    severity: str
    code: str
    path: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactValidationReport:
    artifact_dir: str
    status: str
    parser_version: str = ""
    postprocess_version: str = ""
    issues: list[ArtifactValidationIssue] = field(default_factory=list)

    @property
    def issue_counts(self) -> dict[str, int]:
        counts = {"warning": 0, "fatal_candidate": 0}
        for issue in self.issues:
            counts[issue.severity] = counts.get(issue.severity, 0) + 1
        return counts


class ArtifactValidatorService:
    """Validate artifact shape without changing runtime fatal rules."""

    MANIFEST_FILENAME = "artifact_manifest.json"
    REQUIRED_DEFAULTS = {
        "cleaned_md": "cleaned.md",
        "chunks_json": "chunks.json",
        "tables_json": "tables.json",
        "blocks_json": "blocks.json",
        "quality_report_json": "quality_report.json",
    }

    def validate_artifact_dir(self, artifact_dir: str | Path) -> ArtifactValidationReport:
        base = Path(artifact_dir)
        issues: list[ArtifactValidationIssue] = []
        manifest_payload = self._load_json_object(base / self.MANIFEST_FILENAME, issues)
        required_files = dict(self.REQUIRED_DEFAULTS)
        parser_version = ""
        postprocess_version = ""

        if manifest_payload:
            parser_version = str(manifest_payload.get("parser_version") or "")
            postprocess_version = str(manifest_payload.get("postprocess_version") or "")
            required_files.update(manifest_payload.get("required_files") or {})
            if manifest_payload.get("status") != "parsed":
                issues.append(
                    ArtifactValidationIssue(
                        severity="fatal_candidate",
                        code="manifest_status_not_parsed",
                        path=(base / self.MANIFEST_FILENAME).as_posix(),
                        message="artifact manifest status is not parsed",
                        details={"status": manifest_payload.get("status")},
                    )
                )

        for key, relative_path in required_files.items():
            target = base / str(relative_path)
            if not target.exists():
                issues.append(
                    ArtifactValidationIssue(
                        severity="fatal_candidate",
                        code="required_file_missing",
                        path=target.as_posix(),
                        message=f"required artifact file is missing: {key}",
                        details={"key": key},
                    )
                )
                continue
            if key.endswith("_json"):
                payload = self._load_json_payload(target, issues)
                if key == "quality_report_json" and isinstance(payload, dict):
                    self._validate_quality_report(target, payload, issues)

        status = "pass" if not issues else "warning"
        return ArtifactValidationReport(
            artifact_dir=base.as_posix(),
            status=status,
            parser_version=parser_version,
            postprocess_version=postprocess_version,
            issues=issues,
        )

    def _load_json_object(
        self,
        path: Path,
        issues: list[ArtifactValidationIssue],
    ) -> dict[str, Any]:
        if not path.exists():
            issues.append(
                ArtifactValidationIssue(
                    severity="fatal_candidate",
                    code="required_file_missing",
                    path=path.as_posix(),
                    message="required artifact file is missing",
                    details={"key": path.name},
                )
            )
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(
                ArtifactValidationIssue(
                    severity="fatal_candidate",
                    code="invalid_json",
                    path=path.as_posix(),
                    message="artifact JSON is invalid",
                    details={"error": str(exc)},
                )
            )
            return {}
        if not isinstance(payload, dict):
            issues.append(
                ArtifactValidationIssue(
                    severity="fatal_candidate",
                    code="json_not_object",
                    path=path.as_posix(),
                    message="artifact JSON must be an object",
                )
            )
            return {}
        return payload

    def _load_json_payload(
        self,
        path: Path,
        issues: list[ArtifactValidationIssue],
    ) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(
                ArtifactValidationIssue(
                    severity="fatal_candidate",
                    code="invalid_json",
                    path=path.as_posix(),
                    message="artifact JSON is invalid",
                    details={"error": str(exc)},
                )
            )
            return None

    def _validate_quality_report(
        self,
        path: Path,
        payload: dict[str, Any],
        issues: list[ArtifactValidationIssue],
    ) -> None:
        fatal_errors = payload.get("fatal_errors") or []
        if fatal_errors:
            issues.append(
                ArtifactValidationIssue(
                    severity="fatal_candidate",
                    code="quality_report_fatal_errors",
                    path=path.as_posix(),
                    message="quality_report.fatal_errors is not empty",
                    details={"fatal_errors": fatal_errors},
                )
            )
        warnings = payload.get("warnings") or []
        if warnings:
            issues.append(
                ArtifactValidationIssue(
                    severity="warning",
                    code="quality_report_warnings",
                    path=path.as_posix(),
                    message="quality_report.warnings is not empty",
                    details={"warnings": warnings},
                )
            )


artifact_validator_service = ArtifactValidatorService()
