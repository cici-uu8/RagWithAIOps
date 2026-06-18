(function () {
    "use strict";

    class PermissionViewer {
        constructor(containerOrId, options = {}) {
            this.container = this.resolveContainer(containerOrId);
            this.options = options;
            this.capabilities = {
                granted: [],
                requestable: [],
                forbidden: [],
            };
        }

        render(data = {}) {
            this.capabilities = this.classify(data);
            if (!this.container) {
                return false;
            }
            this.container.innerHTML = `
                <section class="permission-viewer" aria-label="权限状态">
                    <div class="permission-viewer-header">
                        <div>
                            <h4>我的可用能力</h4>
                            <p>按已授权、可申请、不可用分组展示当前账号能力。</p>
                        </div>
                    </div>
                    ${this.renderSection("granted", "已授权", this.capabilities.granted)}
                    ${this.renderSection("requestable", "可申请", this.capabilities.requestable)}
                    ${this.renderSection("forbidden", "不可用", this.capabilities.forbidden)}
                </section>
            `;
            this.bindActions();
            return true;
        }

        classify({ profile = {}, requestableResources = [] } = {}) {
            const classified = {
                granted: [],
                requestable: [],
                forbidden: [],
            };
            const seen = new Set();

            (profile.visible_kb_ids || []).forEach((kbId) => {
                this.addUnique(classified.granted, seen, {
                    id: `knowledge_base:${kbId}:read`,
                    resource_type: "knowledge_base",
                    resource_id: kbId,
                    action: "read",
                    display_name: `知识库 ${kbId}`,
                    status_text: "已授权，可立即查询",
                    scope: kbId,
                });
            });

            (profile.visible_tools || []).forEach((toolId) => {
                this.addUnique(classified.granted, seen, {
                    id: `tool:${toolId}:use`,
                    resource_type: "tool",
                    resource_id: toolId,
                    action: "use",
                    display_name: `工具 ${toolId}`,
                    status_text: "已授权，可立即使用",
                    scope: toolId,
                });
            });

            Object.entries(profile.feature_flags || {}).forEach(([key, enabled]) => {
                if (!enabled) return;
                this.addUnique(classified.granted, seen, {
                    id: `feature:${key}:enabled`,
                    resource_type: "feature",
                    resource_id: key,
                    action: "use",
                    display_name: this.featureLabel(key),
                    status_text: "已开启，可在当前账号使用",
                });
            });

            if (profile.database_demo?.enabled) {
                const tables = profile.database_demo.visible_tables || [];
                this.addUnique(classified.granted, seen, {
                    id: "feature:database_demo:enabled",
                    resource_type: "feature",
                    resource_id: "database_demo",
                    action: "use",
                    display_name: "数据库查询",
                    status_text: "已授权，只读查询可用",
                    scope: tables.length > 0 ? tables.join(", ") : profile.database_demo.database_id || "",
                });
            }

            requestableResources
                .filter((resource) => !resource.already_granted)
                .forEach((resource) => {
                    const action = this.firstRequestableAction(resource);
                    this.addUnique(classified.requestable, seen, {
                        id: `${resource.resource_type}:${resource.resource_id}:${action}`,
                        resource_type: resource.resource_type,
                        resource_id: resource.resource_id,
                        action,
                        display_name: this.resourceDisplayName(resource),
                        status_text: "未授权，需要管理员批准",
                        scope: this.resourceScope(resource),
                        reason: resource.description || resource.metadata?.description || "",
                    });
                });

            Object.entries(profile.unavailable_reasons || {}).forEach(([key, reason]) => {
                this.addUnique(classified.forbidden, seen, {
                    id: `forbidden:${key}`,
                    resource_type: "feature",
                    resource_id: key,
                    action: "use",
                    display_name: this.featureLabel(key),
                    status_text: "不可用，当前账号无权使用",
                    reason,
                });
            });

            this.addUnique(classified.forbidden, seen, {
                id: "forbidden:production_operation",
                resource_type: "operation",
                resource_id: "production_operation",
                action: "execute",
                display_name: "生产环境操作",
                status_text: "禁止直接使用，高风险操作",
                reason: "需要人工审批流程，不能由普通权限申请直接开放。",
            });

            return classified;
        }

        renderSection(tone, title, capabilities) {
            if (!capabilities.length) {
                return `
                    <div class="permission-state-section" data-section="${this.escapeHtml(tone)}">
                        <div class="permission-state-title">${this.escapeHtml(title)}</div>
                        <div class="permission-state-empty">暂无${this.escapeHtml(title)}能力</div>
                    </div>
                `;
            }
            return `
                <div class="permission-state-section" data-section="${this.escapeHtml(tone)}">
                    <div class="permission-state-title">${this.escapeHtml(title)}</div>
                    <div class="permission-state-grid">
                        ${capabilities.map((capability) => this.renderCapability(capability, tone)).join("")}
                    </div>
                </div>
            `;
        }

        renderCapability(capability, tone) {
            const toneAttribute = {
                granted: 'data-tone="granted"',
                requestable: 'data-tone="requestable"',
                forbidden: 'data-tone="forbidden"',
            }[tone] || 'data-tone="forbidden"';
            const actions = tone === "requestable"
                ? `<div class="permission-capability-actions">
                    <button type="button" class="secondary-action-btn permission-viewer-action" data-action="request" data-capability-id="${this.escapeHtml(capability.id)}">申请权限</button>
                </div>`
                : "";
            return `
                <article class="permission-capability-card" ${toneAttribute} data-capability-id="${this.escapeHtml(capability.id)}">
                    <div class="permission-capability-header">
                        <strong>${this.escapeHtml(capability.display_name)}</strong>
                        <span>${this.escapeHtml(capability.status_text)}</span>
                    </div>
                    ${capability.scope ? `<p>范围：${this.escapeHtml(capability.scope)}</p>` : ""}
                    ${capability.reason ? `<p>原因：${this.escapeHtml(capability.reason)}</p>` : ""}
                    ${actions}
                </article>
            `;
        }

        bindActions() {
            if (!this.container) return;
            this.container.querySelectorAll(".permission-viewer-action").forEach((button) => {
                button.addEventListener("click", (event) => {
                    const capability = this.findCapability(event.currentTarget.dataset.capabilityId);
                    if (!capability || event.currentTarget.dataset.action !== "request") {
                        return;
                    }
                    if (typeof this.options.prefillPermissionRequest === "function") {
                        this.options.prefillPermissionRequest(capability);
                    }
                });
            });
        }

        findCapability(id) {
            return Object.values(this.capabilities)
                .flat()
                .find((capability) => capability.id === id) || null;
        }

        addUnique(target, seen, capability) {
            if (!capability.id || seen.has(capability.id)) {
                return;
            }
            seen.add(capability.id);
            target.push(capability);
        }

        firstRequestableAction(resource) {
            const actionOption = (resource.action_options || []).find((option) => !option.already_granted);
            if (actionOption?.action) return actionOption.action;
            const supported = (resource.actions_supported || []).find(Boolean);
            return supported || "read";
        }

        resourceDisplayName(resource) {
            if (typeof this.options.resourceDisplayName === "function") {
                return this.options.resourceDisplayName(resource);
            }
            return resource?.metadata?.display_name || resource?.name || resource?.resource_id || "-";
        }

        resourceScope(resource) {
            const metadata = resource.metadata || {};
            return metadata.scope || metadata.database_id || metadata.kb_id || metadata.table_name || "";
        }

        featureLabel(key) {
            const labels = {
                admin: "管理后台",
                department_admin: "部门管理",
                rag_chat: "知识库问答",
                database_demo: "数据库查询",
                database_catalog: "数据库目录",
                memory_operator: "Memory Operator",
            };
            return labels[key] || key;
        }

        resolveContainer(containerOrId) {
            if (!containerOrId) return null;
            if (typeof containerOrId === "string") {
                return document.getElementById(containerOrId);
            }
            return containerOrId;
        }

        escapeHtml(value) {
            const div = document.createElement("div");
            div.textContent = String(value ?? "");
            return div.innerHTML;
        }
    }

    window.PermissionViewer = PermissionViewer;
}());
