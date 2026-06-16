#!/usr/bin/env python3
"""P5.f3 LLM end-to-end citation drift evaluation.

Validation-only follow-up (P6 prerequisite step P5.f3). Reuses the 18 samples
and 3 MinerU long-doc artifacts from P5.f1 / P5.f2; the only new dimension is
a real LLM call. Sweeps the 3-cell matrix:

  NONE × chunk
  DOC_LEVEL × chunk
  DOC_LEVEL × parent_chunk

`full_doc` granularity is OUT-OF-SCOPE here (per design §4 and P5.f2 caveat
(a): DL × full_doc tokens_avg=46K exceeds qwen-max 32K context window on this
long-doc corpus). NONE × parent_chunk is excluded (per design §3) because
P5.f2 caveat (b) shows 0.833 fallback rate in this corpus, making the cell
near-degenerate to NONE × chunk.

Hard assertions (frozen pre-run):
  - retrieval-side §4 invariance (6 conditions, identical to P5.f2) on every
    sample × every retrieval granularity used. Any failure raises
    AssertionError immediately — that is a P5 / P4.5 implementation bug.

Soft observations (no pass/fail):
  - hallucination_rate: LLM cited chunk_ids outside the retrieval set
  - coverage_rate:      LLM cited at least one retrieval chunk_id
  - citation_jaccard:   |LLM ∩ retrieval| / |LLM ∪ retrieval|
  - empty_answer_rate / no_citation_rate

LLM proxy disclosure (REQUIRED, per design §5.5):
  These metrics measure citation_id alignment between prompt and answer, NOT
  factual citation correctness. A zero hallucination_rate does not prove the
  LLM cited the right chunk for the right fact; a positive hallucination_rate
  does not prove the LLM made up a wrong fact. Real factual citation
  correctness needs human or LLM-as-judge eval, OUT-OF-SCOPE here.

Per user execution stipulation: this script does NOT change P5 / P4.5 /
ChunkPolicy implementation under any condition. ChunkPolicy parent threshold
(P5.f2 caveat (b)) is explicitly out of P5.f3 scope.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


from langchain_openai import ChatOpenAI
from pymilvus import utility

from app.config import config
from app.core import milvus_client as milvus_client_module
from app.models import (
    ContextGranularity,
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

EVAL_DIR = REPO_ROOT / "evals" / "rag_retrieval"
REPORT_DIR = EVAL_DIR / "reports"
SAMPLES_PATH = EVAL_DIR / "p5_long_doc_samples.jsonl"  # reused from P5.f1/f2
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
EVAL_COLLECTION = f"p5_llm_eval_{RUN_ID}"

DEFAULT_TOP_K = 3
DEFAULT_TOP_CHUNKS_PER_DOC = 1
DEFAULT_OVERSAMPLE = 4
CATEGORIES = ["same_doc_redundant", "cross_doc_already", "reverse_control"]

# 3-cell main matrix per design §3. NONE × parent_chunk and full_doc are
# explicitly excluded (see module docstring).
CELL_DEFINITIONS: list[tuple[str, ResultAggregation, ContextGranularity]] = [
    ("none__chunk", ResultAggregation.NONE, ContextGranularity.CHUNK),
    ("doc_level__chunk", ResultAggregation.DOC_LEVEL, ContextGranularity.CHUNK),
    ("doc_level__parent_chunk", ResultAggregation.DOC_LEVEL, ContextGranularity.PARENT_CHUNK),
]

LLM_TEMPERATURE = 0.0
LLM_MAX_TOKENS = 1024
LLM_TIMEOUT_SECONDS = 30
LLM_MAX_RETRIES = 2  # 2 retries = 3 total attempts
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Soft thresholds for corner-case highlighting (NOT pass/fail).
COVERAGE_HIGHLIGHT_THRESHOLD = 0.5
EMPTY_ANSWER_HIGHLIGHT_THRESHOLD = 0.2
LLM_FAILURE_ABORT_THRESHOLD = 0.5  # >= 50% calls failed in any cell -> abort

CITATION_REGEX = re.compile(r"\[chunk:\s*([^\]]+?)\s*\]")

ARTIFACT_BASE = Path(
    "/Users/cici/oncall agent/pdf_eval/outputs/postprocessed/mineru/expanded_corpus"
)
TARGETS = [
    ("manuals", "h3c_campus_switch_installation_guide_cn",
     "h3c_campus_switch_installation_guide_cn.pdf"),
    ("manuals", "h3c_mc101_mc102_user_manual_cn",
     "h3c_mc101_mc102_user_manual_cn.pdf"),
    ("papers", "arxiv_vision_transformer",
     "arxiv_vision_transformer.pdf"),
]

PROMPT_TEMPLATE = """你是知识库问答助手。请基于给定的参考资料回答用户问题。

