# S5-P1 RAGAS Testset Generator 使用指南

## 快速开始

### 1. 安装依赖

```bash
uv pip install ragas langchain-community langchain-text-splitters langchain-openai
```

### 2. 设置 OpenAI API Key

```bash
export OPENAI_API_KEY="sk-..."
```

### 3. 生成候选测试集

```bash
uv run python -m evals.knowledge_base.s5_p1_ragas_testset_generator \
  --output evals/knowledge_base/evalsets/s5p1_ragas_candidates_40q.jsonl \
  --target-size 40 \
  --kb-ids process_digital_dept craft_dept \
  --use-openai
```

### 4. 人工审核

1. 打开生成的 `s5p1_ragas_candidates_40q.jsonl`
2. 对每个样本审核：
   - ✅ Query 质量和相关性
   - ✅ Reference answer 准确性
   - ✅ 填充 `expected_doc_ids`
   - ✅ 提取 `must_include_facts`
   - ✅ 填充 `must_not_include_claims`
   - ✅ 填充 `required_citations`
3. 筛选出 20-30 个高质量样本
4. 保存为 `department_rag_answer_pilot_20q.jsonl`

---

## 生成参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--output` | `s5p1_ragas_candidates_40q.jsonl` | 输出文件路径 |
| `--target-size` | 40 | 生成样本数量 |
| `--kb-ids` | `process_digital_dept` | 从哪些 KB 生成 |
| `--use-openai` | - | 使用 OpenAI GPT-4 生成 |

---

## RAGAS 分布策略

| Evolution Type | 占比 | 说明 |
|---|---:|---|
| **Simple** | 50% | 简单事实查询，单文档即可回答 |
| **Reasoning** | 30% | 需要推理，可能跨 chunk |
| **Multi-context** | 20% | 需要多文档信息组合 |

---

## 输出格式

每个生成的样本包含：

```jsonl
{
  "sample_id": "S5P1-R-001",
  "layer": "answer",
  "query": "CPU throttling 高时应该怎么处理？",
  "allowed_kb_ids": ["process_digital_dept"],
  "expected_doc_ids": [],  // ⚠️ 需人工填充
  "reference_answer": "CPU throttling 告警通常是纯信息性的...",
  "must_include_facts": ["[EXTRACT_FROM_REFERENCE_ANSWER]"],  // ⚠️ 需人工填充
  "must_not_include_claims": ["[HUMAN_REVIEW_REQUIRED]"],  // ⚠️ 需人工填充
  "required_citations": [],  // ⚠️ 需人工填充
  "context_policy": "retrieved_context_only",
  "judge_policy": "ragas_shadow",
  "retrieval_mode": "dense_only",
  "top_k": 3,
  "ragas_generated": true,
  "ragas_evolution_type": "simple",
  "human_review_status": "pending"
}
```

---

## 人工审核 Checklist

### 每个样本必须验证：

#### 1. Query 质量
- [ ] Query 语义清晰
- [ ] 是真实用户可能问的问题
- [ ] 不是过于模糊或过于具体
- [ ] 符合 SRE/oncall 领域

#### 2. Expected Doc
- [ ] 填充 `expected_doc_ids`：哪个文档应该回答这个问题
- [ ] 验证该文档确实包含答案

#### 3. Reference Answer
- [ ] 审核 RAGAS 生成的 `reference_answer`
- [ ] 修正错误或不完整的答案
- [ ] 确保答案基于文档内容，不是 LLM 编造

#### 4. Must Include Facts
- [ ] 从 `reference_answer` 提取 2-4 个关键事实点
- [ ] 每个事实点是独立可验证的
- [ ] 示例：`["CPU throttling 是限流", "Impact 是 informative", "通常可以跳过"]`

#### 5. Must Not Include Claims
- [ ] 列出容易编造的内容
- [ ] 示例：`["具体阈值（如果文档未提及）", "其他部门 runbook", "未提及的工具"]`

#### 6. Required Citations
- [ ] 列出必须引用的文档/section
- [ ] 示例：`[{"doc_id": "doc_xxx", "source_file": "CPUThrottlingHigh.md", "expected_in_answer": "CPUThrottlingHigh"}]`

### 质量筛选标准

**保留**（20-30 个高质量样本）：
- ✅ Query 清晰、真实
- ✅ Reference answer 准确、完整
- ✅ 单文档或少量文档即可回答
- ✅ 覆盖 Markdown + PDF
- ✅ 覆盖不同 evolution types

**丢弃**：
- ❌ Query 过于模糊或不自然
- ❌ Reference answer 明显错误
- ❌ 需要文档外的知识
- ❌ 过于简单（一个词就能回答）
- ❌ 过于复杂（需要多步推理）

---

## 示例：审核前后对比

### 审核前（RAGAS 生成）

```json
{
  "sample_id": "S5P1-R-012",
  "query": "What should I do when CPU throttling is high?",
  "expected_doc_ids": [],
  "reference_answer": "Check if it's affecting performance...",
  "must_include_facts": ["[EXTRACT_FROM_REFERENCE_ANSWER]"],
  "must_not_include_claims": ["[HUMAN_REVIEW_REQUIRED]"],
  "required_citations": []
}
```

### 审核后（人工修正）

```json
{
  "sample_id": "S5P1-R-012",
  "query": "CPU throttling 高时应该怎么处理？",
  "expected_doc_ids": ["doc_5bf080aa-1fda-5e71-8563-4c55c15d75de"],
  "reference_answer": "CPUThrottlingHigh 告警通常是纯信息性的，除非有其他应用问题，否则可以跳过。应检查 CPU requests 是否合理。",
  "must_include_facts": [
    "告警是纯信息性的（informative）",
    "没有其他问题时可以跳过",
    "应检查 requests 设置"
  ],
  "must_not_include_claims": [
    "具体的 CPU 使用率阈值",
    "应该增加 limit",
    "其他部门的处理流程"
  ],
  "required_citations": [{
    "doc_id": "doc_5bf080aa-1fda-5e71-8563-4c55c15d75de",
    "source_file": "CPUThrottlingHigh.md",
    "expected_in_answer": "CPUThrottlingHigh.md"
  }],
  "human_review_status": "approved"
}
```

---

## 常见问题

### Q: RAGAS 生成的 query 质量如何？
A: 通常 60-70% 可用，需要人工筛选和修正。Simple 类型质量最高，Multi-context 类型质量较低。

### Q: 需要审核多少样本？
A: 生成 40 个，筛选出 20-30 个高质量样本用于 pilot。

### Q: 如果 RAGAS 生成的答案错误怎么办？
A: 直接修改 `reference_answer`，基于实际文档内容重写。

### Q: 可以不用 OpenAI 吗？
A: 可以。修改脚本使用本地 LLM（如 Ollama）或 Anthropic Claude API。

---

## 下一步

审核完成后：

1. 保存最终 evalset：`department_rag_answer_pilot_20q.jsonl`
2. 运行 answer baseline：`run_department_rag_answer_eval.py`
3. 查看报告：检查硬门禁和观察指标
4. 失败分流：根据 S5 设计文档的规则分流
