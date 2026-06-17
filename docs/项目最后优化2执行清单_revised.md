# 项目最后优化2执行清单（修订版）

## 背景

对照 LangGraph、Langfuse、Supabase、Dify、Semantic Kernel 等成熟项目，当前项目的主要缺口不是底层能力，而是**产品化的可见性、审计、评测和治理层**。本清单聚焦"看得见、管得住"的可见性层，不做全开放写操作，不做无结构扩张。

## 总体原则

1. **只做可见性**：先补 viewer/explorer/dashboard，不先开放写操作
2. **只读优先**：database catalog 只读、memory 只做 operator review UI、audit 只做查询聚合
3. **复用既有代码**：优先复用 P7 memory 代码、E9 audit 代码、admin-console 资源页代码
4. **明确不做边界**：
   - ❌ 全开放 SQL 编辑（只做只读 catalog + safe-select）
   - ❌ Memory 自动 promotion（保持 operator review）
   - ❌ 散装 prompt 目录 / 无结构 skill 文件夹
   - ❌ 成本控制单独立项（等明确花费压力后条件触发）
   - ❌ Skill 工程独立产品化（等明确扩展生态需求后条件触发）
5. **与 Week 6 Review 对齐**：
   - Memory 可见性：当前 Memory `off`，缺 active 审批/长会话 evidence/rollback 记录，**不能称为产品化完成**
   - Database UI：当前只有 sandbox/database-demo，**不是真实 DB UI**
   - 成本/Skill：明确未触发，不提前做

## 优先级（修订后） - 收口状态（2026-06-17）

| 优先级 | 任务 | 投入 | 价值 | 状态 | 验收 |
|---|---|---|---|---|---|
| **P0a** | Memory Operator Read-only API | 小 | 中 | ✅ 完成 | 7/7 测试通过 |
| **P0b** | Memory Explorer UI（降档） | 小 | 中 | ✅ 完成 | 37/37 测试通过 + 浏览器验收 |
| **P1** | Sandbox/Demo DB Catalog Browser | 中 | 高 | ✅ 完成 | 46/46 测试通过 + 浏览器验收 |
| **P2** | Audit/Trace Ops Dashboard | 中 | 高 | ✅ 完成 | 46/46 测试通过 + 浏览器烟测 |
| **P3** | 成本统计（条件触发） | 中 | 中 | ⏸️ **未触发** | 无明确成本压力 |
| **P4** | Skill registry（条件触发） | 大 | 中 | ⏸️ **未触发** | 无明确扩展生态需求 |

**收口决策**：
- ✅ P0/P1/P2 全部完成并验收，进入 Maintenance 模式
- ⏸️ P3 成本统计：触发条件未满足（无明确成本压力、花费统计需求、预算目标）
- ⏸️ P4 Skill Registry：触发条件未满足（无明确扩展生态需求、外部 skill 安装需求）
- 📄 收口总结：`docs/项目最后优化2_收口总结_20260617.md`

---

# P0a: Memory Operator Read-only API（最小控制面）

## 目标

**只暴露 operator 最小控制面**：review queue、validation status、deprecation preview。不做全 L0/L1/L2 Explorer，不做 evidence 列表，不做 scenario 详情。

## 现状

- ✅ 已有：`MemoryReviewService`（review queue/approve/reject）
- ✅ 已有：`MemoryStore.get_validation_policy_status()`（Gate A.2 计数器）
- ✅ 已有：`MemoryReviewService.build_owner_deprecation_plan()`（deprecation preview）
- ❌ 缺失：HTTP API 暴露

## 验收标准

1. operator 可以通过 HTTP API 查询 review queue（需要审批的 candidate/conflict）
2. operator 可以通过 HTTP API approve/reject/deprecate memory
3. operator 可以通过 HTTP API 查询 validation status（Gate A.2 计数器）
4. operator 可以通过 HTTP API preview deprecation plan（不执行）
5. **明确不做**：L0 evidence 列表、L1 atom 全量查询、L2 scenario 详情

## 实现步骤

### Step 1: 后端 Memory Operator HTTP API（最小集）

**目标**：只暴露 operator 最小控制面，不做全量 CRUD。

**文件清单**：
- 新增：`app/enterprise/admin/memory_operator_routes.py`
- 修改：`app/main.py`（挂载 `/api/admin/memory-operator/*` router）

**API 设计（最小集）**：

```python
# Review Queue（只读）
GET /api/admin/memory-operator/review-queue?reviewer_id=&limit=20
  # 返回需要审批的 candidate/conflict 列表
  # [{"memory_id": "...", "memory_type": "...", "status": "candidate", "owner_id": "...", "review_deadline": "..."}, ...]

# Approve/Reject/Deprecate（写操作）
POST /api/admin/memory-operator/atoms/{atom_id}/approve
  body: {"reviewer_id": "...", "decision_note": "..."}
POST /api/admin/memory-operator/atoms/{atom_id}/reject
  body: {"reviewer_id": "...", "decision_note": "..."}
POST /api/admin/memory-operator/atoms/{atom_id}/deprecate
  body: {"reviewer_id": "...", "decision_note": "..."}

# Validation Status（只读）
GET /api/admin/memory-operator/validation-status?owner_id=
  # 返回 Gate A.2 计数器
  # {"owner_id": "...", "total_diagnosis_count": 10, "effective_diagnosis_count": 5, "policy_met": false}

# Deprecation Preview（只读，不执行）
POST /api/admin/memory-operator/deprecation-preview
  body: {"owner_id": "...", "ttl_days": 180}
  # 返回：{"expired_count": 10, "expired_ids": ["mem_001", "mem_002", ...]}

# 明确不做的 API：
# ❌ GET /api/admin/memory-operator/evidence（不做 L0 evidence 列表）
# ❌ GET /api/admin/memory-operator/atoms（不做 L1 atom 全量查询）
# ❌ GET /api/admin/memory-operator/scenarios（不做 L2 scenario 详情）
```

