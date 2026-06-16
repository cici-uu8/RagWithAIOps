"""Deterministic retrieval-layer eval for reviewed oncall memory."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.models.memory import AlertPatternPayload, MemoryRecord, PlanTemplatePayload
from app.services.memory_retrieval_service import MemoryRetrievalQuery, MemoryRetrievalService
from app.services.memory_store import MemoryStore


SAMPLES_PATH = Path(__file__).parent / "p6_samples.jsonl"
ONCALL_NAMESPACES = [
    "memory://oncall/alert-patterns",
    "memory://oncall/plan-templates",
]
ONCALL_MEMORY_TYPES = ["alert_pattern", "plan_template"]


def load_samples(samples_path: Path = SAMPLES_PATH) -> List[Dict[str, Any]]:
    with samples_path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_memory_record(sample: Dict[str, Any], source: str = "memory_retrieval_eval_fixture") -> MemoryRecord:
    mem = sample["pre_seeded_memory"]
    if mem["memory_type"] == "alert_pattern":
        payload = AlertPatternPayload(**mem["payload"])
    elif mem["memory_type"] == "plan_template":
        payload = PlanTemplatePayload(**mem["payload"])
    else:
        raise ValueError(f"Unknown memory_type: {mem['memory_type']}")

    return MemoryRecord(
        memory_id=mem["memory_id"],
        schema_version=1,
        owner_id="default",
        namespace=mem["namespace"],
        memory_type=mem["memory_type"],
        content=mem["content"],
        summary=mem["content"][:200],
        payload=payload,
        status="active",
        source=source,
        evidence={"source": source, "sample_id": sample.get("id")},
        tags=["memory_layer_eval"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def compute_ranking_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(results)
    if total == 0:
        return {"total": 0, "hit_at_1": 0.0, "hit_at_3": 0.0, "mrr": 0.0}

    hit_at_1 = 0
    hit_at_3 = 0
    reciprocal_rank_sum = 0.0
    for result in results:
        expected = result["expected_memory_id"]
        returned = result["returned_memory_ids"]
        if returned[:1] == [expected]:
            hit_at_1 += 1
        if expected in returned[:3]:
            hit_at_3 += 1
        if expected in returned:
            reciprocal_rank_sum += 1.0 / (returned.index(expected) + 1)

    return {
        "total": total,
        "hit_at_1": hit_at_1 / total,
        "hit_at_3": hit_at_3 / total,
        "mrr": reciprocal_rank_sum / total,
    }


def run_eval(samples_path: Path = SAMPLES_PATH) -> Dict[str, Any]:
    samples = load_samples(samples_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(Path(tmpdir) / "memory.sqlite3")
        for sample in samples:
            store.upsert(build_memory_record(sample))

        retrieval_service = MemoryRetrievalService(store=store)
        results = []
        latencies = []
        for sample in samples:
            expected_memory_id = sample["pre_seeded_memory"]["memory_id"]
            start = time.perf_counter()
            response = retrieval_service.retrieve(
                MemoryRetrievalQuery(
                    query=sample["query"],
                    owner_id="default",
                    namespaces=ONCALL_NAMESPACES,
                    memory_types=ONCALL_MEMORY_TYPES,
                    top_k=3,
                )
            )
            latency_ms = (time.perf_counter() - start) * 1000
            latencies.append(latency_ms)
            returned_memory_ids = [memory.memory_id for memory in response.memory_results]
            matched_terms = [
                term
                for memory in response.memory_results
                for term in memory.matched_terms
            ]
            results.append(
                {
                    "sample_id": sample["id"],
                    "category": sample["category"],
                    "query": sample["query"],
                    "expected_memory_id": expected_memory_id,
                    "returned_memory_ids": returned_memory_ids,
                    "matched_terms": matched_terms,
                    "latency_ms": round(latency_ms, 3),
                    "passed_hit_at_3": expected_memory_id in returned_memory_ids[:3],
                }
            )

    metrics = compute_ranking_metrics(results)
    metrics["latency_ms_avg"] = round(sum(latencies) / len(latencies), 3) if latencies else 0.0
    return {
        "eval_name": "memory_retrieval_eval",
        "eval_status": "valid",
        "metrics": metrics,
        "results": results,
    }


def save_report(report: Dict[str, Any]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(__file__).parent / f"memory_retrieval_eval_{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    report = run_eval()
    output_path = save_report(report)
    metrics = report["metrics"]
    print(f"memory_retrieval_eval report: {output_path}")
    print(
        "metrics: "
        f"total={metrics['total']} "
        f"hit_at_1={metrics['hit_at_1']:.3f} "
        f"hit_at_3={metrics['hit_at_3']:.3f} "
        f"mrr={metrics['mrr']:.3f} "
        f"latency_ms_avg={metrics['latency_ms_avg']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
