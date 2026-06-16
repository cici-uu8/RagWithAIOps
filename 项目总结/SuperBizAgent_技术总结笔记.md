# 技术总结笔记 — SuperBizAgent

> 完成日期：2026-05-26
> 作者：cici

## 1. 项目概述

- **项目名称**：SuperBizAgent
- **一句话描述**：企业级智能对话和运维助手，支持 RAG 知识库问答和 AIOps 智能诊断
- **应用场景**：运维工程师遇到告警或故障时，通过对话方式快速查询运维文档、获取诊断建议、自动执行故障排查
- **目标用户**：企业运维团队、SRE 工程师、技术支持人员

**核心功能**：
1. **智能对话**：基于 LangChain 的多轮对话，支持流式输出
2. **RAG 知识库问答**：上传运维文档（Markdown/PDF/DOCX/XLSX），自动建立向量索引，支持语义检索
3. **AIOps 智能诊断**：基于 Plan-Execute-Replan 模式，自动制定诊断计划、调用监控工具、生成故障报告
4. **文档生命周期管理**：从上传、解析、分块、索引到检索的完整生命周期追踪
5. **混合检索**：支持 dense-only（纯向量）、hybrid（BM25+向量）、hybrid_rerank（混合+重排序）三种检索模式

## 2. 软件环境与版本

### 2.1 操作系统
- **macOS 26.4.1** (Darwin 25E253)

### 2.2 核心软件依赖

| 软件/库 | 版本 | 用途 |
|---------|------|------|
| Python | 3.13.3 (虚拟环境) / 3.11+ (项目要求) | 编程语言 |
| FastAPI | ≥0.109.0 | Web 框架，提供 API 接口 |
| LangChain | ≥0.1.0 | LLM 应用框架，构建对话链路 |
| LangGraph | ≥0.0.40 | 状态图编排，实现 Plan-Execute-Replan |
| DashScope | ≥1.14.0 | 阿里云通义千问 API SDK |
| Milvus (pymilvus) | ≥2.3.5 | 向量数据库，存储文档向量 |
| Redis | ≥5.0.0 | 消息队列，异步文档处理 |
| RQ | ≥1.16.0 | Python 任务队列库 |
| Docker | 最新版 | 容器化部署 Milvus 和 Redis |
| uvicorn | ≥0.27.0 | ASGI 服务器 |
| loguru | ≥0.7.2 | 日志管理 |

### 2.3 开发工具依赖

| 工具 | 版本 | 用途 |
|------|------|------|
| uv | 最新版 | Python 包管理器（推荐，比 pip 更快） |
| black | ≥23.12.0 | 代码格式化 |
| ruff | ≥0.1.9 | 代码检查 |
| pytest | ≥7.4.3 | 单元测试 |

### 2.4 环境配置步骤

#### 步骤 1：安装 Python 和 uv
```bash
# 确认 Python 版本（需要 3.11 或更高）
python3 --version

# 安装 uv 包管理器
pip install uv
```

#### 步骤 2：克隆项目并创建虚拟环境
```bash
# 进入项目目录
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"

# 创建虚拟环境
uv venv

# 激活虚拟环境
source .venv/bin/activate  # macOS/Linux
# 或 .venv\Scripts\activate  # Windows
```

#### 步骤 3：安装项目依赖
```bash
# 使用 uv 安装（推荐，更快）
uv pip install -e .

# 或使用 pip 安装
pip install -e .
```

#### 步骤 4：配置环境变量
```bash
# 编辑 .env 文件
vim .env

# 必填配置项：
DASHSCOPE_API_KEY=your-api-key-here  # 阿里云 DashScope API Key
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-max

# Milvus 配置
MILVUS_HOST=localhost
MILVUS_PORT=19530

# RAG 配置
RAG_TOP_K=3
CHUNK_MAX_SIZE=800
CHUNK_OVERLAP=100
```

#### 步骤 5：启动 Docker 服务（Milvus + Redis）
```bash
# 确保 Docker Desktop 已安装并运行

# 启动 Milvus 向量数据库和 Redis
docker compose -f vector-database.yml up -d

# 等待服务启动完成（约 5-10 秒）
sleep 10

# 验证服务状态
docker ps | grep milvus
docker ps | grep redis
```

