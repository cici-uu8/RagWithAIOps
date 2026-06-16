#!/usr/bin/env python3
"""Run a dense-only P3-1 baseline over a small fixed golden query set.

This script builds a tiny isolated Milvus collection, indexes:
- two existing md docs from aiops-docs
- one synthetic MinerU fixture with a text chunk and a table chunk

Then it runs the current dense retrieval path and writes:
- evals/rag_retrieval/golden_queries.jsonl
- evals/rag_retrieval/reports/dense_only_baseline_YYYY-MM-DD.json
- evals/rag_retrieval/reports/dense_only_baseline_YYYY-MM-DD.md
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from pymilvus import utility

from app.config import config
from app.core import milvus_client as milvus_client_module
from app.models import DocumentRecord, DocumentStatus, ParserEngine, RetrievalQuery
from app.services.artifact_manifest_service import artifact_manifest_service
from app.services.document_splitter_service import document_splitter_service
from app.services import document_ingestion_service as ingestion_module
from app.services import retrieval_service as retrieval_service_module
from app.services import vector_index_service as vector_index_module
from app.services.knowledge_metadata_store import KnowledgeMetadataStore
from app.services.vector_store_manager import vector_store_manager


EVAL_DIR = REPO_ROOT / "evals" / "rag_retrieval"
REPORT_DIR = EVAL_DIR / "reports"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
BASELINE_COLLECTION = f"p3_dense_baseline_{RUN_ID}"

# Local Docker Milvus is consistently reachable through IPv4 in this workspace,
# while PyMilvus may time out when the env file says "localhost".
config.milvus_host = "127.0.0.1"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")


def exact_source_ref_match(result_ref, gold_ref: dict[str, Any]) -> bool:
    return (
        result_ref.kb_id == gold_ref["kb_id"]
        and result_ref.doc_id == gold_ref["doc_id"]
        and result_ref.chunk_id == gold_ref["chunk_id"]
        and result_ref.source_file == gold_ref["source_file"]
        and result_ref.page_start == gold_ref.get("page_start")
        and result_ref.page_end == gold_ref.get("page_end")
        and result_ref.content_type == gold_ref.get("content_type", result_ref.content_type)
        and result_ref.parser_engine.value == gold_ref.get("parser_engine", result_ref.parser_engine.value)
    )


def build_mineru_fixture(root: Path) -> DocumentRecord:
    original_path = (
        root
        / "uploads"
        / "documents"
        / "default"
        / "doc_pdf"
        / "original"
        / "manual.pdf"
    ).resolve()
    artifact_dir = (
        root
        / "uploads"
        / "documents"
        / "default"
        / "doc_pdf"
        / "artifacts"
    ).resolve()
    original_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    original_path.write_bytes(b"%PDF-1.4 mock")
    (artifact_dir / "cleaned.md").write_text("# cleaned fallback only", encoding="utf-8")

    write_json(artifact_dir / "blocks.json", [])
    write_json(
        artifact_dir / "chunks.json",
        [
            {
                "id": "c00001",
                "doc_type": "manual",
                "text": "第一段正文",
                "pages": [2, 3],
                "heading_path": ["第一章", "概述"],
                "block_ids": ["b00001", "b00002"],
                "block_types": ["heading", "text"],
                "char_count": 5,
            }
        ],
    )
    write_json(
        artifact_dir / "tables.json",
        [
            {
                "schema_version": "table_v1",
                "table_id": "t00001",
                "page": 4,
                "page_start": 4,
                "page_end": 4,
                "heading_path": ["第一章", "参数"],
                "content_type": "manual_table",
                "classification": "parameter_table",
                "caption": ["表1 参数"],
                "rows": [["名称", "值"], ["A", "1"]],
                "markdown": "| 名称 | 值 |\n| --- | --- |\n| A | 1 |",
                "raw_html": "<table></table>",
                "quality_flags": ["no_caption"],
            }
        ],
    )
    write_json(
        artifact_dir / "quality_report.json",
        {
            "doc_type": "manual",
            "block_count": 2,
            "chunk_count": 1,
            "table_count": 1,
            "fatal_errors": [],
            "warnings": [],
        },
    )

    record = DocumentRecord(
        doc_id="doc_pdf",
        kb_id="default",
        file_name="manual.pdf",
        file_ext="pdf",
        original_path=original_path.as_posix(),
        artifact_dir=artifact_dir.as_posix(),
        parser_engine=ParserEngine.MINERU,
        status=DocumentStatus.INDEX_PENDING,
        parser_version="mineru-3.1.11",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    artifact_manifest_service.write_manifest(record)
    return record


def build_golden_queries(cpu_path: Path, memory_path: Path, cpu_doc_id: str, memory_doc_id: str) -> list[dict[str, Any]]:
    cpu_docs = document_splitter_service.split_document(
        cpu_path.read_text(encoding="utf-8"),
        cpu_path.as_posix(),
    )
    memory_docs = document_splitter_service.split_document(
        memory_path.read_text(encoding="utf-8"),
        memory_path.as_posix(),
    )

    cpu_chunk_ids = [f"{cpu_doc_id}:c{i:05d}" for i in range(len(cpu_docs))]
    memory_chunk_ids = [f"{memory_doc_id}:c{i:05d}" for i in range(len(memory_docs))]

    return [
        {
            "id": "cpu_alarm",
            "query": "HighCPUUsage 告警怎么处理",
            "gold_doc_ids": [cpu_doc_id],
            "gold_chunk_ids": cpu_chunk_ids,
            "gold_source_refs": [
                {
                    "kb_id": "default",
                    "doc_id": cpu_doc_id,
                    "chunk_id": chunk_id,
                    "source_file": "cpu_high_usage.md",
                    "page_start": None,
                    "page_end": None,
                    "content_type": "markdown_section",
                    "parser_engine": "plain_text",
                }
                for chunk_id in cpu_chunk_ids
            ],
            "expected_keywords": ["HighCPUUsage", "CPU使用率", "80%", "排查步骤"],
            "mode": "dense_only",
        },
        {
            "id": "memory_alarm",
            "query": "HighMemoryUsage 告警怎么处理",
            "gold_doc_ids": [memory_doc_id],
            "gold_chunk_ids": memory_chunk_ids,
            "gold_source_refs": [
                {
                    "kb_id": "default",
                    "doc_id": memory_doc_id,
                    "chunk_id": chunk_id,
                    "source_file": "memory_high_usage.md",
                    "page_start": None,
                    "page_end": None,
                    "content_type": "markdown_section",
                    "parser_engine": "plain_text",
                }
                for chunk_id in memory_chunk_ids
            ],
            "expected_keywords": ["HighMemoryUsage", "内存使用率", "85%", "排查步骤"],
            "mode": "dense_only",
        },
        {
            "id": "mineru_text",
            "query": "第一段正文",
            "gold_doc_ids": ["doc_pdf"],
            "gold_chunk_ids": ["doc_pdf:c00001"],
            "gold_source_refs": [
                {
                    "kb_id": "default",
                    "doc_id": "doc_pdf",
                    "chunk_id": "doc_pdf:c00001",
                    "source_file": "manual.pdf",
                    "page_start": 2,
                    "page_end": 3,
                    "content_type": "text",
                    "parser_engine": "mineru",
                }
            ],
            "expected_keywords": ["第一段正文", "第一章", "概述"],
            "mode": "dense_only",
        },
        {
            "id": "mineru_table",
            "query": "表1 参数",
            "gold_doc_ids": ["doc_pdf"],
            "gold_chunk_ids": ["doc_pdf:table:t00001"],
            "gold_source_refs": [
                {
                    "kb_id": "default",
                    "doc_id": "doc_pdf",
                    "chunk_id": "doc_pdf:table:t00001",
                    "source_file": "manual.pdf",
                    "page_start": 4,
                    "page_end": 4,
                    "content_type": "manual_table",
                    "parser_engine": "mineru",
                }
            ],
            "expected_keywords": ["表1", "名称", "值", "参数"],
            "mode": "dense_only",
        },
    ]


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def avg(key: str) -> float:
        values = [row[key] for row in rows]
        return sum(values) / len(values) if values else 0.0

    return {
        "query_count": len(rows),
        "doc_recall_at_1": avg("doc_recall_at_1"),
        "doc_recall_at_3": avg("doc_recall_at_3"),
        "hit_at_1": avg("hit_at_1"),
        "hit_at_3": avg("hit_at_3"),
        "citation_correctness_at_3": avg("citation_correctness_at_3"),
        "mrr_at_3": avg("mrr_at_3"),
        "latency_ms": {
            "min": min(row["latency_ms"] for row in rows) if rows else 0,
            "p50": statistics.median(row["latency_ms"] for row in rows) if rows else 0,
            "p95": sorted(row["latency_ms"] for row in rows)[max(0, int(len(rows) * 0.95) - 1)] if rows else 0,
            "max": max(row["latency_ms"] for row in rows) if rows else 0,
            "avg": sum(row["latency_ms"] for row in rows) / len(rows) if rows else 0.0,
        },
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# P3-1 Dense Baseline Report")
    lines.append("")
    lines.append(f"- generated_at: {report['generated_at']}")
    lines.append(f"- collection: `{report['collection']}`")
    lines.append(f"- mode: `{report['mode']}`")
    lines.append(f"- query_count: {report['metrics']['query_count']}")
    lines.append("")
    lines.append("## Metrics")
    metrics = report["metrics"]
    lines.append(f"- doc_recall@1: {metrics['doc_recall_at_1']:.3f}")
    lines.append(f"- doc_recall@3: {metrics['doc_recall_at_3']:.3f}")
    lines.append(f"- hit@1: {metrics['hit_at_1']:.3f}")
    lines.append(f"- hit@3: {metrics['hit_at_3']:.3f}")
    lines.append(f"- citation_correctness@3: {metrics['citation_correctness_at_3']:.3f}")
    lines.append(f"- mrr@3: {metrics['mrr_at_3']:.3f}")
    latency = metrics["latency_ms"]
    lines.append(
        f"- latency_ms: min={latency['min']}, p50={latency['p50']}, p95={latency['p95']}, max={latency['max']}, avg={latency['avg']:.1f}"
    )
    lines.append("")
    lines.append("## Query Details")
    for row in report["queries"]:
        lines.append(f"### {row['id']}")
        lines.append(f"- query: {row['query']}")
        lines.append(f"- gold_doc_ids: {', '.join(row['gold_doc_ids'])}")
        lines.append(f"- gold_chunk_ids: {', '.join(row['gold_chunk_ids'])}")
        lines.append(f"- top1_doc_id: {row['top1_doc_id']}")
        lines.append(f"- top1_chunk_id: {row['top1_chunk_id']}")
        lines.append(f"- doc_recall@3: {row['doc_recall_at_3']}")
        lines.append(f"- hit@3: {row['hit_at_3']}")
        lines.append(f"- citation_correctness@3: {row['citation_correctness_at_3']}")
        lines.append(f"- mrr@3: {row['mrr_at_3']:.3f}")
        lines.append(f"- latency_ms: {row['latency_ms']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    original_collection_name = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    original_vector_collection_name = vector_store_manager.collection_name
    original_vector_store = vector_store_manager.vector_store
    original_metadata_store_module = vector_index_module.knowledge_metadata_store
    original_ingestion_metadata_store = ingestion_module.knowledge_metadata_store

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
        vector_index_module.knowledge_metadata_store = temp_store
        ingestion_module.knowledge_metadata_store = temp_store
        milvus_client_module.MilvusClientManager.COLLECTION_NAME = BASELINE_COLLECTION
        vector_store_manager.collection_name = BASELINE_COLLECTION
        vector_store_manager.vector_store = None

        try:
            cpu_path = REPO_ROOT / "aiops-docs" / "cpu_high_usage.md"
            memory_path = REPO_ROOT / "aiops-docs" / "memory_high_usage.md"

            index_service = vector_index_module.VectorIndexService()
            cpu_doc_id = index_service._build_doc_id("default", cpu_path)
            memory_doc_id = index_service._build_doc_id("default", memory_path)

            golden_queries = build_golden_queries(cpu_path, memory_path, cpu_doc_id, memory_doc_id)
            write_jsonl(EVAL_DIR / "golden_queries.jsonl", golden_queries)

            index_service.index_single_file(cpu_path.as_posix(), kb_id="default")
            index_service.index_single_file(memory_path.as_posix(), kb_id="default")

            mineru_record = build_mineru_fixture(tmp_root)
            temp_store.upsert_document(mineru_record)
            index_service.index_document_record(mineru_record)

            query_rows: list[dict[str, Any]] = []
            for item in golden_queries:
                query = RetrievalQuery(query=item["query"], top_k=3, knowledge_base_ids=["default"])
                start = time.perf_counter()
                response = retrieval_service_module.retrieval_service.retrieve(query)
                latency_ms = int((time.perf_counter() - start) * 1000)
                results = response.results[:3]

                top_doc_id = results[0].doc_id if results else ""
                top_chunk_id = results[0].chunk_id if results else ""
                doc_recall_at_1 = 1 if results and top_doc_id in item["gold_doc_ids"] else 0
                doc_recall_at_3 = 1 if any(r.doc_id in item["gold_doc_ids"] for r in results) else 0
                hit_at_1 = 1 if results and top_chunk_id in item["gold_chunk_ids"] else 0
                hit_at_3 = 1 if any(r.chunk_id in item["gold_chunk_ids"] for r in results) else 0

                first_match_rank = None
                citation_correctness_at_3 = 0
                for rank, result in enumerate(results, start=1):
                    if first_match_rank is None and result.chunk_id in item["gold_chunk_ids"]:
                        first_match_rank = rank
                    if any(exact_source_ref_match(result.source_ref, gold_ref) for gold_ref in item["gold_source_refs"]):
                        citation_correctness_at_3 = 1
                mrr_at_3 = 1 / first_match_rank if first_match_rank else 0.0

                query_rows.append(
                    {
                        "id": item["id"],
                        "query": item["query"],
                        "gold_doc_ids": item["gold_doc_ids"],
                        "gold_chunk_ids": item["gold_chunk_ids"],
                        "top1_doc_id": top_doc_id,
                        "top1_chunk_id": top_chunk_id,
                        "doc_recall_at_1": doc_recall_at_1,
                        "doc_recall_at_3": doc_recall_at_3,
                        "hit_at_1": hit_at_1,
                        "hit_at_3": hit_at_3,
                        "citation_correctness_at_3": citation_correctness_at_3,
                        "mrr_at_3": mrr_at_3,
                        "latency_ms": latency_ms,
                        "results": [
                            {
                                "rank": rank,
                                "doc_id": result.doc_id,
                                "chunk_id": result.chunk_id,
                                "score": result.score,
                                "citation_text": result.citation_text,
                                "source_ref": result.source_ref.model_dump(mode="json"),
                            }
                            for rank, result in enumerate(results, start=1)
                        ],
                    }
                )

            metrics = compute_metrics(query_rows)
            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": BASELINE_COLLECTION,
                "mode": "dense_only",
                "metrics": metrics,
                "queries": query_rows,
                "notes": [
                    "This is the initial P3-1 dense-only baseline over a small fixed golden query set.",
                    "It uses the current citation-aware dense retrieval path and a dedicated isolated Milvus collection.",
                    "The MinerU fixture is synthetic and exists only to cover text and table evidence shapes before hybrid/rerank work starts.",
                ],
            }

            report_json = REPORT_DIR / f"dense_only_baseline_{RUN_ID}.json"
            report_md = REPORT_DIR / f"dense_only_baseline_{RUN_ID}.md"
            write_json(report_json, report)
            report_md.write_text(format_markdown(report), encoding="utf-8")

            print(json.dumps({
                "golden_queries": str(EVAL_DIR / "golden_queries.jsonl"),
                "report_json": str(report_json),
                "report_md": str(report_md),
                "metrics": metrics,
            }, ensure_ascii=False, indent=2))

            return 0
        finally:
            vector_index_module.knowledge_metadata_store = original_metadata_store_module
            ingestion_module.knowledge_metadata_store = original_ingestion_metadata_store
            vector_store_manager.vector_store = None
            vector_store_manager.collection_name = original_vector_collection_name
            milvus_client_module.MilvusClientManager.COLLECTION_NAME = original_collection_name
            try:
                if utility.has_collection(BASELINE_COLLECTION):
                    utility.drop_collection(BASELINE_COLLECTION)
            except Exception:
                pass
            vector_store_manager.vector_store = original_vector_store


if __name__ == "__main__":
    raise SystemExit(main())
