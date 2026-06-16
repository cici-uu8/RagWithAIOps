# S4-P2.3 Rank-Gap C-Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an observation-only C-probe that evaluates the 8 residual `rank_gap` samples from the mixed 50q baseline and reports whether temporary rerank promotion is strong enough to justify a formal C evalset.

**Architecture:** Reuse the existing `build_retrieval_mode_comparison_report()` path so dense/hybrid/hybrid_rerank comparisons stay consistent with earlier shadow reports. The new probe module will own three things only: a hardcoded 8-sample whitelist from the repaired 50q evalset, a temporary in-process rerank enable/restore boundary, and a probe-specific verdict classifier (`rank_lift_proven` / `rank_observation_only` / `no_rank_lift`). It will not change `app/config.py`, `.env`, or the normal four-mode comparison runner.

**Tech Stack:** Python, pytest, existing `evals/knowledge_base` report helpers, `app.services.rerank_service.rerank_service`, JSON/Markdown report writers already used by other checklist probes.

---

### Task 1: Freeze the probe contract with failing tests

**Files:**
- Create: `tests/test_checklist4_s4_p23_rank_gap_c_probe.py`
- Create: `evals/knowledge_base/checklist4_s4_p23_rank_gap_c_probe.py`

- [ ] **Step 1: Write the failing test for verdict classification**

```python
def test_classify_rank_gap_candidate_assigns_expected_verdicts():
    from evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe import _classify_rank_gap_candidate

    proven_row = {
        "sample_id": "S4M-A-012",
        "query": "CPUThrottlingHigh 告警什么时候需要处理",
        "dense_only": {"doc_ids": ["doc-other", "doc-target"]},
        "hybrid": {"doc_ids": ["doc-other", "doc-target"]},
        "hybrid_rerank": {"doc_ids": ["doc-target", "doc-other"], "results": [{"metadata": {"rerank_status": "applied"}}]},
    }
    observation_row = {
        "sample_id": "S4M-B-001",
        "query": "PagerDuty 文档提到哪些 incident response training",
        "dense_only": {"doc_ids": ["doc-other", "doc-target"]},
        "hybrid": {"doc_ids": ["doc-other", "doc-target"]},
        "hybrid_rerank": {"doc_ids": ["doc-other", "doc-target"], "results": [{"metadata": {"rerank_status": "applied"}}]},
    }
    no_lift_row = {
        "sample_id": "S4M-B-008",
        "query": "Scoutflo SRE Playbooks 覆盖哪些平台和用途",
        "dense_only": {"doc_ids": ["doc-other"]},
        "hybrid": {"doc_ids": ["doc-other"]},
        "hybrid_rerank": {"doc_ids": ["doc-other"]},
    }

    assert _classify_rank_gap_candidate(proven_row, expected_doc_ids={"doc-target"}, top_k=3)["verdict"] == "rank_lift_proven"
    assert _classify_rank_gap_candidate(observation_row, expected_doc_ids={"doc-target"}, top_k=3)["verdict"] == "rank_observation_only"
    assert _classify_rank_gap_candidate(no_lift_row, expected_doc_ids={"doc-target"}, top_k=3)["verdict"] == "no_rank_lift"
```

Run: `uv run pytest tests/test_checklist4_s4_p23_rank_gap_c_probe.py -q`

Expected: FAIL on import because `checklist4_s4_p23_rank_gap_c_probe.py` does not exist yet.

- [ ] **Step 2: Write the failing test for temporary rerank restore**

