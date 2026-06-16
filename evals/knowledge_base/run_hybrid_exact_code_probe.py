"""Controlled synthetic probe for exact-code retrieval.

This runner does not index into the production/Beta knowledge base. It parses
``enterprise_error_code_reference.md`` from the synthetic fixture directory and
compares three local retrieval modes:

- ``dense_only``: semantic-name proxy that intentionally ignores exact IDs.
- ``sparse_only``: BM25-style lexical retrieval over full chunk text.
- ``hybrid``: RRF fusion of dense and sparse rankings.

The only allowed conclusion is whether exact-code documents are a suitable
candidate type for hybrid retrieval. The report is not evidence for changing
default retrieval configuration.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import config
from evals.knowledge_base.hybrid_exact_code_fixture import (
    QUERY_FILE,
    REFERENCE_FILE,
    validate_fixture_files,
    write_fixture_files,
)

ENTRY_RE = re.compile(r"^### (?P<code>ERR_[A-Z0-9]+_\d{3}) - (?P<title>.+)$", re.MULTILINE)
EXACT_CODE_RE = re.compile(r"ERR_[A-Z0-9]+_\d{3}", re.IGNORECASE)
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+")
GENERIC_QUERY_PHRASES = (
    "怎么解决",
    "是什么错误",
    "如何排查",
    "原因是什么",
    "排查步骤",
    "详细信息",
    "常见原因",
    "相关错误",
    "怎么处理",
    "怎么办",
    "解决方案",
    "错误",
    "原因",
    "排查",
    "处理",
    "解决",
    "步骤",
    "信息",
)
MODES = ("dense_only", "sparse_only", "hybrid")


@dataclass(frozen=True)
class CodeChunk:
    code: str
    title: str
    content: str


@dataclass(frozen=True)
class RankedHit:
    code: str
    score: float
    rank: int
    recall_source: str


def run_probe(
    *,
    reference_path: str | Path = REFERENCE_FILE,
    query_path: str | Path = QUERY_FILE,
    output_json: str | Path | None = None,
    output_md: str | Path | None = None,
    generate_fixture: bool = False,
) -> dict[str, Any]:
    if generate_fixture:
        write_fixture_files(Path(reference_path).parent)

    reference_path = Path(reference_path)
    query_path = Path(query_path)
    chunks = parse_reference_chunks(reference_path)
    queries = _load_jsonl(query_path)
    started_at = time.perf_counter()
    rows = [_evaluate_query(query, chunks) for query in queries]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "synthetic_controlled_exact_code_probe",
        "external_llm_called": False,
        "external_vector_db_called": False,
        "fixture": {
            "reference_path": str(reference_path),
            "query_path": str(query_path),
            "validation": validate_fixture_files(reference_path, query_path),
            "chunk_count": len(chunks),
            "synthetic": True,
            "production_corpus": False,
            "beta_baseline_impact": "none",
        },
        "mode_implementation": {
            "dense_only": "local semantic-name proxy; exact error-code identifiers and generic action phrases are ignored",
            "sparse_only": "local BM25-style lexical scoring over full chunk text including exact error codes",
            "hybrid": "RRF fusion over dense_only and sparse_only ranked lists",
        },
        "config_defaults_observed": _config_defaults(),
        "summary": _summary(rows),
        "decision": _decision(rows),
        "samples": rows,
        "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
    }
    if output_json is not None:
        output_json_path = Path(output_json)
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        output_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def parse_reference_chunks(path: str | Path) -> list[CodeChunk]:
    text = Path(path).read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(text))
    chunks: list[CodeChunk] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunks.append(
            CodeChunk(
                code=match.group("code"),
                title=match.group("title").strip(),
                content=text[start:end].strip(),
            )
        )
    return chunks


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    decision = report["decision"]
    lines = [
        "# Hybrid Exact-Code Synthetic Probe",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Scope: `{report['scope']}`",
        f"- Synthetic: `{report['fixture']['synthetic']}`",
        f"- Production corpus impact: `{report['fixture']['beta_baseline_impact']}`",
        f"- External LLM called: `{report['external_llm_called']}`",
        f"- External vector DB called: `{report['external_vector_db_called']}`",
        f"- Config defaults observed: `{report['config_defaults_observed']}`",
        "",
        "## Summary",
        "",
        f"- Total queries: {summary['total_queries']}",
        f"- Exact-code queries: {summary['query_type_counts'].get('exact_code', 0)}",
        f"- Semantic-name queries: {summary['query_type_counts'].get('semantic_name', 0)}",
        f"- Exact-code hybrid lift vs dense@3: {summary['exact_code_hybrid_lift_vs_dense_at3']}",
        f"- Exact-code sparse lift vs dense@3: {summary['exact_code_sparse_lift_vs_dense_at3']}",
        f"- Verdict: `{decision['verdict']}`",
        f"- Allowed conclusion: {decision['allowed_conclusion']}",
        f"- Hybrid vs sparse note: {decision['hybrid_vs_sparse_note']}",
        "",
        "| mode | hit@1 | hit@3 | exact_code_hit@3 | semantic_hit@3 |",
        "|---|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        mode_summary = summary["by_mode"][mode]
        lines.append(
            "| {mode} | {hit1}/{total} | {hit3}/{total} | {exact3}/{exact_total} | {semantic3}/{semantic_total} |".format(
                mode=mode,
                hit1=mode_summary["hit_at_1"],
                hit3=mode_summary["hit_at_3"],
                total=summary["total_queries"],
                exact3=mode_summary["hit_at_3_by_type"].get("exact_code", 0),
                exact_total=summary["query_type_counts"].get("exact_code", 0),
                semantic3=mode_summary["hit_at_3_by_type"].get("semantic_name", 0),
                semantic_total=summary["query_type_counts"].get("semantic_name", 0),
            )
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This is synthetic controlled evidence only.",
            "- It does not change `app/config.py`, `.env`, Beta corpus, or default retrieval mode.",
            "- It cannot prove business corpus maturity.",
            "- It can only indicate whether exact-code document types are suitable candidates for hybrid retrieval.",
            "",
        ]
    )
    return "\n".join(lines)


def _evaluate_query(query: dict[str, Any], chunks: list[CodeChunk]) -> dict[str, Any]:
    expected = str(query["expected_error_code"])
    top_k = int(query.get("top_k") or 3)
    mode_rankings = {
        "dense_only": _dense_rank(str(query["query"]), chunks),
        "sparse_only": _sparse_rank(str(query["query"]), chunks),
    }
    mode_rankings["hybrid"] = _hybrid_rank(mode_rankings["dense_only"], mode_rankings["sparse_only"])
    result = {
        "sample_id": query["sample_id"],
        "query": query["query"],
        "query_type": query["query_type"],
        "expected_error_code": expected,
        "synthetic": query.get("synthetic") is True,
        "top_k": top_k,
    }
    for mode, ranking in mode_rankings.items():
        top_hits = ranking[:top_k]
        result[mode] = {
            "hit_at_1": bool(top_hits and top_hits[0].code == expected),
            "hit_at_3": any(hit.code == expected for hit in top_hits),
            "rank": _rank_of(ranking, expected),
            "top_codes": [hit.code for hit in top_hits],
            "top_results": [
                {
                    "code": hit.code,
                    "score": round(hit.score, 6),
                    "rank": hit.rank,
                    "recall_source": hit.recall_source,
                }
                for hit in top_hits
            ],
        }
    result["hybrid_lift_vs_dense_at3"] = (
        not result["dense_only"]["hit_at_3"] and result["hybrid"]["hit_at_3"]
    )
    result["sparse_lift_vs_dense_at3"] = (
        not result["dense_only"]["hit_at_3"] and result["sparse_only"]["hit_at_3"]
    )
    return result


def _dense_rank(query: str, chunks: list[CodeChunk]) -> list[RankedHit]:
    query_terms = _semantic_terms(query)
    if not query_terms:
        return []
    scored: list[tuple[float, str]] = []
    for chunk in chunks:
        chunk_terms = _semantic_terms(f"{chunk.title}\n{chunk.content}")
        score = _jaccard_score(query_terms, chunk_terms)
        if score > 0:
            scored.append((score, chunk.code))
    return _ranked_hits(scored, recall_source="dense_proxy")


def _sparse_rank(query: str, chunks: list[CodeChunk]) -> list[RankedHit]:
    query_terms = _tokenize(query)
    if not query_terms:
        return []
    corpus_terms = [_tokenize(chunk.content) for chunk in chunks]
    avgdl = sum(len(terms) for terms in corpus_terms) / len(corpus_terms)
    doc_freqs: Counter[str] = Counter()
    for terms in corpus_terms:
        doc_freqs.update(set(terms))
    scored: list[tuple[float, str]] = []
    for chunk, terms in zip(chunks, corpus_terms, strict=True):
        score = _bm25_score(query_terms, terms, doc_freqs, len(chunks), avgdl)
        if score > 0:
            scored.append((score, chunk.code))
    return _ranked_hits(scored, recall_source="sparse_bm25")


def _hybrid_rank(dense_hits: list[RankedHit], sparse_hits: list[RankedHit]) -> list[RankedHit]:
    scores: dict[str, float] = Counter()
    sources: dict[str, set[str]] = {}
    for source_name, hits in (("dense", dense_hits), ("sparse", sparse_hits)):
        for rank, hit in enumerate(hits, start=1):
            scores[hit.code] += 1 / (60 + rank)
            sources.setdefault(hit.code, set()).add(source_name)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        RankedHit(
            code=code,
            score=score,
            rank=index,
            recall_source="+".join(sorted(sources.get(code, {"unknown"}))),
        )
        for index, (code, score) in enumerate(ranked, start=1)
    ]


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    query_type_counts = dict(Counter(str(row["query_type"]) for row in rows))
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        hit_at_1 = sum(1 for row in rows if row[mode]["hit_at_1"])
        hit_at_3 = sum(1 for row in rows if row[mode]["hit_at_3"])
        hit_at_3_by_type = {
            query_type: sum(
                1
                for row in rows
                if row["query_type"] == query_type and row[mode]["hit_at_3"]
            )
            for query_type in query_type_counts
        }
        by_mode[mode] = {
            "hit_at_1": hit_at_1,
            "hit_at_3": hit_at_3,
            "hit_at_3_by_type": hit_at_3_by_type,
        }
    exact_rows = [row for row in rows if row["query_type"] == "exact_code"]
    return {
        "total_queries": len(rows),
        "query_type_counts": query_type_counts,
        "by_mode": by_mode,
        "hybrid_lift_vs_dense_at3": sum(1 for row in rows if row["hybrid_lift_vs_dense_at3"]),
        "sparse_lift_vs_dense_at3": sum(1 for row in rows if row["sparse_lift_vs_dense_at3"]),
        "exact_code_hybrid_lift_vs_dense_at3": sum(
            1 for row in exact_rows if row["hybrid_lift_vs_dense_at3"]
        ),
        "exact_code_sparse_lift_vs_dense_at3": sum(
            1 for row in exact_rows if row["sparse_lift_vs_dense_at3"]
        ),
    }


def _decision(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _summary(rows)
    exact_lift = summary["exact_code_hybrid_lift_vs_dense_at3"]
    exact_total = summary["query_type_counts"].get("exact_code", 0)
    verdict = (
        "hybrid_suitable_for_exact_code_doc_type"
        if exact_lift >= 3
        else "hybrid_not_proven_for_exact_code_doc_type"
    )
    return {
        "verdict": verdict,
        "success_threshold": "exact_code_hybrid_lift_vs_dense_at3 >= 3",
        "observed_exact_code_lift": exact_lift,
        "observed_sparse_exact_code_lift": summary["exact_code_sparse_lift_vs_dense_at3"],
        "exact_code_query_count": exact_total,
        "allowed_conclusion": (
            "Hybrid can be considered for exact-code / identifier-heavy document types "
            "in a controlled synthetic setting."
            if exact_lift >= 3
            else "This controlled fixture does not prove hybrid value even for exact-code document types."
        ),
        "hybrid_vs_sparse_note": (
            "No hybrid-over-sparse advantage is claimed; the observed exact-code benefit comes from lexical sparse recall, "
            "and hybrid inherits that recall through fusion."
        ),
        "not_evidence_for": [
            "changing rag_default_retrieval_mode",
            "changing app/config.py or .env",
            "Beta corpus maturity",
            "Answer-layer readiness",
            "agent_behavior readiness",
        ],
    }


def _ranked_hits(scored: list[tuple[float, str]], *, recall_source: str) -> list[RankedHit]:
    ordered = sorted(scored, key=lambda item: (-item[0], item[1]))
    return [
        RankedHit(code=code, score=score, rank=index, recall_source=recall_source)
        for index, (score, code) in enumerate(ordered, start=1)
    ]


def _rank_of(ranking: list[RankedHit], expected_code: str) -> int | None:
    for hit in ranking:
        if hit.code == expected_code:
            return hit.rank
    return None


def _semantic_terms(text: str) -> set[str]:
    text = EXACT_CODE_RE.sub(" ", text)
    for phrase in GENERIC_QUERY_PHRASES:
        text = text.replace(phrase, " ")
    return set(_tokenize(text))


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for part in TOKEN_RE.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part):
            tokens.extend(part)
            tokens.extend(part[index : index + 2] for index in range(max(0, len(part) - 1)))
        else:
            tokens.append(part)
    return [token for token in tokens if token.strip()]


def _jaccard_score(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _bm25_score(
    query_terms: list[str],
    document_terms: list[str],
    document_frequencies: Counter[str],
    total_documents: int,
    avg_document_length: float,
) -> float:
    if not document_terms or avg_document_length <= 0:
        return 0.0
    term_counts = Counter(document_terms)
    document_length = len(document_terms)
    score = 0.0
    for term in query_terms:
        term_frequency = term_counts.get(term, 0)
        if term_frequency == 0:
            continue
        document_frequency = document_frequencies.get(term, 0)
        idf = math.log(1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5))
        denominator = term_frequency + 1.5 * (1 - 0.75 + 0.75 * document_length / avg_document_length)
        score += idf * (term_frequency * 2.5) / denominator
    return score


def _load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _config_defaults() -> dict[str, Any]:
    return {
        "rag_default_retrieval_mode": str(config.rag_default_retrieval_mode),
        "rag_query_rewrite_mode": str(config.rag_query_rewrite_mode),
        "rerank_enabled": bool(config.rerank_enabled),
        "rag_top_k": int(config.rag_top_k),
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run synthetic exact-code hybrid probe.")
    parser.add_argument("--reference", default=str(REFERENCE_FILE))
    parser.add_argument("--queries", default=str(QUERY_FILE))
    parser.add_argument("--output-json", default="evals/knowledge_base/reports/hybrid_exact_code_probe_20260612.json")
    parser.add_argument("--output-md", default="evals/knowledge_base/reports/hybrid_exact_code_probe_20260612.md")
    parser.add_argument("--generate-fixture", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_probe(
        reference_path=args.reference,
        query_path=args.queries,
        output_json=args.output_json,
        output_md=args.output_md,
        generate_fixture=args.generate_fixture,
    )
    print(json.dumps({"summary": report["summary"], "decision": report["decision"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
