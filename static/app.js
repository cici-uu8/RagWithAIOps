// SuperBizAgent 前端应用
class SuperBizAgentApp {
    constructor() {
        this.apiBaseUrl = '/api';
        this.currentMode = 'quick'; // 'quick' 或 'stream'
        this.sessionId = this.generateSessionId();
        this.isStreaming = false;
        this.currentChatHistory = []; // 当前对话的消息历史
        this.chatHistories = []; // 当前登录用户的历史对话
        this.isCurrentChatFromHistory = false; // 标记当前对话是否是从历史记录加载的
        this.apiClient = window.EnterpriseApiClient || null;
        this.errorHandler = window.errorHandler || null;
        this.loadingStateManager = window.loadingStateManager || null;
        this.traceManager = window.traceManager || null;
        this.activeOverlayLoading = null;
        this.authToken = this.apiClient?.getToken?.() || localStorage.getItem('enterpriseAuthToken') || '';
        this.currentUser = null;
        this.currentProfile = null;
        this.capabilityHealth = {};
        this.permissionRequests = [];
        this.requestableResources = [];
        this.databaseConfirmations = [];
        this.databaseCatalog = null;
        this.documents = [];
        this.documentHealthDetails = {};
        this.documentPagination = { page: 1, limit: 20, total: 0, hasNext: false };
        this.documentPollingTimer = null;
        this.profileModalMode = 'profile';
        
        this.initializeElements();
        this.bindEvents();
        this.updateUI();
        this.initMarkdown();
        this.checkAndSetCentered();
        this.renderChatHistory();
        this.initializeAuthState();
    }

    // 初始化Markdown配置
    initMarkdown() {
        // 等待 marked 库加载完成
        const checkMarked = () => {
            if (typeof marked !== 'undefined') {
                try {
                    // 配置marked选项
                    marked.setOptions({
                        breaks: true,  // 支持GFM换行
                        gfm: true,     // 启用GitHub风格的Markdown
                        headerIds: false,
                        mangle: false
                    });

                    // 配置代码高亮
                    if (typeof hljs !== 'undefined') {
                        marked.setOptions({
                            highlight: function(code, lang) {
                                if (lang && hljs.getLanguage(lang)) {
                                    try {
                                        return hljs.highlight(code, { language: lang }).value;
                                    } catch (err) {
                                        console.error('代码高亮失败:', err);
                                    }
                                }
                                return code;
                            }
                        });
                    }
                    console.log('Markdown 渲染库初始化成功');
                } catch (e) {
                    console.error('Markdown 配置失败:', e);
                }
            } else {
                // 如果 marked 还没加载，等待一段时间后重试
                setTimeout(checkMarked, 100);
            }
        };
        checkMarked();
    }

    // 安全地渲染 Markdown
    renderMarkdown(content) {
        if (!content) return '';
        
        // 检查 marked 是否可用
        if (typeof marked === 'undefined') {
            console.warn('marked 库未加载，使用纯文本显示');
            return this.escapeHtml(content);
        }
        
        try {
            const html = marked.parse(content);
            return html;
        } catch (e) {
            console.error('Markdown 渲染失败:', e);
            return this.escapeHtml(content);
        }
    }

    // 高亮代码块
    highlightCodeBlocks(container) {
        if (typeof hljs !== 'undefined' && container) {
            try {
                container.querySelectorAll('pre code').forEach((block) => {
                    if (!block.classList.contains('hljs')) {
                        hljs.highlightElement(block);
                    }
                });
            } catch (e) {
                console.error('代码高亮失败:', e);
            }
        }
    }

    // 初始化DOM元素
    initializeElements() {
        // 侧边栏元素
        this.sidebar = document.querySelector('.sidebar');
        this.newChatBtn = document.getElementById('newChatBtn');
        this.aiOpsSidebarBtn = document.getElementById('aiOpsSidebarBtn');
        
        // 输入区域元素
        this.messageInput = document.getElementById('messageInput');
        this.sendButton = document.getElementById('sendButton');
        this.toolsBtn = document.getElementById('toolsBtn');
        this.toolsMenu = document.getElementById('toolsMenu');
        this.uploadFileItem = document.getElementById('uploadFileItem');
        this.modeSelectorBtn = document.getElementById('modeSelectorBtn');
        this.modeDropdown = document.getElementById('modeDropdown');
        this.currentModeText = document.getElementById('currentModeText');
        this.fileInput = document.getElementById('fileInput');
        this.knowledgeScopeSelect = document.getElementById('knowledgeScopeSelect');
        
        // 聊天区域元素
        this.chatMessages = document.getElementById('chatMessages');
        this.loadingOverlay = document.getElementById('loadingOverlay');
        this.chatContainer = document.querySelector('.chat-container');
        this.welcomeGreeting = document.getElementById('welcomeGreeting');
        this.chatHistoryList = document.getElementById('chatHistoryList');

        // 用户入口和弹层
        this.userAccountBtn = document.getElementById('userAccountBtn');
        this.userAccountMenu = document.getElementById('userAccountMenu');
        this.userAvatar = document.getElementById('userAvatar');
        this.userName = document.getElementById('userName');
        this.loginMenuItem = document.getElementById('loginMenuItem');
        this.profileMenuItem = document.getElementById('profileMenuItem');
        this.permissionsMenuItem = document.getElementById('permissionsMenuItem');
        this.fileManagerMenuItem = document.getElementById('fileManagerMenuItem');
        this.databaseCatalogMenuItem = document.getElementById('databaseCatalogMenuItem');
        this.executionDashboardMenuItem = document.getElementById('executionDashboardMenuItem');
        this.adminConsoleMenuItem = document.getElementById('adminConsoleMenuItem');
        this.logoutMenuItem = document.getElementById('logoutMenuItem');
        this.loginModal = document.getElementById('loginModal');
        this.profileModal = document.getElementById('profileModal');
        this.loginForm = document.getElementById('loginForm');
        this.loginUsername = document.getElementById('loginUsername');
        this.loginPassword = document.getElementById('loginPassword');
        this.loginError = document.getElementById('loginError');
        this.closeLoginModal = document.getElementById('closeLoginModal');
        this.closeProfileModal = document.getElementById('closeProfileModal');
        this.profileModalTitle = document.getElementById('profileModalTitle');
        this.profileContent = document.getElementById('profileContent');
        
        // 初始化时检查是否需要居中
        this.checkAndSetCentered();
    }