**实现要点**：
1. 所有端点依赖 `CurrentUser` + admin 角色检查
2. 直接调用既有 `MemoryReviewService` 方法，不新增 service 层
3. review-queue 调用 `MemoryReviewService.get_review_queue(...)`
4. validation-status 调用 `MemoryStore.get_validation_policy_status(...)`
5. deprecation-preview 调用 `MemoryReviewService.build_owner_deprecation_plan(...)`（不执行）
6. approve/reject/deprecate 写 `memory_review` audit

**验证**：
```bash
uv run pytest tests/test_memory_operator_routes.py -q --no-cov

# 测试覆盖：
# - admin 可以查询 review queue
# - 非 admin 403
# - approve/reject/deprecate 写 audit
# - validation-status 返回 Gate A.2 计数器
# - deprecation-preview 不删除数据
```

---

### Step 2: P0a 文档与验收

**文件清单**：
- 修改：`PROJECT_STATE.md`（记录 P0a 完成状态）
- 新增：`docs/memory_operator_api_design.md`（设计文档）

**验收标准**：
1. ✅ 后端 API 单元测试全过
2. ✅ curl 手工验收：admin 可以查询 review queue/validation status
3. ✅ approve/reject/deprecate 写 audit
4. ✅ deprecation-preview 不删除数据
5. ✅ **明确标注**：Memory 仍默认 `off`，此 API 仅供 operator review

**完成标志**：
```bash
uv run pytest tests/test_memory_operator_routes.py -q --no-cov

# curl 验收
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:9900/api/admin/memory-operator/review-queue

curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:9900/api/admin/memory-operator/validation-status?owner_id=test_owner
```

---

# P0b: Memory Explorer UI（降档，明确边界）

## 目标

在 P0a API 稳定后，补 operator UI。**明确标注**：Memory 仍默认 `off`，此 UI 仅供 operator review，不是 Memory 产品化完成。

## 现状

- ✅ 已有：P0a Memory Operator API
- ❌ 缺失：operator UI

## 验收标准

1. operator 可以在浏览器中看到 review queue
2. operator 可以在 UI 中 approve/reject/deprecate memory
3. operator 可以查看 validation status（Gate A.2 计数器）
4. operator 可以预览 deprecation plan（不执行）
5. **明确标注**：页面顶部显示 "Memory 当前默认关闭，此界面仅供 operator review"

## 实现步骤

### Step 1: 前端 Memory Operator Console

**目标**：创建最小的 operator 控制台，只包含 review/validation/deprecation 功能。

**文件清单**：
- 新增：`static/memory-operator.html`
- 新增：`static/memory-operator.js`
- 新增：`static/memory-operator.css`
- 修改：`static/admin-console.html`（添加 "Memory Operator" 入口链接）

**页面结构（最小集）**：

```html
<div id="app">
  <!-- 警告横幅 -->
  <div class="warning-banner">
    ⚠️ Memory 当前默认关闭（memory_mode=off），此界面仅供 operator review。
    Memory 产品化需要：active 审批、真实长会话 evidence、rollback/cleanup 运行记录。
  </div>

  <!-- 三个 tab：Review Queue / Validation Status / Deprecation Preview -->
  <div class="tabs">
    <button @click="activeTab='review'">Review Queue</button>
    <button @click="activeTab='validation'">Validation Status</button>
    <button @click="activeTab='deprecation'">Deprecation Preview</button>
  </div>

  <!-- Review Queue -->
  <div v-if="activeTab==='review'">
    <h3>Review Queue (需要审批的 candidate 和 conflict)</h3>
    <table>
      <thead>
        <tr>
          <th>Memory ID</th>
          <th>Memory Type</th>
          <th>Status</th>
          <th>Owner</th>
          <th>Review Deadline</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in reviewQueue" :key="r.memory_id">
          <td>{{ r.memory_id }}</td>
          <td>{{ r.memory_type }}</td>
          <td>{{ r.status }}</td>
          <td>{{ r.owner_id }}</td>
          <td>{{ formatDate(r.review_deadline) }}</td>
          <td>
            <button @click="approveMemory(r.memory_id)">Approve</button>
            <button @click="rejectMemory(r.memory_id)">Reject</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Validation Status -->
  <div v-if="activeTab==='validation'">
    <h3>Validation Status (Gate A.2 计数器)</h3>
    <input v-model="ownerId" placeholder="Owner ID">
    <button @click="loadValidationStatus">Load</button>
    <div v-if="validationStatus">
      <p>Owner: {{ validationStatus.owner_id }}</p>
      <p>Total Diagnoses: {{ validationStatus.total_diagnosis_count }}</p>
      <p>Effective Diagnoses (last 20): {{ validationStatus.effective_diagnosis_count }}</p>
      <p>Policy Met: {{ validationStatus.policy_met ? 'YES' : 'NO' }}</p>
    </div>
  </div>

  <!-- Deprecation Preview -->
  <div v-if="activeTab==='deprecation'">
    <h3>Deprecation Preview（不执行，仅预览）</h3>
    <input v-model="deprecationOwnerId" placeholder="Owner ID">
    <input v-model="ttlDays" type="number" placeholder="TTL Days (default 180)">
    <button @click="previewDeprecation">Preview</button>
    <div v-if="deprecationPreview">
      <p>将过期 {{ deprecationPreview.expired_count }} 条 memory</p>
      <ul>
        <li v-for="id in deprecationPreview.expired_ids.slice(0, 10)" :key="id">{{ id }}</li>
        <li v-if="deprecationPreview.expired_ids.length > 10">... and {{ deprecationPreview.expired_ids.length - 10 }} more</li>
      </ul>
      <p class="warning">⚠️ 此清单暂不支持在 UI 中执行，请使用 CLI 命令执行 deprecation。</p>
    </div>
  </div>
</div>
```

