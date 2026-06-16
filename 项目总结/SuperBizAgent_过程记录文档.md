# 过程记录文档 — SuperBizAgent

> 记录在项目开发过程中遇到的所有问题和解决方案。
> 时间跨度：2026年3月 - 2026年5月

---

## 问题 1：Milvus content 字段长度限制导致长文档索引失败

- **现象**：
  - 在 P6 corpus probe 阶段，尝试索引长文档时报错
  - 错误信息：`pymilvus.exceptions.MilvusException: <MilvusException: (code=1, message=invalid varchar length: xxx > 8000)>`
  - 具体场景：索引 H3C 设备手册的某些章节时，单个 chunk 的 UTF-8 编码超过 8000 字节

- **原因**：
  - Milvus collection 的 `content` 字段定义为 `varchar(8000)`，限制了单个字段最多 8000 字符
  - `ChunkPolicyService` 在分块时没有考虑 Milvus schema 的硬限制
  - MinerU 解析产生的某些 atomic chunk（如大型表格、长段落）可能超过这个限制

- **解决过程**：
  1. **首先尝试**：修改 Milvus collection schema，将 `varchar(8000)` 改为 `varchar(16000)`
     - **结果**：需要重建 collection，会丢失已有数据，且治标不治本（未来可能还会超）
  
  2. **然后尝试**：在 `DocumentSplitterService` 中强制切分超长 chunk
     - **结果**：会破坏 atomic chunk 的语义完整性（如表格被切断）
  
  3. **最终解决**：在 `ChunkPolicyService` 中实现 atomic hardcap
     - 对超长 chunk 进行智能截断，确保 UTF-8 编码后 ≤ 6000 bytes（留 25% 安全边界）
     - 截断时保留前 N 个字符，确保不会在 UTF-8 多字节字符中间切断
     - 在 metadata 中记录 `truncated: true` 和 `original_length`，保留可追溯性
     - 代码位置：`app/services/chunk_policy_service.py` 的 `_apply_atomic_hardcap()` 方法

