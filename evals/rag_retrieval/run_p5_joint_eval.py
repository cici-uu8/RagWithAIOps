#!/usr/bin/env python3
"""P5.f2 joint evaluation: DOC_LEVEL × P4.5 granularity matrix on long docs.

Validation-only follow-up (P6 prerequisite step P5.f2). Reuses the 18 samples
validated in P5.f1, the same 3 MinerU artifacts, and the same default
parameters. The only new dimension is context_granularity: this run sweeps the
6-cell matrix {NONE, DOC_LEVEL} × {chunk, parent_chunk, full_doc}.

Frozen pre-run thresholds (per user wrap-up):

  Per-granularity token thresholds:
    chunk:        DL tokens_avg ≤ 4000 AND DL/NONE ≤ 2.0
    parent_chunk: DL tokens_avg ≤ 6000 AND DL/NONE ≤ 2.0
    full_doc:     DL/NONE ≤ 1.5 ONLY (no absolute pass/fail threshold)
                  Absolute DL tokens_avg highlighted as SOFT OBSERVATION
                  per user directive.

  Per-strategy invariance assertions (§4 extended to 6 conditions):
    1. (existing) DL chunk_ids ⊆ pool chunk_ids (per granularity)
    2. (existing) NONE chunk_ids ⊆ pool chunk_ids (per granularity)
    3. (existing) DL each result's identity fields byte-equal to the same
       chunk_id's hit in the pool
    4. (existing) DL len ≤ top_k * top_chunks_per_doc + per-doc cap
    5. (NEW) Same chunk_id appearing in ≥ 2 of the 6 cells has byte-equal
       chunk_id / content / source_ref / citation_text (proves granularity
       only mutates context_text + metadata.expanded_context)
    6. (NEW) NONE × {chunk, parent_chunk, full_doc} return identical ordered
       chunk_id lists; DOC_LEVEL × {chunk, parent_chunk, full_doc} return
       identical ordered chunk_id lists (P4.5 §4 ordered-list invariance
       reproduction on long-doc corpus)

  Soft observations (no pass/fail):
    - fallback_rate per cell (P4.5 metadata.context_granularity_fallback)
    - joint_amplification(g) = (DL_avg(g)/DL_avg(chunk)) / (NONE_avg(g)/NONE_avg(chunk))
    - full_doc absolute DL tokens_avg

  Sanity anchors:
    - Reproduce P5.f1 NONE×chunk and DL×chunk aggregate metrics; flag any
      drift from the recorded P5.f1 baseline.
    - Restate P5.f1 D1 conclusion (factor=4 enough; P5.f4 not triggered).
      D1 itself is not re-checked because granularity does not affect the
      candidate pool (pool is always assembled at chunk granularity).

Per user execution stipulation: this script does not change P5 or P4.5
implementation under any condition. Failures stop the run and report back.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from pymilvus import utility

from app.config import config
from app.core import milvus_client as milvus_client_module
from app.models import (
    ContextGranularity,
    DocumentRecord,
    DocumentStatus,
    ParserEngine,
    ResultAggregation,
    RetrievalMode,
    RetrievalQuery,
)
from app.services import document_ingestion_service as ingestion_module
from app.services import retrieval_service as retrieval_service_module
from app.services import vector_index_service as vector_index_module
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.rerank_service import rerank_service
from app.services.vector_store_manager import vector_store_manager


config.milvus_host = "127.0.0.1"

EVAL_DIR = REPO_ROOT / "evals" / "rag_retrieval"
REPORT_DIR = EVAL_DIR / "reports"
SAMPLES_PATH = EVAL_DIR / "p5_long_doc_samples.jsonl"  # reused from P5.f1
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
EVAL_COLLECTION = f"p5_joint_eval_{RUN_ID}"

DEFAULT_TOP_K = 3
DEFAULT_TOP_CHUNKS_PER_DOC = 1
DEFAULT_OVERSAMPLE = 4
CATEGORIES = ["same_doc_redundant", "cross_doc_already", "reverse_control"]

GRANULARITIES = [
    ContextGranularity.CHUNK,
    ContextGranularity.PARENT_CHUNK,
    ContextGranularity.FULL_DOC,
]
STRATEGIES = [ResultAggregation.NONE, ResultAggregation.DOC_LEVEL]

# Frozen pre-run token thresholds (per user wrap-up).
TOKEN_THRESHOLDS = {
    "chunk": {"abs_max": 4000.0, "rel_max": 2.0, "abs_pass_required": True},
    "parent_chunk": {"abs_max": 6000.0, "rel_max": 2.0, "abs_pass_required": True},
    # full_doc: only ratio threshold; absolute is soft-observation per user.
    "full_doc": {"abs_max": None, "rel_max": 1.5, "abs_pass_required": False},
}

ARTIFACT_BASE = Path(__file__).resolve().parents[2] / "data" / "mineru" / "expanded_corpus"
TARGETS = [
    ("manuals", "h3c_campus_switch_installation_guide_cn",
     "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "h3c_mc101_mc102_user_manual_cn",
     "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("papers", "arxiv_vision_transformer",
     "arxiv_vision_transformer.pdf"),
]

# P5.f1 baseline (NONE×chunk and DL×chunk) for sanity reproduction check.
# Source: evals/rag_retrieval/reports/p5_long_doc_eval_20260518_224445.json
P5_F1_BASELINE = {
    "none_chunk_tokens_avg": 1178.388888888889,
    "doc_level_chunk_tokens_avg": 639.7777777777778,
    "none_chunk_distinct_avg": None,  # filled in via runtime computation
    "doc_level_chunk_distinct_avg": None,
}
SANITY_TOKENS_TOLERANCE = 1.0  # any drift > 1.0 token avg flagged as drift


def _qwen_tokenizer():
    from dashscope.tokenizers.tokenizer import get_tokenizer

    return get_tokenizer(config.rag_model)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"P5.f2 samples (reused from P5.f1) not found: {path}")
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        samples.append(json.loads(line))
    if not samples:
        raise ValueError(f"P5.f2 samples empty: {path}")
    return samples


def setup_isolated(tmp_root: Path):
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = temp_store
    ingestion_module.knowledge_metadata_store = temp_store
    retrieval_service_module.knowledge_metadata_store = temp_store
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = EVAL_COLLECTION
    vector_store_manager.collection_name = EVAL_COLLECTION
    vector_store_manager.vector_store = None
    return temp_store


def index_artifact(
    tmp_root: Path,
    category: str,
    stem: str,
    file_name: str,
    index_service: vector_index_module.VectorIndexService,
    metadata_store: KnowledgeMetadataStore,
) -> str:
    src_dir = ARTIFACT_BASE / category / stem
    doc_id = f"doc_p5_long_{stem}"
    artifact_dir = tmp_root / "artifacts" / doc_id / "artifacts"
    original_dir = tmp_root / "artifacts" / doc_id / "original"
    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, artifact_dir, dirs_exist_ok=True)
    original_path = original_dir / file_name
    original_path.write_bytes(b"%PDF-1.4 placeholder")
    record = DocumentRecord(
        doc_id=doc_id,
        kb_id="default",
        file_name=file_name,
        file_ext="pdf",
        original_path=original_path.as_posix(),
        artifact_dir=artifact_dir.as_posix(),
        parser_engine=ParserEngine.MINERU,
        status=DocumentStatus.PARSED,
        parser_version="mineru-3.1.11",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    artifact_manifest_service.write_manifest(record)
    metadata_store.upsert_document(record)
    index_service.index_document_record(record)
    return doc_id


def index_corpus(
    tmp_root: Path,
    index_service: vector_index_module.VectorIndexService,
    metadata_store: KnowledgeMetadataStore,
) -> dict[str, str]:
    file_to_doc_id: dict[str, str] = {}
    for category, stem, file_name in TARGETS:
        doc_id = index_artifact(tmp_root, category, stem, file_name, index_service, metadata_store)
        file_to_doc_id[stem] = doc_id
    return file_to_doc_id


def _result_signature(result) -> dict[str, Any]:
    """Identity payload used for §4 byte-equality assertions."""
    return {
        "chunk_id": result.chunk_id,
        "content": result.content,
        "citation_text": result.citation_text,
        "source_ref": result.source_ref.model_dump(mode="json"),
    }


def evaluate_sample(
    sample: dict[str, Any],
    file_name_to_doc_id: dict[str, str],
    tokenizer,
    top_k: int,
    top_chunks_per_doc: int,
    oversample_factor: int,
) -> dict[str, Any]:
    """Run pool + 6-way matrix retrieval for one sample, return structured row.

    Matrix: {NONE, DOC_LEVEL} × {chunk, parent_chunk, full_doc} = 6 cells.
    Pool is one shared NONE@pool_k chunk-granularity recall used by §4(1)/(2).
    """
    expected_doc_ids = [
        file_name_to_doc_id.get(f.replace(".pdf", ""), "")
        for f in sample.get("expected_doc_files", [])
    ]
    expected_doc_ids = [d for d in expected_doc_ids if d]
    keywords = sample.get("expected_keywords", [])

    pool_k = max(top_k * oversample_factor, top_k)
    pool_query = RetrievalQuery(
        query=sample["query"],
        top_k=pool_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=["default"],
        result_aggregation=ResultAggregation.NONE,
        context_granularity=ContextGranularity.CHUNK,
    )
    response_pool = retrieval_service_module.retrieval_service.retrieve(pool_query)
    pool_results = response_pool.results
    pool_chunk_id_set = {r.chunk_id for r in pool_results}
    pool_signatures = {r.chunk_id: _result_signature(r) for r in pool_results}

    cells: dict[str, dict[str, Any]] = {}
    for strategy in STRATEGIES:
        for granularity in GRANULARITIES:
            cell_key = f"{strategy.value}__{granularity.value}"
            q = RetrievalQuery(
                query=sample["query"],
                top_k=top_k,
                retrieval_mode=RetrievalMode.DENSE_ONLY,
                knowledge_base_ids=["default"],
                result_aggregation=strategy,
                top_chunks_per_doc=top_chunks_per_doc,
                doc_oversample_factor=oversample_factor,
                context_granularity=granularity,
            )
            start = time.perf_counter()
            resp = retrieval_service_module.retrieval_service.retrieve(q)
            latency_ms = int((time.perf_counter() - start) * 1000)
            cells[cell_key] = _summarize_cell(
                resp, strategy, granularity, tokenizer, keywords,
                expected_doc_ids, latency_ms,
            )

    _assert_invariants(sample, cells, pool_chunk_id_set, pool_signatures,
                       top_k, top_chunks_per_doc)

    pool_summary = {
        "pool_k": pool_k,
        "size": len(pool_results),
        "distinct_doc_count": len({r.doc_id for r in pool_results}),
        "top_doc_hit_share": (
            max(Counter(r.doc_id for r in pool_results).values()) / len(pool_results)
            if pool_results else 0.0
        ),
        "doc_id_counts": dict(Counter(r.doc_id for r in pool_results)),
    }
    return {
        "id": sample["id"],
        "category": sample["category"],
        "query": sample["query"],
        "expected_doc_ids": expected_doc_ids,
        "expected_keywords": keywords,
        "pool": pool_summary,
        "cells": cells,
    }


def _summarize_cell(
    response,
    strategy: ResultAggregation,
    granularity: ContextGranularity,
    tokenizer,
    keywords: list[str],
    expected_doc_ids: list[str],
    latency_ms: int,
) -> dict[str, Any]:
    """Per-cell metrics + identity payloads needed for §4 / §6 assertions."""
    results = list(response.results)
    chunk_ids = [r.chunk_id for r in results]
    doc_ids = [r.doc_id for r in results]
    top1_doc = doc_ids[0] if doc_ids else ""
    top1_match = 1 if top1_doc and top1_doc in expected_doc_ids else 0
    distinct_doc_count = len(set(doc_ids))
    tokens = (
        len(tokenizer.encode(response.context_text)) if response.context_text else 0
    )
    keyword_coverage = (
        sum(1 for kw in keywords if kw and kw in response.context_text)
        / max(len(keywords), 1)
    )
    fallbacks = [
        r.metadata.get("context_granularity_fallback") for r in results
    ]
    fallback_count = sum(1 for f in fallbacks if f)
    fallback_rate = fallback_count / max(len(results), 1)
    fallback_reasons = dict(Counter(f for f in fallbacks if f))
    signatures = {r.chunk_id: _result_signature(r) for r in results}
    aggregation_metadata = []
    if strategy == ResultAggregation.DOC_LEVEL:
        aggregation_metadata = [
            {
                "chunk_id": r.chunk_id,
                "doc_hit_count": r.metadata.get("aggregation_doc_hit_count"),
                "doc_max_score": r.metadata.get("aggregation_doc_max_score"),
                "dropped_chunk_ids": r.metadata.get("aggregation_dropped_chunk_ids"),
            }
            for r in results
        ]
    return {
        "strategy": strategy.value,
        "granularity": granularity.value,
        "chunk_ids": chunk_ids,
        "doc_ids": doc_ids,
        "distinct_doc_count": distinct_doc_count,
        "top1_doc_id": top1_doc,
        "top1_doc_match": top1_match,
        "tokens": tokens,
        "keyword_coverage": keyword_coverage,
        "fallback_count": fallback_count,
        "fallback_rate": fallback_rate,
        "fallback_reasons": fallback_reasons,
        "latency_ms": latency_ms,
        "aggregation_metadata": aggregation_metadata,
        "_signatures": signatures,
    }


def _assert_invariants(
    sample: dict[str, Any],
    cells: dict[str, dict[str, Any]],
    pool_chunk_id_set: set[str],
    pool_signatures: dict[str, dict[str, Any]],
    top_k: int,
    top_chunks_per_doc: int,
) -> None:
    """§4 (6 conditions) on the 6-cell matrix.

    1. DL chunk_ids ⊆ pool chunk_ids (per granularity)
    2. NONE chunk_ids ⊆ pool chunk_ids (per granularity)
    3. DL each result's identity fields byte-equal to the same chunk_id's
       hit in the pool (per granularity)
    4. DL len ≤ top_k * top_chunks_per_doc; per-doc count ≤ top_chunks_per_doc
    5. Same chunk_id appearing in ≥ 2 of the 6 cells has byte-equal
       chunk_id / content / source_ref / citation_text
    6. NONE × {chunk, parent_chunk, full_doc} return identical ordered
       chunk_id lists; DOC_LEVEL × {chunk, parent_chunk, full_doc} likewise
    """
    sid = sample["id"]
    sample_max = top_k * top_chunks_per_doc

    # §4(1) and §4(2)
    for granularity in GRANULARITIES:
        for strategy_name, label in (("none", "§4(2) NONE"), ("doc_level", "§4(1) DL")):
            cell = cells[f"{strategy_name}__{granularity.value}"]
            extra = set(cell["chunk_ids"]) - pool_chunk_id_set
            if extra:
                raise AssertionError(
                    f"{label} violated on sample {sid} granularity={granularity.value}: "
                    f"chunk_ids outside candidate pool: {extra}"
                )

    # §4(3): DL identity fields byte-equal to pool entry
    # Note: pool is built at chunk granularity. The signatures captured
    # in DL cells reflect identity AFTER context_text formatting on that
    # cell's granularity, but the identity payload itself (chunk_id /
    # content / source_ref / citation_text) is granularity-independent
    # (P4.5 §1.2). So they must match the pool's identity exactly.
    for granularity in GRANULARITIES:
        cell = cells[f"doc_level__{granularity.value}"]
        for chunk_id, sig in cell["_signatures"].items():
            ref = pool_signatures.get(chunk_id)
            if ref is None:
                raise AssertionError(
                    f"§4(3) violated on sample {sid}: DL granularity={granularity.value} "
                    f"chunk_id {chunk_id} missing from pool"
                )
            if sig != ref:
                raise AssertionError(
                    f"§4(3) violated on sample {sid}: DL granularity={granularity.value} "
                    f"chunk_id {chunk_id} identity mismatch with pool"
                )

    # §4(4)
    for granularity in GRANULARITIES:
        cell = cells[f"doc_level__{granularity.value}"]
        if len(cell["chunk_ids"]) > sample_max:
            raise AssertionError(
                f"§4(4a) violated on sample {sid} granularity={granularity.value}: "
                f"len={len(cell['chunk_ids'])} > {sample_max}"
            )
        per_doc = Counter(cell["doc_ids"])
        over = {d: c for d, c in per_doc.items() if c > top_chunks_per_doc}
        if over:
            raise AssertionError(
                f"§4(4b) violated on sample {sid} granularity={granularity.value}: {over}"
            )

    # §4(5): cross-granularity identity stability for the same chunk_id.
    # Build chunk_id -> list of (cell_key, signature) and require all
    # signatures equal per chunk_id.
    by_chunk_id: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for cell_key, cell in cells.items():
        for chunk_id, sig in cell["_signatures"].items():
            by_chunk_id.setdefault(chunk_id, []).append((cell_key, sig))
    for chunk_id, entries in by_chunk_id.items():
        if len(entries) < 2:
            continue
        ref_key, ref_sig = entries[0]
        for other_key, other_sig in entries[1:]:
            if other_sig != ref_sig:
                raise AssertionError(
                    f"§4(5) violated on sample {sid}: chunk_id {chunk_id} differs across cells "
                    f"({ref_key} vs {other_key}); granularity must not mutate identity fields"
                )

    # §4(6): ordered chunk_id list invariance per strategy across granularities.
    for strategy in STRATEGIES:
        ordered_lists: dict[str, list[str]] = {}
        for granularity in GRANULARITIES:
            ordered_lists[granularity.value] = cells[
                f"{strategy.value}__{granularity.value}"
            ]["chunk_ids"]
        chunk_list = ordered_lists["chunk"]
        for granularity_name, other_list in ordered_lists.items():
            if granularity_name == "chunk":
                continue
            if other_list != chunk_list:
                raise AssertionError(
                    f"§4(6) violated on sample {sid}: strategy={strategy.value} "
                    f"chunk granularity returned {chunk_list} but "
                    f"{granularity_name} returned {other_list} (P4.5 ordered-list invariance)"
                )


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-cell aggregate stats across all 18 samples + per-category breakdown."""

    def percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = max(0, int(len(sorted_values) * pct) - 1)
        return sorted_values[index]

    summary: dict[str, Any] = {
        "total_samples": len(rows),
        "by_cell": {},
        "by_category": {},
    }
    cell_keys = [
        f"{strategy.value}__{granularity.value}"
        for strategy in STRATEGIES
        for granularity in GRANULARITIES
    ]
    for cell_key in cell_keys:
        token_values = [r["cells"][cell_key]["tokens"] for r in rows]
        distinct_values = [r["cells"][cell_key]["distinct_doc_count"] for r in rows]
        match_values = [r["cells"][cell_key]["top1_doc_match"] for r in rows]
        cov_values = [r["cells"][cell_key]["keyword_coverage"] for r in rows]
        fallback_values = [r["cells"][cell_key]["fallback_rate"] for r in rows]
        latency_values = [r["cells"][cell_key]["latency_ms"] for r in rows]
        summary["by_cell"][cell_key] = {
            "tokens_avg": statistics.mean(token_values) if token_values else 0.0,
            "tokens_p95": percentile(token_values, 0.95),
            "tokens_max": max(token_values) if token_values else 0,
            "distinct_doc_count_avg": (
                statistics.mean(distinct_values) if distinct_values else 0.0
            ),
            "top1_doc_match_avg": statistics.mean(match_values) if match_values else 0.0,
            "keyword_coverage_avg": statistics.mean(cov_values) if cov_values else 0.0,
            "fallback_rate_avg": statistics.mean(fallback_values) if fallback_values else 0.0,
            "latency_ms_avg": statistics.mean(latency_values) if latency_values else 0.0,
        }

    for category in CATEGORIES:
        cat_rows = [r for r in rows if r["category"] == category]
        if not cat_rows:
            summary["by_category"][category] = {"sample_count": 0}
            continue
        cat_summary: dict[str, Any] = {"sample_count": len(cat_rows)}
        for cell_key in cell_keys:
            cat_summary[f"tokens_avg_{cell_key}"] = statistics.mean(
                [r["cells"][cell_key]["tokens"] for r in cat_rows]
            )
            cat_summary[f"distinct_doc_count_avg_{cell_key}"] = statistics.mean(
                [r["cells"][cell_key]["distinct_doc_count"] for r in cat_rows]
            )
            cat_summary[f"top1_doc_match_avg_{cell_key}"] = statistics.mean(
                [r["cells"][cell_key]["top1_doc_match"] for r in cat_rows]
            )
        summary["by_category"][category] = cat_summary
    return summary


