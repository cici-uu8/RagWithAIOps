"""Answer shaping for deterministic knowledge orchestration v1."""

from __future__ import annotations

from typing import Any

from app.enterprise.rag.query_intent import QueryIntentDecision


class AnswerGenerator:
    def build_answer(
        self,
        *,
        query: str,
        decision: QueryIntentDecision,
        tool_result: Any = None,
    ) -> str:
        if decision.intent == "document_list":
            return self._document_list_answer(tool_result)
        if decision.intent in {"knowledge_qa", "document_read"}:
            answer = str(tool_result or "没有找到相关信息。")
            scope_note = self._scope_boundary_note(query, decision)
            if scope_note and scope_note not in answer and not self._claims_no_result(answer):
                return f"{answer}\n\n{scope_note}"
            return answer
        if decision.intent == "database":
            return "该问题已识别为数据库能力请求，将进入数据库安全边界处理。请在权限范围内通过数据库能力查看可访问的表，避免在知识库回答中直接执行查询。"
        if decision.intent == "permission_request":
            return "该问题已识别为权限申请请求，将进入权限申请流程。"
        if decision.intent == "permission_filtered":
            return "当前权限或知识库范围内没有可用于回答该问题的资料。请切换到有权限的知识库，或先申请相应资料权限。"
        if decision.intent == "human_review":
            return "该问题涉及高风险操作，需要进入人工审核或确认流程。"
        return ""

    def _document_list_answer(self, tool_result: Any) -> str:
        if not isinstance(tool_result, dict):
            return str(tool_result or "当前用户可见文档为空")
        documents = tool_result.get("documents") or []
        if not documents:
            return str(tool_result.get("message") or "当前用户可见文档为空")
        lines = ["当前可见文件："]
        for document in documents:
            file_name = document.get("file_name") or document.get("filename") or document.get("doc_id") or "-"
            kb_id = document.get("kb_id") or "-"
            lines.append(f"- {file_name}（{kb_id}）")
        return "\n".join(lines)

    def _scope_boundary_note(self, query: str, decision: QueryIntentDecision) -> str:
        if decision.intent != "knowledge_qa":
            return ""
        normalized = (query or "").casefold()
        if not ("中车长客" in normalized or "数字化转型" in normalized):
            return ""
        operational_markers = (
            "oncall",
            "sre",
            "故障",
            "告警",
            "排查",
            "处理",
            "redis",
            "mysql",
            "pod",
            "kafka",
            "cpu",
            "throttling",
        )
        if any(marker in normalized for marker in operational_markers):
            return ""
        return "范围说明：这是非故障排查问题，不是 oncall 处置请求；但属于当前知识范围内的企业资料问答。"

    def _claims_no_result(self, answer: str) -> bool:
        markers = (
            "没有找到相关信息",
            "没有找到直接",
            "当前权限或知识库范围内没有",
            "参考资料不足",
        )
        return any(marker in answer for marker in markers)


answer_generator = AnswerGenerator()
