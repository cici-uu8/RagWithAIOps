# Database Catalog Frontend Design

## 目标

为 P1 Database Catalog API 创建前端 UI，**复用现有 admin-console 风格**。

## 设计原则

1. **集成到 admin-console.html**：在 admin-console 中新增 `database-catalog` route
2. **复用现有 CSS**：使用 `admin-*` / `ea-*` 类名
3. **复用 EnterpriseApiClient**：统一使用 `enterpriseApiClient.request(...)`
4. **权限边界清晰**：只展示 sandbox/database-demo/已授权 MySQL allowlist

## 实现方案

### Step 1: 修改 `admin-console.js`（添加 Database Catalog 逻辑）

#### 1.1 在 `routeKeys` 中添加 `'database-catalog'`

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
    'database-catalog'  // 新增
];
```

#### 1.2 在 `visibleNavItems` 中添加 Database Catalog

```javascript
computed: {
    visibleNavItems() {
        const base = [
            // ... 现有项
            { key: 'database-catalog', label: '数据库查看' },  // 新增
        ];
        return base;
    },
}
```

#### 1.3 在 `data()` 中添加 Database Catalog 状态

```javascript
data() {
    return {
        // ... 现有状态
        databaseCatalog: {
            databases: [],
            selectedDatabase: null,
            selectedTable: null,
            sampleRows: [],
            sampleColumns: [],
            isLoadingSample: false
        }
    };
}
```

#### 1.4 在 `methods` 中添加 Database Catalog 方法

```javascript
methods: {
    // ... 现有方法
    
    async loadDatabaseCatalog() {
        try {
            const data = await enterpriseApiClient.request(
                '/database/catalog',
                { method: 'GET' }
            );
            this.databaseCatalog.databases = data.databases || [];
        } catch (error) {
            this.showError('加载数据库列表失败: ' + error.message);
        }
    },
    
    selectDatabase(db) {
        this.databaseCatalog.selectedDatabase = db;
        this.databaseCatalog.selectedTable = null;
        this.databaseCatalog.sampleRows = [];
        this.databaseCatalog.sampleColumns = [];
    },
    
    selectTable(table) {
        this.databaseCatalog.selectedTable = table;
        this.databaseCatalog.sampleRows = [];
        this.databaseCatalog.sampleColumns = [];
    },
    
    async loadSampleRows() {
        if (!this.databaseCatalog.selectedDatabase || !this.databaseCatalog.selectedTable) {
            return;
        }
        
        this.databaseCatalog.isLoadingSample = true;
        try {
            const dbId = this.databaseCatalog.selectedDatabase.database_id;
            const tableName = this.databaseCatalog.selectedTable.table_name;
            const data = await enterpriseApiClient.request(
                `/database/${dbId}/tables/${tableName}/sample?limit=10`,
                { method: 'GET' }
            );
            this.databaseCatalog.sampleRows = data.rows || [];
            this.databaseCatalog.sampleColumns = data.columns || [];
        } catch (error) {
            this.showError('加载 sample rows 失败: ' + error.message);
        } finally {
            this.databaseCatalog.isLoadingSample = false;
        }
    }
}
```

---

### Step 2: 修改 `admin-console.html`（添加 Database Catalog UI）

#### 2.1 在 `<section class="admin-content">` 中添加 Database Catalog 区块

```html
<!-- Database Catalog Route -->
<section v-if="route === 'database-catalog'" class="admin-card">
    <div class="admin-card-header">
        <div>
            <h3>数据库查看</h3>
            <p class="admin-section-note">
                ℹ️ 此界面只展示 sandbox/database-demo/已授权 MySQL allowlist，不是真实企业 DB UI。
                查看范围受权限控制，未授权列不显示。
            </p>
        </div>
        <button class="ea-btn" type="button" @click="loadDatabaseCatalog">刷新</button>
    </div>

    <div class="admin-db-catalog">
        <!-- 左侧：数据库 + 表列表 -->
        <aside class="admin-db-sidebar">
            <div class="admin-db-section">
                <h4>Databases</h4>
                <div class="admin-db-list">
                    <button 
                        v-for="db in databaseCatalog.databases" 
                        :key="db.database_id"
                        type="button"
                        :class="{ active: databaseCatalog.selectedDatabase?.database_id === db.database_id }"
                        @click="selectDatabase(db)"
                    >
                        {{ db.database_id }}
                        <span class="ea-badge ea-badge-sm">{{ db.source }}</span>
                    </button>
                    <p v-if="databaseCatalog.databases.length === 0" class="admin-empty">
                        暂无可见数据库
                    </p>
                </div>
            </div>

            <div v-if="databaseCatalog.selectedDatabase" class="admin-db-section">
                <h4>Tables</h4>
                <div class="admin-db-list">
                    <button 
                        v-for="table in databaseCatalog.selectedDatabase.tables" 
                        :key="table.table_name"
                        type="button"
                        :class="{ active: databaseCatalog.selectedTable?.table_name === table.table_name }"
                        @click="selectTable(table)"
                    >
                        {{ table.table_name }}
                    </button>
                </div>
            </div>
        </aside>

        <!-- 右侧：表详情 + Sample Rows -->
        <main class="admin-db-main">
            <div v-if="databaseCatalog.selectedTable">
                <h3>{{ databaseCatalog.selectedTable.table_name }}</h3>
                <p class="admin-section-note">{{ databaseCatalog.selectedTable.description }}</p>

                <!-- Authorized Columns -->
                <div class="admin-db-section">
                    <h4>Authorized Columns</h4>
                    <table class="admin-table">
                        <thead>
                            <tr>
                                <th>Column Name</th>
                                <th>Type</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="col in databaseCatalog.selectedTable.authorized_columns" :key="col.column_name">
                                <td><code>{{ col.column_name }}</code></td>
                                <td>{{ col.column_type }}</td>
                            </tr>
                        </tbody>
                    </table>
                    <p class="admin-section-note">未授权列不显示</p>
                </div>

                <!-- Sample Rows -->
                <div class="admin-db-section">
                    <h4>Sample Rows (前 10 行，只显示已授权列)</h4>
                    <button 
                        class="ea-btn" 
                        type="button" 
                        @click="loadSampleRows"
                        :disabled="databaseCatalog.isLoadingSample"
                    >
                        {{ databaseCatalog.isLoadingSample ? '加载中...' : '加载 Sample' }}
                    </button>

                    <table v-if="databaseCatalog.sampleRows.length > 0" class="admin-table admin-table-sm">
                        <thead>
                            <tr>
                                <th v-for="col in databaseCatalog.sampleColumns" :key="col">{{ col }}</th>
                            </tr>
                        </thead>
                        <tbody>
                            <tr v-for="(row, idx) in databaseCatalog.sampleRows" :key="idx">
                                <td v-for="col in databaseCatalog.sampleColumns" :key="col">{{ row[col] }}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div v-else class="admin-empty-state">
                <p>请选择一个表查看详情</p>
            </div>
        </main>
    </div>
