# RAG Answer Layer C6 Answer 30q Failure Triage

Date: 2026-06-12

## Scope

This triage follows `bea125d eval: add c6 answer 30q revisit`.

Inputs:

- Evalset: `evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6.jsonl`
- Deterministic report: `evals/knowledge_base/reports/department_rag_answer_30q_after_c6_baseline_20260612.json`
- OpenJudge shadow report: `evals/knowledge_base/reports/openjudge_answer_shadow_30q_after_c6_20260612.json`

Boundary:

- no Answer prompt change
- no retrieval default change
- no global `top_k` change
- no hybrid / rerank / query rewrite enablement
- no OpenJudge write-back
- no deterministic `passed/failed` override
- no `agent_behavior` acceptance

The JSON/Markdown reports remain local evidence under `evals/**/reports/`, which is ignored by the repository.

## Baseline Split

Answer 30q result:

- total: 30
- passed: 16
- failed: 14
- pass rate: 53.33%
- failure categories:
  - `answer_missing_facts`: 8
  - `context_missing_facts`: 6

Old 20q subset:

- passed: 13/20
- failed: 7/20
- failed split:
  - `answer_missing_facts`: 4
  - `context_missing_facts`: 3

New C6 10q subset:

- passed: 3/10
- failed: 7/10
- failed split:
  - `answer_missing_facts`: 4
  - `context_missing_facts`: 3

Important correction: the new C6 10q failures are mixed. They are not purely a retrieval problem. The three `context_missing_facts` rows should be prioritized because missing context is a prerequisite failure for Answer quality.

## Context-Missing Triage

### C6A-MD-004

Query:

`DBSlowQuery 伴随连接池等待怎么处理`

Finding:

- top-3 retrieves `mysql_slow_query_runbook.md` in all three slots.
- top-3 misses `应用连接池 active / idle / wait`.
- top-3 contains connection-pool exhaustion, `connection timeout`, DB connection near limit, low-priority throttling, and slow SQL repair evidence.
- read-only top-k shadow:
  - `top_k=3`: missing `应用连接池 active / idle / wait`
  - `top_k=5`: no required context facts missing
  - `top_k=8`: no required context facts missing

Classification:

- primary: top-3 chunk-shape issue
- secondary: answer omission, because the generated answer also omitted exact `connection timeout` even though top-3 context contained it

Decision:

- Do not change global top_k from this single sample.
- Keep as a candidate for a narrow retrieval-context shadow, such as top_k=5 or adjacent/parent chunk context, before any default change.

### C6A-MD-005

Query:

`AIOps Lab 本地启动和 smoke 怎么跑`

Finding:

- top-3 retrieves:
  - `aiops_lab_README.md` Smoke chunk
  - `aiops_真实模拟执行清单.md` directory-suggestion chunk
  - `aiops_lab_README.md` intro chunk
- top-3 misses the startup chunk containing:
  - `docker compose -f aiops_lab/docker-compose.yml up --build`
  - `Prometheus: http://localhost:9090`
  - `Alertmanager: http://localhost:9093`
- top-3 includes a weak `seed.py` mention through the directory tree, which is why the deterministic gate classified `python aiops_lab/cmdb/seed.py` as answer-missing rather than context-missing.
- read-only top-k shadow:
  - `top_k=3`: misses startup command and service URLs
  - `top_k=5`: no required context facts missing
  - `top_k=8`: no required context facts missing

Classification:

- primary: top-3 chunk-shape issue
- secondary: sample requires both startup and smoke facts, which live in separate chunks of the same README

Decision:

- Do not change global top_k from this single sample.
- Keep as a candidate for same-document adjacent chunk or top_k=5 shadow.

### C6A-MD-007

Query:

`数据库操作能力里哪些操作直接执行，哪些需要用户确认`

Finding:

- top-3 retrieves both `数据库操作能力执行步骤清单.md` and `数据库操作能力.md`.
- top-3 contains the main execution split:
  - read-only direct execution
  - non-delete write / non-delete DDL direct execution with permission
  - delete operations require user confirmation