def token_threshold_judgement(summary: dict[str, Any]) -> dict[str, Any]:
    """Per-granularity token thresholds (frozen pre-run).

    chunk:        DL ≤ 4000 AND DL/NONE ≤ 2.0 (both required to pass)
    parent_chunk: DL ≤ 6000 AND DL/NONE ≤ 2.0 (both required to pass)
    full_doc:     DL/NONE ≤ 1.5 ONLY; DL absolute is SOFT OBSERVATION (no pass/fail)
    """
    by_cell = summary["by_cell"]
    judgements: dict[str, Any] = {}
    for granularity in GRANULARITIES:
        gname = granularity.value
        none_avg = by_cell[f"none__{gname}"]["tokens_avg"]
        dl_avg = by_cell[f"doc_level__{gname}"]["tokens_avg"]
        ratio = (dl_avg / none_avg) if none_avg > 0 else 0.0
        thresholds = TOKEN_THRESHOLDS[gname]
        abs_max = thresholds["abs_max"]
        rel_max = thresholds["rel_max"]
        if abs_max is None:
            abs_pass = None  # not applicable
        else:
            abs_pass = dl_avg <= abs_max
        rel_pass = ratio <= rel_max
        if thresholds["abs_pass_required"]:
            cell_pass = bool(abs_pass) and bool(rel_pass)
        else:
            cell_pass = bool(rel_pass)
        judgements[gname] = {
            "none_tokens_avg": none_avg,
            "dl_tokens_avg": dl_avg,
            "ratio_dl_over_none": ratio,
            "abs_max_threshold": abs_max,
            "rel_max_threshold": rel_max,
            "abs_pass": abs_pass,
            "rel_pass": rel_pass,
            "cell_pass": cell_pass,
            "abs_pass_required": thresholds["abs_pass_required"],
        }
    judgements["overall_passed"] = all(j["cell_pass"] for j in judgements.values())
    # Soft observation per user directive: highlight full_doc absolute DL token
    # value even though it's not a pass/fail threshold.
    judgements["soft_observations"] = {
        "full_doc_dl_tokens_avg_absolute": judgements["full_doc"]["dl_tokens_avg"],
        "full_doc_dl_tokens_max": by_cell["doc_level__full_doc"]["tokens_max"],
        "full_doc_dl_tokens_p95": by_cell["doc_level__full_doc"]["tokens_p95"],
    }
    return judgements