    // 绑定事件监听器
    bindEvents() {
        // 新建对话
        if (this.newChatBtn) {
            this.newChatBtn.addEventListener('click', () => this.newChat());
        }
        
        // AI Ops按钮
        if (this.aiOpsSidebarBtn) {
            this.aiOpsSidebarBtn.addEventListener('click', () => this.triggerAIOps());
        }
        
        // 模式选择下拉菜单
        if (this.modeSelectorBtn) {
            this.modeSelectorBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleModeDropdown();
            });
        }
        
        // 下拉菜单项点击
        const dropdownItems = document.querySelectorAll('.dropdown-item');
        dropdownItems.forEach(item => {
            item.addEventListener('click', (e) => {
                const mode = item.getAttribute('data-mode');
                this.selectMode(mode);
                this.closeModeDropdown();
            });
        });
        
        // 点击外部关闭下拉菜单
        document.addEventListener('click', (e) => {
            if (!this.modeSelectorBtn.contains(e.target) && 
                !this.modeDropdown.contains(e.target)) {
                this.closeModeDropdown();
            }
        });
        
        // 发送消息
        if (this.sendButton) {
            this.sendButton.addEventListener('click', () => this.sendMessage());
        }
        
        if (this.messageInput) {
            this.messageInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });
        }
        
        // 工具按钮和菜单
        if (this.toolsBtn) {
            this.toolsBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleToolsMenu();
            });
        }
        
        // 工具菜单项点击事件
        if (this.uploadFileItem) {
            this.uploadFileItem.addEventListener('click', () => {
                if (this.fileInput) {
                    this.fileInput.click();
                }
                this.closeToolsMenu();
            });
        }
        
        // 点击外部关闭工具菜单
        document.addEventListener('click', (e) => {
            if (this.toolsBtn && this.toolsMenu && 
                !this.toolsBtn.contains(e.target) && 
                !this.toolsMenu.contains(e.target)) {
                this.closeToolsMenu();
            }
        });
        
        if (this.fileInput) {
            this.fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
        }

        if (this.userAccountBtn) {
            this.userAccountBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleUserMenu();
            });
        }
        if (this.loginMenuItem) {
            this.loginMenuItem.addEventListener('click', () => this.openLoginModal());
        }
        if (this.profileMenuItem) {
            this.profileMenuItem.addEventListener('click', () => this.openProfileModal('profile'));
        }
        if (this.permissionsMenuItem) {
            this.permissionsMenuItem.addEventListener('click', () => this.openProfileModal('permissions'));
        }
        if (this.fileManagerMenuItem) {
            this.fileManagerMenuItem.addEventListener('click', () => this.openProfileModal('documents'));
        }
        if (this.databaseCatalogMenuItem) {
            this.databaseCatalogMenuItem.addEventListener('click', () => this.openProfileModal('database'));
        }
        if (this.executionDashboardMenuItem) {
            this.executionDashboardMenuItem.addEventListener('click', () => this.openExecutionDashboard());
        }
        if (this.adminConsoleMenuItem) {
            this.adminConsoleMenuItem.addEventListener('click', () => this.openAdminConsole());
        }
        if (this.logoutMenuItem) {
            this.logoutMenuItem.addEventListener('click', () => this.logout());
        }
        if (this.closeLoginModal) {
            this.closeLoginModal.addEventListener('click', () => this.closeAccountModals());
        }
        if (this.closeProfileModal) {
            this.closeProfileModal.addEventListener('click', () => this.closeAccountModals());
        }
        if (this.loginForm) {
            this.loginForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.login();
            });
        }
        if (this.loginModal) {
            this.loginModal.addEventListener('click', (e) => {
                if (e.target === this.loginModal) {
                    this.closeAccountModals();
                }
            });
        }
        if (this.profileModal) {
            this.profileModal.addEventListener('click', (e) => {
                if (e.target === this.profileModal) {
                    this.closeAccountModals();
                }
            });
        }
        window.addEventListener('storage', (e) => {
            if (e.key === 'enterpriseAuthToken') {
                this.authToken = e.newValue || '';
                this.initializeAuthState();
            }
        });
        document.addEventListener('click', (e) => {
            if (this.userAccountBtn && this.userAccountMenu &&
                !this.userAccountBtn.contains(e.target) &&
                !this.userAccountMenu.contains(e.target)) {
                this.closeUserMenu();
            }
        });
    }

    async initializeAuthState() {
        if (!this.authToken) {
            this.currentUser = null;
            this.currentProfile = null;
            this.chatHistories = [];
            this.renderChatHistory();
            this.updateUserUI();
            return;
        }
        try {
            const meResponse = await this.apiRequest('/auth/me', { method: 'GET' });
            const mePayload = await meResponse.json();
            this.currentUser = mePayload?.data?.user || null;
            const profileResponse = await this.apiRequest('/me/profile', { method: 'GET' });
            const profilePayload = await profileResponse.json();
            this.currentProfile = profilePayload?.data || null;
            this.capabilityHealth = this.currentProfile?.capabilities || {};
            this.renderKnowledgeScopeOptions();
            this.chatHistories = await this.loadServerChatHistories();
            this.renderChatHistory();
        } catch (error) {
            console.warn('初始化登录态失败:', error);
            this.clearAuthState(false);
        } finally {
            this.updateUserUI();
        }
    }

    getAuthHeaders(extraHeaders = {}) {
        if (this.apiClient?.authHeaders) {
            return this.apiClient.authHeaders(extraHeaders);
        }
        const headers = { ...extraHeaders };
        if (this.authToken) {
            headers.Authorization = `Bearer ${this.authToken}`;
        }
        return headers;
    }

    async apiRequest(path, options = {}) {
        if (this.apiClient?.rawRequest) {
            try {
                return await this.apiClient.rawRequest(path, options);
            } catch (error) {
                if (error.category === 'unauthenticated') {
                    this.clearAuthState(false);
                }
                throw this.normalizeError(error);
            }
        }
        const headers = this.getAuthHeaders(options.headers || {});
        let response;
        try {
            response = await fetch(`${this.apiBaseUrl}${path}`, {
                ...options,
                headers,
            });
        } catch (error) {
            throw this.normalizeError(
                error,
                '无法连接后端服务。请确认“启动企业助手.command”窗口仍然打开，或重新双击启动。'
            );
        }

        if (response.status === 401) {
            this.clearAuthState(false);
            throw new Error('登录已过期，请重新登录。');
        }
        if (!response.ok) {
            throw new Error(await this.readErrorMessage(response));
        }
        return response;
    }

    async readErrorMessage(response) {
        if (this.apiClient?.readError) {
            const error = await this.apiClient.readError(response);
            return error.message;
        }
        let payload = null;
        try {
            payload = await response.clone().json();
        } catch (_error) {
            payload = null;
        }
        const detail = payload?.detail || payload?.message || payload?.data?.user_message || payload?.data?.reason;
        if (response.status === 403) {
            return detail || '你没有权限使用该功能，请联系管理员授权。';
        }
        if (response.status >= 500) {
            const traceId = payload?.data?.trace_id || payload?.trace_id;
            return traceId
                ? `后端处理失败，请复制 trace_id=${traceId} 给开发者排查。`
                : '后端处理失败，请查看服务日志。';
        }
        return detail || `HTTP错误: ${response.status}`;
    }

    normalizeError(error, fallbackMessage = '') {
        if (!this.errorHandler) {
            return error instanceof Error ? error : new Error(fallbackMessage || String(error || '操作失败'));
        }
        const normalized = this.errorHandler.normalize(error, fallbackMessage);
        const nextError = new Error(normalized.message);
        nextError.category = normalized.type;
        nextError.severity = normalized.severity;
        nextError.traceId = normalized.traceId || error?.traceId || error?.trace_id || this.traceManager?.lastTraceId || '';
        nextError.requestId = error?.requestId || error?.request_id || this.traceManager?.lastRequestId || '';
        nextError.title = normalized.title;
        return nextError;
    }

    renderErrorMessage(error, fallbackMessage = '') {
        if (!this.errorHandler) {
            return this.escapeHtml(error?.message || fallbackMessage || '操作失败');
        }
        return this.errorHandler.renderError(this.normalizeError(error, fallbackMessage));
    }

    updateUserUI() {
        const displayName = this.currentUser?.username || '未登录';
        if (this.userName) {
            this.userName.textContent = displayName;
        }
        if (this.userAvatar) {
            this.userAvatar.textContent = this.currentUser ? this.initials(displayName) : '未';
        }
        const loggedIn = Boolean(this.currentUser);
        if (this.loginMenuItem) this.loginMenuItem.style.display = loggedIn ? 'none' : 'block';
        if (this.profileMenuItem) this.profileMenuItem.disabled = !loggedIn;
        if (this.permissionsMenuItem) this.permissionsMenuItem.disabled = !loggedIn;
        if (this.fileManagerMenuItem) this.fileManagerMenuItem.disabled = !loggedIn;
        if (this.databaseCatalogMenuItem) this.databaseCatalogMenuItem.disabled = !loggedIn;
        if (this.executionDashboardMenuItem) this.executionDashboardMenuItem.style.display = loggedIn ? 'block' : 'none';
        if (this.adminConsoleMenuItem) {
            const isAdmin = Boolean(this.currentProfile?.feature_flags?.admin);
            this.adminConsoleMenuItem.style.display = loggedIn && isAdmin ? 'block' : 'none';
        }
        if (this.logoutMenuItem) this.logoutMenuItem.style.display = loggedIn ? 'block' : 'none';
        this.renderKnowledgeScopeOptions();
    }

    renderKnowledgeScopeOptions() {
        if (!this.knowledgeScopeSelect) return;
        const previousValue = this.knowledgeScopeSelect.value;
        const kbIds = this.currentProfile?.visible_kb_ids || [];
        const options = ['<option value="">自动知识库</option>'].concat(
            kbIds.map((kbId) => `<option value="${this.escapeHtml(kbId)}">${this.escapeHtml(kbId)}</option>`)
        );
        this.knowledgeScopeSelect.innerHTML = options.join('');
        if (kbIds.includes(previousValue)) {
            this.knowledgeScopeSelect.value = previousValue;
        }
        this.knowledgeScopeSelect.disabled = kbIds.length === 0;
    }

    selectedKnowledgeBaseIds() {
        const selected = this.knowledgeScopeSelect?.value || '';
        return selected ? [selected] : [];
    }

    buildChatRequestBody(message) {
        const selectedKbIds = this.selectedKnowledgeBaseIds();
        return {
            Id: this.sessionId,
            Question: message,
            SelectedKbIds: this.selectedKnowledgeBaseIds(),
            ScopeSource: selectedKbIds.length > 0 ? 'user_selected' : 'auto_visible',
        };
    }

    initials(name) {
        if (!name) return '未';
        const letters = name.split(/[_\s.-]+/).filter(Boolean).map(part => part[0]).join('');
        return (letters || name[0]).slice(0, 2).toUpperCase();
    }

    toggleUserMenu() {
        if (!this.userAccountMenu) return;
        this.userAccountMenu.classList.toggle('active');
    }

    closeUserMenu() {
        if (this.userAccountMenu) {
            this.userAccountMenu.classList.remove('active');
        }
    }

    openLoginModal() {
        this.closeUserMenu();
        if (this.loginError) this.loginError.textContent = '';
        if (this.loginModal) {
            this.loginModal.classList.add('active');
        }
        if (this.loginUsername) {
            this.loginUsername.focus();
        }
    }

    closeAccountModals() {
        this.stopDocumentPolling();
        this.profileModalMode = 'profile';
        if (this.loginModal) this.loginModal.classList.remove('active');
        if (this.profileModal) this.profileModal.classList.remove('active');
    }

    openAdminConsole() {
        this.closeUserMenu();
        if (!this.currentProfile?.feature_flags?.admin) {
            this.showNotification('你没有权限访问管理后台', 'error');
            return;
        }
        window.location.href = '/static/admin-console.html';
    }

    openExecutionDashboard() {
        this.closeUserMenu();
        if (!this.currentUser) {
            this.showNotification('请先登录后再打开执行看板', 'error');
            return;
        }
        window.location.href = '/static/enterprise-dashboard.html';
    }

    async login() {
        const username = this.loginUsername?.value?.trim();
        const password = this.loginPassword?.value || '';
        if (!username || !password) {
            if (this.loginError) this.loginError.textContent = '请输入用户名和密码';
            return;
        }
        try {
            let response;
            try {
                response = await fetch(`${this.apiBaseUrl}/auth/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password }),
                });
            } catch (_networkError) {
                throw new Error('无法连接后端服务。请确认“启动企业助手.command”窗口仍然打开，或重新双击启动。');
            }
            if (!response.ok) {
                throw new Error(await this.readErrorMessage(response));
            }
            const payload = await response.json();
            this.authToken = payload?.data?.access_token || '';
            this.currentUser = payload?.data?.user || null;
            if (this.apiClient?.setToken) {
                this.apiClient.setToken(this.authToken);
            } else {
                localStorage.setItem('enterpriseAuthToken', this.authToken);
            }
            await this.initializeAuthState();
            this.closeAccountModals();
            this.showNotification('登录成功', 'success');
        } catch (error) {
            if (this.loginError) this.loginError.innerHTML = this.renderErrorMessage(error, '登录失败');
        }
    }

    async logout() {
        this.closeUserMenu();
        if (this.authToken) {
            try {
                await this.apiRequest('/auth/logout', { method: 'POST' });
            } catch (error) {
                console.warn('退出登录请求失败:', error);
            }
        }
        this.clearAuthState(true);
    }

    clearAuthState(showMessage = true) {
        if (this.currentUser && this.currentChatHistory.length > 0) {
            this.saveCurrentChat();
        }
        this.authToken = '';
        this.currentUser = null;
        this.currentProfile = null;
        this.capabilityHealth = {};
        this.databaseCatalog = null;
        this.documents = [];
        this.documentPagination = { page: 1, limit: 20, total: 0, hasNext: false };
        this.stopDocumentPolling();
        this.chatHistories = [];
        this.currentChatHistory = [];
        this.isCurrentChatFromHistory = false;
        this.isStreaming = false;
        this.sessionId = this.generateSessionId();
        this.currentMode = 'quick';
        if (this.messageInput) {
            this.messageInput.value = '';
        }
        if (this.chatMessages) {
            this.chatMessages.innerHTML = '';
        }
        if (this.apiClient?.clearToken) {
            this.apiClient.clearToken();
        } else {
            localStorage.removeItem('enterpriseAuthToken');
        }
        this.renderChatHistory();
        this.updateUI();
        this.checkAndSetCentered();
        this.updateUserUI();
        if (showMessage) {
            this.showNotification('已退出登录', 'info');
        }
    }

    async openProfileModal(mode = 'profile') {
        this.closeUserMenu();
        if (!this.currentUser) {
            this.openLoginModal();
            return;
        }
        this.stopDocumentPolling();
        this.profileModalMode = mode;
        try {
            const response = await this.apiRequest('/me/profile', { method: 'GET' });
            const payload = await response.json();
            this.currentProfile = payload?.data || this.currentProfile;
            this.capabilityHealth = this.currentProfile?.capabilities || {};
        } catch (error) {
            this.showNotification(error.message, 'error');
        }
        if (mode === 'permissions') {
            await this.loadRequestableResources();
            await this.loadPermissionRequests();
            await this.loadDatabaseConfirmations();
            this.renderPermissions();
        } else if (mode === 'documents') {
            await this.loadDocuments({ page: 1 });
        } else if (mode === 'database') {
            await this.loadDatabaseCatalog();
            this.renderDatabaseCatalog();
        } else {
            this.renderProfile();
        }
        if (this.profileModal) {
            this.profileModal.classList.add('active');
        }
    }

    renderProfile() {
        if (!this.profileContent) return;
        if (this.profileModalTitle) this.profileModalTitle.textContent = '个人资料';
        const profile = this.currentProfile || {};
        const user = profile.user || this.currentUser || {};
        const rows = [
            ['用户名', user.username || ''],
            ['用户 ID', user.user_id || ''],
            ['角色', (user.roles || []).join(', ') || '无'],
            ['部门', [user.department_id, user.department_name].filter(Boolean).join(' / ') || '无'],
            ['可见知识库', (profile.visible_kb_ids || []).join(', ') || '无'],
            ['可用工具', (profile.visible_tools || []).join(', ') || '无'],
            ['不可用功能', this.formatUnavailable(profile.unavailable_reasons || {})],
        ];
        this.profileContent.innerHTML = rows.map(([label, value]) => `
            <div class="profile-row">
                <div class="profile-label">${this.escapeHtml(label)}</div>
                <div class="profile-value">${this.escapeHtml(value)}</div>
            </div>
        `).join('') + this.renderCapabilityHealthRows();
    }

    renderCapabilityHealthRows() {
        const capabilities = this.currentProfile?.capabilities || this.capabilityHealth || {};
        const entries = Object.entries(capabilities);
        if (entries.length === 0) {
            return '';
        }
        return `
            <div class="capability-health-banner">
                ${entries.map(([key, capability]) => `
                    <div class="capability-health-item" data-status="${this.escapeHtml(capability?.status || 'unknown')}">
                        <strong>${this.escapeHtml(this.capabilityLabel(key))}</strong>
                        <span>${this.escapeHtml(this.capabilityStatusLabel(capability?.status))}</span>
                        ${capability?.reason ? `<small>${this.escapeHtml(capability.reason)}</small>` : ''}
                    </div>
                `).join('')}
            </div>
        `;
    }

    capabilityLabel(key) {
        const labels = {
            profile: 'Profile',
            knowledge_base_api: 'Knowledge Base',
            document_worker: 'Document Worker',
            database_catalog: 'Database Catalog',
            tool_gateway: 'Tool Gateway',
        };
        return labels[key] || key;
    }

    capabilityStatusLabel(status) {
        const labels = {
            ok: '可用',
            degraded: '降级',
            unknown: '未知',
        };
        return labels[status] || status || '未知';
    }

    async loadPermissionRequests(showError = true) {
        if (!this.currentUser) {
            this.permissionRequests = [];
            return false;
        }
        try {
            const response = await this.apiRequest('/permission-requests/mine', { method: 'GET' });
            const payload = await response.json();
            this.permissionRequests = payload?.data?.permission_requests || [];
            return true;
        } catch (error) {
            this.permissionRequests = [];
            if (showError) {
                this.showNotification(error.message, 'error');
            }
            return false;
        }
    }

    async loadRequestableResources(showError = true) {
        if (!this.currentUser) {
            this.requestableResources = [];
            return false;
        }
        try {
            const response = await this.apiRequest('/permission-requests/resources', { method: 'GET' });
            const payload = await response.json();
            this.requestableResources = payload?.data?.resources || [];
            return true;
        } catch (error) {
            this.requestableResources = [];
            if (showError) {
                this.showNotification(error.message, 'error');
            }
            return false;
        }
    }

    async loadDatabaseConfirmations(showError = true) {
        if (!this.currentUser) {
            this.databaseConfirmations = [];
            return false;
        }
        try {
            const response = await this.apiRequest('/database/confirmations', { method: 'GET' });
            const payload = await response.json();
            this.databaseConfirmations = payload?.data?.confirmations || [];
            return true;
        } catch (error) {
            this.databaseConfirmations = [];
            if (showError) {
                this.showNotification(error.message, 'error');
            }
            return false;
        }
    }

    async loadDatabaseCatalog(showError = true) {
        if (!this.currentUser) {
            this.databaseCatalog = null;
            return false;
        }
        try {
            const response = await this.apiRequest('/database/catalog', { method: 'GET' });
            const payload = await response.json();
            this.databaseCatalog = payload?.data?.catalog || null;
            return true;
        } catch (error) {
            this.databaseCatalog = null;
            if (showError) {
                this.showNotification(error.message, 'error');
            }
            return false;
        }
    }

    async loadDocuments({ page = this.documentPagination.page || 1, silent = false } = {}) {
        if (!this.currentUser) {
            this.documents = [];
            this.documentPagination = { page: 1, limit: 20, total: 0, hasNext: false };
            this.stopDocumentPolling();
            return false;
        }
        try {
            const limit = this.documentPagination.limit || 20;
            const response = await this.apiRequest(`/documents?page=${page}&limit=${limit}`, { method: 'GET' });
            const payload = await response.json();
            const data = payload?.data || {};
            this.documents = data.documents || [];
            this.documentPagination = {
                page: data.page || page,
                limit: data.limit || limit,
                total: data.total || 0,
                hasNext: Boolean(data.has_next),
            };
            if (this.profileModalMode === 'documents') {
                this.renderDocumentManager();
            }
            this.refreshDocumentPolling();
            return true;
        } catch (error) {
            this.documents = [];
            this.stopDocumentPolling();
            if (this.profileModalMode === 'documents') {
                this.renderDocumentManager(error.message || '文档列表加载失败');
            }
            if (!silent) {
                this.showNotification(error.message, 'error');
            }
            return false;
        }
    }

    renderDocumentManager(errorMessage = '') {
        if (!this.profileContent) return;
        if (this.profileModalTitle) this.profileModalTitle.textContent = '文件管理';
        const pagination = this.documentPagination || { page: 1, limit: 20, total: 0, hasNext: false };
        const page = pagination.page || 1;
        const total = pagination.total || 0;
        const canGoPrevious = page > 1;
        const canGoNext = Boolean(pagination.hasNext);
        this.profileContent.innerHTML = `
            <div class="document-manager-panel">
                <div class="document-manager-summary">
                    <strong>文档列表</strong>
                    <span>第 ${this.escapeHtml(String(page))} 页 · 共 ${this.escapeHtml(String(total))} 条 · 每页 ${this.escapeHtml(String(pagination.limit || 20))} 条</span>
                </div>
                ${errorMessage ? `<div class="document-manager-error">${this.escapeHtml(errorMessage)}</div>` : ''}
                <div class="document-manager-table">
                    <div class="document-manager-header">
                        <span>文件</span>
                        <span>状态</span>
                        <span>健康度</span>
                        <span>时间</span>
                        <span>Trace</span>
                    </div>
                    ${this.renderDocumentRows(this.documents)}
                </div>
                <div class="document-manager-pagination">
                    <button type="button" class="secondary-action-btn" data-document-page="${page - 1}" ${canGoPrevious ? '' : 'disabled'}>上一页</button>
                    <button type="button" class="secondary-action-btn" data-document-page="${page + 1}" ${canGoNext ? '' : 'disabled'}>下一页</button>
                </div>
            </div>
        `;
        this.profileContent.querySelectorAll('[data-document-page]').forEach((button) => {
            button.addEventListener('click', () => {
                const nextPage = Number(button.getAttribute('data-document-page'));
                if (Number.isFinite(nextPage) && nextPage > 0) {
                    this.loadDocuments({ page: nextPage });
                }
            });
        });
        this.profileContent.querySelectorAll('[data-document-health-doc]').forEach((button) => {
            button.addEventListener('click', () => {
                const docId = button.getAttribute('data-document-health-doc');
                if (docId) {
                    this.showDocumentHealthDetails(docId);
                }
            });
        });
        this.profileContent.querySelectorAll('[data-document-health-false-positive]').forEach((button) => {
            button.addEventListener('click', () => {
                const docId = button.getAttribute('data-document-health-false-positive');
                if (docId) {
                    this.markDocumentHealthFalsePositive(docId);
                }
            });
        });
    }

    renderDocumentRows(documents) {
        if (!Array.isArray(documents) || documents.length === 0) {
            return '<div class="document-manager-empty">暂无文档</div>';
        }
        return documents.map((document) => {
            const status = document.status || '';
            const error = document.error_message || '';
            const docId = document.id || document.doc_id || '';
            const health = document.health_check || {};
            return `
                <div class="document-manager-row">
                    <div class="document-manager-file">
                        <strong>${this.escapeHtml(document.filename || document.file_name || '-')}</strong>
                        <p>KB: ${this.escapeHtml(document.kb_id || '-')} · Doc: ${this.escapeHtml(docId || '-')}</p>
                    </div>
                    <div>
                        <span class="document-status-badge" data-tone="${this.documentStatusTone(status)}">
                            ${this.escapeHtml(this.documentStatusLabel(status))}
                        </span>
                        ${error ? `<p class="document-manager-error-text">${this.escapeHtml(error)}</p>` : ''}
                    </div>
                    <div class="document-manager-health">
                        <span class="document-health-badge" data-tone="${this.documentHealthTone(health.status)}">
                            ${this.escapeHtml(this.documentHealthLabel(health.status))}
                        </span>
                        <p>${this.escapeHtml(health.summary || '-')}</p>
                        ${docId ? `<button type="button" class="secondary-action-btn document-health-action" data-document-health-doc="${this.escapeHtml(docId)}">详情</button>` : ''}
                        ${this.renderDocumentHealthDetails(docId)}
                    </div>
                    <div class="document-manager-time">
                        <p>上传：${this.escapeHtml(this.formatDateTime(document.uploaded_at || document.created_at))}</p>
                        <p>更新：${this.escapeHtml(this.formatDateTime(document.updated_at))}</p>
                    </div>
                    <div class="document-manager-trace">
                        ${document.trace_id ? `<code>${this.escapeHtml(document.trace_id)}</code>` : '-'}
                    </div>
                </div>
            `;
        }).join('');
    }

    documentHealthLabel(status) {
        const labels = {
            pending: '待检查',
            passed: '通过',
            warning: '警告',
            failed: '失败',
            skipped: '跳过',
        };
        return labels[status] || status || '待检查';
    }

    documentHealthTone(status) {
        if (status === 'passed') return 'success';
        if (status === 'failed') return 'danger';
        if (status === 'warning') return 'warning';
        if (status === 'skipped') return 'muted';
        return 'info';
    }

    async showDocumentHealthDetails(docId) {
        try {
            const response = await this.apiRequest(`/documents/${encodeURIComponent(docId)}/health`, { method: 'GET' });
            const payload = await response.json();
            const data = payload?.data || {};
            this.documentHealthDetails[docId] = data;
            this.documents = this.documents.map((document) => {
                const currentDocId = document.id || document.doc_id;
                if (currentDocId !== docId) return document;
                return {
                    ...document,
                    health_check: {
                        status: data.status,
                        summary: data.summary,
                        checked_at: data.checked_at,
                        marked_as_false_positive: Boolean(data.marked_as_false_positive),
                        false_positive_reason: data.false_positive_reason || '',
                    },
                };
            });
            if (this.profileModalMode === 'documents') {
                this.renderDocumentManager();
            }
        } catch (error) {
            this.showNotification(error.message || '健康检查详情加载失败', 'error');
        }
    }

    async markDocumentHealthFalsePositive(docId) {
        const reason = window.prompt('误报原因');
        if (!reason || !reason.trim()) return;
        try {
            const response = await this.apiRequest(`/documents/${encodeURIComponent(docId)}/health/mark-false-positive`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ reason: reason.trim() }),
            });
            const payload = await response.json();
            const data = payload?.data || {};
            this.documentHealthDetails[docId] = data;
            this.documents = this.documents.map((document) => {
                const currentDocId = document.id || document.doc_id;
                if (currentDocId !== docId) return document;
                return {
                    ...document,
                    health_check: {
                        status: data.status,
                        summary: data.summary,
                        checked_at: data.checked_at,
                        marked_as_false_positive: Boolean(data.marked_as_false_positive),
                        false_positive_reason: data.false_positive_reason || '',
                    },
                };
            });
            if (this.profileModalMode === 'documents') {
                this.renderDocumentManager();
            }
        } catch (error) {
            this.showNotification(error.message || '误报标记失败', 'error');
        }
    }

    renderDocumentHealthDetails(docId) {
        if (!docId || !this.documentHealthDetails[docId]) return '';
        const details = this.documentHealthDetails[docId];
        const retrieval = details.retrieval || {};
        const sourceRef = details.source_ref || {};
        const pdf = details.pdf || {};
        const retrievalQueries = Array.isArray(retrieval.queries) ? retrieval.queries : [];
        const sourceErrors = Array.isArray(sourceRef.errors) ? sourceRef.errors : [];
        const pdfErrors = Array.isArray(pdf.errors) ? pdf.errors : [];
        return `
            <div class="document-health-details">
                <div><strong>检索</strong><span>${retrieval.passed ? '通过' : '未通过'}</span></div>
                ${retrievalQueries.map((item) => `
                    <p>${this.escapeHtml(item.query || '-')} → ${item.hit ? '命中' : '未命中'}${item.rank ? ` #${this.escapeHtml(String(item.rank))}` : ''}</p>
                `).join('')}
                <div><strong>Source Ref</strong><span>${sourceRef.passed ? '通过' : '未通过'}</span></div>
                ${sourceErrors.map((item) => `<p>${this.escapeHtml(item)}</p>`).join('')}
                <div><strong>PDF</strong><span>${pdf.passed ? '通过' : (pdf.skipped || '未通过')}</span></div>
                ${pdfErrors.map((item) => `<p>${this.escapeHtml(item)}</p>`).join('')}
                ${details.marked_as_false_positive ? `<p>已标记误报：${this.escapeHtml(details.false_positive_reason || '-')}</p>` : `<button type="button" class="secondary-action-btn document-health-action" data-document-health-false-positive="${this.escapeHtml(docId)}">标记误报</button>`}
            </div>
        `;
    }

    documentStatusLabel(status) {
        const labels = {
            uploaded: '已上传',
            upload_failed: '上传失败',
            parse_pending: '等待解析',
            enqueue_failed: '入队失败',
            parsing: '解析中',
            parsed: '已解析',
            parse_failed: '解析失败',
            index_pending: '等待索引',
            indexing: '索引中',
            indexed: '已索引',
            index_failed: '索引失败',
        };
        return labels[status] || status || '-';
    }

    documentStatusTone(status) {
        if (status === 'indexed') return 'success';
        if (['upload_failed', 'enqueue_failed', 'parse_failed', 'index_failed'].includes(status)) return 'danger';
        if (['parsing', 'indexing'].includes(status)) return 'info';
        return 'warning';
    }

    isDocumentTerminal(status) {
        return ['indexed', 'upload_failed', 'enqueue_failed', 'parse_failed', 'index_failed'].includes(status);
    }

    refreshDocumentPolling() {
        const shouldPoll = (
            this.profileModalMode === 'documents' &&
            Array.isArray(this.documents) &&
            this.documents.some((document) => !this.isDocumentTerminal(document.status))
        );
        if (shouldPoll) {
            this.startDocumentPolling();
        } else {
            this.stopDocumentPolling();
        }
    }

    startDocumentPolling() {
        if (this.documentPollingTimer) return;
        this.documentPollingTimer = setInterval(() => this.loadDocuments({ silent: true }), 10000);
    }

    stopDocumentPolling() {
        if (!this.documentPollingTimer) return;
        clearInterval(this.documentPollingTimer);
        this.documentPollingTimer = null;
    }

    renderDatabaseCatalog() {
        if (!this.profileContent) return;
        if (this.profileModalTitle) this.profileModalTitle.textContent = '数据库能力';
        const catalog = this.databaseCatalog || {};
        const details = this.currentProfile?.capabilities?.database_catalog?.details || {};
        const visibleDatabases = catalog.visible_databases || details.visible_databases || [];
        const visibleTools = catalog.visible_tools || details.visible_tools || [];
        const visibleTables = catalog.visible_tables || this.currentProfile?.database_demo?.visible_tables || [];
        const safeSqlKernel = catalog.safe_sql_kernel || details.safe_sql_kernel || {};
        const writeOperationsEnabled = Boolean(catalog.write_operations_enabled || details.write_operations_enabled);
        const confirmationRequiredFor = catalog.confirmation_required_for || details.confirmation_required_for || [];
        const lastAuditStatus = catalog.last_audit_status || details.last_audit_status || {};
        const unavailableReason = catalog.unavailable_reason || this.currentProfile?.database_demo?.unavailable_reason || '';

        this.profileContent.innerHTML = `
            <div class="database-catalog-panel">
                <div class="database-catalog-grid">
                    <div class="database-catalog-card">
                        <span>可见 DB</span>
                        <strong>${this.escapeHtml(this.formatCompactList(visibleDatabases))}</strong>
                    </div>
                    <div class="database-catalog-card">
                        <span>可用工具</span>
                        <strong>${this.escapeHtml(this.formatCompactList(visibleTools))}</strong>
                    </div>
                    <div class="database-catalog-card">
                        <span>SafeSqlKernel</span>
                        <strong>${this.escapeHtml(safeSqlKernel.status || 'unknown')}</strong>
                    </div>
                    <div class="database-catalog-card">
                        <span>写操作</span>
                        <strong>${writeOperationsEnabled ? '已开启' : '未开启'}</strong>
                    </div>
                    <div class="database-catalog-card">
                        <span>Confirmation</span>
                        <strong>${this.escapeHtml(this.formatCompactList(confirmationRequiredFor))}</strong>
                    </div>
                    <div class="database-catalog-card">
                        <span>Audit</span>
                        <strong>${this.escapeHtml(lastAuditStatus.status || 'unknown')}</strong>
                    </div>
                </div>
                ${unavailableReason ? `
                    <div class="database-catalog-unavailable">${this.escapeHtml(unavailableReason)}</div>
                ` : ''}
                <div class="database-catalog-table">
                    ${this.renderDatabaseCatalogTableRows(visibleTables)}
                </div>
            </div>
        `;
    }

    renderDatabaseCatalogTableRows(visibleTables) {
        if (!Array.isArray(visibleTables) || visibleTables.length === 0) {
            return '<div class="database-catalog-empty">暂无可见表</div>';
        }
        return visibleTables.map((table) => {
            const columns = (table.visible_columns || []).map((column) => (
                column.column_name || column.name || column
            ));
            return `
                <div class="database-catalog-table-row">
                    <div>
                        <strong>${this.escapeHtml(table.table_name || table.name || '-')}</strong>
                        <p>${this.escapeHtml(table.resource_id || '')}</p>
                    </div>
                    <div>${this.escapeHtml(this.formatCompactList(columns))}</div>
                </div>
            `;
        }).join('');
    }

    renderPermissions() {
        if (!this.profileContent) return;
        if (this.profileModalTitle) this.profileModalTitle.textContent = '我的权限';
        const advancedType = this.defaultAdvancedPermissionType();
        const advancedResource = this.resourcesForPermissionType(advancedType)[0] || null;
        this.profileContent.innerHTML = `
            <div class="permission-request-form" id="permissionRequestForm">
                <form class="permission-request-section" id="quickPermissionRequestForm">
                    <div class="profile-section-title">知识库快捷申请</div>
                    <input type="hidden" name="resource_type" value="knowledge_base">
                    <input type="hidden" name="action" value="read">
                    <div class="permission-request-grid permission-request-grid-compact">
                        <label>
                            知识库
                            <select id="quickPermissionKbId" name="resource_id" required>
                                ${this.renderQuickKbOptions()}
                            </select>
                        </label>
                        <label>
                            访问级别
                            <select id="quickPermissionAction" disabled>
                                <option value="read">部门资料</option>
                            </select>
                        </label>
                    </div>
                    <label>
                        申请原因
                        <textarea id="quickPermissionReason" name="reason" rows="3"></textarea>
                    </label>
                    <button type="submit" class="primary-action-btn">提交知识库申请</button>
                </form>

                <form class="permission-request-section" id="advancedPermissionRequestForm">
                    <div class="profile-section-title">高级资源申请</div>
                    <div class="permission-request-grid">
                        <label>
                            资源类型
                            <select id="advancedPermissionResourceType" name="resource_type" required>
                                ${this.renderAdvancedTypeOptions(advancedType)}
                            </select>
                        </label>
                        <label>
                            资源
                            <select id="advancedPermissionResourceId" name="resource_id" required>
                                ${this.renderAdvancedResourceOptions(advancedType, advancedResource?.resource_id || '')}
                            </select>
                        </label>
                        <label>
                            Action
                            <select id="advancedPermissionAction" name="action" required>
                                ${this.renderAdvancedActionOptions(advancedResource)}
                            </select>
                        </label>
                    </div>
                    <label>
                        申请原因
                        <textarea id="advancedPermissionReason" name="reason" rows="3"></textarea>
                    </label>
                    <button type="submit" class="primary-action-btn">提交高级申请</button>
                </form>
            </div>
            <div class="permission-request-list">
                ${this.renderPermissionRequestRows()}
            </div>
            <div class="database-confirmation-section">
                <div class="profile-section-title">数据库操作确认</div>
                <div class="database-confirmation-list">
                    ${this.renderDatabaseConfirmationRows()}
                </div>
            </div>
        `;
        const quickForm = document.getElementById('quickPermissionRequestForm');
        if (quickForm) {
            quickForm.addEventListener('submit', (event) => this.submitPermissionRequest(event));
        }
        const advancedForm = document.getElementById('advancedPermissionRequestForm');
        if (advancedForm) {
            advancedForm.addEventListener('submit', (event) => this.submitPermissionRequest(event));
        }
        const advancedTypeSelect = document.getElementById('advancedPermissionResourceType');
        if (advancedTypeSelect) {
            advancedTypeSelect.addEventListener('change', () => this.updateAdvancedPermissionOptions());
        }
        const advancedResourceSelect = document.getElementById('advancedPermissionResourceId');
        if (advancedResourceSelect) {
            advancedResourceSelect.addEventListener('change', () => this.updateAdvancedPermissionActionOptions());
        }
        this.profileContent.querySelectorAll('[data-confirmation-action]').forEach((button) => {
            button.addEventListener('click', (event) => this.handleDatabaseConfirmationAction(event));
        });
    }

    defaultAdvancedPermissionType() {
        return ['tool', 'database', 'document'].find((type) => this.resourcesForPermissionType(type).length > 0) || '';
    }

    resourcesForPermissionType(resourceType) {
        return this.requestableResources.filter((resource) => (
            resource.resource_type === resourceType && !resource.already_granted
        ));
    }

    renderQuickKbOptions() {
        const resources = this.resourcesForPermissionType('knowledge_base');
        if (resources.length === 0) {
            return '<option value="">暂无可申请知识库</option>';
        }
        return resources.map((resource) => {
            const documentCount = resource.metadata?.document_count;
            const suffix = Number.isFinite(documentCount) ? `（${documentCount} 个文件）` : '';
            return `<option value="${this.escapeHtml(resource.resource_id)}">${this.escapeHtml(this.resourceDisplayName(resource) + suffix)}</option>`;
        }).join('');
    }

    renderAdvancedTypeOptions(selectedType) {
        const labels = {
            tool: '工具',
            database: '数据库',
            document: '文档',
        };
        const types = Object.keys(labels).filter((type) => this.resourcesForPermissionType(type).length > 0);
        if (types.length === 0) {
            return '<option value="">暂无可申请资源</option>';
        }
        return types.map((type) => `
            <option value="${this.escapeHtml(type)}" ${type === selectedType ? 'selected' : ''}>${this.escapeHtml(labels[type])}</option>
        `).join('');
    }

    renderAdvancedResourceOptions(resourceType, selectedResourceId = '') {
        const resources = this.resourcesForPermissionType(resourceType);
        if (resources.length === 0) {
            return '<option value="">暂无可申请资源</option>';
        }
        return resources.map((resource) => `
            <option value="${this.escapeHtml(resource.resource_id)}" ${resource.resource_id === selectedResourceId ? 'selected' : ''}>${this.escapeHtml(this.resourceDisplayName(resource))}</option>
        `).join('');
    }

    renderAdvancedActionOptions(resource) {
        if (!resource) {
            return '<option value="">无可选 action</option>';
        }
        const actionOptions = (
            resource.action_options || (resource.actions_supported || []).map((action) => ({
                action,
                display_name: this.permissionActionLabel(action),
                already_granted: false,
            }))
        ).filter((option) => !option.already_granted);
        if (actionOptions.length === 0) {
            return '<option value="">无可选 action</option>';
        }
        return actionOptions.map((option) => `
            <option value="${this.escapeHtml(option.action)}">${this.escapeHtml(option.display_name || option.action)}</option>
        `).join('');
    }

    updateAdvancedPermissionOptions() {
        const typeSelect = document.getElementById('advancedPermissionResourceType');
        const resourceSelect = document.getElementById('advancedPermissionResourceId');
        if (!typeSelect || !resourceSelect) return;
        const resources = this.resourcesForPermissionType(typeSelect.value);
        const selectedResource = resources[0] || null;
        resourceSelect.innerHTML = this.renderAdvancedResourceOptions(typeSelect.value, selectedResource?.resource_id || '');
        this.updateAdvancedPermissionActionOptions();
    }

    updateAdvancedPermissionActionOptions() {
        const typeSelect = document.getElementById('advancedPermissionResourceType');
        const resourceSelect = document.getElementById('advancedPermissionResourceId');
        const actionSelect = document.getElementById('advancedPermissionAction');
        if (!typeSelect || !resourceSelect || !actionSelect) return;
        const resource = this.requestableResources.find((item) => (
            item.resource_type === typeSelect.value && item.resource_id === resourceSelect.value
        ));
        actionSelect.innerHTML = this.renderAdvancedActionOptions(resource);
    }

    resourceDisplayName(resource) {
        return resource?.metadata?.display_name || resource?.name || resource?.resource_id || '-';
    }

    renderPermissionRequestRows() {
        if (this.permissionRequests.length === 0) {
            return '<div class="permission-request-empty">暂无权限申请</div>';
        }
        return this.permissionRequests.map((request) => `
            <div class="permission-request-row">
                <div>
                    <strong>${this.escapeHtml(request.resource_display_name || request.resource_id)}</strong>
                    <p>${this.escapeHtml(request.resource_type)}:${this.escapeHtml(request.resource_id)}</p>
                    <p>${this.escapeHtml(request.action_display_name || this.permissionActionLabel(request.action))} · ${this.escapeHtml(request.review_queue || '-')}</p>
                    <p>${this.escapeHtml(request.reason || '未填写原因')}</p>
                    ${request.approver_reason ? `<p>审批备注：${this.escapeHtml(request.approver_reason)}</p>` : ''}
                </div>
                <div>
                    <span class="permission-request-status" data-tone="${this.permissionRequestStatusTone(request.status)}">
                        ${this.escapeHtml(this.permissionRequestStatusLabel(request.status))}
                    </span>
                    <p>${this.escapeHtml(this.formatDateTime(request.created_at))}</p>
                </div>
            </div>
        `).join('');
    }

    renderDatabaseConfirmationRows() {
        if (this.databaseConfirmations.length === 0) {
            return '<div class="database-confirmation-empty">暂无待确认数据库操作</div>';
        }
        return this.databaseConfirmations.map((confirmation) => {
            const pending = confirmation.status === 'pending';
            const summary = confirmation.summary || {};
            const targetTables = (summary.target_tables || confirmation.target_tables || []).join(', ') || '-';
            const targetColumns = (summary.target_columns || confirmation.target_columns || []).join(', ') || '-';
            const rows = summary.estimated_affected_rows ?? '无法可靠估算';
            return `
                <div class="database-confirmation-row" data-status="${this.escapeHtml(confirmation.status)}">
                    <div class="database-confirmation-main">
                        <div class="database-confirmation-title">
                            <strong>${this.escapeHtml(confirmation.operation_type || '-')}</strong>
                            <span class="database-confirmation-status" data-tone="${this.databaseConfirmationStatusTone(confirmation.status)}">
                                ${this.escapeHtml(this.databaseConfirmationStatusLabel(confirmation.status))}
                            </span>
                        </div>
                        <div class="database-confirmation-meta">
                            ${this.escapeHtml(confirmation.database_id || '-')} · 风险 ${this.escapeHtml(confirmation.risk_level || '-')} · 预计影响 ${this.escapeHtml(String(rows))} 行
                        </div>
                        <div class="database-confirmation-targets">
                            表：${this.escapeHtml(targetTables)} · 列：${this.escapeHtml(targetColumns)}
                        </div>
                        <code class="database-confirmation-sql">${this.escapeHtml(confirmation.sql || '')}</code>
                        <div class="database-confirmation-meta">
                            创建：${this.escapeHtml(this.formatDateTime(confirmation.created_at))} · 过期：${this.escapeHtml(this.formatDateTime(confirmation.expires_at))}
                        </div>
                    </div>
                    <div class="database-confirmation-actions">
                        <button type="button" class="secondary-action-btn" data-confirmation-action="cancel" data-confirmation-id="${this.escapeHtml(confirmation.confirmation_id)}" ${pending ? '' : 'disabled'}>取消</button>
                        <button type="button" class="danger-action-btn" data-confirmation-action="confirm" data-confirmation-id="${this.escapeHtml(confirmation.confirmation_id)}" ${pending ? '' : 'disabled'}>确认执行</button>
                    </div>
                </div>
            `;
        }).join('');
    }

    async handleDatabaseConfirmationAction(event) {
        const button = event.currentTarget;
        const confirmationId = button?.dataset?.confirmationId || '';
        const action = button?.dataset?.confirmationAction || '';
        if (!confirmationId || !['confirm', 'cancel'].includes(action)) return;
        if (action === 'confirm') {
            await this.confirmDatabaseOperation(confirmationId);
        } else {
            await this.cancelDatabaseOperation(confirmationId);
        }
    }

    async confirmDatabaseOperation(confirmationId) {
        await this.runDatabaseConfirmationAction(confirmationId, 'confirm');
    }

    async cancelDatabaseOperation(confirmationId) {
        await this.runDatabaseConfirmationAction(confirmationId, 'cancel');
    }

    async runDatabaseConfirmationAction(confirmationId, action) {
        try {
            await this.apiRequest(`/database/confirmations/${confirmationId}/${action}`, {
                method: 'POST',
            });
            await this.loadDatabaseConfirmations(false);
            this.renderPermissions();
            this.showNotification(action === 'confirm' ? '数据库操作已执行' : '数据库操作已取消', 'success');
        } catch (error) {
            await this.loadDatabaseConfirmations(false);
            this.renderPermissions();
            this.showNotification(error.message, 'error');
        }
    }

    async submitPermissionRequest(event) {
        event.preventDefault();
        const formData = new FormData(event.currentTarget);
        const body = {
            resource_type: String(formData.get('resource_type') || '').trim(),
            resource_id: String(formData.get('resource_id') || '').trim(),
            action: String(formData.get('action') || '').trim(),
            reason: String(formData.get('reason') || '').trim(),
        };
        if (!body.resource_type || !body.resource_id || !body.action) {
            this.showNotification('请填写资源类型、Resource ID 和 Action', 'warning');
            return;
        }
        try {
            await this.apiRequest('/permission-requests', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            await this.loadPermissionRequests(false);
            this.renderPermissions();
            this.showNotification('权限申请已提交', 'success');
        } catch (error) {
            this.showNotification(error.message, 'error');
        }
    }

    permissionRequestStatusTone(status) {
        if (status === 'approved') return 'success';
        if (status === 'rejected') return 'danger';
        return 'warning';
    }

    permissionRequestStatusLabel(status) {
        const labels = {
            pending: '待审批',
            approved: '已通过',
            rejected: '已拒绝',
        };
        return labels[status] || status || '-';
    }

    permissionActionLabel(action) {
        const labels = {
            read: '读取',
            use: '使用',
            write: '写入',
            admin: '管理',
            execute: '执行',
        };
        return labels[action] || action || '-';
    }

    databaseConfirmationStatusTone(status) {
        if (status === 'executed') return 'success';
        if (status === 'failed' || status === 'expired') return 'danger';
        if (status === 'cancelled') return 'muted';
        return 'warning';
    }

    databaseConfirmationStatusLabel(status) {
        const labels = {
            pending: '待确认',
            confirmed: '已确认',
            executing: '执行中',
            executed: '已执行',
            cancelled: '已取消',
            expired: '已过期',
            failed: '失败',
        };
        return labels[status] || status || '-';
    }

    formatDateTime(value) {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return date.toLocaleString('zh-CN', { hour12: false });
    }

    formatCompactList(items) {
        if (!Array.isArray(items) || items.length === 0) return '无';
        return items.map((item) => String(item || '')).filter(Boolean).join(', ') || '无';
    }

    formatUnavailable(reasons) {
        const entries = Object.entries(reasons);
        if (entries.length === 0) return '无';
        return entries.map(([key, reason]) => `${key}: ${reason}`).join(', ');
    }

    // 切换工具菜单显示/隐藏
    toggleToolsMenu() {
        if (this.toolsMenu && this.toolsBtn) {
            const wrapper = this.toolsBtn.closest('.tools-btn-wrapper');
            if (wrapper) {
                wrapper.classList.toggle('active');
            }
        }
    }

    // 关闭工具菜单
    closeToolsMenu() {
        if (this.toolsMenu && this.toolsBtn) {
            const wrapper = this.toolsBtn.closest('.tools-btn-wrapper');
            if (wrapper) {
                wrapper.classList.remove('active');
            }
        }
    }

    // 新建对话
    newChat() {
        if (this.isStreaming) {
            this.showNotification('请等待当前对话完成后再新建对话', 'warning');
            return;
        }
        
        // 如果当前有对话内容，且不是从历史记录加载的，才保存为新的历史对话
        // 如果是从历史记录加载的，只需要更新该历史记录
        if (this.currentChatHistory.length > 0) {
            if (this.isCurrentChatFromHistory) {
                // 当前对话是从历史记录加载的，更新该历史记录
                this.updateCurrentChatHistory();
            } else {
                // 当前对话是新对话，保存为新的历史对话
                this.saveCurrentChat();
            }
        }
        
        // 停止所有进行中的操作
        this.isStreaming = false;
        
        // 清空输入框
        if (this.messageInput) {
            this.messageInput.value = '';
        }
        
        // 清空当前对话历史
        this.currentChatHistory = [];
        
        // 重置标记
        this.isCurrentChatFromHistory = false;
        
        // 清空聊天记录
        if (this.chatMessages) {
            this.chatMessages.innerHTML = '';
        }
        
        // 生成新的会话ID
        this.sessionId = this.generateSessionId();
        
        // 重置模式为快速
        this.currentMode = 'quick';
        this.updateUI();
        
        // 重新设置居中样式（确保对话框居中显示）
        this.checkAndSetCentered();
        
        // 确保容器有过渡动画
        if (this.chatContainer) {
            this.chatContainer.style.transition = 'all 0.5s ease';
        }
        
        // 更新历史对话列表
        this.renderChatHistory();
    }
    
    // 保存当前对话到历史记录（新建）
    saveCurrentChat() {
        if (this.currentChatHistory.length === 0) {
            return;
        }
        
        // 检查是否已存在相同ID的历史记录
        const existingIndex = this.chatHistories.findIndex(h => h.id === this.sessionId);
        if (existingIndex !== -1) {
            // 如果已存在，更新而不是新建
            this.updateCurrentChatHistory();
            return;
        }
        
        // 获取对话标题（使用第一条用户消息的前30个字符）
        const firstUserMessage = this.currentChatHistory.find(msg => msg.type === 'user');
        const title = firstUserMessage ? 
            (firstUserMessage.content.substring(0, 30) + (firstUserMessage.content.length > 30 ? '...' : '')) : 
            '新对话';
        
        const chatHistory = {
            id: this.sessionId,
            title: title,
            messages: [...this.currentChatHistory],
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
        };
        
        // 添加到历史记录列表的开头
        this.chatHistories.unshift(chatHistory);
        
        // 限制历史记录数量（最多保存50条）
        if (this.chatHistories.length > 50) {
            this.chatHistories = this.chatHistories.slice(0, 50);
        }
        
        // 保存到localStorage
        this.saveChatHistories();
    }
    
    // 更新当前对话的历史记录
    updateCurrentChatHistory() {
        if (this.currentChatHistory.length === 0) {
            return;
        }
        
        const existingIndex = this.chatHistories.findIndex(h => h.id === this.sessionId);
        if (existingIndex === -1) {
            // 如果不存在，调用保存方法
            this.saveCurrentChat();
            return;
        }
        
        // 更新现有的历史记录
        const history = this.chatHistories[existingIndex];
        history.messages = [...this.currentChatHistory];
        history.updatedAt = new Date().toISOString();
        
        // 如果标题需要更新（第一条消息改变了）
        const firstUserMessage = this.currentChatHistory.find(msg => msg.type === 'user');
        if (firstUserMessage) {
            const newTitle = firstUserMessage.content.substring(0, 30) + (firstUserMessage.content.length > 30 ? '...' : '');
            if (history.title !== newTitle) {
                history.title = newTitle;
            }
        }
        
        // 保存到localStorage
        this.saveChatHistories();
    }
    
    // 加载历史对话列表
    getChatHistoryStorageKey() {
        const userId = this.currentUser?.user_id || this.currentProfile?.user?.user_id;
        return userId ? `chatHistories:${userId}` : null;
    }

    loadChatHistories() {
        const storageKey = this.getChatHistoryStorageKey();
        if (!storageKey) {
            return [];
        }
        try {
            const stored = localStorage.getItem(storageKey);
            return stored ? JSON.parse(stored) : [];
        } catch (e) {
            console.error('加载历史对话失败:', e);
            return [];
        }
    }

    async loadServerChatHistories() {
        try {
            const response = await this.apiRequest('/chat/sessions', {
                method: 'GET'
            });
            const payload = await response.json();
            const sessions = payload?.data?.sessions || [];
            const histories = sessions.map(session => ({
                id: session.session_id || session.id,
                title: session.title || '新对话',
                messages: [],
                createdAt: session.created_at || new Date().toISOString(),
                updatedAt: session.updated_at || session.created_at || new Date().toISOString(),
                serverBacked: true
            })).filter(session => session.id);
            this.chatHistories = histories;
            this.saveChatHistories();
            return histories;
        } catch (error) {
            console.warn('server sessions failed, using local cache', error);
            return this.loadChatHistories();
        }
    }
    
    // 保存历史对话列表到localStorage
    saveChatHistories() {
        const storageKey = this.getChatHistoryStorageKey();
        if (!storageKey) {
            return;
        }
        try {
            localStorage.setItem(storageKey, JSON.stringify(this.chatHistories));
        } catch (e) {
            console.error('保存历史对话失败:', e);
        }
    }
    
    // 渲染历史对话列表
    renderChatHistory() {
        if (!this.chatHistoryList) {
            return;
        }
        
        this.chatHistoryList.innerHTML = '';
        
        if (this.chatHistories.length === 0) {
            return;
        }
        
        this.chatHistories.forEach((history, index) => {
            const historyItem = document.createElement('div');
            historyItem.className = 'history-item';
            historyItem.dataset.historyId = history.id;
            
            historyItem.innerHTML = `
                <div class="history-item-content">
                    <span class="history-item-title">${this.escapeHtml(history.title)}</span>
                </div>
                <button class="history-item-delete" data-history-id="${history.id}" title="删除">
                    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                </button>
            `;
            
            // 点击历史项加载对话
            historyItem.addEventListener('click', (e) => {
                if (!e.target.closest('.history-item-delete')) {
                    this.loadChatHistory(history.id);
                }
            });
            
            // 删除历史对话
            const deleteBtn = historyItem.querySelector('.history-item-delete');
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteChatHistory(history.id);
            });
            
            this.chatHistoryList.appendChild(historyItem);
        });
    }
    
    // 加载历史对话
    async loadChatHistory(historyId) {
        const history = this.chatHistories.find(h => h.id === historyId);
        if (!history) {
            return;
        }
        
        // 如果当前有对话内容，且不是同一个对话，先保存
        if (this.currentChatHistory.length > 0 && this.sessionId !== historyId) {
            if (this.isCurrentChatFromHistory) {
                // 如果当前对话也是从历史记录加载的，更新它
                this.updateCurrentChatHistory();
            } else {
                // 如果当前对话是新对话，保存为新历史
                this.saveCurrentChat();
            }
        }
        
        try {
            // 从后端获取会话历史
            const response = await this.apiRequest(`/chat/session/${historyId}`, {
                method: 'GET'
            });
            if (response.ok) {
                const data = await response.json();
                const backendHistory = data.history || [];
                
                // 更新会话ID
                this.sessionId = history.id;
                this.isCurrentChatFromHistory = true;
                
                // 清空并重新渲染消息
                if (this.chatMessages) {
                    this.chatMessages.innerHTML = '';
                    
                    // 如果后端有历史记录，使用后端的
                    if (backendHistory.length > 0) {
                        this.currentChatHistory = [];
                        backendHistory.forEach(msg => {
                            // 后端返回格式: {role: "user|assistant", content: "...", timestamp: "..."}
                            const messageType = msg.role === 'user' ? 'user' : 'bot';
                            this.addMessage(messageType, msg.content, false, false);
                        });
                    } else {
                        // 否则使用localStorage的历史记录
                        this.currentChatHistory = [...history.messages];
                        history.messages.forEach(msg => {
                            this.addMessage(msg.type, msg.content, false, false);
                        });
                    }
                }
            } else {
                // 如果后端请求失败，使用localStorage的历史记录
                console.warn('从后端加载历史失败，使用本地缓存');
                this.sessionId = history.id;
                this.currentChatHistory = [...history.messages];
                this.isCurrentChatFromHistory = true;
                
                if (this.chatMessages) {
                    this.chatMessages.innerHTML = '';
                    history.messages.forEach(msg => {
                        this.addMessage(msg.type, msg.content, false, false);
                    });
                }
            }
        } catch (error) {
            console.error('加载会话历史失败:', error);
            // 出错时使用localStorage的历史记录
            this.sessionId = history.id;
            this.currentChatHistory = [...history.messages];
            this.isCurrentChatFromHistory = true;
            
            if (this.chatMessages) {
                this.chatMessages.innerHTML = '';
                history.messages.forEach(msg => {
                    this.addMessage(msg.type, msg.content, false, false);
                });
            }
        }
        
        // 更新UI
        this.checkAndSetCentered();
        this.renderChatHistory();
    }
    
    // 删除历史对话
    async deleteChatHistory(historyId) {
        try {
            // 调用后端API清空会话
            const response = await this.apiRequest('/chat/clear', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: historyId
                })
            });

            if (!response.ok) {
                throw new Error('清空会话失败');
            }

            const result = await response.json();
            
            if (result.status === 'success') {
                // 从本地存储中删除
                this.chatHistories = this.chatHistories.filter(h => h.id !== historyId);
                this.saveChatHistories();
                this.renderChatHistory();
                
                // 如果删除的是当前对话，清空当前对话
                if (this.sessionId === historyId) {
                    this.currentChatHistory = [];
                    if (this.chatMessages) {
                        this.chatMessages.innerHTML = '';
                    }
                    this.sessionId = this.generateSessionId();
                    this.checkAndSetCentered();
                }
                
                this.showNotification('会话已清空', 'success');
            } else {
                throw new Error(result.message || '清空会话失败');
            }
        } catch (error) {
            console.error('删除历史对话失败:', error);
            this.showNotification('删除失败: ' + error.message, 'error');
        }
    }

    // 切换模式下拉菜单
    toggleModeDropdown() {
        if (this.modeSelectorBtn && this.modeDropdown) {
            const wrapper = this.modeSelectorBtn.closest('.mode-selector-wrapper');
            if (wrapper) {
                wrapper.classList.toggle('active');
            }
        }
    }

    // 关闭模式下拉菜单
    closeModeDropdown() {
        if (this.modeSelectorBtn && this.modeDropdown) {
            const wrapper = this.modeSelectorBtn.closest('.mode-selector-wrapper');
            if (wrapper) {
                wrapper.classList.remove('active');
            }
        }
    }

    // 选择模式
    selectMode(mode) {
        if (this.isStreaming) {
            this.showNotification('请等待当前对话完成后再切换模式', 'warning');
            return;
        }
        
        this.currentMode = mode;
        this.updateUI();
        
        const modeNames = {
            'quick': '快速',
            'stream': '流式'
        };
        
        this.showNotification(`已切换到${modeNames[mode]}模式`, 'info');
    }

    // 更新UI
    updateUI() {
        // 更新模式选择器显示
        if (this.currentModeText) {
            const modeNames = {
                'quick': '快速',
                'stream': '流式'
            };
            this.currentModeText.textContent = modeNames[this.currentMode] || '快速';
        }
        
        // 更新下拉菜单选中状态
        const dropdownItems = document.querySelectorAll('.dropdown-item');
        dropdownItems.forEach(item => {
            const mode = item.getAttribute('data-mode');
            if (mode === this.currentMode) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
        
        // 更新发送按钮状态
        if (this.sendButton) {
            this.sendButton.disabled = this.isStreaming;
        }
        
        // 更新输入框状态
        if (this.messageInput) {
            this.messageInput.disabled = this.isStreaming;
            this.messageInput.placeholder = '问问智能OnCall助手';
        }
    }

    // 生成随机会话ID
    generateSessionId() {
        return 'session_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
    }

    // 发送消息
    async sendMessage() {
        let message = '';
        if (this.messageInput) {
            message = this.messageInput.value.trim();
        }
        
        if (!message) {
            this.showNotification('请输入消息内容', 'warning');
            return;
        }

        if (this.isStreaming) {
            this.showNotification('请等待当前对话完成', 'warning');
            return;
        }

        // 显示用户消息
        this.addMessage('user', message);
        
        // 清空输入框
        if (this.messageInput) {
            this.messageInput.value = '';
        }

        // 设置发送状态
        this.isStreaming = true;
        this.updateUI();

        try {
            if (this.currentMode === 'quick') {
                await this.sendQuickMessage(message);
            } else if (this.currentMode === 'stream') {
                await this.sendStreamMessage(message);
            }
        } catch (error) {
            console.error('发送消息失败:', error);
            const errorMessage = this.addMessage('assistant', '', false, false);
            const errorContent = errorMessage?.querySelector('.message-content');
            if (errorContent) {
                errorContent.innerHTML = this.renderErrorMessage(error, '发送消息失败');
            }
        } finally {
            this.isStreaming = false;
            this.updateUI();
            
            // 如果当前对话是从历史记录加载的，更新历史记录
            if (this.isCurrentChatFromHistory && this.currentChatHistory.length > 0) {
                this.updateCurrentChatHistory();
                this.renderChatHistory(); // 更新历史对话列表显示
            }
        }
    }

    // 发送快速消息（普通对话）
    async sendQuickMessage(message) {
        // 添加等待提示消息
        const loadingMessage = this.addLoadingMessage('正在思考...');
        const loadingState = this.startLoadingState('chat', loadingMessage);
        
        try {
            const response = await this.apiRequest('/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    ...this.buildChatRequestBody(message)
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP错误: ${response.status}`);
            }

            const data = await response.json();
            console.log('[sendQuickMessage] 响应数据:', JSON.stringify(data));
            
            // 移除等待提示消息
            loadingState.stop();
            if (loadingMessage && loadingMessage.parentNode) {
                loadingMessage.parentNode.removeChild(loadingMessage);
            }
            
            // 统一响应格式：检查 data.code 或 data.message 判断请求是否成功
            if (data.code === 200 || data.message === 'success') {
                // data.data 是 ChatResponse 对象
                const chatResponse = data.data;
                
                if (chatResponse && chatResponse.success) {
                    // 成功：添加实际响应消息（即使 answer 为空也显示）
                    const answer = chatResponse.answer || '（无回复内容）';
                    this.addMessage('assistant', answer);
                } else if (chatResponse && chatResponse.errorMessage) {
                    // 业务错误
                    throw new Error(chatResponse.errorMessage);
                } else {
                    // 兜底：尝试显示任何可用内容
                    const fallbackAnswer = chatResponse?.answer || chatResponse?.errorMessage || '服务返回了空内容';
                    this.addMessage('assistant', fallbackAnswer);
                }
            } else {
                // HTTP 成功但业务失败
                throw new Error(data.message || '请求失败');
            }
        } catch (error) {
            // 出错时也要移除等待提示消息
            loadingState.stop();
            if (loadingMessage && loadingMessage.parentNode) {
                loadingMessage.parentNode.removeChild(loadingMessage);
            }
            throw error;
        }
    }

    // 发送流式消息
    async sendStreamMessage(message) {
        try {
            const response = await this.apiRequest('/chat_stream', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    ...this.buildChatRequestBody(message)
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP错误: ${response.status}`);
            }
            
            // 创建助手消息元素
            const assistantMessageElement = this.addMessage('assistant', '', true);
            let fullResponse = '';

            // 处理流式响应
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let currentEvent = '';

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    
                    if (done) {
                        // 流结束，使用统一的处理方法
                        this.handleStreamComplete(assistantMessageElement, fullResponse);
                        break;
                    }

                    // 解码数据并添加到缓冲区
                    buffer += decoder.decode(value, { stream: true });
                    
                    // 按行分割处理
                    const lines = buffer.split('\n');
                    // 保留最后一行（可能不完整）
                    buffer = lines.pop() || '';
                    
                    for (const line of lines) {
                        if (line.trim() === '') continue;
                        
                        console.log('[SSE调试] 收到行:', line);
                        
                        // 解析SSE格式
                        if (line.startsWith('id:')) {
                            console.log('[SSE调试] 解析到ID');
                            continue;
                        } else if (line.startsWith('event:')) {
                            // 兼容 "event:message" 和 "event: message" 两种格式
                            currentEvent = line.substring(6).trim();
                            console.log('[SSE调试] 解析到事件类型:', currentEvent);
                            // 注意：后端统一使用 "message" 事件名，真正的类型在 data 的 JSON 中
                            continue;
                        } else if (line.startsWith('data:')) {
                            // 兼容 "data:xxx" 和 "data: xxx" 两种格式
                            const rawData = line.substring(5).trim();
                            console.log('[SSE调试] 解析到数据, currentEvent:', currentEvent, ', rawData:', rawData);
                            
                            // 兼容旧格式 [DONE] 标记
                            if (rawData === '[DONE]') {
                                // 流结束标记，将内容转换为Markdown渲染
                                this.handleStreamComplete(assistantMessageElement, fullResponse);
                                return;
                            }
                            
                            // 处理 SSE 数据
                            try {
                                // 尝试解析为 SseMessage 格式的 JSON
                                const sseMessage = JSON.parse(rawData);
                                console.log('[SSE调试] 解析JSON成功:', sseMessage);
                                
                                if (sseMessage && typeof sseMessage.type === 'string') {
                                    if (sseMessage.type === 'content') {
                                        const content = sseMessage.data || '';
                                        fullResponse += content;
                                        console.log('[SSE调试] 添加内容:', content);
                                        
                                        // 实时渲染 Markdown
                                        if (assistantMessageElement) {
                                            const messageContent = assistantMessageElement.querySelector('.message-content');
                                            messageContent.innerHTML = this.renderMarkdown(fullResponse);
                                            // 高亮代码块
                                            this.highlightCodeBlocks(messageContent);
                                            this.scrollToBottom();
                                        }
                                    } else if (sseMessage.type === 'done') {
                                        console.log('[SSE调试] 收到done标记，流结束');
                                        this.handleStreamComplete(assistantMessageElement, fullResponse);
                                        return;
                                    } else if (sseMessage.type === 'error') {
                                        console.error('[SSE调试] 收到错误:', sseMessage.data);
                                        if (assistantMessageElement) {
                                            const messageContent = assistantMessageElement.querySelector('.message-content');
                                            messageContent.innerHTML = this.renderMarkdown('错误: ' + (sseMessage.data || '未知错误'));
                                        }
                                        return;
                                    }
                                } else {
                                    // 不是标准 SseMessage 格式，尝试兼容处理
                                    console.log('[SSE调试] 非标准格式，尝试兼容处理');
                                    fullResponse += rawData;
                                    if (assistantMessageElement) {
                                        const messageContent = assistantMessageElement.querySelector('.message-content');
                                        messageContent.innerHTML = this.renderMarkdown(fullResponse);
                                        this.highlightCodeBlocks(messageContent);
                                        this.scrollToBottom();
                                    }
                                }
                            } catch (e) {
                                // JSON 解析失败，尝试兼容旧格式
                                console.log('[SSE调试] JSON解析失败，使用兼容模式:', e.message);
                                if (rawData === '') {
                                    fullResponse += '\n';
                                } else {
                                    fullResponse += rawData;
                                }
                                
                                if (assistantMessageElement) {
                                    const messageContent = assistantMessageElement.querySelector('.message-content');
                                    messageContent.innerHTML = this.renderMarkdown(fullResponse);
                                    this.highlightCodeBlocks(messageContent);
                                    this.scrollToBottom();
                                }
                            }
                        }
                    }
                }
            } finally {
                reader.releaseLock();
            }
        } catch (error) {
            throw error;
        }
    }

    // 添加消息到聊天界面
    addMessage(type, content, isStreaming = false, saveToHistory = true) {
        // 检查是否是第一条消息，如果是则移除居中样式
        const isFirstMessage = this.chatMessages && this.chatMessages.querySelectorAll('.message').length === 0;
        
        // 保存消息到当前对话历史（如果不是流式消息且需要保存）
        if (!isStreaming && saveToHistory && content) {
            this.currentChatHistory.push({
                type: type,
                content: content,
                timestamp: new Date().toISOString()
            });
        }
        
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${type}${isStreaming ? ' streaming' : ''}`;

        // 如果是assistant消息，添加头像图标
        if (type === 'assistant') {
            const messageAvatar = document.createElement('div');
            messageAvatar.className = 'message-avatar';
            messageAvatar.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="white"/>
                </svg>
            `;
            messageDiv.appendChild(messageAvatar);
        }

        // 创建消息内容包装器
        const messageContentWrapper = document.createElement('div');
        messageContentWrapper.className = 'message-content-wrapper';

        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        
        // 如果是assistant消息且不是流式消息，使用Markdown渲染
        if (type === 'assistant' && !isStreaming) {
            messageContent.innerHTML = this.renderMarkdown(content);
            // 高亮代码块
            this.highlightCodeBlocks(messageContent);
        } else {
            // 用户消息或流式消息使用纯文本
            messageContent.textContent = content;
        }

        messageContentWrapper.appendChild(messageContent);
        messageDiv.appendChild(messageContentWrapper);

        if (this.chatMessages) {
            this.chatMessages.appendChild(messageDiv);
            
            // 如果是第一条消息，移除居中样式并添加动画
            if (isFirstMessage && this.chatContainer) {
                this.chatContainer.classList.remove('centered');
                // 添加动画类
                this.chatContainer.style.transition = 'all 0.5s ease';
            }
            
            this.scrollToBottom();
        }

        return messageDiv;
    }

    // 添加带加载动画的消息
    addLoadingMessage(content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant';

        // 添加头像图标
        const messageAvatar = document.createElement('div');
        messageAvatar.className = 'message-avatar';
        messageAvatar.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="white"/>
            </svg>
        `;
        messageDiv.appendChild(messageAvatar);

        // 创建消息内容包装器
        const messageContentWrapper = document.createElement('div');
        messageContentWrapper.className = 'message-content-wrapper';

        const messageContent = document.createElement('div');
        messageContent.className = 'message-content loading-message-content';
        
        // 创建文本和动画容器
        const textSpan = document.createElement('span');
        textSpan.textContent = content;
        
        // 创建旋转动画图标
        const loadingIcon = document.createElement('span');
        loadingIcon.className = 'loading-spinner-icon';
        loadingIcon.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z" fill="currentColor" opacity="0.2"/>
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10c1.54 0 3-.36 4.28-1l-1.5-2.6C13.64 19.62 12.84 20 12 20c-4.41 0-8-3.59-8-8s3.59-8 8-8c.84 0 1.64.38 2.18 1l1.5-2.6C13 2.36 12.54 2 12 2z" fill="currentColor"/>
            </svg>
        `;
        
        messageContent.appendChild(textSpan);
        messageContent.appendChild(loadingIcon);
        messageContentWrapper.appendChild(messageContent);
        messageDiv.appendChild(messageContentWrapper);

        if (this.chatMessages) {
            this.chatMessages.appendChild(messageDiv);
            
            // 如果是第一条消息，移除居中样式
            const isFirstMessage = this.chatMessages.querySelectorAll('.message').length === 1;
            if (isFirstMessage && this.chatContainer) {
                this.chatContainer.classList.remove('centered');
                this.chatContainer.style.transition = 'all 0.5s ease';
            }
            
            this.scrollToBottom();
        }

        return messageDiv;
    }

    startLoadingState(type, loadingElement) {
        if (!this.loadingStateManager || !loadingElement) {
            return { stop: () => {} };
        }
        return this.loadingStateManager.attach(type, loadingElement);
    }
    
    // 检查并设置居中样式
    checkAndSetCentered() {
        if (this.chatMessages && this.chatContainer) {
            const hasMessages = this.chatMessages.querySelectorAll('.message').length > 0;
            if (!hasMessages) {
                this.chatContainer.classList.add('centered');
            } else {
                this.chatContainer.classList.remove('centered');
            }
        }
    }

    // 滚动到底部
    scrollToBottom() {
        if (this.chatMessages) {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }
    }

    // 处理流式传输完成
    handleStreamComplete(assistantMessageElement, fullResponse) {
        if (assistantMessageElement) {
            assistantMessageElement.classList.remove('streaming');
            const messageContent = assistantMessageElement.querySelector('.message-content');
            if (messageContent) {
                messageContent.innerHTML = this.renderMarkdown(fullResponse);
                // 高亮代码块
                this.highlightCodeBlocks(messageContent);
            }
        }
        // 保存流式消息到历史记录
        if (fullResponse) {
            this.currentChatHistory.push({
                type: 'assistant',
                content: fullResponse,
                timestamp: new Date().toISOString()
            });
            // 如果当前对话是从历史记录加载的，更新历史记录
            if (this.isCurrentChatFromHistory) {
                this.updateCurrentChatHistory();
                this.renderChatHistory();
            }
        }
    }

    // 显示通知
    showNotification(message, type = 'info', fallbackMessage = '') {
        const normalized = type === 'error' && this.errorHandler
            ? this.errorHandler.normalize(message, fallbackMessage)
            : null;
        const displayMessage = normalized ? normalized.message : String(message || fallbackMessage || '');
        // 创建通知元素
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = displayMessage;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            border-radius: 8px;
            color: white;
            font-weight: 500;
            z-index: 10000;
            animation: slideIn 0.3s ease;
            max-width: 300px;
        `;

        // 根据类型设置颜色（Google Material Design配色）
        const colors = {
            info: '#1a73e8',
            success: '#34a853',
            warning: '#fbbc04',
            error: '#ea4335'
        };
        notification.style.backgroundColor = colors[type] || colors.info;

        // 添加到页面
        document.body.appendChild(notification);

        // 3秒后自动移除
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 300);
        }, 3000);
    }

    // 处理文件选择
    handleFileSelect(event) {
        const file = event.target.files[0];
        if (file) {
            // 验证文件格式
            if (!this.validateFileType(file)) {
                this.showNotification('只支持上传 TXT 或 Markdown (.md) 格式的文件', 'error');
                this.fileInput.value = '';
                return;
            }
            this.uploadFile(file);
        }
    }

    // 验证文件类型
    validateFileType(file) {
        const fileName = file.name.toLowerCase();
        const allowedExtensions = ['.txt', '.md', '.markdown'];
        return allowedExtensions.some(ext => fileName.endsWith(ext));
    }

    // 上传文件到知识库
    async uploadFile(file) {
        // 再次验证文件类型（双重保险）
        if (!this.validateFileType(file)) {
            this.showNotification('只支持上传 TXT 或 Markdown (.md) 格式的文件', 'error');
            return;
        }

        // 验证文件大小（限制为50MB）
        const maxSize = 50 * 1024 * 1024;
        if (file.size > maxSize) {
            this.showNotification('文件大小不能超过50MB', 'error');
            return;
        }

        // 锁定前端并显示上传遮罩层
        this.isStreaming = true;
        this.updateUI();
        this.showUploadOverlay(true, file.name);

        try {
            // 创建 FormData
            const formData = new FormData();
            formData.append('file', file);
            const kbId = this.getDefaultUploadKbId();
            formData.append('kb_id', kbId);

            // 发送上传请求
            const response = await this.apiRequest('/upload', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                throw new Error(`HTTP错误: ${response.status}`);
            }

            const data = await response.json();

            if ((data.code === 200 || data.message === 'success') && data.data) {
                // 在聊天界面显示上传成功消息
                const successMessage = `${file.name} 上传到知识库 ${kbId} 成功，可在文件管理查看处理状态`;
                this.addMessage('assistant', successMessage, false, true);
                if (this.profileModalMode === 'documents') {
                    await this.loadDocuments({ page: 1, silent: true });
                }
            } else {
                throw new Error(data.message || '上传失败');
            }
        } catch (error) {
            console.error('文件上传失败:', error);
            this.showNotification(error, 'error', '文件上传失败');
        } finally {
            // 清空文件输入
            if (this.fileInput) {
                this.fileInput.value = '';
            }
            // 解锁前端
            this.isStreaming = false;
            this.showUploadOverlay(false);
            this.updateUI();
        }
    }

    getDefaultUploadKbId() {
        const visibleKbIds = this.currentProfile?.visible_kb_ids || [];
        return visibleKbIds.length > 0 ? visibleKbIds[0] : 'default';
    }

    // 格式化文件大小
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }

    // 发送智能运维请求（SSE 流式模式）
    async sendAIOpsRequest(loadingMessageElement) {
        try {
            const response = await this.apiRequest('/aiops', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId
                })
            });

            if (!response.ok) {
                throw new Error(`HTTP错误: ${response.status}`);
            }

            let fullResponse = '';

            // 处理 SSE 流式响应
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let currentEvent = 'message'; // 默认事件类型为 message

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    
                    if (done) {
                        // 流结束，更新最终内容
                        if (fullResponse) {
                            console.log('AI Ops 流结束，更新最终内容，长度:', fullResponse.length);
                            this.updateAIOpsMessage(loadingMessageElement, fullResponse, []);
                        }
                        break;
                    }

                    // 解码数据并添加到缓冲区
                    buffer += decoder.decode(value, { stream: true });
                    
                    // 按行分割处理
                    const lines = buffer.split('\n');
                    // 保留最后一行（可能不完整）
                    buffer = lines.pop() || '';
                    
                    for (const line of lines) {
                        if (line.trim() === '') continue;
                        
                        console.log('[AI Ops SSE] 收到行:', line);
                        
                        // 解析 SSE 格式
                        if (line.startsWith('id:')) {
                            continue;
                        } else if (line.startsWith('event:')) {
                            currentEvent = line.substring(6).trim();
                            console.log('[AI Ops SSE] 事件类型:', currentEvent);
                            continue;
                        } else if (line.startsWith('data:')) {
                            const rawData = line.substring(5).trim();
                            console.log('[AI Ops SSE] 数据:', rawData, ', currentEvent:', currentEvent);
                            
                            // 解析可能包含多个JSON对象的数据
                            const processJsonMessages = (data) => {
                                const jsonPattern = /\{"type"\s*:\s*"[^"]+"\s*,\s*"data"\s*:\s*(?:"[^"]*"|null)\}/g;
                                const matches = data.match(jsonPattern);
                                
                                if (matches && matches.length > 0) {
                                    console.log('[AI Ops SSE] 匹配到', matches.length, '个JSON对象');
                                    for (const jsonStr of matches) {
                                        try {
                                            const sseMessage = JSON.parse(jsonStr);
                                            if (sseMessage.type === 'content') {
                                                fullResponse += sseMessage.data || '';
                                            } else if (sseMessage.type === 'plan') {
                                                // 处理计划创建事件
                                                const planText = `\n\n## 📋 执行计划\n${sseMessage.message}\n\n`;
                                                fullResponse += planText;
                                            } else if (sseMessage.type === 'step_complete') {
                                                // 处理步骤完成事件
                                                const stepText = `\n✅ ${sseMessage.message}\n`;
                                                fullResponse += stepText;
                                            } else if (sseMessage.type === 'status') {
                                                // 处理状态更新事件
                                                const statusText = `\n⏳ ${sseMessage.message}\n`;
                                                fullResponse += statusText;
                                            } else if (sseMessage.type === 'report') {
                                                // 处理最终报告事件 - 流式输出
                                                console.log('AI Ops 最终报告生成');
                                                const reportText = `\n\n## 🎯 诊断报告\n\n${sseMessage.report || ''}\n`;
                                                fullResponse += reportText;
                                            } else if (sseMessage.type === 'complete') {
                                                // 处理完成事件
                                                console.log('AI Ops 诊断完成');
                                                if (sseMessage.response) {
                                                    fullResponse += `\n\n${sseMessage.response}`;
                                                }
                                                this.updateAIOpsMessage(loadingMessageElement, fullResponse, []);
                                                return true;
                                            } else if (sseMessage.type === 'done') {
                                                console.log('AI Ops 流完成，最终内容长度:', fullResponse.length);
                                                this.updateAIOpsMessage(loadingMessageElement, fullResponse, []);
                                                return true;
                                            } else if (sseMessage.type === 'error') {
                                                throw new Error(sseMessage.data || sseMessage.message || '智能运维分析失败');
                                            }
                                        } catch (e) {
                                            if (e.message.includes('智能运维')) throw e;
                                            console.log('[AI Ops SSE] 单个JSON解析失败:', jsonStr);
                                        }
                                    }
                                    if (loadingMessageElement) {
                                        this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                    }
                                    return false;
                                }
                                return null;
                            };
                            
                            const result = processJsonMessages(rawData);
                            if (result === true) {
                                return; // 流结束
                            } else if (result === null) {
                                // 没有匹配到多个JSON，尝试单个JSON解析
                                try {
                                    const sseMessage = JSON.parse(rawData);
                                    if (sseMessage && sseMessage.type) {
                                        if (sseMessage.type === 'content') {
                                            fullResponse += sseMessage.data || '';
                                            if (loadingMessageElement) {
                                                this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                            }
                                        } else if (sseMessage.type === 'plan') {
                                            // 处理计划创建事件
                                            const planText = `\n\n## 📋 执行计划\n${sseMessage.message}\n\n`;
                                            fullResponse += planText;
                                            if (loadingMessageElement) {
                                                this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                            }
                                        } else if (sseMessage.type === 'step_complete') {
                                            // 处理步骤完成事件
                                            const stepText = `\n✅ ${sseMessage.message}\n`;
                                            fullResponse += stepText;
                                            if (loadingMessageElement) {
                                                this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                            }
                                        } else if (sseMessage.type === 'status') {
                                            // 处理状态更新事件
                                            const statusText = `\n⏳ ${sseMessage.message}\n`;
                                            fullResponse += statusText;
                                            if (loadingMessageElement) {
                                                this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                            }
                                        } else if (sseMessage.type === 'report') {
                                            // 处理最终报告事件 - 这是关键！
                                            console.log('AI Ops 最终报告生成，流式输出中...');
                                            const reportText = `\n\n## 🎯 诊断报告\n\n${sseMessage.report || ''}\n`;
                                            fullResponse += reportText;
                                            if (loadingMessageElement) {
                                                this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                            }
                                        } else if (sseMessage.type === 'complete') {
                                            // 处理完成事件
                                            console.log('AI Ops 诊断完成，最终内容长度:', fullResponse.length);
                                            if (sseMessage.response) {
                                                fullResponse += `\n\n${sseMessage.response}`;
                                            }
                                            // 使用最终的完整内容更新消息
                                            this.updateAIOpsMessage(loadingMessageElement, fullResponse, []);
                                            return;
                                        } else if (sseMessage.type === 'done') {
                                            console.log('AI Ops 流完成，最终内容长度:', fullResponse.length);
                                            this.updateAIOpsMessage(loadingMessageElement, fullResponse, []);
                                            return;
                                        } else if (sseMessage.type === 'error') {
                                            throw new Error(sseMessage.data || sseMessage.message || '智能运维分析失败');
                                        }
                                    } else {
                                        fullResponse += rawData;
                                        if (loadingMessageElement) {
                                            this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                        }
                                    }
                                } catch (e) {
                                    if (e.message.includes('智能运维')) throw e;
                                    // 非 JSON 格式，直接追加原始数据
                                    fullResponse += rawData;
                                    if (loadingMessageElement) {
                                        this.updateAIOpsStreamContent(loadingMessageElement, fullResponse);
                                    }
                                }
                            }
                        }
                    }
                }
            } finally {
                reader.releaseLock();
            }
        } catch (error) {
            throw error;
        }
    }

    // 更新智能运维流式内容（实时显示）
    updateAIOpsStreamContent(messageElement, content) {
        if (!messageElement) return;
        
        // 添加 aiops-message 类
        messageElement.classList.add('aiops-message');
        
        const messageContentWrapper = messageElement.querySelector('.message-content-wrapper');
        if (messageContentWrapper) {
            let messageContent = messageContentWrapper.querySelector('.message-content');
            if (!messageContent) {
                messageContent = document.createElement('div');
                messageContent.className = 'message-content';
                messageContentWrapper.appendChild(messageContent);
            }
            // 流式显示时使用纯文本
            messageContent.textContent = content;
            this.scrollToBottom();
        }
    }

    // 更新智能运维消息（带折叠详情）
    updateAIOpsMessage(messageElement, response, details) {
        console.log('updateAIOpsMessage 被调用');
        console.log('messageElement:', messageElement);
        console.log('response:', response);
        console.log('response length:', response ? response.length : 0);
        console.log('details:', details);
        
        if (!messageElement) {
            // 如果没有传入消息元素，则创建新消息
            console.log('messageElement 为空，创建新消息');
            return this.addAIOpsMessage(response, details);
        }

        // 添加aiops-message类
        messageElement.classList.add('aiops-message');

        // 获取消息内容包装器
        const messageContentWrapper = messageElement.querySelector('.message-content-wrapper');
        if (!messageContentWrapper) {
            console.error('未找到 message-content-wrapper');
            return;
        }

        // 清空现有内容（保留消息内容容器）
        const messageContent = messageContentWrapper.querySelector('.message-content');
        if (!messageContent) {
            console.error('未找到 message-content');
            return;
        }

        // 移除加载动画相关的类和内容
        messageContent.classList.remove('loading-message-content');
        messageContent.textContent = '';
        
        // 移除加载图标（如果存在）
        const loadingIcon = messageContent.querySelector('.loading-spinner-icon');
        if (loadingIcon) {
            loadingIcon.remove();
        }

        // 详情部分（可折叠）- 先显示
        if (details && details.length > 0) {
            // 检查是否已存在详情容器
            let detailsContainer = messageElement.querySelector('.aiops-details');
            if (!detailsContainer) {
                detailsContainer = document.createElement('div');
                detailsContainer.className = 'aiops-details';
                messageContentWrapper.insertBefore(detailsContainer, messageContent);
            } else {
                // 清空现有详情
                detailsContainer.innerHTML = '';
            }

            const detailsToggle = document.createElement('div');
            detailsToggle.className = 'details-toggle';
            detailsToggle.innerHTML = `
                <svg class="toggle-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M9 18L15 12L9 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>查看详细步骤 (${details.length}条)</span>
            `;

            const detailsContent = document.createElement('div');
            detailsContent.className = 'details-content';
            
            details.forEach((detail, index) => {
                const detailItem = document.createElement('div');
                detailItem.className = 'detail-item';
                detailItem.innerHTML = `<strong>步骤 ${index + 1}:</strong> ${this.escapeHtml(detail)}`;
                detailsContent.appendChild(detailItem);
            });

            // 点击切换折叠状态
            detailsToggle.addEventListener('click', () => {
                detailsContent.classList.toggle('expanded');
                detailsToggle.classList.toggle('expanded');
            });

            detailsContainer.appendChild(detailsToggle);
            detailsContainer.appendChild(detailsContent);
        }

        // 更新主要响应内容（使用Markdown渲染）
        console.log('开始渲染 Markdown');
        const renderedHtml = this.renderMarkdown(response);
        console.log('Markdown 渲染完成，HTML 长度:', renderedHtml ? renderedHtml.length : 0);
        messageContent.innerHTML = renderedHtml;
        console.log('innerHTML 已设置');
        // 高亮代码块
        this.highlightCodeBlocks(messageContent);
        console.log('代码块高亮完成');
        
        // 保存到历史记录
        this.currentChatHistory.push({
            type: 'assistant',
            content: response,
            timestamp: new Date().toISOString()
        });
        
        this.scrollToBottom();
        return messageElement;
    }

    // 添加智能运维消息（带折叠详情）- 保留用于兼容性
    addAIOpsMessage(response, details) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant aiops-message';

        // 添加头像图标
        const messageAvatar = document.createElement('div');
        messageAvatar.className = 'message-avatar';
        messageAvatar.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 2L15.09 8.26L22 9.27L17 14.14L18.18 21.02L12 17.77L5.82 21.02L7 14.14L2 9.27L8.91 8.26L12 2Z" fill="white"/>
            </svg>
        `;
        messageDiv.appendChild(messageAvatar);

        // 创建消息内容包装器
        const messageContentWrapper = document.createElement('div');
        messageContentWrapper.className = 'message-content-wrapper';

        // 详情部分（可折叠）- 先显示
        if (details && details.length > 0) {
            const detailsContainer = document.createElement('div');
            detailsContainer.className = 'aiops-details';

            const detailsToggle = document.createElement('div');
            detailsToggle.className = 'details-toggle';
            detailsToggle.innerHTML = `
                <svg class="toggle-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M9 18L15 12L9 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>查看详细步骤 (${details.length}条)</span>
            `;

            const detailsContent = document.createElement('div');
            detailsContent.className = 'details-content';
            
            details.forEach((detail, index) => {
                const detailItem = document.createElement('div');
                detailItem.className = 'detail-item';
                detailItem.innerHTML = `<strong>步骤 ${index + 1}:</strong> ${this.escapeHtml(detail)}`;
                detailsContent.appendChild(detailItem);
            });

            // 点击切换折叠状态
            detailsToggle.addEventListener('click', () => {
                detailsContent.classList.toggle('expanded');
                detailsToggle.classList.toggle('expanded');
            });

            detailsContainer.appendChild(detailsToggle);
            detailsContainer.appendChild(detailsContent);
            messageContentWrapper.appendChild(detailsContainer);
        }

        // 主要响应内容 - 后显示（使用Markdown渲染）
        const messageContent = document.createElement('div');
        messageContent.className = 'message-content';
        messageContent.innerHTML = this.renderMarkdown(response);
        // 高亮代码块
        this.highlightCodeBlocks(messageContent);
        messageContentWrapper.appendChild(messageContent);
        messageDiv.appendChild(messageContentWrapper);
        
        if (this.chatMessages) {
            this.chatMessages.appendChild(messageDiv);
            this.scrollToBottom();
        }

        return messageDiv;
    }

    // HTML转义
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // 触发智能运维（点击智能运维按钮时直接调用）
    async triggerAIOps() {
        if (this.isStreaming) {
            this.showNotification('请等待当前操作完成', 'warning');
            return;
        }

        // 新建对话
        this.newChat();
        
        // 添加"分析中..."的消息（带旋转动画）
        const loadingMessage = this.addLoadingMessage('分析中...');
        const loadingState = this.startLoadingState('aiops', loadingMessage);
        this.currentAIOpsMessage = loadingMessage; // 保存消息引用用于后续更新
        
        // 设置发送状态
        this.isStreaming = true;
        this.updateUI();

        try {
            await this.sendAIOpsRequest(loadingMessage);
        } catch (error) {
            console.error('智能运维分析失败:', error);
            // 更新消息为错误信息
            if (loadingMessage) {
                const messageContent = loadingMessage.querySelector('.message-content');
                if (messageContent) {
                    messageContent.innerHTML = this.renderErrorMessage(error, '智能运维分析失败');
                }
            }
        } finally {
            loadingState.stop();
            this.isStreaming = false;
            this.currentAIOpsMessage = null;
            this.updateUI();
        }
    }

    // 显示/隐藏加载遮罩层
    showLoadingOverlay(show) {
        if (this.loadingOverlay) {
            if (show) {
                this.loadingOverlay.style.display = 'flex';
                // 更新文字为智能运维
                const loadingText = this.loadingOverlay.querySelector('.loading-text');
                const loadingSubtext = this.loadingOverlay.querySelector('.loading-subtext');
                if (loadingText) loadingText.textContent = '智能运维分析中，请稍候...';
                if (loadingSubtext) loadingSubtext.textContent = '后端正在处理，请耐心等待';
                this.startOverlayLoadingState('aiops', '后端正在处理，请耐心等待');
                // 防止页面滚动
                document.body.style.overflow = 'hidden';
            } else {
                this.stopOverlayLoadingState();
                this.loadingOverlay.style.display = 'none';
                // 恢复页面滚动
                document.body.style.overflow = '';
            }
        }
    }

    // 显示/隐藏上传遮罩层
    showUploadOverlay(show, fileName = '') {
        if (this.loadingOverlay) {
            if (show) {
                this.loadingOverlay.style.display = 'flex';
                // 更新文字为上传中
                const loadingText = this.loadingOverlay.querySelector('.loading-text');
                const loadingSubtext = this.loadingOverlay.querySelector('.loading-subtext');
                if (loadingText) loadingText.textContent = '正在上传文件...';
                if (loadingSubtext) loadingSubtext.textContent = fileName ? `上传: ${fileName}` : '请稍候';
                this.startOverlayLoadingState('file_upload', fileName ? `上传: ${fileName}` : '请稍候');
                // 防止页面滚动
                document.body.style.overflow = 'hidden';
            } else {
                this.stopOverlayLoadingState();
                this.loadingOverlay.style.display = 'none';
                // 恢复页面滚动
                document.body.style.overflow = '';
            }
        }
    }

    startOverlayLoadingState(type, subtext) {
        this.stopOverlayLoadingState();
        if (!this.loadingStateManager || !this.loadingOverlay) {
            return;
        }
        this.activeOverlayLoading = this.loadingStateManager.bindOverlay(type, this.loadingOverlay, { subtext });
    }

    stopOverlayLoadingState() {
        if (this.activeOverlayLoading) {
            this.activeOverlayLoading.stop();
            this.activeOverlayLoading = null;
        }
    }
}

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    new SuperBizAgentApp();
});
