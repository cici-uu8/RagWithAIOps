# RAG Production Readiness Checklist

日期：2026-06-12

状态：`internal_beta_execution_ready`

## 1. Scope

本清单用于把当前 RAG MVP 基线推进到小范围生产 beta。

当前目标不是正式 GA，不扩大 Answer gate，不改变 retrieval 默认值。

输入基线：

```text
MVP baseline = docs/RAG_MVP_Baseline_20260612.md
Beta readiness = docs/RAG_Beta_Readiness_生产试运行闭环.md
User feedback loop = docs/RAG_Beta_User_Feedback_Log.md
Internal beta runbook = docs/RAG_Internal_Beta_Runbook_20260612.md
```

默认禁止项：

```text
do_not_create_answer_50q = true
do_not_enter_agent_behavior = true
do_not_enable_openjudge_or_ragas_gate = true
do_not_change_rag_default_retrieval_mode = true
do_not_enable_query_rewrite = true
do_not_enable_rerank = true
do_not_default_hybrid = true
```

## 2. Phase 1 - Baseline And Dependency Lock

| item | status | evidence / command | decision |
|---|---|---|---|
| MVP baseline documented | `done` | `docs/RAG_MVP_Baseline_20260612.md` | current baseline accepted for beta |
| `uv.lock` reviewed | `done` | `git diff uv.lock`; TOML package comparison | only registry URL mirror rewrite, no package/version/dependency change |
| `uv.lock` restored | `done` | `git restore uv.lock` | do not commit local mirror URL churn |
| default config locked | `done` | `tests/test_beta_readiness_smoke.py`, `app/config.py` | `dense_only / off / false / top_k=3` |
| unrelated local assets isolated | `done` | `git status --short` | `data/knowledge_assets/` remains untracked and out of beta readiness commit |
| internal beta runbook documented | `done` | `docs/RAG_Internal_Beta_Runbook_20260612.md` | runbook connects launch-day smoke, seed users, monitoring, feedback, and stop/continue rules |

Dependency lock decision:

```text
pyproject_changed = false
dependency_versions_changed = false
uv_lock_package_set_changed = false
uv_lock_restored = true
```

## 3. Phase 2 - Minimum Runtime Smoke

Required before every beta/demo check:

```bash
.venv/bin/python -m evals.knowledge_base.beta_readiness_smoke \
  --output evals/knowledge_base/reports/beta_readiness_smoke_YYYYMMDD.json
```

Current evidence:

```text
report = evals/knowledge_base/reports/beta_readiness_smoke_20260612.json
status = passed
check_count = 7
passed_count = 7
failed_count = 0
external_llm_called = false
external_vector_db_called = false
```

Checks covered:

- auth login
- controlled RAG Q&A
- source_ref lookup
- permission filtering
- audit logging
- feedback schema
- config defaults

## 4. Phase 3 - Retrieval And Answer Gates

Retrieval gate:

| check | target | current | status |
|---|---:|---:|---|
| Mixed retrieval pass rate | `>=80%` | `45/54 = 83.3%` | `passed` |
| not_ready | `0` | `0` | `passed` |
| wrong_scope_count | `0` | `0` | `passed` |
| citation_unresolvable_count | `0` | `0` | `passed` |
| all_source_ref_resolvable | `true` | `true` | `passed` |

Answer gate:

| check | target | current | status |
|---|---:|---:|---|
| Answer hard safety gates | clean | clean | `passed` |
| unsupported_claim_count | `0` | `0` | `passed` |
| permission_leak_count | `0` | `0` | `passed` |
| source_ref_unresolvable_count | `0` | `0` | `passed` |
| retrieval_layer_failed_count | `0` | `0` | `passed` |
| Answer completeness | observation | `18/30 = 60%` | `limited` |

Decision:

```text
retrieval_ready_for_beta = true
answer_safe_but_limited = true
answer_ready_for_agent_behavior = false
```

## 5. Phase 4 - Rollback Readiness

Current rollback evidence:

| capability | status | evidence |
|---|---|---|
| PDF Agent tools | local rollback drill recorded | `docs/B4 PDF Agent 工具生产启用与回滚记录.md` |
| RAG default config | source defaults remain conservative | `app/config.py`, beta smoke config defaults |
| OpenJudge | shadow-only; no production gate rollback needed | `docs/OpenJudge_Shadow_Eval_Integration_Design.md` |
| query rewrite / rerank / hybrid | disabled by default | no production enablement |

Still required before broader production:

- target environment owner approval
- rollback owner and time window
- exact config keys and service restart path
- post-rollback smoke command
- incident criteria for rollback

## 6. Phase 5 - Performance Baseline

Current status: `pending`.

Minimum beta performance baseline should record:

| metric | required | source |
|---|---|---|
| retrieval latency p50/p95 | yes | retrieval runner or service trace |
| controlled beta smoke runtime | yes | beta readiness smoke |
| live answer generation latency p50/p95 | yes if live LLM enabled | live `/api/chat` observation |
| source_ref lookup latency | optional | smoke / metadata store trace |
| error rate | yes | app logs / audit |

Do not block the current MVP baseline on missing performance numbers, but do not call this production GA until this section has real data.

## 7. Phase 6 - Monitoring And Feedback

Feedback path:

```text
docs/RAG_Internal_Beta_Runbook_20260612.md
docs/RAG_Beta_User_Feedback_Log.md
docs/schemas/rag_user_feedback.schema.json
```

Required fields:

- original query
- retrieved docs
- answer
- answer_issue
- missing_facts
- source_ref_resolvable
- permission_scope_issue
- followup_decision

Trigger thresholds:

| trigger | action |
|---|---|
| 3+ confirmed `answer_incomplete` | reopen narrow Answer revisit |
| 3+ confirmed `retrieval_no_hit` / `retrieval_wrong_doc` | reopen retrieval triage |
| any permission/scope issue | security bug first |
| repeated source_ref unresolvable | citation/source_ref bug first |

## 8. Beta Launch Checklist

Before starting or expanding beta:

- [x] MVP baseline documented.
- [x] Dependency lock checked; no package changes accepted.
- [x] Default config locked to `dense_only / off / false`.
- [x] Beta readiness smoke exists and has current passing evidence.
- [x] Retrieval baseline is above 80%.
- [x] Answer hard safety gates are clean.
- [x] Feedback log and schema exist.
- [x] Internal beta runbook exists.
- [x] Week 1 seed feedback is recorded and below optimization trigger thresholds.
- [x] Run fresh beta smoke for the current runbook check.
- [x] Select initial 3-5 internal beta user roles.
- [ ] Confirm users do not paste secrets or production sensitive data.
- [ ] Record start date, owner, and review cadence.
- [ ] Collect one full week of feedback for the next beta cycle.
- [x] Review recorded seed feedback using the weekly template.

## 9. Launch Decision Rules

Continue beta if:

```text
average_satisfaction >= 3.5
retrieval_success_rate >= 80%
source_ref_unresolvable_cluster = false
permission_scope_issue = false
```

Pause or narrow beta if:

```text
permission_scope_issue = true
source_ref_unresolvable_cluster = true
retrieval_failure_rate > 40%
average_satisfaction < 2.5
```

Open targeted optimization if:

```text
same_issue_type_confirmed_count >= 3
reproducible = true
source_ref_evidence_present = true
```

## 10. Current Recommendation

Proceed to small internal beta using the current MVP baseline.

Do not continue synthetic evalset optimization by default. The next useful evidence should come from real beta feedback, not from further broadening Answer or Retrieval evalsets without a clustered failure trigger.
