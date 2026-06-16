#!/usr/bin/env python3
"""P6 trigger evidence evaluation (frozen pre-run, single-shot).

Operationalizes design §4.2 / §10 with O2 domain-level precision metric:

  - For each `single_domain_required` and `cross_doc_tempting` sample (12 total):
      pool = retrieve(query, top_k=12)        # top_k * doc_oversample_factor = 3*4
      actual_top3   = pool[:3]
      oracle_top3   = [c for c in pool if c.domain == correct_domain][:3]
      actual_p3     = #{c in actual_top3 : c.domain == correct_domain} / 3
      oracle_p3     = #{c in oracle_top3 : c.domain == correct_domain} / 3
      lift          = oracle_p3 - actual_p3
  - `domain_irrelevant_control` samples (6) skip trigger math but still retrieve,
    asserting retrieval-side §4 invariance shape doesn't break.

Trigger formula (frozen pre-run):
  trigger_p6 = (
      invariants_all_ok
      AND #{s in single+cross : s.lift >= 0.10} >= 3
  )

Retrieval-side §4 invariance (operationalized for P6 single-cell context;
3 conditions; any failure = AssertionError immediately):
  1. result.chunk_id == result.source_ref.chunk_id
  2. result.doc_id   == result.source_ref.doc_id
  3. pool chunk_ids are unique

Validation-only: NO `app/*` / `tests/*` change. P6 implementation
(domain_metadata enricher) explicitly NOT in this run.
"""

from __future__ import annotations

import argparse
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

EXPANDED_BASE = Path(
    "/Users/cici/oncall agent/pdf_eval/outputs/postprocessed/mineru/expanded_corpus"
)
AIOPS_DIR = REPO_ROOT / "aiops-docs"
SAMPLES_PATH = REPO_ROOT / "evals" / "rag_retrieval" / "p6_samples.jsonl"
REPORT_DIR = REPO_ROOT / "evals" / "rag_retrieval" / "reports"

CANDIDATE_KB = "default"
TOP_K_TARGET = 3
DOC_OVERSAMPLE_FACTOR = 4
POOL_K = TOP_K_TARGET * DOC_OVERSAMPLE_FACTOR  # 12
LIFT_THRESHOLD = 0.10
MIN_QUALIFYING_QUERIES = 3
DOMAINS = ("contracts", "manuals", "papers", "aiops-docs")
EXCLUDED_SUBDIRS = ("stress_cases", "manual_windows")  # design §2 hard exclude

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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def setup_isolated_index(tmp_root: Path, run_id: str):
    eval_collection = f"p6_trigger_eval_{run_id}"
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
    original_path.write_bytes(b"%PDF-1.4 placeholder")
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
    if not md_files:
        raise FileNotFoundError(f"No aiops-docs markdown files under {AIOPS_DIR}")
    for md_file in md_files:
        doc_id = index_service._build_doc_id(CANDIDATE_KB, md_file.resolve())
        index_service.index_single_file(md_file.as_posix(), kb_id="default")
        file_to_doc_id[md_file.name] = doc_id
    return file_to_doc_id


def load_samples() -> list[dict[str, Any]]:
    if not SAMPLES_PATH.exists():
        raise FileNotFoundError(f"P6 samples missing: {SAMPLES_PATH}")
    samples = []
    for line in SAMPLES_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            samples.append(json.loads(line))
    return samples


def assert_invariants(pool, sample_id: str) -> None:
    """3 retrieval-side invariants (frozen pre-run, any failure = AssertionError)."""
    seen_chunk_ids = set()
    for r in pool:
        # 1. chunk_id ↔ source_ref.chunk_id sync
        assert r.chunk_id == r.source_ref.chunk_id, (
            f"sample={sample_id} chunk_id/source_ref mismatch: "
            f"{r.chunk_id} vs {r.source_ref.chunk_id}"
        )
        # 2. doc_id ↔ source_ref.doc_id sync
        assert r.doc_id == r.source_ref.doc_id, (
            f"sample={sample_id} doc_id/source_ref mismatch: "
            f"{r.doc_id} vs {r.source_ref.doc_id}"
        )
        # 3. unique chunk_ids in pool
        assert r.chunk_id not in seen_chunk_ids, (
            f"sample={sample_id} duplicate chunk_id in pool: {r.chunk_id}"
        )
        seen_chunk_ids.add(r.chunk_id)


