"""Checklist 3 RAG shadow inventory report.

This report is intentionally static/read-only. It inventories current RAG
retrieval enhancement code paths and existing shadow comparison assets without
calling Milvus, LLMs, or changing runtime defaults.
"""

from __future__ import annotations

import argparse
import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_COMPARISON_SAMPLES_PATH = "<local-approved-comparison-samples>"
DEFAULT_COMPARISON_REPORT_PATH = (
    "evals/knowledge_base/fixtures/retrieval_mode_comparison_summary.json"
)
REQUIRED_RETRIEVAL_MODES = ["dense_only", "sparse_only", "hybrid", "hybrid_rerank"]
REQUIRED_COMPARISON_MODES = ["dense_only", "sparse_only", "hybrid", "hybrid_rerank"]


def build_checklist3_rag_shadow_inventory_report(
    *,
    repo_root: str | Path | None = None,
    comparison_samples_path: str | Path = DEFAULT_COMPARISON_SAMPLES_PATH,
    comparison_report_path: str | Path = DEFAULT_COMPARISON_REPORT_PATH,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    retrieval_modes = _retrieval_mode_inventory(root)
    services = _service_inventory(root)
    defaults = _default_config_inventory(root)
    tool_schema = _retrieve_knowledge_tool_schema(root)
    comparison_runner = _comparison_runner_inventory(
        root,
        comparison_samples_path=comparison_samples_path,
        comparison_report_path=comparison_report_path,
    )
    query_rewrite = _query_rewrite_inventory(root)
    safety = {
        "runs_retrieval": False,
        "changes_runtime_config": False,
        "changes_default_retrieval_mode": False,
        "exposes_retrieval_mode_to_model": tool_schema["exposes_retrieval_mode"],
    }
    gaps = _gaps(
        retrieval_modes=retrieval_modes,
        services=services,
        defaults=defaults,
        tool_schema=tool_schema,
        comparison_runner=comparison_runner,
        query_rewrite=query_rewrite,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "ready_for_shadow_eval" if not gaps else "needs_shadow_expansion",
        "scope": {
            "phase": "S3-P2.1",
            "report_kind": "rag_shadow_inventory",
            "repo_root": root.as_posix(),
            "read_only": True,
        },
        "retrieval_modes": retrieval_modes,
        "services": services,
        "defaults": defaults,
        "tool_schema": tool_schema,
        "comparison_runner": comparison_runner,
        "query_rewrite": query_rewrite,
        "safety": safety,
        "gaps": gaps,
    }


def write_checklist3_rag_shadow_inventory_report(
    *,
    output_json: str | Path,
    output_md: str | Path | None = None,
    repo_root: str | Path | None = None,
    comparison_samples_path: str | Path = DEFAULT_COMPARISON_SAMPLES_PATH,
    comparison_report_path: str | Path = DEFAULT_COMPARISON_REPORT_PATH,
) -> dict[str, Any]:
    report = build_checklist3_rag_shadow_inventory_report(
        repo_root=repo_root,
        comparison_samples_path=comparison_samples_path,
        comparison_report_path=comparison_report_path,
    )
    output_json_path = Path(output_json)
    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if output_md is not None:
        output_md_path = Path(output_md)
        output_md_path.parent.mkdir(parents=True, exist_ok=True)
        output_md_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def _retrieval_mode_inventory(root: Path) -> dict[str, Any]:
    rel = "app/models/knowledge.py"
    info = _class_info(root, rel, "RetrievalMode")
    values = _enum_string_values(root / rel, "RetrievalMode")
    return {
        **info,
        "values": values,
        "required_values": list(REQUIRED_RETRIEVAL_MODES),
        "supports_required_modes": all(mode in values for mode in REQUIRED_RETRIEVAL_MODES),
    }


def _service_inventory(root: Path) -> dict[str, Any]:
    hybrid_rel = "app/services/hybrid_search_service.py"
    rerank_rel = "app/services/rerank_service.py"
    retrieval_rel = "app/services/retrieval_service.py"
    hybrid_text = _read_text(root / hybrid_rel)
    rerank_text = _read_text(root / rerank_rel)
    retrieval_text = _read_text(root / retrieval_rel)
    return {
        "retrieval_service": {
            **_class_info(root, retrieval_rel, "RetrievalService"),
            "uses_hybrid_for_non_dense": (
                "if query.retrieval_mode == RetrievalMode.DENSE_ONLY" in retrieval_text
                and "hybrid_search_service.search(query)" in retrieval_text
            ),
        },
        "hybrid_search_service": {
            **_class_info(root, hybrid_rel, "HybridSearchService"),
            "uses_dense": "vector_search_service.search_similar_documents" in hybrid_text,
            "uses_sparse": "sparse_search_service.search" in hybrid_text,
            "uses_rrf": "RrfFusionService" in hybrid_text and ".fuse(" in hybrid_text,
            "supports_hybrid_rerank": "RetrievalMode.HYBRID_RERANK" in hybrid_text,
            "calls_rerank_service": "rerank_service.rerank" in hybrid_text,
        },
        "rerank_service": {
            **_class_info(root, rerank_rel, "RerankService"),
            "has_enabled_flag": "self.enabled" in rerank_text,
            "has_timeout_gate": "timeout_ms" in rerank_text and "TimeoutError" in rerank_text,
            "has_fallback_on_error": "fallback_on_error" in rerank_text,
            "default_model": _settings_defaults(root).get("rerank_model"),
        },
    }


def _default_config_inventory(root: Path) -> dict[str, Any]:
    defaults = _settings_defaults(root)
    return {
        "rag_default_retrieval_mode": {
            "source_default": defaults.get("rag_default_retrieval_mode"),
            "expected": "dense_only",
            "ok": defaults.get("rag_default_retrieval_mode") == "dense_only",
            "source": "app/config.py",
        },
        "rag_query_rewrite_mode": {
            "source_default": defaults.get("rag_query_rewrite_mode"),
            "expected": "off",
            "ok": defaults.get("rag_query_rewrite_mode") == "off",
            "source": "app/config.py",
        },
        "rerank_enabled": {
            "source_default": defaults.get("rerank_enabled"),
            "expected": False,
            "ok": defaults.get("rerank_enabled") is False,
            "source": "app/config.py",
        },
    }


def _retrieve_knowledge_tool_schema(root: Path) -> dict[str, Any]:
    rel = "app/tools/knowledge_tool.py"
    args = _function_args(root / rel, "retrieve_knowledge")
    text = _read_text(root / rel)
    reader = _function_info(root, rel, "_default_retrieval_mode")
    return {
        "source": rel,
        "retrieve_knowledge_args": args,
        "exposes_retrieval_mode": "retrieval_mode" in args,
        "default_retrieval_mode_reader": reader,
        "reader_uses_config": "config.rag_default_retrieval_mode" in text,
        "fallbacks_to_dense_only": "RetrievalMode.DENSE_ONLY" in text,
    }


def _comparison_runner_inventory(
    root: Path,
    *,
    comparison_samples_path: str | Path,
    comparison_report_path: str | Path,
) -> dict[str, Any]:
    runner_rel = "evals/knowledge_base/retrieval_mode_comparison_report.py"
    test_rel = "tests/test_retrieval_mode_comparison_report.py"
    runner_text = _read_text(root / runner_rel)
    sample_rel = Path(comparison_samples_path).as_posix()
    report_rel = Path(comparison_report_path).as_posix()
    sample_path = root / sample_rel
    report_path = root / report_rel
    compared_modes = [
        mode
        for mode in REQUIRED_COMPARISON_MODES
        if f"RetrievalMode.{_enum_member_name(mode)}" in runner_text
    ]
    latest_summary = _load_report_summary(report_path)
    return {
        "runner": {
            **_function_info(root, runner_rel, "build_retrieval_mode_comparison_report"),
            "path": runner_rel,
        },
        "test_exists": (root / test_rel).exists(),
        "test_path": test_rel,
        "samples_path": sample_rel,
        "samples_exists": sample_path.exists(),
        "sample_count": _sample_count(sample_path),
        "compared_modes": compared_modes,
        "required_modes": list(REQUIRED_COMPARISON_MODES),
        "covers_required_modes": all(mode in compared_modes for mode in REQUIRED_COMPARISON_MODES),
        "latest_report_path": report_rel,
        "latest_report_exists": report_path.exists(),
        "latest_report_summary": latest_summary,
        "latest_report_gate": _comparison_report_gate(latest_summary),
    }


def _query_rewrite_inventory(root: Path) -> dict[str, Any]:
    app_hits: list[dict[str, Any]] = []
    for path in sorted((root / "app").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == "app/config.py":
            continue
        text = _read_text(path).lower()
        if "query_rewrite" in text or "queryrewrite" in text:
            app_hits.append({"path": rel})
    config_defaults = _settings_defaults(root)
    return {
        "config_field_exists": "rag_query_rewrite_mode" in config_defaults,
        "source_default": config_defaults.get("rag_query_rewrite_mode"),
        "implementation_files": app_hits,
        "status": "implemented" if app_hits else "not_implemented",
    }


def _gaps(
    *,
    retrieval_modes: dict[str, Any],
    services: dict[str, Any],
    defaults: dict[str, Any],
    tool_schema: dict[str, Any],
    comparison_runner: dict[str, Any],
    query_rewrite: dict[str, Any],
) -> list[str]:
    gaps: list[str] = []
    if not retrieval_modes["supports_required_modes"]:
        gaps.append("retrieval_mode_enum_missing_required_modes")
    if not services["hybrid_search_service"]["exists"]:
        gaps.append("hybrid_search_service_missing")
    if not services["rerank_service"]["exists"]:
        gaps.append("rerank_service_missing")
    if not defaults["rag_default_retrieval_mode"]["ok"]:
        gaps.append("rag_default_retrieval_mode_not_dense_only")
    if not defaults["rag_query_rewrite_mode"]["ok"]:
        gaps.append("rag_query_rewrite_mode_not_off")
    if not defaults["rerank_enabled"]["ok"]:
        gaps.append("rerank_enabled_not_false")
    if tool_schema["exposes_retrieval_mode"]:
        gaps.append("retrieve_knowledge_exposes_retrieval_mode")
    if not comparison_runner["runner"]["exists"]:
        gaps.append("retrieval_mode_comparison_runner_missing")
    if not comparison_runner["samples_exists"]:
        gaps.append("retrieval_mode_comparison_samples_missing")
    if not comparison_runner["covers_required_modes"]:
        missing = sorted(
            set(comparison_runner["required_modes"]) - set(comparison_runner["compared_modes"])
        )
        gaps.extend(f"comparison_runner_missing_{mode}" for mode in missing)
    if not comparison_runner["latest_report_exists"]:
        gaps.append("retrieval_mode_comparison_latest_report_missing")
    if query_rewrite["status"] != "implemented":
        gaps.append("query_rewrite_not_implemented")
    return gaps


def _class_info(root: Path, rel_path: str, class_name: str) -> dict[str, Any]:
    node = _find_ast_node(root / rel_path, ast.ClassDef, class_name)
    return {
        "exists": node is not None,
        "path": rel_path,
        "line": int(node.lineno) if node is not None else 0,
    }


def _function_info(root: Path, rel_path: str, function_name: str) -> dict[str, Any]:
    node = _find_ast_node(root / rel_path, ast.FunctionDef, function_name)
    return {
        "exists": node is not None,
        "path": rel_path,
        "line": int(node.lineno) if node is not None else 0,
    }


def _find_ast_node(path: Path, node_type: type, name: str):
    if not path.exists():
        return None
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, node_type) and getattr(node, "name", "") == name:
            return node
    return None


def _enum_string_values(path: Path, class_name: str) -> list[str]:
    class_node = _find_ast_node(path, ast.ClassDef, class_name)
    if class_node is None:
        return []
    values: list[str] = []
    for node in class_node.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                values.append(node.value.value)
    return values


def _settings_defaults(root: Path) -> dict[str, Any]:
    path = root / "app/config.py"
    if not path.exists():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defaults: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Settings":
            continue
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                try:
                    defaults[item.target.id] = ast.literal_eval(item.value)
                except (TypeError, ValueError):
                    continue
    return defaults


def _function_args(path: Path, function_name: str) -> list[str]:
    node = _find_ast_node(path, ast.FunctionDef, function_name)
    if node is None:
        return []
    return [arg.arg for arg in node.args.args]


def _sample_count(path: Path) -> int:
    if not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return len(payload)
    return len(payload.get("samples") or [])


def _load_report_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _comparison_report_gate(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {
            "available": False,
            "not_ready_count": None,
            "wrong_scope_count": None,
            "citation_incomplete_count": None,
            "gate_passed": False,
        }
    not_ready_count = int(summary.get("not_ready_count") or 0)
    wrong_scope_count = int(summary.get("wrong_scope_count") or 0)
    citation_incomplete_count = int(summary.get("citation_incomplete_count") or 0)
    return {
        "available": True,
        "not_ready_count": not_ready_count,
        "wrong_scope_count": wrong_scope_count,
        "citation_incomplete_count": citation_incomplete_count,
        "gate_passed": (
            not_ready_count == 0
            and wrong_scope_count == 0
            and citation_incomplete_count == 0
        ),
    }


def _enum_member_name(mode: str) -> str:
    return mode.upper()


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Checklist 3 RAG Shadow Inventory Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Status: `{report['status']}`",
        f"- Phase: `{report['scope']['phase']}`",
        f"- Read-only: `{report['scope']['read_only']}`",
        f"- Runs retrieval: `{report['safety']['runs_retrieval']}`",
        f"- Changes runtime config: `{report['safety']['changes_runtime_config']}`",
        f"- Gaps: {report['gaps'] or []}",
        "",
        "## Retrieval Modes",
        "",
        f"- Source: `{report['retrieval_modes']['path']}:{report['retrieval_modes']['line']}`",
        f"- Values: {report['retrieval_modes']['values']}",
        "",
        "## Services",
        "",
        "| service | exists | path | line | key facts |",
        "|---|---|---|---:|---|",
    ]
    for name, info in report["services"].items():
        facts = [
            key
            for key, value in info.items()
            if key not in {"exists", "path", "line"} and value is True
        ]
        lines.append(
            f"| {name} | {info['exists']} | `{info['path']}` | {info['line']} | {', '.join(facts) or '-'} |"
        )
    lines.extend(
        [
            "",
            "## Defaults",
            "",
            "| config | source default | expected | ok |",
            "|---|---|---|---|",
        ]
    )
    for name, row in report["defaults"].items():
        lines.append(f"| {name} | `{row['source_default']}` | `{row['expected']}` | {row['ok']} |")
    lines.extend(
        [
            "",
            "## Comparison Runner",
            "",
            f"- Runner: `{report['comparison_runner']['runner']['path']}:{report['comparison_runner']['runner']['line']}`",
            f"- Compared modes: {report['comparison_runner']['compared_modes']}",
            f"- Covers required modes: `{report['comparison_runner']['covers_required_modes']}`",
            f"- Latest report gate: {report['comparison_runner']['latest_report_gate']}",
            "",
            "## Query Rewrite",
            "",
            f"- Status: `{report['query_rewrite']['status']}`",
            f"- Source default: `{report['query_rewrite']['source_default']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default="")
    parser.add_argument("--comparison-samples", default=DEFAULT_COMPARISON_SAMPLES_PATH)
    parser.add_argument("--comparison-report", default=DEFAULT_COMPARISON_REPORT_PATH)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()
    write_checklist3_rag_shadow_inventory_report(
        repo_root=args.repo_root or None,
        comparison_samples_path=args.comparison_samples,
        comparison_report_path=args.comparison_report,
        output_json=args.output_json,
        output_md=args.output_md or None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