def joint_amplification(summary: dict[str, Any]) -> dict[str, Any]:
    """joint_amplification(g) = (DL_avg(g)/DL_avg(chunk)) / (NONE_avg(g)/NONE_avg(chunk)).

    > 1.0 means dedup amplifies granularity's token cost (joint hazard).
    < 1.0 means dedup mitigates granularity's token cost.
    Soft observation only; no pass/fail per user directive E1.
    """
    by_cell = summary["by_cell"]
    none_chunk = by_cell["none__chunk"]["tokens_avg"]
    dl_chunk = by_cell["doc_level__chunk"]["tokens_avg"]
    metrics: dict[str, Any] = {
        "definition": (
            "joint_amplification(g) = (DL_avg(g)/DL_avg(chunk)) / "
            "(NONE_avg(g)/NONE_avg(chunk)); >1.0 = dedup amplifies granularity"
        ),
        "by_granularity": {},
    }
    for granularity in GRANULARITIES:
        gname = granularity.value
        none_g = by_cell[f"none__{gname}"]["tokens_avg"]
        dl_g = by_cell[f"doc_level__{gname}"]["tokens_avg"]
        none_ratio = (none_g / none_chunk) if none_chunk > 0 else 0.0
        dl_ratio = (dl_g / dl_chunk) if dl_chunk > 0 else 0.0
        amp = (dl_ratio / none_ratio) if none_ratio > 0 else 0.0
        metrics["by_granularity"][gname] = {
            "none_g_over_chunk": none_ratio,
            "dl_g_over_chunk": dl_ratio,
            "joint_amplification": amp,
        }
    return metrics


