#!/usr/bin/env python3
"""P5 long-doc follow-up evaluation (P6 prerequisite step P5.f1).

Indexes 3 MinerU long-doc artifacts (h3c_campus, h3c_mc101, arxiv_vit) into
an isolated Milvus collection + isolated KnowledgeMetadataStore, then runs
20 samples (6 same_doc_redundant / 6 cross_doc_already / 6 reverse_control)
under three retrieval strategies:

  Pool:      NONE @ pool_k = top_k * doc_oversample_factor (default 12)
  NONE:      NONE @ top_k (default 3) -- baseline strategy
  DOC_LEVEL: DOC_LEVEL @ top_k -- dedup strategy

Hard assertions (P5 design §4, frozen pre-run):
  1. set(returned_chunk_ids_doc_level) ⊆ set(candidate_pool_chunk_ids)
  2. set(returned_chunk_ids_none)      ⊆ set(candidate_pool_chunk_ids)
  3. For each chunk_id in DOC_LEVEL.results, citation_text / source_ref /
     content are byte-equal to the same chunk_id's hit in the candidate pool.
  4. len(results_doc_level) ≤ top_k * top_chunks_per_doc and per-doc count ≤
     top_chunks_per_doc.

Per-category discrimination (P5 design §9, F3 = unchanged from main P5 eval):
  same_doc_redundant: ≥ 70% samples distinct_doc_count(DOC_LEVEL) > NONE
  cross_doc_already:  ≥ 70% samples distinct_doc_count(DOC_LEVEL) == NONE
  reverse_control:    top1_doc_match degradation ratio ≤ 10%

NEW thresholds for long-doc follow-up (frozen pre-run per user F3 directive):

  D1 pool-signal "factor=4 enough?" judgement:
    If ≥ 30% of same_doc_redundant samples have pool top_doc_hit_share == 1.0
    (candidate pool entirely from one doc -> dedup has no doc to swap to),
    flag factor=4 as not enough. This triggers P5.f4 parameter tuning as
    follow-up work; it does NOT block this run from being marked complete.

  E3 token cost dual threshold:
    (a) DOC_LEVEL tokens_avg ≤ 4000
    (b) DOC_LEVEL tokens_avg / NONE tokens_avg ≤ 2.0
    Both must hold for token cost to be acceptable. If either fails, the
    run still completes but the report flags long-doc DOC_LEVEL token cost
    as unacceptable at default parameters.

Per user execution stipulation: this script does not change P5 implementation
under any condition. If §4 invariants fail, the run aborts via AssertionError.
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
SAMPLES_PATH = EVAL_DIR / "p5_long_doc_samples.jsonl"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
EVAL_COLLECTION = f"p5_long_doc_eval_{RUN_ID}"

DEFAULT_TOP_K = 3
DEFAULT_TOP_CHUNKS_PER_DOC = 1
DEFAULT_OVERSAMPLE = 4
CATEGORIES = ["same_doc_redundant", "cross_doc_already", "reverse_control"]

ARTIFACT_BASE = Path(
    "/Users/cici/oncall agent/pdf_eval/outputs/postprocessed/mineru/expanded_corpus"
)
TARGETS = [
    ("manuals", "h3c_campus_switch_installation_guide_cn",
     "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "h3c_mc101_mc102_user_manual_cn",
     "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("papers", "arxiv_vision_transformer",
     "arxiv_vision_transformer.pdf"),
]


def _qwen_tokenizer():
    from dashscope.tokenizers.tokenizer import get_tokenizer

    return get_tokenizer(config.rag_model)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"P5 long-doc samples not found: {path}")
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        samples.append(json.loads(line))
    if not samples:
        raise ValueError(f"P5 long-doc samples empty: {path}")
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
    """Index 3 long-doc artifacts. Returns stem -> doc_id mapping."""
    file_to_doc_id: dict[str, str] = {}
    for category, stem, file_name in TARGETS:
        doc_id = index_artifact(tmp_root, category, stem, file_name, index_service, metadata_store)
        file_to_doc_id[stem] = doc_id
    return file_to_doc_id


def _result_signature(result) -> dict[str, Any]:
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
    pool_chunk_ids = [r.chunk_id for r in pool_results]
    pool_signatures = {r.chunk_id: _result_signature(r) for r in pool_results}

    none_query = RetrievalQuery(
        query=sample["query"],
        top_k=top_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=["default"],
        result_aggregation=ResultAggregation.NONE,
        context_granularity=ContextGranularity.CHUNK,
    )
    start = time.perf_counter()
    response_none = retrieval_service_module.retrieval_service.retrieve(none_query)
    latency_none = int((time.perf_counter() - start) * 1000)

    dl_query = RetrievalQuery(
        query=sample["query"],
        top_k=top_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=["default"],
        result_aggregation=ResultAggregation.DOC_LEVEL,
        top_chunks_per_doc=top_chunks_per_doc,
        doc_oversample_factor=oversample_factor,
        context_granularity=ContextGranularity.CHUNK,
    )
    start = time.perf_counter()
    response_dl = retrieval_service_module.retrieval_service.retrieve(dl_query)
    latency_dl = int((time.perf_counter() - start) * 1000)

    none_chunk_ids = [r.chunk_id for r in response_none.results]
    dl_chunk_ids = [r.chunk_id for r in response_dl.results]
    pool_chunk_id_set = set(pool_chunk_ids)

    if not set(dl_chunk_ids).issubset(pool_chunk_id_set):
        raise AssertionError(
            f"P5 §4(1) violated on sample {sample['id']}: extra="
            f"{set(dl_chunk_ids) - pool_chunk_id_set}"
        )
    if not set(none_chunk_ids).issubset(pool_chunk_id_set):
        raise AssertionError(
            f"P5 §4(2) violated on sample {sample['id']}: extra="
            f"{set(none_chunk_ids) - pool_chunk_id_set}"
        )
    for r in response_dl.results:
        ref = pool_signatures[r.chunk_id]
        actual = _result_signature(r)
        if actual != ref:
            raise AssertionError(
                f"P5 §4(3) violated on sample {sample['id']} chunk_id {r.chunk_id}"
            )
    if len(response_dl.results) > top_k * top_chunks_per_doc:
        raise AssertionError(
            f"P5 §4(4a) violated on sample {sample['id']}: "
            f"len={len(response_dl.results)} > {top_k * top_chunks_per_doc}"
        )
    per_doc_count = Counter(r.doc_id for r in response_dl.results)
    over = {d: c for d, c in per_doc_count.items() if c > top_chunks_per_doc}
    if over:
        raise AssertionError(
            f"P5 §4(4b) violated on sample {sample['id']}: {over}"
        )

    distinct_doc_none = len({r.doc_id for r in response_none.results})
    distinct_doc_dl = len({r.doc_id for r in response_dl.results})
    none_top1_doc = response_none.results[0].doc_id if response_none.results else ""
    dl_top1_doc = response_dl.results[0].doc_id if response_dl.results else ""
    none_top1_match = 1 if none_top1_doc and none_top1_doc in expected_doc_ids else 0
    dl_top1_match = 1 if dl_top1_doc and dl_top1_doc in expected_doc_ids else 0
    pool_total = len(pool_chunk_ids)
    if pool_total > 0:
        pool_doc_hit_counts = Counter(r.doc_id for r in pool_results)
        top_doc_hit_share = max(pool_doc_hit_counts.values()) / pool_total
    else:
        top_doc_hit_share = 0.0
    pool_distinct_doc_count = len({r.doc_id for r in pool_results})

    none_tokens = (
        len(tokenizer.encode(response_none.context_text)) if response_none.context_text else 0
    )
    dl_tokens = (
        len(tokenizer.encode(response_dl.context_text)) if response_dl.context_text else 0
    )

    keyword_cov_none = (
        sum(1 for kw in keywords if kw and kw in response_none.context_text)
        / max(len(keywords), 1)
    )
    keyword_cov_dl = (
        sum(1 for kw in keywords if kw and kw in response_dl.context_text)
        / max(len(keywords), 1)
    )

    return {
        "id": sample["id"],
        "category": sample["category"],
        "query": sample["query"],
        "expected_doc_ids": expected_doc_ids,
        "expected_keywords": keywords,
        "pool": {
            "pool_k": pool_k,
            "size": pool_total,
            "distinct_doc_count": pool_distinct_doc_count,
            "top_doc_hit_share": top_doc_hit_share,
            "doc_id_counts": dict(Counter(r.doc_id for r in pool_results)),
            "chunk_ids": pool_chunk_ids,
        },
        "none": {
            "chunk_ids": none_chunk_ids,
            "doc_ids": [r.doc_id for r in response_none.results],
            "distinct_doc_count": distinct_doc_none,
            "top1_doc_id": none_top1_doc,
            "top1_doc_match": none_top1_match,
            "tokens": none_tokens,
            "keyword_coverage": keyword_cov_none,
            "latency_ms": latency_none,
        },
        "doc_level": {
            "chunk_ids": dl_chunk_ids,
            "doc_ids": [r.doc_id for r in response_dl.results],
            "distinct_doc_count": distinct_doc_dl,
            "top1_doc_id": dl_top1_doc,
            "top1_doc_match": dl_top1_match,
            "tokens": dl_tokens,
            "keyword_coverage": keyword_cov_dl,
            "latency_ms": latency_dl,
            "aggregation_metadata": [
                {
                    "chunk_id": r.chunk_id,
                    "doc_hit_count": r.metadata.get("aggregation_doc_hit_count"),
                    "doc_max_score": r.metadata.get("aggregation_doc_max_score"),
                    "dropped_chunk_ids": r.metadata.get("aggregation_dropped_chunk_ids"),
                }
                for r in response_dl.results
            ],
        },
        "distinct_doc_count_delta": distinct_doc_dl - distinct_doc_none,
        "top1_doc_match_degraded": (none_top1_match == 1 and dl_top1_match == 0),
        "tokens_ratio_dl_over_none": (dl_tokens / none_tokens) if none_tokens > 0 else 0.0,
    }


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def percentile(values, pct):
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = max(0, int(len(sorted_values) * pct) - 1)
        return sorted_values[index]

    summary: dict[str, Any] = {
        "total_samples": len(rows),
        "by_strategy": {},
        "by_category": {},
    }
    for strategy in ("none", "doc_level"):
        token_values = [r[strategy]["tokens"] for r in rows]
        distinct_values = [r[strategy]["distinct_doc_count"] for r in rows]
        match_values = [r[strategy]["top1_doc_match"] for r in rows]
        cov_values = [r[strategy]["keyword_coverage"] for r in rows]
        summary["by_strategy"][strategy] = {
            "tokens_avg": statistics.mean(token_values) if token_values else 0.0,
            "tokens_p95": percentile(token_values, 0.95),
            "tokens_max": max(token_values) if token_values else 0,
            "distinct_doc_count_avg": (
                statistics.mean(distinct_values) if distinct_values else 0.0
            ),
            "top1_doc_match_avg": statistics.mean(match_values) if match_values else 0.0,
            "keyword_coverage_avg": statistics.mean(cov_values) if cov_values else 0.0,
        }
    for category in CATEGORIES:
        cat_rows = [r for r in rows if r["category"] == category]
        if not cat_rows:
            summary["by_category"][category] = {"sample_count": 0}
            continue
        cat_summary: dict[str, Any] = {"sample_count": len(cat_rows)}
        for strategy in ("none", "doc_level"):
            cat_summary[f"distinct_doc_count_avg_{strategy}"] = statistics.mean(
                [r[strategy]["distinct_doc_count"] for r in cat_rows]
            )
            cat_summary[f"tokens_avg_{strategy}"] = statistics.mean(
                [r[strategy]["tokens"] for r in cat_rows]
            )
            cat_summary[f"top1_doc_match_avg_{strategy}"] = statistics.mean(
                [r[strategy]["top1_doc_match"] for r in cat_rows]
            )
        summary["by_category"][category] = cat_summary
    return summary


def discrimination_self_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """F3: identical thresholds to the main P5 eval (frozen pre-run)."""
    checks: dict[str, Any] = {}
    sd_rows = [r for r in rows if r["category"] == "same_doc_redundant"]
    if sd_rows:
        improved = sum(1 for r in sd_rows if r["distinct_doc_count_delta"] > 0)
        checks["same_doc_redundant"] = {
            "rule": "≥ 70% samples: distinct_doc_count(DOC_LEVEL) > NONE",
            "samples": len(sd_rows),
            "matching": improved,
            "ratio": improved / len(sd_rows),
            "passed": improved / len(sd_rows) >= 0.70,
        }
    cd_rows = [r for r in rows if r["category"] == "cross_doc_already"]
    if cd_rows:
        same = sum(1 for r in cd_rows if r["distinct_doc_count_delta"] == 0)
        checks["cross_doc_already"] = {
            "rule": "≥ 70% samples: distinct_doc_count(DOC_LEVEL) == NONE",
            "samples": len(cd_rows),
            "matching": same,
            "ratio": same / len(cd_rows),
            "passed": same / len(cd_rows) >= 0.70,
        }
    rc_rows = [r for r in rows if r["category"] == "reverse_control"]
    if rc_rows:
        degraded = sum(1 for r in rc_rows if r["top1_doc_match_degraded"])
        ratio = degraded / len(rc_rows)
        checks["reverse_control"] = {
            "rule": "top1_doc_match degradation ratio ≤ 10%",
            "samples": len(rc_rows),
            "matching": degraded,
            "ratio": ratio,
            "passed": ratio <= 0.10,
        }
    checks["overall_passed"] = all(c.get("passed") for c in checks.values() if isinstance(c, dict))
    return checks


def d1_oversample_judgement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """D1: is doc_oversample_factor=4 enough on long-doc corpus?"""
    sd_rows = [r for r in rows if r["category"] == "same_doc_redundant"]
    if not sd_rows:
        return {"applicable": False, "reason": "no same_doc_redundant samples"}
    saturated = sum(1 for r in sd_rows if r["pool"]["top_doc_hit_share"] >= 1.0)
    saturation_ratio = saturated / len(sd_rows)
    factor_enough = saturation_ratio < 0.30
    return {
        "applicable": True,
        "rule": (
            "factor=4 enough iff < 30% same_doc_redundant samples saturate "
            "(top_doc_hit_share == 1.0 means pool is from one doc only, "
            "dedup has no doc to swap to)"
        ),
        "saturated_samples": saturated,
        "total_same_doc_samples": len(sd_rows),
        "saturation_ratio": saturation_ratio,
        "factor_enough": factor_enough,
        "triggers_p5_f4_param_tuning": not factor_enough,
    }


def e3_token_judgement(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    """E3: dual token threshold (DL avg ≤ 4000 AND DL/NONE ≤ 2.0)."""
    dl_avg = summary["by_strategy"]["doc_level"]["tokens_avg"]
    none_avg = summary["by_strategy"]["none"]["tokens_avg"]
    abs_pass = dl_avg <= 4000.0
    rel_ratio = (dl_avg / none_avg) if none_avg > 0 else 0.0
    rel_pass = rel_ratio <= 2.0
    return {
        "rule_a": "DOC_LEVEL tokens_avg ≤ 4000",
        "rule_b": "DOC_LEVEL tokens_avg / NONE tokens_avg ≤ 2.0",
        "dl_tokens_avg": dl_avg,
        "none_tokens_avg": none_avg,
        "ratio_dl_over_none": rel_ratio,
        "abs_threshold_pass": abs_pass,
        "rel_threshold_pass": rel_pass,
        "passed": abs_pass and rel_pass,
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# P5 long-doc follow-up evaluation report (P5.f1)")
    lines.append("")
    lines.append(f"- generated_at: {report['generated_at']}")
    lines.append(f"- collection: `{report['collection']}`")
    lines.append(f"- sample_count: {report['summary']['total_samples']}")
    lines.append(f"- top_k: {report['top_k']}")
    lines.append(f"- top_chunks_per_doc: {report['top_chunks_per_doc']}")
    lines.append(f"- doc_oversample_factor: {report['doc_oversample_factor']}")
    lines.append(f"- citation_invariant_all_ok: {report['citation_invariant_all_ok']}")
    lines.append(f"- F3 discrimination_overall_passed: {report['discrimination']['overall_passed']}")
    lines.append(f"- D1 factor_enough: {report['d1']['factor_enough']}")
    lines.append(f"- E3 token_pass: {report['e3']['passed']}")
    lines.append("")

    lines.append("## Corpus")
    for stem, doc_id in report["doc_ids"].items():
        lines.append(f"- {stem} -> {doc_id}")
    lines.append("")

    lines.append("## Strategy summary")
    lines.append(
        "| strategy | tokens_avg | tokens_p95 | tokens_max | distinct_doc_count_avg | top1_doc_match_avg | keyword_coverage_avg |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for strategy, m in report["summary"]["by_strategy"].items():
        lines.append(
            f"| {strategy} | {m['tokens_avg']:.1f} | {m['tokens_p95']:.0f} | {m['tokens_max']} | "
            f"{m['distinct_doc_count_avg']:.2f} | {m['top1_doc_match_avg']:.3f} | "
            f"{m['keyword_coverage_avg']:.3f} |"
        )
    lines.append("")

    lines.append("## Category × strategy")
    for category in CATEGORIES:
        cat = report["summary"]["by_category"].get(category, {})
        if not cat or cat.get("sample_count", 0) == 0:
            continue
        lines.append(f"### {category} (n={cat['sample_count']})")
        lines.append(
            "| strategy | distinct_doc_count_avg | tokens_avg | top1_doc_match_avg |"
        )
        lines.append("|---|---|---|---|")
        for strategy in ("none", "doc_level"):
            lines.append(
                f"| {strategy} | {cat[f'distinct_doc_count_avg_{strategy}']:.2f} | "
                f"{cat[f'tokens_avg_{strategy}']:.1f} | "
                f"{cat[f'top1_doc_match_avg_{strategy}']:.3f} |"
            )
        lines.append("")

    lines.append("## F3 discrimination self-check (unchanged thresholds)")
    for category in CATEGORIES:
        check = report["discrimination"].get(category, {})
        passed = check.get("passed")
        lines.append(
            f"- **{category}**: {'PASS' if passed else 'FAIL'} - "
            f"matching={check.get('matching', 0)}/{check.get('samples', 0)} "
            f"(ratio={check.get('ratio', 0):.2f}); rule: {check.get('rule', 'n/a')}"
        )
    lines.append("")

    lines.append("## D1 doc_oversample_factor=4 judgement")
    d1 = report["d1"]
    lines.append(
        f"- saturated samples (pool top_doc_hit_share == 1.0): "
        f"{d1.get('saturated_samples', 0)}/{d1.get('total_same_doc_samples', 0)} "
        f"(ratio={d1.get('saturation_ratio', 0):.2f})"
    )
    lines.append(f"- factor=4 enough? **{d1.get('factor_enough', False)}**")
    if d1.get("triggers_p5_f4_param_tuning"):
        lines.append(
            "- This triggers P5.f4 parameter tuning as follow-up work; the present run still completes."
        )
    lines.append("")

    lines.append("## E3 token cost dual threshold")
    e3 = report["e3"]
    lines.append(
        f"- DOC_LEVEL tokens_avg = {e3['dl_tokens_avg']:.1f}, NONE tokens_avg = {e3['none_tokens_avg']:.1f}"
    )
    lines.append(f"- ratio = {e3['ratio_dl_over_none']:.2f}")
    lines.append(f"- rule_a (≤ 4000) pass: {e3['abs_threshold_pass']}")
    lines.append(f"- rule_b (ratio ≤ 2.0) pass: {e3['rel_threshold_pass']}")
    lines.append(f"- E3 overall pass: **{e3['passed']}**")
    lines.append("")

    lines.append("## Per-sample (compact)")
    lines.append(
        "| id | category | distinct(none/dl) | top1_match(none/dl) | tokens(none/dl) | pool_top_share |"
    )
    lines.append("|---|---|---|---|---|---|")
    for row in report["rows"]:
        n = row["none"]
        d = row["doc_level"]
        lines.append(
            f"| {row['id']} | {row['category']} | "
            f"{n['distinct_doc_count']}/{d['distinct_doc_count']} | "
            f"{n['top1_doc_match']}/{d['top1_doc_match']} | "
            f"{n['tokens']}/{d['tokens']} | "
            f"{row['pool']['top_doc_hit_share']:.2f} |"
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
            citation_all_ok = True
            summary = aggregate_metrics(rows)
            discrimination = discrimination_self_check(rows)
            d1 = d1_oversample_judgement(rows)
            e3 = e3_token_judgement(rows, summary)

            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": EVAL_COLLECTION,
                "tokenizer": "dashscope.qwen-max",
                "top_k": DEFAULT_TOP_K,
                "top_chunks_per_doc": DEFAULT_TOP_CHUNKS_PER_DOC,
                "doc_oversample_factor": DEFAULT_OVERSAMPLE,
                "doc_ids": stem_to_doc_id,
                "summary": summary,
                "discrimination": discrimination,
                "d1": d1,
                "e3": e3,
                "citation_invariant_all_ok": citation_all_ok,
                "rows": rows,
            }
            report_json = REPORT_DIR / f"p5_long_doc_eval_{RUN_ID}.json"
            report_md = REPORT_DIR / f"p5_long_doc_eval_{RUN_ID}.md"
            write_json(report_json, report)
            report_md.write_text(format_markdown(report), encoding="utf-8")

            output = {
                "samples": str(SAMPLES_PATH),
                "report_json": str(report_json),
                "report_md": str(report_md),
                "discrimination": discrimination,
                "d1": d1,
                "e3": e3,
                "citation_invariant_all_ok": citation_all_ok,
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
    p = argparse.ArgumentParser(description="Run P5 long-doc follow-up evaluation.")
    return p.parse_args()


def main() -> int:
    parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
