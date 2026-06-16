#!/usr/bin/env python3
"""P5.f3 LLM smoke: 1-call validation before full run.

Validates the LLM integration risk dimensions only:
- DASHSCOPE_API_KEY readable from config
- ChatOpenAI compat mode reachable at DASHSCOPE_BASE_URL
- prompt template renders
- citation regex extracts chunk_id from response
- timeout / retry config does not error in happy path

Does NOT index corpus (already proven by P5.f1/f2).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evals.rag_retrieval.run_p5_llm_eval import (
    PROMPT_TEMPLATE, _build_llm, call_llm, parse_citations,
)


SMOKE_CONTEXT = """【参考资料 1】
标题: 测试章节
来源: smoke_test.md
定位: [来源: smoke_test.md, 章节: 测试章节, chunk: smoke:c00001]
内容:
ping 命令用于测试网络连通性。如果目标主机不可达，ping 会超时。

【参考资料 2】
标题: 测试章节 2
来源: smoke_test.md
定位: [来源: smoke_test.md, 章节: 测试章节 2, chunk: smoke:c00002]
内容:
SSH 是远程登录协议，使用加密通道。
"""

SMOKE_QUERY = "ping 命令是干什么的？"
EXPECTED_RETRIEVAL_CHUNK_IDS = {"smoke:c00001", "smoke:c00002"}


def main() -> int:
    print("=" * 60)
    print("P5.f3 LLM smoke")
    print("=" * 60)

    print("\n[1/4] Building LLM client...")
    try:
        llm = _build_llm()
    except Exception as exc:
        print(f"FAIL: LLM client construction raised: {exc}")
        return 1
    print("  OK")

    print("\n[2/4] Rendering prompt...")
    prompt = PROMPT_TEMPLATE.format(context_text=SMOKE_CONTEXT, query=SMOKE_QUERY)
    print(f"  prompt length = {len(prompt)} chars")

    print("\n[3/4] Calling LLM (1 call, with retry+timeout)...")
    answer, success, err = call_llm(prompt, llm)
    if not success:
        print(f"FAIL: LLM call failed after retries: {err}")
        return 2
    print(f"  OK; answer length = {len(answer)} chars")
    print("  --- answer ---")
    print(answer[:600])
    print("  --- /answer ---")

    print("\n[4/4] Parsing citations from answer...")
    cited = parse_citations(answer)
    print(f"  cited chunk_ids = {sorted(cited)}")
    inside = cited & EXPECTED_RETRIEVAL_CHUNK_IDS
    outside = cited - EXPECTED_RETRIEVAL_CHUNK_IDS
    print(f"  inside_retrieval = {sorted(inside)}")
    print(f"  outside_retrieval = {sorted(outside)}")
    if not cited:
        print("  WARN: LLM did not emit any [chunk: <id>] citations.")
        print("        prompt or model behavior may need adjustment, but this")
        print("        is not strictly a smoke failure (eval treats it as")
        print("        no_citation = True).")
        return 0
    if outside and not inside:
        print("  WARN: LLM cited only outside retrieval set.")
        print(f"        outside ids: {sorted(outside)}")
    print("\nSmoke PASSED. Safe to run run_p5_llm_eval.py for the full 54-call evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