- top-3 misses `不做万能 execute_sql`.
- read-only top-k shadow:
  - `top_k=3`: misses `不做万能 execute_sql`
  - `top_k=5`: still misses `不做万能 execute_sql`
  - `top_k=8`: still misses `不做万能 execute_sql`
- source text check shows exact `不做万能 execute_sql` exists in `数据库操作能力执行步骤清单.md` under the hard-boundary section, not in the primary required citation document `数据库操作能力.md`.

Classification:

- mixed eval-design/context issue.
- This is not solved by a small top-k increase.
- The sample combines "direct vs confirmation" with a separate hard-boundary phrase from a different section/document.

Decision:

- Do not treat this as evidence for global retrieval tuning.
- Before rerun, either:
  - narrow the sample to facts present in the primary expected document, or
  - explicitly make it a cross-document hard-boundary sample and adjust expected citations / query wording accordingly.

## OpenJudge High-Score / Deterministic-Failed Triage

OpenJudge correctness >= 4.5 and deterministic failed:

- `C6A-MD-003`: correctness 5.0, deterministic failure `answer_missing_facts`

Actual answer evidence:

- answer says `SQL 指纹`
- answer says `估计扫描行数(rows)`
- deterministic required facts are `SQL fingerprint` and `rows examined`

Classification:

- likely deterministic terminology false negative.
- This is a narrow synonym/translation issue, not a reason to loosen the whole Answer gate.

Candidate limited calibration:

- change `SQL fingerprint` to `SQL fingerprint||SQL 指纹`
- change `rows examined` to `rows examined||扫描行数`

Do not add generic `rows` as an alias because it is too broad.

OpenJudge correctness >= 4.0 also surfaced `S5P1-MD-001`, `S5P1-MD-003`, `S5P1-MD-006`, `C6A-MD-001`, and `C6A-MD-007`, but those are not clean synonym fixes. They either still miss real deterministic facts or involve context/eval-design boundaries.

## Root-Cause Summary

| Group | Samples | Root cause | Next action |
|---|---:|---|---|
| C6 top-3 context shape | 2 | `C6A-MD-004`, `C6A-MD-005` need facts spread across nearby chunks | Shadow top_k=5 or adjacent/parent chunk context; no default change |
| C6 eval-design/context mismatch | 1 | `C6A-MD-007` requires hard-boundary phrase outside the primary expected citation context | Re-scope sample before rerun |
| Clear terminology false negative | 1 | `C6A-MD-003` uses Chinese terms for English required facts | Limited alias calibration only |
| Answer omission | remaining | Context is present but generation omits deterministic details | Do not tune prompt globally until failures cluster after context/eval calibration |

## Decision

Answer 30q remains below threshold. Do not enter `agent_behavior`, do not create Answer 50q, and do not promote OpenJudge to a gate.

The next safe implementation order is:

1. Apply a narrow C6A-MD-003 terminology calibration if accepted.
2. Re-scope C6A-MD-007 before any rerun.
3. Run a shadow-only context experiment for C6A-MD-004 and C6A-MD-005, comparing default top-3 with top_k=5 or same-document adjacent chunks.
4. Only after those are resolved, rerun Answer 30q and inspect whether remaining failures are true answer-generation omissions.

## Triage-Fix Rerun

Derived evalset:

- `evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6_triage_fix.jsonl`

This file preserves the original `department_rag_answer_30q_after_c6.jsonl` baseline and changes only two rows:

- `C6A-MD-003`
  - `SQL fingerprint` -> `SQL fingerprint||SQL 指纹`
  - `rows examined` -> `rows examined||扫描行数`
  - intentionally did not add generic `rows`
- `C6A-MD-007`
  - narrowed the required facts to the direct-vs-confirmation decision present in `数据库操作能力.md`
  - moved the cross-document `execute_sql` boundary into `must_not_include_claims`
  - kept production-open false claims forbidden

Deterministic rerun:

