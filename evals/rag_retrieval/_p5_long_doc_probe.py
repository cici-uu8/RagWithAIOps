#!/usr/bin/env python3
"""P5 long-doc probe.

Step 2 A2 step 3 prep work: index 3 MinerU long-doc artifacts into an isolated
Milvus collection + isolated metadata store, then probe:

  1. Per-doc post-policy chunk count (children) and parent count.
  2. Total chunks across the 3 docs.
  3. Recall doc distribution under candidate queries (top-3 and pool=12)
     under NONE strategy. This data feeds sample design for run_p5_long_doc_eval.py
     and avoids designing samples by semantic intuition (the trap from P5 round-1/2).

This is a probe, not a permanent eval. It does not assert anything; it only
prints structured output.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path("/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from pymilvus import utility

from app.config import config
from app.core import milvus_client as milvus_client_module
from app.models import (
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

ARTIFACT_BASE = Path("/Users/cici/oncall agent/pdf_eval/outputs/postprocessed/mineru/expanded_corpus")
TARGETS = [
    ("manuals", "h3c_campus_switch_installation_guide_cn", "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "h3c_mc101_mc102_user_manual_cn", "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("papers", "arxiv_vision_transformer", "arxiv_vision_transformer.pdf"),
]

CANDIDATE_QUERIES = [
    # CN manual content (likely concentrated in h3c docs)
    "交换机安装步骤 上架与机柜",
    "电源模块连接 接地保护",
    "端口配置 VLAN 划分",
    "防雷保护与浪涌保护",
    "硬件指示灯状态含义",
    # EN paper content (likely concentrated in arxiv_vit)
    "vision transformer self-attention image patches",
    "ViT pretraining JFT ImageNet performance",
    "transformer encoder layer normalization",
    "patch embedding position encoding",
    # potentially cross-doc: programmatic framework / generic
    "图1 参考",
    "Table 1 reference",
    "introduction section",
    "experimental setup",
    "performance comparison",
    "model architecture overview",
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup_isolated_index(tmp_root: Path, run_id: str):
    eval_collection = f"p5_long_doc_probe_{run_id}"
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = temp_store
    ingestion_module.knowledge_metadata_store = temp_store
    retrieval_service_module.knowledge_metadata_store = temp_store
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = eval_collection
    vector_store_manager.collection_name = eval_collection
    vector_store_manager.vector_store = None
    return temp_store, eval_collection


def index_artifact(
    tmp_root: Path,
    category: str,
    stem: str,
    file_name: str,
    index_service: vector_index_module.VectorIndexService,
    metadata_store: KnowledgeMetadataStore,
) -> str:
    """Copy artifact dir to temp, write manifest, ingest into temp Milvus.

    Returns the doc_id used for indexing.
    """
    src_dir = ARTIFACT_BASE / category / stem
    doc_id = f"doc_p5_long_{stem}"
    artifact_dir = tmp_root / "artifacts" / doc_id / "artifacts"
    original_dir = tmp_root / "artifacts" / doc_id / "original"
    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, artifact_dir, dirs_exist_ok=True)
    # original_path is needed by VectorIndexService._cleanup_existing_document_data
    original_path = original_dir / file_name
    original_path.write_bytes(b"%PDF-1.4 placeholder for probe")

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


def report_corpus_state(metadata_store: KnowledgeMetadataStore) -> dict[str, Any]:
    chunks = metadata_store.list_chunks()
    by_doc: dict[str, dict[str, int]] = {}
    for c in chunks:
        d = by_doc.setdefault(c.doc_id, {"children": 0, "parents": 0})
        if c.metadata.get("chunk_role") == "parent":
            d["parents"] += 1
        else:
            d["children"] += 1
    return by_doc


def probe_recall_distribution(query_text: str, top_k: int, pool_k: int) -> dict[str, Any]:
    """Return doc_id distribution for top-k and pool-k under NONE strategy."""
    results_top: list = []
    results_pool: list = []
    q_top = RetrievalQuery(
        query=query_text,
        top_k=top_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=["default"],
        result_aggregation=ResultAggregation.NONE,
    )
    resp_top = retrieval_service_module.retrieval_service.retrieve(q_top)
    results_top = resp_top.results

    q_pool = q_top.model_copy(update={"top_k": pool_k})
    resp_pool = retrieval_service_module.retrieval_service.retrieve(q_pool)
    results_pool = resp_pool.results

    return {
        "query": query_text,
        "top_doc_ids": [r.doc_id for r in results_top],
        "top_distinct_doc_count": len({r.doc_id for r in results_top}),
        "pool_doc_ids": [r.doc_id for r in results_pool],
        "pool_distinct_doc_count": len({r.doc_id for r in results_pool}),
        "top_chunk_ids_short": [r.chunk_id.split(":")[-1] for r in results_top],
    }


def run() -> None:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    original_collection_name = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    original_vector_collection_name = vector_store_manager.collection_name
    original_vector_store = vector_store_manager.vector_store
    original_metadata_store_module = vector_index_module.knowledge_metadata_store
    original_ingestion_metadata_store = ingestion_module.knowledge_metadata_store
    original_retrieval_metadata_store = retrieval_service_module.knowledge_metadata_store
    original_rerank_enabled = rerank_service.enabled

    eval_collection = ""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_store, eval_collection = setup_isolated_index(tmp_root, run_id)
        try:
            index_service = vector_index_module.VectorIndexService()
            doc_ids: dict[str, str] = {}
            for category, stem, file_name in TARGETS:
                doc_id = index_artifact(
                    tmp_root, category, stem, file_name, index_service, temp_store
                )
                doc_ids[stem] = doc_id

            corpus_state = report_corpus_state(temp_store)
            print("=" * 60)
            print("CORPUS POST-POLICY STATE")
            print("=" * 60)
            for stem, doc_id in doc_ids.items():
                state = corpus_state.get(doc_id, {"children": 0, "parents": 0})
                print(f"  {stem}")
                print(f"    doc_id = {doc_id}")
                print(f"    children = {state['children']}, parents = {state['parents']}")
            total_children = sum(s["children"] for s in corpus_state.values())
            total_parents = sum(s["parents"] for s in corpus_state.values())
            print(f"  TOTAL: children = {total_children}, parents = {total_parents}")

            print()
            print("=" * 60)
            print("RECALL PROBE (top_k=3, pool_k=12)")
            print("=" * 60)
            probe_results = []
            for q in CANDIDATE_QUERIES:
                row = probe_recall_distribution(q, top_k=3, pool_k=12)
                probe_results.append(row)
                short_doc_map = {v: k[:30] for k, v in doc_ids.items()}
                top_short = [short_doc_map.get(d, d[:8]) for d in row["top_doc_ids"]]
                pool_short = [short_doc_map.get(d, d[:8]) for d in row["pool_doc_ids"]]
                print(f"\n  Q: {q}")
                print(f"    top-3 distinct={row['top_distinct_doc_count']} docs={top_short}")
                print(f"    pool-12 distinct={row['pool_distinct_doc_count']} pool={pool_short}")

            # Save structured output for sample design.
            out_path = REPO_ROOT / "evals" / "rag_retrieval" / "_p5_long_doc_probe.json"
            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": eval_collection,
                "doc_ids": doc_ids,
                "corpus_state": corpus_state,
                "probe": probe_results,
            }
            write_json(out_path, payload)
            print(f"\nProbe output: {out_path}")
        finally:
            rerank_service.enabled = original_rerank_enabled
            vector_index_module.knowledge_metadata_store = original_metadata_store_module
            ingestion_module.knowledge_metadata_store = original_ingestion_metadata_store
            retrieval_service_module.knowledge_metadata_store = original_retrieval_metadata_store
            vector_store_manager.vector_store = None
            vector_store_manager.collection_name = original_vector_collection_name
            milvus_client_module.MilvusClientManager.COLLECTION_NAME = original_collection_name
            try:
                if eval_collection and utility.has_collection(eval_collection):
                    utility.drop_collection(eval_collection)
            except Exception:
                pass
            vector_store_manager.vector_store = original_vector_store


if __name__ == "__main__":
    run()
