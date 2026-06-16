"""Deterministic checks for S5 answer-layer evals."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

KB_LEAK_MARKERS: dict[str, list[str]] = {
    "process_digital_dept": ["process_digital_dept"],
    "craft_dept": ["craft_dept"],
}
_ASCII_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")
_CJK_CHAR_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_WEAK_CJK_CHARS = set("的了和与及或是否什么哪些怎么应该需要可以进行使用结合判断分析查询关注检查处理说明文档内容相关")


def contains_required_text(text: str, expected: str) -> bool:
    """Return whether expected text is present under strict deterministic matching."""

    if not str(expected).strip():
        return True
    alternatives = _expected_alternatives(str(expected))
    if len(alternatives) > 1:
        return any(contains_required_text(text, alternative) for alternative in alternatives)
    if str(expected).strip() in str(text):
        return True
    expected_compact = _compact_for_match(str(expected))
    if not expected_compact:
        return True
    text_compact = _compact_for_match(str(text))
    if expected_compact in text_compact:
        return True
    return _has_required_token_coverage(str(text), str(expected))


def _expected_alternatives(expected: str) -> list[str]:
    """Split deterministic fact aliases written as ``source phrase||answer phrase``."""

    if "||" not in expected:
        return [expected]
    return [part.strip() for part in expected.split("||") if part.strip()]


def check_answer_hard_gates(
    *,
    sample: dict[str, Any],
    answer_text: str,
    context_text: str,
    retrieval_row: dict[str, Any],
) -> dict[str, Any]:
    missing_required_facts = [
        fact
        for fact in sample.get("must_include_facts") or []
        if not contains_required_text(answer_text, str(fact))
    ]
    context_missing_facts = [
        fact
        for fact in missing_required_facts
        if not contains_required_text(context_text, str(fact))
    ]
    answer_missing_facts = [
        fact for fact in missing_required_facts if fact not in context_missing_facts
    ]
    missing_citations = _missing_required_citations(
        answer_text,
        sample.get("required_citations") or [],
    )
    unsupported_claims = _unsupported_claim_hits(
        answer_text,
        sample.get("must_not_include_claims") or [],
    )
    permission_leaks = _permission_leak_hits(
        answer_text,
        allowed_kb_ids=sample.get("allowed_kb_ids") or [],
    )
    integrity = retrieval_row.get("source_ref_integrity") or {}
    source_ref_unresolvable_count = int(integrity.get("citation_unresolvable_count") or 0)
    source_ref_unresolvable_count += int(integrity.get("cross_scope_error_count") or 0)

    retrieval_layer_passed = retrieval_row.get("status") == "passed"
    hard_gate_passed = (
        retrieval_layer_passed
        and not missing_required_facts
        and not missing_citations
        and not unsupported_claims
        and not permission_leaks
        and source_ref_unresolvable_count == 0
    )

    return {
        "retrieval_layer_passed": retrieval_layer_passed,
        "hard_gate_passed": hard_gate_passed,
        "failure_category": _failure_category(
            retrieval_layer_passed=retrieval_layer_passed,
            retrieval_failure_category=str(retrieval_row.get("failure_category") or ""),
            permission_leaks=permission_leaks,
            unsupported_claims=unsupported_claims,
            missing_citations=missing_citations,
            source_ref_unresolvable_count=source_ref_unresolvable_count,
            context_missing_facts=context_missing_facts,
            answer_missing_facts=answer_missing_facts,
        ),
        "missing_required_fact_count": len(missing_required_facts),
        "missing_required_facts": list(missing_required_facts),
        "context_missing_fact_count": len(context_missing_facts),
        "context_missing_facts": list(context_missing_facts),
        "answer_missing_fact_count": len(answer_missing_facts),
        "answer_missing_facts": list(answer_missing_facts),
        "citation_required_but_missing": len(missing_citations),
        "missing_required_citations": missing_citations,
        "unsupported_claim_count": len(unsupported_claims),
        "unsupported_claims": unsupported_claims,
        "permission_leak_count": len(permission_leaks),
        "permission_leaks": permission_leaks,
        "source_ref_unresolvable_count": source_ref_unresolvable_count,
    }


def _failure_category(
    *,
    retrieval_layer_passed: bool,
    retrieval_failure_category: str,
    permission_leaks: list[dict[str, str]],
    unsupported_claims: list[dict[str, str]],
    missing_citations: list[dict[str, Any]],
    source_ref_unresolvable_count: int,
    context_missing_facts: list[str],
    answer_missing_facts: list[str],
) -> str:
    if not retrieval_layer_passed:
        return retrieval_failure_category or "retrieval_layer_failed"
    if permission_leaks:
        return "permission_leak"
    if unsupported_claims:
        return "answer_fabrication"
    if context_missing_facts:
        return "context_missing_facts"
    if answer_missing_facts:
        return "answer_missing_facts"
    if missing_citations or source_ref_unresolvable_count:
        return "citation_error"
    return "passed"


def _missing_required_citations(
    answer_text: str,
    required_citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for citation in required_citations:
        candidates = [
            citation.get("expected_in_answer"),
            citation.get("source_file"),
            citation.get("doc_id"),
        ]
        if not any(
            contains_required_text(answer_text, str(candidate))
            for candidate in candidates
            if candidate
        ):
            missing.append(dict(citation))
    return missing


def _unsupported_claim_hits(
    answer_text: str,
    must_not_include_claims: list[str],
) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for claim in must_not_include_claims:
        markers = _claim_markers(str(claim))
        hit_marker = next(
            (
                marker
                for marker in markers
                if _contains_forbidden_marker(
                    answer_text,
                    marker,
                    full_claim=str(claim),
                )
            ),
            "",
        )
        if hit_marker:
            hits.append({"claim": str(claim), "matched_marker": hit_marker})
    return hits


def _contains_forbidden_marker(answer_text: str, marker: str, *, full_claim: str) -> bool:
    if marker == full_claim:
        return marker in answer_text or _compact_for_match(marker) in _compact_for_match(answer_text)
    return contains_required_text(answer_text, marker)


def _claim_markers(claim: str) -> list[str]:
    markers = [claim]
    if "如" not in claim:
        return markers
    tail = claim.split("如", 1)[1]
    for token in re.split(r"[、,，/]|或|和", tail):
        token = token.strip(" 。；;()（）")
        if len(_compact_for_match(token)) >= 2:
            markers.append(token)
    return markers


def _permission_leak_hits(
    answer_text: str,
    *,
    allowed_kb_ids: list[str],
) -> list[dict[str, str]]:
    allowed = {str(kb_id) for kb_id in allowed_kb_ids}
    hits: list[dict[str, str]] = []
    for kb_id, markers in KB_LEAK_MARKERS.items():
        if kb_id in allowed:
            continue
        for marker in markers:
            if contains_required_text(answer_text, marker):
                hits.append({"kb_id": kb_id, "matched_marker": marker})
                break
    return hits


def _compact_for_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in normalized if ch.isalnum())


def _has_required_token_coverage(text: str, expected: str) -> bool:
    normalized_text = unicodedata.normalize("NFKC", text).casefold()
    normalized_expected = unicodedata.normalize("NFKC", expected).casefold()

    ascii_tokens = [
        token
        for token in _ASCII_TOKEN_PATTERN.findall(normalized_expected)
        if len(token) >= 2 or token.isdigit()
    ]
    compact_text = _compact_for_match(normalized_text)
    if ascii_tokens and not all(_compact_for_match(token) in compact_text for token in ascii_tokens):
        return False

    cjk_chars = [
        char
        for char in _CJK_CHAR_PATTERN.findall(normalized_expected)
        if char not in _WEAK_CJK_CHARS
    ]
    if len(cjk_chars) < 4:
        return bool(ascii_tokens)

    text_chars = set(_CJK_CHAR_PATTERN.findall(normalized_text))
    covered = sum(1 for char in cjk_chars if char in text_chars)
    return covered / len(cjk_chars) >= 0.72
