# Month 2 执行清单（Week 5-8）

**目标**: 能力扩展 + 质量保证  
**周期**: 4周  
**验收**: Milestone 2通过标准全部达成  

---

## Week 5: RAG质量提升第二波（50→100 docs + Rerank验证）

**硬规则**:

- 语料扩充、retrieval、rerank、query rewrite 都必须有 baseline / compare / scorecard。
- 默认值继续保持 `dense_only / query_rewrite=off / rerank_enabled=false`，除非 compare gate 明确通过。
- 公开语料扩充不等待内部联系人，但必须记录 manifest、license、synthetic 标记。
- Rerank 以现有 `app/services/rerank_service.py` 边界扩展，不新建平行 RAG 框架。

### Day 1-3: 语料扩充Phase 2

#### Day 1: 语料收集
**外部开源runbook来源**:
- [ ] awesome-sre GitHub仓库
- [ ] Prometheus告警规则库
- [ ] K8s troubleshooting最佳实践
- [ ] Redis运维文档
- [ ] MySQL性能优化文档

**任务清单**:
- [ ] 下载50个文档
- [ ] 格式转换为Markdown
- [ ] 质量评审（确保内容有用）
- [ ] 创建manifest文件
- [ ] 更新 `docs/baselines/baseline_month2_rag_50doc.md`

#### Day 2: 批量导入
```bash
# 生成manifest（dry-run预览）
python -m app.cli.knowledge_base import \
  --dir docs/external_runbooks \
  --dry-run

# 执行导入
python -m app.cli.knowledge_base import \
  --dir docs/external_runbooks \
  --apply
```

**任务清单**:
- [ ] manifest预览无误
- [ ] 执行导入
- [ ] 确认向量索引已更新

#### Day 3: 回归测试
```bash
# 跑全量evalset
python -m evals.rag_layer.run_suite

# 检查baseline
python -m evals.rag_layer.analyze_results
```

**门禁条件**:
- [ ] baseline_after ≥ baseline_before - 3%
- [ ] new_doc_hit_rate ≥ 50%
- [ ] 无scope泄漏
- [ ] 生成 `docs/compare-reports/compare_month2_rag_50_to_100_docs.md`
- [ ] embedding / retrieval / rerank / query rewrite 各自有失败分流记录

**如果baseline下降>3%**:
```bash
# 立即回滚
python -m app.cli.knowledge_base rollback --batch latest
# 分析失败原因
python -m evals.rag_layer.failure_analysis
```

### Day 4-5: Rerank二次排序验证（条件触发）

**前提条件**: retrieval residual triage 中仍有≥5个 rank-gap 样本，且 local lexical rerank 不足以解释/解决。

#### Day 4: 接入百炼文本Rerank候选

**实现边界**:

- 在 `app/services/rerank_service.py` 现有 `RerankScorer` 协议下增加外部 scorer。
- local lexical 保留为 baseline/fallback。
- 百炼候选优先使用 `qwen3-rerank` 文本 rerank 能力。
- 不把 `gte-rerank-hybrid` 当作直接文本 rerank 首选；如要使用，必须在 compare 报告里说明它属于知识库/Retrieve API 参数语境。
- API key 只从环境变量读取，不写入代码、文档或报告。

**示意形态**:
```python
class BailianRerankScorer:
    def score(self, query: str, candidates: list[SearchResult]) -> list[float]:
        """Return one score per candidate; fallback remains local lexical."""
```

**任务清单**:
- [ ] Bailian/DashScope rerank scorer 已实现或 external-blocked 记录清楚
- [ ] 降级逻辑已实现
- [ ] 单元测试已添加
- [ ] API smoke 只记录成功/失败/延迟/模型名，不记录密钥
- [ ] `docs/scorecards/scorecard_month2_rerank_candidates.md` 已创建

#### Day 5: Shadow对比实验
```python
# 运行shadow模式
python -m evals.rag_layer.shadow_rerank \
  --mode shadow \
  --days 1

# 分析lift_proven数据
python -m evals.rag_layer.analyze_rerank_lift
```

**决策点**:
```yaml
如果 lift_proven ≥ 5个样本:
  → 继续 shadow 或申请 active gate；不得自动改默认值
  
如果 lift_proven < 5个样本:
  → reject 或 keep-shadow，继续使用当前默认 dense_only
```

**Week 5 验收**:
- [ ] 语料库扩充到100个文档 ✅
- [ ] Baseline保持80-85% ✅
- [ ] Rerank方案有数据支撑决策 ✅
- [ ] `docs/compare-reports/compare_month2_rerank_local_vs_bailian.md` 已生成 ✅
- [ ] week5_evidence.md已填写 ✅

---

## Week 6: 企业能力完善（已调整 - 部分任务已提前完成）

### ⭐️ 本周调整说明