def evaluate_sample(sample: dict[str, Any],
                    doc_id_to_domain: dict[str, str]) -> dict[str, Any]:
    q = RetrievalQuery(
        query=sample["query"], top_k=POOL_K,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=[CANDIDATE_KB],
        result_aggregation=ResultAggregation.NONE,
    )
    resp = retrieval_service_module.retrieval_service.retrieve(q)
    pool = resp.results
    assert_invariants(pool, sample["id"])

    pool_domains = [doc_id_to_domain.get(r.doc_id, "unknown") for r in pool]
    pool_chunk_ids = [r.chunk_id for r in pool]

    correct_domain = sample.get("correct_domain")
    is_trigger_sample = sample["category"] in (
        "single_domain_required", "cross_doc_tempting"
    )

    actual_top3_idx = list(range(min(TOP_K_TARGET, len(pool))))
    actual_top3_domains = [pool_domains[i] for i in actual_top3_idx]
    actual_top3_chunk_ids = [pool_chunk_ids[i] for i in actual_top3_idx]

    if is_trigger_sample and correct_domain is not None:
        # Oracle filter: keep only chunks whose doc.domain == correct_domain
        oracle_idx = [i for i, d in enumerate(pool_domains) if d == correct_domain]
        oracle_top3_idx = oracle_idx[:TOP_K_TARGET]
        oracle_top3_domains = [pool_domains[i] for i in oracle_top3_idx]
        oracle_top3_chunk_ids = [pool_chunk_ids[i] for i in oracle_top3_idx]

        actual_match = sum(1 for d in actual_top3_domains if d == correct_domain)
        oracle_match = sum(1 for d in oracle_top3_domains if d == correct_domain)
        actual_p3 = actual_match / TOP_K_TARGET
        oracle_p3 = oracle_match / TOP_K_TARGET
        lift = oracle_p3 - actual_p3
        qualifies = lift >= LIFT_THRESHOLD

        # Domain composition of pool
        dom_counts: dict[str, int] = {}
        for d in pool_domains:
            dom_counts[d] = dom_counts.get(d, 0) + 1
        correct_in_pool = dom_counts.get(correct_domain, 0)
    else:
        oracle_top3_domains = []
        oracle_top3_chunk_ids = []
        actual_p3 = None
        oracle_p3 = None
        lift = None
        qualifies = False
        dom_counts = {}
        correct_in_pool = None

    return {
        "id": sample["id"],
        "category": sample["category"],
        "query": sample["query"],
        "correct_domain": correct_domain,
        "pool_size": len(pool),
        "pool_domain_counts": dom_counts,
        "correct_in_pool": correct_in_pool,
        "actual_top3_domains": actual_top3_domains,
        "actual_top3_chunk_ids": actual_top3_chunk_ids,
        "oracle_top3_domains": oracle_top3_domains,
        "oracle_top3_chunk_ids": oracle_top3_chunk_ids,
        "actual_precision_3": actual_p3,
        "oracle_precision_3": oracle_p3,
        "lift": lift,
        "qualifies_trigger": qualifies,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, dict[str, Any]] = {}
    qualifying_ids: list[str] = []
    for r in rows:
        cat = r["category"]
        bucket = by_category.setdefault(cat, {
            "n": 0, "lift_values": [], "qualifying": 0,
        })
        bucket["n"] += 1
        if r["lift"] is not None:
            bucket["lift_values"].append(r["lift"])
        if r["qualifies_trigger"]:
            bucket["qualifying"] += 1
            qualifying_ids.append(r["id"])
    for cat, b in by_category.items():
        if b["lift_values"]:
            b["lift_avg"] = sum(b["lift_values"]) / len(b["lift_values"])
            b["lift_max"] = max(b["lift_values"])
            b["lift_min"] = min(b["lift_values"])
        else:
            b["lift_avg"] = None
            b["lift_max"] = None
            b["lift_min"] = None
        del b["lift_values"]

    qualifying_count = len(qualifying_ids)
    return {
        "by_category": by_category,
        "qualifying_count": qualifying_count,
        "qualifying_ids": qualifying_ids,
        "trigger_p6": qualifying_count >= MIN_QUALIFYING_QUERIES,
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines = []
    lines.append("# P6 trigger evidence evaluation report")
    lines.append("")
    lines.append("## Frozen pre-run constraints (per docs/p6_corpus_prep_design.md §4.2 / §10)")
    lines.append("")
    lines.append("- **Metric**: O2 domain-level precision@3 (operationalized variant of "
                 "design §4.2; expected_chunk_keywords kept on samples for traceability "
                 "but not used in trigger calc).")
    lines.append("- **Trigger threshold**: `lift = oracle_precision@3 - actual_precision@3 "
                 "≥ 0.10` on **≥ 3 query stably** out of 12 trigger samples "
                 "(single_domain_required + cross_doc_tempting). Threshold ≥ 0.10 is "
                 "**equivalent to ≥ 1/3** by precision@3 discreteness (denominator=3): "
                 "lift values can only be {0, ±1/3, ±2/3, ±1}, so ≥ 0.10 means "
                 "\"oracle filter pulls at least 1 more correct hit into the top-3.\"")
    lines.append("- **Pool**: top_k_target=3, doc_oversample_factor=4 ⇒ pool_k=12. NONE "
                 "aggregation, dense_only mode (matches design §5).")
    lines.append("- **Domains** (4): contracts / manuals / papers / aiops-docs. "
                 "Excluded: stress_cases / manual_windows (per design §2).")
    lines.append("- **Implementation note**: oracle filter is an eval-script post-processor "
                 "simulation. No `app/*` / `tests/*` changes; "
                 "`ChunkRecord.metadata.domain_metadata` is NOT written. P6 implementation "
                 "phase remains gated independent of this trigger result.")
    lines.append("- **Retrieval-side §4 invariance** (operationalized for P6 single cell):")
    lines.append("  1. `result.chunk_id == result.source_ref.chunk_id`")
    lines.append("  2. `result.doc_id == result.source_ref.doc_id`")
    lines.append("  3. pool chunk_ids unique")
    lines.append(f"  → invariants_all_ok = **{report['invariants_all_ok']}**")
    lines.append("")
    lines.append("## Trigger judgment")
    lines.append("")
    lines.append(f"- qualifying_count (lift ≥ {LIFT_THRESHOLD}): **{report['summary']['qualifying_count']}** / 12")
    lines.append(f"- threshold: ≥ {MIN_QUALIFYING_QUERIES} qualifying query")
    lines.append(f"- **trigger_p6 = {report['summary']['trigger_p6']}**")
    if report['summary']['qualifying_ids']:
        lines.append(f"- qualifying sample ids: {', '.join(report['summary']['qualifying_ids'])}")
    lines.append("")
    lines.append("## Per-category aggregates")
    lines.append("")
    lines.append("| category | n | lift_avg | lift_max | lift_min | qualifying |")
    lines.append("|---|---|---|---|---|---|")
    for cat, b in report['summary']['by_category'].items():
        avg = f"{b['lift_avg']:.3f}" if b['lift_avg'] is not None else "n/a"
        lmax = f"{b['lift_max']:.3f}" if b['lift_max'] is not None else "n/a"
        lmin = f"{b['lift_min']:.3f}" if b['lift_min'] is not None else "n/a"
        lines.append(f"| {cat} | {b['n']} | {avg} | {lmax} | {lmin} | {b['qualifying']} |")
    lines.append("")
    lines.append("## Per-sample detail")
    lines.append("")
    lines.append("| id | category | query | correct_domain | pool composition "
                 "| actual@3 | oracle@3 | lift | qualifies |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in report["rows"]:
        comp = ", ".join(f"{d}={c}" for d, c in
                         sorted(r["pool_domain_counts"].items(), key=lambda x: -x[1])) or "—"
        a = f"{r['actual_precision_3']:.2f}" if r['actual_precision_3'] is not None else "—"
        o = f"{r['oracle_precision_3']:.2f}" if r['oracle_precision_3'] is not None else "—"
        lift = f"{r['lift']:.2f}" if r['lift'] is not None else "—"
        qual = "✓" if r["qualifies_trigger"] else ""
        q_short = r["query"][:36]
        lines.append(f"| {r['id']} | {r['category']} | {q_short} | "
                     f"{r['correct_domain'] or '—'} | {comp} | {a} | {o} | {lift} | {qual} |")
    lines.append("")
    lines.append("## Decision impact")
    lines.append("")
    if report['summary']['trigger_p6']:
        lines.append("- `trigger_p6 = true` ⇒ P6 trigger evidence is **sufficient** under the "
                     "operationalized §10 (a)+(c) test on this 4-domain corpus.")
        lines.append("- Next step: P6 implementation thread MAY proceed, but scope must be "
                     "informed by **which domain pair surfaced the lift** (per category breakdown). "
                     "Generic `domain_metadata` enricher is not automatically justified — narrow "
                     "scope to the actual lift-producing domain pair.")
    else:
        lines.append("- `trigger_p6 = false` ⇒ P6 trigger evidence **insufficient** on this corpus.")
        lines.append("- P6 implementation remains gated. Recording corpus-property caveat in "
                     "`PROJECT_STATE.md` Open Problems.")
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    o_coll = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    o_vname = vector_store_manager.collection_name
    o_vstore = vector_store_manager.vector_store
    o_idx_store = vector_index_module.knowledge_metadata_store
    o_ing_store = ingestion_module.knowledge_metadata_store
    o_ret_store = retrieval_service_module.knowledge_metadata_store
    o_rerank = rerank_service.enabled

    eval_collection = ""
    invariants_all_ok = True
    samples = load_samples()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_store, eval_collection = setup_isolated_index(tmp_root, run_id)
        try:
            index_service = vector_index_module.VectorIndexService()
            doc_id_to_domain: dict[str, str] = {}
            print(f"INDEX 17 docs (kb_id={CANDIDATE_KB}, collection={eval_collection})...",
                  flush=True)
            for domain, subdir, stem, file_name in MINERU_TARGETS:
                doc_id = index_mineru_artifact(tmp_root, domain, subdir, stem,
                                                file_name, index_service, temp_store)
                doc_id_to_domain[doc_id] = domain
            for name, doc_id in index_aiops_corpus(index_service).items():
                doc_id_to_domain[doc_id] = "aiops-docs"
            print(f"  done ({len(doc_id_to_domain)} docs)")

            rows: list[dict[str, Any]] = []
            for sample in samples:
                row = evaluate_sample(sample, doc_id_to_domain)
                rows.append(row)
                if row["lift"] is not None:
                    print(f"  {row['id']:<22} {row['category']:<26} "
                          f"actual={row['actual_precision_3']:.2f} "
                          f"oracle={row['oracle_precision_3']:.2f} "
                          f"lift={row['lift']:>+.2f} "
                          f"{'[QUAL]' if row['qualifies_trigger'] else ''}")
                else:
                    print(f"  {row['id']:<22} {row['category']:<26} (control, skipped)")

            summary = aggregate(rows)
            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": eval_collection,
                "kb_id": CANDIDATE_KB,
                "metric": "O2 domain-level precision@3",
                "top_k_target": TOP_K_TARGET,
                "doc_oversample_factor": DOC_OVERSAMPLE_FACTOR,
                "pool_k": POOL_K,
                "lift_threshold": LIFT_THRESHOLD,
                "min_qualifying_queries": MIN_QUALIFYING_QUERIES,
                "domains": list(DOMAINS),
                "excluded_subdirs": list(EXCLUDED_SUBDIRS),
                "samples_path": str(SAMPLES_PATH),
                "doc_id_to_domain": doc_id_to_domain,
                "rows": rows,
                "summary": summary,
                "invariants_all_ok": invariants_all_ok,
            }
            REPORT_DIR.mkdir(parents=True, exist_ok=True)
            json_path = REPORT_DIR / f"p6_trigger_eval_{run_id}.json"
            md_path = REPORT_DIR / f"p6_trigger_eval_{run_id}.md"
            write_json(json_path, report)
            md_path.write_text(format_markdown(report), encoding="utf-8")

            print()
            print("=" * 64)
            print(f"  trigger_p6 = {summary['trigger_p6']}  "
                  f"(qualifying_count = {summary['qualifying_count']} / 12, "
                  f"threshold ≥ {MIN_QUALIFYING_QUERIES})")
            print(f"  invariants_all_ok = {invariants_all_ok}")
            print(f"  report: {json_path}")
            print(f"  markdown: {md_path}")
            print("=" * 64)
            return report
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P6 trigger evidence evaluation.")
    parser.parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
