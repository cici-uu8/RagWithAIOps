import json
import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.run_openjudge_answer_shadow_eval import (
    build_openjudge_answer_shadow_report,
    write_openjudge_answer_shadow_report,
)


class OpenJudgeAnswerShadowEvalTests(unittest.TestCase):
    def test_build_report_keeps_openjudge_scores_shadow_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "baseline.json"
            evalset_path = root / "answer_evalset.jsonl"
            _write_baseline(baseline_path)
            _write_evalset(evalset_path)

            report = build_openjudge_answer_shadow_report(
                baseline_report_path=baseline_path,
                evalset_path=evalset_path,
                openjudge_results_provider=_fake_openjudge_results_provider,
            )

        self.assertEqual(report["report_name"], "openjudge_answer_shadow_eval")
        self.assertEqual(report["scope"]["layer"], "answer")
        self.assertTrue(report["scope"]["shadow_only"])
        self.assertFalse(report["scope"]["changes_main_gate"])
        self.assertFalse(report["scope"]["writes_back_to_baseline"])
        self.assertEqual(report["summary"]["total"], 3)
        self.assertEqual(report["summary"]["deterministic_status_counts"], {"failed": 2, "passed": 1})
        self.assertEqual(report["summary"]["openjudge_status_counts"]["correctness"], {"scored": 3})
        self.assertEqual(report["results"][0]["deterministic"]["status"], "failed")
        self.assertEqual(report["results"][0]["openjudge_shadow"]["correctness"]["score"], 2.0)
        self.assertEqual(report["results"][2]["deterministic"]["status"], "passed")
        self.assertEqual(report["results"][2]["openjudge_shadow"]["correctness"]["score"], 5.0)
        self.assertIn("answer_missing_facts", report["correlation_analysis"]["metrics"])
        self.assertIn("unsupported_claim_count", report["correlation_analysis"]["metrics"])
        self.assertIn("context_missing_facts", report["correlation_analysis"]["metrics"])
        self.assertLess(
            report["correlation_analysis"]["metrics"]["answer_missing_facts"]["correctness"],
            0,
        )

    def test_build_report_marks_context_dependent_scores_low_confidence_when_context_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "baseline.json"
            evalset_path = root / "answer_evalset.jsonl"
            _write_baseline(baseline_path, include_context=False)
            _write_evalset(evalset_path)

            report = build_openjudge_answer_shadow_report(
                baseline_report_path=baseline_path,
                evalset_path=evalset_path,
                openjudge_results_provider=_fake_openjudge_results_provider,
            )

        self.assertEqual(report["summary"]["context_text_available_count"], 0)
        self.assertIn("context_text_missing", report["results"][0]["input_warnings"])
        self.assertEqual(report["results"][0]["openjudge_shadow"]["hallucination"]["confidence"], "low")

    def test_write_report_writes_json_and_markdown_without_changing_gate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            baseline_path = root / "baseline.json"
            evalset_path = root / "answer_evalset.jsonl"
            output_json = root / "shadow.json"
            _write_baseline(baseline_path)
            _write_evalset(evalset_path)

            report = write_openjudge_answer_shadow_report(
                output_json=output_json,
                baseline_report_path=baseline_path,
                evalset_path=evalset_path,
                openjudge_results_provider=_fake_openjudge_results_provider,
            )

            written = json.loads(output_json.read_text(encoding="utf-8"))
            markdown = output_json.with_suffix(".md").read_text(encoding="utf-8")
            output_exists = output_json.exists()

        self.assertEqual(report["report_json_path"], output_json.as_posix())
        self.assertTrue(output_exists)
        self.assertEqual(written["scope"]["shadow_only"], True)
        self.assertIn("OpenJudge Answer Shadow Eval", markdown)
        self.assertIn("Shadow scores do not affect pass/fail", markdown)


def _fake_openjudge_results_provider(cases):
    scores = {
        "S1": {
            "relevance": 4.0,
            "hallucination": 2.0,
            "correctness": 2.0,
            "instruction_following": 3.0,
        },
        "S2": {
            "relevance": 3.0,
            "hallucination": 3.0,
            "correctness": 3.0,
            "instruction_following": 3.0,
        },
        "S3": {
            "relevance": 5.0,
            "hallucination": 5.0,
            "correctness": 5.0,
            "instruction_following": 5.0,
        },
    }
    return {
        grader: [
            {
                "name": grader,
                "score": scores[case["sample_id"]][grader],
                "reason": f"{grader} reason for {case['sample_id']}",
            }
            for case in cases
        ]
        for grader in ("relevance", "hallucination", "correctness", "instruction_following")
    }


def _write_baseline(path: Path, *, include_context: bool = True) -> None:
    rows = [
        _baseline_row(
            "S1",
            status="failed",
            failure_category="answer_missing_facts",
            answer_missing=2,
            context_missing=0,
            unsupported=1,
            include_context=include_context,
        ),
        _baseline_row(
            "S2",
            status="failed",
            failure_category="context_missing_facts",
            answer_missing=0,
            context_missing=2,
            unsupported=0,
            include_context=include_context,
        ),
        _baseline_row(
            "S3",
            status="passed",
            failure_category="passed",
            answer_missing=0,
            context_missing=0,
            unsupported=0,
            include_context=include_context,
        ),
    ]
    path.write_text(
        json.dumps(
            {
                "report_name": "department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611",
                "summary": {"total": len(rows), "passed": 1, "failed": 2},
                "results": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _baseline_row(
    sample_id: str,
    *,
    status: str,
    failure_category: str,
    answer_missing: int,
    context_missing: int,
    unsupported: int,
    include_context: bool,
) -> dict:
    row = {
        "sample_id": sample_id,
        "query": f"{sample_id} query",
        "status": status,
        "failure_category": failure_category,
        "answer_text": f"{sample_id} answer",
        "gate": {
            "hard_gate_passed": status == "passed",
            "answer_missing_fact_count": answer_missing,
            "context_missing_fact_count": context_missing,
            "unsupported_claim_count": unsupported,
            "citation_required_but_missing": 0,
            "permission_leak_count": 0,
            "source_ref_unresolvable_count": 0,
        },
        "retrieval": {
            "status": "passed",
            "failure_category": "passed",
            "expected_doc_hit": True,
            "source_ref_integrity": {
                "citation_unresolvable_count": 0,
                "cross_scope_error_count": 0,
            },
        },
    }
    if include_context:
        row["context_text"] = f"{sample_id} retrieved context"
    else:
        row["context_text_chars"] = 42
    return row


def _write_evalset(path: Path) -> None:
    rows = [
        _evalset_row("S1", "S1 reference"),
        _evalset_row("S2", "S2 reference"),
        _evalset_row("S3", "S3 reference"),
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _evalset_row(sample_id: str, reference_answer: str) -> dict:
    return {
        "sample_id": sample_id,
        "layer": "answer",
        "query": f"{sample_id} query",
        "allowed_kb_ids": ["process_digital_dept"],
        "expected_doc_ids": [f"doc-{sample_id}"],
        "scope": "scoped",
        "reference_answer": reference_answer,
        "must_include_facts": ["required fact"],
        "must_not_include_claims": [],
        "required_citations": [],
        "context_policy": "retrieved_context_only",
    }


if __name__ == "__main__":
    unittest.main()
