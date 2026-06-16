# RAG Answer Layer C6 Answer 30q Revisit

Date: 2026-06-12

## Scope

This is a narrow Answer-layer revisit after C6 corpus expansion and C6-P3 retrieval validation.

It creates a derived Answer evalset:

- `evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6.jsonl`

The derived evalset keeps the historical Answer 20q unchanged as its first 20 rows, then appends 10 C6 samples:

- 4 Redis/MySQL runbook Markdown samples
- 3 other C6 Markdown samples
- 3 C6 PDF samples

Every new sample includes:

- `reference_answer`
- `must_include_facts`
- `must_not_include_claims`
- `required_citations`

## Boundary

This revisit does not change the main runtime or main gate:

- no change to `run_department_rag_answer_eval.py`
- no change to answer prompt
- no change to retrieval default
- no change to `top_k`
- no change to `rag_default_retrieval_mode=dense_only`
- no change to `rag_query_rewrite_mode=off`
- no change to `rerank_enabled=false`
- no OpenJudge score write-back
- no deterministic `passed/failed` override
- no agent behavior acceptance

## Baseline Run

Command:

```bash
uv run python evals/knowledge_base/run_department_rag_answer_eval.py \
  --evalset evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6.jsonl \
  --report evals/knowledge_base/reports/department_rag_answer_30q_after_c6_baseline_20260612.json
```

Result:

- total: 30
- passed: 16
- failed: 14
- pass rate: 53.33%
- not_ready: 0
- failure categories:
  - `answer_missing_facts`: 8
  - `context_missing_facts`: 6
- clean safety/source boundary:
  - `citation_required_but_missing`: 0
  - `unsupported_claim_count`: 0
  - `permission_leak_count`: 0
  - `source_ref_unresolvable_count`: 0
  - `retrieval_layer_failed_count`: 0

Because 16/30 is below 21/30, this result does not justify moving to `agent_behavior`.

## Old 20q Split

Compared with `department_rag_answer_pilot_20q_after_synonym_fix_20260612.json`, the old 20q subset moved from 14/20 to 13/20 in this run.

Status changes:

- `S5P1-MD-003`: passed -> failed, `answer_missing_facts`
- `S5P1-MD-006`: passed -> failed, `answer_missing_facts`
- `S5P1-MD-008`: failed -> passed

Interpretation:

- This confirms existing Answer 20q generation variance remains active.
- The regression is not a source_ref, citation, scope, permission, or unsupported-claim issue.
- Do not relax the old 20q gate globally from this single run.

## New 10q Split

The new C6 10q subset passed 3/10:

- passed: `C6A-MD-006`, `C6A-PDF-009`, `C6A-PDF-010`
- failed: 7

Failure split:

- `answer_missing_facts`: 4
- `context_missing_facts`: 3

Failed new samples:

- `C6A-MD-001`: `answer_missing_facts`; missing `redis_memory_used_ratio`, `evicted_keys`
- `C6A-MD-002`: `answer_missing_facts`; missing emergency Redis mitigation actions
- `C6A-MD-003`: `answer_missing_facts`; missing `SQL fingerprint`, `rows examined`
- `C6A-MD-004`: `context_missing_facts`; connection-pool metrics missing from top-3 context, `connection timeout` omitted by answer
- `C6A-MD-005`: `context_missing_facts`; startup commands and service URLs not fully present in top-3 context
- `C6A-MD-007`: `context_missing_facts`; `execute_sql` boundary missing from top-3 context, production-DB boundary omitted by answer
- `C6A-PDF-008`: `answer_missing_facts`; GHG emission source categories omitted

Interpretation:

- New C6 documents are reachable at retrieval level, but Answer generation often summarizes without preserving deterministic facts.
- Several failures are valid context-shape failures: the expected document is found, but top-3 chunks do not contain all required facts.
- Several failures are answer-generation omissions despite context containing the facts.
- This is not an OpenJudge gate issue and not a reason to change retrieval defaults.

## OpenJudge Shadow 30q

Command:

```bash
uv run python evals/knowledge_base/run_openjudge_answer_shadow_eval.py \
  --baseline-report evals/knowledge_base/reports/department_rag_answer_30q_after_c6_baseline_20260612.json \
  --evalset evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6.jsonl \
  --output-json evals/knowledge_base/reports/openjudge_answer_shadow_30q_after_c6_20260612.json \
  --max-concurrency 4
```

Result:

- deterministic status remains 16 passed / 14 failed
- `shadow_only=true`
- `changes_main_gate=false`
- `writes_back_to_baseline=false`
- `shadow_scores_affect_pass_fail=false`
- OpenJudge scored 30/30 for all graders:
  - relevance
  - hallucination
  - correctness
  - instruction_following
- `context_text_available_count=0`, so hallucination/context-sensitive scores remain low-context diagnostics

Correlation observations:

- `context_missing_facts` vs correctness: -0.6472
- `context_missing_facts` vs relevance: -0.6751
- `answer_missing_facts` vs correctness: -0.0258
- `unsupported_claim_count` correlations are null because unsupported-claim count is constant 0

Interpretation:

- OpenJudge remains useful as a diagnostic layer for context-quality degradation.
- OpenJudge does not track deterministic answer-missing facts strongly in this run.
- No OpenJudge signal should alter deterministic pass/fail.

## Decision

Do not enter `agent_behavior` from this result.

Do not create Answer 50q from this result.

Do not tune prompt, `top_k`, hybrid, rerank, or query rewrite globally from this single run.

The next useful step is failure analysis, starting with:

1. Review the 3 new `context_missing_facts` samples to decide whether the issue is chunking/top-3 context shape or overly broad sample facts.
2. Review high-OpenJudge / deterministic-failed samples such as `C6A-MD-003` for possible synonym/terminology calibration, for example `SQL fingerprint` vs `SQL 指纹`.
3. If enough failures cluster as answer omissions after context is present, consider a narrow answer-prompt shadow experiment. Keep it shadow-only until a full rerun proves lift.
