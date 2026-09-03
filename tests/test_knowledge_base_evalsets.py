import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.enterprise.context import RequestContext
from app.models import ParserEngine, RetrievalQuery, RetrievalResponse, RetrievalResult, SourceRef
from evals.knowledge_base.run_department_rag_eval import (
    evaluate_case,
    run_department_rag_eval,
)


class KnowledgeBaseEvalsetTests(unittest.TestCase):
    def test_evaluate_case_outputs_chapter_10_required_fields_when_no_results(self):
        case = {
            "sample_id": "RAG-X",
            "query": "中车长客数字化转型",
            "allowed_kb_ids": ["process_digital_dept"],
            "expected_doc_ids": ["doc-process"],
            "expected_answer_keywords": ["数字化"],
            "scope": "scoped",
        }

        class EmptyRetrievalService:
            def retrieve(self, query):
                return RetrievalResponse(query=query, results=[], context_text="")

        row = evaluate_case(
            case,
            retrieval_service=EmptyRetrievalService(),
            metadata_store=None,
            context=RequestContext(
                request_id="request-eval-test",
                trace_id="trace-eval-test",
                user_id="user-eval",
                username="eval",
                department_id="dept_1",
                department_name="dept",
                roles=["user"],
            ),
        )

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["no_result_reason"], "retrieval_no_hit")
        self.assertEqual(row["selected_kb_ids"], ["process_digital_dept"])
        self.assertEqual(row["source_ref"], [])
        self.assertEqual(row["answer_score"], 0.0)
        self.assertEqual(row["failure_category"], "no_retrieval_hit")

    def test_expected_permission_filtered_no_results_passes(self):
        case = {
            "sample_id": "PERM-X",
            "query": "工艺部现场设备工艺版第 1 页内容",
            "allowed_kb_ids": ["process_digital_dept"],
            "expected_doc_ids": [],
            "expected_answer_keywords": [],
            "scope": "scoped",
            "expected_failure": "permission_filtered",
        }

        row = evaluate_case(
            case,
            retrieval_service=_StaticRetrievalService([]),
            metadata_store=None,
            context=_eval_context(),
        )

        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["no_result_reason"], "permission_filtered")
        self.assertEqual(row["failure_category"], "passed")
        self.assertEqual(row["answer_score"], 1.0)

    def test_permission_filtered_target_short_circuits_before_retrieval(self):
        case = {
            "sample_id": "PERM-SHORT",
            "query": "工艺部现场设备工艺版第 1 页内容",
            "allowed_kb_ids": ["process_digital_dept"],
            "expected_doc_ids": [],
            "expected_answer_keywords": [],
            "scope": "scoped",
            "expected_failure": "permission_filtered",
            "target_kb_id": "craft_dept",
        }

        class RetrievalShouldNotRun:
            def retrieve(self, query):
                raise AssertionError("permission-filtered cases should not retrieve")

        row = evaluate_case(
            case,
            retrieval_service=RetrievalShouldNotRun(),
            metadata_store=None,
            context=_eval_context(),
        )

        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["no_result_reason"], "permission_filtered")
        self.assertEqual(row["result_count"], 0)

    def test_forbidden_kb_result_is_wrong_scope(self):
        case = {
            "sample_id": "SCOPE-X",
            "query": "运维手册的告警处理",
            "allowed_kb_ids": ["process_digital_dept"],
            "expected_doc_ids": ["doc-process"],
            "expected_answer_keywords": ["告警"],
            "scope": "scoped",
            "retrieved_must_not_contain_kb": ["craft_dept"],
        }

        row = evaluate_case(
            case,
            retrieval_service=_StaticRetrievalService([_retrieval_result(kb_id="craft_dept")]),
            metadata_store=None,
            context=_eval_context(),
        )

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["failure_category"], "wrong_scope")

    def test_citation_unresolvable_is_hard_failure(self):
        case = {
            "sample_id": "CITE-X",
            "query": "线上故障怎么处理",
            "allowed_kb_ids": ["process_digital_dept"],
            "expected_doc_ids": ["doc-process"],
            "expected_answer_keywords": ["故障"],
            "scope": "scoped",
            "citation_must_resolvable": True,
        }

        row = evaluate_case(
            case,
            retrieval_service=_StaticRetrievalService([_retrieval_result()]),
            metadata_store=_ChunkLookupStore(chunks=[]),
            context=_eval_context(),
        )

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["failure_category"], "citation_unresolvable")
        self.assertEqual(row["source_ref_integrity"]["citation_unresolvable_count"], 1)

    def test_runner_reports_guardrail_rates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evalset = Path(tmpdir) / "cases.jsonl"
            evalset.write_text(
                json.dumps(
                    {
                        "sample_id": "SCOPE-RATE",
                        "query": "运维手册的告警处理",
                        "allowed_kb_ids": ["process_digital_dept"],
                        "expected_doc_ids": ["doc-process"],
                        "expected_answer_keywords": ["告警"],
                        "scope": "scoped",
                        "retrieved_must_not_contain_kb": ["craft_dept"],
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "evals.knowledge_base.run_department_rag_eval.retrieval_service.retrieve",
                return_value=RetrievalResponse(
                    query=RetrievalQuery(query="运维手册的告警处理"),
                    results=[_retrieval_result(kb_id="craft_dept")],
                    context_text="告警",
                ),
            ):
                report = run_department_rag_eval(
                    evalset,
                    output_dir=Path(tmpdir),
                    write_report=True,
                    metadata_store=_ChunkLookupStore(chunks=[]),
                )

            self.assertEqual(report["summary"]["wrong_scope_count"], 1)
            self.assertEqual(report["summary"]["wrong_scope_rate"], 1.0)
            self.assertEqual(report["summary"]["citation_unresolvable_count"], 0)

    def test_runner_marks_eval_framework_blocked_instead_of_hiding_not_ready(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evalset = Path(tmpdir) / "cases.jsonl"
            evalset.write_text(
                json.dumps(
                    {
                        "sample_id": "RAG-BLOCKED",
                        "query": "线上故障怎么处理",
                        "allowed_kb_ids": ["process_digital_dept"],
                        "expected_doc_ids": [],
                        "expected_answer_keywords": [],
                        "scope": "scoped",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            with patch(
                "evals.knowledge_base.run_department_rag_eval.retrieval_service.retrieve",
                side_effect=RuntimeError("milvus unavailable"),
            ):
                report = run_department_rag_eval(evalset, output_dir=Path(tmpdir), write_report=True)

            self.assertEqual(report["summary"]["status_counts"], {"not_ready": 1})
            self.assertEqual(report["summary"]["failure_categories"], {"eval_framework_blocked": 1})
            self.assertEqual(report["results"][0]["status"], "not_ready")
            self.assertEqual(report["results"][0]["failure_category"], "eval_framework_blocked")
            self.assertTrue((Path(tmpdir) / report["report_json_path"]).exists())


class _StaticRetrievalService:
    def __init__(self, results):
        self._results = results

    def retrieve(self, query):
        return RetrievalResponse(
            query=query,
            results=self._results,
            context_text="\n".join(result.content for result in self._results),
        )


class _ChunkLookupStore:
    def __init__(self, chunks):
        self._chunks = chunks

    def list_chunks_by_doc_id(self, doc_id):
        return [chunk for chunk in self._chunks if chunk.doc_id == doc_id]


def _eval_context():
    return RequestContext(
        request_id="request-eval-test",
        trace_id="trace-eval-test",
        user_id="user-eval",
        username="eval",
        department_id="dept_1",
        department_name="dept",
        roles=["user"],
    )


def _retrieval_result(
    *,
    kb_id: str = "process_digital_dept",
    doc_id: str = "doc-process",
    chunk_id: str = "doc-process:c00001",
) -> RetrievalResult:
    source_ref = SourceRef(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file="oncall.md",
        page_start=1,
        page_end=1,
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    return RetrievalResult(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        content="告警 故障 处理",
        score=0.9,
        source_ref=source_ref,
        citation_text="来源: oncall.md",
        metadata={"source_ref": source_ref.model_dump(mode="json")},
    )


if __name__ == "__main__":
    unittest.main()