```python
def test_build_rank_gap_c_probe_report_restores_rerank_enabled(monkeypatch, tmp_path):
    from app.services.rerank_service import rerank_service
    from evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe import build_rank_gap_c_probe_report

    evalset = tmp_path / "evalset.jsonl"
    evalset.write_text(
        '{"sample_id":"S4M-A-012","query":"CPUThrottlingHigh 告警什么时候需要处理","allowed_kb_ids":["process_digital_dept"],"expected_doc_ids":["doc-target"],"expected_answer_keywords":["CPU Throttling High"],"scope":"scoped","retrieval_mode":"dense_only","top_k":3}\n',
        encoding="utf-8",
    )

    original_enabled = rerank_service.enabled

    def fake_build(*args, **kwargs):
        assert rerank_service.enabled is True
        return {
            "generated_at": "2026-06-10T00:00:00Z",
            "modes": ["dense_only", "hybrid", "hybrid_rerank"],
            "summary": {
                "total": 1,
                "mode_result_counts": {"dense_only": 1, "hybrid": 1, "hybrid_rerank": 1},
                "mode_not_ready_counts": {"dense_only": 0, "hybrid": 0, "hybrid_rerank": 0},
                "mode_wrong_scope_counts": {"dense_only": 0, "hybrid": 0, "hybrid_rerank": 0},
                "mode_citation_incomplete_counts": {"dense_only": 0, "hybrid": 0, "hybrid_rerank": 0},
                "mode_expected_doc_found_counts": {"dense_only": 1, "hybrid": 1, "hybrid_rerank": 1},
                "latency_ms_by_mode": {"dense_only": {"avg": 1, "p95": 1, "max": 1}, "hybrid": {"avg": 1, "p95": 1, "max": 1}, "hybrid_rerank": {"avg": 1, "p95": 1, "max": 1}},
                "rerank_status_counts_by_mode": {"hybrid_rerank": {"applied": 1}},
                "wrong_scope_count": 0,
                "not_ready_count": 0,
                "citation_incomplete_count": 0,
                "dense_result_count": 1,
                "hybrid_result_count": 1,
                "hybrid_added_result_count": 0,
            },
            "comparison": {"doc_overlap_matrix": {}, "rank_diff_matrix": {}},
            "samples": [],
        }

    monkeypatch.setattr(
        "evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe.build_retrieval_mode_comparison_report",
        fake_build,
    )
    report = build_rank_gap_c_probe_report(evalset_path=evalset, sample_ids=["S4M-A-012"], enable_true_rerank=True)

    assert rerank_service.enabled == original_enabled
    assert report["scope"]["temporary_rerank_enablement"] is True
```

Run: `uv run pytest tests/test_checklist4_s4_p23_rank_gap_c_probe.py -q`

Expected: FAIL because the probe module and restoration behavior are still missing.

---

### Task 2: Implement the observation-only probe runner

**Files:**
- Create: `evals/knowledge_base/checklist4_s4_p23_rank_gap_c_probe.py`
- Modify: `evals/knowledge_base/retrieval_mode_comparison_report.py` only if a tiny helper is absolutely needed for report shape reuse; prefer not to touch it.

- [ ] **Step 1: Implement the probe module with the smallest possible surface**

```python
RANK_GAP_SAMPLE_IDS = [
    "S4M-A-012",
    "S4M-B-001",
    "S4M-B-008",
    "S4M-B-009",
    "S4M-C-003",
    "S4M-D-001",
    "S4M-E-004",
    "S4M-E-006",
]
```

Core behavior to implement:

```python
def build_rank_gap_c_probe_report(
    *,
    evalset_path: str | Path = "evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl",
    sample_ids: list[str] | None = None,
    retrieval_service=None,
    min_effective_samples: int = 6,
    enable_true_rerank: bool = True,
) -> dict[str, Any]:
    ...
```

Expected flow:

1. Load the formal 50q JSONL with the existing `load_evalset()` helper.
2. Filter to the explicit 8 `sample_ids` whitelist.
3. Temporarily set `rerank_service.enabled = True` only for the `build_retrieval_mode_comparison_report()` call.
4. Run `dense_only`, `hybrid`, and `hybrid_rerank` only.
5. Classify each row with:

