# Memory Operator Frontend Design

日期: 2026-06-16

状态: P0b 已实现。最终采用 admin-console 集成方案，不创建独立 `static/memory-operator.*`。

## 目标

为 P0a Memory Operator API 创建最小 operator review UI，复用现有管理后台认证、导航、API client 和样式。该 UI 只服务 review queue、Gate A.2 validation status 和 deprecation preview，不表示 Memory 已进入主链路或产品化完成。

## 设计原则

1. 在 `static/admin-console.html` / `static/admin-console.js` 中新增 `memory-operator` route。
2. 复用 `EnterpriseApiClient` / `adminFetch(...)`，不单独实现 token 或 fetch 逻辑。
3. 复用现有 `admin-*` / `ea-*` 样式，只在 `admin-console.css` 中补通用 `admin-tabs` 和 panel 样式。
4. approve/reject 前端只提交 `decision_note`；`reviewer_id` 必须由后端 `RequestContext.user_id` 派生。
5. Deprecation 在 UI 中只做 preview，不提供 owner deprecate 执行按钮。

## 最终实现

### JavaScript

文件: `static/admin-console.js`

- `routeKeys` / `navItems` 新增 `memory-operator`。
- `data()` 新增 `memoryOperator` 状态:
  - `activeTab`
  - `reviewQueue`
  - `reviewQueueMeta`
  - `validationStatus`
  - `deprecationPreview`
- `forms.memoryOperator` 保存 owner / limit 输入。
- `loadMemoryReviewQueue()` 调用:

```text
GET /api/admin/memory-operator/review-queue?owner_id=<owner>&limit=<limit>
```

- `loadMemoryValidationStatus()` 调用:

```text
GET /api/admin/memory-operator/validation-status?owner_id=<owner>
```

- `previewMemoryDeprecation()` 调用:

```text
POST /api/admin/memory-operator/deprecation-preview
body: {"owner_id": "<owner>"}
```

- `decideMemory(memory, decision)` 调用:

```text
POST /api/admin/memory-operator/atoms/{memory_id}/{approve|reject}
body: {"decision_note": "<operator note>"}
```

### HTML

文件: `static/admin-console.html`

新增 `route === 'memory-operator'` 内容区，包含:

- 警告横幅:

```text
⚠️ Memory 当前默认关闭（memory_mode=off），此界面仅供 operator review
```

- `Review Queue` tab: owner/limit 查询、candidate/conflict 表格、decision note、Approve/Reject。
- `Validation Status` tab: owner 查询、Gate A.2、diagnosis count、remaining、milestone、prompt integration。
- `Deprecation Preview` tab: owner 查询、rollback action、records_to_deprecate、destructive_delete、records 列表。

### CSS

文件: `static/admin-console.css`

- 新增 `.admin-tabs`，用于 admin console 内 tab 切换。
- 新增 `.memory-operator-panel`，用于三段 Memory Operator 内容区布局。

## 不做

- 不做独立 `static/memory-operator.html` / `.js` / `.css`。
- 不做全 L0/L1/L2 Explorer。
- 不做 Memory 自动 promotion。
- 不把 durable memory 注入 RAG/AIOps 主 prompt。
- 不在 UI 中执行 owner deprecate；批量治理动作仍需受控 API/CLI 二次确认。

## 验收标准

1. admin-console 左侧 nav 显示 `Memory Operator`。
2. 点击后显示 Memory Operator 内容区。
3. 页面顶部显示 memory 默认关闭警告。
4. 三个 tab 可切换: Review Queue / Validation Status / Deprecation Preview。
5. Review Queue 可加载列表，Approve/Reject 后刷新 queue。
6. 前端 approve/reject 请求体不包含 `reviewer_id`。
7. Validation Status 可查询 Gate A.2 状态。
8. Deprecation Preview 只读展示 owner-scoped deprecation plan。
9. 所有 API 调用复用 `EnterpriseApiClient` / `adminFetch(...)`。

## 验证

```bash
node --check static/admin-console.js
uv run pytest tests/test_assistant_frontend_optimization.py tests/test_memory_operator_adapter.py tests/test_memory_operator_routes.py -q --no-cov
uv run ruff check --select F,E9,I tests/test_assistant_frontend_optimization.py
git diff --check -- static/admin-console.js static/admin-console.html static/admin-console.css tests/test_assistant_frontend_optimization.py
```
