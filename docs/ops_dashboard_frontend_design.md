# Ops Dashboard Frontend Design

## 目标

为 P2 Ops Metrics API 创建前端 UI，**复用现有 admin-console 风格**。**不含成本统计**。

## 设计原则

1. **集成到 admin-console.html**：在 admin-console 中新增 `ops-dashboard` route
2. **复用现有 CSS**：使用 `admin-*` / `ea-*` 类名
3. **复用 EnterpriseApiClient**：统一使用 `enterpriseApiClient.request(...)`
4. **不做成本统计**：只做 trace/audit/tool/route/latency/failure，不做成本

## 实现方案

### Step 1: 修改 `admin-console.js`（添加 Ops Dashboard 逻辑）

#### 1.1 在 `routeKeys` 中添加 `'ops-dashboard'`

```javascript
const routeKeys = [
    'overview', 
    'users', 
    'roles', 
    'departments', 
    'resources', 
    'grants', 
    'permission-requests', 
    'reviews', 
    'audit', 
    'trace',
    'memory-operator',
    'database-catalog',
    'ops-dashboard'  // 新增
];
```

#### 1.2 在 `visibleNavItems` 中添加 Ops Dashboard

```javascript
computed: {
    visibleNavItems() {
        const base = [
            // ... 现有项
            { key: 'ops-dashboard', label: 'Ops Dashboard' },  // 新增
        ];
        return base;
    },
}
```

#### 1.3 在 `data()` 中添加 Ops Dashboard 状态

```javascript
data() {
    return {
        // ... 现有状态
        opsDashboard: {
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
            failures: [],
            isLoading: false
        }
    };
}
```

#### 1.4 在 `methods` 中添加 Ops Dashboard 方法

```javascript
methods: {
    // ... 现有方法
    
    async loadOpsDashboard() {
        this.opsDashboard.isLoading = true;
        try {
            await Promise.all([
                this.loadOpsSummary(),
                this.loadOpsTimeline(),
                this.loadOpsFailures()
            ]);
        } catch (error) {
            this.showError('加载 Ops Dashboard 失败: ' + error.message);
        } finally {
            this.opsDashboard.isLoading = false;
        }
    },
    
    async loadOpsSummary() {
        const data = await enterpriseApiClient.request(
            `/admin/ops-metrics/summary?time_range=${this.opsDashboard.timeRange}`,
            { method: 'GET' }
        );
        this.opsDashboard.summary = data;
    },
    
    async loadOpsTimeline() {
        const data = await enterpriseApiClient.request(
            `/admin/ops-metrics/timeline?time_range=${this.opsDashboard.timeRange}&bucket=1h`,
            { method: 'GET' }
        );
        this.opsDashboard.timeline = data;
    },
    
    async loadOpsFailures() {
        const data = await enterpriseApiClient.request(
            `/admin/ops-metrics/failures?time_range=${this.opsDashboard.timeRange}`,
            { method: 'GET' }
        );
        this.opsDashboard.failures = data;
    },
    
    changeTimeRange(range) {
        this.opsDashboard.timeRange = range;
        this.loadOpsDashboard();
    }
}
```

---

### Step 2: 修改 `admin-console.html`（添加 Ops Dashboard UI）

#### 2.1 在 `<section class="admin-content">` 中添加 Ops Dashboard 区块