```bash
.venv/bin/python evals/knowledge_base/run_department_rag_answer_eval.py \
  --evalset evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6_triage_fix.jsonl \
  --report evals/knowledge_base/reports/department_rag_answer_30q_after_c6_triage_fix_20260612.json
```

Result:

- total: 30
- passed: 18
- failed: 12
- pass rate: 60.00%
- not_ready: 0
- failure categories:
  - `answer_missing_facts`: 7
  - `context_missing_facts`: 5
- `C6A-MD-003`: passed
- `C6A-MD-007`: passed

Observed status changes versus the original 16/30 run:

- `C6A-MD-003`: failed -> passed
- `C6A-MD-007`: failed -> passed
- `S5P1-MD-006`: failed -> passed
- `S5P1-MD-008`: passed -> failed

The last two are old-20q generation variance, not triage-fix edits. Net result is still +2 passed.

OpenJudge shadow rerun:

```bash
.venv/bin/python evals/knowledge_base/run_openjudge_answer_shadow_eval.py \
  --baseline-report evals/knowledge_base/reports/department_rag_answer_30q_after_c6_triage_fix_20260612.json \
  --evalset evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6_triage_fix.jsonl \
  --output-json evals/knowledge_base/reports/openjudge_answer_shadow_30q_after_c6_triage_fix_20260612.json \
  --max-concurrency 4
```

Result:

- deterministic status remains 18 passed / 12 failed
- OpenJudge scored 30/30 for relevance, hallucination, correctness, and instruction_following
- `shadow_only=true`
- `changes_main_gate=false`
- `writes_back_to_baseline=false`
- `shadow_scores_affect_pass_fail=false`

Decision after rerun:

- 18/30 is an improvement from 16/30, but still below the 21/30 continuation threshold.
- The triage-fix file lives at the formal evalset path; it is not part of the beta launch material or a promoted Answer gate.
- Do not enter `agent_behavior`.
- Do not create Answer 50q.
- Do not change global prompt, top_k, retrieval mode, hybrid, rerank, or query rewrite defaults.
- The next Answer-specific step, if pursued, is a shadow-only context experiment for `C6A-MD-004` and `C6A-MD-005`.

## Context Shadow Follow-Up

Runner:

- `evals/knowledge_base/run_answer_context_shadow_eval.py`

Scope:

- retrieval-only context coverage probe
- no LLM answer generation
- no LLM-as-judge
- no write-back to deterministic baseline
- no default `top_k`, retrieval mode, query rewrite, rerank, or prompt change

### C6A-MD-004/005

Command:

```bash
.venv/bin/python evals/knowledge_base/run_answer_context_shadow_eval.py \
  --evalset evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6_triage_fix.jsonl \
  --sample-id C6A-MD-004 \
  --sample-id C6A-MD-005 \
  --top-ks 3,5,8 \
  --output-json evals/knowledge_base/reports/answer_30q_context_shadow_c6a_md_004_005_20260612.json
```

Result:

- `C6A-MD-004`
  - `top_k=3` missing: `应用连接池 active / idle / wait||连接池 active / idle / wait`
  - `top_k=5` missing: none
  - `top_k=8` missing: none
- `C6A-MD-005`
  - `top_k=3` missing: `docker compose -f aiops_lab/docker-compose.yml up --build`, `Prometheus: http://localhost:9090||Alertmanager: http://localhost:9093`
  - `top_k=5` missing: none
  - `top_k=8` missing: none

Conclusion: both C6 context-missing samples are confirmed top-3 chunk-shape issues. They are candidates for a narrow top_k=5 Answer rerun, but this does not justify a global default `top_k` change.

### Remaining Context-Missing Samples

Command:

```bash
.venv/bin/python evals/knowledge_base/run_answer_context_shadow_eval.py \
  --evalset evals/knowledge_base/evalsets/department_rag_answer_30q_after_c6_triage_fix.jsonl \
  --sample-id S5P1-MD-002 \
  --sample-id S5P1-PDF-004 \
  --sample-id S5P1-PDF-009 \
  --top-ks 3,5,8 \
  --output-json evals/knowledge_base/reports/answer_30q_context_shadow_remaining_context_missing_20260612.json
```