**JS 实现要点**：
```javascript
const app = Vue.createApp({
  data() {
    return {
      activeTab: 'review',
      reviewQueue: [],
      validationStatus: null,
      deprecationPreview: null,
      ownerId: '',
      deprecationOwnerId: '',
      ttlDays: 180
    };
  },
  methods: {
    async loadReviewQueue() {
      const resp = await fetch('/api/admin/memory-operator/review-queue', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('enterpriseAuthToken')}` }
      });
      this.reviewQueue = await resp.json();
    },
    async approveMemory(memoryId) {
      const note = prompt('Decision note:');
      if (!note) return;
      await fetch(`/api/admin/memory-operator/atoms/${memoryId}/approve`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('enterpriseAuthToken')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ reviewer_id: 'current_admin', decision_note: note })
      });
      alert('Approved');
      this.loadReviewQueue();
    },
    async rejectMemory(memoryId) {
      const note = prompt('Decision note:');
      if (!note) return;
      await fetch(`/api/admin/memory-operator/atoms/${memoryId}/reject`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('enterpriseAuthToken')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ reviewer_id: 'current_admin', decision_note: note })
      });
      alert('Rejected');
      this.loadReviewQueue();
    },
    async loadValidationStatus() {
      const resp = await fetch(`/api/admin/memory-operator/validation-status?owner_id=${this.ownerId}`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('enterpriseAuthToken')}` }
      });
      this.validationStatus = await resp.json();
    },
    async previewDeprecation() {
      const resp = await fetch('/api/admin/memory-operator/deprecation-preview', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('enterpriseAuthToken')}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ owner_id: this.deprecationOwnerId, ttl_days: this.ttlDays })
      });
      this.deprecationPreview = await resp.json();
    },
    formatDate(isoStr) {
      return isoStr ? new Date(isoStr).toLocaleString() : 'N/A';
    }
  },
  mounted() {
    this.loadReviewQueue();
  }
});

app.mount('#app');
```

**验证**：
```bash
# 浏览器打开 http://localhost:9900/static/memory-operator.html
# 1. 页面顶部显示警告横幅
# 2. 可以查看 review queue
# 3. 可以 approve/reject memory
# 4. 可以查看 validation status
# 5. 可以 preview deprecation（不执行）
```

---

### Step 2: P0b 文档与验收

**文件清单**：
- 修改：`PROJECT_STATE.md`（记录 P0b 完成状态，明确 Memory 仍未产品化）
- 修改：`docs/memory_operator_api_design.md`（追加 UI 部分）

**验收标准**：
1. ✅ 前端集成测试通过
2. ✅ 浏览器手工验收：operator 可以查看/审批/预览
3. ✅ **警告横幅显示**：Memory 当前默认关闭，此界面仅供 operator review
4. ✅ **不称为产品化完成**：PROJECT_STATE.md 明确标注 Memory 仍未 eligible

**完成标志**：
```bash
uv run pytest tests/test_memory_operator_frontend.py -q --no-cov

# 浏览器验收
# - admin-console 有 "Memory Operator" 入口
# - 页面顶部有警告横幅
# - 可以查看 review queue/validation status/deprecation preview
# - 可以 approve/reject memory
```


---

# P1: Sandbox/Demo DB Catalog Browser（限定范围）

## 目标

**只展示 sandbox/database-demo/已授权 MySQL allowlist**，不叫"真实 DB UI"。复用 admin-console 资源页基础，补独立 catalog + sample row preview。

## 现状

- ✅ 已有：`DatabaseCapabilityCatalogService`（catalog 服务）
- ✅ 已有：`SafeSqlKernel`（SQL 安全检查）
- ✅ 已有：`/api/database/safe-select`（安全 SELECT 端点）
- ✅ 已有：admin-console 资源页（按 table 分组展示 `database_table/database_column`）
- ✅ 已有：`ToolGateway.execute("database_demo.safe_select", ...)`（走权限检查）
- ✅ 已补齐：`database-catalog` 已集成到现有 admin-console
- ✅ 已补齐：sample rows preview，且只返回授权列

## 验收标准

1. 用户可以看到**已授权**的数据库列表（sandbox/database-demo/MySQL allowlist）
2. 用户可以查看数据库的表列表（table name + description）
3. 用户可以查看表的**已授权列**列表（column name + type）
4. 用户可以查看表的 sample rows（前 10 行，**只显示已授权列**）
5. **明确不做**：任意 SQL 编辑器、未授权列展示、真实企业 DB（非 allowlist）

## 实现步骤

### Step 1: 后端 DB Catalog API 增强（权限边界）

**目标**：在既有 catalog 基础上，增加 sample rows 端点，**必须走 ToolGateway + SafeSqlKernel + 列权限过滤**。

**文件清单**：
- 修改：`app/enterprise/database/routes.py`（复用既有 `/api/database` router）
- 修改：`app/enterprise/database/service.py`（新增 `get_authorized_columns(...)`）
- 修改：`app/enterprise/database/sandbox.py`（补 `ensure_sandbox_database(...)`）
- 修改：`tests/test_enterprise_database_http.py`

**API 设计**：

```python
# 既有 API（复用）
GET /api/database/catalog
  # 返回用户可见的 DB 列表（sandbox/database-demo/MySQL allowlist）

# 新增 API
GET /api/database/{database_id}/tables/{table_name}/sample?limit=10
  # 返回：{"rows": [...], "columns": [...], "total_rows_estimate": null}
  # 实现：调用 ToolGateway.execute("database_demo.safe_select", {"sql": "SELECT {authorized_columns} FROM {table} LIMIT 10"})
  # 权限边界：只返回已授权列，未授权列不返回

# 明确不做的 API：
# ❌ POST /api/database/sql-editor（不做任意 SQL 编辑器）
# ❌ GET /api/database/{database_id}/tables/{table_name}/all-columns（不返回未授权列）
```

**实现要点**：
1. sample API **必须走 ToolGateway**，不能绕权限直接查数据库
2. 构造 SQL 时，先查询用户已授权列，只 SELECT 这些列
3. 如果用户对该表无任何列权限，返回 403
4. sample rows 返回 JSON-safe 格式（处理 Decimal / datetime）
5. 不暴露未授权列的列名/类型/内容

**验证**：
```bash
uv run pytest tests/test_enterprise_database_http.py tests/test_assistant_frontend_optimization.py -q --no-cov

# 测试覆盖：
# - 有 table + column 权限用户可以查看 sample rows
# - 无 table 权限用户 403
# - 只返回已授权列（未授权列不在 columns / rows 中）
# - sample rows 返回 JSON-safe 格式
```

---

### Step 2: 前端 DB Catalog Browser（限定范围）

**目标**：在 admin-console 中新增 catalog browser 页面，**只展示 sandbox/database-demo/已授权 MySQL allowlist**。

**文件清单**：
- 修改：`static/admin-console.html`
- 修改：`static/admin-console.js`
- 修改：`static/admin-console.css`
- 修改：`tests/test_assistant_frontend_optimization.py`

**页面结构**：

```html
<div id="app">
  <!-- 警告横幅 -->
  <div class="info-banner">
    ℹ️ 此界面只展示 sandbox/database-demo/已授权 MySQL allowlist，不是真实企业 DB UI。
    查看范围受权限控制，未授权列不显示。
  </div>

  <!-- 左侧：数据库 + 表列表 -->
  <div class="sidebar">
    <h3>Databases</h3>
    <ul>
      <li v-for="db in databases" :key="db.database_id" @click="selectDatabase(db)">
        {{ db.database_id }}
        <span class="badge">{{ db.source }}</span>
      </li>
    </ul>
    
    <h3 v-if="selectedDatabase">Tables</h3>
    <ul v-if="selectedDatabase">
      <li v-for="table in tables" :key="table.table_name" @click="selectTable(table)">
        {{ table.table_name }}
      </li>
    </ul>
  </div>
  
  <!-- 右侧：表详情 + Sample Rows -->
  <div class="main">
    <div v-if="selectedTable">
      <h2>{{ selectedTable.table_name }}</h2>
      <p>{{ selectedTable.description }}</p>
      
      <!-- Columns（只显示已授权列） -->
      <h3>Authorized Columns</h3>
      <table class="columns-table">
        <thead>
          <tr>
            <th>Column Name</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="col in selectedTable.authorized_columns" :key="col.column_name">
            <td>{{ col.column_name }}</td>
            <td>{{ col.column_type }}</td>
          </tr>
        </tbody>
      </table>
      <p class="hint">未授权列不显示</p>
      
      <!-- Sample Rows（只显示已授权列） -->
      <h3>Sample Rows (前 10 行，只显示已授权列)</h3>
      <button @click="loadSampleRows">Load Sample</button>
      <table v-if="sampleRows.length > 0" class="sample-table">
        <thead>
          <tr>
            <th v-for="col in sampleColumns" :key="col">{{ col }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in sampleRows" :key="idx">
            <td v-for="col in sampleColumns" :key="col">{{ row[col] }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    
    <div v-else>
      <p>请选择一个表查看详情</p>
    </div>
  </div>
</div>
```

**JS 实现要点**：
```javascript
const app = Vue.createApp({
  data() {
    return {
      databases: [],
      selectedDatabase: null,
      tables: [],
      selectedTable: null,
      sampleRows: [],
      sampleColumns: []
    };
  },
  methods: {
    async loadDatabases() {
      const resp = await fetch('/api/database/catalog', {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('enterpriseAuthToken')}` }
      });
      const data = await resp.json();
      this.databases = data.databases || [];
    },
    async selectDatabase(db) {
      this.selectedDatabase = db;
      this.tables = db.tables || [];
      this.selectedTable = null;
    },
    async selectTable(table) {
      this.selectedTable = table;
      this.sampleRows = [];
      this.sampleColumns = [];
    },
    async loadSampleRows() {
      try {
        const resp = await fetch(
          `/api/database/${this.selectedDatabase.database_id}/tables/${this.selectedTable.table_name}/sample?limit=10`,
          { headers: { 'Authorization': `Bearer ${localStorage.getItem('enterpriseAuthToken')}` } }
        );
        if (resp.status === 403) {
          alert('无权限查看此表');
          return;
        }
        const data = await resp.json();
        this.sampleRows = data.rows;
        this.sampleColumns = data.columns;  // 只包含已授权列
      } catch (err) {
        alert('加载失败: ' + err.message);
      }
    }
  },
  mounted() {
    this.loadDatabases();
  }
});

