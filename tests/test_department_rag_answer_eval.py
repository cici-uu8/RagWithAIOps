import json
import tempfile
import unittest
from pathlib import Path

from app.models import ParserEngine, RetrievalResponse, RetrievalResult, SourceRef
from evals.knowledge_base.answer_eval_helpers import (
    check_answer_hard_gates,
    contains_required_text,
)
from evals.knowledge_base.run_department_rag_answer_eval import (
    GenerationResult,
    load_answer_evalset,
    run_department_rag_answer_eval,
)


class DepartmentRagAnswerEvalTests(unittest.TestCase):
    def test_contains_required_text_ignores_spacing_and_punctuation(self):
        self.assertTrue(contains_required_text("查询最近 30 分钟的 system-metrics 日志", "最近30分钟"))
        self.assertTrue(contains_required_text("引用 [source: cpu_high_usage.md]", "cpu_high_usage.md"))
        self.assertFalse(contains_required_text("只提到了内存排查", "CPU 排查"))

    def test_contains_required_text_accepts_explicit_fact_aliases(self):
        self.assertTrue(contains_required_text("Pod 已经处于非就绪状态超过15分钟", "non-ready state||非就绪状态"))
        self.assertTrue(contains_required_text("Pod has been in a non-ready state", "non-ready state||非就绪状态"))
        self.assertFalse(contains_required_text("Pod 已经正常运行", "non-ready state||非就绪状态"))

    def test_check_answer_hard_gates_classifies_answer_missing_facts(self):
        sample = _sample()
        context_text = "排查时需要 查询最近30分钟系统指标日志，并关注 cpu_usage > 80。"
        answer_text = "应关注 cpu_usage > 80。[source: cpu_high_usage.md]"

        gate = check_answer_hard_gates(
            sample=sample,
            answer_text=answer_text,
            context_text=context_text,
            retrieval_row=_retrieval_row(status="passed"),
        )

        self.assertFalse(gate["hard_gate_passed"])
        self.assertEqual(gate["failure_category"], "answer_missing_facts")
        self.assertEqual(gate["missing_required_fact_count"], 1)
        self.assertEqual(gate["context_missing_fact_count"], 0)

    def test_check_answer_hard_gates_classifies_context_missing_facts(self):
        sample = _sample()
        context_text = "这里只提到了 cpu_usage > 80。"
        answer_text = "应关注 cpu_usage > 80。[source: cpu_high_usage.md]"

        gate = check_answer_hard_gates(
            sample=sample,
            answer_text=answer_text,
            context_text=context_text,
            retrieval_row=_retrieval_row(status="passed"),
        )

        self.assertFalse(gate["hard_gate_passed"])
        self.assertEqual(gate["failure_category"], "context_missing_facts")
        self.assertEqual(gate["context_missing_fact_count"], 1)

    def test_check_answer_hard_gates_catches_missing_citation_and_forbidden_marker(self):
        sample = _sample()
        sample["must_not_include_claims"] = ["文档未提及的 CPU 阈值如 85% 或 95%"]
        context_text = "查询最近30分钟系统指标日志，并关注 cpu_usage > 80。"
        answer_text = "查询最近30分钟系统指标日志，并建议 95% 才处理。"

        gate = check_answer_hard_gates(
            sample=sample,
            answer_text=answer_text,
            context_text=context_text,
            retrieval_row=_retrieval_row(status="passed"),
        )

        self.assertEqual(gate["failure_category"], "answer_fabrication")
        self.assertEqual(gate["citation_required_but_missing"], 1)
        self.assertEqual(gate["unsupported_claim_count"], 1)

    def test_unsupported_claim_check_does_not_fuzzy_match_omission_phrase(self):
        sample = _sample()
        sample["must_include_facts"] = ["隔离许可", "LOTO"]
        sample["must_not_include_claims"] = ["省略隔离许可和 LOTO 安全要求"]
        context_text = "处理前必须完成隔离许可，并按 LOTO 安全要求切断能量。"
        answer_text = "处理前必须完成隔离许可，并按 LOTO 安全要求切断能量。[source: cpu_high_usage.md]"

        gate = check_answer_hard_gates(
            sample=sample,
            answer_text=answer_text,
            context_text=context_text,
            retrieval_row=_retrieval_row(status="passed"),
        )

        self.assertTrue(gate["hard_gate_passed"])
        self.assertEqual(gate["unsupported_claim_count"], 0)

    def test_load_answer_evalset_requires_answer_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "answer.jsonl"
            path.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")
            cases = load_answer_evalset(path)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["sample_id"], "S5P1-X")

    def test_runner_reports_answer_baseline_with_injected_generator(self):
        class StaticRetrievalService:
            def retrieve(self, query):
                result = _retrieval_result()
                return RetrievalResponse(
                    query=query,
                    results=[result],
                    context_text="【参考资料 1】\n来源: cpu_high_usage.md\n内容:\n查询最近30分钟系统指标日志，并关注 cpu_usage > 80。",
                )

        class StaticGenerator:
            generator_kind = "static_test_generator"
            model_name = "static"

            def generate(self, *, query, context_text, sample):
                return GenerationResult(
                    answer_text=(
                        "应查询最近30分钟系统指标日志，并关注 cpu_usage > 80。"
                        "[source: cpu_high_usage.md]"
                    ),
                    success=True,
                    error_type="",
                    error_message="",
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            evalset = Path(tmpdir) / "answer.jsonl"
            evalset.write_text(json.dumps(_sample(), ensure_ascii=False) + "\n", encoding="utf-8")
            report = run_department_rag_answer_eval(
                evalset,
                output_dir=tmpdir,
                write_report=True,
                retrieval_service=StaticRetrievalService(),
                metadata_store=None,
                answer_generator=StaticGenerator(),
            )

        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["summary"]["status_counts"], {"passed": 1})
        self.assertTrue(report["summary"]["hard_gate_passed"])
        self.assertEqual(report["results"][0]["failure_category"], "passed")


