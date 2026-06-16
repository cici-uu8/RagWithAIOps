"""
Memory Guidance Service: 格式化 memory 为 LLM prompt guidance

P5 职责:
- 将 MemoryRetrievalResult 格式化为带标签的 guidance 文本
- 明确标注 memory 不是 document source
- 暴露 updated_at、evidence_refs、status
- 提供 replanner 可推翻的 guidance 格式
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from textwrap import dedent

from app.models.memory import (
    MemoryRecord,
    MemoryType,
    AlertPatternPayload,
    PlanTemplatePayload,
)
from app.services.memory_retrieval_service import MemoryRetrievalResponse, MemoryRetrievalResult


class MemoryGuidanceService:
    """格式化 memory 为 LLM guidance"""

    @staticmethod
    def format_hierarchical_guidance(
        hierarchical_response: Any,
        include_metadata: bool = True,
    ) -> str:
        """
        Format P7.5 layered memory retrieval for planner guidance.

        L2 scenario guidance is preferred. If no L2 scenario is returned, L1
        atom guidance is used. Legacy memories keep the P6/P6_v2 format and are
        explicitly marked as not-yet-aggregated memory.
        """
        l2_scenarios: list[MemoryRetrievalResult] = list(
            getattr(hierarchical_response, "l2_scenarios", [])
        )
        l1_atoms: list[MemoryRetrievalResult] = list(getattr(hierarchical_response, "l1_atoms", []))
        legacy_memories: list[MemoryRetrievalResult] = list(
            getattr(hierarchical_response, "legacy_memories", [])
        )

        if not (l2_scenarios or l1_atoms or legacy_memories):
            return ""

        if legacy_memories and not l2_scenarios and not l1_atoms:
            legacy_response = MemoryRetrievalResponse(
                query=getattr(hierarchical_response, "query", ""),
                owner_id=getattr(hierarchical_response, "owner_id", "default"),
                memory_results=legacy_memories,
                empty_message="",
                trace=getattr(hierarchical_response, "trace", {}),
            )
            legacy_guidance = MemoryGuidanceService.format_memory_guidance(
                legacy_response,
                include_metadata=include_metadata,
            )
            if not legacy_guidance:
                return ""
            return "\n".join(
                [
                    "## 分层运行时记忆指导",
                    "",
                    "基于历史记忆（待聚合）:",
                    "",
                    legacy_guidance,
                ]
            )

        lines = MemoryGuidanceService._hierarchical_guidance_header()

        if l2_scenarios:
            lines.append("基于历史场景经验:")
            lines.append("")
            for idx, scenario in enumerate(l2_scenarios, 1):
                MemoryGuidanceService._append_l2_scenario_guidance(
                    lines,
                    scenario,
                    idx=idx,
                    include_metadata=include_metadata,
                )
        elif l1_atoms:
            lines.append("基于历史原子观测:")
            lines.append("")
            for idx, atom in enumerate(l1_atoms, 1):
                MemoryGuidanceService._append_l1_atom_guidance(
                    lines,
                    atom,
                    idx=idx,
                    include_metadata=include_metadata,
                )

        lines.append("---")
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def format_memory_guidance(
        retrieval_response: MemoryRetrievalResponse,
        include_metadata: bool = True
    ) -> str:
        """
        将 memory retrieval response 格式化为 prompt guidance

        Args:
            retrieval_response: memory 检索响应
            include_metadata: 是否包含 updated_at / evidence_refs / status

        Returns:
            格式化的 guidance 文本
        """
        if not retrieval_response.memory_results:
            return ""

        guidance_lines = [
            "## 运行时记忆指导",
            "",
            "以下内容是用户偏好、处理经验或运行时上下文。",
            "- 它们不是文档来源，不能作为文档 citation。",
            "- 当前工具观测（日志、指标、配置、部署记录）优先于历史 memory。",
            "- 如果当前观测明确反驳旧记忆（例如当前工具观测显示已修复），以新证据为准，并说明历史记忆可能过时。",
            "- 如果当前观测不充分，可以把记忆作为待验证假设并执行 fresh checks。",
            "- 每条记忆包含 updated_at 和 evidence_refs。",
            "- 如果新工具证据与旧记忆冲突，以新证据为准，并将旧记忆标记为 candidate/conflict。",
            ""
        ]

        for idx, memory in enumerate(retrieval_response.memory_results, 1):
            guidance_lines.append(f"### 记忆 {idx}: {memory.memory_type}")
            guidance_lines.append("")

            # 主要内容
            guidance_lines.append(f"**摘要**: {memory.summary}")
            guidance_lines.append("")
            guidance_lines.append(f"**内容**: {memory.content}")
            guidance_lines.append("")

            # metadata
            if include_metadata:
                guidance_lines.append(f"**状态**: {memory.status}")
                guidance_lines.append(f"**更新时间**: {memory.updated_at.isoformat()}")

                # evidence_refs
                if memory.evidence_refs:
                    evidence_summary = MemoryGuidanceService._format_evidence_summary(
                        memory.evidence_refs
                    )
                    if evidence_summary:
                        guidance_lines.append(f"**证据来源**: {evidence_summary}")

                guidance_lines.append("")

        guidance_lines.append("---")
        guidance_lines.append("")

        return "\n".join(guidance_lines)

    @staticmethod
    def _hierarchical_guidance_header() -> list[str]:
        return [
            "## 分层运行时记忆指导",
            "",
            "以下内容是运行时 memory 的分层召回结果。",
            "- 它们不是文档来源，不能作为文档 citation。",
            "- 当前工具观测（日志、指标、配置、部署记录）优先于历史 memory。",
            "- 如果当前观测明确反驳历史 scenario 或 atom，以当前观测为准，并说明历史 memory 可能过时。",
            "- L2 scenario 是由 L1 atom 聚合出的经验包，L2 scenario 不是文档 citation。",
            "- 每条结果保留 L1 atom ids 和 L0 evidence refs，必要时可下钻核验。",
            "",
        ]

    @staticmethod
    def _append_l2_scenario_guidance(
        lines: list[str],
        scenario: MemoryRetrievalResult,
        *,
        idx: int,
        include_metadata: bool,
    ) -> None:
        payload = scenario.payload
        title = payload.get("scenario_title") or scenario.summary
        lines.append(f"### 历史场景经验 {idx}: {title}")
        lines.append("")
        MemoryGuidanceService._append_text_list(
            lines,
            "适用条件",
            payload.get("applicable_conditions", []),
        )
        MemoryGuidanceService._append_text_list(
            lines,
            "建议诊断步骤",
            payload.get("diagnostic_path", []),
            numbered=True,
        )
        MemoryGuidanceService._append_text_list(
            lines,
            "常见根因",
            payload.get("common_root_causes", []),
        )
        MemoryGuidanceService._append_text_list(
            lines,
            "修复建议",
            payload.get("remediation_steps", []),
        )

        l1_atom_ids = [str(item) for item in payload.get("l1_atom_ids", []) if str(item).strip()]
        if l1_atom_ids:
            lines.append(f"**L1 atoms**: {', '.join(l1_atom_ids)}")
        evidence_summary = MemoryGuidanceService._format_evidence_summary(scenario.evidence_refs)
        if evidence_summary:
            lines.append(f"**L0 evidence refs**: {evidence_summary}")
        if include_metadata:
            lines.append(f"**状态**: {scenario.status}")
            lines.append(f"**更新时间**: {scenario.updated_at.isoformat()}")
        lines.append("")

    @staticmethod
    def _append_l1_atom_guidance(
        lines: list[str],
        atom: MemoryRetrievalResult,
        *,
        idx: int,
        include_metadata: bool,
    ) -> None:
        payload = atom.payload
        lines.append(f"### 历史原子观测 {idx}: {payload.get('atom_type') or atom.memory_type}")
        lines.append("")
        claim = payload.get("claim") or atom.summary
        lines.append(f"**观察结论**: {claim}")
        for label, key in (
            ("根因", "root_cause"),
            ("检查项", "check_name"),
            ("修复动作", "remediation"),
        ):
            value = payload.get(key)
            if value:
                lines.append(f"**{label}**: {value}")
        evidence_summary = MemoryGuidanceService._format_evidence_summary(atom.evidence_refs)
        if evidence_summary:
            lines.append(f"**L0 evidence refs**: {evidence_summary}")
        if include_metadata:
            lines.append(f"**状态**: {atom.status}")
            lines.append(f"**更新时间**: {atom.updated_at.isoformat()}")
        lines.append("")

    @staticmethod
    def _append_text_list(
        lines: list[str],
        title: str,
        items: Any,
        *,
        numbered: bool = False,
    ) -> None:
        normalized = [str(item).strip() for item in items or [] if str(item).strip()]
        if not normalized:
            return
        lines.append(f"**{title}**:")
        for index, item in enumerate(normalized, 1):
            prefix = f"{index}." if numbered else "-"
            lines.append(f"{prefix} {item}")
        lines.append("")

    @staticmethod
    def _format_evidence_summary(evidence_refs: List[Dict[str, Any]]) -> str:
        """格式化 evidence_refs 为简短摘要"""
        if not evidence_refs:
            return "manual entry"

        parts = []
        for ref in evidence_refs:
            if "evidence_id" in ref:
                parts.append(str(ref["evidence_id"]))
            if "session_id" in ref:
                parts.append(f"session {ref['session_id'][:8]}...")
            if "source_type" in ref:
                parts.append(ref["source_type"])
            if "message_refs" in ref and ref["message_refs"]:
                parts.append(f"{len(ref['message_refs'])} messages")
            if "state_refs" in ref and ref["state_refs"]:
                parts.append(f"{len(ref['state_refs'])} state fields")

        return ", ".join(parts) if parts else "manual entry"

    @staticmethod
    def format_alert_pattern_guidance(memory: MemoryRecord) -> str:
        """格式化 alert_pattern 为专门的 guidance"""
        if memory.memory_type != MemoryType.ALERT_PATTERN:
            return ""

        payload = memory.payload
        if not payload or not isinstance(payload, AlertPatternPayload):
            return ""

        lines = [
            f"**告警模式**: {payload.alert_name}",
            f"**服务**: {payload.service or 'N/A'}",
            f"**根因假设**: {payload.root_cause}",
        ]

        if payload.fix:
            lines.append(f"**处理方案**: {payload.fix}")

        lines.append(f"**更新时间**: {memory.updated_at.isoformat()}")
        lines.append("")
        lines.append(
            "注意: 这是历史根因假设。若当前日志、指标、配置或部署记录显示该问题已修复或不再成立，必须优先采用当前观测，并说明该记忆可能过时；若没有冲突证据，可把它作为排查假设并执行 fresh checks。"
        )

        return "\n".join(lines)

    @staticmethod
    def format_plan_template_guidance(memory: MemoryRecord) -> str:
        """格式化 plan_template 为专门的 guidance"""
        if memory.memory_type != MemoryType.PLAN_TEMPLATE:
            return ""

        payload = memory.payload
        if not payload or not isinstance(payload, PlanTemplatePayload):
            return ""

        lines = [
            f"**计划模板**: {payload.alert_type}",
            "",
            "**建议步骤**:",
        ]

        for idx, step in enumerate(payload.plan_steps, 1):
            lines.append(f"{idx}. {step}")

        lines.append("")
        lines.append(f"**更新时间**: {memory.updated_at.isoformat()}")
        lines.append("")
        lines.append("注意: 这是历史成功计划，可根据新证据调整。")

        return "\n".join(lines)

    @staticmethod
    def combine_memory_and_document_context(
        memory_guidance: str,
        document_context: str
    ) -> str:
        """
        合并 memory guidance 和 document context

        Args:
            memory_guidance: 格式化的 memory guidance
            document_context: 现有的文档上下文

        Returns:
            合并后的 experience_context
        """
        parts = []

        if memory_guidance:
            parts.append(memory_guidance)

        if document_context:
            parts.append(document_context)

        return "\n".join(parts) if parts else ""
