"""Schema-bound extraction of L1 atom candidates from L0 evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_qwq import ChatQwen
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.config import config
from app.models.memory import MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_atom import L1Atom, L1AtomExtractionMethod, L1AtomType
from app.services.memory_evidence_store import MemoryEvidenceStore, memory_evidence_store
from app.services.memory_store import MemoryStore, memory_store


class L1AtomExtractionEnvelope(BaseModel):
    """LLM-facing extraction envelope."""

    atoms: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionMetrics(BaseModel):
    """Counters for P7.2 extraction outcomes."""

    extraction_attempt_count: int = 0
    extraction_success_count: int = 0
    extraction_schema_failure_count: int = 0
    extraction_empty_count: int = 0
    evidence_integrity_failure_count: int = 0
    skipped_incomplete_evidence_count: int = 0
    transient_failed_count: int = 0

    def snapshot(self) -> dict[str, int]:
        return self.model_dump()


EXTRACTION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                You extract only traceable oncall memory atoms from one L0 evidence bundle.

                Rules:
                - Use only the supplied evidence.
                - Do not invent facts not supported by the evidence.
                - Return JSON with one key: atoms.
                - Each atom must include evidence_refs and claim.
                - Prefer fewer atoms over speculative atoms.
                - Supported atom types:
                  root_cause_observation
                  check_observation
                  remediation_observation
                  negative_observation
                  config_or_deploy_change
                """
            ).strip(),
        ),
        ("user", "{evidence_json}"),
    ]
)


