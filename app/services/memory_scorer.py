"""Scoring adapters for durable oncall memory retrieval."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Protocol

from app.models.memory import MemoryRecord


class MemoryScorer(Protocol):
    """Score one memory record for one natural-language query."""

    def score(self, record: MemoryRecord, query: str) -> tuple[float, List[str]]:
        """Return score and matched terms for one memory record."""


class LexicalMemoryScorer:
    """Current lexical scorer with synonym expansion."""

    retrieval_mode = "lexical"

    _SYNONYMS: Dict[str, List[str]] = {
        "中文": ["chinese"],
        "简洁": ["concise"],
        "证据边界": ["evidence boundary", "evidence boundaries", "evidence from hypotheses"],
        "证据": ["evidence"],
        "边界": ["boundary", "boundaries"],
        "排查": ["diagnosis", "diagnose", "inspect"],
        "告警": ["alert"],
        "内存": ["memory"],
        "oom": ["outofmemoryerror", "oom_kill", "out of memory"],
        "利用率": ["usage"],
        "使用率": ["usage"],
        "处理器": ["cpu"],
        "负载": ["load"],
        "过高": ["high"],
        "飙高": ["spike", "high"],
        "飙升": ["spike", "high"],
        "计算资源打满": ["cpu", "load", "high"],
        "processor": ["cpu"],
        "saturation": ["load", "high"],
        "deploy": ["deployment", "rollout"],
    }

    def score(self, record: MemoryRecord, query: str) -> tuple[float, List[str]]:
        terms = self._expand_terms(query)
        search_text = self._record_search_text(record)
        matched_terms = [term for term in terms if term in search_text]
        return float(len(matched_terms)), matched_terms

    def _expand_terms(self, query_text: str) -> List[str]:
        raw_terms = {
            term.strip().lower()
            for term in re.split(r"[\s,，。！？?;；:/\\|]+", query_text)
            if term.strip()
        }
        compact_query = query_text.strip().lower()
        if compact_query:
            raw_terms.add(compact_query)
        for term in self._SYNONYMS:
            if term in compact_query:
                raw_terms.add(term)

        expanded: list[str] = []
        seen: set[str] = set()
        for term in raw_terms:
            for candidate in [term, *self._SYNONYMS.get(term, [])]:
                candidate = candidate.strip().lower()
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    expanded.append(candidate)
        return expanded

    def _record_search_text(self, record: MemoryRecord) -> str:
        payload_json = json.dumps(record.payload.model_dump(mode="json"), ensure_ascii=False)
        parts = [
            record.memory_id,
            record.namespace,
            record.memory_type.value,
            record.content,
            record.summary,
            " ".join(record.tags),
            payload_json,
        ]
        return "\n".join(parts).lower()