Result:

- `S5P1-MD-002`
  - `top_k=3` missing: `查询最近15分钟 application-logs`, `关注 ERROR、FATAL 或 status:500`, `检查 restart/crash/oom_kill 和依赖服务状态`
  - `top_k=5` missing: none
  - `top_k=8` missing: none
- `S5P1-PDF-004`
  - `top_k=3` missing: `AWS`, `Kubernetes`, `Sentry`, `414`
  - `top_k=5` missing: `414`
  - `top_k=8` missing: `414`
- `S5P1-PDF-009`
  - `top_k=3` missing: `Folder Structure`, `Control-Plane`, `Pods`
  - `top_k=5` missing: same
  - `top_k=8` missing: same

Conclusion: one old Markdown sample (`S5P1-MD-002`) joins the top_k=5 context candidate pool. The two Scoutflo PDF samples are not solved by top_k=5 or top_k=8; they need separate PDF/source-support/chunking review, not a simple top-k change.

### Answer-Missing / OpenJudge Follow-Up

OpenJudge high-score scan on the 7 remaining `answer_missing_facts` samples found no new clean synonym false negative. The highest correctness score among answer-missing samples is 4.0, and the reasons still point to real omitted deterministic facts or broader answer-generation omissions.

Conclusion:

- Do not add new synonyms from this scan.
- Do not loosen `Quick Links` to generic `链接`.
- Do not change the Answer prompt globally from this evidence.

## Decision After Context Shadow

- Current deterministic baseline remains 18/30.
- Three samples are now context candidates for a narrow top_k=5 Answer rerun:
  - `C6A-MD-004`
  - `C6A-MD-005`
  - `S5P1-MD-002`
- If all three pass in a dedicated Answer rerun, the theoretical ceiling is 21/30, but that still must be proven with actual answer generation.
- `S5P1-PDF-004` and `S5P1-PDF-009` should not be included in a top_k-only fix claim.

## 3q Sample-Local Top-K=5 Answer Shadow

Derived evalset:

- `evals/knowledge_base/evalsets/department_rag_answer_3q_top_k5_shadow.jsonl`

Construction:

- source: `department_rag_answer_30q_after_c6_triage_fix.jsonl`
- selected samples: `C6A-MD-004`, `C6A-MD-005`, `S5P1-MD-002`
- only sample-level change: `top_k=5`
- added `shadow_note=sample_local_top_k5_answer_shadow; does_not_change_global_default_top_k`

Command:

```bash
.venv/bin/python evals/knowledge_base/run_department_rag_answer_eval.py \
  --evalset evals/knowledge_base/evalsets/department_rag_answer_3q_top_k5_shadow.jsonl \
  --report evals/knowledge_base/reports/department_rag_answer_3q_top_k5_shadow_20260612.json
```

Result:

- total: 3
- passed: 1
- failed: 2
- not_ready: 0
- pass rate: 33.33%
- failure categories:
  - `passed`: 1
  - `answer_missing_facts`: 2

Sample results:

- `C6A-MD-004`: failed as `answer_missing_facts`
  - context_missing: none
  - answer_missing: `connection timeout`
- `C6A-MD-005`: passed
- `S5P1-MD-002`: failed as `answer_missing_facts`
  - context_missing: none
  - answer_missing: `查询最近15分钟 application-logs`, `检查 restart/crash/oom_kill 和依赖服务状态`

Decision:

- The 3q shadow proves context coverage is necessary but not sufficient for Answer pass.
- Sample-local `top_k=5` would only contribute +1 proven pass from this run, not the +3 needed to reach 21/30.
- Do not create a 30q top_k=5 promoted evalset from this evidence.
- Do not change global `top_k`.
- If Answer work continues, the next issue is answer generation completeness, not retrieval context coverage alone.