```html
<!-- Ops Dashboard Route -->
<section v-if="route === 'ops-dashboard'" class="admin-card">
    <div class="admin-card-header">
        <div>
            <h3>Ops Dashboard</h3>
            <p class="admin-section-note">
                跨会话/跨用户的运维统计。只展示 trace/audit/tool/route/latency/failure，不含成本统计。
            </p>
        </div>
        <div class="admin-header-actions">
            <select v-model="opsDashboard.timeRange" @change="loadOpsDashboard">
                <option value="1h">最近 1 小时</option>
                <option value="24h">最近 24 小时</option>
                <option value="7d">最近 7 天</option>
            </select>
            <button class="ea-btn" type="button" @click="loadOpsDashboard" :disabled="opsDashboard.isLoading">
                {{ opsDashboard.isLoading ? '刷新中...' : '刷新' }}
            </button>
        </div>
    </div>

    <!-- 总览卡片（不含成本） -->
    <div class="admin-ops-cards">
        <div class="admin-ops-card">
            <span class="admin-muted">总请求数</span>
            <strong>{{ opsDashboard.summary.total_requests }}</strong>
        </div>
        <div class="admin-ops-card">
            <span class="admin-muted">成功率</span>
            <strong>{{ (opsDashboard.summary.success_rate * 100).toFixed(2) }}%</strong>
        </div>
        <div class="admin-ops-card">
            <span class="admin-muted">P50 延迟</span>
            <strong>{{ opsDashboard.summary.p50_latency_ms }} ms</strong>
        </div>
        <div class="admin-ops-card">
            <span class="admin-muted">P95 延迟</span>
            <strong>{{ opsDashboard.summary.p95_latency_ms }} ms</strong>
        </div>
    </div>

    <!-- Top Users / Routes / Tools -->
    <div class="admin-ops-top-section">
        <div class="admin-ops-top-list">
            <h4>Top Users</h4>
            <table class="admin-table admin-table-sm">
                <thead>
                    <tr>
                        <th>User ID</th>
                        <th>Count</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="u in opsDashboard.summary.top_users" :key="u.user_id">
                        <td>{{ u.user_id }}</td>
                        <td>{{ u.count }}</td>
                    </tr>
                    <tr v-if="opsDashboard.summary.top_users.length === 0">
                        <td colspan="2" class="admin-empty">暂无数据</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="admin-ops-top-list">
            <h4>Top Routes</h4>
            <table class="admin-table admin-table-sm">
                <thead>
                    <tr>
                        <th>Route</th>
                        <th>Count</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="r in opsDashboard.summary.top_routes" :key="r.route">
                        <td>{{ r.route }}</td>
                        <td>{{ r.count }}</td>
                    </tr>
                    <tr v-if="opsDashboard.summary.top_routes.length === 0">
                        <td colspan="2" class="admin-empty">暂无数据</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div class="admin-ops-top-list">
            <h4>Top Tools</h4>
            <table class="admin-table admin-table-sm">
                <thead>
                    <tr>
                        <th>Tool</th>
                        <th>Count</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="t in opsDashboard.summary.top_tools" :key="t.tool">
                        <td><code>{{ t.tool }}</code></td>
                        <td>{{ t.count }}</td>
                    </tr>
                    <tr v-if="opsDashboard.summary.top_tools.length === 0">
                        <td colspan="2" class="admin-empty">暂无数据</td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Timeline -->
    <div class="admin-ops-section">
        <h4>请求趋势（按小时）</h4>
        <table class="admin-table">
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
                <tr v-for="t in opsDashboard.timeline" :key="t.time_bucket">
                    <td>{{ formatTimestamp(t.time_bucket) }}</td>
                    <td>{{ t.total }}</td>
                    <td>{{ t.success }}</td>
                    <td>{{ t.failed }}</td>
                    <td>{{ (t.success / t.total * 100).toFixed(2) }}%</td>
                </tr>
                <tr v-if="opsDashboard.timeline.length === 0">
                    <td colspan="5" class="admin-empty">暂无数据</td>
                </tr>
            </tbody>
        </table>
    </div>

    <!-- Failures -->
    <div class="admin-ops-section">
        <h4>最近失败（最多 20 条）</h4>
        <table class="admin-table">
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
                <tr v-for="f in opsDashboard.failures" :key="f.trace_id">
                    <td><code>{{ f.trace_id }}</code></td>
                    <td>{{ f.user_id }}</td>
                    <td>{{ f.route }}</td>
                    <td>
                        <span class="ea-badge" :data-tone="f.recovered ? 'warning' : 'danger'">
                            {{ f.failure_semantics }}
                        </span>
                    </td>
                    <td>
                        <span class="ea-badge" :data-tone="f.recovered ? 'success' : 'danger'">
                            {{ f.recovered ? 'YES' : 'NO' }}
                        </span>
                    </td>
                    <td>{{ formatTimestamp(f.timestamp) }}</td>
                </tr>
                <tr v-if="opsDashboard.failures.length === 0">
                    <td colspan="6" class="admin-empty">暂无失败记录</td>
                </tr>
            </tbody>
        </table>
    </div>
</section>
```

---

### Step 3: 在 `admin-console.css` 中新增 Ops Dashboard 样式

```css
.admin-ops-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin: 20px 0;
}

.admin-ops-card {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 16px;
    border: 1px solid var(--ea-line);
    border-radius: var(--ea-radius-md);
    background: var(--ea-surface);
}

.admin-ops-card strong {
    font-size: 24px;
    font-weight: 700;
}

.admin-ops-top-section {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 20px;
    margin: 20px 0;
}

.admin-ops-top-list h4 {
    margin: 0 0 12px 0;
    font-size: 14px;
    font-weight: 700;
}

.admin-ops-section {
    margin: 30px 0;
}

.admin-ops-section h4 {
    margin: 0 0 12px 0;
    font-size: 14px;
    font-weight: 700;
}
```

---

## 验收标准

1. ✅ 在 `admin-console.html` 左侧 nav 中可以看到 "Ops Dashboard" 按钮
2. ✅ 点击后右侧显示 Ops Dashboard 内容区
3. ✅ 页面顶部说明："只展示 trace/audit/tool/route/latency/failure，不含成本统计"
4. ✅ 显示 4 个总览卡片（总请求数/成功率/P50延迟/P95延迟），**不含成本卡片**
5. ✅ 显示 Top Users/Routes/Tools 三个列表
6. ✅ 显示请求趋势 timeline（按小时聚合）
7. ✅ 显示最近失败列表（含 failure_semantics 和 recovered 状态）
8. ✅ 可以切换时间范围（1h/24h/7d）
9. ✅ 所有 API 调用使用 `EnterpriseApiClient`
10. ✅ 所有样式使用现有 `admin-*` / `ea-*` 类名
11. ✅ **不显示成本相关内容**

---

## 明确不做（留给 P3）

- ❌ 不显示 total_cost / cost_by_user / cost_by_model 卡片
- ❌ 不显示 token 消耗趋势图
- ❌ 不做成本报表导出
- ❌ 不做成本阈值告警

