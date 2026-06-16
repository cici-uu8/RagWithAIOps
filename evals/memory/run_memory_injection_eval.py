"""Deterministic injection-layer eval for reviewed oncall memory guidance."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.models.memory_mode import MemoryMode
from app.services.memory_guidance_provider import MemoryGuidanceProvider
from app.services.memory_trace_service import MemoryTraceService
from evals.memory.run_memory_retrieval_eval import SAMPLES_PATH, build_memory_record, load_samples
from app.services.memory_store import MemoryStore


def summarize_injection_results(results: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "checks_total": len(results),
        "checks_passed": sum(1 for result in results if result["passed"]),
    }


def _seed_first_memory(store_path: Path) -> str:
    sample = load_samples(SAMPLES_PATH)[0]
    store = MemoryStore(store_path=store_path)
    record = build_memory_record(sample, source="memory_injection_eval_fixture")
    store.upsert(record)
    return record.memory_id


def _provider(trace_dir: Path) -> MemoryGuidanceProvider:
    return MemoryGuidanceProvider(trace_service=MemoryTraceService(trace_dir=str(trace_dir)))


def run_eval() -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store_path = root / "memory.sqlite3"
        expected_memory_id = _seed_first_memory(store_path)
        provider = _provider(root / "traces")

        off_result = provider.build(
            {
                "input": "service-a CPUHigh alert triggered again",
                "memory_mode": "off",
                "memory_store_path": str(store_path),
            }
        )
        results.append(
            {
                "case_id": "off_matching_memory",
                "mode": off_result.mode.value,
                "guidance_text_present": bool(off_result.guidance_text),
                "observation_present": off_result.observation is not None,
                "passed": (
                    off_result.mode == MemoryMode.OFF
                    and off_result.guidance_text == ""
                    and off_result.observation is None
                ),
            }
        )

        shadow_result = provider.build(
            {
                "input": "service-a CPUHigh alert triggered again",
                "memory_mode": "shadow",
                "memory_owner_id": "default",
                "memory_store_path": str(store_path),
            }
        )
        results.append(
            {
                "case_id": "shadow_matching_memory",
                "mode": shadow_result.mode.value,
                "guidance_text_present": bool(shadow_result.guidance_text),
                "observation_present": shadow_result.observation is not None,
                "memory_ids": (shadow_result.observation or {}).get("memory_ids", []),
                "passed": (
                    shadow_result.mode == MemoryMode.SHADOW
                    and shadow_result.guidance_text == ""
                    and (shadow_result.observation or {}).get("memory_ids") == [expected_memory_id]
                ),
            }
        )

        active_result = provider.build(
            {
                "input": "service-a CPUHigh alert triggered again",
                "memory_mode": "active",
                "memory_owner_id": "default",
                "memory_store_path": str(store_path),
            }
        )
        results.append(
            {
                "case_id": "active_matching_memory",
                "mode": active_result.mode.value,
                "guidance_text_present": bool(active_result.guidance_text),
                "observation_present": active_result.observation is not None,
                "memory_ids": (active_result.observation or {}).get("memory_ids", []),
                "passed": (
                    active_result.mode == MemoryMode.ACTIVE
                    and bool(active_result.guidance_text)
                    and (active_result.observation or {}).get("memory_ids") == [expected_memory_id]
                ),
            }
        )

        active_no_match = provider.build(
            {
                "input": "KafkaLag partition backlog consumer group",
                "memory_mode": "active",
                "memory_owner_id": "default",
                "memory_store_path": str(store_path),
            }
        )
        results.append(
            {
                "case_id": "active_no_matching_memory",
                "mode": active_no_match.mode.value,
                "guidance_text_present": bool(active_no_match.guidance_text),
                "observation_present": active_no_match.observation is not None,
                "passed": (
                    active_no_match.mode == MemoryMode.ACTIVE
                    and active_no_match.guidance_text == ""
                    and active_no_match.observation is None
                ),
            }
        )

        custom_store_result = _provider(root / "custom_traces").build(
            {
                "input": "service-a CPUHigh alert triggered again",
                "memory_mode": "active",
                "memory_owner_id": "default",
                "memory_store_path": str(store_path),
            }
        )
        results.append(
            {
                "case_id": "custom_memory_store_path",
                "mode": custom_store_result.mode.value,
                "guidance_text_present": bool(custom_store_result.guidance_text),
                "observation_present": custom_store_result.observation is not None,
                "memory_ids": (custom_store_result.observation or {}).get("memory_ids", []),
                "passed": (custom_store_result.observation or {}).get("memory_ids") == [expected_memory_id],
            }
        )

    metrics = summarize_injection_results(results)
    return {
        "eval_name": "memory_injection_eval",
        "eval_status": "valid" if metrics["checks_passed"] == metrics["checks_total"] else "failed",
        "metrics": metrics,
        "results": results,
    }


def save_report(report: Dict[str, Any]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(__file__).parent / f"memory_injection_eval_{timestamp}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    report = run_eval()
    output_path = save_report(report)
    metrics = report["metrics"]
    print(f"memory_injection_eval report: {output_path}")
    print(f"metrics: checks_passed={metrics['checks_passed']}/{metrics['checks_total']}")
    return 0 if report["eval_status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