引用规则:
- 每个事实陈述后用 [chunk: <chunk_id>] 格式标注引用。
- <chunk_id> 必须是参考资料中出现过的 chunk 标识符。
- 如果参考资料里找不到答案，直接说"参考资料中未找到相关信息"。

参考资料:
{context_text}

用户问题: {query}

请按以下格式回答:
回答: <回答内容，每个事实后标注 [chunk: <chunk_id>]>"""


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_samples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"P5.f3 samples (reused from P5.f1/f2) not found: {path}")
    samples: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        samples.append(json.loads(line))
    if not samples:
        raise ValueError(f"P5.f3 samples empty: {path}")
    return samples


def setup_isolated(tmp_root: Path):
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
    vector_index_module.knowledge_metadata_store = temp_store
    ingestion_module.knowledge_metadata_store = temp_store
    retrieval_service_module.knowledge_metadata_store = temp_store
    milvus_client_module.MilvusClientManager.COLLECTION_NAME = EVAL_COLLECTION
    vector_store_manager.collection_name = EVAL_COLLECTION
    vector_store_manager.vector_store = None
    return temp_store


def index_artifact(
    tmp_root: Path,
    category: str,
    stem: str,
    file_name: str,
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
    original_path.write_bytes(b"%PDF-1.4 placeholder")
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


def index_corpus(
    tmp_root: Path,
    index_service: vector_index_module.VectorIndexService,
    metadata_store: KnowledgeMetadataStore,
) -> dict[str, str]:
    file_to_doc_id: dict[str, str] = {}
    for category, stem, file_name in TARGETS:
        doc_id = index_artifact(tmp_root, category, stem, file_name, index_service, metadata_store)
        file_to_doc_id[stem] = doc_id
    return file_to_doc_id


def _result_signature(result) -> dict[str, Any]:
    return {
        "chunk_id": result.chunk_id,
        "content": result.content,
        "citation_text": result.citation_text,
        "source_ref": result.source_ref.model_dump(mode="json"),
    }


def _build_llm() -> ChatOpenAI:
    """Construct a deterministic, non-streaming qwen-max client for evaluation.

    Not using `LLMFactory.create_chat_model` because it defaults to
    streaming=True without a timeout knob; eval needs reproducibility.
    """
    return ChatOpenAI(
        model=config.rag_model,
        temperature=LLM_TEMPERATURE,
        max_tokens=LLM_MAX_TOKENS,
        timeout=LLM_TIMEOUT_SECONDS,
        streaming=False,
        base_url=DASHSCOPE_BASE_URL,
        api_key=config.dashscope_api_key,
    )


def call_llm(prompt: str, llm: ChatOpenAI) -> tuple[str, bool, str]:
    """Invoke LLM with retry + timeout per design §10.

    Returns:
        (answer_text, success, error_msg). On success error_msg is "".
        On failure (after all retries) answer_text is "" and success=False.
    """
    last_err = ""
    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            response = llm.invoke(prompt)
            text = response.content if hasattr(response, "content") else str(response)
            if not isinstance(text, str):
                # langchain may return a list of content parts; coerce to string.
                text = json.dumps(text, ensure_ascii=False)
            return text, True, ""
        except Exception as exc:  # noqa: BLE001 - we record any error
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < LLM_MAX_RETRIES:
                time.sleep(2 ** attempt)  # 1s, 2s exponential backoff
    return "", False, last_err


def parse_citations(answer_text: str) -> set[str]:
    """Extract chunk_ids from LLM answer using `[chunk: <id>]` regex.

    Strict string equality with retrieval chunk_ids; no fuzzy match (per
    design §8.2: avoid normalizing away real drift).
    """
    return {match.strip() for match in CITATION_REGEX.findall(answer_text or "")}


def _assert_retrieval_invariants(
    sample: dict[str, Any],
    cells: dict[str, dict[str, Any]],
    pool_chunk_id_set: set[str],
    pool_signatures: dict[str, dict[str, Any]],
    top_k: int,
    top_chunks_per_doc: int,
) -> None:
    """§4 invariance under the P5.f3 3-cell matrix.

    Adapted from P5.f2 §4 (6 conditions) to the 3 cells we actually run:

    1. DL chunk_ids ⊆ pool chunk_ids (DL × chunk, DL × parent_chunk)
    2. NONE chunk_ids ⊆ pool chunk_ids (NONE × chunk)
    3. DL each result's identity fields byte-equal to the same chunk_id's
       hit in the pool (DL × chunk, DL × parent_chunk)
    4. DL len ≤ top_k * top_chunks_per_doc and per-doc count ≤ top_chunks_per_doc
       (DL × chunk, DL × parent_chunk)
    5. Same chunk_id appearing in ≥ 2 of the 3 cells has byte-equal identity
       fields (chunk_id / content / source_ref / citation_text). Proves
       granularity / strategy never mutate identity across cells.
    6. DOC_LEVEL × {chunk, parent_chunk} return identical ordered chunk_id
       lists (P4.5 ordered-list invariance reproduction across granularities,
       restricted to DOC_LEVEL since NONE only has chunk granularity here).
    """
    sid = sample["id"]
    sample_max = top_k * top_chunks_per_doc

    # §4(1) and §4(2)
    for cell_key, cell in cells.items():
        extra = set(cell["chunk_ids"]) - pool_chunk_id_set
        if extra:
            raise AssertionError(
                f"§4(1)/(2) violated on sample {sid} cell={cell_key}: "
                f"chunk_ids outside candidate pool: {extra}"
            )

    # §4(3): DL identity fields byte-equal to pool entry
    for cell_key, cell in cells.items():
        if cell["strategy"] != "doc_level":
            continue
        for chunk_id, sig in cell["_signatures"].items():
            ref = pool_signatures.get(chunk_id)
            if ref is None:
                raise AssertionError(
                    f"§4(3) violated on sample {sid} cell={cell_key}: "
                    f"chunk_id {chunk_id} missing from pool"
                )
            if sig != ref:
                raise AssertionError(
                    f"§4(3) violated on sample {sid} cell={cell_key}: "
                    f"chunk_id {chunk_id} identity mismatch with pool"
                )

    # §4(4): DL length and per-doc cap
    for cell_key, cell in cells.items():
        if cell["strategy"] != "doc_level":
            continue
        if len(cell["chunk_ids"]) > sample_max:
            raise AssertionError(
                f"§4(4a) violated on sample {sid} cell={cell_key}: "
                f"len={len(cell['chunk_ids'])} > {sample_max}"
            )
        per_doc = Counter(cell["doc_ids"])
        over = {d: c for d, c in per_doc.items() if c > top_chunks_per_doc}
        if over:
            raise AssertionError(
                f"§4(4b) violated on sample {sid} cell={cell_key}: {over}"
            )

    # §4(5): cross-cell identity stability for the same chunk_id.
    by_chunk_id: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for cell_key, cell in cells.items():
        for chunk_id, sig in cell["_signatures"].items():
            by_chunk_id.setdefault(chunk_id, []).append((cell_key, sig))
    for chunk_id, entries in by_chunk_id.items():
        if len(entries) < 2:
            continue
        ref_key, ref_sig = entries[0]
        for other_key, other_sig in entries[1:]:
            if other_sig != ref_sig:
                raise AssertionError(
                    f"§4(5) violated on sample {sid}: chunk_id {chunk_id} differs "
                    f"between cells {ref_key} and {other_key}; granularity / "
                    f"strategy must not mutate identity fields"
                )

    # §4(6): DL × {chunk, parent_chunk} return identical ordered chunk_id lists.
    dl_chunk_ids = cells.get("doc_level__chunk", {}).get("chunk_ids")
    dl_parent_ids = cells.get("doc_level__parent_chunk", {}).get("chunk_ids")
    if dl_chunk_ids is not None and dl_parent_ids is not None:
        if dl_chunk_ids != dl_parent_ids:
            raise AssertionError(
                f"§4(6) violated on sample {sid}: DL×chunk returned {dl_chunk_ids} "
                f"but DL×parent_chunk returned {dl_parent_ids} (P4.5 ordered-list "
                f"invariance across granularities)"
            )


def _build_cell_record(
    response,
    strategy: ResultAggregation,
    granularity: ContextGranularity,
    cell_key: str,
) -> dict[str, Any]:
    """Per-cell retrieval signatures + chunk identifiers for assertions."""
    results = list(response.results)
    return {
        "cell_key": cell_key,
        "strategy": strategy.value,
        "granularity": granularity.value,
        "chunk_ids": [r.chunk_id for r in results],
        "doc_ids": [r.doc_id for r in results],
        "_signatures": {r.chunk_id: _result_signature(r) for r in results},
        "context_text": response.context_text,
        "fallback_count": sum(
            1 for r in results
            if r.metadata.get("context_granularity_fallback")
        ),
        "fallback_rate": (
            sum(1 for r in results if r.metadata.get("context_granularity_fallback"))
            / max(len(results), 1)
        ),
    }


def evaluate_sample(
    sample: dict[str, Any],
    file_name_to_doc_id: dict[str, str],
    llm: ChatOpenAI,
    top_k: int,
    top_chunks_per_doc: int,
    oversample_factor: int,
) -> dict[str, Any]:
    """Per-sample: pool retrieve + 3-cell retrieve + assert §4 + 3 LLM calls.

    Returns a structured row containing per-cell retrieval/LLM outputs and
    per-sample / per-cell metrics. Failures of §4 raise immediately. LLM
    failures are recorded but do not raise here; aggregate_metrics decides
    whether the run-wide failure ratio crosses the abort threshold.
    """
    expected_doc_ids = [
        file_name_to_doc_id.get(f.replace(".pdf", ""), "")
        for f in sample.get("expected_doc_files", [])
    ]
    expected_doc_ids = [d for d in expected_doc_ids if d]

    # Pool query (NONE @ pool_k, chunk granularity) for §4(1)/(2)/(3).
    pool_k = max(top_k * oversample_factor, top_k)
    pool_query = RetrievalQuery(
        query=sample["query"],
        top_k=pool_k,
        retrieval_mode=RetrievalMode.DENSE_ONLY,
        knowledge_base_ids=["default"],
        result_aggregation=ResultAggregation.NONE,
        context_granularity=ContextGranularity.CHUNK,
    )
    pool_response = retrieval_service_module.retrieval_service.retrieve(pool_query)
    pool_results = pool_response.results
    pool_chunk_id_set = {r.chunk_id for r in pool_results}
    pool_signatures = {r.chunk_id: _result_signature(r) for r in pool_results}

    # 3-cell retrieval.
    cells: dict[str, dict[str, Any]] = {}
    for cell_key, strategy, granularity in CELL_DEFINITIONS:
        retrieval_query = RetrievalQuery(
            query=sample["query"],
            top_k=top_k,
            retrieval_mode=RetrievalMode.DENSE_ONLY,
            knowledge_base_ids=["default"],
            result_aggregation=strategy,
            top_chunks_per_doc=top_chunks_per_doc,
            doc_oversample_factor=oversample_factor,
            context_granularity=granularity,
        )
        response = retrieval_service_module.retrieval_service.retrieve(retrieval_query)
        cells[cell_key] = _build_cell_record(response, strategy, granularity, cell_key)

    # §4 invariance — strong assertion. Any failure raises immediately.
    _assert_retrieval_invariants(
        sample, cells, pool_chunk_id_set, pool_signatures,
        top_k, top_chunks_per_doc,
    )

    # LLM call per cell + citation drift metrics.
    for cell_key, _, _ in CELL_DEFINITIONS:
        cell = cells[cell_key]
        prompt = PROMPT_TEMPLATE.format(
            context_text=cell["context_text"],
            query=sample["query"],
        )
        llm_start = time.perf_counter()
        answer_text, success, error_msg = call_llm(prompt, llm)
        llm_latency_ms = int((time.perf_counter() - llm_start) * 1000)

        retrieval_chunk_id_set = set(cell["chunk_ids"])
        if success:
            llm_cited = parse_citations(answer_text)
            empty_answer = (not answer_text) or (
                "未找到相关信息" in answer_text and not llm_cited
            )
            no_citation = (not empty_answer) and (len(llm_cited) == 0)
            outside = llm_cited - retrieval_chunk_id_set
            inside = llm_cited & retrieval_chunk_id_set
            hallucinated = len(outside) > 0
            covered = len(inside) >= 1
            union = llm_cited | retrieval_chunk_id_set
            jaccard = (len(inside) / len(union)) if union else 0.0
        else:
            llm_cited = set()
            empty_answer = False
            no_citation = False
            outside = set()
            inside = set()
            hallucinated = False
            covered = False
            jaccard = 0.0

        cell["llm"] = {
            "success": success,
            "error_msg": error_msg,
            "answer_text": answer_text,
            "answer_chars": len(answer_text),
            "llm_latency_ms": llm_latency_ms,
            "cited_chunk_ids": sorted(llm_cited),
            "cited_outside_retrieval": sorted(outside),
            "cited_inside_retrieval": sorted(inside),
            "hallucinated": hallucinated,
            "covered": covered,
            "jaccard": jaccard,
            "empty_answer": empty_answer,
            "no_citation": no_citation,
        }
        # Drop _signatures from final per-cell payload — only used for assertions.
        cell.pop("_signatures", None)

    return {
        "id": sample["id"],
        "category": sample["category"],
        "query": sample["query"],
        "expected_doc_ids": expected_doc_ids,
        "pool": {
            "pool_k": pool_k,
            "size": len(pool_results),
            "distinct_doc_count": len({r.doc_id for r in pool_results}),
            "chunk_ids": sorted(pool_chunk_id_set),
        },
        "cells": cells,
    }


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-cell totals across all samples + per-category breakdown.

    All rates exclude llm_call_failed samples from the denominator (per
    design §10: failures don't pretend to be data). The failure ratio itself
    is reported separately so the abort condition can be evaluated.
    """
    summary: dict[str, Any] = {
        "total_samples": len(rows),
        "by_cell": {},
        "by_category": {},
    }
    cell_keys = [ck for ck, _, _ in CELL_DEFINITIONS]

    for cell_key in cell_keys:
        succeeded = [r["cells"][cell_key]["llm"] for r in rows if r["cells"][cell_key]["llm"]["success"]]
        all_calls = [r["cells"][cell_key]["llm"] for r in rows]
        n_succ = len(succeeded)
        n_total = len(all_calls)
        failure_rate = (n_total - n_succ) / n_total if n_total else 0.0

        if n_succ == 0:
            summary["by_cell"][cell_key] = {
                "n_total": n_total,
                "n_succeeded": 0,
                "llm_failure_rate": failure_rate,
                "hallucination_rate": None,
                "coverage_rate": None,
                "jaccard_avg": None,
                "empty_answer_rate": None,
                "no_citation_rate": None,
                "fallback_rate_avg": statistics.mean(
                    [r["cells"][cell_key]["fallback_rate"] for r in rows]
                ) if rows else 0.0,
            }
            continue

        hallucinated = sum(1 for c in succeeded if c["hallucinated"])
        covered = sum(1 for c in succeeded if c["covered"])
        empty = sum(1 for c in succeeded if c["empty_answer"])
        no_cite = sum(1 for c in succeeded if c["no_citation"])
        jaccard_avg = statistics.mean(c["jaccard"] for c in succeeded)
        fallback_rate = statistics.mean(
            r["cells"][cell_key]["fallback_rate"] for r in rows
        )

        summary["by_cell"][cell_key] = {
            "n_total": n_total,
            "n_succeeded": n_succ,
            "llm_failure_rate": failure_rate,
            "hallucination_rate": hallucinated / n_succ,
            "coverage_rate": covered / n_succ,
            "jaccard_avg": jaccard_avg,
            "empty_answer_rate": empty / n_succ,
            "no_citation_rate": no_cite / n_succ,
            "fallback_rate_avg": fallback_rate,
        }

    for category in CATEGORIES:
        cat_rows = [r for r in rows if r["category"] == category]
        if not cat_rows:
            summary["by_category"][category] = {"sample_count": 0}
            continue
        cat: dict[str, Any] = {"sample_count": len(cat_rows)}
        for cell_key in cell_keys:
            succeeded = [r["cells"][cell_key]["llm"] for r in cat_rows if r["cells"][cell_key]["llm"]["success"]]
            if not succeeded:
                cat[f"hallucination_rate_{cell_key}"] = None
                cat[f"coverage_rate_{cell_key}"] = None
                cat[f"jaccard_avg_{cell_key}"] = None
                continue
            cat[f"hallucination_rate_{cell_key}"] = (
                sum(1 for c in succeeded if c["hallucinated"]) / len(succeeded)
            )
            cat[f"coverage_rate_{cell_key}"] = (
                sum(1 for c in succeeded if c["covered"]) / len(succeeded)
            )
            cat[f"jaccard_avg_{cell_key}"] = statistics.mean(c["jaccard"] for c in succeeded)
        summary["by_category"][category] = cat

    return summary


