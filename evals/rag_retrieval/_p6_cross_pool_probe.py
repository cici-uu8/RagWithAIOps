#!/usr/bin/env python3
"""P6 cross-candidate pool probe.

After _p6_corpus_kw_probe identified 12 cross candidates and we drafted 6
into p6_samples.jsonl (cross_001/002/003 partial-spread + cross_004/005/006
full-miss), this probe verifies pool_k=12 composition for ALL 12 candidates:

  - For each cross candidate, run RetrievalQuery with top_k=12 (= pool_k of
    the trigger eval per design §4.2: top_k * doc_oversample_factor = 3*4).
  - Report per-domain composition of the pool (does oracle have ≥3 chunks
    in correct_domain to filter to?).
  - Compute realistic O2-metric oracle_precision@3 = min(3, correct_domain
    pool count) / 3 — this tells us the upper bound on lift before the eval
    runs, so we can swap full-miss samples with empty-oracle samples.

Probe-only: no assertions, no implementation changes. Output:
evals/rag_retrieval/_p6_cross_pool_probe.json
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

EXPANDED_BASE = Path(__file__).resolve().parents[2] / "data" / "mineru" / "expanded_corpus"
AIOPS_DIR = REPO_ROOT / "aiops-docs"

MINERU_TARGETS: list[tuple[str, str, str, str]] = [
    ("contracts", "contracts_regulations",
     "beijing_construction_worker_labor_contract_template",
     "beijing_construction_worker_labor_contract_template.pdf"),
    ("contracts", "contracts_regulations",
     "nanchang_employment_cooperation_agreement_template",
     "nanchang_employment_cooperation_agreement_template.pdf"),
    ("contracts", "contracts_regulations",
     "nanchang_general_labor_contract_template",
     "nanchang_general_labor_contract_template.pdf"),
    ("manuals", "manuals", "h3c_campus_switch_installation_guide_cn",
     "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "manuals", "h3c_comware_v7_high_risk_command_reference_cn",
     "h3c_comware_v7_high_risk_command_reference_cn.pdf"),
    ("manuals", "manuals", "h3c_e528_config_guide_cn",
     "h3c_e528_config_guide_cn.pdf"),
    ("manuals", "manuals", "h3c_mc101_mc102_user_manual_cn",
     "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("manuals", "manuals", "h3c_switch_troubleshooting_guide_cn",
     "h3c_switch_troubleshooting_guide_cn.pdf"),
    ("papers", "papers", "arxiv_attention_is_all_you_need",
     "arxiv_attention_is_all_you_need.pdf"),
    ("papers", "papers", "arxiv_deep_residual_learning",
     "arxiv_deep_residual_learning.pdf"),
    ("papers", "papers", "arxiv_unet_biomedical_segmentation",
     "arxiv_unet_biomedical_segmentation.pdf"),
    ("papers", "papers", "arxiv_vision_transformer",
     "arxiv_vision_transformer.pdf"),
]

CANDIDATE_KB = "default"

# All 12 cross candidates from kw_probe + the 4 weak corpus_probe ones for
# breadth (lets us verify if any "weak" corpus_probe query in fact has lift
# potential we missed).
CROSS_CANDIDATES: list[tuple[str, str, str]] = [
    # (id, query, correct_domain) — from kw_probe
    ("p6_cross_001", "性能基准对比 浮点运算", "papers"),
    ("p6_cross_002", "时延 延迟 网络优化", "aiops-docs"),
    ("p6_cross_003", "归档 备份 日志存储", "manuals"),
    ("p6_cross_004", "断点续传 重试机制", "aiops-docs"),
    ("p6_cross_005", "并发 吞吐量 限流", "aiops-docs"),
    ("p6_cross_006", "性能 优化", "papers"),
    ("p6_cross_kw_007", "故障代码 ERROR 错误处理", "manuals"),
    ("p6_cross_kw_008", "embedding 向量表示", "papers"),
    ("p6_cross_kw_009", "文件传输协议", "manuals"),
    ("p6_cross_kw_010", "签订日期 生效时间", "contracts"),
    ("p6_cross_kw_011", "梯度下降 反向传播", "papers"),
    ("p6_cross_kw_012", "权利义务", "contracts"),
    ("p6_cross_kw_013", "防火墙 安全策略", "manuals"),
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup_isolated_index(tmp_root: Path, run_id: str):
    eval_collection = f"p6_cross_pool_probe_{run_id}"
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = temp_store
    ingestion_module.knowledge_metadata_store = temp_store
    retrieval_service_module.knowledge_metadata_store = temp_store
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = eval_collection
    vector_store_manager.collection_name = eval_collection
    vector_store_manager.vector_store = None
    return temp_store, eval_collection


def index_mineru_artifact(tmp_root, domain, subdir, stem, file_name,
                          index_service, metadata_store) -> str:
    src_dir = EXPANDED_BASE / subdir / stem
    if not src_dir.exists():
        raise FileNotFoundError(f"MinerU artifact missing: {src_dir}")
    doc_id = f"doc_p6_{domain}_{stem}"
    artifact_dir = tmp_root / "artifacts" / doc_id / "artifacts"
    original_dir = tmp_root / "artifacts" / doc_id / "original"
    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_dir, artifact_dir, dirs_exist_ok=True)
    original_path = original_dir / file_name
    original_path.write_bytes(b"%PDF-1.4 placeholder for probe")
    record = DocumentRecord(
        doc_id=doc_id, kb_id=CANDIDATE_KB, file_name=file_name, file_ext="pdf",
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


def index_aiops_corpus(index_service) -> dict[str, str]:
    file_to_doc_id: dict[str, str] = {}
    md_files = sorted(AIOPS_DIR.glob("*.md"))
    for md_file in md_files:
        doc_id = index_service._build_doc_id(CANDIDATE_KB, md_file.resolve())
        index_service.index_single_file(md_file.as_posix(), kb_id="default")
        file_to_doc_id[md_file.name] = doc_id
    return file_to_doc_id


def probe_pool(query: str, correct_domain: str,
               doc_id_to_domain: dict[str, str], pool_k: int) -> dict[str, Any]:
    q = RetrievalQuery(
        query=query, top_k=pool_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=[CANDIDATE_KB],
        result_aggregation=ResultAggregation.NONE,
    )
    resp = retrieval_service_module.retrieval_service.retrieve(q)
    pool_results = resp.results
    pool_domains = [doc_id_to_domain.get(r.doc_id, "unknown") for r in pool_results]
    correct_in_pool = sum(1 for d in pool_domains if d == correct_domain)

    # Domain composition of pool
    dom_counts: dict[str, int] = {}
    for d in pool_domains:
        dom_counts[d] = dom_counts.get(d, 0) + 1

    # Top-3 (actual) and oracle_top_3 (first 3 in correct_domain)
    actual_top3_domains = pool_domains[:3]
    actual_match3 = sum(1 for d in actual_top3_domains if d == correct_domain)
    oracle_top3_domains = [d for d in pool_domains if d == correct_domain][:3]
    oracle_match3 = len(oracle_top3_domains)

    # O2 metric upper bound
    actual_precision_3 = actual_match3 / 3
    oracle_precision_3 = oracle_match3 / 3
    lift = oracle_precision_3 - actual_precision_3

    return {
        "query": query,
        "correct_domain": correct_domain,
        "pool_size": len(pool_results),
        "pool_domain_counts": dom_counts,
        "correct_in_pool": correct_in_pool,
        "actual_top3_domains": actual_top3_domains,
        "actual_match_3": actual_match3,
        "oracle_match_3": oracle_match3,
        "actual_precision_3": actual_precision_3,
        "oracle_precision_3": oracle_precision_3,
        "lift": lift,
    }


def run() -> None:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    o_coll = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    o_vname = vector_store_manager.collection_name
    o_vstore = vector_store_manager.vector_store
    o_idx_store = vector_index_module.knowledge_metadata_store
    o_ing_store = ingestion_module.knowledge_metadata_store
    o_ret_store = retrieval_service_module.knowledge_metadata_store
    o_rerank = rerank_service.enabled

    eval_collection = ""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_store, eval_collection = setup_isolated_index(tmp_root, run_id)
        try:
            index_service = vector_index_module.VectorIndexService()
            doc_id_to_domain: dict[str, str] = {}
            print("INDEX 17 docs ...", end=" ", flush=True)
            for domain, subdir, stem, file_name in MINERU_TARGETS:
                doc_id = index_mineru_artifact(tmp_root, domain, subdir, stem,
                                                file_name, index_service, temp_store)
                doc_id_to_domain[doc_id] = domain
            for name, doc_id in index_aiops_corpus(index_service).items():
                doc_id_to_domain[doc_id] = "aiops-docs"
            print(f"done ({len(doc_id_to_domain)} docs).")
            print()
            print(f"{'id':<22} {'correct':<11}  {'pool composition':<48}  "
                  f"{'corr_in_pool':>13}  {'a_p@3':>5}  {'o_p@3':>5}  {'lift':>5}")
            print("-" * 130)

            results = []
            for sid, query, dom in CROSS_CANDIDATES:
                row = probe_pool(query, dom, doc_id_to_domain, pool_k=12)
                row["id"] = sid
                results.append(row)
                comp = ", ".join(f"{d}={c}" for d, c in
                                 sorted(row["pool_domain_counts"].items(), key=lambda x: -x[1]))
                print(f"{sid:<22} {dom:<11}  {comp:<48}  {row['correct_in_pool']:>13}  "
                      f"{row['actual_precision_3']:>5.2f}  "
                      f"{row['oracle_precision_3']:>5.2f}  "
                      f"{row['lift']:>5.2f}")

            # Threshold check
            thresh_lift = 0.10
            qual_count = sum(1 for r in results if r["lift"] >= thresh_lift)
            print()
            print(f"queries with lift >= {thresh_lift}: {qual_count}/{len(results)}")
            print(f"trigger threshold: lift >= 0.10 on >= 3 query → "
                  f"{'satisfied' if qual_count >= 3 else 'NOT satisfied'} (queries-only view)")

            out_path = REPO_ROOT / "evals" / "rag_retrieval" / "_p6_cross_pool_probe.json"
            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": eval_collection,
                "kb_id": CANDIDATE_KB,
                "metric": "O2 domain-level precision@3",
                "pool_k": 12,
                "doc_id_to_domain": doc_id_to_domain,
                "results": results,
            }
            write_json(out_path, payload)
            print(f"\nProbe output: {out_path}")
        finally:
            rerank_service.enabled = o_rerank
            vector_index_module.knowledge_metadata_store = o_idx_store
            ingestion_module.knowledge_metadata_store = o_ing_store
            retrieval_service_module.knowledge_metadata_store = o_ret_store
            vector_store_manager.vector_store = None
            vector_store_manager.collection_name = o_vname
            milvus_client_module.MilvusClientManager.COLLECTION_NAME = o_coll
            try:
                if eval_collection and utility.has_collection(eval_collection):
                    utility.drop_collection(eval_collection)
            except Exception:
                pass
            vector_store_manager.vector_store = o_vstore


if __name__ == "__main__":
    run()