def _sample() -> dict:
    return {
        "sample_id": "S5P1-X",
        "layer": "answer",
        "query": "CPU 使用率高怎么排查",
        "allowed_kb_ids": ["process_digital_dept"],
        "expected_doc_ids": ["doc-cpu"],
        "scope": "scoped",
        "retrieval_mode": "dense_only",
        "top_k": 3,
        "reference_answer": "应查询最近30分钟系统指标日志，并关注 cpu_usage > 80。",
        "must_include_facts": ["查询最近30分钟系统指标日志"],
        "must_not_include_claims": ["未在文档中出现的第三方 APM 工具名"],
        "required_citations": [
            {
                "doc_id": "doc-cpu",
                "source_file": "cpu_high_usage.md",
                "expected_in_answer": "cpu_high_usage.md",
            }
        ],
        "answer_risk_type": "low",
        "context_policy": "retrieved_context_only",
        "judge_policy": "deterministic_only",
    }


def _retrieval_row(status: str) -> dict:
    return {
        "status": status,
        "failure_category": "passed" if status == "passed" else "no_retrieval_hit",
        "source_ref_integrity": {
            "all_resolvable": True,
            "citation_unresolvable_count": 0,
            "cross_scope_error_count": 0,
        },
    }


def _retrieval_result() -> RetrievalResult:
    source_ref = SourceRef(
        kb_id="process_digital_dept",
        doc_id="doc-cpu",
        chunk_id="chunk-cpu-1",
        source_file="cpu_high_usage.md",
        heading_path=["排查步骤"],
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RetrievalResult(
        kb_id="process_digital_dept",
        doc_id="doc-cpu",
        chunk_id="chunk-cpu-1",
        content="查询最近30分钟系统指标日志，并关注 cpu_usage > 80。",
        score=0.1,
        source_ref=source_ref,
        citation_text="[来源: cpu_high_usage.md, 章节: 排查步骤, chunk: chunk-cpu-1]",
        metadata={},
    )


if __name__ == "__main__":
    unittest.main()
