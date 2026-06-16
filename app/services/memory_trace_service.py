"""
Memory Trace Service: 记录 memory shadow/active 观测结果

职责:
- 生成 memory_observation trace dict
- 保存 shadow mode 全文到 trace 文件
- 提供简洁的日志摘要格式
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from app.services.memory_retrieval_service import MemoryRetrievalResponse
from app.models.memory_mode import MemoryMode


class MemoryTraceService:
    """Memory trace 服务"""

    def __init__(self, trace_dir: str = "traces/memory"):
        """
        初始化 trace 服务

        Args:
            trace_dir: trace 文件存储目录
        """
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def create_observation(
        self,
        mode: MemoryMode,
        memory_response: MemoryRetrievalResponse,
        memory_guidance_text: str,
        query: str,
        owner_id: str
    ) -> Dict[str, Any]:
        """
        创建 memory observation trace

        Args:
            mode: memory 模式
            memory_response: memory 检索响应
            memory_guidance_text: 格式化后的 guidance 文本
            query: 查询文本
            owner_id: owner ID

        Returns:
            observation dict
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        trace_id = f"mem_trace_{timestamp}"

        observation = {
            "mode": mode.value,
            "trace_id": trace_id,
            "query": query,
            "owner_id": owner_id,
            "memory_ids": [m.memory_id for m in memory_response.memory_results],
            "namespaces": list(set(m.namespace for m in memory_response.memory_results)),
            "memory_types": list(set(m.memory_type for m in memory_response.memory_results)),
            "hit_count": len(memory_response.memory_results),
            "would_inject": (mode == MemoryMode.ACTIVE),
            "timestamp": datetime.now().isoformat(),
            "retrieval_trace": memory_response.trace,
        }

        # Shadow mode 保存全文
        if mode == MemoryMode.SHADOW:
            trace_file_path = self.trace_dir / f"{trace_id}.txt"
            self._save_shadow_trace(
                trace_file_path,
                observation,
                memory_guidance_text
            )
            observation["full_text_path"] = str(trace_file_path)

        return observation

    def _save_shadow_trace(
        self,
        file_path: Path,
        observation: Dict[str, Any],
        memory_guidance_text: str
    ):
        """
        保存 shadow trace 到文件

        Args:
            file_path: 文件路径
            observation: observation dict
            memory_guidance_text: 完整 guidance 文本
        """
        success = False
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"# Memory Shadow Trace\n\n")
                f.write(f"**Trace ID**: {observation['trace_id']}\n")
                f.write(f"**Mode**: {observation['mode']}\n")
                f.write(f"**Owner**: {observation['owner_id']}\n")
                f.write(f"**Query**: {observation['query']}\n")
                f.write(f"**Hit Count**: {observation['hit_count']}\n")
                f.write(f"**Memory IDs**: {', '.join(observation['memory_ids'])}\n")
                f.write(f"**Namespaces**: {', '.join(observation['namespaces'])}\n")
                f.write(f"**Memory Types**: {', '.join(observation['memory_types'])}\n")
                f.write(f"**Would Inject**: {observation['would_inject']}\n")
                f.write(f"**Timestamp**: {observation['timestamp']}\n\n")
                f.write(f"---\n\n")
                f.write(f"## Retrieval Trace\n\n")
                f.write(f"```json\n{json.dumps(observation['retrieval_trace'], indent=2, ensure_ascii=False)}\n```\n\n")
                f.write(f"---\n\n")
                f.write(f"## Full Guidance Text\n\n")
                f.write(memory_guidance_text)
            success = True
        finally:
            # 记录指标
            from app.services.shadow_mode_metrics import shadow_metrics
            shadow_metrics.record_trace_write(success=success)

    @staticmethod
    def format_log_summary(observation: Dict[str, Any]) -> str:
        """
        格式化日志摘要（不包含全文）

        Args:
            observation: observation dict

        Returns:
            日志摘要字符串
        """
        memory_ids_preview = observation['memory_ids'][:3]
        if len(observation['memory_ids']) > 3:
            memory_ids_preview.append(f"... +{len(observation['memory_ids']) - 3} more")

        return (
            f"[MEMORY-{observation['mode'].upper()}] "
            f"hit={observation['hit_count']}, "
            f"ids={memory_ids_preview}, "
            f"inject={observation['would_inject']}, "
            f"trace_id={observation['trace_id']}"
        )
