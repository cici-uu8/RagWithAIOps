#!/usr/bin/env python3
"""P5 long-doc hit-text dump for keyword selection.

Dumps the first 500 chars of each NONE@top-3 hit chunk content for the 18
proposed samples, so I can pick expected_keywords that actually appear in the
real recall hits (not by semantic intuition). Runs once, output saved as
plain text for easy reading.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
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
    DocumentRecord, DocumentStatus, ParserEngine,
    ResultAggregation, RetrievalMode, RetrievalQuery,
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
QUERIES = [
    ("p5_long_same_001", "固件升级 软件版本切换"),
    ("p5_long_same_002", "ping 网络诊断 连通性测试"),
    ("p5_long_same_003", "查看运行日志 故障排查"),
    ("p5_long_same_004", "恢复出厂设置 重置配置"),
    ("p5_long_same_005", "测试 性能 评估 指标"),
    ("p5_long_same_006", "硬件指示灯状态含义"),
    ("p5_long_cross_001", "电源模块连接 接地保护"),
    ("p5_long_cross_002", "Table 1 reference"),
    ("p5_long_cross_003", "experimental setup"),
    ("p5_long_cross_004", "performance comparison"),
    ("p5_long_cross_005", "登录设备 console 命令行配置"),
    ("p5_long_cross_006", "参考文献 引用 来源"),
    ("p5_long_reverse_001", "交换机安装步骤 上架与机柜"),
    ("p5_long_reverse_002", "端口配置 VLAN 划分"),
    ("p5_long_reverse_003", "防雷保护与浪涌保护"),
    ("p5_long_reverse_004", "vision transformer self-attention image patches"),
    ("p5_long_reverse_005", "ViT pretraining JFT ImageNet performance"),
    ("p5_long_reverse_006", "transformer encoder layer normalization"),
]


def setup(tmp_root: Path, run_id: str):
    coll = f"p5_long_hit_dump_{run_id}"
    ts = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = ts
    ingestion_module.knowledge_metadata_store = ts
    retrieval_service_module.knowledge_metadata_store = ts
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = coll
    vector_store_manager.collection_name = coll
    vector_store_manager.vector_store = None
    return ts, coll


def index_one(tmp_root, cat, stem, fn, idx, store) -> str:
    src = ARTIFACT_BASE / cat / stem
    doc_id = f"doc_p5_long_{stem}"
    a = tmp_root / "artifacts" / doc_id / "artifacts"
    o = tmp_root / "artifacts" / doc_id / "original"
    a.parent.mkdir(parents=True, exist_ok=True)
    o.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, a, dirs_exist_ok=True)
    op = o / fn
    op.write_bytes(b"%PDF-1.4 placeholder")
    rec = DocumentRecord(
        doc_id=doc_id, kb_id="default", file_name=fn, file_ext="pdf",
        original_path=op.as_posix(), artifact_dir=a.as_posix(),
        parser_engine=ParserEngine.MINERU, status=DocumentStatus.PARSED,
        parser_version="mineru-3.1.11",
        created_at=datetime.now(), updated_at=datetime.now(),
    )
    artifact_manifest_service.write_manifest(rec)
    store.upsert_document(rec)
    idx.index_document_record(rec)
    return doc_id


def run() -> None:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    o_coll = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    o_vname = vector_store_manager.collection_name
    o_vstore = vector_store_manager.vector_store
    o_idx_store = vector_index_module.knowledge_metadata_store
    o_ing_store = ingestion_module.knowledge_metadata_store
    o_ret_store = retrieval_service_module.knowledge_metadata_store
    o_rerank = rerank_service.enabled
    coll = ""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        store, coll = setup(tmp_root, run_id)
        try:
            idx = vector_index_module.VectorIndexService()
            doc_ids = {}
            for cat, stem, fn in TARGETS:
                doc_ids[stem] = index_one(tmp_root, cat, stem, fn, idx, store)
            short = {v: k for k, v in doc_ids.items()}

            lines = []
            for sid, q in QUERIES:
                resp = retrieval_service_module.retrieval_service.retrieve(
                    RetrievalQuery(
                        query=q, top_k=3,
                        retrieval_mode=RetrievalMode.DENSE_ONLY,
                        knowledge_base_ids=["default"],
                        result_aggregation=ResultAggregation.NONE,
                    )
                )
                lines.append(f"\n{'=' * 80}\n{sid} :: {q}\n{'=' * 80}")
                for i, r in enumerate(resp.results, 1):
                    sd = short.get(r.doc_id, r.doc_id[:8])
                    body = r.content.replace("\n", " ").strip()[:500]
                    lines.append(f"[hit {i}] doc={sd}  chunk_id={r.chunk_id.split(':')[-1]}")
                    lines.append(f"  {body}")
            out = REPO_ROOT / "evals" / "rag_retrieval" / "_p5_long_doc_hit_dump.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"Hit dump: {out}")
        finally:
            rerank_service.enabled = o_rerank
            vector_index_module.knowledge_metadata_store = o_idx_store
            ingestion_module.knowledge_metadata_store = o_ing_store
            retrieval_service_module.knowledge_metadata_store = o_ret_store
            vector_store_manager.vector_store = None
            vector_store_manager.collection_name = o_vname
            milvus_client_module.MilvusClientManager.COLLECTION_NAME = o_coll
            try:
                if coll and utility.has_collection(coll):
                    utility.drop_collection(coll)
            except Exception:
                pass
            vector_store_manager.vector_store = o_vstore


if __name__ == "__main__":
    run()
