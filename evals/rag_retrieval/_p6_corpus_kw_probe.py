#!/usr/bin/env python3
"""P6 corpus keyword verification probe.

After _p6_corpus_probe showed all 4 domains exhibit STRONG single-domain
signal (23/23 single candidates @ top-3=3/3 match) and cross queries get
collapsed to a single domain, this probe locks 18 sample candidates by:

  1. Verifying each single-domain candidate's expected_keywords appears in
     NONE@top-3 hit text (P5.f1 lesson: don't pick keywords by intuition).
  2. For cross_doc_tempting candidates, verifying that dense top-3 actually
     misses the correct_domain (so oracle filter has lift potential).
  3. Dumping top-3 hit-text head + per-domain composition for sample-design
     hand-off.

Output: evals/rag_retrieval/_p6_corpus_kw_probe.json

Probe-only: no assertions, no implementation changes. Reuses corpus indexing
from _p6_corpus_probe.py (kb_id="default", isolated Milvus collection).
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

EXPANDED_BASE = Path("/Users/cici/oncall agent/pdf_eval/outputs/postprocessed/mineru/expanded_corpus")
AIOPS_DIR = REPO_ROOT / "aiops-docs"

MINERU_TARGETS: list[tuple[str, str, str, str]] = [
    ("contracts", "contracts_regulations", "beijing_construction_worker_labor_contract_template", "beijing_construction_worker_labor_contract_template.pdf"),
    ("contracts", "contracts_regulations", "nanchang_employment_cooperation_agreement_template", "nanchang_employment_cooperation_agreement_template.pdf"),
    ("contracts", "contracts_regulations", "nanchang_general_labor_contract_template", "nanchang_general_labor_contract_template.pdf"),
    ("manuals", "manuals", "h3c_campus_switch_installation_guide_cn", "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "manuals", "h3c_comware_v7_high_risk_command_reference_cn", "h3c_comware_v7_high_risk_command_reference_cn.pdf"),
    ("manuals", "manuals", "h3c_e528_config_guide_cn", "h3c_e528_config_guide_cn.pdf"),
    ("manuals", "manuals", "h3c_mc101_mc102_user_manual_cn", "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("manuals", "manuals", "h3c_switch_troubleshooting_guide_cn", "h3c_switch_troubleshooting_guide_cn.pdf"),
    ("papers", "papers", "arxiv_attention_is_all_you_need", "arxiv_attention_is_all_you_need.pdf"),
    ("papers", "papers", "arxiv_deep_residual_learning", "arxiv_deep_residual_learning.pdf"),
    ("papers", "papers", "arxiv_unet_biomedical_segmentation", "arxiv_unet_biomedical_segmentation.pdf"),
    ("papers", "papers", "arxiv_vision_transformer", "arxiv_vision_transformer.pdf"),
]

CANDIDATE_KB = "default"

# 6 single_domain_required candidates (selected from probe's 23 STRONG queries):
# 4-domain balanced 2/2/1/1. expected_keywords proposed; verify presence in top-3.
SINGLE_CANDIDATES: list[tuple[str, str, str, list[str]]] = [
    # (id, query, correct_domain, proposed_expected_keywords)
    ("p6_single_001", "试用期最长不能超过多少", "contracts", ["试用期", "六个月", "月"]),
    ("p6_single_002", "工伤保险责任认定", "contracts", ["工伤", "保险", "责任"]),
    ("p6_single_003", "VLAN划分与配置步骤", "manuals", ["VLAN", "配置", "划分"]),
    ("p6_single_004", "display version命令输出", "manuals", ["display", "version", "版本"]),
    ("p6_single_005", "self-attention multi-head transformer", "papers", ["attention", "transformer", "head"]),
    ("p6_single_006", "CPU使用率过高排查", "aiops-docs", ["CPU", "使用率", "排查"]),
]

# 12 cross_doc_tempting candidates (need dense top-3 to MISS correct_domain
# for oracle filter to have lift potential). Will collapse to 6 after probe.
CROSS_CANDIDATES: list[tuple[str, str, str, list[str]]] = [
    # 中文程序性词组，可能跨域：故障 / 排查 / 配置 / 性能 / 优化 / 测试
    ("p6_cross_001", "性能基准对比 浮点运算", "papers", ["performance", "FLOPs", "benchmark"]),
    ("p6_cross_002", "故障代码 ERROR 错误处理", "manuals", ["ERROR", "故障", "错误"]),
    ("p6_cross_003", "断点续传 重试机制", "aiops-docs", ["重试", "断点", "续传"]),
    ("p6_cross_004", "embedding 向量表示", "papers", ["embedding", "vector", "representation"]),
    ("p6_cross_005", "时延 延迟 网络优化", "aiops-docs", ["时延", "延迟", "响应"]),
    ("p6_cross_006", "归档 备份 日志存储", "manuals", ["归档", "备份", "日志"]),
    ("p6_cross_007", "文件传输协议", "manuals", ["FTP", "传输", "文件"]),
    ("p6_cross_008", "签订日期 生效时间", "contracts", ["生效", "签订", "日期"]),
    ("p6_cross_009", "并发 吞吐量 限流", "aiops-docs", ["并发", "限流", "吞吐"]),
    ("p6_cross_010", "梯度下降 反向传播", "papers", ["gradient", "backprop", "descent"]),
    ("p6_cross_011", "防火墙 安全策略", "manuals", ["防火墙", "安全", "策略"]),
    ("p6_cross_012", "权利义务", "contracts", ["权利", "义务", "甲方"]),
]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup_isolated_index(tmp_root: Path, run_id: str):
    eval_collection = f"p6_kw_probe_{run_id}"
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = temp_store
    ingestion_module.knowledge_metadata_store = temp_store
    retrieval_service_module.knowledge_metadata_store = temp_store
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = eval_collection
    vector_store_manager.collection_name = eval_collection
    vector_store_manager.vector_store = None
    return temp_store, eval_collection


def index_mineru_artifact(tmp_root, domain, subdir, stem, file_name, index_service, metadata_store) -> str:
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
        original_path=original_path.as_posix(), artifact_dir=artifact_dir.as_posix(),
        parser_engine=ParserEngine.MINERU, status=DocumentStatus.PARSED,
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
    if not md_files:
        raise FileNotFoundError(f"No aiops-docs markdown files under {AIOPS_DIR}")
    for md_file in md_files:
        doc_id = index_service._build_doc_id(CANDIDATE_KB, md_file.resolve())
        index_service.index_single_file(md_file.as_posix(), kb_id="default")
        file_to_doc_id[md_file.name] = doc_id
    return file_to_doc_id


def probe_one(query: str, correct_domain: str, kws: list[str], doc_id_to_domain: dict[str, str],
              category: str) -> dict[str, Any]:
    q = RetrievalQuery(
        query=query, top_k=3,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=[CANDIDATE_KB],
        result_aggregation=ResultAggregation.NONE,
    )
    resp = retrieval_service_module.retrieval_service.retrieve(q)
    top_results = resp.results
    joined = "\n\n".join(r.content for r in top_results)
    domains = [doc_id_to_domain.get(r.doc_id, "unknown") for r in top_results]
    domain_match = sum(1 for d in domains if d == correct_domain)

    keyword_counts = {kw: joined.count(kw) for kw in kws}
    all_present = all(c > 0 for c in keyword_counts.values())

    # Per-result hit-text head (first 300 chars; truncate long table content)
    hit_heads = []
    for r in top_results:
        head = r.content[:300]
        hit_heads.append({
            "doc_id": r.doc_id,
            "domain": doc_id_to_domain.get(r.doc_id, "unknown"),
            "chunk_id": r.chunk_id,
            "head": head,
        })

    # cross_doc_tempting suitability: dense MUST miss correct_domain for oracle to have lift
    if category == "cross_doc_tempting":
        cross_suitable = (domain_match == 0)
    else:
        cross_suitable = None

    return {
        "query": query,
        "correct_domain": correct_domain,
        "category": category,
        "top_doc_ids": [r.doc_id for r in top_results],
        "top_chunk_ids": [r.chunk_id for r in top_results],
        "top_domains": domains,
        "domain_match_count": domain_match,
        "keyword_counts": keyword_counts,
        "all_keywords_present": all_present,
        "cross_suitable": cross_suitable,
        "joined_chars": len(joined),
        "hit_heads": hit_heads,
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

            print(f"=" * 60)
            print(f"INDEX (12 MinerU + 5 plain_text aiops)")
            print(f"=" * 60)
            for domain, subdir, stem, file_name in MINERU_TARGETS:
                doc_id = index_mineru_artifact(tmp_root, domain, subdir, stem, file_name, index_service, temp_store)
                doc_id_to_domain[doc_id] = domain
            aiops_map = index_aiops_corpus(index_service)
            for name, doc_id in aiops_map.items():
                doc_id_to_domain[doc_id] = "aiops-docs"
            print(f"  total docs: {len(doc_id_to_domain)}")

            print()
            print(f"=" * 60)
            print(f"SINGLE CANDIDATES (6) — keyword + domain match check")
            print(f"=" * 60)
            single_results = []
            for sid, query, dom, kws in SINGLE_CANDIDATES:
                row = probe_one(query, dom, kws, doc_id_to_domain, "single_domain_required")
                row["id"] = sid
                single_results.append(row)
                kw_summary = ", ".join(f"{k}={v}" for k, v in row["keyword_counts"].items())
                tag = "OK" if row["all_keywords_present"] and row["domain_match_count"] == 3 else "WARN"
                print(f"  [{tag}] {sid}  q={query}")
                print(f"        domain_match={row['domain_match_count']}/3  kw_present={row['all_keywords_present']}  {kw_summary}")
                print(f"        top_domains={row['top_domains']}")

            print()
            print(f"=" * 60)
            print(f"CROSS CANDIDATES (12) — must miss correct_domain in top-3")
            print(f"=" * 60)
            cross_results = []
            for sid, query, dom, kws in CROSS_CANDIDATES:
                row = probe_one(query, dom, kws, doc_id_to_domain, "cross_doc_tempting")
                row["id"] = sid
                cross_results.append(row)
                kw_summary = ", ".join(f"{k}={v}" for k, v in row["keyword_counts"].items())
                cross_tag = "CROSS-OK" if row["cross_suitable"] else "no-spread"
                print(f"  [{cross_tag}] {sid}  q={query}  correct={dom}")
                print(f"        domain_match={row['domain_match_count']}/3  top_domains={row['top_domains']}")
                print(f"        kw {kw_summary}")

            cross_suitable_count = sum(1 for r in cross_results if r["cross_suitable"])
            print()
            print(f"  cross_suitable (dense misses correct_domain): {cross_suitable_count}/12")

            out_path = REPO_ROOT / "evals" / "rag_retrieval" / "_p6_corpus_kw_probe.json"
            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": eval_collection,
                "kb_id": CANDIDATE_KB,
                "doc_id_to_domain": doc_id_to_domain,
                "single_candidates": single_results,
                "cross_candidates": cross_results,
                "summary": {
                    "single_total": len(single_results),
                    "single_kw_ok": sum(1 for r in single_results if r["all_keywords_present"]),
                    "single_domain_ok": sum(1 for r in single_results if r["domain_match_count"] == 3),
                    "cross_total": len(cross_results),
                    "cross_suitable": cross_suitable_count,
                },
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
