#!/usr/bin/env python3
"""Re-verify keywords from p5_long_doc_samples.jsonl after manual swaps.

Reads the saved samples file, re-runs NONE@top-3, and checks every
expected_keyword appears at least once in the joined hit content.
This is the gate before running run_p5_long_doc_eval.py.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path("/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21")
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
ARTIFACT_BASE = Path("/Users/cici/oncall agent/pdf_eval/outputs/postprocessed/mineru/expanded_corpus")
TARGETS = [
    ("manuals", "h3c_campus_switch_installation_guide_cn", "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "h3c_mc101_mc102_user_manual_cn", "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("papers", "arxiv_vision_transformer", "arxiv_vision_transformer.pdf"),
]


def setup(tmp_root, run_id):
    coll = f"p5_long_recheck_{run_id}"
    ts = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = ts
    ingestion_module.knowledge_metadata_store = ts
    retrieval_service_module.knowledge_metadata_store = ts
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = coll
    vector_store_manager.collection_name = coll
    vector_store_manager.vector_store = None
    return ts, coll


def index_one(tmp_root, cat, stem, fn, idx, store):
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


def run():
    samples_path = REPO_ROOT / "evals" / "rag_retrieval" / "p5_long_doc_samples.jsonl"
    samples = [json.loads(l) for l in samples_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    o_coll = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    o_vname = vector_store_manager.collection_name
    o_vstore = vector_store_manager.vector_store
    o_idx_store = vector_index_module.knowledge_metadata_store
    o_ing_store = ingestion_module.knowledge_metadata_store
    o_ret_store = retrieval_service_module.knowledge_metadata_store
    o_rerank = rerank_service.enabled
    coll = ""
    failed_samples = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        store, coll = setup(tmp_root, run_id)
        try:
            idx = vector_index_module.VectorIndexService()
            for cat, stem, fn in TARGETS:
                index_one(tmp_root, cat, stem, fn, idx, store)
            for s in samples:
                resp = retrieval_service_module.retrieval_service.retrieve(
                    RetrievalQuery(
                        query=s["query"], top_k=3,
                        retrieval_mode=RetrievalMode.DENSE_ONLY,
                        knowledge_base_ids=["default"],
                        result_aggregation=ResultAggregation.NONE,
                    )
                )
                joined = "\n\n".join(r.content for r in resp.results)
                missing = [kw for kw in s["expected_keywords"] if kw not in joined]
                tag = "OK" if not missing else "FAIL"
                print(f"  {s['id']:25s} [{tag:4s}] {s['query'][:55]}")
                if missing:
                    failed_samples.append((s["id"], missing, [r.doc_id[:30] for r in resp.results]))
            print()
            print(f"Total: {len(samples)}, OK: {len(samples) - len(failed_samples)}, FAIL: {len(failed_samples)}")
            for sid, miss, doc_ids in failed_samples:
                print(f"  {sid}: missing={miss}, top_doc={doc_ids}")
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
    return failed_samples


if __name__ == "__main__":
    failed = run()
    sys.exit(0 if not failed else 1)
