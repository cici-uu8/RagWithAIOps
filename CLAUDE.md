# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. Language Preference

**Use Chinese (中文) for all communication with this user.**

- All responses, explanations, and status updates should be in Chinese
- Code comments can remain in English or follow project conventions
- Technical terms can use English when appropriate (e.g., "memory guidance", "baseline flavor")
- Error messages and logs can remain in their original language

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

## 5. Verification Protocol

**Never accept completion claims without reading actual artifacts.**

When the user says work is complete (e.g., "E1 done", "tests passed", "verified"):

**MUST DO before saying "验收通过":**
1. **Read the actual code files**
   - Use `Read` tool to check implementation
   - Verify directory structure with `ls` or `find`
   - Confirm key logic is present

2. **Check test outputs**
   - Read test files to verify coverage
   - If user claims "9/9 passed", look for test output or run summary
   - Don't accept test claims without evidence

3. **Verify documentation sync**
   - Read development record files
   - Check PROJECT_STATE.md updates
   - Confirm task_plan.md reflects completion

4. **Inspect Git commits**
   - Use `git show <commit>` to see actual changes
   - Verify commit message matches claimed work
   - Check file change statistics

5. **Validate claimed results**
   - If "compileall passed", look for output
   - If "smoke test ok", check logs
   - If "X/Y tests passed", verify the numbers

**NEVER DO:**
- ❌ Say "验收通过" based only on user description
- ❌ Assume code exists or is correct without reading it
- ❌ Give "next step" advice without verifying current step
- ❌ Trust "it works" without seeing evidence

**Example - WRONG:**
```
User: E1 done, 9/9 tests passed
Assistant: ✅ E1 验收通过。下一步做 E2...
```

**Example - RIGHT:**
```
User: E1 done, 9/9 tests passed
Assistant: [reads app/enterprise/auth/*.py]
Assistant: [reads tests/test_enterprise_auth.py]
Assistant: [checks git show <commit>]
Assistant: [reads docs/enterprise_capability_development_record.md]
Assistant: ✅ E1 验收通过。我已确认：
- app/enterprise/auth/ 目录结构正确
- JWT/AuthService 实现完整
- 测试文件包含 119 行，覆盖登录/登出/黑名单
- 文档已同步
下一步是 E2...
```

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


<!-- CAT-CAFE-GOVERNANCE-START -->
> Pack version: 1.4.0 | Provider: claude

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