class MemoryExtractorService:
    """Extract L1 atom candidates from L0 evidence without auto-promotion."""

    def __init__(
        self,
        *,
        evidence_store: MemoryEvidenceStore = memory_evidence_store,
        store: MemoryStore = memory_store,
        extraction_chain: Any | None = None,
        schema_failure_pause_threshold: float = 0.2,
        schema_failure_pause_min_attempts: int = 5,
        transient_retry_count: int = 1,
    ):
        if schema_failure_pause_threshold <= 0 or schema_failure_pause_threshold > 1:
            raise ValueError("schema_failure_pause_threshold must be in (0, 1]")
        if schema_failure_pause_min_attempts <= 0:
            raise ValueError("schema_failure_pause_min_attempts must be positive")
        if transient_retry_count < 0:
            raise ValueError("transient_retry_count must be non-negative")

        self.evidence_store = evidence_store
        self.store = store
        self.extraction_chain = extraction_chain or self._build_default_chain()
        self.schema_failure_pause_threshold = schema_failure_pause_threshold
        self.schema_failure_pause_min_attempts = schema_failure_pause_min_attempts
        self.transient_retry_count = transient_retry_count
        self.metrics = ExtractionMetrics()
        self.outcomes: dict[str, dict[str, Any]] = {}
        self.llm_extraction_paused = False
        self.pause_reason: str | None = None

    def extract_atoms_from_evidence(self, evidence_id: str) -> list[L1Atom]:
        """Extract zero or more L1 atoms from one L0 evidence id."""

        self.metrics.extraction_attempt_count += 1
        evidence = self.evidence_store.get(evidence_id)
        if evidence is None:
            self.metrics.evidence_integrity_failure_count += 1
            return self._record_outcome(
                evidence_id,
                outcome="evidence_integrity_failure",
                atoms=[],
                details={"reason": "evidence_not_found"},
            )

        integrity = self.evidence_store.check_integrity(evidence_id)
        if not integrity.get("ok"):
            self.metrics.evidence_integrity_failure_count += 1
            return self._record_outcome(
                evidence_id,
                outcome="evidence_integrity_failure",
                atoms=[],
                details=integrity,
            )

        if self._should_skip_incomplete_evidence(evidence):
            self.metrics.skipped_incomplete_evidence_count += 1
            return self._record_outcome(
                evidence_id,
                outcome="skipped_incomplete_evidence",
                atoms=[],
                details={
                    "diagnosis_status": evidence.diagnosis_status,
                    "has_final_response_ref": evidence.final_response_ref is not None,
                    "has_key_events_ref": evidence.key_events_ref is not None,
                },
            )

        if self._should_pause_llm_extraction():
            atoms = self._extract_rule_v1(evidence)
            if not atoms:
                self.metrics.extraction_empty_count += 1
                return self._record_outcome(
                    evidence_id,
                    outcome="empty",
                    atoms=[],
                    details={"extraction_method": L1AtomExtractionMethod.RULE_V1.value},
                )
            stored = self._store_atoms(atoms)
            self.metrics.extraction_success_count += 1
            return self._record_outcome(
                evidence_id,
                outcome="success",
                atoms=stored,
                details={"extraction_method": L1AtomExtractionMethod.RULE_V1.value},
            )

        raw_result = None
        last_exc: Exception | None = None
        for attempt in range(self.transient_retry_count + 1):
            try:
                raw_result = self._invoke_extraction_chain(evidence)
                last_exc = None
                break
            except Exception as exc:  # pragma: no cover - exercised through tests via fake chains
                last_exc = exc
                if self._looks_like_schema_failure(exc):
                    self.metrics.extraction_schema_failure_count += 1
                    self._maybe_pause_llm_extraction()
                    return self._record_outcome(
                        evidence_id,
                        outcome="schema_failed",
                        atoms=[],
                        details={"error_type": type(exc).__name__, "error": str(exc)},
                    )
                if attempt < self.transient_retry_count:
                    logger.warning(
                        "L1 extraction transient failure evidence_id={} attempt={}/{} error={}",
                        evidence_id,
                        attempt + 1,
                        self.transient_retry_count + 1,
                        exc,
                    )
                    continue
                self.metrics.transient_failed_count += 1
                return self._record_outcome(
                    evidence_id,
                    outcome="transient_failed",
                    atoms=[],
                    details={"error_type": type(exc).__name__, "error": str(exc)},
                )

        if last_exc is not None and raw_result is None:
            self.metrics.transient_failed_count += 1
            return self._record_outcome(
                evidence_id,
                outcome="transient_failed",
                atoms=[],
                details={"error_type": type(last_exc).__name__, "error": str(last_exc)},
            )

        raw_atoms = self._coerce_raw_atoms(raw_result)
        if not raw_atoms:
            self.metrics.extraction_empty_count += 1
            return self._record_outcome(
                evidence_id,
                outcome="empty",
                atoms=[],
                details={"extraction_method": L1AtomExtractionMethod.SCHEMA_LLM_V1.value},
            )

        valid_atoms: list[L1Atom] = []
        schema_failures = 0
        for index, raw_atom in enumerate(raw_atoms):
            try:
                valid_atoms.append(
                    self._build_atom(
                        raw_atom,
                        evidence=evidence,
                        extraction_method=L1AtomExtractionMethod.SCHEMA_LLM_V1,
                        atom_index=index,
                    )
                )
            except (ValidationError, ValueError, TypeError) as exc:
                schema_failures += 1
                logger.warning(
                    "L1 atom schema validation failed evidence_id={} index={} error={}",
                    evidence_id,
                    index,
                    exc,
                )

        if schema_failures:
            self.metrics.extraction_schema_failure_count += schema_failures
            self._maybe_pause_llm_extraction()

        if not valid_atoms:
            outcome = "schema_failed" if schema_failures else "empty"
            if outcome == "empty":
                self.metrics.extraction_empty_count += 1
            return self._record_outcome(
                evidence_id,
                outcome=outcome,
                atoms=[],
                details={
                    "extraction_method": L1AtomExtractionMethod.SCHEMA_LLM_V1.value,
                    "schema_failure_count": schema_failures,
                },
            )

        stored = self._store_atoms(valid_atoms)
        self.metrics.extraction_success_count += 1
        return self._record_outcome(
            evidence_id,
            outcome="success",
            atoms=stored,
            details={
                "extraction_method": L1AtomExtractionMethod.SCHEMA_LLM_V1.value,
                "schema_failure_count": schema_failures,
            },
        )

    def get_metrics(self) -> dict[str, int]:
        return self.metrics.snapshot()

    def _invoke_extraction_chain(self, evidence) -> Any:
        payload = {
            "evidence_json": json.dumps(self._build_prompt_payload(evidence), ensure_ascii=False, sort_keys=True),
        }
        if hasattr(self.extraction_chain, "invoke"):
            return self.extraction_chain.invoke(payload)
        if callable(self.extraction_chain):
            return self.extraction_chain(payload)
        raise TypeError("extraction_chain must expose invoke() or be callable")

    def _build_default_chain(self):
        llm = ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            base_url=config.dashscope_api_base,
            temperature=0,
            streaming=False,
        )
        return EXTRACTION_PROMPT | llm.with_structured_output(
            L1AtomExtractionEnvelope,
            method="json_mode",
        )

    def _build_prompt_payload(self, evidence) -> dict[str, Any]:
        return {
            "evidence_id": evidence.evidence_id,
            "owner_id": evidence.owner_id,
            "session_id": evidence.session_id,
            "query": evidence.query,
            "service": evidence.service,
            "alert_name": evidence.alert_name,
            "environment": evidence.environment,
            "diagnosis_status": evidence.diagnosis_status,
            "created_at": evidence.created_at.isoformat(),
            "final_response_preview": evidence.final_response_preview,
            "final_response": self._load_ref_payload(evidence.final_response_ref, fallback=evidence.final_response_preview),
            "plan": self._safe_json_loads(evidence.plan_json, fallback=[]),
            "past_steps": self._load_ref_payload(evidence.past_steps_ref, fallback=[]),
            "key_events": self._load_ref_payload(evidence.key_events_ref, fallback=[]),
            "tool_results": self._load_ref_payload(evidence.tool_results_ref, fallback=[]),
            "memory_observation": self._safe_json_loads(evidence.memory_observation_json, fallback=None),
            "refs_manifest": self._safe_json_loads(evidence.refs_manifest_json, fallback={"refs": []}),
        }

    def _coerce_raw_atoms(self, raw_result: Any) -> list[dict[str, Any]]:
        if raw_result is None:
            return []
        if isinstance(raw_result, L1AtomExtractionEnvelope):
            return [atom for atom in raw_result.atoms if isinstance(atom, dict)]
        if isinstance(raw_result, dict):
            atoms = raw_result.get("atoms", [])
            if isinstance(atoms, list):
                return [atom for atom in atoms if isinstance(atom, dict)]
            return []
        if isinstance(raw_result, list):
            return [atom for atom in raw_result if isinstance(atom, dict)]
        if hasattr(raw_result, "model_dump"):
            dumped = raw_result.model_dump()
            atoms = dumped.get("atoms", [])
            if isinstance(atoms, list):
                return [atom for atom in atoms if isinstance(atom, dict)]
        return []

    def _build_atom(
        self,
        raw_atom: dict[str, Any],
        *,
        evidence,
        extraction_method: L1AtomExtractionMethod,
        atom_index: int,
    ) -> L1Atom:
        atom_type = self._coerce_atom_type(raw_atom.get("atom_type"))
        evidence_refs = self._coerce_evidence_refs(raw_atom.get("evidence_refs"), evidence.evidence_id)
        service = self._choose_text(raw_atom.get("service"), evidence.service)
        alert_name = self._choose_text(raw_atom.get("alert_name"), evidence.alert_name)
        environment = self._choose_text(raw_atom.get("environment"), evidence.environment)
        claim = self._choose_text(raw_atom.get("claim"))
        atom_id = self._build_atom_id(
            evidence.evidence_id,
            atom_type,
            claim,
            service=service,
            alert_name=alert_name,
            atom_index=atom_index,
            raw_atom=raw_atom,
        )
        payload = {
            "atom_id": atom_id,
            "owner_id": evidence.owner_id,
            "evidence_id": evidence.evidence_id,
            "atom_type": atom_type.value,
            "service": service,
            "alert_name": alert_name,
            "environment": environment,
            "claim": claim,
            "root_cause": self._choose_text(raw_atom.get("root_cause")),
            "check_name": self._choose_text(raw_atom.get("check_name")),
            "remediation": self._choose_text(raw_atom.get("remediation")),
            "negates_memory_id": self._choose_text(raw_atom.get("negates_memory_id")),
            "valid_from": self._parse_datetime(raw_atom.get("valid_from")),
            "valid_until": self._parse_datetime(raw_atom.get("valid_until")),
            "confidence": self._coerce_confidence(raw_atom.get("confidence")),
            "evidence_refs": evidence_refs,
            "extraction_method": extraction_method.value,
            "status": "candidate",
        }
        return L1Atom.model_validate(payload)

    def _store_atoms(self, atoms: list[L1Atom]) -> list[L1Atom]:
        stored: list[L1Atom] = []
        for atom in atoms:
            record = self._atom_to_memory_record(atom)
            self.store.upsert(record)
            stored.append(atom)
        return stored

    def _atom_to_memory_record(self, atom: L1Atom) -> MemoryRecord:
        summary = self._truncate(atom.claim, 240)
        content = self._truncate(atom.claim, 800)
        evidence = {
            "evidence_type": "l1_atom_candidate",
            "l0_evidence_id": atom.evidence_id,
            "l0_evidence_refs": list(atom.evidence_refs),
            "atom_type": atom.atom_type.value,
            "extraction_method": atom.extraction_method.value,
            "confidence": atom.confidence,
        }
        return MemoryRecord(
            memory_id=atom.atom_id,
            owner_id=atom.owner_id,
            namespace="memory://oncall/l1-atoms",
            memory_type=MemoryType.L1_ATOM,
            content=content,
            summary=summary,
            payload=atom,
            source="l0-evidence-schema-extractor, NOT reviewed active memory",
            evidence=evidence,
            status=MemoryStatus.CANDIDATE,
            tags=["l1_atom", atom.atom_type.value, atom.extraction_method.value],
        )

    def _record_outcome(
        self,
        evidence_id: str,
        *,
        outcome: str,
        atoms: list[L1Atom],
        details: dict[str, Any],
    ) -> list[L1Atom]:
        self.outcomes[evidence_id] = {
            "outcome": outcome,
            "atom_ids": [atom.atom_id for atom in atoms],
            "details": details,
            "metrics": self.get_metrics(),
        }
        logger.info(
            "L1 extraction outcome evidence_id={} outcome={} atoms={}",
            evidence_id,
            outcome,
            len(atoms),
        )
        return atoms

    def _should_skip_incomplete_evidence(self, evidence) -> bool:
        return (
            evidence.diagnosis_status != "complete"
            or evidence.final_response_ref is None
            or evidence.key_events_ref is None
        )

    def _should_pause_llm_extraction(self) -> bool:
        if self.llm_extraction_paused:
            return True
        if self.metrics.extraction_attempt_count < self.schema_failure_pause_min_attempts:
            return False
        failure_rate = self._schema_failure_rate()
        if failure_rate > self.schema_failure_pause_threshold:
            self.llm_extraction_paused = True
            self.pause_reason = (
                f"schema failure rate {failure_rate:.2%} exceeded threshold "
                f"{self.schema_failure_pause_threshold:.2%}"
            )
            logger.warning("Pausing LLM extraction: {}", self.pause_reason)
            return True
        return False

    def _maybe_pause_llm_extraction(self) -> None:
        if self.metrics.extraction_attempt_count < self.schema_failure_pause_min_attempts:
            return
        if self._schema_failure_rate() > self.schema_failure_pause_threshold:
            self.llm_extraction_paused = True
            self.pause_reason = (
                f"schema failure rate {self._schema_failure_rate():.2%} exceeded threshold "
                f"{self.schema_failure_pause_threshold:.2%}"
            )
            logger.warning("Pausing LLM extraction: {}", self.pause_reason)

    def _schema_failure_rate(self) -> float:
        if self.metrics.extraction_attempt_count <= 0:
            return 0.0
        return self.metrics.extraction_schema_failure_count / self.metrics.extraction_attempt_count

    def _looks_like_schema_failure(self, exc: Exception) -> bool:
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        return any(
            marker in name or marker in text
            for marker in ("validation", "schema", "outputparser", "pydantic")
        )

    def _extract_rule_v1(self, evidence) -> list[L1Atom]:
        text_parts = [
            evidence.query,
            evidence.final_response_preview,
            self._load_ref_payload(evidence.final_response_ref, fallback=""),
            json.dumps(self._safe_json_loads(evidence.memory_observation_json, fallback={}), ensure_ascii=False),
        ]
        combined = "\n".join(str(part) for part in text_parts if str(part).strip())
        atoms: list[L1Atom] = []

        root_match = re.search(r"(?:root cause|根因)[:：]\s*(.+)", combined, re.IGNORECASE)
        if root_match and (evidence.service or evidence.alert_name):
            claim = self._truncate(f"{evidence.service or evidence.alert_name} 的当前根因是 {root_match.group(1).strip()}", 240)
            atoms.append(
                self._build_atom_from_values(
                    evidence=evidence,
                    atom_type=L1AtomType.ROOT_CAUSE_OBSERVATION,
                    claim=claim,
                    evidence_refs=[evidence.evidence_id],
                    extraction_method=L1AtomExtractionMethod.RULE_V1,
                    root_cause=root_match.group(1).strip(),
                )
            )

        if re.search(r"(rollback|revert|回滚|恢复)", combined, re.IGNORECASE):
            claim = self._truncate(
                f"{evidence.service or evidence.alert_name or evidence.evidence_id} 可通过 rollback recent deploy 修复",
                240,
            )
            atoms.append(
                self._build_atom_from_values(
                    evidence=evidence,
                    atom_type=L1AtomType.REMEDIATION_OBSERVATION,
                    claim=claim,
                    evidence_refs=[evidence.evidence_id],
                    extraction_method=L1AtomExtractionMethod.RULE_V1,
                    remediation="rollback recent deploy",
                )
            )

        if re.search(r"(not|不是|不再是|already fixed|已修复|已解决)", combined, re.IGNORECASE):
            claim = self._truncate(
                f"{evidence.service or evidence.alert_name or evidence.evidence_id} 的旧根因假设已被当前证据否定",
                240,
            )
            atoms.append(
                self._build_atom_from_values(
                    evidence=evidence,
                    atom_type=L1AtomType.NEGATIVE_OBSERVATION,
                    claim=claim,
                    evidence_refs=[evidence.evidence_id],
                    extraction_method=L1AtomExtractionMethod.RULE_V1,
                )
            )

        if re.search(r"(config|configuration|deploy|deployment|配置|发布|变更|更新)", combined, re.IGNORECASE):
            claim = self._truncate(
                f"{evidence.service or evidence.alert_name or evidence.evidence_id} 的配置或发布状态在当前诊断后已发生变化",
                240,
            )
            atoms.append(
                self._build_atom_from_values(
                    evidence=evidence,
                    atom_type=L1AtomType.CONFIG_OR_DEPLOY_CHANGE,
                    claim=claim,
                    evidence_refs=[evidence.evidence_id],
                    extraction_method=L1AtomExtractionMethod.RULE_V1,
                )
            )

        check_match = re.search(r"(?:check|检查)[:：]?\s*(.+)", combined, re.IGNORECASE)
        if check_match:
            check_name = self._truncate(check_match.group(1).strip(), 120)
            claim = self._truncate(
                f"{evidence.service or evidence.alert_name or evidence.evidence_id} 场景下必须先查 {check_name}",
                240,
            )
            atoms.append(
                self._build_atom_from_values(
                    evidence=evidence,
                    atom_type=L1AtomType.CHECK_OBSERVATION,
                    claim=claim,
                    evidence_refs=[evidence.evidence_id],
                    extraction_method=L1AtomExtractionMethod.RULE_V1,
                    check_name=check_name,
                )
            )

        return atoms

    def _build_atom_from_values(
        self,
        *,
        evidence,
        atom_type: L1AtomType,
        claim: str,
        evidence_refs: list[str],
        extraction_method: L1AtomExtractionMethod,
        root_cause: str | None = None,
        check_name: str | None = None,
        remediation: str | None = None,
    ) -> L1Atom:
        atom_id = self._build_atom_id(
            evidence.evidence_id,
            atom_type,
            claim,
            service=evidence.service,
            alert_name=evidence.alert_name,
            atom_index=0,
            raw_atom={
                "root_cause": root_cause,
                "check_name": check_name,
                "remediation": remediation,
            },
        )
        return L1Atom.model_validate(
            {
                "atom_id": atom_id,
                "owner_id": evidence.owner_id,
                "evidence_id": evidence.evidence_id,
                "atom_type": atom_type.value,
                "service": evidence.service,
                "alert_name": evidence.alert_name,
                "environment": evidence.environment,
                "claim": claim,
                "root_cause": root_cause,
                "check_name": check_name,
                "remediation": remediation,
                "negates_memory_id": None,
                "valid_from": evidence.created_at,
                "valid_until": None,
                "confidence": 0.55,
                "evidence_refs": evidence_refs,
                "extraction_method": extraction_method.value,
                "status": "candidate",
            }
        )

    def _coerce_atom_type(self, value: Any) -> L1AtomType:
        if isinstance(value, L1AtomType):
            return value
        if value is None:
            raise ValueError("atom_type is required")
        return L1AtomType(str(value))

    def _coerce_evidence_refs(self, value: Any, evidence_id: str) -> list[str]:
        refs: list[str] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    stripped = item.strip()
                    if stripped:
                        refs.append(stripped)
                elif isinstance(item, dict):
                    ref = str(item.get("evidence_id", "")).strip()
                    if ref:
                        refs.append(ref)
        if evidence_id not in refs:
            raise ValueError("evidence_refs must include the source evidence_id")
        return refs

    def _coerce_confidence(self, value: Any) -> float:
        if value is None or str(value).strip() == "":
            return 0.5
        return float(value)

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        return datetime.fromisoformat(text)

    def _choose_text(self, *values: Any) -> str | None:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _build_atom_id(
        self,
        evidence_id: str,
        atom_type: L1AtomType,
        claim: str,
        *,
        service: str | None,
        alert_name: str | None,
        atom_index: int,
        raw_atom: dict[str, Any],
    ) -> str:
        digest_input = json.dumps(
            {
                "evidence_id": evidence_id,
                "atom_type": atom_type.value,
                "claim": claim,
                "service": service,
                "alert_name": alert_name,
                "atom_index": atom_index,
                "root_cause": raw_atom.get("root_cause"),
                "check_name": raw_atom.get("check_name"),
                "remediation": raw_atom.get("remediation"),
                "negates_memory_id": raw_atom.get("negates_memory_id"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:16]
        return f"l1_atom_{digest}"

    def _load_ref_payload(self, ref, *, fallback: Any) -> Any:
        if ref is None:
            return fallback
        path = getattr(ref, "path", None)
        if not path:
            return fallback
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return fallback
        payloads: list[Any] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                payloads.append(json.loads(line).get("payload"))
            except json.JSONDecodeError:
                payloads.append(line)
        if not payloads:
            return fallback
        if len(payloads) == 1:
            return payloads[0]
        return payloads

    def _safe_json_loads(self, value: str | None, *, fallback: Any) -> Any:
        if value is None or not str(value).strip():
            return fallback
        try:
            return json.loads(value)
        except Exception:
            return fallback

    def _truncate(self, value: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."


memory_extractor_service = MemoryExtractorService()