- **参考来源**：
  - Milvus 官方文档：[Schema Design](https://milvus.io/docs/schema.md)
  - 项目内部文档：`docs/chunk_policy_atomic_hardcap_design.md`
  - Python UTF-8 编码处理：`str.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')`

- **经验教训**：
  - 在设计数据模型时，要提前考虑下游存储的硬限制
  - 对于可能超长的字段，要在写入前做防御性检查
  - 通过 P5.f3 评估验证了 hardcap 不影响检索质量（retrieval byte-level drift=0）
  - 下次遇到类似问题，优先考虑"在写入前处理"而不是"修改 schema"

---

## 问题 2：DashScope embedding API 批量调用返回 400 错误

- **现象**：
  - 在向量化文档时，调用 DashScope `text-embedding-v4` API 报错
  - 错误信息：`{"code": "InvalidParameter", "message": "batch size is invalid"}`
  - 具体场景：一次性传入 50+ 条文本进行批量 embedding，API 拒绝请求
  - 导致 eval pipeline 无法正常运行，所有评估脚本都卡在向量化阶段

- **原因**：
  - DashScope API 对批量请求有隐式限制，单次请求不能超过一定数量（具体限制未在文档中明确说明）
  - `VectorEmbeddingService.embed_documents()` 方法直接将所有文本一次性发送给 API
  - 没有实现分批处理逻辑

- **解决过程**：
  1. **首先尝试**：查看 DashScope 官方文档，寻找批量限制说明
     - **结果**：文档中没有明确说明 batch size 限制，只提到"支持批量调用"
  
  2. **然后尝试**：通过二分法测试，逐步减少 batch size
     - 测试 50 条 → 失败
     - 测试 25 条 → 失败
     - 测试 10 条 → 成功
     - **结果**：确定单次请求最多 10 条文本
  
  3. **最终解决**：在 `VectorEmbeddingService` 中实现分批处理
     ```python
     def embed_documents(self, texts: List[str]) -> List[List[float]]:
         BATCH_SIZE = 10
         all_embeddings = []
         for i in range(0, len(texts), BATCH_SIZE):
             batch = texts[i:i+BATCH_SIZE]
             response = self.client.embed(batch)
             all_embeddings.extend(response.embeddings)
         return all_embeddings
     ```
     - 代码位置：`app/services/vector_embedding_service.py`
     - 添加重试机制，提高稳定性

- **参考来源**：
  - DashScope 官方文档：[文本向量 API](https://dashscope.aliyun.com/docs/text-embedding)
  - 通过实际测试确定的 batch size 限制

- **经验教训**：
  - 调用第三方 API 时，不能假设"支持批量"就意味着"无限制批量"
  - 要做好防御性编程，实现分批处理和重试机制
  - 如果 API 文档不清晰，通过二分法测试是快速定位限制的有效方法
  - 这个修复是 eval pipeline 能够正常运行的前提条件

---

## 问题 3：WeKnora Go 代码无法直接接入 Python 主链路

- **现象**：
  - WeKnora 项目有完整的知识库层设计（DocumentRecord、ChunkRecord、ParserRegistry 等）
  - 但 WeKnora 是 Go 语言实现，无法直接在 Python 项目中使用
  - 尝试通过 gRPC 或 HTTP 接口调用 WeKnora 服务，但会引入额外的网络开销和部署复杂度

- **原因**：
  - 语言栈不同：WeKnora 是 Go，SuperBizAgent 是 Python
  - 项目定位不同：WeKnora 是独立的知识平台，SuperBizAgent 是应用层项目
  - 当前阶段的目标是"补知识库层"，而不是"整体迁移到 WeKnora 平台"

- **解决过程**：
  1. **首先尝试**：通过 HTTP API 调用 WeKnora 服务
     - **结果**：需要部署独立的 WeKnora 服务，增加运维复杂度；网络调用增加延迟
  
  2. **然后尝试**：寻找 Go 到 Python 的代码转换工具
     - **结果**：没有成熟的自动转换工具，手动转换工作量巨大
  
  3. **最终解决**：采用"按字段语义复制 + 最小 Python 化"策略
     - 步骤 1：对 WeKnora 的关键文件做只读复核（R0 review）
       - 复核文件：`internal/types/knowledgebase.go`、`internal/types/knowledge.go`、`internal/types/chunk.go`
       - 产出文档：`docs/weknora_r0_reuse_review.md`
     
     - 步骤 2：在 `app/models/knowledge.py` 中重建领域对象
       - 保持字段语义一致（如 `doc_id`、`kb_id`、`parser_engine`、`status`）
       - 使用 Python 的 Pydantic 替代 Go 的 struct
       - 保持接口语义一致，但实现语言不同
     
     - 步骤 3：逐步迁移核心逻辑
       - ParserEngineRouter：路由逻辑从 Go 翻译为 Python
       - ChunkPolicyService：分块策略从 Go 翻译为 Python
       - 保留 WeKnora 的设计思想，但用 Python 重新实现

- **参考来源**：
  - WeKnora 项目源码：`/Users/cici/oncall agent/WeKnora`
  - 项目内部文档：`docs/weknora_r0_reuse_review.md`、`docs/technical_fusion_decision_manual.md`

- **经验教训**：
  - 跨语言复用代码时，"复用设计"比"复用代码"更重要
  - 不要试图强行对接不同语言栈的项目，除非有明确的架构收益
  - 通过只读复核（R0 review）可以快速理解外部项目的设计思想
  - "复制成熟实现 + 最小修改"是一种务实的复用策略

---

## 问题 4：混合检索的 BM25 和向量检索分数量纲不一致

- **现象**：
  - 实现混合检索时，BM25 返回的分数范围是 0-10+，向量检索返回的分数范围是 0-1
  - 直接相加会导致 BM25 分数占主导，向量检索几乎没有贡献
  - 尝试归一化后相加，但不同查询的分数分布差异很大，归一化效果不稳定

- **原因**：
  - BM25 是基于词频和文档频率的统计模型，分数没有上界
  - 向量检索是基于余弦相似度，分数范围固定在 [-1, 1]（实际使用时归一化到 [0, 1]）
  - 两种检索方式的分数语义完全不同，无法直接比较

- **解决过程**：
  1. **首先尝试**：Min-Max 归一化后相加
     ```python
     def normalize(scores):
         min_s, max_s = min(scores), max(scores)
         return [(s - min_s) / (max_s - min_s) for s in scores]
     ```
     - **结果**：对于分数分布极端的查询（如只有一个高分结果），归一化后失真严重
  
  2. **然后尝试**：Z-score 标准化后相加
     - **结果**：需要假设分数服从正态分布，但实际分布往往不是正态的
  
  3. **最终解决**：采用 RRF (Reciprocal Rank Fusion) 算法
     - RRF 只关注排序位置，不关注具体分数
     - 公式：`score = 1 / (k + rank + 1)`，其中 k=60（经验值）
     - 对 BM25 和向量检索的结果分别计算 RRF 分数，然后相加
     ```python
     def rrf_fusion(dense_results, sparse_results, k=60):
         scores = {}
         for rank, result in enumerate(dense_results):
             scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (k + rank + 1)
         for rank, result in enumerate(sparse_results):
             scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (k + rank + 1)
         return sorted(scores.items(), key=lambda x: x[1], reverse=True)
     ```
     - 代码位置：`app/services/hybrid_search_service.py`

- **参考来源**：
  - 论文：[Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
  - LangChain 官方文档：[Ensemble Retriever](https://python.langchain.com/docs/modules/data_connection/retrievers/ensemble)

- **经验教训**：
  - 融合不同来源的分数时，基于排序的方法（如 RRF）比基于分数的方法更稳定
  - RRF 的 k 参数通常设为 60，这是论文中的经验值，实际使用中可以根据评估结果调优
  - 通过离线评估验证了 hybrid 模式相比 dense_only 有提升

---

## 问题 5：P5 文档级去重的候选池大小设计

- **现象**：
  - 实现文档级去重时，需要先召回一个候选池，然后按文档聚合
  - 如果候选池太小（如 top_k=3），可能只覆盖 1-2 个文档，去重没有意义
  - 如果候选池太大（如 top_k=100），计算开销增加，且可能引入低质量结果

- **原因**：
  - 文档级去重的目标是"从多个文档中各选一些代表性 chunk"
  - 需要候选池足够大，才能覆盖足够多的文档
  - 但候选池不能无限大，否则会影响性能和质量

- **解决过程**：
  1. **首先尝试**：固定候选池大小为 top_k * 2
     - **结果**：在某些查询中，候选池只覆盖 1-2 个文档，去重效果不明显
  
  2. **然后尝试**：固定候选池大小为 top_k * 10
     - **结果**：候选池过大，引入了很多低相关性的结果，反而降低了质量
  
  3. **最终解决**：引入 `doc_oversample_factor` 参数（默认 4）
     - 候选池大小 = `top_k * doc_oversample_factor`
     - 通过 P5.f1 评估验证 factor=4 足够（0/6 样本饱和到单文档）
     - 如果某个查询的候选池中所有结果都来自同一文档，说明 factor 不够，需要增大
     - 代码位置：`app/services/retrieval_service.py` 的 `_retrieve_with_doc_aggregation()` 方法

- **参考来源**：
  - 项目内部文档：`docs/p5_doc_level_dedup_design.md`
  - 评估报告：`evals/rag_retrieval/reports/p5_long_doc_eval_*.md`

- **经验教训**：
  - 对于需要调优的参数，要通过离线评估找到合适的默认值
  - 要设计"饱和检测"机制，判断参数是否足够（如 0/6 样本饱和）
  - 参数设计要考虑"最坏情况"（如所有候选都来自同一文档）

---

## 问题 6：异步文档处理 Worker 的状态同步问题

- **现象**：
  - PDF/DOCX/XLSX 文档通过 RQ 队列异步处理
  - 用户上传文档后，立即查询文档状态，有时会看到 `uploaded` 而不是 `parse_pending`
  - 导致用户误以为文档没有被处理

- **原因**：
  - 文档上传后，先写入数据库（状态为 `uploaded`）
  - 然后才将任务投递到 RQ 队列
  - 如果队列投递成功，状态才更新为 `parse_pending`
  - 在这两步之间存在时间窗口，用户可能看到中间状态

- **解决过程**：
  1. **首先尝试**：在投递队列前就将状态设为 `parse_pending`
     - **结果**：如果队列投递失败，状态会不一致（显示 pending 但实际没有任务）
  
  2. **然后尝试**：使用数据库事务，确保状态更新和队列投递原子性
     - **结果**：RQ 队列不支持事务，无法实现真正的原子性
  
  3. **最终解决**：采用"先投递，后更新"的顺序，并添加状态确认机制
     - 步骤 1：创建文档记录，状态为 `uploaded`
     - 步骤 2：投递 RQ 任务
     - 步骤 3：如果投递成功，更新状态为 `parse_pending` + 记录 `processing_job_id`
     - 步骤 4：在 API 响应中返回最新状态
     - 添加 `status_source`、`status_evidence`、`status_confirmed_at` 字段，提高可追溯性
     - 代码位置：`app/services/document_processing_queue.py`

- **参考来源**：
  - RQ 官方文档：[Job Status](https://python-rq.org/docs/jobs/)
  - 项目内部文档：`docs/p1_p2_execution_checklist.md`

- **经验教训**：
  - 异步任务的状态管理要考虑"投递失败"的情况
  - 不能假设队列投递一定成功，要有失败处理逻辑
  - 通过 `status_source` 和 `status_evidence` 可以提高状态变更的可追溯性
  - 用户查询状态时，要返回最新的确认状态，而不是中间状态

---

## 总结

在 SuperBizAgent 项目的开发过程中，遇到的主要问题可以归为以下几类：

1. **存储限制问题**（问题 1）：需要在写入前做防御性检查
2. **第三方 API 限制问题**（问题 2）：不能假设 API 无限制，要实现分批和重试
3. **跨语言复用问题**（问题 3）：复用设计比复用代码更重要
4. **算法融合问题**（问题 4）：基于排序的方法比基于分数的方法更稳定
5. **参数调优问题**（问题 5）：通过离线评估找到合适的默认值
6. **异步状态同步问题**（问题 6）：要考虑失败情况，提高可追溯性

这些问题的解决过程体现了"先理解根因，再选择方案，最后通过评估验证"的工程化思维。

---

**文档完成日期**：2026-05-26
**作者**：cici