app.mount('#app');
```

**验证**：
```bash
# 浏览器打开 http://localhost:9900/static/admin-console.html#database-catalog
# 1. 页面顶部显示 info 横幅
# 2. 左侧只显示 sandbox/database-demo/MySQL allowlist
# 3. 点击 table，只显示已授权列
# 4. 点击 "Load Sample"，只显示已授权列的数据
# 5. 未授权表/列返回 403 或不显示
```

---

### Step 3: P1 文档与验收

**文件清单**：
- 修改：`PROJECT_STATE.md`（记录 P1 完成状态，**明确不是真实 DB UI**）
- 已有：`docs/database_catalog_backend_design_compliant.md`
- 已有：`docs/database_catalog_frontend_design.md`

**验收标准**：
1. ✅ 后端 API 测试通过
2. ✅ 前端集成测试通过
3. ✅ 浏览器手工验收：用户可以查看 sandbox/demo DB/Tables/Columns/Sample Rows
4. ✅ 权限边界正确：未授权列不显示
5. ✅ **明确标注**：此界面只展示 sandbox/database-demo/已授权 MySQL allowlist

**完成标志**：
```bash
uv run pytest tests/test_enterprise_database_http.py tests/test_assistant_frontend_optimization.py -q --no-cov

# 浏览器验收
# - admin-console 有 "数据库查看" / database-catalog 入口
# - 页面顶部有 info 横幅
# - 可以看到 sandbox/database-demo/MySQL allowlist
# - 可以查看已授权 Columns 和 Sample Rows
# - 未授权列不显示
```

### P1 完成记录（2026-06-16）

P1 已按架构合规版完成，实际实现选择是集成到现有 `admin-console`，而不是新增独立 `static/database-catalog.*`:

- 后端：`app/enterprise/database/routes.py` 新增 `GET /api/database/{database_id}/tables/{table_name}/sample?limit=10`，route 走 `RequestGateway(route="database_catalog_sample_rows")`。
- 权限：`DatabaseCapabilityCatalogService.get_authorized_columns(...)` 只返回授权列；普通用户需要 table + column grants，admin 只返回 registry-visible columns。
- 执行：sample SQL 只由授权列构造，不用 `SELECT *`，并通过 `ToolGateway.execute(..., "database_demo.safe_select", ...)` 进入 `SafeSqlKernel`。
- 前端：`static/admin-console.js/html/css` 增加 `database-catalog` route，显示数据库/表、Authorized Columns、Sample Rows 和 `safe_sql_verified` 状态。
- 验证：`tests/test_enterprise_database_http.py`、`tests/test_assistant_frontend_optimization.py` 相关测试通过；targeted ruff、`node --check static/admin-console.js`、`git diff --check` 通过；live API smoke 和 Playwright 浏览器 smoke 已完成。

---

# P2: Audit/Trace Ops Dashboard（不含成本）

## 目标

创建跨会话/跨用户的 AIOps 运维仪表盘，聚合 **trace/audit/tool/route/latency/failure** 统计。**明确不做成本统计**（留给 P3）。

## 现状

- ✅ 已有：E11 Vue3 execution dashboard（单次诊断可视化）
- ✅ 已有：E9 audit/trace 基础（SQLite `enterprise_audit.sqlite`）
- ✅ 已有并已复用：`AuditService.query(...)` read-side seam（默认 SQLite，本地测试可用 InMemory）
- ✅ 已补齐：跨会话/跨用户的 summary/timeline/failures 聚合
- ✅ 已补齐：tool 调用统计、route 分布、latency p50/p95

## 验收标准

1. admin 可以看到按 user/route/tool 的调用统计（top N）
2. admin 可以看到按 trace_id 的 latency 分布（p50/p95/max）
3. admin 可以看到按 event_type 的审计事件趋势（timeline）
4. admin 可以看到失败率/recovered 率（`failure_semantics`）
5. **明确不做**：token 消耗趋势、成本统计（留给 P3）

## 实现步骤

### Step 1: 后端 Ops Metrics API（不含成本）

**目标**：基于既有 audit 数据，提供聚合统计 API，**不做成本计算**。

**文件清单**：
- 新增：`app/enterprise/admin/ops_metrics_routes.py`
- 修改：`app/main.py`（挂载 `/api/admin/ops-metrics/*` router）

**API 设计（不含成本）**：

```python
# 聚合统计 API
GET /api/admin/ops-metrics/summary?time_range=24h
  # 返回：
  # {
  #   "total_requests": 1000,
  #   "success_rate": 0.95,
  #   "avg_latency_ms": 1500,
  #   "p50_latency_ms": 1200,
  #   "p95_latency_ms": 3000,
  #   "top_users": [{"user_id": "...", "count": 100}, ...],
  #   "top_routes": [{"route": "chat", "count": 500}, ...],
  #   "top_tools": [{"tool": "retrieve_knowledge", "count": 300}, ...]
  # }
  # 明确不包含：total_cost, cost_by_user, cost_by_model

GET /api/admin/ops-metrics/traces?time_range=24h&limit=50
  # 返回最近 N 条 trace 列表
  # [{"trace_id": "...", "user_id": "...", "route": "...", "latency_ms": 1500, "status": "success"}, ...]

GET /api/admin/ops-metrics/failures?time_range=24h
  # 返回失败/recovered trace 列表
  # [{"trace_id": "...", "failure_semantics": "infra_error", "recovered": false}, ...]

GET /api/admin/ops-metrics/timeline?time_range=24h&bucket=1h
  # 返回按时间桶聚合的事件数
  # [{"time_bucket": "2026-06-16T10:00:00Z", "total": 100, "success": 95, "failed": 5}, ...]

# 明确不做的 API：
# ❌ GET /api/admin/ops-metrics/cost-summary（不做成本统计，留给 P3）
```

**实现要点**：
1. 复用 `SQLiteAuditSink.query(...)` 查询 audit 事件
2. 按 `event_type` 过滤（`request_started` / `request_completed` / `request_failed`）
3. 计算 latency：`completed.timestamp - started.timestamp`
4. 计算 p50/p95：排序后取中位数和 95% 分位
5. 按 user_id/route/tool 分组聚合 count
6. 失败率：`failed / total`
7. recovered 率：从 `failure_semantics` metadata 中提取
8. **不做成本计算**：不读取 `model_call` audit 的 `usage` 字段

**验证**：
```bash
uv run pytest tests/test_ops_metrics_api.py -q --no-cov

# 测试覆盖：
# - admin 可以查询 ops summary（不含成本）
# - 非 admin 403
# - latency p50/p95 计算正确
# - top users/routes/tools 聚合正确
# - timeline 按时间桶聚合正确
# - failures 返回 failure_semantics 和 recovered 状态
```

---

### Step 2: 前端 Ops Dashboard 页面（不含成本）

**目标**：创建独立的 ops dashboard 页面，展示跨会话统计，**不含成本卡片**。

**文件清单**：
- 修改：`static/admin-console.js`（添加 `ops-dashboard` route/state/methods）
- 修改：`static/admin-console.html`（添加 "Ops Dashboard" 区块）
- 修改：`static/admin-console.css`（添加 `.admin-ops-*` 样式）

**页面结构（不含成本）**：

```html
<div id="app">
  <!-- 时间范围选择 -->
  <div class="filters">
    <select v-model="timeRange" @change="loadMetrics">
      <option value="1h">最近 1 小时</option>
      <option value="24h">最近 24 小时</option>
      <option value="7d">最近 7 天</option>
    </select>
    <button @click="loadMetrics">Refresh</button>
  </div>

  <!-- 总览卡片（不含成本） -->
  <div class="summary-cards">
    <div class="card">
      <h3>总请求数</h3>
      <div class="value">{{ summary.total_requests }}</div>
    </div>
    <div class="card">
      <h3>成功率</h3>
      <div class="value">{{ (summary.success_rate * 100).toFixed(2) }}%</div>
    </div>
    <div class="card">
      <h3>P50 延迟</h3>
      <div class="value">{{ summary.p50_latency_ms }} ms</div>
    </div>
    <div class="card">
      <h3>P95 延迟</h3>
      <div class="value">{{ summary.p95_latency_ms }} ms</div>
    </div>
  </div>

  <!-- Top Users / Routes / Tools -->
  <div class="top-lists">
    <div class="top-section">
      <h3>Top Users</h3>
      <table>
        <thead>
          <tr><th>User ID</th><th>Count</th></tr>
        </thead>
        <tbody>
          <tr v-for="u in summary.top_users" :key="u.user_id">
            <td>{{ u.user_id }}</td>
            <td>{{ u.count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    
    <div class="top-section">
      <h3>Top Routes</h3>
      <table>
        <thead>
          <tr><th>Route</th><th>Count</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in summary.top_routes" :key="r.route">
            <td>{{ r.route }}</td>
            <td>{{ r.count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    
    <div class="top-section">
      <h3>Top Tools</h3>
      <table>
        <thead>
          <tr><th>Tool</th><th>Count</th></tr>
        </thead>
        <tbody>
          <tr v-for="t in summary.top_tools" :key="t.tool">
            <td>{{ t.tool }}</td>
            <td>{{ t.count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Timeline Chart（简化版：用表格展示） -->
  <div class="timeline">
    <h3>请求趋势（按小时）</h3>
    <table>
      <thead>
        <tr>
          <th>Time Bucket</th>
          <th>Total</th>
          <th>Success</th>
          <th>Failed</th>
          <th>Success Rate</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in timeline" :key="t.time_bucket">
          <td>{{ formatDate(t.time_bucket) }}</td>
          <td>{{ t.total }}</td>
          <td>{{ t.success }}</td>
          <td>{{ t.failed }}</td>
          <td>{{ (t.success / t.total * 100).toFixed(2) }}%</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- 失败列表 -->
  <div class="failures">
    <h3>最近失败（最多 20 条）</h3>
    <table>
      <thead>
        <tr>
          <th>Trace ID</th>
          <th>User ID</th>
          <th>Route</th>
          <th>Failure Semantics</th>
          <th>Recovered</th>
          <th>Timestamp</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="f in failures" :key="f.trace_id">
          <td>{{ f.trace_id }}</td>
          <td>{{ f.user_id }}</td>
          <td>{{ f.route }}</td>
          <td>{{ f.failure_semantics }}</td>
          <td>{{ f.recovered ? 'YES' : 'NO' }}</td>
          <td>{{ formatDate(f.timestamp) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
```

**JS 实现要点**（不含成本）：
```javascript
const app = Vue.createApp({
  data() {
    return {
      timeRange: '24h',
      summary: {
        total_requests: 0,
        success_rate: 0,
        p50_latency_ms: 0,
        p95_latency_ms: 0,
        top_users: [],
        top_routes: [],
        top_tools: []
      },
      timeline: [],
      failures: []
    };
  },
  methods: {
    async loadMetrics() {
      const token = localStorage.getItem('enterpriseAuthToken');
      
      // Load summary (不含成本)
      const summaryResp = await fetch(`/api/admin/ops-metrics/summary?time_range=${this.timeRange}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      this.summary = await summaryResp.json();
      
      // Load timeline
      const timelineResp = await fetch(`/api/admin/ops-metrics/timeline?time_range=${this.timeRange}&bucket=1h`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      this.timeline = await timelineResp.json();
      
      // Load failures
      const failuresResp = await fetch(`/api/admin/ops-metrics/failures?time_range=${this.timeRange}`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      this.failures = await failuresResp.json();
    },
    formatDate(isoStr) {
      return isoStr ? new Date(isoStr).toLocaleString() : 'N/A';
    }
  },
  mounted() {
    this.loadMetrics();
  }
});

app.mount('#app');
```

**验证**：
```bash
# 浏览器打开 http://localhost:9900/static/ops-dashboard.html
# 1. 以 admin 身份登录
# 2. 查看总览卡片（总请求数/成功率/延迟，不含成本）
# 3. 查看 Top Users/Routes/Tools
# 4. 查看请求趋势 timeline
# 5. 查看最近失败列表
# 6. 切换时间范围（1h/24h/7d）并刷新
```

---

### Step 3: P2 文档与验收

**文件清单**：
- 修改：`PROJECT_STATE.md`（记录 P2 完成状态，**明确不含成本**）
- 新增：`docs/ops_dashboard_design.md`（设计文档）

**验收标准**：
1. ✅ 后端 API 测试通过
2. ✅ 前端集成测试通过
3. ✅ 浏览器手工验收：admin 可以查看跨会话统计
4. ✅ 非 admin 用户 403
5. ✅ latency p50/p95 计算正确
6. ✅ top users/routes/tools 聚合正确
7. ✅ failures 显示 failure_semantics 和 recovered 状态
8. ✅ **明确标注**：不含成本统计（留给 P3）

**完成标志**：
```bash
uv run pytest tests/test_ops_metrics_service.py tests/test_ops_metrics_adapter.py tests/test_ops_metrics_routes.py tests/test_assistant_frontend_optimization.py -q --no-cov

# 浏览器验收
# - admin-console 有 "Ops Dashboard" 入口
# - 可以查看总览卡片（不含成本）
# - 可以查看 Top Users/Routes/Tools
# - 可以查看请求趋势
# - 可以查看最近失败列表
# - 可以按时间范围过滤
```

### P2 完成记录（2026-06-17）

P2 已按架构合规版完成，实际实现选择是集成到现有 `admin-console`，而不是新增独立 `static/ops-dashboard.*`：

- 后端：新增 `AuditService.query(...)` read-side seam、`OpsMetricsService`、`OpsMetricsAdapter`、`ops_metrics_routes.py`，并在 `app/main.py` 挂载 `/api/admin/ops-metrics/*`。
- API：`GET /api/admin/ops-metrics/summary`、`timeline`、`failures` 均通过 `RequestGateway.execute(...)`；非 admin 403；非法 time range 返回 400 并写 request_failed audit。
- 前端：`static/admin-console.js/html/css` 新增 `ops-dashboard` route，总览卡片、Top Users/Routes/Tools、Timeline、Failures 均复用 `adminFetch` / EnterpriseApiClient。
- 边界：response 和 UI 都不包含 `total_cost`、`cost_by_user`、`cost_by_model` 或 token/cost dashboard；P3 仍需明确触发条件。
- 验证：ops metrics + frontend 46/46、admin/memory/ops route regression 31/31、targeted ruff、`node --check static/admin-console.js`、Browser mock API 烟测、`git diff --check` 通过。


---

# P3: 成本统计（条件触发）

## 触发条件

满足以下**任一**条件时，才开始实现 P3：

1. **明确的成本压力**：月度花费超过预算阈值（如 ¥10,000）
2. **用户量稳定**：日活用户 ≥ 10 人，持续 7 天以上
3. **预算管理需求**：需要按 user/department/route 分配成本配额

**当前状态**：❌ 未触发（等明确成本压力后再做）

## 目标

在 ops dashboard 中增加成本统计功能，按 user/route/model/tag 聚合 token 消耗和金额，并支持阈值告警。

## 明确不做（未触发前）

- ❌ 不在 P2 中提前做成本统计
- ❌ 不提前配置模型单价
- ❌ 不提前建立成本告警机制
- ❌ 不提前做成本报表导出

## 实现步骤（等触发后再执行）

参考原清单 P3 部分，触发后再展开实施。

---

# P4: Skill Registry（条件触发）

## 触发条件

满足以下**任一**条件时，才开始实现 P4：

1. **明确扩展生态需求**：需要第三方开发者贡献 skill
2. **Skill 数量 ≥ 10 个**：内部 skill 已足够多，需要统一管理
3. **多团队协作**：多个团队同时开发 skill，需要 registry

**当前状态**：❌ 未触发（等明确扩展生态需求后再做）

## 目标

建立 skill manifest + CLI scaffold + registry，让 skill 开发/安装/管理规范化。

## 明确不做（未触发前）

- ❌ 不提前做 skill manifest schema
- ❌ 不提前做 CLI scaffold
- ❌ 不提前做 skill registry
- ❌ 不建立散装 skill 文件夹

## 实现步骤（等触发后再执行）

参考原清单 P4 部分，触发后再展开实施。

---

# 总结

## 修订后的执行顺序

| 优先级 | 任务 | 状态 | 边界收窄 |
|---|---|---|---|
| **P0a** | Memory Operator Read-only API | 🚀 **立即执行** | 只做 review queue/validation status/deprecation preview |
| **P0b** | Memory Explorer UI | 🚀 **P0a 稳定后执行** | 明确标注"Memory 仍默认 off，此 UI 仅供 operator review" |
| **P1** | Sandbox/Demo DB Catalog Browser | 🚀 **立即执行** | 只展示 sandbox/database-demo/已授权 MySQL allowlist |
| **P2** | Audit/Trace Ops Dashboard | ✅ **已完成** | 只做 trace/audit/tool/route/latency/failure，不做成本 |
| **P3** | 成本统计 | ⏸️ **等触发条件满足** | 等明确成本压力后再做 |
| **P4** | Skill Registry | ⏸️ **等触发条件满足** | 等明确扩展生态需求后再做 |

## 与 Week 6 Review 对齐

### Memory 可见性（P0a/P0b）
- **Week 6 结论**：Memory 当前 `off`，缺 active 审批/真实长会话 evidence/rollback 记录，不 eligible
- **修订后边界**：
  - ✅ P0a 只做 operator 最小控制面（review queue/validation status/deprecation preview）
  - ✅ P0b UI 明确标注"Memory 仍默认 off，此 UI 仅供 operator review"
  - ❌ **不称为 Memory 产品化完成**
  - ❌ 不做全 L0/L1/L2 Explorer（evidence 列表、atom 全量查询、scenario 详情）

### Database UI（P1）
- **Week 6 结论**：当前只有 sandbox/database-demo，不是真实 DB UI
- **修订后边界**：
  - ✅ 只展示 sandbox/database-demo/已授权 MySQL allowlist
  - ✅ sample rows 必须走 ToolGateway + SafeSqlKernel + 列权限过滤
  - ✅ 页面明确标注"此界面只展示 sandbox/database-demo/已授权 MySQL allowlist"
  - ❌ **不叫真实 DB UI**
  - ❌ 不做任意 SQL 编辑器
  - ❌ 不绕权限直接查数据库

### AIOps Ops Dashboard（P2）
- **Week 6 结论**：没有稳定 token/tool/DB metric baseline，F8 evidence-only
- **修订后边界**：
  - ✅ 只做 trace/audit/tool/route/latency/failure 聚合
  - ❌ **不做成本统计**（留给 P3 触发后做）
  - ❌ 不在 summary 中返回 total_cost/cost_by_user/cost_by_model

### 成本/Skill（P3/P4）
- **Week 6 结论**：成本/Skill 明确未触发
- **修订后边界**：
  - ✅ P3/P4 继续条件触发
  - ❌ 不提前做成本配置/告警/报表
  - ❌ 不提前做 skill manifest/registry

## 注意事项

1. **边界收窄**：每个任务都明确"做什么 + 不做什么"
2. **与 Week 6 Review 对齐**：不和"不 eligible / 未触发"的结论冲突
3. **复用既有代码**：优先调用既有 service 层，不重复造轮子
4. **明确标注限制**：UI 上显示警告横幅/info 横幅，说明当前边界
5. **权限边界**：Database sample rows 必须走 ToolGateway，Memory 必须走 MemoryReviewService

## 验收口径

每个任务完成后，必须满足：

1. ✅ **后端 API 单元测试全过**
   - 测试覆盖权限边界、audit 写入、数据不泄露
   
2. ✅ **前端集成测试全过**
   - 测试覆盖 admin/非 admin、授权/未授权、边界标注显示
   
3. ✅ **浏览器手工验收全过**
   - admin 可以查看/操作
   - 非 admin 403
   - 警告横幅/info 横幅显示
   - 未授权内容不显示
   
4. ✅ **文档更新**
   - `PROJECT_STATE.md`：记录完成状态，明确边界限制
   - 开发记录：追加实现记录
   - 设计文档：新增设计文档，明确"做什么 + 不做什么"
   
5. ✅ **与 Week 6 Review 对齐**
   - 不和"不 eligible / 未触发"的结论冲突
   - 不称为"产品化完成"（如果 Week 6 说不 eligible）

## 完成标志

### P0a 完成
```bash
uv run pytest tests/test_memory_operator_routes.py -q --no-cov
# curl 验收：review queue / validation status / deprecation preview
```

### P0b 完成
```bash
uv run pytest tests/test_memory_operator_frontend.py -q --no-cov
# 浏览器验收：警告横幅显示 + 可以查看/审批
```

### P1 完成
```bash
uv run pytest tests/test_enterprise_database_http.py tests/test_assistant_frontend_optimization.py -q --no-cov
# 浏览器验收：admin-console database-catalog + info 横幅显示 + 只显示已授权范围
```

### P2 完成
```bash
uv run pytest tests/test_ops_metrics_api.py tests/test_ops_dashboard_frontend.py -q --no-cov
# 浏览器验收：总览卡片（不含成本）+ Top N + timeline + failures
```

---

## 后续工作（等触发后）

### P3 成本统计触发后
1. 配置模型单价（`MODEL_PRICING`）
2. 实现成本计算（`CostCalculator`）
3. 实现成本聚合 API（`/api/admin/ops-metrics/cost-summary`）
4. 在 ops dashboard 中增加成本卡片/成本 tab
5. 实现阈值告警（邮件/飞书/企业微信）
6. 实现成本报表导出（CSV）

### P4 Skill Registry 触发后
1. 定义 skill manifest schema（参考 Dify/Semantic Kernel）
2. 实现 CLI scaffold（`python -m app.cli.skill_cli scaffold`）
3. 实现 skill registry（list/install/uninstall/load）
4. 实现 skill 依赖/权限/输入输出 schema 声明