#### 步骤 6：验证安装
```bash
# 验证 Python 环境
python --version

# 验证依赖安装
pip list | grep -E "fastapi|langchain|pymilvus|dashscope"

# 运行单元测试
python -m unittest discover tests -v
```

## 3. 项目结构说明

```
super_biz_agent_py-release-2026-03-21/
├── app/                                    # 应用核心代码
│   ├── main.py                             # FastAPI 应用入口
│   ├── config.py                           # 配置管理
│   ├── api/                                # API 路由层
│   │   ├── chat.py                         # 对话接口
│   │   ├── aiops.py                        # AIOps 诊断接口
│   │   ├── file.py                         # 文件上传接口
│   │   └── health.py                       # 健康检查
│   ├── services/                           # 业务服务层
│   │   ├── rag_agent_service.py            # RAG Agent 服务
│   │   ├── aiops_service.py                # AIOps 服务
│   │   ├── document_ingestion_service.py   # 文档接入服务
│   │   ├── vector_index_service.py         # 向量索引服务
│   │   ├── retrieval_service.py            # 检索服务
│   │   ├── hybrid_search_service.py        # 混合检索服务
│   │   ├── rerank_service.py               # 重排序服务
│   │   ├── chunk_policy_service.py         # 分块策略服务
│   │   └── memory_store.py                 # 记忆存储服务
│   ├── models/                             # 数据模型层
│   │   ├── knowledge.py                    # 知识库模型
│   │   ├── memory.py                       # 记忆模型
│   │   └── request.py                      # 请求模型
│   ├── agent/                              # Agent 模块
│   │   ├── mcp_client.py                   # MCP 客户端
│   │   └── aiops/                          # AIOps 核心逻辑
│   ├── cli/                                # 命令行工具
│   │   └── memory_operator.py              # 记忆管理 CLI
│   └── workers/                            # 后台 Worker
│       └── document_processing_worker.py   # 文档处理 Worker
├── static/                                 # Web 前端
│   ├── index.html                          # 主页面
│   ├── app.js                              # 前端逻辑
│   └── styles.css                          # 样式表
├── mcp_servers/                            # MCP 服务器
│   ├── cls_server.py                       # 日志查询服务
│   └── monitor_server.py                   # 监控数据服务
├── aiops-docs/                             # 运维知识库文档
├── docs/                                   # 项目文档
├── evals/                                  # 评估脚本
│   └── rag_retrieval/                      # RAG 检索评估
├── tests/                                  # 单元测试
├── logs/                                   # 日志目录
├── uploads/                                # 上传文件临时目录
├── volumes/                                # Milvus 数据持久化
├── .env                                    # 环境变量配置
├── pyproject.toml                          # 项目配置
├── vector-database.yml                     # Docker Compose 配置
├── Makefile                                # 项目管理命令
└── README.md                               # 项目说明
```

### 3.1 核心模块说明

| 模块 | 文件路径 | 职责 |
|------|----------|------|
| **应用入口** | `app/main.py` | 注册 FastAPI 路由、静态页面、健康检查 |
| **配置管理** | `app/config.py` | 加载环境变量、MCP 服务器配置 |
| **对话接口** | `app/api/chat.py` | 提供普通对话和流式对话 API |
| **AIOps 接口** | `app/api/aiops.py` | 提供智能诊断 API |
| **文件上传** | `app/api/file.py` | 处理文档上传、校验、接入工作流 |
| **文档接入** | `app/services/document_ingestion_service.py` | 保存原件、创建记录、路由 parser |
| **向量索引** | `app/services/vector_index_service.py` | 统一 md/txt 与 MinerU artifact 入库 |
| **检索服务** | `app/services/retrieval_service.py` | 把 raw hit 转成带 citation 的结构化结果 |
| **混合检索** | `app/services/hybrid_search_service.py` | BM25 + 向量 + RRF fusion |
| **重排序** | `app/services/rerank_service.py` | 独立 rerank 边界、开关、失败回退 |
| **分块策略** | `app/services/chunk_policy_service.py` | 统一最终 chunk 边界、parent chunk |
| **知识库模型** | `app/models/knowledge.py` | DocumentRecord、ChunkRecord、SourceRef |
| **RAG Agent** | `app/services/rag_agent_service.py` | LangGraph 状态图、工具调用 |
| **AIOps 服务** | `app/services/aiops_service.py` | Plan-Execute-Replan 诊断流程 |

