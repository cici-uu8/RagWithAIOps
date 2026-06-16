import tempfile
import unittest
from pathlib import Path

from evals.knowledge_base.checklist3_rag_shadow_inventory_report import (
    build_checklist3_rag_shadow_inventory_report,
    write_checklist3_rag_shadow_inventory_report,
)


class Checklist3RagShadowInventoryReportTests(unittest.TestCase):
    def test_current_repo_inventory_records_existing_capabilities_and_gaps(self):
        report = build_checklist3_rag_shadow_inventory_report()

        self.assertEqual(report["status"], "needs_shadow_expansion")
        self.assertEqual(
            report["retrieval_modes"]["values"],
            ["dense_only", "sparse_only", "hybrid", "hybrid_rerank"],
        )
        self.assertTrue(report["retrieval_modes"]["supports_required_modes"])
        self.assertTrue(report["services"]["hybrid_search_service"]["exists"])
        self.assertTrue(report["services"]["hybrid_search_service"]["uses_rrf"])
        self.assertTrue(report["services"]["hybrid_search_service"]["supports_hybrid_rerank"])
        self.assertTrue(report["services"]["rerank_service"]["exists"])
        self.assertTrue(report["services"]["rerank_service"]["has_fallback_on_error"])
        self.assertTrue(report["defaults"]["rag_default_retrieval_mode"]["ok"])
        self.assertTrue(report["defaults"]["rag_query_rewrite_mode"]["ok"])
        self.assertTrue(report["defaults"]["rerank_enabled"]["ok"])
        self.assertFalse(report["tool_schema"]["exposes_retrieval_mode"])
        self.assertTrue(report["tool_schema"]["reader_uses_config"])
        self.assertTrue(report["comparison_runner"]["runner"]["exists"])
        self.assertEqual(
            report["comparison_runner"]["compared_modes"],
            ["dense_only", "sparse_only", "hybrid", "hybrid_rerank"],
        )
        self.assertTrue(report["comparison_runner"]["covers_required_modes"])
        self.assertEqual(report["query_rewrite"]["status"], "not_implemented")
        self.assertIn("query_rewrite_not_implemented", report["gaps"])
        self.assertFalse(report["safety"]["runs_retrieval"])
        self.assertFalse(report["safety"]["changes_runtime_config"])

    def test_inventory_reads_latest_comparison_report_summary(self):
        report = build_checklist3_rag_shadow_inventory_report()
        gate = report["comparison_runner"]["latest_report_gate"]

        self.assertTrue(gate["available"])
        self.assertEqual(gate["not_ready_count"], 0)
        self.assertEqual(gate["wrong_scope_count"], 0)
        self.assertEqual(gate["citation_incomplete_count"], 0)
        self.assertTrue(gate["gate_passed"])

    def test_missing_comparison_assets_are_reported_as_gaps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_minimal_repo(root)

            report = build_checklist3_rag_shadow_inventory_report(
                repo_root=root,
                comparison_samples_path="missing_samples.json",
                comparison_report_path="missing_report.json",
            )

            self.assertEqual(report["status"], "needs_shadow_expansion")
            self.assertIn("retrieval_mode_comparison_samples_missing", report["gaps"])
            self.assertIn("retrieval_mode_comparison_latest_report_missing", report["gaps"])

    def test_write_report_outputs_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_json = root / "rag_inventory.json"
            output_md = root / "rag_inventory.md"

            report = write_checklist3_rag_shadow_inventory_report(
                output_json=output_json,
                output_md=output_md,
            )

            self.assertEqual(report["status"], "needs_shadow_expansion")
            self.assertTrue(output_json.exists())
            self.assertTrue(output_md.exists())
            self.assertIn(
                "Checklist 3 RAG Shadow Inventory Report",
                output_md.read_text(encoding="utf-8"),
            )


def _write_minimal_repo(root: Path) -> None:
    (root / "app/models").mkdir(parents=True)
    (root / "app/services").mkdir(parents=True)
    (root / "app/tools").mkdir(parents=True)
    (root / "evals/knowledge_base").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "app/config.py").write_text(
        """
class Settings:
    rag_default_retrieval_mode: str = "dense_only"
    rag_query_rewrite_mode: str = "off"
    rerank_enabled: bool = False
    rerank_model: str = "local_lexical_v1"
""",
        encoding="utf-8",
    )
    (root / "app/models/knowledge.py").write_text(
        """
class RetrievalMode:
    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
""",
        encoding="utf-8",
    )
    (root / "app/services/retrieval_service.py").write_text(
        """
class RetrievalService:
    def retrieve(self, query):
        if query.retrieval_mode == RetrievalMode.DENSE_ONLY:
            return vector_search_service.search_similar_documents(query.query)
        return hybrid_search_service.search(query)
""",
        encoding="utf-8",
    )
    (root / "app/services/hybrid_search_service.py").write_text(
        """
class HybridSearchService:
    def search(self, query):
        dense = vector_search_service.search_similar_documents(query.query)
        sparse = sparse_search_service.search(query.query)
        fused = RrfFusionService().fuse([dense, sparse])
        if query.retrieval_mode == RetrievalMode.HYBRID_RERANK:
            return rerank_service.rerank(query, fused)
        return fused
""",
        encoding="utf-8",
    )
    (root / "app/services/rerank_service.py").write_text(
        """
class RerankService:
    def __init__(self):
        self.enabled = False
        self.fallback_on_error = True
        self.timeout_ms = 500
        TimeoutError
""",
        encoding="utf-8",
    )
    (root / "app/tools/knowledge_tool.py").write_text(
        """
def retrieve_knowledge(query, knowledge_base_ids=None, file_name=None, doc_id=None, top_k=None):
    return query

def _default_retrieval_mode():
    return config.rag_default_retrieval_mode or RetrievalMode.DENSE_ONLY
""",
        encoding="utf-8",
    )
    (root / "evals/knowledge_base/retrieval_mode_comparison_report.py").write_text(
        """
def build_retrieval_mode_comparison_report(samples):
    return [RetrievalMode.DENSE_ONLY, RetrievalMode.HYBRID]
""",
        encoding="utf-8",
    )
    (root / "tests/test_retrieval_mode_comparison_report.py").write_text(
        "def test_placeholder():\n    pass\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
