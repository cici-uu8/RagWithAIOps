#!/usr/bin/env python3
"""P5 doc-level result aggregation evaluation.

For each sample, run THREE retrievals (per design §4 / §6):
- Pool:       NONE @ pool_k (= top_k * doc_oversample_factor); used for citation
              invariance assertion against the candidate pool DOC_LEVEL sees.
- NONE:       NONE @ top_k; baseline strategy.
- DOC_LEVEL:  DOC_LEVEL @ top_k; dedup strategy.

Strong assertions (§4):
  1. set(returned_chunk_ids_doc_level) ⊆ set(candidate_pool_chunk_ids)
  2. set(returned_chunk_ids_none)      ⊆ set(candidate_pool_chunk_ids)
  3. For each chunk_id in DOC_LEVEL.results, citation_text / source_ref / content
     are byte-equal to the same chunk_id's hit in the candidate pool.
  4. len(results_doc_level) ≤ top_k * top_chunks_per_doc and per-doc count ≤
     top_chunks_per_doc.

Per-category discrimination self-check (§9, thresholds frozen pre-run):
  same_doc_redundant: ≥ 70% samples distinct_doc_count(DOC_LEVEL) > NONE
  cross_doc_already:  ≥ 70% samples distinct_doc_count(DOC_LEVEL) == NONE
  reverse_control:    top1_doc_match degradation ratio ≤ 10%

Design doc: docs/p5_doc_level_dedup_design.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from pymilvus import utility

from app.config import config
from app.core import milvus_client as milvus_client_module
from app.models import ContextGranularity, ResultAggregation, RetrievalMode, RetrievalQuery
from app.services import document_ingestion_service as ingestion_module
from app.services import retrieval_service as retrieval_service_module
from app.services import vector_index_service as vector_index_module
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.rerank_service import rerank_service
from app.services.vector_store_manager import vector_store_manager


EVAL_DIR = REPO_ROOT / "evals" / "rag_retrieval"
REPORT_DIR = EVAL_DIR / "reports"
SAMPLES_PATH = EVAL_DIR / "p5_samples.jsonl"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
EVAL_COLLECTION = f"p5_doc_level_eval_{RUN_ID}"
DEFAULT_TOP_K = 3
DEFAULT_TOP_CHUNKS_PER_DOC = 1
DEFAULT_OVERSAMPLE = 4

CATEGORIES = ["same_doc_redundant", "cross_doc_already", "reverse_control"]

# Same Milvus IPv4 fallback as P4.5 / P3 evals.
config.milvus_host = "127.0.0.1"


def _qwen_tokenizer():
    """Reuse the P4.5 tokenizer (qwen-max) so token costs are comparable."""
    from dashscope.tokenizers.tokenizer import get_tokenizer

    return get_tokenizer(config.rag_model)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"P5 samples not found: {path}")
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        samples.append(json.loads(line))
    if not samples:
        raise ValueError(f"P5 samples empty: {path}")
    return samples


def build_doc_id_for_path(index_service, kb_id: str, path: Path) -> str:
    return index_service._build_doc_id(kb_id, path.resolve())


def index_aiops_corpus(index_service) -> dict[str, str]:
    docs_dir = REPO_ROOT / "aiops-docs"
    file_to_doc_id: dict[str, str] = {}
    for md_file in sorted(docs_dir.glob("*.md")):
        doc_id = build_doc_id_for_path(index_service, "default", md_file)
        index_service.index_single_file(md_file.as_posix(), kb_id="default")
        file_to_doc_id[md_file.name] = doc_id
    return file_to_doc_id


def _result_signature(result) -> dict[str, Any]:
    """Stable per-result identity payload for §4 byte-equality assertions."""
    return {
        "chunk_id": result.chunk_id,
        "content": result.content,
        "citation_text": result.citation_text,
        "source_ref": result.source_ref.model_dump(mode="json"),
    }


def evaluate_sample(
    sample: dict[str, Any],
    file_to_doc_id: dict[str, str],
    tokenizer,
    top_k: int,
    top_chunks_per_doc: int,
    oversample_factor: int,
) -> dict[str, Any]:
    expected_doc_ids = [
        file_to_doc_id[name] for name in sample["expected_doc_files"] if name in file_to_doc_id
    ]
    keywords = sample.get("expected_keywords", [])

    # Pool query: NONE @ pool_k, mirrors what DOC_LEVEL sees internally.
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

    # NONE strategy: top_k baseline.
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

    # DOC_LEVEL strategy.
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

    # ---- §4 invariance assertions (must all hold) ----
    none_chunk_ids = [r.chunk_id for r in response_none.results]
    dl_chunk_ids = [r.chunk_id for r in response_dl.results]
    pool_chunk_id_set = set(pool_chunk_ids)

    if not set(dl_chunk_ids).issubset(pool_chunk_id_set):
        raise AssertionError(
            f"P5 §4(1) violated: DOC_LEVEL produced chunk_ids outside the candidate pool "
            f"for sample {sample['id']}: extra={set(dl_chunk_ids) - pool_chunk_id_set}"
        )
    if not set(none_chunk_ids).issubset(pool_chunk_id_set):
        raise AssertionError(
            f"P5 §4(2) violated: NONE produced chunk_ids outside the candidate pool "
            f"for sample {sample['id']}: extra={set(none_chunk_ids) - pool_chunk_id_set}"
        )
    for r in response_dl.results:
        ref = pool_signatures[r.chunk_id]
        actual = _result_signature(r)
        if actual != ref:
            raise AssertionError(
                f"P5 §4(3) violated: DOC_LEVEL result for chunk_id {r.chunk_id} differs "
                f"from candidate-pool entry on sample {sample['id']}; "
                f"actual={actual} ref={ref}"
            )
    if len(response_dl.results) > top_k * top_chunks_per_doc:
        raise AssertionError(
            f"P5 §4(4a) violated: DOC_LEVEL returned {len(response_dl.results)} results, "
            f"exceeds top_k * top_chunks_per_doc = {top_k * top_chunks_per_doc} on sample {sample['id']}"
        )
    from collections import Counter

    per_doc_count = Counter(r.doc_id for r in response_dl.results)
    over = {d: c for d, c in per_doc_count.items() if c > top_chunks_per_doc}
    if over:
        raise AssertionError(
            f"P5 §4(4b) violated: doc_id occurrence cap exceeded on sample {sample['id']}: {over}"
        )

    # ---- Signals (§6) ----
    distinct_doc_none = len({r.doc_id for r in response_none.results})
    distinct_doc_dl = len({r.doc_id for r in response_dl.results})
    none_top1_doc = response_none.results[0].doc_id if response_none.results else ""
    dl_top1_doc = response_dl.results[0].doc_id if response_dl.results else ""
    none_top1_match = 1 if none_top1_doc and none_top1_doc in expected_doc_ids else 0
    dl_top1_match = 1 if dl_top1_doc and dl_top1_doc in expected_doc_ids else 0
    pool_total = len(pool_chunk_ids)
    if pool_total > 0:
        doc_hit_counts = Counter(r.doc_id for r in pool_results)
        top_doc_hit_share = max(doc_hit_counts.values()) / pool_total
    else:
        top_doc_hit_share = 0.0

    none_tokens = (
        len(tokenizer.encode(response_none.context_text)) if response_none.context_text else 0
    )
    dl_tokens = (
        len(tokenizer.encode(response_dl.context_text)) if response_dl.context_text else 0
    )

    keyword_cov_none = (
        sum(1 for kw in keywords if kw and kw in response_none.context_text) / max(len(keywords), 1)
    )
    keyword_cov_dl = (
        sum(1 for kw in keywords if kw and kw in response_dl.context_text) / max(len(keywords), 1)
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
            "chunk_ids": pool_chunk_ids,
            "doc_ids": [r.doc_id for r in pool_results],
            "top_doc_hit_share": top_doc_hit_share,
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
    def percentile(values: list[float], pct: float) -> float:
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
        token_values = [row[strategy]["tokens"] for row in rows]
        distinct_values = [row[strategy]["distinct_doc_count"] for row in rows]
        match_values = [row[strategy]["top1_doc_match"] for row in rows]
        cov_values = [row[strategy]["keyword_coverage"] for row in rows]
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
        cat_rows = [row for row in rows if row["category"] == category]
        if not cat_rows:
            summary["by_category"][category] = {"sample_count": 0}
            continue
        cat_summary: dict[str, Any] = {"sample_count": len(cat_rows)}
        for strategy in ("none", "doc_level"):
            cat_summary[f"distinct_doc_count_avg_{strategy}"] = statistics.mean(
                [row[strategy]["distinct_doc_count"] for row in cat_rows]
            )
            cat_summary[f"tokens_avg_{strategy}"] = statistics.mean(
                [row[strategy]["tokens"] for row in cat_rows]
            )
            cat_summary[f"top1_doc_match_avg_{strategy}"] = statistics.mean(
                [row[strategy]["top1_doc_match"] for row in cat_rows]
            )
        summary["by_category"][category] = cat_summary

    return summary


def discrimination_self_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-category thresholds, frozen pre-run (design §9)."""
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
    else:
        checks["same_doc_redundant"] = {"samples": 0, "passed": False}

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
    else:
        checks["cross_doc_already"] = {"samples": 0, "passed": False}

    rc_rows = [r for r in rows if r["category"] == "reverse_control"]
    if rc_rows:
        degraded = sum(1 for r in rc_rows if r["top1_doc_match_degraded"])
        ratio = degraded / len(rc_rows)
        checks["reverse_control"] = {
            "rule": "top1_doc_match degradation ratio (NONE hits, DOC_LEVEL misses) ≤ 10%",
            "samples": len(rc_rows),
            "matching": degraded,
            "ratio": ratio,
            "passed": ratio <= 0.10,
        }
    else:
        checks["reverse_control"] = {"samples": 0, "passed": False}

    checks["overall_passed"] = all(c.get("passed") for c in checks.values() if isinstance(c, dict))
    return checks


