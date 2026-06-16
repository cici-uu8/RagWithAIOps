# AGENTS.md

Scope: `/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21`

## 0. CodeGraph Project Path

- For CodeGraph queries for this project, always use `projectPath="/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"`.
- Do not query the parent directory `/Users/cici/oncall agent` as the CodeGraph project; that directory contains multiple projects and is not the intended CodeGraph index target for this repo.

## 1. Default Development Rule

- Prefer reusing mature code from `/Users/cici/oncall agent/WeKnora` before inventing new implementation.
- For RAG, document ingestion, chunking, parser routing, knowledge base, retrieval, citation, and artifact handling, first search the local WeKnora clone for an existing service, model, handler, or infrastructure boundary that can be adapted.
- Make the smallest possible change to this repo so existing functionality stays intact unless the user explicitly asks for behavior changes.

## 2. Reuse Policy

- If WeKnora already has a working pattern, adapt it here instead of re-creating it from scratch.
- Prefer copying the mature abstraction boundary, then trimming it to the smallest shape needed for this repo.
- Do not introduce new parallel frameworks, data models, or pipeline conventions if an equivalent WeKnora implementation already exists.
- If direct reuse is not possible, document the reason in `PROJECT_STATE.md` and keep the delta minimal.

## 3. Safety Boundary

- Do not break current user-facing behavior while introducing reusable code.
- Keep documentation, artifact contracts, and code paths aligned.
- Treat `docs/rag_ingestion_artifact_contract.md` as the hard P1/P2 ingestion contract.

## 4. Development Recording Rule

- Every meaningful development step must be recorded in `docs/rag_fusion_development_record.md`.
- For OpenViking-style durable memory work, record the memory-specific process in `docs/memory_fusion_development_record.md`; keep `docs/rag_fusion_development_record.md` for RAG / WeKnora fusion work.
- Recording is not optional cleanup after coding; it is part of the implementation work itself.
- For each step, record at least:
  - why the step is being done now,
  - what files or modules were changed,
  - what problem or risk appeared,
  - how it was resolved or intentionally deferred,
  - how to explain the step in project-review or interview settings.
- The record must include concrete code-level evidence, not only summary language.
- For any non-trivial implementation step, include examples such as:
  - what the old code/model structure looked like,
  - what exact class/field/function was added or changed,
  - why that exact code shape was chosen over nearby alternatives,
  - what command or check was used to verify the step.
- For interview-facing project work, also record:
  - the most likely follow-up question an interviewer would ask about the step,
  - a concrete answer grounded in the actual code change and tradeoff,
  - enough implementation detail that the answer sounds like real development rather than retrospective summary.
- When a task is only partially completed, blocked, or rolled back, that must also be recorded explicitly.
- If a future agent changes plan order, assumptions, or technical route, update both the development record and the governing planning docs so the written history stays aligned with the actual implementation path.


<!-- CAT-CAFE-GOVERNANCE-START -->
> Pack version: 1.4.0 | Provider: codex

## Cat Cafe Governance Rules (Auto-managed)

### Hard Constraints (immutable)
- **Public local defaults**: use frontend 3003 and API 3004 to avoid colliding with another local runtime.
- **Redis port 6399** is Cat Cafe's production Redis. Never connect to it from external projects. Use 6398 for dev/test.
- **No self-review**: The same individual cannot review their own code. Cross-family review preferred.
- **Identity is constant**: Never impersonate another cat. Identity is a hard constraint.

### Collaboration Standards
- A2A handoff uses five-tuple: What / Why / Tradeoff / Open Questions / Next Action
- Vision Guardian: Read original requirements before starting. AC completion ≠ feature complete.
- Review flow: quality-gate → request-review → receive-review → merge-gate
- Skills are available via symlinked cat-cafe-skills/ — load the relevant skill before each workflow step
- Shared rules: See cat-cafe-skills/refs/shared-rules.md for full collaboration contract

### Quality Discipline (overrides "try simplest approach first")
- **Bug: find root cause before fixing**. No guess-and-patch. Steps: reproduce → logs → call chain → confirm root cause → fix
- **Uncertain direction: stop → search → ask → confirm → then act**. Never "just try it first"
- **"Done" requires evidence** (tests pass / screenshot / logs). Bug fix = red test first, then green

### Knowledge Engineering
- Documents use YAML frontmatter (feature_ids, topics, doc_kind, created)
- Three-layer info architecture: CLAUDE.md (≤100 lines) → Skills (on-demand) → refs/
- Backlog: BACKLOG.md (hot) → Feature files (warm) → raw docs (cold)
- Feature lifecycle: kickoff → discussion → implementation → review → completion
- SOP: See docs/SOP.md for the 6-step workflow
<!-- CAT-CAFE-GOVERNANCE-END -->
