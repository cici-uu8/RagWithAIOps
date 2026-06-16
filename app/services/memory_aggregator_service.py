"""L1 -> L2 scenario aggregation for reviewed oncall memory."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, Field

from app.models.memory import L1Atom, L2ScenarioPayload, MemoryRecord, MemoryStatus, MemoryType
from app.models.memory_atom import L1AtomType
from app.services.memory_candidate_service import dedup_key
from app.services.memory_store import MemoryStore, memory_store


class AggregationMetrics(BaseModel):
    """Counters for P7.4 aggregation outcomes."""

    aggregation_attempt_count: int = 0
    aggregation_success_count: int = 0
    aggregation_duplicate_count: int = 0
    aggregation_skipped_count: int = 0
    aggregation_traceability_failure_count: int = 0

    def snapshot(self) -> dict[str, int]:
        return self.model_dump()


class MemoryAggregationResult(BaseModel):
    """Result for one L2 aggregation attempt."""

    owner_id: str
    action: Literal["created", "duplicate", "skipped"]
    records: list[MemoryRecord] = Field(default_factory=list)
    atom_ids: list[str] = Field(default_factory=list)
    scenario_key: Optional[str] = None
    skipped_reason: Optional[str] = None
    metrics: dict[str, int] = Field(default_factory=dict)


class MemoryAggregatorService:
    """Build traceable L2 scenario candidates from stable L1 atoms."""

    def __init__(
        self,
        *,
        store: MemoryStore = memory_store,
        stable_statuses: Iterable[MemoryStatus] = (MemoryStatus.ACTIVE,),
        min_atoms_per_scenario: int = 2,
    ):
        self.store = store
        self.stable_statuses = tuple(stable_statuses)
        self.min_atoms_per_scenario = min_atoms_per_scenario
        self.metrics = AggregationMetrics()

    def aggregate_from_atom_ids(
        self,
        atom_ids: list[str],
        *,
        owner_id: str = "default",
    ) -> MemoryAggregationResult:
        """Aggregate a caller-selected atom slice into one L2 scenario candidate."""

        self.metrics.aggregation_attempt_count += 1
        atoms = self._load_atoms_by_id(atom_ids, owner_id=owner_id)
        return self._aggregate_atoms(owner_id=owner_id, atoms=atoms, requested_atom_ids=atom_ids)

    def aggregate_for_scope(
        self,
        *,
        owner_id: str = "default",
        service: str | None = None,
        alert_name: str | None = None,
        environment: str | None = None,
    ) -> MemoryAggregationResult:
        """Aggregate all stable L1 atoms that match one scope."""

        self.metrics.aggregation_attempt_count += 1
        atoms = self._load_atoms_for_scope(
            owner_id=owner_id,
            service=service,
            alert_name=alert_name,
            environment=environment,
        )
        return self._aggregate_atoms(owner_id=owner_id, atoms=atoms, requested_atom_ids=None)

    def get_metrics(self) -> dict[str, int]:
        return self.metrics.snapshot()

    def _aggregate_atoms(
        self,
        *,
        owner_id: str,
        atoms: list[MemoryRecord],
        requested_atom_ids: list[str] | None,
    ) -> MemoryAggregationResult:
        if len(atoms) < self.min_atoms_per_scenario:
            self.metrics.aggregation_skipped_count += 1
            return MemoryAggregationResult(
                owner_id=owner_id,
                action="skipped",
                atom_ids=[record.memory_id for record in atoms],
                skipped_reason=f"at least {self.min_atoms_per_scenario} stable L1 atoms are required",
                metrics=self.get_metrics(),
            )

        stable_atoms = [record for record in atoms if record.status in self.stable_statuses and isinstance(record.payload, L1Atom)]
        if len(stable_atoms) < self.min_atoms_per_scenario:
            self.metrics.aggregation_skipped_count += 1
            return MemoryAggregationResult(
                owner_id=owner_id,
                action="skipped",
                atom_ids=[record.memory_id for record in atoms],
                skipped_reason=f"at least {self.min_atoms_per_scenario} stable L1 atoms are required after lifecycle/status filtering",
                metrics=self.get_metrics(),
            )

        if requested_atom_ids is not None:
            stable_atoms = self._dedupe_by_requested_order(stable_atoms, requested_atom_ids)

        scope = self._scope_from_atoms(stable_atoms)
        if scope is None:
            self.metrics.aggregation_skipped_count += 1
            return MemoryAggregationResult(
                owner_id=owner_id,
                action="skipped",
                atom_ids=[record.memory_id for record in stable_atoms],
                skipped_reason="L2 first slice only supports one service + one alert + one environment scope",
                metrics=self.get_metrics(),
            )

        scenario_key = self._scenario_key(owner_id=owner_id, scope=scope)
        scenario_record = self._build_scenario_record(
            owner_id=owner_id,
            scenario_key=scenario_key,
            atoms=stable_atoms,
            scope=scope,
        )

        existing_records = [
            record
            for record in self.store.list_memories(owner_id=owner_id, memory_type=MemoryType.L2_SCENARIO)
            if record.status != MemoryStatus.DEPRECATED
        ]
        for existing in existing_records:
            if dedup_key(existing) == dedup_key(scenario_record):
                self.metrics.aggregation_duplicate_count += 1
                return MemoryAggregationResult(
                    owner_id=owner_id,
                    action="duplicate",
                    records=[existing],
                    atom_ids=[record.memory_id for record in stable_atoms],
                    scenario_key=scenario_key,
                    metrics=self.get_metrics(),
                )

        stored = self.store.upsert(scenario_record)
        self.metrics.aggregation_success_count += 1
        return MemoryAggregationResult(
            owner_id=owner_id,
            action="created",
            records=[stored],
            atom_ids=[record.memory_id for record in stable_atoms],
            scenario_key=scenario_key,
            metrics=self.get_metrics(),
        )

    def _load_atoms_by_id(self, atom_ids: list[str], *, owner_id: str) -> list[MemoryRecord]:
        seen: set[str] = set()
        atoms: list[MemoryRecord] = []
        for atom_id in atom_ids:
            if atom_id in seen:
                continue
            seen.add(atom_id)
            record = self.store.get(atom_id)
            if record is None or record.owner_id != owner_id:
                self.metrics.aggregation_traceability_failure_count += 1
                continue
            atoms.append(record)
        return atoms

    def _load_atoms_for_scope(
        self,
        *,
        owner_id: str,
        service: str | None,
        alert_name: str | None,
        environment: str | None,
    ) -> list[MemoryRecord]:
        records = self.store.list_memories(
            owner_id=owner_id,
            memory_type=MemoryType.L1_ATOM,
        )
        atoms: list[MemoryRecord] = []
        for record in records:
            if record.status not in self.stable_statuses:
                continue
            payload = record.payload
            if not isinstance(payload, L1Atom):
                self.metrics.aggregation_traceability_failure_count += 1
                continue
            if service is not None and payload.service != service:
                continue
            if alert_name is not None and payload.alert_name != alert_name:
                continue
            if environment is not None and payload.environment != environment:
                continue
            atoms.append(record)
        return atoms

    def _dedupe_by_requested_order(self, atoms: list[MemoryRecord], requested_atom_ids: list[str]) -> list[MemoryRecord]:
        ordered: list[MemoryRecord] = []
        lookup = {record.memory_id: record for record in atoms}
        for atom_id in requested_atom_ids:
            record = lookup.get(atom_id)
            if record is not None and record not in ordered:
                ordered.append(record)
        return ordered

    def _scope_from_atoms(self, atoms: list[MemoryRecord]) -> dict[str, str | None] | None:
        service_values = {record.payload.service for record in atoms if isinstance(record.payload, L1Atom) and record.payload.service}
        alert_values = {record.payload.alert_name for record in atoms if isinstance(record.payload, L1Atom) and record.payload.alert_name}
        environment_values = {record.payload.environment for record in atoms if isinstance(record.payload, L1Atom) and record.payload.environment}
        if len(service_values) > 1 or len(alert_values) > 1 or len(environment_values) > 1:
            return None
        return {
            "service": next(iter(service_values), None),
            "alert_name": next(iter(alert_values), None),
            "environment": next(iter(environment_values), None),
        }

    def _scenario_key(self, *, owner_id: str, scope: dict[str, str | None]) -> str:
        return "|".join(
            [
                f"owner={self._norm(owner_id)}",
                f"service={self._norm(scope.get('service')) or 'any'}",
                f"alert={self._norm(scope.get('alert_name')) or 'any'}",
                f"environment={self._norm(scope.get('environment')) or 'any'}",
            ]
        )

    def _build_scenario_record(
        self,
        *,
        owner_id: str,
        scenario_key: str,
        atoms: list[MemoryRecord],
        scope: dict[str, str | None],
    ) -> MemoryRecord:
        ordered_atoms = self._sort_atoms(atoms)
        atom_ids = [record.memory_id for record in ordered_atoms]
        evidence_refs = [
            {
                "evidence_type": "l2_scenario_support",
                "scenario_key": scenario_key,
                "source_atom_id": record.memory_id,
                "atom_type": record.payload.atom_type.value,
                "evidence_id": record.payload.evidence_id,
                "claim": record.payload.claim,
            }
            for record in ordered_atoms
        ]
        applicable_conditions = self._build_applicable_conditions(scope, ordered_atoms)
        diagnostic_path = self._build_diagnostic_path(ordered_atoms)
        common_root_causes = self._unique_text(
            record.payload.root_cause
            for record in ordered_atoms
            if isinstance(record.payload, L1Atom) and record.payload.root_cause
        )
        remediation_steps = self._unique_text(
            record.payload.remediation
            for record in ordered_atoms
            if isinstance(record.payload, L1Atom) and record.payload.remediation
        )
        supporting_claims = [record.payload.claim for record in ordered_atoms if isinstance(record.payload, L1Atom)]
        scenario_title = self._build_scenario_title(scope)
        markdown = self._build_scenario_markdown(
            scenario_title=scenario_title,
            scope=scope,
            atom_ids=atom_ids,
            evidence_refs=evidence_refs,
            applicable_conditions=applicable_conditions,
            diagnostic_path=diagnostic_path,
            common_root_causes=common_root_causes,
            remediation_steps=remediation_steps,
            supporting_claims=supporting_claims,
        )
        payload = L2ScenarioPayload(
            scenario_key=scenario_key,
            scenario_title=scenario_title,
            service=scope.get("service"),
            alert_name=scope.get("alert_name"),
            environment=scope.get("environment"),
            applicable_conditions=applicable_conditions,
            diagnostic_path=diagnostic_path,
            common_root_causes=common_root_causes,
            remediation_steps=remediation_steps,
            supporting_claims=supporting_claims,
            l1_atom_ids=atom_ids,
            evidence_refs=evidence_refs,
            scenario_markdown=markdown,
        )
        memory_id = self._scenario_memory_id(scenario_key, atom_ids)
        evidence = {
            "evidence_type": "l2_scenario_candidate",
            "scenario_key": scenario_key,
            "l1_atom_ids": atom_ids,
            "l0_evidence_refs": [ref["evidence_id"] for ref in evidence_refs],
        }
        return MemoryRecord(
            memory_id=memory_id,
            owner_id=owner_id,
            namespace="memory://oncall/l2-scenarios",
            memory_type=MemoryType.L2_SCENARIO,
            content=markdown,
            summary=self._truncate(scenario_title, 240),
            payload=payload,
            source="l1-atom-aggregator, NOT reviewed active memory",
            evidence=evidence,
            status=MemoryStatus.CANDIDATE,
            tags=["l2_scenario", scope.get("service") or "any", scope.get("alert_name") or "any"],
        )

    def _sort_atoms(self, atoms: list[MemoryRecord]) -> list[MemoryRecord]:
        priority = {
            L1AtomType.ROOT_CAUSE_OBSERVATION: 0,
            L1AtomType.CHECK_OBSERVATION: 1,
            L1AtomType.REMEDIATION_OBSERVATION: 2,
            L1AtomType.NEGATIVE_OBSERVATION: 3,
            L1AtomType.CONFIG_OR_DEPLOY_CHANGE: 4,
        }
        return sorted(
            atoms,
            key=lambda record: (
                priority.get(record.payload.atom_type, 99) if isinstance(record.payload, L1Atom) else 99,
                record.updated_at,
                record.memory_id,
            ),
        )

    def _build_applicable_conditions(self, scope: dict[str, str | None], atoms: list[MemoryRecord]) -> list[str]:
        conditions: list[str] = []
        for key in ("service", "alert_name", "environment"):
            value = scope.get(key)
            if value:
                conditions.append(str(value))
        if any(isinstance(record.payload, L1Atom) and record.payload.valid_from for record in atoms):
            conditions.append("stable L1 atoms with traceable evidence")
        return self._unique_text(conditions)

    def _build_diagnostic_path(self, atoms: list[MemoryRecord]) -> list[str]:
        checks = [
            record.payload.check_name
            for record in atoms
            if isinstance(record.payload, L1Atom) and record.payload.check_name
        ]
        if checks:
            return self._unique_text(checks)
        return ["repeat the stable checks captured by the supporting L1 atoms"]

    def _build_scenario_title(self, scope: dict[str, str | None]) -> str:
        parts = [scope.get("service") or "unknown-service", scope.get("alert_name") or "scenario"]
        if scope.get("environment"):
            parts.append(f"({scope['environment']})")
        return f"Scenario: {' '.join(parts)}"

    def _build_scenario_markdown(
        self,
        *,
        scenario_title: str,
        scope: dict[str, str | None],
        atom_ids: list[str],
        evidence_refs: list[dict[str, Any]],
        applicable_conditions: list[str],
        diagnostic_path: list[str],
        common_root_causes: list[str],
        remediation_steps: list[str],
        supporting_claims: list[str],
    ) -> str:
        lines = [
            f"# {scenario_title}",
            "",
            "## Applicable Conditions",
        ]
        for condition in applicable_conditions or ["stable L1 atoms only"]:
            lines.append(f"- {condition}")

        lines.extend(["", "## Recommended Diagnostic Path"])
        for index, step in enumerate(diagnostic_path, 1):
            lines.append(f"{index}. {step}")

        if common_root_causes:
            lines.extend(["", "## Common Root Causes"])
            for item in common_root_causes:
                lines.append(f"- {item}")

        if remediation_steps:
            lines.extend(["", "## Remediation Steps"])
            for item in remediation_steps:
                lines.append(f"- {item}")

        if supporting_claims:
            lines.extend(["", "## Supporting Claims"])
            for item in supporting_claims:
                lines.append(f"- {item}")

        lines.extend(
            [
                "",
                "## Evidence",
                f"- L1 atom ids: {', '.join(atom_ids)}",
                f"- L0 evidence ids: {', '.join(ref['evidence_id'] for ref in evidence_refs)}",
            ]
        )
        return "\n".join(lines)

    def _scenario_memory_id(self, scenario_key: str, atom_ids: list[str]) -> str:
        digest = hashlib.sha256(
            self._normalize_json(
                {
                    "scenario_key": scenario_key,
                    "atom_ids": sorted(atom_ids),
                }
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"l2_scenario_{digest}"

    @staticmethod
    def _normalize_json(value: Any) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    @staticmethod
    def _norm(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().lower()

    @staticmethod
    def _unique_text(values: Iterable[str | None]) -> list[str]:
        seen: set[str] = set()
        items: list[str] = []
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(text)
        return items


memory_aggregator_service = MemoryAggregatorService()
