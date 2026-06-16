import json

from evals.knowledge_base.hybrid_exact_code_fixture import (
    build_error_code_entries,
    build_query_rows,
    validate_fixture_files,
    write_fixture_files,
)
from evals.knowledge_base.run_hybrid_exact_code_probe import (
    parse_reference_chunks,
    run_probe,
)


def test_hybrid_exact_code_fixture_has_120_synthetic_entries(tmp_path):
    reference_path, query_path = write_fixture_files(tmp_path)
    validation = validate_fixture_files(reference_path, query_path)
    reference_text = reference_path.read_text(encoding="utf-8")
    query_rows = [
        json.loads(line)
        for line in query_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert validation["valid"] is True
    assert validation["entry_count"] == 120
    assert validation["rendered_entry_heading_count"] == 120
    assert len(parse_reference_chunks(reference_path)) == 120
    assert "synthetic=true" in reference_text
    assert "production_corpus: false" in reference_text
    assert len(query_rows) == 36
    assert sum(1 for row in query_rows if row["query_type"] == "exact_code") == 30
    assert all(row["synthetic"] is True for row in query_rows)


def test_fixture_generation_keeps_expected_category_counts():
    entries = build_error_code_entries()
    rows = build_query_rows(entries)
    category_counts = {}
    for entry in entries:
        category_counts[entry.category] = category_counts.get(entry.category, 0) + 1

    assert category_counts == {
        "数据库错误": 30,
        "Redis 错误": 20,
        "Kubernetes 错误": 25,
        "应用错误": 25,
        "网络错误": 10,
        "系统错误": 10,
    }
    assert len(rows) == 36


def test_hybrid_exact_code_probe_reports_limited_synthetic_conclusion(tmp_path):
    reference_path, query_path = write_fixture_files(tmp_path / "fixture")
    output_json = tmp_path / "report.json"
    output_md = tmp_path / "report.md"

    report = run_probe(
        reference_path=reference_path,
        query_path=query_path,
        output_json=output_json,
        output_md=output_md,
    )

    assert output_json.exists()
    assert output_md.exists()
    assert report["fixture"]["validation"]["valid"] is True
    assert report["fixture"]["synthetic"] is True
    assert report["fixture"]["production_corpus"] is False
    assert report["fixture"]["beta_baseline_impact"] == "none"
    assert report["external_llm_called"] is False
    assert report["external_vector_db_called"] is False
    assert report["summary"]["total_queries"] == 36
    assert report["summary"]["query_type_counts"]["exact_code"] == 30
    assert report["summary"]["exact_code_hybrid_lift_vs_dense_at3"] >= 3
    assert (
        report["decision"]["verdict"]
        == "hybrid_suitable_for_exact_code_doc_type"
    )
    assert "changing rag_default_retrieval_mode" in report["decision"]["not_evidence_for"]
    assert report["config_defaults_observed"]["rag_default_retrieval_mode"] == "dense_only"
    assert "cannot prove business corpus maturity" in output_md.read_text(encoding="utf-8")


def test_probe_dense_semantic_control_still_handles_name_queries(tmp_path):
    reference_path, query_path = write_fixture_files(tmp_path / "fixture")

    report = run_probe(reference_path=reference_path, query_path=query_path)

    semantic_total = report["summary"]["query_type_counts"]["semantic_name"]
    assert semantic_total == 6
    assert (
        report["summary"]["by_mode"]["dense_only"]["hit_at_3_by_type"]["semantic_name"]
        >= 4
    )
    assert (
        report["summary"]["by_mode"]["hybrid"]["hit_at_3_by_type"]["semantic_name"]
        >= 4
    )