## 4. 代码开发步骤

### 4.1 开发时间线

- **开始时间**：2026年3月
- **持续时间**：约 2-3 个月（2026年3月 - 2026年5月）
- **当前状态**：持续开发中

### 4.2 开发阶段概览

项目采用分阶段迭代开发模式，从 P1 到 P6 逐步增强功能：

| 阶段 | 名称 | 主要内容 | 完成时间 |
|------|------|----------|----------|
| **P1** | 领域对象与文档生命周期 | DocumentRecord、ChunkRecord、状态管理 | 2026-05-13 |
| **P2** | MinerU 解析与 Artifact Contract | PDF/DOCX/XLSX 解析、六件套 artifact | 2026-05-17 |
| **P3** | 混合检索与 Rerank | BM25 + 向量、RRF fusion、重排序 | 2026-05-18 |
| **P4.5** | 上下文粒度控制 | chunk/parent_chunk/full_doc 三种粒度 | 2026-05-18 |
| **P5** | 文档级去重 | doc-level aggregation、减少冗余 | 2026-05-19 |
| **P6** | 记忆系统 | OpenViking + TencentDB 双参考记忆 | 2026-05-25 |

### 4.3 关键开发步骤详解

#### 步骤 1：建立领域对象层（P1）

**做了什么**：
- 创建 `app/models/knowledge.py`，定义核心领域对象
- 引入 `DocumentRecord`（文档记录）、`ChunkRecord`（分块记录）、`SourceRef`（来源引用）
- 定义文档状态枚举：`uploaded` → `parse_pending` → `index_pending` → `indexed` → `failed`

**为什么这样做**：
- 原有项目只有轻量的 `DocumentChunk` 模型，没有文档生命周期管理
- 需要追踪文档从上传到索引的完整状态
- 为后续 MinerU 解析和 citation 提供数据基础

**关键代码**：
```python
# app/models/knowledge.py
class DocumentRecord(BaseModel):
    doc_id: str
    kb_id: str
    original_filename: str
    parser_engine: ParserEngine  # plain_text / mineru
    status: DocumentStatus
    status_source: str
    status_detail: Optional[str]
    status_evidence: Optional[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime

class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    chunk_index: int
    content: str
    metadata: Dict[str, Any]
```

**参考来源**：
- WeKnora 项目的 `internal/types/knowledge.go`
- WeKnora 项目的 `internal/types/chunk.go`

---

#### 步骤 2：实现 MinerU Artifact Contract（P2）

**做了什么**：
- 创建 `app/services/artifact_manifest_service.py`，定义 artifact 六件套契约
- 创建 `app/services/artifact_chunk_builder_service.py`，将 MinerU 产物转换为可索引 chunk
- 实现 `app/services/parser_engine_router.py`，根据文件扩展名路由到不同 parser

**为什么这样做**：
- PDF/DOCX/XLSX 需要专门的解析器（MinerU），不能简单当作纯文本处理
- 需要标准化 MinerU 的输出格式，避免上下游协议不一致
- 六件套包括：`cleaned.md`、`chunks.json`、`tables.json`、`equations.json`、`images/`、`quality_report.json`

**关键代码**：
```python
# app/services/artifact_manifest_service.py
ARTIFACT_MANIFEST_SCHEMA = {
    "cleaned_md": {"required": True, "type": "file"},
    "chunks_json": {"required": True, "type": "file"},
    "tables_json": {"required": True, "type": "file"},
    "equations_json": {"required": False, "type": "file"},
    "images_dir": {"required": False, "type": "directory"},
    "quality_report_json": {"required": True, "type": "file"}
}

def validate_artifact_manifest(artifact_dir: Path) -> bool:
    # 校验六件套是否完整
    pass
```

