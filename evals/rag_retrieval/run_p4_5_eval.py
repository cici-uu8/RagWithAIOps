#!/usr/bin/env python3
"""P4.5 context_granularity evaluation.

针对 chunk / parent_chunk / full_doc 三种粒度模式跑 P4.5 样本集, 输出:
- citation 不变性: 每条 query 三模式下 [(chunk_id, citation_text)] 严格有序相等;
- 用 Qwen tokenizer 统计三模式 context_text 的真实 token 数;
- per-category 区分度自检, 不达标即标 "evaluation set invalid";
- 反向控制组阳性命中数 (signal_density 下降 ≥ 10%);
- P5 启动证据原始信号 (parent_chunk 重复浪费 / full_doc 重复浪费)。

设计文档: docs/p4_5_context_granularity_design.md
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
from app.models import ContextGranularity, RetrievalMode, RetrievalQuery
from app.services import document_ingestion_service as ingestion_module
from app.services import retrieval_service as retrieval_service_module
from app.services import vector_index_service as vector_index_module
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.rerank_service import rerank_service
from app.services.vector_store_manager import vector_store_manager


EVAL_DIR = REPO_ROOT / "evals" / "rag_retrieval"
REPORT_DIR = EVAL_DIR / "reports"
SAMPLES_PATH = EVAL_DIR / "p4_5_samples.jsonl"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
EVAL_COLLECTION = f"p4_5_context_granularity_eval_{RUN_ID}"
DEFAULT_TOP_K = 3

CATEGORIES = ["parent_advantage", "multi_child_hit", "long_doc", "reverse_control"]
GRANULARITIES = [
    ContextGranularity.CHUNK,
    ContextGranularity.PARENT_CHUNK,
    ContextGranularity.FULL_DOC,
]

# 与 run_retrieval_eval.py 一致的本地 Milvus IPv4 兜底。
config.milvus_host = "127.0.0.1"


def _qwen_tokenizer():
    """Lazy-load Qwen tokenizer (与下游 LLM `qwen-max` 一致)。

    设计 §5: 严禁用 len(text)/4 / word count / 字符数代替。
    """
    from dashscope.tokenizers.tokenizer import get_tokenizer

    return get_tokenizer(config.rag_model)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"P4.5 samples not found: {path}")
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        samples.append(json.loads(line))
    if not samples:
        raise ValueError(f"P4.5 samples empty: {path}")
    return samples


def build_doc_id_for_path(index_service, kb_id: str, path: Path) -> str:
    return index_service._build_doc_id(kb_id, path.resolve())


def index_aiops_corpus(index_service) -> dict[str, str]:
    """将 5 篇 aiops-docs 入库, 返回 file_name -> doc_id 映射。"""
    docs_dir = REPO_ROOT / "aiops-docs"
    file_to_doc_id: dict[str, str] = {}
    for md_file in sorted(docs_dir.glob("*.md")):
        doc_id = build_doc_id_for_path(index_service, "default", md_file)
        index_service.index_single_file(md_file.as_posix(), kb_id="default")
        file_to_doc_id[md_file.name] = doc_id
    return file_to_doc_id


def keyword_occurrences(text: str, keywords: list[str]) -> int:
    if not text or not keywords:
        return 0
    return sum(text.count(kw) for kw in keywords if kw)


def keyword_coverage(text: str, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    hit = sum(1 for kw in keywords if kw and kw in text)
    return hit / len(keywords)


def has_multi_child_same_parent(results: list[Any]) -> bool:
    parent_ids: dict[str, int] = {}
    for r in results:
        pid = r.metadata.get("parent_chunk_id") if isinstance(r.metadata, dict) else None
        if pid:
            parent_ids[pid] = parent_ids.get(pid, 0) + 1
    return any(count >= 2 for count in parent_ids.values())


def evaluate_sample(
    sample: dict[str, Any],
    file_to_doc_id: dict[str, str],
    tokenizer,
    top_k: int,
) -> dict[str, Any]:
    expected_doc_ids = [
        file_to_doc_id[name] for name in sample["expected_doc_files"] if name in file_to_doc_id
    ]
    keywords = sample.get("expected_keywords", [])

    per_mode: dict[str, dict[str, Any]] = {}
    ordered_citations: dict[str, list[list[str]]] = {}
    for granularity in GRANULARITIES:
        query = RetrievalQuery(
            query=sample["query"],
            top_k=top_k,
            retrieval_mode=RetrievalMode.DENSE_ONLY,
            knowledge_base_ids=["default"],
            context_granularity=granularity,
        )
        start = time.perf_counter()
        response = retrieval_service_module.retrieval_service.retrieve(query)
        latency_ms = int((time.perf_counter() - start) * 1000)
        results = response.results[:top_k]

        ordered_citations[granularity.value] = [
            [r.chunk_id, r.citation_text] for r in results
        ]

        context_text = response.context_text
        token_count = len(tokenizer.encode(context_text)) if context_text else 0
        kw_occ = keyword_occurrences(context_text, keywords)
        kw_cov = keyword_coverage(context_text, keywords)
        signal_density = (kw_occ / token_count) if token_count > 0 else 0.0
        doc_recall = (
            1
            if any(r.doc_id in expected_doc_ids for r in results) and expected_doc_ids
            else 0
        )
        multi_child = has_multi_child_same_parent(results)

        per_mode[granularity.value] = {
            "context_text": context_text,
            "tokens": token_count,
            "keyword_occurrences": kw_occ,
            "keyword_coverage": kw_cov,
            "signal_density": signal_density,
            "doc_recall": doc_recall,
            "multi_child_same_parent": multi_child,
            "fallbacks": [
                r.metadata.get("context_granularity_fallback")
                for r in results
                if r.metadata.get("context_granularity_fallback")
            ],
            "retrieved_chunk_ids": [r.chunk_id for r in results],
            "retrieved_doc_ids": [r.doc_id for r in results],
            "latency_ms": latency_ms,
        }

    # 严格有序断言 (P4.5 设计 §4): 三模式下有序 citation list 完全相等。
    citation_invariant_ok = (
        ordered_citations["chunk"]
        == ordered_citations["parent_chunk"]
        == ordered_citations["full_doc"]
    )
    if not citation_invariant_ok:
        raise AssertionError(
            "P4.5 citation invariance violated for sample "
            f"{sample['id']}: ordered_citations={json.dumps(ordered_citations, ensure_ascii=False)}"
        )

    chunk_density = per_mode["chunk"]["signal_density"]
    pc_drop = (
        (chunk_density - per_mode["parent_chunk"]["signal_density"]) / chunk_density
        if chunk_density > 0
        else 0.0
    )
    fd_drop = (
        (chunk_density - per_mode["full_doc"]["signal_density"]) / chunk_density
        if chunk_density > 0
        else 0.0
    )
    pc_token_ratio = (
        per_mode["parent_chunk"]["tokens"] / per_mode["chunk"]["tokens"]
        if per_mode["chunk"]["tokens"] > 0
        else 0.0
    )
    fd_token_ratio = (
        per_mode["full_doc"]["tokens"] / per_mode["chunk"]["tokens"]
        if per_mode["chunk"]["tokens"] > 0
        else 0.0
    )

    return {
        "id": sample["id"],
        "category": sample["category"],
        "query": sample["query"],
        "expected_doc_ids": expected_doc_ids,
        "expected_keywords": keywords,
        "modes": per_mode,
        "ordered_citations": ordered_citations,
        "citation_invariant_ok": citation_invariant_ok,
        "signal_density_drop_parent_chunk": pc_drop,
        "signal_density_drop_full_doc": fd_drop,
        "token_ratio_parent_chunk_over_chunk": pc_token_ratio,
        "token_ratio_full_doc_over_chunk": fd_token_ratio,
    }


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = max(0, int(len(sorted_values) * pct) - 1)
        return sorted_values[index]

    summary: dict[str, Any] = {"total_samples": len(rows), "by_mode": {}, "by_category": {}}
    for granularity in GRANULARITIES:
        mode_name = granularity.value
        token_values = [row["modes"][mode_name]["tokens"] for row in rows]
        density_values = [row["modes"][mode_name]["signal_density"] for row in rows]
        coverage_values = [row["modes"][mode_name]["keyword_coverage"] for row in rows]
        recall_values = [row["modes"][mode_name]["doc_recall"] for row in rows]
        summary["by_mode"][mode_name] = {
            "tokens_avg": statistics.mean(token_values) if token_values else 0.0,
            "tokens_max": max(token_values) if token_values else 0,
            "tokens_p95": percentile(token_values, 0.95),
            "signal_density_avg": statistics.mean(density_values) if density_values else 0.0,
            "keyword_coverage_avg": statistics.mean(coverage_values) if coverage_values else 0.0,
            "doc_recall_avg": statistics.mean(recall_values) if recall_values else 0.0,
        }

    for category in CATEGORIES:
        cat_rows = [row for row in rows if row["category"] == category]
        if not cat_rows:
            summary["by_category"][category] = {"sample_count": 0}
            continue
        cat_summary: dict[str, Any] = {"sample_count": len(cat_rows)}
        for granularity in GRANULARITIES:
            mode_name = granularity.value
            cat_summary[f"tokens_avg_{mode_name}"] = statistics.mean(
                [row["modes"][mode_name]["tokens"] for row in cat_rows]
            )
            cat_summary[f"keyword_coverage_avg_{mode_name}"] = statistics.mean(
                [row["modes"][mode_name]["keyword_coverage"] for row in cat_rows]
            )
            cat_summary[f"signal_density_avg_{mode_name}"] = statistics.mean(
                [row["modes"][mode_name]["signal_density"] for row in cat_rows]
            )
        summary["by_category"][category] = cat_summary

    return summary


def discrimination_self_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """P4.5 设计 §9: 跑前固定的区分度自检。任何一条不达标即视为评测集失效。"""
    checks: dict[str, Any] = {}

    pa_rows = [row for row in rows if row["category"] == "parent_advantage"]
    if pa_rows:
        higher_count = sum(
            1
            for row in pa_rows
            if row["modes"]["parent_chunk"]["keyword_coverage"]
            > row["modes"]["chunk"]["keyword_coverage"]
        )
        checks["parent_advantage"] = {
            "rule": "≥ 50% samples: parent_chunk keyword_coverage strictly > chunk",
            "samples": len(pa_rows),
            "matching": higher_count,
            "ratio": higher_count / len(pa_rows),
            "passed": higher_count / len(pa_rows) >= 0.5,
        }
    else:
        checks["parent_advantage"] = {"samples": 0, "passed": False}

    mc_rows = [row for row in rows if row["category"] == "multi_child_hit"]
    if mc_rows:
        with_multi = sum(
            1 for row in mc_rows if row["modes"]["chunk"]["multi_child_same_parent"]
        )
        checks["multi_child_hit"] = {
            "rule": "≥ 50% samples: top-K contains ≥ 2 hits sharing the same parent_chunk_id",
            "samples": len(mc_rows),
            "matching": with_multi,
            "ratio": with_multi / len(mc_rows),
            "passed": with_multi / len(mc_rows) >= 0.5,
        }
    else:
        checks["multi_child_hit"] = {"samples": 0, "passed": False}

    ld_rows = [row for row in rows if row["category"] == "long_doc"]
    if ld_rows:
        big_ratio = sum(
            1 for row in ld_rows if row["token_ratio_full_doc_over_chunk"] >= 2.0
        )
        checks["long_doc"] = {
            "rule": "≥ 50% samples: tokens(full_doc) / tokens(chunk) >= 2.0",
            "samples": len(ld_rows),
            "matching": big_ratio,
            "ratio": big_ratio / len(ld_rows),
            "passed": big_ratio / len(ld_rows) >= 0.5,
        }
    else:
        checks["long_doc"] = {"samples": 0, "passed": False}

    rc_rows = [row for row in rows if row["category"] == "reverse_control"]
    if rc_rows:
        positives = sum(
            1
            for row in rc_rows
            if row["signal_density_drop_full_doc"] >= 0.10
            or row["signal_density_drop_parent_chunk"] >= 0.10
        )
        checks["reverse_control"] = {
            "rule": "≥ 30% samples: signal_density drops ≥ 10% in parent_chunk or full_doc vs chunk",
            "samples": len(rc_rows),
            "matching": positives,
            "ratio": positives / len(rc_rows),
            "passed": positives / len(rc_rows) >= 0.30,
        }
    else:
        checks["reverse_control"] = {"samples": 0, "passed": False}

    checks["overall_passed"] = all(c.get("passed") for c in checks.values() if isinstance(c, dict))
    return checks


def collect_p5_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """记 (不实现) P5 启动证据。P4.5 设计 §10。"""
    mc_rows = [row for row in rows if row["category"] == "multi_child_hit"]
    parent_waste_30 = (
        sum(
            1
            for row in mc_rows
            if row["modes"]["chunk"]["multi_child_same_parent"]
            and row["token_ratio_parent_chunk_over_chunk"] >= 1.30
        )
        / len(mc_rows)
        if mc_rows
        else 0.0
    )
    full_doc_waste_50 = sum(
        1 for row in rows if row["token_ratio_full_doc_over_chunk"] >= 1.50
    ) / max(len(rows), 1)
    return {
        "multi_child_parent_chunk_waste_>=30%_ratio": parent_waste_30,
        "any_full_doc_waste_>=50%_ratio": full_doc_waste_50,
        "trigger_p5": parent_waste_30 >= 0.5 or full_doc_waste_50 >= 0.5,
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# P4.5 Context Granularity Evaluation Report")
    lines.append("")
    lines.append(f"- generated_at: {report['generated_at']}")
    lines.append(f"- collection: `{report['collection']}`")
    lines.append(f"- sample_count: {report['summary']['total_samples']}")
    lines.append(f"- citation_invariant_all_ok: {report['citation_invariant_all_ok']}")
    lines.append(f"- discrimination_overall_passed: {report['discrimination']['overall_passed']}")
    lines.append("")

    lines.append("## Mode summary")
    lines.append("| mode | tokens_avg | tokens_p95 | tokens_max | signal_density_avg | keyword_coverage_avg | doc_recall_avg |")
    lines.append("|---|---|---|---|---|---|---|")
    for mode_name, m in report["summary"]["by_mode"].items():
        lines.append(
            f"| {mode_name} | {m['tokens_avg']:.1f} | {m['tokens_p95']:.0f} | {m['tokens_max']} | "
            f"{m['signal_density_avg']:.4f} | {m['keyword_coverage_avg']:.3f} | {m['doc_recall_avg']:.3f} |"
        )
    lines.append("")

    lines.append("## Category × mode")
    for category in CATEGORIES:
        cat = report["summary"]["by_category"].get(category, {})
        if not cat or cat.get("sample_count", 0) == 0:
            continue
        lines.append(f"### {category} (n={cat['sample_count']})")
        lines.append("| mode | tokens_avg | keyword_coverage_avg | signal_density_avg |")
        lines.append("|---|---|---|---|")
        for mode_name in [g.value for g in GRANULARITIES]:
            lines.append(
                f"| {mode_name} | {cat[f'tokens_avg_{mode_name}']:.1f} | "
                f"{cat[f'keyword_coverage_avg_{mode_name}']:.3f} | "
                f"{cat[f'signal_density_avg_{mode_name}']:.4f} |"
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

    lines.append("## Reverse-control positives")
    rc_rows = [row for row in report["rows"] if row["category"] == "reverse_control"]
    pos_pc = sum(1 for row in rc_rows if row["signal_density_drop_parent_chunk"] >= 0.10)
    pos_fd = sum(1 for row in rc_rows if row["signal_density_drop_full_doc"] >= 0.10)
    lines.append(f"- positive (parent_chunk, signal_density drop >= 10%): {pos_pc}/{len(rc_rows)}")
    lines.append(f"- positive (full_doc, signal_density drop >= 10%): {pos_fd}/{len(rc_rows)}")
    lines.append("")

    lines.append("## P5 trigger evidence")
    p5 = report["p5_evidence"]
    for key, value in p5.items():
        lines.append(f"- {key}: {value}")
    lines.append("")

    lines.append("## Per-sample (compact)")
    lines.append(
        "| id | category | top_chunk(chunk) | tokens chunk/parent/full | density chunk/parent/full | drop pc/fd |"
    )
    lines.append("|---|---|---|---|---|---|")
    for row in report["rows"]:
        m = row["modes"]
        top_chunk = (
            m["chunk"]["retrieved_chunk_ids"][0] if m["chunk"]["retrieved_chunk_ids"] else "-"
        )
        lines.append(
            f"| {row['id']} | {row['category']} | {top_chunk} | "
            f"{m['chunk']['tokens']}/{m['parent_chunk']['tokens']}/{m['full_doc']['tokens']} | "
            f"{m['chunk']['signal_density']:.4f}/{m['parent_chunk']['signal_density']:.4f}/{m['full_doc']['signal_density']:.4f} | "
            f"{row['signal_density_drop_parent_chunk']:.2f}/{row['signal_density_drop_full_doc']:.2f} |"
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
                evaluate_sample(sample, file_to_doc_id, tokenizer, DEFAULT_TOP_K)
                for sample in samples
            ]
            citation_all_ok = all(row["citation_invariant_ok"] for row in rows)

            summary = aggregate_metrics(rows)
            discrimination = discrimination_self_check(rows)
            p5_evidence = collect_p5_evidence(rows)

            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": EVAL_COLLECTION,
                "tokenizer": "dashscope.qwen-max",
                "top_k": DEFAULT_TOP_K,
                "summary": summary,
                "discrimination": discrimination,
                "citation_invariant_all_ok": citation_all_ok,
                "p5_evidence": p5_evidence,
                "rows": rows,
            }

            report_json = REPORT_DIR / f"p4_5_eval_{RUN_ID}.json"
            report_md = REPORT_DIR / f"p4_5_eval_{RUN_ID}.md"
            write_json(report_json, report)
            report_md.write_text(format_markdown(report), encoding="utf-8")

            output = {
                "samples": str(SAMPLES_PATH),
                "report_json": str(report_json),
                "report_md": str(report_md),
                "summary": summary,
                "discrimination": discrimination,
                "p5_evidence": p5_evidence,
                "citation_invariant_all_ok": citation_all_ok,
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
    parser = argparse.ArgumentParser(description="Run the P4.5 context_granularity evaluation.")
    return parser.parse_args()


def main() -> int:
    parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