def collect_p6_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """P6 启动证据 (设计 §10): 仅记不做。

    当前 corpus 没有 path / 目录 / domain 显式 metadata, 这里只能给出占位
    proxy: 期望命中文档与 top-1 命中文档的语义距离。本次评测没有体感会触发
    P6, 字段保留是为了下一轮如有显式领域过滤需求时可统一接入。
    """
    return {
        "trigger_p6": False,
        "note": (
            "Current aiops-docs corpus has no path-derived domain metadata; "
            "explicit P6 trigger would require either ≥3 queries that need path/folder "
            "filtering or stable reverse-control positives showing kb_id is insufficient."
        ),
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# P5 doc-level dedup evaluation report")
    lines.append("")
    lines.append(f"- generated_at: {report['generated_at']}")
    lines.append(f"- collection: `{report['collection']}`")
    lines.append(f"- sample_count: {report['summary']['total_samples']}")
    lines.append(f"- top_k: {report['top_k']}")
    lines.append(f"- top_chunks_per_doc: {report['top_chunks_per_doc']}")
    lines.append(f"- doc_oversample_factor: {report['doc_oversample_factor']}")
    lines.append(f"- citation_invariant_all_ok: {report['citation_invariant_all_ok']}")
    lines.append(
        f"- discrimination_overall_passed: {report['discrimination']['overall_passed']}"
    )
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

    lines.append("## Discrimination self-check")
    for category in CATEGORIES:
        check = report["discrimination"].get(category, {})
        passed = check.get("passed")
        lines.append(
            f"- **{category}**: {'PASS' if passed else 'FAIL'} - "
            f"matching={check.get('matching', 0)}/{check.get('samples', 0)} "
            f"(ratio={check.get('ratio', 0):.2f}); rule: {check.get('rule', 'n/a')}"
        )
    lines.append("")

    lines.append("## Per-sample (compact)")
    lines.append(
        "| id | category | distinct(none/dl) | top1_match(none/dl) | tokens(none/dl) |"
    )
    lines.append("|---|---|---|---|---|")
    for row in report["rows"]:
        n = row["none"]
        d = row["doc_level"]
        lines.append(
            f"| {row['id']} | {row['category']} | "
            f"{n['distinct_doc_count']}/{d['distinct_doc_count']} | "
            f"{n['top1_doc_match']}/{d['top1_doc_match']} | "
            f"{n['tokens']}/{d['tokens']} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def run() -> dict[str, Any]:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    samples = load_samples(SAMPLES_PATH)
    tokenizer = _qwen_tokenizer()

    original_collection_name = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    original_vector_collection_name = vector_store_manager.collection_name
    original_vector_store = vector_store_manager.vector_store
    original_metadata_store_module = vector_index_module.knowledge_metadata_store
    original_ingestion_metadata_store = ingestion_module.knowledge_metadata_store
    original_retrieval_metadata_store = retrieval_service_module.knowledge_metadata_store
    original_rerank_enabled = rerank_service.enabled

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
        vector_index_module.knowledge_metadata_store = temp_store
        ingestion_module.knowledge_metadata_store = temp_store
        retrieval_service_module.knowledge_metadata_store = temp_store
        milvus_client_module.MilvusClientManager.COLLECTION_NAME = EVAL_COLLECTION
        vector_store_manager.collection_name = EVAL_COLLECTION
        vector_store_manager.vector_store = None

        try:
            index_service = vector_index_module.VectorIndexService()
            file_to_doc_id = index_aiops_corpus(index_service)

            rows = [
                evaluate_sample(
                    sample,
                    file_to_doc_id,
                    tokenizer,
                    DEFAULT_TOP_K,
                    DEFAULT_TOP_CHUNKS_PER_DOC,
                    DEFAULT_OVERSAMPLE,
                )
                for sample in samples
            ]

            citation_all_ok = True  # Any failed assertion would have raised above.
            summary = aggregate_metrics(rows)
            discrimination = discrimination_self_check(rows)
            p6_evidence = collect_p6_evidence(rows)

            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": EVAL_COLLECTION,
                "tokenizer": "dashscope.qwen-max",
                "top_k": DEFAULT_TOP_K,
                "top_chunks_per_doc": DEFAULT_TOP_CHUNKS_PER_DOC,
                "doc_oversample_factor": DEFAULT_OVERSAMPLE,
                "summary": summary,
                "discrimination": discrimination,
                "citation_invariant_all_ok": citation_all_ok,
                "p6_evidence": p6_evidence,
                "rows": rows,
            }

            report_json = REPORT_DIR / f"p5_eval_{RUN_ID}.json"
            report_md = REPORT_DIR / f"p5_eval_{RUN_ID}.md"
            write_json(report_json, report)
            report_md.write_text(format_markdown(report), encoding="utf-8")

            output = {
                "samples": str(SAMPLES_PATH),
                "report_json": str(report_json),
                "report_md": str(report_md),
                "summary": summary,
                "discrimination": discrimination,
                "citation_invariant_all_ok": citation_all_ok,
                "p6_evidence": p6_evidence,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return report
        finally:
            rerank_service.enabled = original_rerank_enabled
            vector_index_module.knowledge_metadata_store = original_metadata_store_module
            ingestion_module.knowledge_metadata_store = original_ingestion_metadata_store
            retrieval_service_module.knowledge_metadata_store = original_retrieval_metadata_store
            vector_store_manager.vector_store = None
            vector_store_manager.collection_name = original_vector_collection_name
            milvus_client_module.MilvusClientManager.COLLECTION_NAME = original_collection_name
            try:
                if utility.has_collection(EVAL_COLLECTION):
                    utility.drop_collection(EVAL_COLLECTION)
            except Exception:
                pass
            vector_store_manager.vector_store = original_vector_store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the P5 doc-level dedup evaluation.")
    return parser.parse_args()


def main() -> int:
    parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
