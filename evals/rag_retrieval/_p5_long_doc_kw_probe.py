#!/usr/bin/env python3
"""P5 long-doc keyword verification probe.

Step 2 A2 step 3.5: for each of the 18 proposed samples, run NONE@top_3 and
check whether each proposed expected_keyword appears in the joined hit-chunk
content. Output a structured table so I can swap out keywords that don't
actually appear in NONE hits before locking the samples file.

Per user constraint: keywords must appear in the NONE-hit chunks at least
once, otherwise expected_keywords becomes noise.
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

# 18 samples with proposed keywords (will be verified; failed keywords swapped before save).
SAMPLES = [
    # === same_doc_redundant (6) ===
    ("p5_long_same_001", "same_doc_redundant", "固件升级 软件版本切换",
     ["固件", "升级", "版本"]),
    ("p5_long_same_002", "same_doc_redundant", "ping 网络诊断 连通性测试",
     ["ping", "网络", "连通"]),
    ("p5_long_same_003", "same_doc_redundant", "查看运行日志 故障排查",
     ["日志", "故障", "排查"]),
    ("p5_long_same_004", "same_doc_redundant", "恢复出厂设置 重置配置",
     ["恢复", "出厂", "重置"]),
    ("p5_long_same_005", "same_doc_redundant", "测试 性能 评估 指标",
     ["测试", "性能", "评估"]),
    ("p5_long_same_006", "same_doc_redundant", "硬件指示灯状态含义",
     ["指示灯", "状态", "硬件"]),
    # === cross_doc_already (6) ===
    ("p5_long_cross_001", "cross_doc_already", "电源模块连接 接地保护",
     ["电源", "接地", "保护"]),
    ("p5_long_cross_002", "cross_doc_already", "Table 1 reference",
     ["Table", "reference"]),
    ("p5_long_cross_003", "cross_doc_already", "experimental setup",
     ["experimental", "setup"]),
    ("p5_long_cross_004", "cross_doc_already", "performance comparison",
     ["performance", "comparison"]),
    ("p5_long_cross_005", "cross_doc_already", "登录设备 console 命令行配置",
     ["登录", "console", "命令"]),
    ("p5_long_cross_006", "cross_doc_already", "参考文献 引用 来源",
     ["参考文献", "引用"]),
    # === reverse_control (6) ===
    ("p5_long_reverse_001", "reverse_control", "交换机安装步骤 上架与机柜",
     ["交换机", "安装", "机柜"]),
    ("p5_long_reverse_002", "reverse_control", "端口配置 VLAN 划分",
     ["端口", "VLAN"]),
    ("p5_long_reverse_003", "reverse_control", "防雷保护与浪涌保护",
     ["防雷", "浪涌"]),
    ("p5_long_reverse_004", "reverse_control",
     "vision transformer self-attention image patches",
     ["transformer", "attention", "patches"]),
    ("p5_long_reverse_005", "reverse_control",
     "ViT pretraining JFT ImageNet performance",
     ["ViT", "ImageNet", "pretraining"]),
    ("p5_long_reverse_006", "reverse_control",
     "transformer encoder layer normalization",
     ["transformer", "encoder", "normalization"]),
]

# expected_doc_files mapping (doc_id will be resolved at probe time)
EXPECTED_DOCS = {
    "p5_long_reverse_001": ["h3c_campus_switch_installation_guide_cn"],
    "p5_long_reverse_002": ["h3c_mc101_mc102_user_manual_cn"],
    "p5_long_reverse_003": ["h3c_campus_switch_installation_guide_cn"],
    "p5_long_reverse_004": ["arxiv_vision_transformer"],
    "p5_long_reverse_005": ["arxiv_vision_transformer"],
    "p5_long_reverse_006": ["arxiv_vision_transformer"],
}


def setup_isolated_index(tmp_root: Path, run_id: str):
    eval_collection = f"p5_long_doc_kw_probe_{run_id}"
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
        doc_id=doc_id, kb_id="default", file_name=file_name, file_ext="pdf",
        original_path=original_path.as_posix(),
        artifact_dir=artifact_dir.as_posix(),
        parser_engine=ParserEngine.MINERU,
        status=DocumentStatus.PARSED,
        parser_version="mineru-3.1.11",
        created_at=datetime.now(), updated_at=datetime.now(),
    )
    artifact_manifest_service.write_manifest(record)
    metadata_store.upsert_document(record)
    index_service.index_document_record(record)
    return doc_id


def verify_keywords(query_text: str, proposed_kws: list[str]) -> dict[str, Any]:
    q = RetrievalQuery(
        query=query_text, top_k=3,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=["default"],
        result_aggregation=ResultAggregation.NONE,
    )
    resp = retrieval_service_module.retrieval_service.retrieve(q)
    joined = "\n\n".join(r.content for r in resp.results)
    coverage = {kw: joined.count(kw) for kw in proposed_kws}
    return {
        "query": query_text,
        "top_doc_ids": [r.doc_id for r in resp.results],
        "joined_chars": len(joined),
        "keyword_counts": coverage,
        "all_present": all(c > 0 for c in coverage.values()),
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

            short_map = {v: k for k, v in doc_ids.items()}
            verifications = []
            for sid, category, query, kws in SAMPLES:
                v = verify_keywords(query, kws)
                v["id"] = sid
                v["category"] = category
                v["proposed_keywords"] = kws
                v["top_doc_short"] = [short_map.get(d, d[:8]) for d in v["top_doc_ids"]]
                verifications.append(v)
                status = "OK" if v["all_present"] else "PARTIAL"
                print(f"{sid} [{status}] {query[:50]}")
                for kw, c in v["keyword_counts"].items():
                    flag = "" if c > 0 else " <<<MISSING"
                    print(f"    {kw}={c}{flag}")
                print(f"    top_doc={v['top_doc_short']}")

            failed = [v for v in verifications if not v["all_present"]]
            print()
            print(f"Total: {len(SAMPLES)}, all-present: {len(verifications) - len(failed)}, partial: {len(failed)}")
            if failed:
                print("Samples needing keyword swap:")
                for v in failed:
                    missing = [kw for kw, c in v["keyword_counts"].items() if c == 0]
                    print(f"  {v['id']} missing: {missing}")

            out_path = REPO_ROOT / "evals" / "rag_retrieval" / "_p5_long_doc_kw_probe.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "doc_ids": doc_ids,
                "expected_docs_per_sample": EXPECTED_DOCS,
                "verifications": verifications,
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"\nKeyword probe output: {out_path}")
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