**参考来源**：
- WeKnora 项目的 MinerU adapter 实现
- `pdf_eval` 项目的 MinerU 产物语义

---

#### 步骤 3：实现混合检索（P3）

**做了什么**：
- 创建 `app/services/sparse_search_service.py`，实现 BM25 稀疏检索
- 创建 `app/services/hybrid_search_service.py`，实现 RRF (Reciprocal Rank Fusion) 融合
- 创建 `app/services/rerank_service.py`，实现重排序逻辑
- 支持三种检索模式：`dense_only`（纯向量）、`hybrid`（混合）、`hybrid_rerank`（混合+重排）

**为什么这样做**：
- 纯向量检索在某些场景下召回率不足（如精确关键词匹配）
- BM25 擅长关键词匹配，向量检索擅长语义理解，两者互补
- Rerank 可以进一步优化排序质量

**关键代码**：
```python
# app/services/hybrid_search_service.py
def rrf_fusion(dense_results: List, sparse_results: List, k: int = 60) -> List:
    """RRF 融合算法"""
    scores = {}
    for rank, result in enumerate(dense_results):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (k + rank + 1)
    for rank, result in enumerate(sparse_results):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

**参考来源**：
- LangChain 官方文档的 Hybrid Search 示例
- 论文：Reciprocal Rank Fusion (RRF)

#### 步骤 4：实现上下文粒度控制（P4.5）

**做了什么**：
- 在 `app/services/retrieval_service.py` 中实现三种上下文粒度：
  - `chunk`：返回命中的 chunk 本身（默认）
  - `parent_chunk`：返回 chunk 的父级上下文
  - `full_doc`：返回整个文档内容
- 在 `app/services/chunk_policy_service.py` 中实现 parent chunk 生成逻辑

**为什么这样做**：
- 单个 chunk 可能上下文不足，导致 LLM 理解不完整
- 不同场景需要不同粒度的上下文（快速问答 vs 深度分析）
- 保持向后兼容，默认行为不变

**关键代码**：
```python
# app/models/knowledge.py
class ContextGranularity(str, Enum):
    chunk = "chunk"              # 只返回命中 chunk
    parent_chunk = "parent_chunk"  # 返回父级 chunk
    full_doc = "full_doc"        # 返回完整文档

# app/services/retrieval_service.py
def _format_context(self, results: List[RetrievalResult], 
                   granularity: ContextGranularity) -> str:
    if granularity == ContextGranularity.chunk:
        return "\n\n".join([r.content for r in results])
    elif granularity == ContextGranularity.parent_chunk:
        return "\n\n".join([r.metadata.get("parent_content", r.content) for r in results])
    elif granularity == ContextGranularity.full_doc:
        return self._assemble_full_doc_context(results)
```

**参考来源**：
- 自研设计，参考了 RAG 最佳实践

---

#### 步骤 5：实现文档级去重（P5）

**做了什么**：
- 在 `app/services/retrieval_service.py` 中实现 `doc_level` aggregation
- 按文档聚合检索结果，避免同一文档的多个 chunk 重复出现
- 支持 `top_chunks_per_doc` 和 `doc_oversample_factor` 参数调优

**为什么这样做**：
- 同一文档的多个 chunk 可能都被召回，导致上下文冗余
- 用户更希望看到来自不同文档的信息，而不是同一文档的重复内容
- 减少 token 消耗，提高检索多样性

**关键代码**：
```python
# app/models/knowledge.py
class ResultAggregation(str, Enum):
    none = "none"          # 不聚合（默认）
    doc_level = "doc_level"  # 按文档聚合

# app/services/retrieval_service.py
def _aggregate_by_doc(self, candidates: List[RetrievalResult], 
                     top_k: int, top_chunks_per_doc: int) -> List[RetrievalResult]:
    # 按 doc_id 分组
    doc_groups = {}
    for result in candidates:
        doc_id = result.metadata["doc_id"]
        if doc_id not in doc_groups:
            doc_groups[doc_id] = []
        doc_groups[doc_id].append(result)
    
    # 按文档命中数和最高分排序
    sorted_docs = sorted(doc_groups.items(), 
                        key=lambda x: (len(x[1]), max(r.score for r in x[1])), 
                        reverse=True)
    
    # 每个文档最多保留 top_chunks_per_doc 个 chunk
    final_results = []
    for doc_id, chunks in sorted_docs:
        final_results.extend(chunks[:top_chunks_per_doc])
        if len(final_results) >= top_k:
            break
    return final_results[:top_k]
