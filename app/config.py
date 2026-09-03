"""配置管理模块

使用 Pydantic Settings 实现类型安全的配置管理
"""

from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 应用配置
    app_name: str = "RagWithAIOps"
    app_version: str = "1.0.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 9900

    # DashScope 配置
    dashscope_api_key: str = ""  # 默认空字符串，实际使用需从环境变量加载
    dashscope_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen-max"
    dashscope_embedding_model: str = "text-embedding-v4"  # v4 支持多种维度（默认 1024）

    # Milvus 配置
    milvus_uri: str = ""
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_timeout: int = 10000  # 毫秒

    # RAG 配置
    rag_top_k: int = 3
    rag_default_retrieval_mode: str = "dense_only"
    rag_query_rewrite_mode: str = "off"
    rag_session_memory_mode: str = "off"
    rag_session_memory_max_prompt_chars: int = 2000
    rag_session_memory_max_tail_messages: int = 12
    rag_session_memory_snapshot_ttl_seconds: int = 2592000
    tool_result_offload_enabled: bool = False
    tool_result_offload_threshold: int = 2000
    tool_result_offload_max_bytes: int = 200000
    tool_result_offload_ttl_days: int = 7
    pdf_agent_tools_enabled: bool = False
    rag_model: str = "qwen-max"  # 使用快速响应模型，不带扩展思考
    rerank_enabled: bool = False
    rerank_model: str = "local_lexical_v1"
    rerank_bailian_model: str = "qwen3-rerank"
    rerank_bailian_endpoint: str = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
    rerank_timeout_ms: int = 2000
    rerank_top_k: int = 10
    rerank_fallback_on_error: bool = True

    # 文档分块配置
    chunk_max_size: int = 800
    chunk_overlap: int = 100

    # P5 Shadow Mode 配置
    memory_shadow_allowlist: str = ""  # 逗号分隔的 owner_id 白名单，例如 "user1,user2"
    memory_shadow_sampling_rate: float = 0.0  # 采样率 (0.0 - 1.0)，默认 0% 不开启

    # Enterprise E1 Auth / RequestContext 配置
    jwt_secret_key: str = "dev-enterprise-secret-change-me-32bytes"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 120

    # Enterprise E2 Gateway / Audit 配置
    enterprise_audit_sqlite_path: str = "logs/enterprise_audit.sqlite"
    enterprise_audit_jsonl_path: str = "logs/enterprise_audit.jsonl"
    enterprise_task_contract_sqlite_path: str = "logs/enterprise_task_contracts.sqlite"
    enterprise_human_review_sqlite_path: str = "logs/enterprise_human_reviews.sqlite"
    enterprise_chat_session_sqlite_path: str = "logs/enterprise_chat_sessions.sqlite"
    enterprise_database_confirmation_sqlite_path: str = (
        "logs/enterprise_database_confirmations.sqlite"
    )
    enterprise_mysql_enabled: bool = False
    enterprise_mysql_database_id: str = "mysql_sales_readonly"
    enterprise_mysql_host: str = ""
    enterprise_mysql_port: int = 3306
    enterprise_mysql_database: str = ""
    enterprise_mysql_username: str = ""
    enterprise_mysql_password: str = ""
    enterprise_mysql_connect_timeout_seconds: float = 5.0
    enterprise_mysql_read_timeout_seconds: float = 5.0
    enterprise_mysql_pool_size: int = 2
    enterprise_mysql_default_limit: int = 100
    enterprise_mysql_max_limit: int = 100
    enterprise_mysql_allowlist_json: str = ""

    # MinerU 解析配置
    mineru_cli_path: str = "mineru"
    mineru_api_url: str = ""
    mineru_method: str = "auto"
    mineru_backend: str = "pipeline"
    mineru_language: str = "ch"
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True
    mineru_mplconfigdir: str = "/private/tmp/mpl"
    mineru_postprocess_script_path: str = ""

    # 异步文档处理队列配置
    document_processing_redis_url: str = "redis://localhost:6379/0"
    document_processing_queue_name: str = "document_processing"
    document_processing_job_timeout_seconds: int = 1800
    document_processing_result_ttl_seconds: int = 86400
    document_processing_failure_ttl_seconds: int = 604800

    # MCP 服务配置
    mcp_cls_transport: str = "streamable-http"
    mcp_cls_url: str = "http://localhost:8003/mcp"
    mcp_monitor_transport: str = "streamable-http"
    mcp_monitor_url: str = "http://localhost:8004/mcp"

    @property
    def mcp_servers(self) -> dict[str, dict[str, Any]]:
        """获取完整的 MCP 服务器配置"""
        return {
            "cls": {
                "transport": self.mcp_cls_transport,
                "url": self.mcp_cls_url,
            },
            "monitor": {
                "transport": self.mcp_monitor_transport,
                "url": self.mcp_monitor_url,
            }
        }


# 全局配置实例
config = Settings()