def fallback_observation(summary: dict[str, Any]) -> dict[str, Any]:
    """Per-cell fallback rate. Soft observation only (no pass/fail)."""
    by_cell = summary["by_cell"]
    obs: dict[str, Any] = {}
    for strategy in STRATEGIES:
        for granularity in GRANULARITIES:
            cell_key = f"{strategy.value}__{granularity.value}"
            obs[cell_key] = by_cell[cell_key]["fallback_rate_avg"]
    return obs


def p5_f1_sanity_reproduction(summary: dict[str, Any]) -> dict[str, Any]:
    """Verify NONE×chunk and DL×chunk reproduce P5.f1 baseline within tolerance.

    Drift here means P5.f2 plumbing changed something at chunk granularity,
    which would invalidate the joint comparison.
    """
    none_chunk = summary["by_cell"]["none__chunk"]["tokens_avg"]
    dl_chunk = summary["by_cell"]["doc_level__chunk"]["tokens_avg"]
    none_drift = abs(none_chunk - P5_F1_BASELINE["none_chunk_tokens_avg"])
    dl_drift = abs(dl_chunk - P5_F1_BASELINE["doc_level_chunk_tokens_avg"])
    return {
        "p5_f1_none_chunk_tokens_avg": P5_F1_BASELINE["none_chunk_tokens_avg"],
        "p5_f2_none_chunk_tokens_avg": none_chunk,
        "none_chunk_drift": none_drift,
        "p5_f1_doc_level_chunk_tokens_avg": P5_F1_BASELINE["doc_level_chunk_tokens_avg"],
        "p5_f2_doc_level_chunk_tokens_avg": dl_chunk,
        "doc_level_chunk_drift": dl_drift,
        "tolerance": SANITY_TOKENS_TOLERANCE,
        "passed": (
            none_drift <= SANITY_TOKENS_TOLERANCE
            and dl_drift <= SANITY_TOKENS_TOLERANCE
        ),
    }


