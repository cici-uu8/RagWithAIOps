"""
Tests for MemoryGuidanceService

验证:
- memory guidance 格式化包含必需标签
- memory guidance 暴露 updated_at / evidence_refs / status
- alert_pattern / plan_template 专门格式化
- memory + document context 合并
"""

import unittest
from datetime import datetime, timezone

from app.models.memory import MemoryRecord, MemoryType
from app.services.memory_retrieval_service import MemoryRetrievalResponse, MemoryRetrievalResult
from app.services.memory_guidance_service import MemoryGuidanceService


class TestMemoryGuidanceService(unittest.TestCase):
    """Test MemoryGuidanceService"""

    def test_format_memory_guidance_includes_required_labels(self):
        """memory guidance 必须包含 guidance 标签和推翻规则"""
        memory = MemoryRecord(
            memory_id="mem_test_001",
            schema_version=1,
            owner_id="default",
            namespace="memory://oncall/alert-patterns",
            memory_type=MemoryType.ALERT_PATTERN,
            content="CPUHigh alert pattern",
            summary="CPU high pattern",
            payload={
                "alert_name": "CPUHigh",
                "service": "service-a",
                "root_cause": "memory leak",
                "fix": "restart service",
                "signal_keys": [],
                "metric_patterns": [],
                "log_patterns": [],
                "evidence_refs": []
            },
            source="test",
            evidence={"session_id": "sess_001", "source_type": "aiops"},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        result_item = MemoryRetrievalResult(
            memory_id=memory.memory_id,
            owner_id=memory.owner_id,
            namespace=memory.namespace,
            memory_type=memory.memory_type,
            status=memory.status,
            content=memory.content,
            summary=memory.summary,
            score=0.95,
            matched_terms=["CPUHigh"],
            evidence_refs=[{"session_id": "sess_001", "source_type": "aiops"}],
            payload={"alert_name": "CPUHigh", "service": "service-a", "root_cause": "memory leak"},
            source=memory.source,
            tags=[],
            updated_at=memory.updated_at
        )

        response = MemoryRetrievalResponse(
            query="CPUHigh",
            owner_id="default",
            namespaces=["memory://oncall/alert-patterns"],
            memory_types=[MemoryType.ALERT_PATTERN],
            memory_results=[result_item],
            empty_message="",
            trace={"lexical_hits": 1}
        )

        guidance = MemoryGuidanceService.format_memory_guidance(response)

        # 必须包含 guidance 标签
        self.assertIn("运行时记忆指导", guidance)
        self.assertIn("不是文档来源", guidance)
        self.assertIn("不能作为文档 citation", guidance)

        # 必须包含推翻规则
        self.assertIn("新工具证据与旧记忆冲突", guidance)
        self.assertIn("以新证据为准", guidance)
        self.assertIn("当前工具观测", guidance)
        self.assertIn("如果当前观测明确反驳", guidance)
        self.assertIn("如果当前观测不充分", guidance)

    def test_format_memory_guidance_exposes_metadata(self):
        """memory guidance 必须暴露 updated_at / evidence_refs / status"""
        memory = MemoryRecord(
            memory_id="mem_test_002",
            schema_version=1,
            owner_id="default",
            namespace="memory://oncall/plan-templates",
            memory_type=MemoryType.PLAN_TEMPLATE,
            content="Disk alert plan",
            summary="Disk alert investigation",
            payload={
                "alert_type": "DiskHigh",
                "plan_steps": ["check mount", "check recent deploy"],
                "tool_hints": [],
                "success_criteria": [],
                "stop_conditions": [],
                "evidence_refs": []
            },
            source="test",
            evidence={
                "session_id": "sess_002",
                "source_type": "aiops",
                "state_refs": ["plan_steps", "response"]
            },
            status="active",
            created_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 24, tzinfo=timezone.utc)
        )

        result_item = MemoryRetrievalResult(
            memory_id=memory.memory_id,
            owner_id=memory.owner_id,
            namespace=memory.namespace,
            memory_type=memory.memory_type,
            status=memory.status,
            content=memory.content,
            summary=memory.summary,
            score=0.90,
            matched_terms=["DiskHigh"],
            evidence_refs=[{
                "session_id": "sess_002",
                "source_type": "aiops",
                "state_refs": ["plan_steps", "response"]
            }],
            payload={"alert_type": "DiskHigh", "plan_steps": ["check mount", "check recent deploy"]},
            source=memory.source,
            tags=[],
            updated_at=memory.updated_at
        )

        response = MemoryRetrievalResponse(
            query="DiskHigh",
            owner_id="default",
            namespaces=["memory://oncall/plan-templates"],
            memory_types=[MemoryType.PLAN_TEMPLATE],
            memory_results=[result_item],
            empty_message="",
            trace={}
        )

        guidance = MemoryGuidanceService.format_memory_guidance(
            response, include_metadata=True
        )

        # 必须暴露 status
        self.assertIn("状态", guidance)
        self.assertIn("active", guidance)

        # 必须暴露 updated_at
        self.assertIn("更新时间", guidance)
        self.assertIn("2026-05-24", guidance)

        # 必须暴露 evidence_refs
        self.assertIn("证据来源", guidance)
        self.assertIn("sess_002", guidance)
        self.assertIn("state fields", guidance)

    def test_format_alert_pattern_guidance(self):
        """alert_pattern 专门格式化必须包含根因假设和 fresh checks 提醒"""
        memory = MemoryRecord(
            memory_id="mem_alert_001",
            schema_version=1,
            owner_id="default",
            namespace="memory://oncall/alert-patterns",
            memory_type=MemoryType.ALERT_PATTERN,
            content="CPUHigh pattern",
            summary="CPU high",
            payload={
                "alert_name": "CPUHigh",
                "service": "service-a",
                "root_cause": "memory leak in worker process",
                "fix": "restart worker, check heap dump",
                "signal_keys": [],
                "metric_patterns": [],
                "log_patterns": [],
                "evidence_refs": []
            },
            source="test",
            evidence={"session_id": "sess_003"},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        guidance = MemoryGuidanceService.format_alert_pattern_guidance(memory)

        # 必须包含根因假设
        self.assertIn("根因假设", guidance)
        self.assertIn("memory leak in worker process", guidance)

        # 必须包含处理方案
        self.assertIn("处理方案", guidance)
        self.assertIn("restart worker", guidance)

        # 必须提醒 fresh checks
        self.assertIn("历史根因假设", guidance)
        self.assertIn("fresh checks", guidance)
        self.assertIn("当前日志", guidance)
        self.assertIn("必须优先采用当前观测", guidance)
        self.assertIn("若没有冲突证据", guidance)

    def test_format_plan_template_guidance(self):
        """plan_template 专门格式化必须包含建议步骤和可调整提醒"""
        memory = MemoryRecord(
            memory_id="mem_plan_001",
            schema_version=1,
            owner_id="default",
            namespace="memory://oncall/plan-templates",
            memory_type=MemoryType.PLAN_TEMPLATE,
            content="Disk alert plan",
            summary="Disk investigation",
            payload={
                "alert_type": "DiskHigh",
                "plan_steps": [
                    "check mount points",
                    "check recent deploy",
                    "check log rotation"
                ],
                "tool_hints": [],
                "success_criteria": [],
                "stop_conditions": [],
                "evidence_refs": []
            },
            source="test",
            evidence={"session_id": "sess_004"},
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        guidance = MemoryGuidanceService.format_plan_template_guidance(memory)

        # 必须包含建议步骤
        self.assertIn("建议步骤", guidance)
        self.assertIn("check mount points", guidance)
        self.assertIn("check recent deploy", guidance)
        self.assertIn("check log rotation", guidance)

        # 必须提醒可调整
        self.assertIn("历史成功计划", guidance)
        self.assertIn("根据新证据调整", guidance)

    def test_combine_memory_and_document_context(self):
        """memory guidance 和 document context 必须能合并"""
        memory_guidance = "## 运行时记忆指导\n\nmemory content"
        document_context = "## 相关经验文档\n\ndocument content"

        combined = MemoryGuidanceService.combine_memory_and_document_context(
            memory_guidance, document_context
        )

        # 必须包含两部分
        self.assertIn("运行时记忆指导", combined)
        self.assertIn("相关经验文档", combined)

        # memory 应在 document 之前
        memory_pos = combined.find("运行时记忆指导")
        doc_pos = combined.find("相关经验文档")
        self.assertLess(memory_pos, doc_pos)

    def test_empty_memory_result_returns_empty_guidance(self):
        """空 memory result 应返回空 guidance"""
        response = MemoryRetrievalResponse(
            query="unknown",
            owner_id="default",
            namespaces=[],
            memory_types=[],
            memory_results=[],
            empty_message="no memory found",
            trace={}
        )

        guidance = MemoryGuidanceService.format_memory_guidance(response)
        self.assertEqual(guidance, "")

    def test_combine_with_empty_memory_returns_document_only(self):
        """memory 为空时应只返回 document context"""
        memory_guidance = ""
        document_context = "## 相关经验文档\n\ndocument content"

        combined = MemoryGuidanceService.combine_memory_and_document_context(
            memory_guidance, document_context
        )

        self.assertEqual(combined, document_context)

    def test_combine_with_empty_document_returns_memory_only(self):
        """document 为空时应只返回 memory guidance"""
        memory_guidance = "## 运行时记忆指导\n\nmemory content"
        document_context = ""

        combined = MemoryGuidanceService.combine_memory_and_document_context(
            memory_guidance, document_context
        )

        self.assertEqual(combined, memory_guidance)


if __name__ == "__main__":
    unittest.main()
