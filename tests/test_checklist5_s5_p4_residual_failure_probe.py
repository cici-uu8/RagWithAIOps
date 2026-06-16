import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.models import (
    ParserEngine,
    ResultAggregation,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    SourceRef,
)
from evals.knowledge_base.run_department_rag_answer_eval import GenerationResult


class Checklist5S5P4ResidualFailureProbeTests(unittest.TestCase):
    def test_build_report_runs_four_observation_probe_tracks(self):
        from evals.knowledge_base.checklist5_s5_p4_residual_failure_probe import (
            build_s5_p4_residual_failure_probe_report,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            evalset = root / "answer.jsonl"
            baseline = root / "baseline.json"
            artifact_dir = root / "scoutflo_artifacts"
            artifact_dir.mkdir()
            _write_evalset(evalset)
            _write_baseline(baseline)
            _write_scoutflo_chunks(artifact_dir)

            report = build_s5_p4_residual_failure_probe_report(
                evalset_path=evalset,
                baseline_report_path=baseline,
                retrieval_service=FakeRetrievalService(),
                metadata_store=FakeMetadataStore(artifact_dir),
                generator_factory=FakeGeneratorFactory(),
                variance_runs=5,
            )

        self.assertEqual(report["probe_name"], "checklist5_s5_p4_residual_failure_probe")
        self.assertEqual(report["status"], "observation_only")
        self.assertEqual(report["summary"]["sample_count"], 7)
        self.assertEqual(report["summary"]["prompt_policy_probe"]["enhanced_passed_count"], 2)
        self.assertTrue(report["summary"]["top_k_context_probe"]["top_k_5_passed"])
        self.assertTrue(report["summary"]["top_k_context_probe"]["doc_level_passed"])
        self.assertEqual(
            report["summary"]["pdf_chunk_source_support_probe"]["chunk_indexed_but_ranked_low_count"],
            2,
        )
        self.assertEqual(report["summary"]["generation_variance_probe"]["stable_fail_count"], 1)
        self.assertEqual(report["summary"]["generation_variance_probe"]["unstable_count"], 1)
        self.assertFalse(report["decisions"]["eligible_for_answer_50q"])
        self.assertFalse(report["scope"]["changes_answer_prompt"])
        self.assertFalse(report["scope"]["changes_default_retrieval_mode"])
        self.assertFalse(report["scope"]["changes_rerank_enabled"])
        self.assertFalse(report["scope"]["uses_ragas"])


class FakeRetrievalService:
    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        sample_id = str(query.query).split("::", 1)[0]
        doc_id = EXPECTED_DOCS.get(sample_id, "doc-other")
        source_file = SOURCE_FILES.get(sample_id, "source.md")

        if sample_id == "S5P1-MD-002":
            if query.result_aggregation == ResultAggregation.DOC_LEVEL:
                content = "先确认故障并记录故障时间。查询最近15分钟 application-logs，关注 ERROR、FATAL 或 status:500，检查 restart/crash/oom_kill 和依赖服务状态。"
            elif query.top_k >= 5:
                content = "先确认故障并记录故障时间。查询最近15分钟 application-logs，关注 ERROR、FATAL 或 status:500，检查 restart/crash/oom_kill 和依赖服务状态。"
            else:
                content = "先确认故障并记录故障时间。"
            return _response(query, sample_id, doc_id, source_file, content)

        if sample_id in {"S5P1-PDF-004", "S5P1-PDF-009"}:
            if query.top_k >= 10:
                content = (
                    "AWS Kubernetes Sentry 414 Folder Structure Control-Plane Pods"
                )
                chunk_id = "doc-scoutflo:c00004" if sample_id == "S5P1-PDF-004" else "doc-scoutflo:c00009"
            else:
                content = "Resources and essential links."
                chunk_id = "doc-scoutflo:c99999"
            return _response(query, sample_id, doc_id, source_file, content, chunk_id=chunk_id)

        content = "查询最近30分钟系统指标日志，关注 cpu_usage > 80，结合应用日志判断原因。AI 视觉识别，数据中心贯通多平台数据。PagerDuty Incident Response on-call practitioners SLO quarter uptime unreliability budget"
        return _response(query, sample_id, doc_id, source_file, content)


class FakeMetadataStore:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir

    def get_document(self, doc_id: str):
        if doc_id == "doc-scoutflo":
            return SimpleNamespace(doc_id=doc_id, artifact_dir=str(self.artifact_dir))
        return SimpleNamespace(doc_id=doc_id, artifact_dir="")

    def list_chunks_by_doc_id(self, doc_id: str):
        return [
            SimpleNamespace(chunk_id=f"{doc_id}:c00001"),
            SimpleNamespace(chunk_id=f"{doc_id}:c00004"),
            SimpleNamespace(chunk_id=f"{doc_id}:c00009"),
            SimpleNamespace(chunk_id=f"{doc_id}:c99999"),
        ]


class FakeGeneratorFactory:
    def __init__(self) -> None:
        self.variance_counts: dict[str, int] = {}

    def __call__(self, kind: str):
        return FakeGenerator(kind, self.variance_counts)


class FakeGenerator:
    generator_kind = "fake"
    model_name = "fake"

    def __init__(self, kind: str, variance_counts: dict[str, int]) -> None:
        self.kind = kind
        self.variance_counts = variance_counts

    def generate(self, *, query: str, context_text: str, sample: dict):
        sample_id = sample["sample_id"]
        if self.kind == "prompt_enhanced":
            return GenerationResult(_answer_with_all_facts(sample), True)
        if self.kind == "context_shadow":
            return GenerationResult(context_text + f" [source: {SOURCE_FILES[sample_id]}]", True)
        if self.kind == "generation_variance":
            count = self.variance_counts.get(sample_id, 0)
            self.variance_counts[sample_id] = count + 1
            if sample_id == "S5P1-PDF-001":
                if count in {1, 3}:
                    return GenerationResult(_answer_with_all_facts(sample), True)
                return GenerationResult("只说了 PagerDuty。[source: pagerduty.pdf]", True)
            return GenerationResult("只说了 SLO。[source: reliability.pdf]", True)
        return GenerationResult("笼统回答，没有覆盖所有 required facts。[source: source.md]", True)


def _write_evalset(path: Path) -> None:
    rows = [
        _sample("S5P1-MD-001", "CPU使用率持续超过80%怎么排查", "doc-cpu", "cpu_high_usage.md", ["查询最近30分钟系统指标日志", "cpu_usage > 80"]),
        _sample("S5P1-MD-002", "服务不可用时应该先检查什么", "doc-service", "service_unavailable.md", ["先确认故障并记录故障时间", "查询最近15分钟 application-logs", "ERROR", "restart"]),
        _sample("S5P1-MD-007", "中车长客数字化转型有哪些成果", "doc-crrc", "crrc.md", ["AI 视觉识别", "数据中心贯通"]),
        _sample("S5P1-PDF-001", "PagerDuty 文档的主要内容是什么", "doc-pagerduty", "pagerduty.pdf", ["PagerDuty", "Incident Response", "on-call practitioners"]),
        _sample("S5P1-PDF-002", "Unreliability Budgets 的定义是什么", "doc-reliability", "reliability.pdf", ["SLO", "quarter", "uptime", "unreliability budget"]),
        _sample("S5P1-PDF-004", "Scoutflo SRE Playbooks 支持哪些平台", "doc-scoutflo", "scoutflo.pdf", ["AWS", "Kubernetes", "Sentry", "414"]),
        _sample("S5P1-PDF-009", "Scoutflo 文档中 Kubernetes 章节在哪", "doc-scoutflo", "scoutflo.pdf", ["Kubernetes", "Folder Structure", "Control-Plane", "Pods"]),
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _write_baseline(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "summary": {"total": 20, "passed": 13, "failed": 7, "not_ready": 0},
                "results": [
                    {"sample_id": sample_id, "status": "failed", "failure_category": "answer_missing_facts"}
                    for sample_id in EXPECTED_DOCS
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_scoutflo_chunks(path: Path) -> None:
    chunks = [
        {"id": "c00004", "text": "Overview: AWS Kubernetes Sentry Total Playbooks: 414", "pages": [1]},
        {"id": "c00009", "text": "Kubernetes Folder Structure includes Control-Plane and Pods", "pages": [4, 5]},
    ]
    (path / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")


def _sample(sample_id: str, query: str, doc_id: str, source_file: str, facts: list[str]) -> dict:
    EXPECTED_DOCS[sample_id] = doc_id
    SOURCE_FILES[sample_id] = source_file
    return {
        "sample_id": sample_id,
        "layer": "answer",
        "query": f"{sample_id}::{query}",
        "allowed_kb_ids": ["process_digital_dept"],
        "expected_doc_ids": [doc_id],
        "scope": "scoped",
        "retrieval_mode": "dense_only",
        "top_k": 3,
        "reference_answer": "",
        "must_include_facts": facts,
        "must_not_include_claims": [],
        "required_citations": [{"doc_id": doc_id, "source_file": source_file, "expected_in_answer": source_file}],
        "answer_risk_type": "low",
        "context_policy": "retrieved_context_only",
        "judge_policy": "deterministic_only",
        "document_format": "pdf" if "PDF" in sample_id else "md",
    }


def _response(
    query: RetrievalQuery,
    sample_id: str,
    doc_id: str,
    source_file: str,
    content: str,
    *,
    chunk_id: str | None = None,
) -> RetrievalResponse:
    chunk_id = chunk_id or f"{doc_id}:c00001"
    result = RetrievalResult(
        kb_id="process_digital_dept",
        doc_id=doc_id,
        chunk_id=chunk_id,
        content=content,
        score=0.1,
        source_ref=SourceRef(
            kb_id="process_digital_dept",
            doc_id=doc_id,
            chunk_id=chunk_id,
            source_file=source_file,
            parser_engine=ParserEngine.MINERU if source_file.endswith(".pdf") else ParserEngine.PLAIN_TEXT,
        ),
        citation_text=f"[source: {source_file}, chunk: {chunk_id}]",
        metadata={},
    )
    context = f"【参考资料 1】\n来源: {source_file}\n内容:\n{content}\n"
    return RetrievalResponse(query=query, results=[result], context_text=context)


def _answer_with_all_facts(sample: dict) -> str:
    return "；".join(sample["must_include_facts"]) + f"。[source: {SOURCE_FILES[sample['sample_id']]}]"


EXPECTED_DOCS: dict[str, str] = {}
SOURCE_FILES: dict[str, str] = {}


if __name__ == "__main__":
    unittest.main()
