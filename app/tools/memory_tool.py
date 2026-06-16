"""Sidecar durable memory retrieval tool."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from loguru import logger

from app.services.memory_retrieval_service import (
    MemoryRetrievalQuery,
    memory_retrieval_service,
)


@tool(response_format="content_and_artifact")
def retrieve_memory(
    query: str,
    owner_id: str = "default",
    namespaces: Optional[List[str]] = None,
    memory_types: Optional[List[str]] = None,
    top_k: int = 3,
) -> Tuple[str, Dict[str, Any]]:
    """Retrieve durable oncall memory in explicit sidecar flows only.

    This tool is intentionally not part of the default RAG agent tool list.
    Memory hits are guidance artifacts, not document citations.
    """
    try:
        memory_query = MemoryRetrievalQuery(
            query=query,
            owner_id=owner_id,
            namespaces=list(namespaces) if namespaces else [],
            memory_types=list(memory_types) if memory_types else [],
            top_k=top_k,
        )
        logger.info(
            "memory retrieval tool called: query='{}', owner_id={}, namespaces={}, memory_types={}",
            query,
            owner_id,
            memory_query.namespaces,
            [memory_type.value for memory_type in memory_query.memory_types],
        )
        response = memory_retrieval_service.retrieve(memory_query)
        artifact = response.model_dump(mode="json")
        artifact["status"] = "ok" if response.memory_results else "empty"
        return _format_memory_content(artifact), artifact
    except Exception as exc:
        logger.error("memory retrieval tool failed: {}", exc)
        error_message = f"检索记忆时发生错误: {exc}"
        return error_message, {
            "query": query,
            "owner_id": owner_id,
            "memory_results": [],
            "namespaces": list(namespaces) if namespaces else [],
            "memory_types": list(memory_types) if memory_types else [],
            "status": "error",
            "trace": {"error": str(exc)},
            "empty_message": error_message,
        }


def _format_memory_content(artifact: Dict[str, Any]) -> str:
    results = artifact.get("memory_results", [])
    if not results:
        return str(artifact.get("empty_message", "No active memory matched the query."))

    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        lines.append(f"【记忆 {index}】")
        lines.append(f"类型: {result.get('memory_type', '')}")
        lines.append(f"命名空间: {result.get('namespace', '')}")
        lines.append(f"摘要: {result.get('summary', '')}")
        lines.append(f"内容: {result.get('content', '')}")
        matched_terms = result.get("matched_terms") or []
        if matched_terms:
            lines.append(f"命中词: {', '.join(str(term) for term in matched_terms)}")
        lines.append("")
    return "\n".join(lines).strip()