**已提前完成（2026-06-16至17）**:
- ✅ Database v2 Stage 1-4（包含原计划的Stage 3）
- ✅ 管理后台独立页面骨架（admin-console.html已存在）
- ✅ Database Catalog Browser完整功能

**详见**: `历史完成记录.md`

**本周调整为**: 管理后台功能增强 + 权限申请工作流细化

---

### Day 1-2: ~~Database v2 Stage 3~~ → 已完成，跳过

**原任务**: 实现browse_sample_rows功能  
**状态**: ✅ 已在2026-06-17完成  
**证据**: 
- `GET /api/database/{database_id}/tables/{table_name}/sample` 已实现
- 测试: 46/46 passed
- 浏览器手工验收通过

**新任务（替代）**: 权限申请工作流UI细化

#### Day 1: 后端实现（如需要）
**检查现有实现是否完整**:
```python
class DatabaseCatalogService:
    async def browse_sample_rows(
        self,
        db_name: str,
        table_name: str,
        limit: int = 10
    ) -> dict:
        """浏览表示例数据（只读、脱敏）"""
        # 权限检查
        if not self._check_permission(db_name):
            raise PermissionDeniedError()
        
        # 查询示例数据
        query = f"SELECT * FROM {table_name} LIMIT {limit}"
        rows = await self._execute_readonly_query(query)
        
        # 脱敏处理
        rows = self._desensitize(rows)
        
        return {
            "table": table_name,
            "rows": rows,
            "total_count": await self._get_total_count(table_name)
        }
    
    def _desensitize(self, rows: List[dict]) -> List[dict]:
        """脱敏处理"""
        # 手机号、邮箱、身份证等脱敏
        pass
```

**任务清单**:
- [ ] browse_sample_rows已实现
- [ ] 脱敏逻辑已实现
- [ ] 单元测试已添加
- [ ] 权限检查已验证

#### Day 2: 前端集成
**修改 static/app.js**（数据库能力部分）:
```javascript
async showDatabaseSampleRows(dbName, tableName) {
    const response = await fetch(`/api/database/${dbName}/tables/${tableName}/sample`);
    const data = await response.json();
    
    // 渲染表格
    const html = `
        <h3>${tableName}</h3>
        <p>总行数: ${data.total_count}</p>
        <table class="sample-table">
            <thead>
                <tr>${Object.keys(data.rows[0]).map(k => `<th>${k}</th>`).join('')}</tr>
            </thead>
            <tbody>
                ${data.rows.map(row => `
                    <tr>${Object.values(row).map(v => `<td>${v}</td>`).join('')}</tr>
                `).join('')}
            </tbody>
        </table>
    `;
    
    document.getElementById('database-sample-container').innerHTML = html;
}
```

**任务清单**:
- [ ] 前端接口已集成
- [ ] 表格展示样式已完成
- [ ] 测试：查看示例数据正常

### Day 3-4: ~~管理后台独立页面~~ → 已完成，改为功能增强

**原任务**: 创建admin.html骨架  
**状态**: ✅ admin-console.html已存在，且已有3个功能tab  
**已有功能**:
- ✅ Memory Operator（Review Queue / Validation Status / Deprecation）
- ✅ Database Catalog（数据库/表/列浏览 + sample rows）
- ✅ Ops Dashboard（总览/Top榜/Timeline/Failures）

**新任务**: 权限申请工作流UI实现

#### Day 3: 权限申请表单
**创建权限申请界面**（如不存在）:
```html
<!DOCTYPE html>
<html>
<head>
    <title>管理后台 - SuperBizAgent</title>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
    <div class="admin-container">
        <aside class="admin-sidebar">
            <nav>
                <a href="#users">用户管理</a>
                <a href="#permissions">权限审批</a>
                <a href="#audit">审计日志</a>
                <a href="#knowledge">知识库管理</a>
            </nav>
        </aside>
        <main class="admin-content">
            <div id="content-area"></div>
        </main>
    </div>
    <script src="/static/js/admin.js"></script>
</body>
</html>
```

**创建 static/js/admin.js**:
```javascript
class AdminConsole {
    constructor() {
        this.currentView = 'users';
        this.init();
    }
    
    init() {
        this.setupRouting();
        this.loadInitialView();
    }
    
    async loadUserManagement() {
        // 实现用户管理页面
    }
    
    async loadPermissionApproval() {
        // 实现权限审批页面
    }
    
    async loadAuditLog() {
        // 实现审计日志页面
    }
}

window.adminConsole = new AdminConsole();
```

**任务清单**:
- [ ] admin.html已创建
- [ ] admin.js已创建
- [ ] 路由切换正常
- [ ] 样式已完成

#### Day 4: 权限申请工作流
**实现权限申请表单 + 审批流程**