```

**参考来源**：
- 自研设计，参考了搜索引擎的结果多样性策略

---

#### 步骤 6：实现记忆系统（P6）

**做了什么**：
- 创建 `app/models/memory.py`，定义记忆记录模型
- 创建 `app/services/memory_store.py`，实现 SQLite 持久化
- 创建 `app/services/memory_retrieval_service.py`，实现记忆检索
- 创建 `app/cli/memory_operator.py`，提供命令行管理工具
- 支持五种记忆类型：alert_pattern、plan_template、preference、runtime_context、candidate_summary

**为什么这样做**：
- AIOps 诊断需要记住历史告警模式和诊断计划
- 避免每次都从零开始，提高诊断效率
- 支持人工审核和管理记忆内容

**关键代码**：
```python
# app/models/memory.py
class MemoryType(str, Enum):
    alert_pattern = "alert_pattern"      # 告警模式
    plan_template = "plan_template"      # 诊断计划模板
    preference = "preference"            # 用户偏好
    runtime_context = "runtime_context"  # 运行时上下文
    candidate_summary = "candidate_summary"  # 候选总结

class MemoryRecord(BaseModel):
    memory_id: str
    owner_id: str
    namespace: str
    memory_type: MemoryType
    status: MemoryStatus  # candidate / active / deprecated
    payload: Dict[str, Any]
    evidence_refs: List[str]
    created_at: datetime
```

**参考来源**：
- OpenViking 项目（namespace/context layers/retrieval trace）
- TencentDB-Agent-Memory 项目（SQLite/FTS/vector/RRF）

## 5. 编程调试流程

### 5.1 从零开始搭建环境

```bash
# 1. 进入项目目录
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"

# 2. 创建并激活虚拟环境
uv venv
source .venv/bin/activate

# 3. 安装依赖
uv pip install -e .

# 4. 配置环境变量
vim .env
# 填入 DASHSCOPE_API_KEY 等必要配置

# 5. 启动 Docker 服务
docker compose -f vector-database.yml up -d

# 6. 等待 Milvus 和 Redis 启动完成
sleep 10

# 7. 验证 Docker 服务状态
docker ps | grep -E "milvus|redis"
```

### 5.2 启动服务

#### 方式 1：使用 Makefile（推荐，macOS/Linux）
```bash
# 一键初始化（首次运行）
make init

# 启动所有服务
make start

# 停止所有服务
make stop

# 重启服务
make restart
```

#### 方式 2：手动启动（适用于所有平台）
```bash
# 1. 启动 MCP 服务（新开终端窗口）
python mcp_servers/cls_server.py      # CLS 日志查询服务
python mcp_servers/monitor_server.py  # 监控数据服务

# 2. 启动 FastAPI 主服务（新开终端窗口）
python -m uvicorn app.main:app --host 0.0.0.0 --port 9900

# 3. 启动文档处理 Worker（新开终端窗口，可选）
python -m app.workers.document_processing_worker

# 预期输出：
# INFO:     Started server process [xxxxx]
# INFO:     Waiting for application startup.
# INFO:     Application startup complete.
# INFO:     Uvicorn running on http://0.0.0.0:9900
```

### 5.3 验证服务运行

```bash
# 1. 检查健康状态
curl http://localhost:9900/api/health

# 预期输出：
# {"status":"healthy","milvus":"connected","timestamp":"2026-05-26T..."}

# 2. 访问 Web 界面
open http://localhost:9900

# 3. 访问 API 文档
open http://localhost:9900/docs
```

### 5.4 上传文档并测试 RAG

```bash
# 1. 上传 Markdown 文档到知识库
curl -X POST "http://localhost:9900/api/upload" \
  -F "file=@aiops-docs/cpu_high_usage.md" \
  -F "kb_id=aiops"

# 预期输出：
# {"doc_id":"doc_xxx","status":"indexed","message":"Document indexed successfully"}

