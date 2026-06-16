"""Rule-based conflict detection for P7 layered oncall memory."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.models.memory import (
    AlertPatternPayload,
    MemoryRecord,
    MemoryStatus,
    MemoryType,
    PlanTemplatePayload,
)
from app.models.memory_atom import L1Atom, L1AtomType
from app.models.memory_conflict import MemoryConflictResult, MemoryConflictVerdict
from app.services.memory_store import MemoryStore, memory_store


class ConflictMetrics:
    """Counters for rule-based P7.3 conflict detection."""

    def __init__(self) -> None:
        self.conflict_checked_count = 0
        self.possible_conflict_count = 0
        self.supersession_candidate_count = 0

    def snapshot(self) -> dict[str, int]:
        return {
            "conflict_checked_count": self.conflict_checked_count,
            "possible_conflict_count": self.possible_conflict_count,
            "supersession_candidate_count": self.supersession_candidate_count,
        }


class ConflictDetectorService:
    """Detect whether a fresh L1 atom conflicts with existing active memory."""

    NEGATIVE_MARKERS = (
        "not",
        "no longer",
        "not reproduced",
        "denies",
        "contradicts",
        "fresh check",
        "不是",
        "不再",
        "未复现",
        "没有复现",
        "已修复",
        "已经修复",
        "推翻",
        "否定",
        "不成立",
    )
    CONFIG_DEPLOY_MARKERS = (
        "config",
        "configuration",
        "deploy",
        "deployment",
        "updated",
        "changed",
        "配置",
        "部署",
        "发布",
        "更新",
        "变更",
        "改动",
    )

    def __init__(
        self,
        *,
        store: MemoryStore = memory_store,
        min_confidence: float = 0.5,
    ):
        if min_confidence < 0 or min_confidence > 1:
            raise ValueError("min_confidence must be in [0, 1]")
        self.store = store
        self.min_confidence = min_confidence
        self.metrics = ConflictMetrics()

    def detect_conflicts(self, atom_or_record: L1Atom | MemoryRecord) -> list[MemoryConflictResult]:
        """Return only active memories with a rule-based conflict verdict."""

        atom = self._coerce_atom(atom_or_record)
        candidates = self.store.list_memories(owner_id=atom.owner_id, status=MemoryStatus.ACTIVE)
        results: list[MemoryConflictResult] = []
        for record in candidates:
            result = self.detect_conflict(atom, record)
            if result.verdict != MemoryConflictVerdict.NO_CONFLICT:
                results.append(result)
        return sorted(results, key=lambda result: result.memory_id)

    def detect_conflict(
        self,
        atom_or_record: L1Atom | MemoryRecord,
        existing_memory: MemoryRecord,
    ) -> MemoryConflictResult:
        """Evaluate one fresh atom against one existing memory record."""

        atom = self._coerce_atom(atom_or_record)
        self.metrics.conflict_checked_count += 1
        matched_scope = self._matched_scope(atom, existing_memory)

        if existing_memory.status != MemoryStatus.ACTIVE:
            return self._result(
                atom,
                existing_memory,
                verdict=MemoryConflictVerdict.NO_CONFLICT,
                reason="memory is not active",
                matched_scope=matched_scope,
            )
        if existing_memory.owner_id != atom.owner_id:
            return self._result(
                atom,
                existing_memory,
                verdict=MemoryConflictVerdict.NO_CONFLICT,
                reason="owner scope differs",
                matched_scope=matched_scope,
            )
        if not self._evidence_is_current_enough(atom):
            return self._result(
                atom,
                existing_memory,
                verdict=MemoryConflictVerdict.NO_CONFLICT,
                reason="evidence is not current enough",
                matched_scope=matched_scope,
            )

        if atom.negates_memory_id and atom.negates_memory_id == existing_memory.memory_id:
            return self._counted_result(
                atom,
                existing_memory,
                verdict=MemoryConflictVerdict.SUPERSESSION_CANDIDATE,
                reason="negates_memory_id matched active memory",
                matched_scope=matched_scope,
            )

        if not self._scope_matches(atom, existing_memory):
            return self._result(
                atom,
                existing_memory,
                verdict=MemoryConflictVerdict.NO_CONFLICT,
                reason="scope does not match",
                matched_scope=matched_scope,
            )

        verdict, reason = self._claim_verdict(atom, existing_memory)
        return self._counted_result(
            atom,
            existing_memory,
            verdict=verdict,
            reason=reason,
            matched_scope=matched_scope,
        )

    def get_metrics(self) -> dict[str, int]:
        return self.metrics.snapshot()

    def _claim_verdict(
        self,
        atom: L1Atom,
        existing_memory: MemoryRecord,
    ) -> tuple[MemoryConflictVerdict, str]:
        payload = existing_memory.payload

        if isinstance(payload, AlertPatternPayload):
            return self._alert_pattern_verdict(atom, payload)
        if isinstance(payload, PlanTemplatePayload):
            return self._plan_template_verdict(atom, payload)
        return MemoryConflictVerdict.NO_CONFLICT, "unsupported memory type for P7.3 conflict rules"

    def _alert_pattern_verdict(
        self,
        atom: L1Atom,
        payload: AlertPatternPayload,
    ) -> tuple[MemoryConflictVerdict, str]:
        if atom.atom_type == L1AtomType.ROOT_CAUSE_OBSERVATION and atom.root_cause:
            if _norm(atom.root_cause) != _norm(payload.root_cause):
                return MemoryConflictVerdict.POSSIBLE_CONFLICT, "root cause differs"

        if atom.atom_type == L1AtomType.REMEDIATION_OBSERVATION and atom.remediation and payload.fix:
            if _norm(atom.remediation) != _norm(payload.fix):
                return MemoryConflictVerdict.POSSIBLE_CONFLICT, "remediation/fix differs"

        if atom.atom_type == L1AtomType.NEGATIVE_OBSERVATION:
            if self._claim_denies(atom.claim, payload.root_cause) or self._claim_denies(atom.claim, payload.fix):
                return MemoryConflictVerdict.SUPERSESSION_CANDIDATE, "negative observation denies old claim"

        if atom.atom_type == L1AtomType.CONFIG_OR_DEPLOY_CHANGE and self._has_config_deploy_marker(atom.claim):
            return MemoryConflictVerdict.POSSIBLE_CONFLICT, "config/deploy state changed"

        return MemoryConflictVerdict.NO_CONFLICT, "claim does not contradict active memory"

    def _plan_template_verdict(
        self,
        atom: L1Atom,
        payload: PlanTemplatePayload,
    ) -> tuple[MemoryConflictVerdict, str]:
        if atom.atom_type == L1AtomType.NEGATIVE_OBSERVATION:
            claim = _norm(atom.claim)
            for condition in payload.stop_conditions:
                if _norm(condition) and _norm(condition) in claim and self._has_negative_marker(atom.claim):
                    return (
                        MemoryConflictVerdict.POSSIBLE_CONFLICT,
                        "plan stop condition contradicted by fresh check",
                    )

        if atom.atom_type == L1AtomType.CONFIG_OR_DEPLOY_CHANGE and self._has_config_deploy_marker(atom.claim):
            return MemoryConflictVerdict.POSSIBLE_CONFLICT, "config/deploy state changed"

        return MemoryConflictVerdict.NO_CONFLICT, "claim does not contradict plan template"

    def _scope_matches(self, atom: L1Atom, existing_memory: MemoryRecord) -> bool:
        service = _old_service(existing_memory)
        alert_name = _old_alert_name(existing_memory)
        environment = _old_environment(existing_memory)

        if atom.service and service and _norm(atom.service) != _norm(service):
            return False
        if atom.alert_name and alert_name and _norm(atom.alert_name) != _norm(alert_name):
            return False
        if atom.environment and environment and _norm(atom.environment) != _norm(environment):
            return False

        matched = 0
        if atom.service and service and _norm(atom.service) == _norm(service):
            matched += 1
        if atom.alert_name and alert_name and _norm(atom.alert_name) == _norm(alert_name):
            matched += 1
        if atom.environment and environment and _norm(atom.environment) == _norm(environment):
            matched += 1
        return matched > 0

    def _matched_scope(self, atom: L1Atom, existing_memory: MemoryRecord) -> dict[str, Any]:
        service = _old_service(existing_memory)
        alert_name = _old_alert_name(existing_memory)
        environment = _old_environment(existing_memory)
        return {
            "owner_id": atom.owner_id,
            "service": atom.service or service,
            "alert_name": atom.alert_name or alert_name,
            "environment": atom.environment or environment,
        }

    def _evidence_is_current_enough(self, atom: L1Atom) -> bool:
        if not atom.evidence_refs:
            return False
        if atom.confidence < self.min_confidence:
            return False
        if atom.valid_until is None:
            return True
        now = datetime.now(atom.valid_until.tzinfo) if atom.valid_until.tzinfo else datetime.now()
        return atom.valid_until >= now

    def _claim_denies(self, claim: str, old_value: str | None) -> bool:
        if not old_value:
            return False
        normalized_claim = _norm(claim)
        return _norm(old_value) in normalized_claim and self._has_negative_marker(claim)

    def _has_negative_marker(self, text: str) -> bool:
        normalized = _norm(text)
        return any(_norm(marker) in normalized for marker in self.NEGATIVE_MARKERS)

    def _has_config_deploy_marker(self, text: str) -> bool:
        normalized = _norm(text)
        return any(_norm(marker) in normalized for marker in self.CONFIG_DEPLOY_MARKERS)

    def _counted_result(
        self,
        atom: L1Atom,
        existing_memory: MemoryRecord,
        *,
        verdict: MemoryConflictVerdict,
        reason: str,
        matched_scope: dict[str, Any],
    ) -> MemoryConflictResult:
        if verdict == MemoryConflictVerdict.POSSIBLE_CONFLICT:
            self.metrics.possible_conflict_count += 1
        if verdict == MemoryConflictVerdict.SUPERSESSION_CANDIDATE:
            self.metrics.supersession_candidate_count += 1
        return self._result(
            atom,
            existing_memory,
            verdict=verdict,
            reason=reason,
            matched_scope=matched_scope,
        )

    def _result(
        self,
        atom: L1Atom,
        existing_memory: MemoryRecord,
        *,
        verdict: MemoryConflictVerdict,
        reason: str,
        matched_scope: dict[str, Any],
    ) -> MemoryConflictResult:
        return MemoryConflictResult(
            memory_id=existing_memory.memory_id,
            atom_id=atom.atom_id,
            owner_id=atom.owner_id,
            memory_type=existing_memory.memory_type,
            verdict=verdict,
            reason=reason,
            evidence_id=atom.evidence_id,
            matched_scope=matched_scope,
            review_required=verdict != MemoryConflictVerdict.NO_CONFLICT,
            evidence_refs=list(atom.evidence_refs),
            old_claim=existing_memory.summary,
            new_claim=atom.claim,
        )

    def _coerce_atom(self, atom_or_record: L1Atom | MemoryRecord) -> L1Atom:
        if isinstance(atom_or_record, L1Atom):
            return atom_or_record
        if atom_or_record.memory_type != MemoryType.L1_ATOM or not isinstance(atom_or_record.payload, L1Atom):
            raise ValueError("ConflictDetectorService expects an L1 atom or L1 atom memory record")
        return atom_or_record.payload


def _old_service(record: MemoryRecord) -> str | None:
    payload = record.payload
    if isinstance(payload, AlertPatternPayload):
        return payload.service
    evidence_service = record.evidence.get("service") if isinstance(record.evidence, dict) else None
    return str(evidence_service).strip() if evidence_service else None


def _old_alert_name(record: MemoryRecord) -> str | None:
    payload = record.payload
    if isinstance(payload, AlertPatternPayload):
        return payload.alert_name
    if isinstance(payload, PlanTemplatePayload):
        return payload.alert_type
    evidence_alert = record.evidence.get("alert_name") if isinstance(record.evidence, dict) else None
    return str(evidence_alert).strip() if evidence_alert else None


def _old_environment(record: MemoryRecord) -> str | None:
    environment = record.evidence.get("environment") if isinstance(record.evidence, dict) else None
    return str(environment).strip() if environment else None


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip().lower())


conflict_detector_service = ConflictDetectorService()