**任务清单**:
- [ ] 申请表单已实现
- [ ] 审批页面已实现
- [ ] 通知机制已实现
- [ ] 测试：完整工作流通过

**Week 6 验收（已调整）**:
- [ ] ~~Database v2 Stage 3完成~~ → ✅ 已提前完成
- [ ] ~~管理后台页面可用~~ → ✅ 已提前完成（admin-console已有3个功能）
- [ ] 权限申请工作流UI完成（新增任务）
- [ ] 权限申请后端逻辑完整（新增任务）
- [ ] 测试：权限申请完整流程通过
- [ ] week6_evidence.md已填写

**提前完成证据**:
- 参考 `历史完成记录.md`
- P1 Database Catalog: 46/46 tests passed
- admin-console已有完整框架和3个功能tab

---

## Week 7: AIOps场景扩充第二波（6→10场景）+ Ops Dashboard增强（可选）

### ⭐️ 本周说明

**基础Ops Dashboard已完成**（2026-06-17）:
- ✅ 总览卡片（总请求/成功率/P50/P95）
- ✅ Top Users/Routes/Tools
- ✅ Timeline趋势
- ✅ Failures列表
- ✅ 测试: 46/46 passed

**不含成本统计**（P3触发条件未满足）

**本周重点**: AIOps场景扩充为主，Ops Dashboard增强为可选

---

### Day 1-2: SlowResponse场景
### Day 2.5-4: NetworkLatency场景
### Day 4.5-5: PodCrashLoop场景（K8s，复杂度高）

**每个场景的标准流程**:
1. 编写场景文档（aiops-docs/xxx.md）
2. 实现故障注入脚本（scripts/aiops_lab/inject_xxx.sh）
3. 编写evalset（evals/aiops/xxx_evalset.json）
4. 测试诊断流程
5. 验证成功率≥80%

---

## Week 8: 质量保证体系建立

### Day 1-2: 前端单元测试

**创建 tests/frontend/test_error_handler.js**:
```javascript
// 使用Jest或Vitest
describe('ErrorHandler', () => {
    test('should classify network error', () => {
        const handler = new ErrorHandler();
        const error = new Error('Failed to fetch');
        const classified = handler.classifyError(error);
        expect(classified.type).toBe('network');
        expect(classified.severity).toBe('critical');
    });
});
```

**任务清单**:
- [ ] 测试框架已配置（Jest/Vitest）
- [ ] error-handler单元测试≥5个
- [ ] loading-states单元测试≥3个
- [ ] 测试覆盖率≥30%

### Day 3-4: E2E测试

**创建 tests/e2e/test_core_flow.py**（Playwright）:
```python
from playwright.async_api import async_playwright

async def test_login_chat_flow():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 登录
        await page.goto('http://localhost:3003')
        await page.fill('#username', 'test_user')
        await page.fill('#password', 'password')
        await page.click('#login-btn')
        
        # 聊天
        await page.fill('#chat-input', 'CPU使用率高怎么办')
        await page.click('#send-btn')
        
        # 验证回答
        await page.wait_for_selector('.chat-message')
        
        await browser.close()
```

**任务清单**:
- [ ] Playwright已配置
- [ ] 核心流程E2E≥3个
- [ ] E2E测试通过

### Day 5: 代码规范自动化

**配置 .pre-commit-config.yaml**:
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

**执行**:
```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

**任务清单**:
- [ ] pre-commit已配置
- [ ] ruff检查通过
- [ ] 所有文件格式化完成

---

## Month 2 最终验收（Week 8 Friday - 已调整）

### 功能验收
- [ ] RAG语料库100个文档，baseline≥80%
- [ ] AIOps场景10个，成功率≥85%
- [ ] ~~Database v2 Stage 3完成~~ → ✅ 已提前完成（Stage 1-4全部完成）
- [ ] ~~管理后台可用~~ → ✅ 已提前完成（admin-console已有3个功能）
- [ ] 权限申请工作流完整（Week 6新增任务）

### 质量验收
- [ ] 前端测试覆盖率≥30%
- [ ] 后端测试覆盖率≥70%
- [ ] E2E测试覆盖核心流程
- [ ] 代码规范检查全部通过

### 文档验收
- [ ] week5-8 evidence已归档
- [ ] ~~管理后台使用文档完成~~ → 部分已完成（Database Catalog/Ops Dashboard文档已有）
- [ ] 权限申请工作流文档（新增）

### 提前完成的额外成果
- ✅ Memory Operator完整功能（P0a + P0b）
- ✅ Database v2 Stage 1-4（原计划只到Stage 3）
- ✅ Ops Dashboard基础版（原计划Week 10才做）

**通过标准**: 以上未打勾项全部打勾 + 提前完成项已验收

**下一步**: 打开 `Month3_执行清单.md`