```python
if not applied:
    verdict = "no_true_rerank"
elif hybrid_rerank_rank is None or hybrid_rerank_rank > top_k:
    verdict = "no_rank_lift"
elif hybrid_rank is None and hybrid_rerank_rank <= top_k:
    verdict = "rank_lift_proven"
elif hybrid_rerank_rank < hybrid_rank:
    verdict = "rank_lift_proven"
elif hybrid_rerank_rank == hybrid_rank:
    verdict = "rank_observation_only"
else:
    verdict = "no_rank_lift"
```

6. Aggregate counts and emit a JSON/Markdown report with `verdict_counts`, `guardrail_clean`, `true_rerank_applied`, `eligible_for_formal_evalset`, `default_switch_eligibility = not_eligible_for_default_switch`, and per-sample ranks.
7. Restore `rerank_service.enabled` in a `finally` block even if report generation fails.

Expected CLI:

```bash
uv run python -m evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe \
  --output-json evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.json \
  --output-md evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.md
```

- [ ] **Step 2: Run the probe tests and confirm they pass**

Run:

```bash
uv run pytest tests/test_checklist4_s4_p23_rank_gap_c_probe.py -q
```

Expected: PASS with the new probe module in place.

Then run the smoke report generation against the real formal 50q evalset:

```bash
uv run python -m evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe \
  --output-json evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.json \
  --output-md evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.md
```

Expected: JSON and MD reports are written, `rerank_service.enabled` returns to its original value, and the report status is either `formal_value_proven` or `observation_only`.

- [ ] **Step 3: Keep the probe output isolated from defaults**

No code snippet here. This is a hard verification step: inspect the module and confirm it does **not** write to `app/config.py`, `.env`, or any runtime config file, and it restores `rerank_service.enabled` even on exceptions.

Run: `git diff --check && uv run python -m evals.knowledge_base.checklist4_s4_p23_rank_gap_c_probe --help`

Expected: clean diff check and CLI help showing only probe-specific flags.

---

### Task 3: Sync the durable project state after the smoke run

**Files:**
- Modify: `PROJECT_STATE.md`
- Modify: `docs/rag_fusion_development_record.md`
- Modify: `docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`
- Modify: `docs/RAG_QueryRewrite_清单4_S4-P2.2_Mixed_50q失败样本分流分析.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

- [ ] **Step 1: Record the probe result in the source-of-truth docs**

Update the state files with the actual probe conclusion, using the real report summary:

```text
rank_gap probe = 8 samples
rank_lift_proven = <actual count>
rank_observation_only = <actual count>
no_rank_lift = <actual count>
decision = observation_only or formal_value_proven
default_switch_eligibility = not_eligible_for_default_switch
```

Do **not** claim a formal C evalset unless the probe actually meets the `>= 6/8` threshold and the guardrails stay clean.

- [ ] **Step 2: Add the probe artifacts to the RAG dev record**

Append a short entry that answers:

1. Why the probe was needed now.
2. Which 8 sample_ids were included.
3. Whether rerank was temporarily enabled only in-process.
4. Whether rerank had formal value or only observation-only value.
5. What the next step is for expression-gap expansion.

- [ ] **Step 3: Re-run formatting and safety checks**

Run:

```bash
git diff --check
```

Expected: no whitespace / patch formatting issues.

If the probe wrote a report, also verify the new files exist:

```bash
python3 - <<'PY'
from pathlib import Path
for path in [
    Path('evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.json'),
    Path('evals/knowledge_base/reports/checklist4_s4_p23_rank_gap_c_probe_20260610.md'),
]:
    print(path, path.exists())
PY
```

Expected: `True` for both files if the smoke run completed.

---

## Self-Review Checklist

- [ ] The probe module is separate from `retrieval_mode_comparison_report.py`.
- [ ] The probe restores `rerank_service.enabled` after every run.
- [ ] The probe only touches the 8 explicit residual `rank_gap` sample ids.
- [ ] The probe report can say `formal_value_proven` only when `rank_lift_proven >= 6`.
- [ ] No task changes `app/config.py`, `.env`, or default retrieval mode.
- [ ] Docs/state updates are limited to post-smoke fact capture, not speculative decisions.
