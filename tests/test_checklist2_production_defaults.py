from app.config import Settings


def test_checklist2_production_safety_defaults_remain_off():
    defaults = Settings.model_fields

    assert defaults["rag_session_memory_mode"].default == "off"
    assert defaults["tool_result_offload_enabled"].default is False
    assert defaults["pdf_agent_tools_enabled"].default is False
    assert defaults["rag_query_rewrite_mode"].default == "off"
    assert defaults["rag_default_retrieval_mode"].default == "dense_only"
    assert defaults["rerank_enabled"].default is False