# 2. 测试 RAG 对话
curl -X POST "http://localhost:9900/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"Id":"test-session","Question":"CPU 使用率过高怎么办？"}'

# 预期输出：
# {"answer":"根据文档，CPU 使用率过高时可以...","sources":[...]}

# 3. 测试流式对话
curl -X POST "http://localhost:9900/api/chat_stream" \
  -H "Content-Type: application/json" \
  -d '{"Id":"test-session","Question":"CPU 使用率过高怎么办？"}' \
  --no-buffer

# 预期输出：
# data: {"type":"token","content":"根据"}
# data: {"type":"token","content":"文档"}
# ...
```

### 5.5 测试 AIOps 诊断

```bash
# 触发 AIOps 智能诊断
curl -X POST "http://localhost:9900/api/aiops" \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-aiops"}' \
  --no-buffer

# 预期输出（流式）：
# data: {"type":"plan","content":"制定诊断计划..."}
# data: {"type":"step","content":"步骤1: 查询日志..."}
# data: {"type":"result","content":"诊断报告..."}
```

### 5.6 常见报错与处理

| 报错信息 | 原因 | 解决方法 |
|----------|------|----------|
| `ModuleNotFoundError: No module named 'fastapi'` | 依赖未安装 | `uv pip install -e .` |
| `Connection refused: localhost:19530` | Milvus 未启动 | `docker compose -f vector-database.yml up -d` |
| `DASHSCOPE_API_KEY not found` | 环境变量未配置 | 检查 `.env` 文件，确保填入正确的 API Key |
| `batch size is invalid` | DashScope embedding 批量请求过大 | 已修复：`vector_embedding_service.py` 自动分批（每批10条） |
| `varchar(8000) exceeded` | 单个 chunk 超过 Milvus 字段长度限制 | 已修复：`chunk_policy_service.py` 实现 atomic hardcap（≤6000 bytes） |
| `Port 9900 already in use` | 端口被占用 | `lsof -i :9900` 查看占用进程，`kill -9 <PID>` 结束进程 |
| `Redis connection failed` | Redis 未启动 | `docker ps \| grep redis` 检查状态，重启 Docker 服务 |

### 5.7 运行单元测试

```bash
# 运行所有测试
python -m unittest discover tests -v

# 预期输出：
# test_document_record (tests.test_knowledge.TestKnowledge) ... ok
# test_chunk_record (tests.test_knowledge.TestKnowledge) ... ok
# test_memory_store (tests.test_memory_store.TestMemoryStore) ... ok
# ...
# Ran 101 tests in 12.345s
# OK

# 运行特定测试文件
python -m unittest tests.test_retrieval_service -v

# 运行代码检查
python -m compileall app tests
```

### 5.8 运行评估脚本

```bash
# 运行 RAG 检索评估（三种模式对比）
python evals/rag_retrieval/run_retrieval_eval.py

# 预期输出：
# Running dense_only evaluation...
# Running hybrid evaluation...
# Running hybrid_rerank evaluation...
# Report saved to: evals/rag_retrieval/reports/retrieval_eval_20260526_*.json

# 运行 P5 文档级去重评估
python evals/rag_retrieval/run_p5_eval.py

# 运行 P6 记忆系统评估
python evals/memory/run_p6_memory_eval_lite.py
```

## 6. 运行说明

### 6.1 启动方式

**推荐方式**（macOS/Linux）：
```bash
make start
```

**Windows 方式**：
```powershell
.\start-windows.bat
```

**手动方式**（所有平台）：
1. 启动 Docker 服务：`docker compose -f vector-database.yml up -d`
2. 启动 MCP 服务：`python mcp_servers/cls_server.py` 和 `python mcp_servers/monitor_server.py`
3. 启动 FastAPI 主服务：`python -m uvicorn app.main:app --host 0.0.0.0 --port 9900`
4. （可选）启动文档处理 Worker：`python -m app.workers.document_processing_worker`

### 6.2 输入要求

**文档上传**：
- 支持格式：`.md`、`.txt`（plain_text parser）、`.pdf`、`.docx`、`.xlsx`（MinerU parser）
- 文件大小：建议 < 50MB
- 编码：UTF-8

**对话输入**：
- 问题长度：建议 < 500 字符
- 会话 ID：必填，用于多轮对话上下文管理

### 6.3 预期输出

**Web 界面**：
- 访问 `http://localhost:9900` 可看到对话界面
- 支持三种模式：快速问答、流式对话、智能运维诊断