def detect_corner_cases(summary: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per design §9.3: highlight samples / cells that warrant attention.

    These are NOT pass/fail; they only surface in the markdown report so
    nothing important hides in averages.
    """
    cells_low_coverage = [
        cell_key
        for cell_key, m in summary["by_cell"].items()
        if m.get("coverage_rate") is not None and m["coverage_rate"] < COVERAGE_HIGHLIGHT_THRESHOLD
    ]
    cells_high_empty = [
        cell_key
        for cell_key, m in summary["by_cell"].items()
        if m.get("empty_answer_rate") is not None and m["empty_answer_rate"] > EMPTY_ANSWER_HIGHLIGHT_THRESHOLD
    ]
    hallucinated_samples = []
    for row in rows:
        for cell_key, _, _ in CELL_DEFINITIONS:
            llm = row["cells"][cell_key]["llm"]
            if llm.get("success") and llm.get("hallucinated"):
                hallucinated_samples.append({
                    "id": row["id"],
                    "category": row["category"],
                    "cell": cell_key,
                    "cited_outside_retrieval": llm["cited_outside_retrieval"][:5],
                })
    return {
        "cells_with_coverage_below_threshold": cells_low_coverage,
        "cells_with_empty_answer_above_threshold": cells_high_empty,
        "hallucinated_samples": hallucinated_samples,
    }


def check_abort_condition(summary: dict[str, Any]) -> dict[str, Any]:
    """Per design §10/§12: abort if LLM failure ratio ≥ 50% in any cell."""
    failed_cells = []
    for cell_key, m in summary["by_cell"].items():
        if m["llm_failure_rate"] >= LLM_FAILURE_ABORT_THRESHOLD:
            failed_cells.append({
                "cell": cell_key,
                "llm_failure_rate": m["llm_failure_rate"],
                "n_total": m["n_total"],
                "n_succeeded": m["n_succeeded"],
            })
    return {
        "abort_threshold": LLM_FAILURE_ABORT_THRESHOLD,
        "failed_cells": failed_cells,
        "should_abort": len(failed_cells) > 0,
    }


def format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# P5.f3 LLM citation drift evaluation report")
    lines.append("")
    lines.append("## Proxy disclosure (per design §5.5 / §16, REQUIRED)")
    lines.append("")
    lines.append(
        "**The metrics below measure citation_id alignment between prompt and "
        "answer, NOT factual citation correctness.** A zero hallucination_rate "
        "does NOT prove the LLM cited the right chunk for the right fact; a "
        "positive hallucination_rate does NOT prove the LLM made up a wrong "
        "fact. Real factual citation correctness needs human or LLM-as-judge "
        "evaluation, which is OUT-OF-SCOPE in P5.f3."
    )
    lines.append("")
    lines.append("## Scope (per design §4 / §16, REQUIRED)")
    lines.append("")
    lines.append(
        "**`full_doc` granularity is OUT-OF-SCOPE on this long-doc corpus** and "
        "is NOT included in the evaluation matrix. P5.f2 caveat (a) already "
        "established that `DOC_LEVEL × full_doc` produces tokens_avg ≈ 46K on "
        "this corpus, exceeding the qwen-max 32K context window. Adding LLM "
        "calls does not lift this hard limit, so `full_doc` was not added back. "
        "Future LLM-side full_doc evaluation requires either a short-doc subset "
        "or upgraded context-window LLM, which would be a separate run "
        "(P5.f3.b), not this one."
    )
    lines.append("")
    lines.append(f"- generated_at: {report['generated_at']}")
    lines.append(f"- collection: `{report['collection']}`")
    lines.append(f"- llm_model: {report['llm_model']}")
    lines.append(f"- llm_temperature: {report['llm_temperature']}")
    lines.append(f"- llm_max_tokens: {report['llm_max_tokens']}")
    lines.append(f"- llm_timeout_seconds: {report['llm_timeout_seconds']}")
    lines.append(f"- sample_count: {report['summary']['total_samples']}")
    lines.append(f"- top_k: {report['top_k']}")
    lines.append(f"- top_chunks_per_doc: {report['top_chunks_per_doc']}")
    lines.append(f"- doc_oversample_factor: {report['doc_oversample_factor']}")
    lines.append(f"- retrieval_invariants_all_ok: {report['invariants_all_ok']}")
    lines.append(
        f"- llm_call_aborted: {report['abort_check']['should_abort']} "
        f"(threshold ≥ {LLM_FAILURE_ABORT_THRESHOLD})"
    )
    lines.append("")

    lines.append("## Corpus")
    for stem, doc_id in report["doc_ids"].items():
        lines.append(f"- {stem} -> {doc_id}")
    lines.append("")

    lines.append("## Per-cell metrics (soft observations, no pass/fail)")
    lines.append(
        "| cell | n_succeeded/n_total | llm_failure_rate | hallucination_rate | "
        "coverage_rate | jaccard_avg | empty_answer_rate | no_citation_rate | "
        "fallback_rate_avg |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for cell_key, _, _ in CELL_DEFINITIONS:
        m = report["summary"]["by_cell"][cell_key]

        def fmt(v):
            return f"{v:.3f}" if isinstance(v, (int, float)) and v is not None else "n/a"

        lines.append(
            f"| {cell_key} | {m['n_succeeded']}/{m['n_total']} | "
            f"{fmt(m['llm_failure_rate'])} | {fmt(m['hallucination_rate'])} | "
            f"{fmt(m['coverage_rate'])} | {fmt(m['jaccard_avg'])} | "
            f"{fmt(m['empty_answer_rate'])} | {fmt(m['no_citation_rate'])} | "
            f"{fmt(m['fallback_rate_avg'])} |"
        )
    lines.append("")

    lines.append("## Per-category × cell (soft observations)")
    for category in CATEGORIES:
        cat = report["summary"]["by_category"].get(category, {})
        if not cat or cat.get("sample_count", 0) == 0:
            continue
        lines.append(f"### {category} (n={cat['sample_count']})")
        lines.append("| cell | hallucination_rate | coverage_rate | jaccard_avg |")
        lines.append("|---|---|---|---|")
        for cell_key, _, _ in CELL_DEFINITIONS:
            def fmt(v):
                return f"{v:.3f}" if isinstance(v, (int, float)) and v is not None else "n/a"

            lines.append(
                f"| {cell_key} | "
                f"{fmt(cat.get(f'hallucination_rate_{cell_key}'))} | "
                f"{fmt(cat.get(f'coverage_rate_{cell_key}'))} | "
                f"{fmt(cat.get(f'jaccard_avg_{cell_key}'))} |"
            )
        lines.append("")

    lines.append("## Corner cases (per design §9.3)")
    cc = report["corner_cases"]
    lines.append(
        f"- cells with coverage_rate < {COVERAGE_HIGHLIGHT_THRESHOLD}: "
        f"{cc['cells_with_coverage_below_threshold'] or 'none'}"
    )
    lines.append(
        f"- cells with empty_answer_rate > {EMPTY_ANSWER_HIGHLIGHT_THRESHOLD}: "
        f"{cc['cells_with_empty_answer_above_threshold'] or 'none'}"
    )
    if cc["hallucinated_samples"]:
        lines.append(f"- hallucinated samples (n={len(cc['hallucinated_samples'])}):")
        for entry in cc["hallucinated_samples"][:30]:  # cap output
            outside = entry["cited_outside_retrieval"]
            lines.append(
                f"  - {entry['id']} [{entry['category']}] cell={entry['cell']} "
                f"outside_retrieval={outside}"
            )
        if len(cc["hallucinated_samples"]) > 30:
            lines.append(
                f"  - ... ({len(cc['hallucinated_samples']) - 30} more in JSON report)"
            )
    else:
        lines.append("- hallucinated samples: none")
    lines.append("")

    lines.append("## Abort check")
    abort = report["abort_check"]
    lines.append(f"- abort_threshold (llm_failure_rate per cell): {abort['abort_threshold']}")
    if abort["failed_cells"]:
        lines.append("- cells exceeding threshold:")
        for entry in abort["failed_cells"]:
            lines.append(
                f"  - {entry['cell']}: failure_rate={entry['llm_failure_rate']:.3f} "
                f"({entry['n_total'] - entry['n_succeeded']}/{entry['n_total']})"
            )
    else:
        lines.append("- no cell exceeded the abort threshold")
    lines.append(f"- should_abort: **{abort['should_abort']}**")
    lines.append("")

    lines.append("## Per-sample compact (top-3 cells)")
    lines.append(
        "| id | category | NONE×chunk hall/cov/jac | DL×chunk hall/cov/jac | "
        "DL×parent hall/cov/jac |"
    )
    lines.append("|---|---|---|---|---|")
    for row in report["rows"]:
        def cell_str(cell_key):
            llm = row["cells"][cell_key]["llm"]
            if not llm["success"]:
                return "FAILED"
            return (
                f"{int(llm['hallucinated'])}/{int(llm['covered'])}/"
                f"{llm['jaccard']:.2f}"
            )

        lines.append(
            f"| {row['id']} | {row['category']} | "
            f"{cell_str('none__chunk')} | {cell_str('doc_level__chunk')} | "
            f"{cell_str('doc_level__parent_chunk')} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def run() -> dict[str, Any]:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    samples = load_samples(SAMPLES_PATH)
    llm = _build_llm()

    o_coll = milvus_client_module.MilvusClientManager.COLLECTION_NAME
    o_vname = vector_store_manager.collection_name
    o_vstore = vector_store_manager.vector_store
    o_idx_store = vector_index_module.knowledge_metadata_store
    o_ing_store = ingestion_module.knowledge_metadata_store
    o_ret_store = retrieval_service_module.knowledge_metadata_store
    o_rerank = rerank_service.enabled

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        temp_store = setup_isolated(tmp_root)
        try:
            index_service = vector_index_module.VectorIndexService()
            stem_to_doc_id = index_corpus(tmp_root, index_service, temp_store)
            file_name_to_doc_id = {stem: did for stem, did in stem_to_doc_id.items()}

            rows = [
                evaluate_sample(
                    s, file_name_to_doc_id, llm,
                    DEFAULT_TOP_K, DEFAULT_TOP_CHUNKS_PER_DOC, DEFAULT_OVERSAMPLE,
                )
                for s in samples
            ]
            invariants_all_ok = True  # any failed assertion would have raised
            summary = aggregate_metrics(rows)
            corner_cases = detect_corner_cases(summary, rows)
            abort_check = check_abort_condition(summary)

            report = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "collection": EVAL_COLLECTION,
                "llm_model": config.rag_model,
                "llm_temperature": LLM_TEMPERATURE,
                "llm_max_tokens": LLM_MAX_TOKENS,
                "llm_timeout_seconds": LLM_TIMEOUT_SECONDS,
                "llm_max_retries": LLM_MAX_RETRIES,
                "top_k": DEFAULT_TOP_K,
                "top_chunks_per_doc": DEFAULT_TOP_CHUNKS_PER_DOC,
                "doc_oversample_factor": DEFAULT_OVERSAMPLE,
                "doc_ids": stem_to_doc_id,
                "summary": summary,
                "corner_cases": corner_cases,
                "abort_check": abort_check,
                "invariants_all_ok": invariants_all_ok,
                "rows": rows,
            }
            report_json = REPORT_DIR / f"p5_llm_eval_{RUN_ID}.json"
            report_md = REPORT_DIR / f"p5_llm_eval_{RUN_ID}.md"
            write_json(report_json, report)
            report_md.write_text(format_markdown(report), encoding="utf-8")

            if abort_check["should_abort"]:
                # Per design §10/§12: do NOT silently complete a run with
                # ≥50% LLM-call failures.
                raise AssertionError(
                    f"P5.f3 abort condition triggered: "
                    f"{abort_check['failed_cells']}. Report still written for "
                    f"forensic review at {report_json}"
                )

            output = {
                "samples": str(SAMPLES_PATH),
                "report_json": str(report_json),
                "report_md": str(report_md),
                "invariants_all_ok": invariants_all_ok,
                "abort_should_trigger": abort_check["should_abort"],
                "by_cell": summary["by_cell"],
                "corner_cases": corner_cases,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
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
                if utility.has_collection(EVAL_COLLECTION):
                    utility.drop_collection(EVAL_COLLECTION)
            except Exception:
                pass
            vector_store_manager.vector_store = o_vstore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run P5.f3 LLM citation drift evaluation.")
    return p.parse_args()


def main() -> int:
    parse_args()
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
