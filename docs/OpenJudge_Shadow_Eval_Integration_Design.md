# OpenJudge Shadow Eval Integration Design

## 1. Positioning

OpenJudge is introduced only as an Answer-layer shadow evaluator. It supplements
the existing deterministic gates with LLM-as-judge quality signals, but it is not
the main evaluation baseline and must not decide pass/fail.

The main gate remains:

- Retrieval and citation contract: `expected_doc_ids`, `source_ref`, scope,
  citation resolvability, and retrieval failure category.
- Answer hard gate: `must_include_facts`, `required_citations`,
  `must_not_include_claims`, permission leakage, and source-ref integrity.
- Agent behavior contract: `TrajectoryMatcher`, audit events, task contracts,
  SSE contract, DB-agent expectations, and AIOps failure semantics.

OpenJudge output is allowed to answer a different question: whether the generated
answer looks relevant, faithful, correct against a reference answer, and aligned
with the prompt policy. That signal is useful for review and diagnosis, but it is
not strong enough to replace project-specific evidence checks.

## 2. Non-Goals

- Do not modify `run_department_rag_answer_eval.py`.
- Do not change `passed`, `failed`, `hard_gate_passed`, or any existing baseline
  report.
- Do not enable RAGAS, query rewrite, rerank, hybrid retrieval, or a new default
  `top_k`.
- Do not write OpenJudge scores back into the Answer baseline.
- Do not treat OpenJudge score thresholds as release gates.

## 3. Runner Shape

Add an independent runner:

```text
evals/knowledge_base/run_openjudge_answer_shadow_eval.py
```

The runner reads:

- an existing Answer baseline report, normally
  `evals/knowledge_base/reports/department_rag_answer_pilot_20q_baseline_after_s5_p31_repair_20260611.json`;
- the matching Answer evalset, normally
  `evals/knowledge_base/evalsets/department_rag_answer_pilot_20q.jsonl`.

The runner writes a new report under `evals/knowledge_base/reports/` and never
updates the source baseline.

Each row keeps the deterministic result separate from the shadow result:

```json
{
  "sample_id": "S5P1-MD-001",
  "deterministic": {
    "status": "failed",
    "failure_category": "answer_missing_facts",
    "answer_missing_facts": 2,
    "unsupported_claim_count": 0,
    "context_missing_facts": 0
  },
  "openjudge_shadow": {
    "relevance": {"status": "scored", "score": 4.0},
    "hallucination": {"status": "scored", "score": 3.0, "confidence": "low"},
    "correctness": {"status": "scored", "score": 2.0},
    "instruction_following": {"status": "scored", "score": 3.0}
  }
}
```

If the baseline report lacks full `context_text`, context-dependent scores remain
shadow-only and are marked with lower confidence. The runner must record the
missing input instead of silently pretending that the score has full evidence.

## 4. Correlation Analysis

The first useful analysis is correlation between OpenJudge scores and existing
deterministic error counts:

- `answer_missing_facts`
- `unsupported_claim_count`
- `context_missing_facts`

The report may compute Pearson correlation when at least two scored samples and
non-constant values are available. Missing or constant series must be reported as
`null`, not converted into a fake score.

The correlation result is diagnostic only:

- high correlation can increase confidence that OpenJudge is useful for review;
- low correlation means the grader, prompt, or input mapping needs adjustment;
- neither result changes the deterministic gate.

## 5. Dependency Boundary

The runner should support dependency injection for tests and local dry runs.
Real OpenJudge imports happen only when the default provider is used. This keeps
the main project install path and existing eval tests independent from
`py-openjudge` unless the user explicitly runs the shadow evaluator with that
dependency installed.

If `py-openjudge` or judge model credentials are unavailable, the runner should
fail clearly or produce a not-ready shadow report, but it must not affect the
Answer baseline.

## 6. Acceptance

This integration is acceptable when:

- the design document states OpenJudge is shadow-only;
- the runner can build a report from a baseline report and evalset;
- the report preserves deterministic pass/fail separately from OpenJudge scores;
- the report states that shadow scores do not affect pass/fail;
- tests cover report construction, missing-context handling, and file writing;
- no production config or main gate is modified.
