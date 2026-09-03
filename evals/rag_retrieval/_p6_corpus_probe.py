#!/usr/bin/env python3
"""P6 corpus probe.

Index the P6 mixed-domain corpus (4 domains: contracts, manuals, papers,
aiops-docs; 17 docs total) into an isolated Milvus collection + isolated
metadata store, then probe candidate queries to surface dense-retrieval
hit distribution. Output feeds sample design for run_p6_trigger_eval.py.

Per design §3 / §7:
- Single kb_id = "default" (mixed parser engines: plain_text + MinerU).
- doc_id -> domain map is built explicitly during indexing; do not rely on
  doc_id prefix reverse-lookup (plain_text doc_ids are hash-form).
- Any single ingestion failure halts the run with a root-cause report
  (mixed parser-engine ingestion is first live in eval framework here).

Probe-only: no assertions, no implementation changes. Outputs JSON for
sample-design hand-off.
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

# (domain, expanded_corpus subdir, doc stem, original filename)
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

# Candidate queries spread across 4 domains. Probe will report dense top-3
# distribution + folder/domain composition; sample design picks 18 from this
# pool after seeing real hit data (per P5.f1 lesson: do NOT trust intuition).
CANDIDATE_QUERIES: list[tuple[str, str]] = [
    # contracts (CN, contract/policy register)
    ("试用期最长不能超过多少", "contracts"),
    ("劳动合同终止条件", "contracts"),
    ("工伤保险责任认定", "contracts"),
    ("合同甲方乙方签字盖章要求", "contracts"),
    ("违约金计算方式", "contracts"),
    ("社会保险缴纳基数", "contracts"),
    # manuals (CN, network device CLI / config)
    ("交换机端口聚合配置命令", "manuals"),
    ("VLAN划分与配置步骤", "manuals"),
    ("OSPF路由协议配置", "manuals"),
    ("display version命令输出", "manuals"),
    ("STP生成树协议参数", "manuals"),
    ("ACL访问控制列表配置", "manuals"),
    # papers (EN, academic ML/CV)
    ("self-attention multi-head transformer", "papers"),
    ("residual connection skip identity mapping", "papers"),
    ("U-Net biomedical image segmentation", "papers"),
    ("vision transformer image patches embedding", "papers"),
    ("encoder decoder architecture", "papers"),
    ("BLEU score machine translation", "papers"),
    # aiops-docs (CN, ops SOP)
    ("CPU使用率过高排查", "aiops-docs"),
    ("磁盘占用满 处理步骤", "aiops-docs"),
    ("内存使用率高定位方法", "aiops-docs"),
    ("服务不可用 排查思路", "aiops-docs"),
    ("响应慢 定位方法", "aiops-docs"),
    # cross-domain-tempting candidates (probe whether these get pulled cross-folder)
    ("性能 优化", "cross"),
    ("配置 步骤", "cross"),
    ("故障 处理", "cross"),
    ("协议 参数", "cross"),
]

CANDIDATE_KB = "default"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def setup_isolated_index(tmp_root: Path, run_id: str):
    eval_collection = f"p6_corpus_probe_{run_id}"
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = temp_store
    ingestion_module.knowledge_metadata_store = temp_store
    retrieval_service_module.knowledge_metadata_store = temp_store
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = eval_collection
    vector_store_manager.collection_name = eval_collection
    vector_store_manager.vector_store = None
    return temp_store, eval_collection


def index_mineru_artifact(
    tmp_root: Path,
    domain: str,
    subdir: str,
    stem: str,
    file_name: str,
    index_service: vector_index_module.VectorIndexService,
    metadata_store: KnowledgeMetadataStore,
) -> str:
    """Copy artifact dir to tmp, write manifest, ingest.

    Mirrors the P5.f1 long-doc probe approach. Halts (raises) on failure
    per design §7.
    """
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
        doc_id=doc_id,
        kb_id=CANDIDATE_KB,
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


def index_aiops_corpus(
    index_service: vector_index_module.VectorIndexService,
) -> dict[str, str]:
    """Index aiops-docs/*.md via plain_text path.

    Returns {filename: doc_id}. Halts on any failure.
    """
    file_to_doc_id: dict[str, str] = {}
    md_files = sorted(AIOPS_DIR.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No aiops-docs markdown files under {AIOPS_DIR}")
    for md_file in md_files:
        doc_id = index_service._build_doc_id(CANDIDATE_KB, md_file.resolve())
        index_service.index_single_file(md_file.as_posix(), kb_id="default")
        file_to_doc_id[md_file.name] = doc_id
    return file_to_doc_id


def report_corpus_state(
    metadata_store: KnowledgeMetadataStore,
    doc_id_to_domain: dict[str, str],
) -> dict[str, Any]:
    chunks = metadata_store.list_chunks()
    by_doc: dict[str, dict[str, Any]] = {}
    for c in chunks:
        d = by_doc.setdefault(
            c.doc_id,
            {"children": 0, "parents": 0, "domain": doc_id_to_domain.get(c.doc_id, "unknown")},
        )
        if c.metadata.get("chunk_role") == "parent":
            d["parents"] += 1
        else:
            d["children"] += 1
    return by_doc


def probe_recall_distribution(
    query_text: str,
    expected_domain: str,
    doc_id_to_domain: dict[str, str],
    top_k: int,
    pool_k: int,
) -> dict[str, Any]:
    q_top = RetrievalQuery(
        query=query_text,
        top_k=top_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=[CANDIDATE_KB],
        result_aggregation=ResultAggregation.NONE,
    )
    resp_top = retrieval_service_module.retrieval_service.retrieve(q_top)
    top_results = resp_top.results

    q_pool = q_top.model_copy(update={"top_k": pool_k})
    resp_pool = retrieval_service_module.retrieval_service.retrieve(q_pool)
    pool_results = resp_pool.results

    def _domain(doc_id: str) -> str:
        return doc_id_to_domain.get(doc_id, "unknown")

    top_domains = [_domain(r.doc_id) for r in top_results]
    pool_domains = [_domain(r.doc_id) for r in pool_results]

    top_domain_match = sum(1 for d in top_domains if d == expected_domain)
    pool_domain_match = sum(1 for d in pool_domains if d == expected_domain)

    return {
        "query": query_text,
        "expected_domain": expected_domain,
        "top_domains": top_domains,
        "top_domain_match_count": top_domain_match,
        "top_distinct_doc_count": len({r.doc_id for r in top_results}),
        "top_doc_ids": [r.doc_id for r in top_results],
        "top_chunk_ids_short": [r.chunk_id.split(":")[-1] for r in top_results],
        "pool_domains": pool_domains,
        "pool_domain_match_count": pool_domain_match,
        "pool_distinct_doc_count": len({r.doc_id for r in pool_results}),
        "pool_doc_ids": [r.doc_id for r in pool_results],
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

            print("=" * 60)
            print("INDEX MINERU ARTIFACTS (12 docs)")
            print("=" * 60)
            for domain, subdir, stem, file_name in MINERU_TARGETS:
                doc_id = index_mineru_artifact(
                    tmp_root, domain, subdir, stem, file_name, index_service, temp_store
                )
                doc_id_to_domain[doc_id] = domain
                print(f"  [{domain}] {stem} -> {doc_id}")

            print()
            print("=" * 60)
            print("INDEX AIOPS PLAIN_TEXT (5 docs)")
            print("=" * 60)
            aiops_map = index_aiops_corpus(index_service)
            for name, doc_id in aiops_map.items():
                doc_id_to_domain[doc_id] = "aiops-docs"
                print(f"  [aiops-docs] {name} -> {doc_id}")

            print()
            print("=" * 60)
            print("CORPUS POST-POLICY STATE (per doc)")
            print("=" * 60)
            corpus_state = report_corpus_state(temp_store, doc_id_to_domain)
            domain_totals: dict[str, dict[str, int]] = {}
            for doc_id, state in corpus_state.items():
                dom = state["domain"]
                t = domain_totals.setdefault(dom, {"docs": 0, "children": 0, "parents": 0})
                t["docs"] += 1
                t["children"] += state["children"]
                t["parents"] += state["parents"]
                short = doc_id if len(doc_id) <= 70 else doc_id[:67] + "..."
                print(f"  [{dom}] {short}: c={state['children']} p={state['parents']}")
            print()
            print("  --- per-domain totals ---")
            for dom, t in sorted(domain_totals.items()):
                print(f"  [{dom}] docs={t['docs']} children={t['children']} parents={t['parents']}")

            print()
            print("=" * 60)
            print(f"RECALL PROBE (top_k=3, pool_k=12, queries={len(CANDIDATE_QUERIES)})")
            print("=" * 60)
            probe_results: list[dict[str, Any]] = []
            for q_text, expected_domain in CANDIDATE_QUERIES:
                row = probe_recall_distribution(
                    q_text, expected_domain, doc_id_to_domain, top_k=3, pool_k=12
                )
                probe_results.append(row)
                print(
                    f"\n  Q: {q_text}  [expected={expected_domain}]\n"
                    f"    top-3 domains={row['top_domains']} "
                    f"match={row['top_domain_match_count']}/3 "
                    f"distinct_docs={row['top_distinct_doc_count']}\n"
                    f"    pool-12 match={row['pool_domain_match_count']}/12 "
                    f"distinct_docs={row['pool_distinct_doc_count']}"
                )

            out_path = REPO_ROOT / "evals" / "rag_retrieval" / "_p6_corpus_probe.json"
            payload = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": eval_collection,
                "kb_id": CANDIDATE_KB,
                "doc_id_to_domain": doc_id_to_domain,
                "domain_totals": domain_totals,
                "corpus_state": corpus_state,
                "probe": probe_results,
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