</section>
```

---

### Step 3: 在 `admin-console.css` 中新增 Database Catalog 样式

```css
.admin-db-catalog {
    display: grid;
    grid-template-columns: 240px minmax(0, 1fr);
    gap: 20px;
    margin-top: 20px;
}

.admin-db-sidebar {
    display: flex;
    flex-direction: column;
    gap: 20px;
}

.admin-db-section {
    margin-bottom: 20px;
}

.admin-db-section h4 {
    margin: 0 0 10px 0;
    font-size: 14px;
    font-weight: 700;
}

.admin-db-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.admin-db-list button {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 12px;
    border: 1px solid var(--ea-line);
    border-radius: var(--ea-radius-md);
    background: var(--ea-surface);
    color: var(--ea-text);
    text-align: left;
    font-size: 13px;
    cursor: pointer;
}

.admin-db-list button:hover,
.admin-db-list button.active {
    border-color: var(--ea-primary);
    background: var(--ea-primary-light);
}

.admin-db-main {
    min-height: 400px;
}

.admin-empty-state {
    display: grid;
    place-items: center;
    min-height: 400px;
    color: var(--ea-muted);
}

.admin-table-sm {
    font-size: 12px;
}

.admin-table-sm td {
    padding: 6px 10px;
}
```

---

## 验收标准

1. ✅ 在 `admin-console.html` 左侧 nav 中可以看到 "数据库查看" 按钮
2. ✅ 点击后右侧显示 Database Catalog 内容区
3. ✅ 页面顶部显示 info 横幅："此界面只展示 sandbox/database-demo/已授权 MySQL allowlist"
4. ✅ 左侧显示可见数据库列表（sandbox/database-demo/MySQL allowlist）
5. ✅ 点击数据库后，显示表列表
6. ✅ 点击表后，右侧显示表详情（只显示已授权列）
7. ✅ 点击 "加载 Sample" 后，显示前 10 行数据（只显示已授权列）
8. ✅ 未授权表/列返回 403 或不显示
9. ✅ 所有 API 调用使用 `EnterpriseApiClient`
10. ✅ 所有样式使用现有 `admin-*` / `ea-*` 类名

