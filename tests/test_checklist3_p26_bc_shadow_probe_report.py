import json
import tempfile
import unittest
from pathlib import Path

from app.models import (
    ParserEngine,
    RetrievalMode,
    RetrievalQuery,
    RetrievalResponse,
    RetrievalResult,
    SourceRef,
)
from evals.knowledge_base.checklist3_p26_bc_shadow_probe_report import (
    build_p26_bc_shadow_probe_report,
    load_bc_candidates,
    rerank_service,
    write_p26_bc_shadow_probe_report,
)


class FakeProbeRetrievalService:
    def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
        results = self._results_for(query)
        return RetrievalResponse(
            query=query,
            results=results,
            context_text="\n".join(result.content for result in results),
        )

    def _results_for(self, query: RetrievalQuery) -> list[RetrievalResult]:
        sample = query.query
        mode = query.retrieval_mode
        if sample == "B lift sample":
            if mode == RetrievalMode.DENSE_ONLY:
                return [_result("doc-other")]
            if mode in {
                RetrievalMode.SPARSE_ONLY,
                RetrievalMode.HYBRID,
                RetrievalMode.HYBRID_RERANK,
            }:
                return [_result("doc-target")]
        if sample == "B dense already good":
            if mode == RetrievalMode.DENSE_ONLY:
                return [_result("doc-target")]
            return [_result("doc-target")]
        if sample == "C rank lift sample":
            if mode == RetrievalMode.HYBRID:
                return [_result("doc-other"), _result("doc-target")]
            if mode == RetrievalMode.HYBRID_RERANK:
                return [_result("doc-target", rerank_status="applied"), _result("doc-other", rerank_status="applied")]
            return [_result("doc-other"), _result("doc-target")]
        if sample == "C no rank lift":
            if mode == RetrievalMode.HYBRID_RERANK:
                return [_result("doc-target", rerank_status="applied")]
            return [_result("doc-target")]
        return []


class Checklist3P26BcShadowProbeReportTests(unittest.TestCase):
    def test_load_bc_candidates_from_markdown_tables(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _candidate_doc(Path(tmpdir))

            candidates = load_bc_candidates(path)

        self.assertEqual(len(candidates["benefit_b"]), 2)
        self.assertEqual(len(candidates["benefit_c"]), 2)
        self.assertEqual(candidates["benefit_b"][0]["sample_id"], "P26-B-001")
        self.assertEqual(candidates["benefit_b"][0]["allowed_kb_ids"], ["process_digital_dept"])
        self.assertEqual(candidates["benefit_b"][0]["expected_doc_ids"], ["doc-target"])
        self.assertEqual(candidates["benefit_b"][0]["expected_answer_keywords"], ["Primary"])

    def test_build_report_classifies_b_lift_and_c_true_rerank_rank_lift(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _candidate_doc(Path(tmpdir))
            original_enabled = rerank_service.enabled
            report = build_p26_bc_shadow_probe_report(
                candidate_doc_path=path,
                retrieval_service=FakeProbeRetrievalService(),
                min_effective_samples=1,
                enable_true_rerank_for_c=True,
            )

        self.assertEqual(rerank_service.enabled, original_enabled)
        self.assertEqual(report["status"], "passed_formal_upgrade_candidate")
        self.assertTrue(report["benefit_b"]["eligible_for_formal_evalset"])
        self.assertEqual(report["benefit_b"]["effective_lift_count"], 1)
        self.assertEqual(report["benefit_b"]["candidates"][0]["verdict"], "proven_lift")
        self.assertEqual(report["benefit_b"]["candidates"][1]["verdict"], "no_lift")
        self.assertTrue(report["benefit_c"]["eligible_for_formal_evalset"])
        self.assertTrue(report["benefit_c"]["true_rerank_applied"])
        self.assertEqual(report["benefit_c"]["effective_rank_lift_count"], 1)
        self.assertEqual(report["benefit_c"]["candidates"][0]["verdict"], "proven_rank_lift")
        self.assertEqual(report["benefit_c"]["candidates"][1]["verdict"], "no_rank_lift")
        self.assertEqual(report["decisions"]["default_switch_eligibility"], "not_eligible_for_default_switch")

    def test_report_stays_candidate_only_when_effective_counts_are_too_low(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = _candidate_doc(Path(tmpdir))
            report = build_p26_bc_shadow_probe_report(
                candidate_doc_path=path,
                retrieval_service=FakeProbeRetrievalService(),
                min_effective_samples=10,
                enable_true_rerank_for_c=True,
            )

        self.assertFalse(report["benefit_b"]["eligible_for_formal_evalset"])
        self.assertEqual(report["benefit_b"]["downgrade_to"], "lexical_lift_observation_report")
        self.assertFalse(report["benefit_c"]["eligible_for_formal_evalset"])
        self.assertEqual(report["benefit_c"]["downgrade_to"], "rank_lift_observation_report")
        self.assertFalse(report["decisions"]["create_benefit_b_formal_evalset"])
        self.assertFalse(report["decisions"]["create_benefit_c_formal_evalset"])

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = _candidate_doc(root)
            output_json = root / "probe.json"
            output_md = root / "probe.md"

            report = write_p26_bc_shadow_probe_report(
                candidate_doc_path=path,
                retrieval_service=FakeProbeRetrievalService(),
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(json.loads(output_json.read_text(encoding="utf-8"))["status"], report["status"])
            self.assertTrue(output_md.exists())
            self.assertIn("Benefit-B/C Shadow Probe", output_md.read_text(encoding="utf-8"))


def _candidate_doc(root: Path) -> Path:
    path = root / "candidates.md"
    path.write_text(
        """
## 5. Benefit-B: sparse / hybrid lift 15q 候选

| candidate_id | query | allowed_kb_ids | expected_doc_ids | keywords | failure_class | support_check_status | notes |
|---|---|---|---|---|---|---|---|
| P26-B-001 | B lift sample | `process_digital_dept` | `doc-target` | `Primary` | `acronym` | `needs_shadow_probe` | test |
| P26-B-002 | B dense already good | `process_digital_dept` | `doc-target` | `Ack` | `exact_term` | `needs_shadow_probe` | test |

## 6. Benefit-C: rerank rank lift 15q 候选

| candidate_id | query | allowed_kb_ids | expected_doc_ids | keywords | failure_class | support_check_status | seed_evidence |
|---|---|---|---|---|---|---|---|
| P26-C-001 | C rank lift sample | `process_digital_dept` | `doc-target` | `Runbook` | `rank_lift` | `needs_shadow_probe` | test |
| P26-C-002 | C no rank lift | `process_digital_dept` | `doc-target` | `Runbook` | `rank_lift` | `needs_shadow_probe` | test |
""",
        encoding="utf-8",
    )
    return path


def _result(doc_id: str, *, rerank_status: str = "") -> RetrievalResult:
    chunk_id = f"{doc_id}:c00001"
    source_ref = SourceRef(
        kb_id="process_digital_dept",
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file="superbiz_oncall_handbook.md",
        parser_engine=ParserEngine.PLAIN_TEXT,
    )
    metadata = {"source_ref": source_ref.model_dump(mode="json")}
    if rerank_status:
        metadata["rerank_status"] = rerank_status
    return RetrievalResult(
        kb_id="process_digital_dept",
        doc_id=doc_id,
        chunk_id=chunk_id,
        content=f"{doc_id} content",
        score=1.0,
        source_ref=source_ref,
        citation_text="来源: superbiz_oncall_handbook.md",
        metadata=metadata,
    )


if __name__ == "__main__":
    unittest.main()
