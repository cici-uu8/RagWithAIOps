"""Citation verifier that trusts structured source_ref only."""

from __future__ import annotations

from typing import Any

from app.enterprise.context import RequestContext
from app.enterprise.verifiers.base import BaseVerifier
from app.enterprise.verifiers.models import (
    VerificationFinding,
    VerificationResult,
    VerificationStatus,
)
from app.services.chunk_evidence_mapper import ChunkEvidenceMapper


class CitationVerifier(BaseVerifier):
    name = "CitationVerifier"

    def verify(self, context: RequestContext, payload: dict[str, Any]) -> VerificationResult:
        del context
        response = payload.get("response") or payload.get("retrieval_response")
        allowed_document_ids = {str(item) for item in payload.get("allowed_document_ids", [])}
        results = _results(response)
        findings: list[VerificationFinding] = []

        for index, result in enumerate(results):
            source_ref = _value(result, "source_ref")
            if source_ref is None:
                findings.append(
                    self._finding(
                        "citation_source_ref_missing",
                        "引用缺少结构化 source_ref，不能只依赖展示文本。",
                        metadata={"result_index": index},
                    )
                )
                continue

            missing_source_ref_fields = [
                f"source_ref.{field}"
                for field in ChunkEvidenceMapper.REQUIRED_SOURCE_REF_FIELDS
                if not _has_value(_value(source_ref, field))
            ]
            if missing_source_ref_fields:
                findings.append(
                    self._finding(
                        "citation_source_ref_incomplete",
                        "引用缺少 mapper 必需的结构化证据字段。",
                        metadata={
                            "result_index": index,
                            "missing_fields": missing_source_ref_fields,
                        },
                    )
                )
                continue

            raw_source_doc_id = _value(source_ref, "doc_id")
            evidence = ChunkEvidenceMapper.from_retrieval_result(result)
            missing_fields = ChunkEvidenceMapper.validate_required_fields(evidence)
            if missing_fields:
                findings.append(
                    self._finding(
                        "citation_source_ref_incomplete",
                        "引用缺少 mapper 必需的结构化证据字段。",
                        metadata={
                            "result_index": index,
                            "missing_fields": missing_fields,
                        },
                    )
                )
                continue

            source_doc_id = raw_source_doc_id
            if not source_doc_id:
                findings.append(
                    self._finding(
                        "citation_source_ref_missing",
                        "引用缺少结构化 source_ref，不能只依赖展示文本。",
                        metadata={"result_index": index},
                    )
                )
                continue

            if allowed_document_ids and source_doc_id not in allowed_document_ids:
                findings.append(
                    self._finding(
                        "citation_source_not_authorized",
                        "引用来源不在授权文档集合内。",
                        metadata={
                            "result_index": index,
                            "source_doc_id": source_doc_id,
                            "allowed_document_ids": sorted(allowed_document_ids),
                        },
                    )
                )
                continue

            result_doc_id = _value(result, "doc_id")
            if result_doc_id and result_doc_id != source_doc_id:
                findings.append(
                    self._finding(
                        "citation_source_ref_mismatch",
                        "检索结果 doc_id 与结构化 source_ref.doc_id 不一致。",
                        metadata={
                            "result_index": index,
                            "result_doc_id": result_doc_id,
                            "source_doc_id": source_doc_id,
                        },
                    )
                )

        if findings:
            return self._result(
                VerificationStatus.FAILED,
                findings,
                metadata={"result_count": len(results)},
            )
        return self._result(
            VerificationStatus.PASSED,
            metadata={"result_count": len(results)},
        )


def _results(response: Any) -> list[Any]:
    if response is None:
        return []
    if isinstance(response, dict):
        return list(response.get("results") or [])
    return list(getattr(response, "results", []) or [])


def _value(item: Any, key: str) -> Any:
    if item is None:
        return None
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True
