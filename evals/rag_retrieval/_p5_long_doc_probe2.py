#!/usr/bin/env python3
"""P5 long-doc probe round-2: same_doc_redundant candidate hunting.

Step 2 A2 step 3 prep work, single-round probe per user stop-loss:
re-index 3 long-doc artifacts, run 13 new candidate queries focused on
producing "NONE distinct=1, pool distinct>=2" patterns. This is the only
permitted second probe; if base rate of same_doc_redundant candidates
remains insufficient after this run, P5.f1 closes via path 4 (accept that
the 3-doc long-doc corpus has insufficient same_doc_redundant signal,
write it up as a corpus-level limitation).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
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

ARTIFACT_BASE = Path(__file__).resolve().parents[2] / "data" / "mineru" / "expanded_corpus"
TARGETS = [
    ("manuals", "h3c_campus_switch_installation_guide_cn", "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "h3c_mc101_mc102_user_manual_cn", "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("papers", "arxiv_vision_transformer", "arxiv_vision_transformer.pdf"),
]

# 13 new candidates, designed to produce "NONE distinct=1, pool distinct>=2" patterns.
CANDIDATE_QUERIES = [
    # 8 cross-H3C tech topics: NONE may concentrate in one H3C, pool may bleed the other.
    "登录设备 console 命令行配置",
    "查看 MAC 地址表 命令",
    "SSH 远程登录配置",
    "固件升级 软件版本切换",
    "ping 网络诊断 连通性测试",
    "查看运行日志 故障排查",
    "恢复出厂设置 重置配置",
    "Telnet 远程管理配置",
    # 3 generic academic/technical: NONE may concentrate, pool may include arxiv or other H3C.
    "参考文献 引用 来源",
    "数据 结果 比较 表",
    "测试 性能 评估 指标",
    # 2 arxiv-leaning generic: NONE may concentrate in arxiv, pool may bleed H3C.
    "默认 参数 配置 设置",
    "层 编号 计数",
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup_isolated_index(tmp_root: Path, run_id: str):
    eval_collection = f"p5_long_doc_probe2_{run_id}"
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = temp_store
    ingestion_module.knowledge_metadata_store = temp_store
    retrieval_service_module.knowledge_metadata_store = temp_store
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = eval_collection
    vector_store_manager.collection_name = eval_collection
    vector_store_manager.vector_store = None
    return temp_store, eval_collection


def index_artifact(
    tmp_root: Path, category: str, stem: str, file_name: str,
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


def probe(query_text: str, top_k: int, pool_k: int) -> dict[str, Any]:
    q_top = RetrievalQuery(
        query=query_text, top_k=top_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=["default"],
        result_aggregation=ResultAggregation.NONE,
    )
    resp_top = retrieval_service_module.retrieval_service.retrieve(q_top)
    resp_pool = retrieval_service_module.retrieval_service.retrieve(
        q_top.model_copy(update={"top_k": pool_k})
    )
    return {
        "query": query_text,
        "top_doc_ids": [r.doc_id for r in resp_top.results],
        "top_distinct_doc_count": len({r.doc_id for r in resp_top.results}),
        "pool_doc_ids": [r.doc_id for r in resp_pool.results],
        "pool_distinct_doc_count": len({r.doc_id for r in resp_pool.results}),
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
                doc_id = index_artifact(tmp_root, category, stem, file_name, index_service, temp_store)
                doc_ids[stem] = doc_id

            short_doc_map = {v: k for k, v in doc_ids.items()}
            results = []
            for q in CANDIDATE_QUERIES:
                row = probe(q, top_k=3, pool_k=12)
                results.append(row)
                top_short = [short_doc_map.get(d, d[:8]) for d in row["top_doc_ids"]]
                pool_count = Counter(short_doc_map.get(d, d[:8]) for d in row["pool_doc_ids"])
                tag = ""
                if row["top_distinct_doc_count"] == 1 and row["pool_distinct_doc_count"] >= 2:
                    tag = " [SAME_DOC_REDUNDANT CANDIDATE]"
                elif row["top_distinct_doc_count"] >= 2:
                    tag = " [cross_doc_already candidate]"
                print(f"\nQ: {q}{tag}")
                print(f"  top-3 distinct={row['top_distinct_doc_count']} top={top_short}")
                print(f"  pool-12 distinct={row['pool_distinct_doc_count']} pool_count={dict(pool_count)}")

            same_doc_count = sum(
                1 for r in results
                if r["top_distinct_doc_count"] == 1 and r["pool_distinct_doc_count"] >= 2
            )
            cross_count = sum(1 for r in results if r["top_distinct_doc_count"] >= 2)
            print()
            print("=" * 60)
            print(f"ROUND-2 SUMMARY (13 new queries)")
            print("=" * 60)
            print(f"  same_doc_redundant candidates: {same_doc_count} / 13")
            print(f"  cross_doc_already candidates:  {cross_count} / 13")

            out_path = REPO_ROOT / "evals" / "rag_retrieval" / "_p5_long_doc_probe2.json"
            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "doc_ids": doc_ids,
                "probe": results,
                "same_doc_redundant_candidates_round2": same_doc_count,
                "cross_doc_already_candidates_round2": cross_count,
            }
            write_json(out_path, payload)
            print(f"\nProbe-2 output: {out_path}")
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