**API 响应**：
- 对话接口返回 JSON 格式，包含 `answer` 和 `sources`（引用来源）
- 流式接口返回 SSE (Server-Sent Events) 格式，逐 token 输出

**日志输出**：
- 日志文件：`logs/app_YYYY-MM-DD.log`（按天轮转）
- MCP 日志：`mcp_cls.log`、`mcp_monitor.log`

### 6.4 运行时间

- **服务启动**：约 10-15 秒（等待 Milvus 和 Redis 启动）
- **文档上传**：
  - Markdown/TXT：< 1 秒（同步索引）
  - PDF/DOCX/XLSX：5-30 秒（异步解析，取决于文档大小）
- **RAG 对话**：1-3 秒（包括检索 + LLM 生成）
- **AIOps 诊断**：10-30 秒（包括计划制定 + 工具调用 + 报告生成）

## 7. 参考链接

| 链接 | 解决了什么问题 |
|------|----------------|
| [FastAPI 官方文档](https://fastapi.tiangolo.com/) | 学习 FastAPI 框架的基本用法、路由定义、依赖注入 |
| [LangChain 官方文档](https://python.langchain.com/) | 学习 LangChain 的 Agent、Tool、Memory 等核心概念 |
| [LangGraph Plan-Execute 教程](https://langchain-ai.github.io/langgraph/tutorials/plan-and-execute/) | 实现 AIOps 的 Plan-Execute-Replan 诊断流程 |
| [阿里云 DashScope 文档](https://dashscope.aliyun.com/) | 获取 API Key、了解通义千问模型的调用方式 |
| [Milvus 官方文档](https://milvus.io/docs) | 学习向量数据库的基本操作、collection 管理、向量检索 |
| [MCP 协议规范](https://modelcontextprotocol.io/) | 理解 MCP 协议，实现日志查询和监控工具接入 |
| [WeKnora 项目](https://github.com/xxx/WeKnora) | 参考知识库领域对象设计、parser registry、chunk service |
| [OpenViking 项目](https://github.com/xxx/OpenViking) | 参考记忆系统的 namespace/context layers/retrieval trace 设计 |
| [TencentDB-Agent-Memory 项目](https://github.com/xxx/TencentDB-Agent-Memory) | 参考 SQLite/FTS/vector/RRF 混合检索、symbolic session offload |
| [牛客：腾讯后台开发面经](https://www.nowcoder.com/discuss/353154952065392640) | 学习如何准备项目深挖问题、技术追问 |
| [Reciprocal Rank Fusion 论文](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf) | 理解 RRF 融合算法的原理，用于混合检索 |

## 8. 项目亮点与技术难点

### 8.1 项目亮点

1. **完整的文档生命周期管理**
   - 从上传、解析、分块、索引到检索的全流程追踪
   - 支持状态确认机制（`status_source`、`status_evidence`、`status_confirmed_at`）
   - 可追溯每个文档的处理历史

2. **多 Parser 引擎支持**
   - 自动路由：`.md/.txt` → plain_text，`.pdf/.docx/.xlsx` → MinerU
   - 标准化 artifact contract，确保上下游协议一致
   - 支持异步解析（RQ 队列），避免阻塞主服务

3. **多模式检索**
   - `dense_only`：纯向量检索（默认）
   - `hybrid`：BM25 + 向量 + RRF 融合
   - `hybrid_rerank`：混合检索 + 重排序
   - 通过离线评估验证各模式效果

4. **灵活的上下文控制**
   - 三种粒度：`chunk`（默认）、`parent_chunk`、`full_doc`
   - 文档级去重：避免同一文档的多个 chunk 重复出现
   - 可配置参数：`top_chunks_per_doc`、`doc_oversample_factor`

5. **记忆系统**
   - 支持五种记忆类型：alert_pattern、plan_template、preference、runtime_context、candidate_summary
   - 人工审核机制：candidate → active / deprecated
   - 命令行管理工具：`memory_operator.py`

6. **完善的评估体系**
   - P1-P6 阶段性评估和门禁
   - 离线评估脚本：`run_retrieval_eval.py`、`run_p5_eval.py`、`run_p6_memory_eval_lite.py`
   - 评估指标：citation invariance、token overhead、lift、discrimination

### 8.2 技术难点与解决方案

#### 难点 1：Milvus content 字段长度限制

**问题描述**：
- Milvus collection 的 `content` 字段定义为 `varchar(8000)`
- P6 corpus probe 时遇到单个 chunk 超过 8000 字符，导致索引失败

**解决方案**：
- 在 `ChunkPolicyService` 中实现 atomic hardcap
- 对超长 chunk 进行截断，确保 UTF-8 编码后 ≤ 6000 bytes（留有安全边界）
- 通过 P5.f3 评估验证 retrieval byte-level drift=0，确保不影响检索质量

**代码位置**：`app/services/chunk_policy_service.py`

---

#### 难点 2：DashScope embedding API 批量调用失败

**问题描述**：
- 向量化时批量请求 DashScope API，返回 `400 batch size is invalid`
- 导致 eval pipeline 无法正常运行

**解决方案**：
- 在 `vector_embedding_service.embed_documents` 中实现分批处理
- 每批最多 10 条文本，避免超过 API 限制
- 添加重试机制，提高稳定性

**代码位置**：`app/services/vector_embedding_service.py`

---

#### 难点 3：WeKnora Go 代码无法直接接入 Python 主链路

**问题描述**：
- WeKnora 是 Go 实现，有完整的知识库层设计
- 无法直接复用 Go 代码到 Python 项目

**解决方案**：
- 采用"按字段语义复制 + 最小 Python 化"策略
- 在 `app/models/knowledge.py` 中重建领域对象
- 保持接口语义一致，但实现语言不同

**参考来源**：
- `WeKnora/internal/types/knowledgebase.go`
- `WeKnora/internal/types/knowledge.go`
- `WeKnora/internal/types/chunk.go`

---

#### 难点 4：混合检索的 RRF 融合参数调优

**问题描述**：
- BM25 和向量检索的分数量纲不同，无法直接相加
- 需要找到合适的融合算法和参数

**解决方案**：
- 采用 RRF (Reciprocal Rank Fusion) 算法
- 公式：`score = 1 / (k + rank + 1)`，其中 k=60（经验值）
- 通过离线评估验证 hybrid 模式相比 dense_only 的提升

**代码位置**：`app/services/hybrid_search_service.py`

---

#### 难点 5：P5 文档级去重的候选池大小设计

**问题描述**：
- 如果候选池太小，可能无法覆盖足够多的文档
- 如果候选池太大，计算开销增加

**解决方案**：
- 引入 `doc_oversample_factor` 参数（默认 4）
- 候选池大小 = `top_k * doc_oversample_factor`
- 通过 P5.f1 评估验证 factor=4 足够（0/6 样本饱和）

**代码位置**：`app/services/retrieval_service.py`

## 9. 后续优化方向

1. **性能优化**
   - 引入缓存机制（Redis），减少重复检索
   - 优化 Milvus 索引参数（IVF_FLAT → HNSW）
   - 实现批量向量化，提高吞吐量

2. **功能扩展**
   - 支持更多文档格式（PPT、HTML、代码文件）
   - 实现多知识库隔离（不同团队使用不同 kb_id）
   - 支持文档更新和删除（当前只支持新增）

3. **评估完善**
   - 引入 LLM-as-judge 评估框架（RAGAS、TruLens）
   - 扩展评估语料（当前主要是中文运维文档）
   - 实现 A/B 测试框架，对比不同检索策略

4. **生产化**
   - 添加用户认证和权限管理
   - 实现分布式部署（多副本、负载均衡）
   - 完善监控和告警（Prometheus + Grafana）

---

**文档完成日期**：2026-05-26
**作者**：cici
**项目版本**：v1.2.1 (release-2026-03-21)
