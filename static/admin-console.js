(function () {
    const apiBaseUrl = '/api';
    const tokenStorageKey = 'enterpriseAuthToken';
    const enterpriseApiClient = window.EnterpriseApiClient || null;
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
    ];

    function createEmptyForms() {
        return {
            user: {
                user_id: '',
                username: '',
                password: '',
                department_id: 'dept_1',
                department_name: 'Department 1',
                roles: 'user',
            },
            role: {
                role_id: '',
                name: '',
                description: '',
            },
            grant: {
                principal_type: 'user',
                principal_id: '',
                resource_type: 'document',
                resource_id: '',
                action: 'read',
                effect: 'allow',
                reason: '',
            },
            audit: {
                trace_id: '',
                user_id: '',
                event_type: '',
                limit: '50',
            },
            trace: {
                trace_id: '',
                compare_trace_id: '',
            },
            memoryOperator: {
                owner_id: 'default',
                limit: '20',
                validation_owner_id: 'default',
                deprecation_owner_id: 'default',
            },
            databaseCatalog: {
                sample_limit: '10',
            },
            departmentScope: {
                department_id: '',
                resource_type: '',
                resource_id: '',
                action: '',
            },
        };
    }

    function normalizeRoute(rawRoute) {
        const route = (rawRoute || '').replace(/^#\/?/, '');
        return routeKeys.includes(route) ? route : 'overview';
    }

    function parseCsv(value, fallback = []) {
        const items = String(value || '')
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean);
        return items.length > 0 ? items : fallback;
    }

    async function readErrorMessage(response) {
        if (enterpriseApiClient?.readError) {
            const error = await enterpriseApiClient.readError(response);
            return error.message;
        }
        let payload = null;
        try {
            payload = await response.clone().json();
        } catch (_error) {
            payload = null;
        }
        const detail = payload?.detail || payload?.message || payload?.data?.user_message || payload?.data?.reason;
        if (response.status === 401) {
            return detail || '登录已过期，请回到聊天页重新登录。';
        }
        if (response.status === 403) {
            return detail || '你没有权限访问管理后台。';
        }
        if (response.status >= 500) {
            const traceId = payload?.data?.trace_id || payload?.trace_id;
            return traceId
                ? `后端处理失败，请复制 trace_id=${traceId} 给开发者排查。`
                : '后端处理失败，请查看服务日志。';
        }
        return detail || `HTTP错误: ${response.status}`;
    }

    function mountWithoutVue(message) {
        const mountPoint = document.getElementById('admin-console-app');
        if (!mountPoint) return;
        mountPoint.innerHTML = `
            <div class="admin-auth-state">
                <section class="admin-auth-panel">
                    <h1>企业助手管理后台</h1>
                    <p>${message}</p>
                    <p class="admin-muted">请确认网络可访问 Vue3 CDN，或回到聊天页继续使用普通助手能力。</p>
                    <div class="admin-row-actions admin-panel-actions">
                        <button class="ea-btn ea-btn-primary" type="button" onclick="window.location.href='/'">返回聊天页</button>
                    </div>
                </section>
            </div>
        `;
    }

    function buildAdminApp() {
        const { createApp } = window.Vue;

        return createApp({
            data() {
                return {
                    apiBaseUrl,
                    token: enterpriseApiClient?.getToken?.() || localStorage.getItem(tokenStorageKey) || '',
                    authState: 'loading',
                    route: normalizeRoute(window.location.hash),
                    currentUser: {},
                    profile: null,
                    capabilityHealth: {},
                    scope: null,
                    busy: false,
                    users: [],
                    roles: [],
                    departments: [],
                    grants: [],
                    permissionRequests: [],
                    permissionRequestSummary: {
                        pending_count: 0,
                        requires_global_review_count: 0,
                    },
                    reviews: [],
                    resources: [],
                    grantPreview: null,
                    auditEvents: [],
                    traceTimeline: null,
                    traceComparison: null,
                    traceCompareEnabled: false,
                    memoryOperator: {
                        activeTab: 'review',
                        reviewQueue: [],
                        reviewQueueMeta: {
                            owner_id: 'default',
                            total: 0,
                            limit: 20,
                        },
                        validationStatus: null,
                        deprecationPreview: null,
                    },
                    databaseCatalog: {
                        databases: [],
                        selectedDatabaseId: '',
                        selectedTableName: '',
                        sampleRows: [],
                        sampleColumns: [],
                        sampleMeta: null,
                        isLoadingSample: false,
                    },
                    traceFilters: [
                        { source: 'routing', label: 'routing', enabled: true },
                        { source: 'retrieval', label: 'retrieval', enabled: true },
                        { source: 'permission', label: 'permission', enabled: true },
                        { source: 'tool', label: 'tool', enabled: true },
                        { source: 'database', label: 'database', enabled: true },
                        { source: 'memory', label: 'memory', enabled: true },
                        { source: 'sse', label: 'sse', enabled: true },
                        { source: 'audit', label: 'audit', enabled: true },
                        { source: 'not_recorded', label: 'not_recorded', enabled: true },
                    ],
                    reviewDecisionReasons: {},
                    memoryDecisionNotes: {},
                    permissionRequestDecisionReasons: {},
                    builtInRoles: ['admin', 'department_admin', 'user'],
                    forms: createEmptyForms(),
                    toast: {
                        message: '',
                        type: 'success',
                    },
                    navItems: [
                        { key: 'overview', label: '概览' },
                        { key: 'users', label: '用户' },
                        { key: 'roles', label: '角色' },
                        { key: 'departments', label: '部门' },
                        { key: 'resources', label: '资源' },
                        { key: 'grants', label: '授权' },
                        { key: 'permission-requests', label: '权限申请' },
                        { key: 'reviews', label: '审批' },
                        { key: 'audit', label: '审计' },
                        { key: 'trace', label: 'Trace' },
                        { key: 'memory-operator', label: 'Memory Operator' },
                        { key: 'database-catalog', label: '数据库查看' },
                    ],
                };
            },
            computed: {
                visibleNavItems() {
                    return this.navItems
                        .filter((item) => item.key !== 'departments' || this.isGlobalAdmin)
                        .filter((item) => item.key !== 'roles' || this.isGlobalAdmin);
                },
                currentRouteLabel() {
                    return this.navItems.find((item) => item.key === this.route)?.label || '概览';
                },
                roleLabel() {
                    return (this.currentUser.roles || []).join(', ') || '无角色';
                },
                isGlobalAdmin() {
                    return (this.currentUser.roles || []).includes('admin');
                },
                isDepartmentAdmin() {
                    return (this.currentUser.roles || []).includes('department_admin');
                },
                scopeLabel() {
                    if (this.isGlobalAdmin) {
                        return '全局管理员';
                    }
                    if (this.isDepartmentAdmin) {
                        return '部门管理员';
                    }
                    return '普通用户';
                },
                capabilityHealthItems() {
                    const labels = {
                        profile: 'Profile',
                        knowledge_base_api: 'KB',
                        document_worker: 'Worker',
                        database_catalog: 'DB',
                        tool_gateway: 'Tools',
                    };
                    return Object.entries(this.capabilityHealth || {}).map(([key, capability]) => ({
                        key,
                        label: labels[key] || key,
                        status: capability?.status || 'unknown',
                        reason: capability?.reason || '',
                    }));
                },
                filteredTraceTimeline() {
                    if (!this.traceTimeline?.timeline) return [];
                    const enabledSources = new Set(
                        this.traceFilters
                            .filter((filter) => filter.enabled)
                            .map((filter) => filter.source),
                    );
                    return this.traceTimeline.timeline.filter((item) => {
                        if (enabledSources.has(item.source)) return true;
                        return item.source === 'not_recorded' && enabledSources.has(item.stage);
                    });
                },
                selectedResource() {
                    return this.resources.find((resource) => resource.resource_id === this.forms.grant.resource_id) || null;
                },
                selectedResourceActions() {
                    return this.selectedResource?.actions_supported || [];
                },
                databaseResources() {
                    return this.resources.filter((resource) => (
                        resource.resource_type === 'database_table' || resource.resource_type === 'database_column'
                    ));
                },
                databaseTables() {
                    return this.databaseResources
                        .filter((resource) => resource.resource_type === 'database_table')
                        .sort((left, right) => {
                            const leftName = left.metadata?.table_name || left.resource_id;
                            const rightName = right.metadata?.table_name || right.resource_id;
                            return leftName.localeCompare(rightName);
                        });
                },
                databaseColumnsByTable() {
                    const grouped = {};
                    this.databaseResources
                        .filter((resource) => resource.resource_type === 'database_column')
                        .forEach((resource) => {
                            const tableName = resource.metadata?.table_name || '';
                            if (!grouped[tableName]) {
                                grouped[tableName] = [];
                            }
                            grouped[tableName].push(resource);
                        });
                    Object.values(grouped).forEach((columns) => {
                        columns.sort((left, right) => {
                            const leftName = left.metadata?.column_name || left.resource_id;
                            const rightName = right.metadata?.column_name || right.resource_id;
                            return leftName.localeCompare(rightName);
                        });
                    });
                    return grouped;
                },
                grantCanSubmit() {
                    return Boolean(this.grantPreview?.can_submit);
                },
                businessDepartments() {
                    return this.departments.filter((department) => department.department_id !== 'system');
                },
                selectedDepartment() {
                    return this.departments.find(
                        (department) => department.department_id === this.forms.departmentScope.department_id,
                    ) || null;
                },
                resourceTypes() {
                    return Array.from(new Set(this.resources.map((resource) => resource.resource_type))).sort();
                },
                scopeResourceOptions() {
                    return this.resources.filter(
                        (resource) => resource.resource_type === this.forms.departmentScope.resource_type,
                    );
                },
                selectedDepartmentScopeResource() {
                    return this.scopeResourceOptions.find(
                        (resource) => resource.resource_id === this.forms.departmentScope.resource_id,
                    ) || null;
                },
                scopeActionOptions() {
                    return this.selectedDepartmentScopeResource?.actions_supported || [];
                },
                selectedDatabaseCatalog() {
                    return this.databaseCatalog.databases.find(
                        (database) => database.database_id === this.databaseCatalog.selectedDatabaseId,
                    ) || null;
                },
                selectedDatabaseTable() {
                    return (this.selectedDatabaseCatalog?.tables || []).find(
                        (table) => table.table_name === this.databaseCatalog.selectedTableName,
                    ) || null;
                },
                selectedDatabaseColumns() {
                    return this.selectedDatabaseTable?.visible_columns || [];
                },
            },
            mounted() {
                window.addEventListener('hashchange', this.syncRouteFromHash);
                this.initialize();
            },
            beforeUnmount() {
                window.removeEventListener('hashchange', this.syncRouteFromHash);
            },
            methods: {
                async initialize() {
                    this.token = enterpriseApiClient?.getToken?.() || localStorage.getItem(tokenStorageKey) || '';
                    if (!this.token) {
                        this.authState = 'login_required';
                        return;
                    }
                    this.authState = 'loading';
                    try {
                        const mePayload = await this.adminFetch('/auth/me');
                        this.currentUser = mePayload.data?.user || {};

                        const profilePayload = await this.adminFetch('/me/profile');
                        this.profile = profilePayload.data || null;
                        this.capabilityHealth = this.profile?.capabilities || {};
                        this.currentUser = this.profile?.user || this.currentUser;

                        if (!this.profile?.feature_flags?.admin) {
                            this.authState = 'forbidden';
                            return;
                        }

                        const scopePayload = await this.adminFetch('/admin/scope');
                        this.scope = scopePayload.data?.scope || null;

                        this.authState = 'ready';
                        this.route = normalizeRoute(window.location.hash);
                        this.replaceHashForRoute(this.route);
                        await this.loadRouteData(this.route);
                    } catch (error) {
                        if (this.authState === 'loading') {
                            this.authState = this.token ? 'forbidden' : 'login_required';
                        }
                        this.showToast(error.message, 'error');
                    }
                },
                async adminFetch(path, options = {}) {
                    if (enterpriseApiClient?.request) {
                        try {
                            return await enterpriseApiClient.request(path, options);
                        } catch (error) {
                            if (error.category === 'unauthenticated') {
                                this.clearToken();
                                this.authState = 'login_required';
                            } else if (error.category === 'forbidden') {
                                this.authState = 'forbidden';
                            }
                            throw new Error(error.message);
                        }
                    }
                    const headers = {
                        Accept: 'application/json',
                        ...(options.headers || {}),
                    };
                    const hasBody = Object.prototype.hasOwnProperty.call(options, 'body');
                    if (hasBody && !headers['Content-Type']) {
                        headers['Content-Type'] = 'application/json';
                    }
                    if (this.token) {
                        headers.Authorization = `Bearer ${this.token}`;
                    }

                    let response;
                    try {
                        response = await fetch(`${this.apiBaseUrl}${path}`, {
                            ...options,
                            headers,
                        });
                    } catch (_error) {
                        throw new Error('无法连接后端服务。请确认启动窗口仍然打开。');
                    }

                    if (response.status === 401) {
                        this.clearToken();
                        this.authState = 'login_required';
                        throw new Error('登录已过期，请回到聊天页重新登录。');
                    }
                    if (response.status === 403) {
                        this.authState = 'forbidden';
                        throw new Error(await readErrorMessage(response));
                    }
                    if (!response.ok) {
                        throw new Error(await readErrorMessage(response));
                    }
                    return response.json();
                },
                clearToken() {
                    this.token = '';
                    if (enterpriseApiClient?.clearToken) {
                        enterpriseApiClient.clearToken();
                    } else {
                        localStorage.removeItem(tokenStorageKey);
                    }
                },
                capabilityStatusLabel(status) {
                    const labels = {
                        ok: '可用',
                        degraded: '降级',
                        unknown: '未知',
                    };
                    return labels[status] || status || '未知';
                },
                async loadRouteData(route) {
                    if (route === 'overview') {
                        return this.loadOverview();
                    } else if (route === 'users') {
                        return this.loadUsers();
                    } else if (route === 'roles') {
                        return this.loadRoles();
                    } else if (route === 'departments') {
                        return this.loadDepartmentScope();
                    } else if (route === 'resources') {
                        return this.loadResources();
                    } else if (route === 'grants') {
                        return this.loadGrants();
                    } else if (route === 'permission-requests') {
                        return this.loadPermissionRequests();
                    } else if (route === 'reviews') {
                        return this.loadReviews();
                    } else if (route === 'audit') {
                        return this.loadAudit();
                    } else if (route === 'trace') {
                        return this.loadTraceTimeline();
                    } else if (route === 'memory-operator') {
                        return this.loadMemoryOperator();
                    } else if (route === 'database-catalog') {
                        return this.loadDatabaseCatalog();
                    }
                    return false;
                },
                async loadMemoryOperator(setBusy = true) {
                    if (this.memoryOperator.activeTab === 'validation') {
                        return this.loadMemoryValidationStatus(setBusy);
                    }
                    if (this.memoryOperator.activeTab === 'deprecation') {
                        return this.previewMemoryDeprecation(setBusy);
                    }
                    return this.loadMemoryReviewQueue(setBusy);
                },
                async loadDatabaseCatalog(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/database/catalog');
                        const catalog = payload.data?.catalog || {};
                        const visibleDatabases = catalog.visible_databases || [];
                        this.databaseCatalog.databases = visibleDatabases.map((databaseId) => ({
                            database_id: databaseId,
                            source: databaseId === 'sandbox_sales' ? 'database-demo' : 'mysql-allowlist',
                            tables: databaseId === catalog.database_id ? (catalog.visible_tables || []) : [],
                            visible_tools: catalog.visible_tools || [],
                            safe_sql_kernel: catalog.safe_sql_kernel || {},
                            write_operations_enabled: Boolean(catalog.write_operations_enabled),
                        }));
                        if (!this.selectedDatabaseCatalog && this.databaseCatalog.databases.length > 0) {
                            this.databaseCatalog.selectedDatabaseId = this.databaseCatalog.databases[0].database_id;
                        }
                        if (!this.selectedDatabaseTable) {
                            this.databaseCatalog.selectedTableName = (this.selectedDatabaseCatalog?.tables || [])[0]?.table_name || '';
                        }
                        this.databaseCatalog.sampleRows = [];
                        this.databaseCatalog.sampleColumns = [];
                        this.databaseCatalog.sampleMeta = null;
                        if (this.selectedDatabaseTable) {
                            await this.loadDatabaseSampleRows(false);
                        }
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadOverview() {
                    this.busy = true;
                    try {
                        const results = await Promise.all([
                            this.loadUsers(false),
                            this.loadRoles(false),
                            this.loadResources(false),
                            this.loadGrants(false),
                            this.loadPermissionRequests(false),
                            this.loadReviews(false),
                        ]);
                        return results.every(Boolean);
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        this.busy = false;
                    }
                },
                async loadUsers(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/users');
                        this.users = payload.data?.users || [];
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadRoles(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/roles');
                        this.roles = payload.data?.roles || [];
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadDepartments(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/departments');
                        this.departments = payload.data?.departments || [];
                        this.ensureDepartmentScopeDefaults();
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadDepartmentScope(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const results = await Promise.all([
                            this.loadDepartments(false),
                            this.loadResources(false),
                        ]);
                        this.ensureDepartmentScopeDefaults();
                        return results.every(Boolean);
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadResources(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/resources');
                        this.resources = payload.data?.resources || [];
                        if (!this.forms.grant.resource_id && this.resources.length > 0) {
                            this.applyResourceToGrant(this.resources[0]);
                        }
                        this.ensureDepartmentScopeDefaults();
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadGrants(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/grants');
                        this.grants = payload.data?.grants || [];
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadPermissionRequests(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/permission-requests');
                        this.permissionRequests = payload.data?.permission_requests || [];
                        this.permissionRequestSummary = {
                            pending_count: payload.data?.pending_count || 0,
                            requires_global_review_count: payload.data?.requires_global_review_count || 0,
                        };
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadReviews(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/reviews/pending');
                        this.reviews = payload.data?.reviews || [];
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadAudit(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const params = new URLSearchParams();
                        Object.entries(this.forms.audit).forEach(([key, value]) => {
                            if (value) params.set(key, value);
                        });
                        const query = params.toString() ? `?${params.toString()}` : '';
                        const payload = await this.adminFetch(`/admin/audit${query}`);
                        this.auditEvents = payload.data?.events || [];
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadTraceTimeline(setBusy = true) {
                    const traceId = this.forms.trace.trace_id.trim();
                    if (!traceId) {
                        this.traceTimeline = null;
                        this.traceComparison = null;
                        return true;
                    }
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch(`/admin/traces/${encodeURIComponent(traceId)}`);
                        this.traceTimeline = payload.data?.trace || null;
                        this.traceComparison = null;
                        return true;
                    } catch (error) {
                        this.traceTimeline = null;
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadTraceComparison(setBusy = true) {
                    const left = this.forms.trace.trace_id.trim();
                    const right = this.forms.trace.compare_trace_id.trim();
                    if (!left || !right) {
                        this.showToast('请输入两个 trace_id 或 request_id', 'error');
                        return false;
                    }
                    if (setBusy) this.busy = true;
                    try {
                        const params = new URLSearchParams({ left, right });
                        const payload = await this.adminFetch(`/admin/traces/compare?${params.toString()}`);
                        this.traceComparison = payload.data?.comparison || null;
                        return true;
                    } catch (error) {
                        this.traceComparison = null;
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadMemoryReviewQueue(setBusy = true) {
                    if (setBusy) this.busy = true;
                    try {
                        const ownerId = this.forms.memoryOperator.owner_id.trim() || 'default';
                        const limit = Number.parseInt(this.forms.memoryOperator.limit, 10) || 20;
                        const params = new URLSearchParams({
                            owner_id: ownerId,
                            limit: String(limit),
                        });
                        const payload = await this.adminFetch(`/admin/memory-operator/review-queue?${params.toString()}`);
                        const data = payload.data || {};
                        this.memoryOperator.reviewQueue = data.items || [];
                        this.memoryOperator.reviewQueueMeta = {
                            owner_id: data.owner_id || ownerId,
                            total: data.total || 0,
                            limit: data.limit || limit,
                        };
                        return true;
                    } catch (error) {
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async loadMemoryValidationStatus(setBusy = true) {
                    const ownerId = this.forms.memoryOperator.validation_owner_id.trim() || 'default';
                    if (setBusy) this.busy = true;
                    try {
                        const params = new URLSearchParams({ owner_id: ownerId });
                        const payload = await this.adminFetch(`/admin/memory-operator/validation-status?${params.toString()}`);
                        this.memoryOperator.validationStatus = payload.data?.status || null;
                        return true;
                    } catch (error) {
                        this.memoryOperator.validationStatus = null;
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async previewMemoryDeprecation(setBusy = true) {
                    const ownerId = this.forms.memoryOperator.deprecation_owner_id.trim() || 'default';
                    if (setBusy) this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/memory-operator/deprecation-preview', {
                            method: 'POST',
                            body: JSON.stringify({ owner_id: ownerId }),
                        });
                        this.memoryOperator.deprecationPreview = payload.data?.plan || null;
                        return true;
                    } catch (error) {
                        this.memoryOperator.deprecationPreview = null;
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        if (setBusy) this.busy = false;
                    }
                },
                async createUser() {
                    this.busy = true;
                    try {
                        const body = {
                            user_id: this.forms.user.user_id,
                            username: this.forms.user.username,
                            password: this.forms.user.password,
                            department_id: this.forms.user.department_id,
                            department_name: this.forms.user.department_name,
                            roles: parseCsv(this.forms.user.roles, ['user']),
                        };
                        await this.adminFetch('/admin/users', {
                            method: 'POST',
                            body: JSON.stringify(body),
                        });
                        this.forms.user = createEmptyForms().user;
                        await this.loadUsers(false);
                        this.showToast('用户已创建', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async disableUser(user) {
                    if (!window.confirm(`确定禁用用户 ${user.username} 吗？`)) return;
                    this.busy = true;
                    try {
                        await this.adminFetch(`/admin/users/${encodeURIComponent(user.user_id)}/disable`, {
                            method: 'POST',
                        });
                        await this.loadUsers(false);
                        this.showToast('用户已禁用', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async createRole() {
                    this.busy = true;
                    try {
                        await this.adminFetch('/admin/roles', {
                            method: 'POST',
                            body: JSON.stringify({ ...this.forms.role }),
                        });
                        this.forms.role = createEmptyForms().role;
                        await this.loadRoles(false);
                        this.showToast('角色已创建', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async deleteRole(role) {
                    if (!window.confirm(`确定删除角色 ${role.role_id} 吗？`)) return;
                    this.busy = true;
                    try {
                        await this.adminFetch(`/admin/roles/${encodeURIComponent(role.role_id)}`, {
                            method: 'DELETE',
                        });
                        await this.loadRoles(false);
                        this.showToast('角色已删除', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async createGrant() {
                    if (!this.grantPreview?.can_submit) {
                        this.showToast('请先通过授权预览', 'error');
                        return;
                    }
                    this.busy = true;
                    try {
                        const body = this.buildGrantPayload();
                        await this.adminFetch('/admin/grants', {
                            method: 'POST',
                            body: JSON.stringify(body),
                        });
                        this.forms.grant = createEmptyForms().grant;
                        this.grantPreview = null;
                        await this.loadGrants(false);
                        this.showToast('Grant 已保存', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                canApprovePermissionRequest(request) {
                    return this.isGlobalAdmin || !request.requires_global_review;
                },
                async approvePermissionRequest(request) {
                    if (!this.canApprovePermissionRequest(request)) {
                        this.showToast('permission_request_requires_global_review', 'error');
                        return;
                    }
                    this.busy = true;
                    try {
                        const reason = this.permissionRequestDecisionReasons[request.request_id] || '';
                        await this.adminFetch(`/admin/permission-requests/${encodeURIComponent(request.request_id)}/approve`, {
                            method: 'POST',
                            body: JSON.stringify({ reason }),
                        });
                        delete this.permissionRequestDecisionReasons[request.request_id];
                        await this.loadPermissionRequests(false);
                        this.showToast('权限申请已通过', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async rejectPermissionRequest(request) {
                    this.busy = true;
                    try {
                        const reason = this.permissionRequestDecisionReasons[request.request_id] || '';
                        await this.adminFetch(`/admin/permission-requests/${encodeURIComponent(request.request_id)}/reject`, {
                            method: 'POST',
                            body: JSON.stringify({ reason }),
                        });
                        delete this.permissionRequestDecisionReasons[request.request_id];
                        await this.loadPermissionRequests(false);
                        this.showToast('权限申请已拒绝', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async previewGrant() {
                    this.busy = true;
                    try {
                        const payload = await this.adminFetch('/admin/grant-preview', {
                            method: 'POST',
                            body: JSON.stringify(this.buildGrantPayload()),
                        });
                        this.grantPreview = payload.data || null;
                        this.showToast(
                            this.grantPreview?.can_submit ? '授权预览通过' : '授权预览未通过',
                            this.grantPreview?.can_submit ? 'success' : 'error',
                        );
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                buildGrantPayload() {
                    const body = {
                        resource_type: this.forms.grant.resource_type,
                        resource_id: this.forms.grant.resource_id,
                        action: this.forms.grant.action,
                        principal_type: this.forms.grant.principal_type,
                        principal_id: this.forms.grant.principal_id,
                        effect: this.forms.grant.effect,
                    };
                    if (this.forms.grant.reason) {
                        body.reason = this.forms.grant.reason;
                    }
                    return body;
                },
                applyResourceToGrant(resource) {
                    if (!resource) return;
                    this.forms.grant.resource_type = resource.resource_type;
                    this.forms.grant.resource_id = resource.resource_id;
                    this.forms.grant.action = (resource.actions_supported || [])[0] || '';
                    this.grantPreview = null;
                },
                onGrantResourceChanged() {
                    const resource = this.selectedResource;
                    if (resource) {
                        this.applyResourceToGrant(resource);
                    }
                },
                onGrantActionChanged() {
                    this.grantPreview = null;
                },
                ensureDepartmentScopeDefaults() {
                    const form = this.forms.departmentScope;
                    if (!form.department_id && this.businessDepartments.length > 0) {
                        form.department_id = this.businessDepartments[0].department_id;
                    }
                    if (!form.resource_type && this.resourceTypes.length > 0) {
                        form.resource_type = this.resourceTypes[0];
                    }
                    if (!this.scopeResourceOptions.some((resource) => resource.resource_id === form.resource_id)) {
                        form.resource_id = this.scopeResourceOptions[0]?.resource_id || '';
                    }
                    if (!this.scopeActionOptions.includes(form.action)) {
                        form.action = this.scopeActionOptions[0] || '';
                    }
                },
                onDepartmentScopeResourceTypeChanged() {
                    this.forms.departmentScope.resource_id = this.scopeResourceOptions[0]?.resource_id || '';
                    this.onDepartmentScopeResourceChanged();
                },
                onDepartmentScopeResourceChanged() {
                    this.forms.departmentScope.action = this.scopeActionOptions[0] || '';
                },
                normalizeDepartmentResources(resources) {
                    return (resources || []).map((resource) => ({
                        resource_type: resource.resource_type,
                        resource_id: resource.resource_id,
                        actions: [...(resource.actions || [])],
                    }));
                },
                async addDepartmentResourceToScope() {
                    const department = this.selectedDepartment;
                    const resource = this.selectedDepartmentScopeResource;
                    const action = this.forms.departmentScope.action;
                    if (!department || !resource || !action) {
                        this.showToast('请选择部门、资源和 action', 'error');
                        return;
                    }
                    const nextResources = this.normalizeDepartmentResources(department.manageable_resources);
                    const existing = nextResources.find(
                        (item) => item.resource_type === resource.resource_type && item.resource_id === resource.resource_id,
                    );
                    if (existing) {
                        existing.actions = Array.from(new Set([...(existing.actions || []), action]));
                    } else {
                        nextResources.push({
                            resource_type: resource.resource_type,
                            resource_id: resource.resource_id,
                            actions: [action],
                        });
                    }
                    await this.updateDepartmentResourceScope(department.department_id, nextResources, '部门资源 scope 已更新');
                },
                async removeDepartmentResourceFromScope(department, resource) {
                    const nextResources = this.normalizeDepartmentResources(department.manageable_resources).filter(
                        (item) => item.resource_type !== resource.resource_type || item.resource_id !== resource.resource_id,
                    );
                    await this.updateDepartmentResourceScope(department.department_id, nextResources, '部门资源已移出 scope');
                },
                async updateDepartmentResourceScope(departmentId, resources, message) {
                    this.busy = true;
                    try {
                        const payload = await this.adminFetch(
                            `/admin/departments/${encodeURIComponent(departmentId)}/resource-scope`,
                            {
                                method: 'PATCH',
                                body: JSON.stringify({ resources: this.normalizeDepartmentResources(resources) }),
                            },
                        );
                        const updatedDepartment = payload.data?.department;
                        if (updatedDepartment) {
                            this.departments = this.departments.map((department) => (
                                department.department_id === updatedDepartment.department_id ? updatedDepartment : department
                            ));
                        }
                        this.showToast(message, 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async revokeGrant(grant) {
                    if (!window.confirm(`确定撤销 Grant ${grant.grant_id} 吗？`)) return;
                    this.busy = true;
                    try {
                        const payload = await this.adminFetch(`/admin/grants/${encodeURIComponent(grant.grant_id)}`, {
                            method: 'DELETE',
                        });
                        if (!payload.data?.revoked) {
                            this.showToast('Grant 不存在或已被撤销', 'error');
                            await this.loadGrants(false);
                            return;
                        }
                        await this.loadGrants(false);
                        this.showToast('Grant 已撤销', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async decideReview(review, decision) {
                    const reason = this.reviewDecisionReasons[review.review_id] || '';
                    this.busy = true;
                    try {
                        await this.adminFetch(`/admin/reviews/${encodeURIComponent(review.review_id)}/${decision}`, {
                            method: 'POST',
                            body: JSON.stringify({ reason }),
                        });
                        delete this.reviewDecisionReasons[review.review_id];
                        await this.loadReviews(false);
                        this.showToast(decision === 'approve' ? '审批已通过' : '审批已拒绝', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                setMemoryOperatorTab(tab) {
                    this.memoryOperator.activeTab = tab;
                    if (tab === 'review' && this.memoryOperator.reviewQueue.length === 0) {
                        this.loadMemoryReviewQueue();
                    }
                },
                async selectDatabaseCatalog(database) {
                    this.databaseCatalog.selectedDatabaseId = database?.database_id || '';
                    this.databaseCatalog.selectedTableName = (database?.tables || [])[0]?.table_name || '';
                    this.databaseCatalog.sampleRows = [];
                    this.databaseCatalog.sampleColumns = [];
                    this.databaseCatalog.sampleMeta = null;
                    if (this.databaseCatalog.selectedTableName) {
                        await this.loadDatabaseSampleRows();
                    }
                },
                async selectDatabaseTable(table) {
                    this.databaseCatalog.selectedTableName = table?.table_name || '';
                    this.databaseCatalog.sampleRows = [];
                    this.databaseCatalog.sampleColumns = [];
                    this.databaseCatalog.sampleMeta = null;
                    if (this.databaseCatalog.selectedTableName) {
                        await this.loadDatabaseSampleRows();
                    }
                },
                async loadDatabaseSampleRows(setBusy = true) {
                    const databaseId = this.databaseCatalog.selectedDatabaseId;
                    const tableName = this.databaseCatalog.selectedTableName;
                    const limit = Number.parseInt(this.forms.databaseCatalog.sample_limit, 10) || 10;
                    if (!databaseId || !tableName) {
                        return false;
                    }
                    if (setBusy) this.busy = true;
                    this.databaseCatalog.isLoadingSample = true;
                    try {
                        const path = `/database/${encodeURIComponent(databaseId)}/tables/${encodeURIComponent(tableName)}/sample?limit=${encodeURIComponent(limit)}`;
                        const payload = await this.adminFetch(path);
                        const sample = payload.data?.sample || {};
                        this.databaseCatalog.sampleRows = sample.rows || [];
                        this.databaseCatalog.sampleColumns = sample.columns || [];
                        this.databaseCatalog.sampleMeta = {
                            row_count: sample.row_count || 0,
                            limit: sample.limit || limit,
                            safe_sql_verified: Boolean(sample.safe_sql_verified),
                            total_rows_estimate: sample.total_rows_estimate ?? null,
                        };
                        return true;
                    } catch (error) {
                        this.databaseCatalog.sampleRows = [];
                        this.databaseCatalog.sampleColumns = [];
                        this.databaseCatalog.sampleMeta = null;
                        this.showToast(error.message, 'error');
                        return false;
                    } finally {
                        this.databaseCatalog.isLoadingSample = false;
                        if (setBusy) this.busy = false;
                    }
                },
                async decideMemory(memory, decision) {
                    const note = (this.memoryDecisionNotes[memory.memory_id] || '').trim();
                    if (!note) {
                        this.showToast('请填写 memory review 决策说明', 'error');
                        return;
                    }
                    this.busy = true;
                    try {
                        await this.adminFetch(`/admin/memory-operator/atoms/${encodeURIComponent(memory.memory_id)}/${decision}`, {
                            method: 'POST',
                            body: JSON.stringify({ decision_note: note }),
                        });
                        delete this.memoryDecisionNotes[memory.memory_id];
                        await this.loadMemoryReviewQueue(false);
                        this.showToast(decision === 'approve' ? 'Memory 已通过' : 'Memory 已拒绝', 'success');
                    } catch (error) {
                        this.showToast(error.message, 'error');
                    } finally {
                        this.busy = false;
                    }
                },
                async refreshCurrent() {
                    const ok = await this.loadRouteData(this.route);
                    if (ok) {
                        this.showToast('已刷新', 'success');
                    }
                },
                setRoute(route) {
                    const nextRoute = normalizeRoute(route);
                    if (nextRoute === this.route) return;
                    this.route = nextRoute;
                    this.replaceHashForRoute(nextRoute);
                    this.loadRouteData(nextRoute);
                },
                syncRouteFromHash() {
                    const nextRoute = normalizeRoute(window.location.hash);
                    if (nextRoute === this.route) return;
                    this.route = nextRoute;
                    if (this.authState === 'ready') {
                        this.loadRouteData(nextRoute);
                    }
                },
                replaceHashForRoute(route) {
                    const hash = `#${route}`;
                    if (window.location.hash !== hash) {
                        window.history.replaceState(null, '', hash);
                    }
                },
                goChat() {
                    window.location.href = '/';
                },
                shortTime(value) {
                    if (!value) return '-';
                    const date = new Date(value);
                    if (Number.isNaN(date.getTime())) return String(value);
                    return date.toLocaleString('zh-CN', { hour12: false });
                },
                compactJson(value) {
                    if (value === null || value === undefined || value === '') return '-';
                    if (typeof value === 'string') return value;
                    try {
                        return JSON.stringify(value);
                    } catch (_error) {
                        return String(value);
                    }
                },
                async copyTraceId() {
                    if (!this.traceTimeline?.trace_id) return;
                    await this.copyToClipboard(this.traceTimeline.trace_id, 'trace_id 已复制');
                },
                async copyTraceJson() {
                    if (!this.traceTimeline) return;
                    await this.copyToClipboard(JSON.stringify(this.traceTimeline, null, 2), 'Trace JSON 已复制');
                },
                async copyToClipboard(text, message) {
                    try {
                        if (navigator.clipboard?.writeText) {
                            await navigator.clipboard.writeText(text);
                        } else {
                            const textarea = document.createElement('textarea');
                            textarea.value = text;
                            textarea.setAttribute('readonly', 'readonly');
                            textarea.style.position = 'fixed';
                            textarea.style.opacity = '0';
                            document.body.appendChild(textarea);
                            textarea.select();
                            document.execCommand('copy');
                            document.body.removeChild(textarea);
                        }
                        this.showToast(message, 'success');
                    } catch (_error) {
                        this.showToast('复制失败，请手动复制', 'error');
                    }
                },
                timelineItemTone(item) {
                    const status = item?.status || item?.event_type || 'unknown';
                    if (status === 'success' || item?.event_type === 'hit') return 'success';
                    if (status === 'not_recorded' || status === 'partial') return 'warning';
                    if (status === 'failure' || item?.event_type === 'miss' || item?.event_type === 'error') return 'danger';
                    return 'neutral';
                },
                showToast(message, type = 'success') {
                    this.toast = { message, type };
                    window.clearTimeout(this.toastTimer);
                    this.toastTimer = window.setTimeout(() => {
                        this.toast = { message: '', type: 'success' };
                    }, 3200);
                },
            },
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        if (!window.Vue) {
            mountWithoutVue('Vue3 runtime 未加载，无法启动管理后台。');
            return;
        }
        buildAdminApp().mount('#admin-console-app');
    });
}());
