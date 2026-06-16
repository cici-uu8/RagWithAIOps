"""Deterministic matcher for Enterprise 2.0 trace trajectories."""

from __future__ import annotations

from collections import Counter

from app.enterprise.aiops.failure_semantics import (
    HARD_FAILURE_LABELS,
    RECOVERED_LABELS,
    AIOpsFailureLabel,
)
from app.enterprise.observability.sse_contract import REQUIRED_SSE_FIELDS
from evals.enterprise.models import (
    ActualTrajectory,
    ExpectedTrajectory,
    TraceEvalResult,
    TrajectoryMismatch,
)


class TrajectoryMatcher:
    def match(self, expected: ExpectedTrajectory, actual: ActualTrajectory) -> TraceEvalResult:
        mismatches: list[TrajectoryMismatch] = []
        mismatches.extend(self._check_final_status(expected, actual))
        mismatches.extend(self._check_required_audit_events(expected, actual))
        mismatches.extend(self._check_required_stages(expected, actual))
        mismatches.extend(self._check_forbidden_tools(expected, actual))
        mismatches.extend(self._check_expected_contract(expected, actual))
        mismatches.extend(self._check_sse(expected, actual))
        mismatches.extend(self._check_database_agent_expectations(expected, actual))
        mismatches.extend(self._check_aiops_expectations(expected, actual))

        return TraceEvalResult(
            eval_id=expected.eval_id,
            trace_id=actual.trace_id,
            request_id=actual.request_id,
            route=actual.route,
            final_status=actual.terminal_status,
            passed=not mismatches,
            mismatches=mismatches,
        )

    def _check_database_agent_expectations(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        expected_tool = str(expected.input.get("expected_tool") or "").strip()
        if not expected_tool:
            return []

        if not _observed_expected_tool(expected_tool, actual.observed_tools):
            return [
                TrajectoryMismatch(
                    code="tool_not_called",
                    category="database_agent",
                    message=f"Expected database tool was not called: {expected_tool}",
                    tool_id=expected_tool,
                )
            ]

        database_events = [
            event for event in actual.audit_events if event.event_type == "database_query"
        ]
        if not database_events:
            return [
                TrajectoryMismatch(
                    code="audit_missing",
                    category="database_agent",
                    message="Expected database_query audit evidence, but none was observed",
                    event_type="database_query",
                )
            ]

        database_event = database_events[-1]
        metadata = database_event.metadata
        blocked_reason = str(
            metadata.get("blocked_reason")
            or database_event.reason
            or metadata.get("reason")
            or ""
        )
        blocked = (
            database_event.decision in {"denied", "blocked"}
            or str(metadata.get("status") or "").lower() == "blocked"
            or bool(blocked_reason)
        )
        expected_rejection_reason = str(expected.input.get("expected_rejection_reason") or "")
        if blocked:
            if not expected_rejection_reason:
                return [
                    TrajectoryMismatch(
                        code="sql_blocked",
                        category="database_agent",
                        message=f"SQL was blocked unexpectedly: {blocked_reason or 'unknown'}",
                        event_type="database_query",
                    )
                ]
            if _normalize(blocked_reason) != _normalize(expected_rejection_reason):
                return [
                    TrajectoryMismatch(
                        code="sql_blocked",
                        category="database_agent",
                        message=(
                            f"Expected rejection={expected_rejection_reason}, "
                            f"got {blocked_reason or 'unknown'}"
                        ),
                        event_type="database_query",
                    )
                ]
        elif expected_rejection_reason:
            return [
                TrajectoryMismatch(
                    code="sql_blocked",
                    category="database_agent",
                    message=f"Expected SQL rejection={expected_rejection_reason}, but SQL was not blocked",
                    event_type="database_query",
                )
            ]

        if _metadata_value(metadata, "db_diff") != str(expected.input.get("expected_db_diff") or ""):
            return [
                TrajectoryMismatch(
                    code="db_diff_failed",
                    category="database_agent",
                    message=(
                        f"Expected db_diff={expected.input.get('expected_db_diff')}, "
                        f"got {_metadata_value(metadata, 'db_diff') or 'missing'}"
                    ),
                    event_type="database_query",
                )
            ]

        audit_label = _metadata_value(metadata, "audit_label")
        expected_audit_label = str(expected.input.get("expected_audit_label") or "")
        if expected_audit_label and audit_label != expected_audit_label:
            return [
                TrajectoryMismatch(
                    code="audit_missing",
                    category="database_agent",
                    message=(
                        f"Expected audit_label={expected_audit_label}, "
                        f"got {audit_label or 'missing'}"
                    ),
                    event_type="database_query",
                )
            ]

        if not _matches_expected_scalar(
            metadata,
            "sql_family",
            str(expected.input.get("expected_sql_family") or ""),
            fallback_keys=("sql_kind",),
        ):
            return [
                TrajectoryMismatch(
                    code="audit_missing",
                    category="database_agent",
                    message="Expected SQL family evidence is missing or mismatched",
                    event_type="database_query",
                )
            ]

        if not _matches_expected_list(
            metadata,
            expected.input.get("expected_tables") or [],
            keys=("table_names", "target_tables", "table_name"),
        ):
            return [
                TrajectoryMismatch(
                    code="audit_missing",
                    category="database_agent",
                    message="Expected table evidence is missing or mismatched",
                    event_type="database_query",
                )
            ]

        if not _matches_expected_list(
            metadata,
            expected.input.get("expected_columns") or [],
            keys=("target_columns", "columns", "column_names"),
        ):
            return [
                TrajectoryMismatch(
                    code="audit_missing",
                    category="database_agent",
                    message="Expected column evidence is missing or mismatched",
                    event_type="database_query",
                )
            ]

        return []

    def _check_aiops_expectations(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        required_tools = [str(tool) for tool in expected.input.get("aiops_required_tools") or []]
        required_evidence = [
            str(category)
            for category in expected.input.get("aiops_required_evidence_categories") or []
        ]
        expected_failure_semantics = str(
            expected.input.get("expected_failure_semantics") or ""
        )
        if not required_tools and not required_evidence and not expected_failure_semantics:
            return []

        mismatches: list[TrajectoryMismatch] = []
        observed_tools = list(actual.observed_tools)
        for tool_id in required_tools:
            if not _observed_expected_tool(tool_id, observed_tools):
                mismatches.append(
                    TrajectoryMismatch(
                        code="aiops_required_tool_missing",
                        category="aiops",
                        message=f"Expected AIOps required tool was not observed: {tool_id}",
                        tool_id=tool_id,
                    )
                )

        observed_evidence = _collect_aiops_evidence_categories(actual)
        for category in required_evidence:
            if not _contains_normalized(observed_evidence, category):
                mismatches.append(
                    TrajectoryMismatch(
                        code="aiops_evidence_missing",
                        category="aiops",
                        message=f"Expected AIOps evidence category was not observed: {category}",
                    )
                )

        observed_semantics = _collect_aiops_failure_semantics(actual)
        if expected_failure_semantics:
            if not observed_semantics:
                mismatches.append(
                    TrajectoryMismatch(
                        code="aiops_failure_semantics_missing",
                        category="aiops",
                        message=(
                            "Expected AIOps failure semantics label was not observed: "
                            f"{expected_failure_semantics}"
                        ),
                    )
                )
            elif _normalize(expected_failure_semantics) == _normalize(
                AIOpsFailureLabel.RECOVERED_INFRA_ERROR.value
            ):
                mismatches.extend(
                    _check_recovered_infra_error_semantics(
                        expected_failure_semantics,
                        observed_semantics,
                    )
                )
            else:
                for observed in observed_semantics:
                    if _normalize(observed["label"]) != _normalize(expected_failure_semantics):
                        mismatches.append(
                            TrajectoryMismatch(
                                code="aiops_failure_semantics_inconsistent",
                                category="aiops",
                                message=(
                                    f"Expected AIOps failure_semantics={expected_failure_semantics}, "
                                    f"got {observed['label']}"
                                ),
                                event_type=observed.get("event_type"),
                            )
                        )

        for observed in observed_semantics:
            label = observed["label"]
            hard_failure = bool(observed.get("hard_failure"))
            try:
                known_label = AIOpsFailureLabel(label)
            except ValueError:
                continue

            if known_label in RECOVERED_LABELS:
                if hard_failure:
                    mismatches.append(
                        TrajectoryMismatch(
                            code="aiops_degradation_hard_failure",
                            category="aiops",
                            message=f"Recovered AIOps degradation was marked as hard failure: {label}",
                            event_type=observed.get("event_type"),
                        )
                    )
                continue

            if known_label in HARD_FAILURE_LABELS and not hard_failure:
                mismatches.append(
                    TrajectoryMismatch(
                        code="aiops_failure_semantics_inconsistent",
                        category="aiops",
                        message=f"Hard AIOps failure label was not marked hard: {label}",
                        event_type=observed.get("event_type"),
                    )
                )

        return mismatches

    def _check_final_status(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        if _normalize(expected.expected.final_status) == _normalize(actual.terminal_status):
            return []
        return [
            TrajectoryMismatch(
                code="final_status_mismatch",
                category="status",
                message=(
                    f"Expected final_status={expected.expected.final_status}, "
                    f"got {actual.terminal_status}"
                ),
            )
        ]

    def _check_required_audit_events(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        mismatches: list[TrajectoryMismatch] = []
        observed = Counter(actual.observed_audit_events)
        for event_type in expected.expected.required_audit_events:
            if observed[event_type] == 0:
                mismatches.append(
                    TrajectoryMismatch(
                        code="missing_audit_event",
                        category="audit",
                        message=f"Missing required audit event: {event_type}",
                        event_type=event_type,
                    )
                )
        return mismatches

    def _check_required_stages(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        required = [_normalize(stage) for stage in expected.expected.required_stages]
        observed = [_normalize(stage) for stage in actual.observed_stages]
        if not required:
            return []

        mismatches: list[TrajectoryMismatch] = []
        missing = [stage for stage in required if stage not in observed]
        for stage in missing:
            mismatches.append(
                TrajectoryMismatch(
                    code="missing_stage",
                    category="stage",
                    message=f"Missing required stage: {stage}",
                    stage=stage,
                )
            )
        if missing:
            return mismatches

        positions = [observed.index(stage) for stage in required]
        if positions != sorted(positions):
            mismatches.append(
                TrajectoryMismatch(
                    code="stage_order_violation",
                    category="stage",
                    message=(
                        f"Required stages must appear in order {required}, "
                        f"observed {observed}"
                    ),
                )
            )
        return mismatches

    def _check_forbidden_tools(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        mismatches: list[TrajectoryMismatch] = []
        observed_tools = [_normalize_tool(tool) for tool in actual.observed_tools]
        for forbidden in expected.expected.forbidden_tools:
            normalized_forbidden = _normalize_tool(forbidden)
            for observed, raw_tool in zip(observed_tools, actual.observed_tools, strict=False):
                if _tool_matches_forbidden(observed, normalized_forbidden):
                    mismatches.append(
                        TrajectoryMismatch(
                            code="forbidden_tool_used",
                            category="tool",
                            message=f"Forbidden tool was observed: {raw_tool}",
                            tool_id=raw_tool,
                        )
                    )
        return mismatches

    def _check_sse(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        sse_expectation = expected.expected.sse
        if sse_expectation is None:
            return []
        if not actual.sse_events:
            return [
                TrajectoryMismatch(
                    code="sse_missing_events",
                    category="sse",
                    message="Expected SSE events, but none were observed",
                )
            ]

        mismatches: list[TrajectoryMismatch] = []
        allowed_types = set(sse_expectation.allowed_event_types)
        for index, event in enumerate(actual.sse_events):
            event_type = str(event.get("type") or "unknown")
            if allowed_types and event_type not in allowed_types:
                mismatches.append(
                    TrajectoryMismatch(
                        code="sse_event_type_not_allowed",
                        category="sse",
                        message=f"SSE event #{index} type={event_type} is not allowed",
                    )
                )
            if sse_expectation.must_include_trace_id and not event.get("trace_id"):
                mismatches.append(
                    TrajectoryMismatch(
                        code="sse_missing_trace_id",
                        category="sse",
                        message=f"SSE event #{index} is missing trace_id",
                    )
                )
            if sse_expectation.must_include_request_id and not event.get("request_id"):
                mismatches.append(
                    TrajectoryMismatch(
                        code="sse_missing_request_id",
                        category="sse",
                        message=f"SSE event #{index} is missing request_id",
                    )
                )

            missing_fields = [
                field
                for field in sorted(REQUIRED_SSE_FIELDS - {"trace_id", "request_id"})
                if field not in event or event[field] in (None, "")
            ]
            for field in missing_fields:
                mismatches.append(
                    TrajectoryMismatch(
                        code="sse_missing_field",
                        category="sse",
                        message=f"SSE event #{index} is missing required field: {field}",
                    )
                )
        return mismatches

    def _check_expected_contract(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        contract_expectation = expected.expected.expected_contract
        if contract_expectation is None:
            return []
        if actual.task_contract is None:
            return [
                TrajectoryMismatch(
                    code="contract_missing",
                    category="contract",
                    message="Expected task contract evidence, but none was observed",
                )
            ]

        mismatches: list[TrajectoryMismatch] = []
        mismatches.extend(self._check_contract_scope(expected, actual))
        mismatches.extend(self._check_contract_approval(expected, actual))
        mismatches.extend(self._check_success_criteria(expected, actual))
        return mismatches

    def _check_contract_scope(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        contract_expectation = expected.expected.expected_contract
        contract = actual.task_contract
        if contract_expectation is None or contract is None:
            return []

        mismatches: list[TrajectoryMismatch] = []
        required_scope = contract_expectation.required_scope
        for data_source in required_scope.allowed_data_sources:
            if not _contains_normalized(contract.allowed_data_sources, data_source):
                mismatches.append(
                    TrajectoryMismatch(
                        code="scope_violation",
                        category="contract",
                        message=f"Contract is missing required data source scope: {data_source}",
                    )
                )
        for tool_id in required_scope.allowed_tools:
            if not _contains_tool_scope(contract.allowed_tools, tool_id):
                mismatches.append(
                    TrajectoryMismatch(
                        code="scope_violation",
                        category="contract",
                        message=f"Contract is missing required tool scope: {tool_id}",
                        tool_id=tool_id,
                    )
                )
        for action in required_scope.forbidden_actions:
            if not _contains_normalized(contract.forbidden_actions, action):
                mismatches.append(
                    TrajectoryMismatch(
                        code="scope_violation",
                        category="contract",
                        message=f"Contract is missing required forbidden action: {action}",
                    )
                )

        forbidden_tools = [
            *contract_expectation.forbidden_tools,
            *contract.forbidden_actions,
        ]
        for observed_tool in actual.observed_tools:
            if contract.allowed_tools and not _contains_tool_scope(contract.allowed_tools, observed_tool):
                mismatches.append(
                    TrajectoryMismatch(
                        code="scope_violation",
                        category="contract",
                        message=f"Observed tool is outside task contract scope: {observed_tool}",
                        tool_id=observed_tool,
                    )
                )
            for forbidden_tool in forbidden_tools:
                if _tool_matches_forbidden(_normalize_tool(observed_tool), _normalize_tool(forbidden_tool)):
                    mismatches.append(
                        TrajectoryMismatch(
                            code="scope_violation",
                            category="contract",
                            message=f"Observed tool violates task contract scope: {observed_tool}",
                            tool_id=observed_tool,
                        )
                    )

        for observed_source in actual.observed_data_sources:
            if contract.allowed_data_sources and not _contains_normalized(
                contract.allowed_data_sources,
                observed_source,
            ):
                mismatches.append(
                    TrajectoryMismatch(
                        code="scope_violation",
                        category="contract",
                        message=f"Observed data source is outside task contract scope: {observed_source}",
                    )
                )
        return mismatches

    def _check_contract_approval(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        contract_expectation = expected.expected.expected_contract
        contract = actual.task_contract
        if contract_expectation is None or contract is None:
            return []

        requires_approval = bool(contract_expectation.requires_human_approval)
        if not requires_approval:
            return []
        if _normalize(contract.status) in {"pending", "approved"}:
            return []
        return [
            TrajectoryMismatch(
                code="approval_missing",
                category="contract",
                message=(
                    "Task contract requires human approval, "
                    f"but observed status={contract.status or 'unknown'}"
                ),
            )
        ]

    def _check_success_criteria(
        self,
        expected: ExpectedTrajectory,
        actual: ActualTrajectory,
    ) -> list[TrajectoryMismatch]:
        contract_expectation = expected.expected.expected_contract
        if contract_expectation is None or not contract_expectation.success_criteria_keywords:
            return []
        if not _has_final_report(actual):
            return []
        if _has_success_criteria_check(actual):
            return []
        return [
            TrajectoryMismatch(
                code="success_criteria_unchecked",
                category="contract",
                message="Final report exists without success criteria check evidence",
            )
        ]


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _normalize_tool(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _tool_matches_forbidden(observed: str, forbidden: str) -> bool:
    return observed == forbidden or observed.startswith(f"{forbidden}.") or observed.startswith(f"{forbidden}:")


def _contains_normalized(values: list[str], expected: str) -> bool:
    normalized_expected = _normalize(expected)
    return any(_normalize(value) == normalized_expected for value in values)


def _contains_tool_scope(values: list[str], observed: str) -> bool:
    normalized_observed = _normalize_tool(observed)
    return any(
        normalized_observed == _normalize_tool(value)
        or normalized_observed.startswith(f"{_normalize_tool(value)}.")
        or normalized_observed.startswith(f"{_normalize_tool(value)}:")
        for value in values
    )


def _observed_expected_tool(expected_tool: str, observed_tools: list[str]) -> bool:
    return any(_normalize_tool(tool) == _normalize_tool(expected_tool) for tool in observed_tools)


def _metadata_value(metadata: dict, key: str) -> str:
    value = metadata.get(key)
    if value is None:
        return ""
    return str(value)


def _matches_expected_scalar(
    metadata: dict,
    primary_key: str,
    expected: str,
    *,
    fallback_keys: tuple[str, ...] = (),
) -> bool:
    if not expected:
        return True
    for key in (primary_key, *fallback_keys):
        value = _metadata_value(metadata, key)
        if value and _normalize(value) == _normalize(expected):
            return True
    return False


def _matches_expected_list(
    metadata: dict,
    expected_values,
    *,
    keys: tuple[str, ...],
) -> bool:
    expected = [str(value) for value in expected_values]
    if not expected:
        return True
    observed: list[str] = []
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, list):
            observed.extend(str(item) for item in value)
        elif value:
            observed.append(str(value))
    return all(_contains_normalized(observed, value) for value in expected)


def _collect_aiops_evidence_categories(actual: ActualTrajectory) -> list[str]:
    observed: list[str] = []
    for event in actual.audit_events:
        observed.extend(_metadata_list(event.metadata, "evidence_categories"))
        observed.extend(_metadata_list(event.metadata, "evidence_category"))
    for event in actual.sse_events:
        observed.extend(_event_list(event, "evidence_categories"))
        observed.extend(_event_list(event, "evidence_category"))
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        observed.extend(_metadata_list(data, "evidence_categories"))
        observed.extend(_metadata_list(data, "evidence_category"))
    return _ordered_unique_str(observed)


def _collect_aiops_failure_semantics(actual: ActualTrajectory) -> list[dict]:
    observed: list[dict] = []
    for event in actual.audit_events:
        label = event.metadata.get("failure_semantics")
        if not label:
            continue
        observed.append(
            {
                "label": str(label),
                "hard_failure": bool(event.metadata.get("failure_semantics_hard_failure")),
                "event_type": event.event_type,
                "terminal": _is_aiops_terminal_semantics_event(
                    event.metadata.get("source_event_type") or event.event_type,
                    event.metadata.get("stage"),
                ),
            }
        )
    for event in actual.sse_events:
        label = event.get("failure_semantics")
        if not label:
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            label = data.get("failure_semantics")
        if not label:
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        hard_failure = event.get("failure_semantics_hard_failure")
        if hard_failure is None:
            hard_failure = data.get("failure_semantics_hard_failure")
        observed.append(
            {
                "label": str(label),
                "hard_failure": bool(hard_failure),
                "event_type": str(event.get("type") or "sse"),
                "terminal": _is_aiops_terminal_semantics_event(
                    event.get("type") or data.get("type"),
                    event.get("stage") or data.get("stage"),
                ),
            }
        )
    return observed


def _is_aiops_terminal_semantics_event(event_type, stage) -> bool:
    normalized_type = _normalize(str(event_type or ""))
    normalized_stage = _normalize(str(stage or ""))
    return normalized_type in {"complete", "done"} or normalized_stage in {
        "diagnosis_complete",
        "done",
    }


def _check_recovered_infra_error_semantics(
    expected_failure_semantics: str,
    observed_semantics: list[dict],
) -> list[TrajectoryMismatch]:
    mismatches: list[TrajectoryMismatch] = []
    terminal_observed = [observed for observed in observed_semantics if observed.get("terminal")]
    if not terminal_observed:
        mismatches.append(
            TrajectoryMismatch(
                code="aiops_failure_semantics_missing",
                category="aiops",
                message="Expected terminal AIOps recovered infra semantics, but no terminal semantic event was observed",
            )
        )
    else:
        terminal = terminal_observed[-1]
        if _normalize(terminal["label"]) != _normalize(expected_failure_semantics):
            mismatches.append(
                TrajectoryMismatch(
                    code="aiops_failure_semantics_inconsistent",
                    category="aiops",
                    message=(
                        f"Expected terminal AIOps failure_semantics={expected_failure_semantics}, "
                        f"got {terminal['label']}"
                    ),
                    event_type=terminal.get("event_type"),
                )
            )
        if bool(terminal.get("hard_failure")):
            mismatches.append(
                TrajectoryMismatch(
                    code="aiops_degradation_hard_failure",
                    category="aiops",
                    message="Recovered infra error terminal event was marked as hard failure",
                    event_type=terminal.get("event_type"),
                )
            )

    has_intermediate_infra = any(
        _normalize(observed["label"]) == _normalize(AIOpsFailureLabel.INFRA_ERROR.value)
        and not observed.get("terminal")
        for observed in observed_semantics
    )
    if not has_intermediate_infra:
        mismatches.append(
            TrajectoryMismatch(
                code="aiops_failure_semantics_missing",
                category="aiops",
                message="Expected intermediate infra_error evidence before recovered_infra_error, but none was observed",
            )
        )
    return mismatches


def _metadata_list(metadata: dict, key: str) -> list[str]:
    value = metadata.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _event_list(event: dict, key: str) -> list[str]:
    value = event.get(key)
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _ordered_unique_str(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _has_final_report(actual: ActualTrajectory) -> bool:
    if actual.terminal_status == "completed":
        return True
    return any(event.get("type") in {"report", "done", "complete"} for event in actual.sse_events)


def _has_success_criteria_check(actual: ActualTrajectory) -> bool:
    for event in actual.audit_events:
        if event.event_type in {
            "task_contract_success_checked",
            "success_criteria_checked",
            "report_verified",
        }:
            return True
        if event.metadata.get("success_criteria_checked") is True:
            return True
    for event in actual.sse_events:
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("success_criteria_checked") is True or data.get("success_criteria_checked") is True:
            return True
    return False