# Restated from P5.f1 (G: not re-checked since granularity does not affect pool).
P5_F1_D1_ANCHOR = {
    "factor_enough": True,
    "saturation_ratio": 0.0,
    "saturated_samples": 0,
    "total_same_doc_samples": 6,
    "triggers_p5_f4_param_tuning": False,
    "source_report": "evals/rag_retrieval/reports/p5_long_doc_eval_20260518_224445.json",
    "rationale": (
        "D1 not re-checked in P5.f2 because granularity does not affect the "
        "candidate pool (pool is always assembled at chunk granularity). "
        "P5.f1 D1 conclusion is restated here as a sanity anchor."
    ),
}


def format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# P5.f2 joint evaluation report (DOC_LEVEL × granularity)")
    lines.append("")
    lines.append(f"- generated_at: {report['generated_at']}")
    lines.append(f"- collection: `{report['collection']}`")
    lines.append(f"- sample_count: {report['summary']['total_samples']}")
    lines.append(f"- top_k: {report['top_k']}")
    lines.append(f"- top_chunks_per_doc: {report['top_chunks_per_doc']}")
    lines.append(f"- doc_oversample_factor: {report['doc_oversample_factor']}")
    lines.append(f"- §4 invariants_all_ok: {report['invariants_all_ok']}")
    lines.append(f"- token threshold overall_passed: {report['token_judgement']['overall_passed']}")
    lines.append(f"- P5.f1 sanity reproduction: {report['sanity']['passed']}")
    lines.append("")

    lines.append("## Corpus")
    for stem, doc_id in report["doc_ids"].items():
        lines.append(f"- {stem} -> {doc_id}")
    lines.append("")

    lines.append("## Token threshold judgement (frozen pre-run)")
    tj = report["token_judgement"]
    lines.append(
        "| granularity | NONE avg | DL avg | ratio | abs_max | rel_max | abs_pass | rel_pass | cell_pass |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for granularity in GRANULARITIES:
        gname = granularity.value
        j = tj[gname]
        abs_max_str = f"{j['abs_max_threshold']}" if j['abs_max_threshold'] is not None else "n/a (soft)"
        abs_pass_str = "n/a" if j['abs_pass'] is None else str(j['abs_pass'])
        lines.append(
            f"| {gname} | {j['none_tokens_avg']:.1f} | {j['dl_tokens_avg']:.1f} | "
            f"{j['ratio_dl_over_none']:.2f} | {abs_max_str} | {j['rel_max_threshold']} | "
            f"{abs_pass_str} | {j['rel_pass']} | **{j['cell_pass']}** |"
        )
    lines.append("")

    so = tj["soft_observations"]
    lines.append("### SOFT OBSERVATION: full_doc absolute DL token cost")
    lines.append(
        f"- full_doc DL tokens_avg = **{so['full_doc_dl_tokens_avg_absolute']:.1f}** "
        f"(no pass/fail threshold; surfaced per user directive to avoid hiding the absolute cost)"
    )
    lines.append(f"- full_doc DL tokens_p95 = {so['full_doc_dl_tokens_p95']}")
    lines.append(f"- full_doc DL tokens_max = {so['full_doc_dl_tokens_max']}")
    lines.append("")

    lines.append("## 6-cell summary")
    lines.append(
        "| cell | tokens_avg | tokens_p95 | tokens_max | distinct_avg | top1_match_avg | keyword_cov_avg | fallback_rate_avg |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for strategy in STRATEGIES:
        for granularity in GRANULARITIES:
            cell_key = f"{strategy.value}__{granularity.value}"
            m = report["summary"]["by_cell"][cell_key]
            lines.append(
                f"| {cell_key} | {m['tokens_avg']:.1f} | {m['tokens_p95']:.0f} | "
                f"{m['tokens_max']} | {m['distinct_doc_count_avg']:.2f} | "
                f"{m['top1_doc_match_avg']:.3f} | {m['keyword_coverage_avg']:.3f} | "
                f"{m['fallback_rate_avg']:.3f} |"
            )
    lines.append("")

    lines.append("## Joint amplification (soft observation)")
    ja = report["joint_amplification"]
    lines.append(f"- definition: {ja['definition']}")
    lines.append("")
    lines.append("| granularity | NONE g/chunk | DL g/chunk | joint_amplification |")
    lines.append("|---|---|---|---|")
    for granularity in GRANULARITIES:
        m = ja["by_granularity"][granularity.value]
        lines.append(
            f"| {granularity.value} | {m['none_g_over_chunk']:.3f} | "
            f"{m['dl_g_over_chunk']:.3f} | {m['joint_amplification']:.3f} |"
        )
    lines.append("")

    lines.append("## Fallback rate observation (soft)")
    for cell_key, rate in report["fallback_observation"].items():
        lines.append(f"- {cell_key}: {rate:.3f}")
    lines.append("")

    lines.append("## P5.f1 sanity reproduction")
    s = report["sanity"]
    lines.append(
        f"- NONE×chunk tokens_avg: P5.f1 = {s['p5_f1_none_chunk_tokens_avg']:.4f}, "
        f"P5.f2 = {s['p5_f2_none_chunk_tokens_avg']:.4f}, "
        f"drift = {s['none_chunk_drift']:.4f} (tolerance {s['tolerance']})"
    )
    lines.append(
        f"- DL×chunk   tokens_avg: P5.f1 = {s['p5_f1_doc_level_chunk_tokens_avg']:.4f}, "
        f"P5.f2 = {s['p5_f2_doc_level_chunk_tokens_avg']:.4f}, "
        f"drift = {s['doc_level_chunk_drift']:.4f} (tolerance {s['tolerance']})"
    )
    lines.append(f"- sanity_passed: **{s['passed']}**")
    lines.append("")

    lines.append("## P5.f1 D1 anchor (not re-checked, restated)")
    d1 = report["d1_anchor"]
    lines.append(f"- factor_enough: {d1['factor_enough']}")
    lines.append(
        f"- saturated_samples: {d1['saturated_samples']}/{d1['total_same_doc_samples']} "
        f"(ratio={d1['saturation_ratio']:.2f})"
    )
    lines.append(f"- triggers_p5_f4_param_tuning: {d1['triggers_p5_f4_param_tuning']}")
    lines.append(f"- rationale: {d1['rationale']}")
    lines.append("")

    lines.append("## Per-sample compact (chunk_ids reproduce per §4(6); tokens shown per cell)")
    lines.append(
        "| id | category | NONE tok (c/p/f) | DL tok (c/p/f) | DL distinct (c/p/f) |"
    )
    lines.append("|---|---|---|---|---|")
    for row in report["rows"]:
        c = row["cells"]
        n_tokens = (
            f"{c['none__chunk']['tokens']}/"
            f"{c['none__parent_chunk']['tokens']}/"
            f"{c['none__full_doc']['tokens']}"
        )
        d_tokens = (
            f"{c['doc_level__chunk']['tokens']}/"
            f"{c['doc_level__parent_chunk']['tokens']}/"
            f"{c['doc_level__full_doc']['tokens']}"
        )
        d_distinct = (
            f"{c['doc_level__chunk']['distinct_doc_count']}/"
            f"{c['doc_level__parent_chunk']['distinct_doc_count']}/"
            f"{c['doc_level__full_doc']['distinct_doc_count']}"
        )
        lines.append(
            f"| {row['id']} | {row['category']} | {n_tokens} | {d_tokens} | {d_distinct} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def run() -> dict[str, Any]:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    samples = load_samples(SAMPLES_PATH)
    tokenizer = _qwen_tokenizer()

    o_coll = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    o_vname = vector_store_manager.collection_name
    o_vstore = vector_store_manager.vector_store
    o_idx_store = vector_index_module.knowledge_metadata_store
    o_ing_store = ingestion_module.knowledge_metadata_store
    o_ret_store = retrieval_service_module.knowledge_metadata_store
    o_rerank = rerank_service.enabled

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_store = setup_isolated(tmp_root)
        try:
            index_service = vector_index_module.VectorIndexService()
            stem_to_doc_id = index_corpus(tmp_root, index_service, temp_store)
            file_name_to_doc_id = {stem: did for stem, did in stem_to_doc_id.items()}

            rows = [
                evaluate_sample(
                    s, file_name_to_doc_id, tokenizer,
                    DEFAULT_TOP_K, DEFAULT_TOP_CHUNKS_PER_DOC, DEFAULT_OVERSAMPLE,
                )
                for s in samples
            ]
            invariants_all_ok = True  # any failed assertion would have raised
            summary = aggregate_metrics(rows)
            tj = token_threshold_judgement(summary)
            ja = joint_amplification(summary)
            fb = fallback_observation(summary)
            sanity = p5_f1_sanity_reproduction(summary)

            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": EVAL_COLLECTION,
                "tokenizer": "dashscope.qwen-max",
                "top_k": DEFAULT_TOP_K,
                "top_chunks_per_doc": DEFAULT_TOP_CHUNKS_PER_DOC,
                "doc_oversample_factor": DEFAULT_OVERSAMPLE,
                "doc_ids": stem_to_doc_id,
                "summary": summary,
                "token_judgement": tj,
                "joint_amplification": ja,
                "fallback_observation": fb,
                "sanity": sanity,
                "d1_anchor": P5_F1_D1_ANCHOR,
                "invariants_all_ok": invariants_all_ok,
                "rows": rows,
            }
            report_json = REPORT_DIR / f"p5_joint_eval_{RUN_ID}.json"
            report_md = REPORT_DIR / f"p5_joint_eval_{RUN_ID}.md"
            write_json(report_json, report)
            report_md.write_text(format_markdown(report), encoding="utf-8")

            output = {
                "samples": str(SAMPLES_PATH),
                "report_json": str(report_json),
                "report_md": str(report_md),
                "invariants_all_ok": invariants_all_ok,
                "token_judgement_overall_passed": tj["overall_passed"],
                "token_judgement_per_granularity": {
                    g.value: tj[g.value]["cell_pass"] for g in GRANULARITIES
                },
                "soft_observations": {
                    "joint_amplification": {
                        g.value: ja["by_granularity"][g.value]["joint_amplification"]
                        for g in GRANULARITIES
                    },
                    "full_doc_dl_tokens_avg_absolute": tj["soft_observations"][
                        "full_doc_dl_tokens_avg_absolute"
                    ],
                    "fallback_rate_avg": fb,
                },
                "sanity_passed": sanity["passed"],
                "d1_anchor_factor_enough": P5_F1_D1_ANCHOR["factor_enough"],
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return report
        finally:
            rerank_service.enabled = o_rerank
            vector_index_module.knowledge_metadata_store = o_idx_store
            ingestion_module.knowledge_metadata_store = o_ing_store
            retrieval_service_module.knowledge_metadata_store = o_ret_store
            vector_store_manager.vector_store = None
            vector_store_manager.collection_name = o_vname
            milvus_client_module.MilvusClientManager.COLLECTION_NAME = o_coll
            try:
                if utility.has_collection(EVAL_COLLECTION):
                    utility.drop_collection(EVAL_COLLECTION)
            except Exception:
                pass
            vector_store_manager.vector_store = o_vstore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run P5.f2 joint evaluation.")
    return p.parse_args()


def main() -> int:
    parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
