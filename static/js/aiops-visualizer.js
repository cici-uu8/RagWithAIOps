(function () {
    "use strict";

    class AIOpsVisualizer {
        constructor(containerOrId) {
            this.container = this.resolveContainer(containerOrId);
            this.steps = [];
            this.currentStep = 0;
            this.startedAt = null;
            this.finishedAt = null;
            this.closed = false;
        }

        init(plan = {}) {
            const planSteps = this.extractPlanSteps(plan);
            this.startedAt = Date.now();
            this.finishedAt = null;
            this.currentStep = 0;
            this.closed = false;
            this.steps = planSteps.map((step, index) => ({
                id: step.id || index + 1,
                title: step.title || step.description || step.name || `诊断步骤 ${index + 1}`,
                status: "pending",
                startTime: null,
                endTime: null,
                tools: [],
                result: "",
                error: "",
            }));
            this.render();
            return this;
        }

        handleEvent(event = {}) {
            const type = event.type || event.event || "";
            if (type === "plan") {
                this.init(event.data || event.plan || event);
            } else if (type === "step_start" || type === "status") {
                if (this.closed) return this;
                this.updateStep(this.resolveStepId(event), {
                    status: "running",
                    startTime: Date.now(),
                });
            } else if (type === "tool_call") {
                this.addToolCall(
                    this.resolveStepId(event),
                    event.tool_name || event.toolName || event.name || "tool",
                    event.parameters || event.args || event.data || {}
                );
            } else if (type === "step_complete") {
                this.updateStep(this.resolveStepId(event), {
                    status: "completed",
                    endTime: Date.now(),
                    result: event.result || event.message || "",
                });
            } else if (type === "step_error" || type === "error") {
                this.updateStep(this.resolveStepId(event), {
                    status: "failed",
                    endTime: Date.now(),
                    error: event.error || event.message || event.data || "步骤失败",
                });
            } else if (type === "report" || type === "complete" || type === "done") {
                this.finishedAt = Date.now();
                this.closed = true;
                this.markRemainingCompleted(event.message || event.response || "");
            }
            return this;
        }

        updateStep(stepId, update = {}) {
            const step = this.findStep(stepId);
            if (!step) return this;

            Object.assign(step, update);
            if (update.status === "running" && !step.startTime) {
                step.startTime = Date.now();
            }
            if ((update.status === "completed" || update.status === "failed") && !step.endTime) {
                step.endTime = Date.now();
            }
            this.currentStep = this.completedStepCount();
            this.render();
            return this;
        }

        addToolCall(stepId, toolName, parameters = {}) {
            const step = this.findStep(stepId);
            if (!step) return this;

            step.tools.push({
                name: toolName,
                parameters,
                timestamp: Date.now(),
            });
            if (step.status === "pending") {
                step.status = "running";
                step.startTime = step.startTime || Date.now();
            }
            this.render();
            return this;
        }

        render() {
            if (!this.container) return false;
            const total = this.steps.length || 1;
            const progressPercent = Math.round((this.completedStepCount() / total) * 100);

            this.container.innerHTML = `
                <section class="aiops-flow-container" aria-label="AIOps诊断流程">
                    <div class="aiops-flow-header">
                        <div>
                            <h3>AIOps 诊断进行中</h3>
                            <p>${this.escapeHtml(this.summaryText())}</p>
                        </div>
                        <span class="aiops-flow-progress-text">${progressPercent}%</span>
                    </div>
                    <div class="aiops-flow-progress" aria-hidden="true">
                        <div class="aiops-flow-progress-bar" style="width: ${progressPercent}%"></div>
                    </div>
                    <div class="aiops-flow-steps">
                        ${this.steps.map((step) => this.renderStep(step)).join("")}
                    </div>
                </section>
            `;
            return true;
        }

        renderStep(step) {
            const statusLabels = {
                pending: "等待",
                running: "进行中",
                completed: "完成",
                failed: "失败",
            };
            const details = step.status !== "pending"
                ? `<div class="aiops-step-details">
                    ${step.tools.map((tool) => this.renderTool(tool)).join("")}
                    ${step.result ? `<div class="aiops-step-result">${this.escapeHtml(step.result)}</div>` : ""}
                    ${step.error ? `<div class="aiops-step-error">${this.escapeHtml(step.error)}</div>` : ""}
                    ${step.endTime ? `<div class="aiops-step-time">耗时: ${this.formatDuration(step)}</div>` : ""}
                </div>`
                : "";

            return `
                <article class="aiops-flow-step aiops-flow-step-${this.escapeHtml(step.status)}" data-step-id="${this.escapeHtml(step.id)}">
                    <div class="aiops-step-header">
                        <span class="aiops-step-number">${this.escapeHtml(step.id)}</span>
                        <span class="aiops-step-title">${this.escapeHtml(step.title)}</span>
                        <span class="aiops-step-status">${statusLabels[step.status] || step.status}</span>
                    </div>
                    ${details}
                </article>
            `;
        }

        renderTool(tool) {
            return `
                <details class="aiops-tool-call">
                    <summary>${this.escapeHtml(tool.name)}</summary>
                    <pre>${this.escapeHtml(JSON.stringify(tool.parameters || {}, null, 2))}</pre>
                </details>
            `;
        }

        extractPlanSteps(plan) {
            if (Array.isArray(plan)) return plan;
            if (Array.isArray(plan.steps)) return plan.steps;
            if (Array.isArray(plan.plan)) {
                return plan.plan.map((item) => (
                    typeof item === "string" ? { title: item } : item
                ));
            }
            if (typeof plan.message === "string" && plan.message.trim()) {
                return plan.message
                    .split(/\r?\n/)
                    .map((line) => line.replace(/^\s*\d+[.)、-]?\s*/, "").trim())
                    .filter(Boolean)
                    .map((title) => ({ title }));
            }
            return [
                { title: "制定诊断计划" },
                { title: "查询监控数据" },
                { title: "分析异常信号" },
                { title: "生成诊断报告" },
            ];
        }

        resolveStepId(event) {
            return event.step_id || event.stepId || event.id || this.nextActiveStepId();
        }

        nextActiveStepId() {
            const running = this.steps.find((step) => step.status === "running");
            if (running) return running.id;
            const pending = this.steps.find((step) => step.status === "pending");
            if (pending) return pending.id;
            return this.steps[this.steps.length - 1]?.id;
        }

        findStep(stepId) {
            if (!this.steps.length) {
                this.init();
            }
            return this.steps.find((step) => String(step.id) === String(stepId)) || this.steps[0];
        }

        markRemainingCompleted(result = "") {
            this.steps.forEach((step) => {
                if (step.status === "running" || step.status === "pending") {
                    step.status = "completed";
                    step.endTime = step.endTime || Date.now();
                    step.result = step.result || result;
                }
            });
            this.currentStep = this.completedStepCount();
            this.render();
        }

        completedStepCount() {
            return this.steps.filter((step) => step.status === "completed").length;
        }

        summaryText() {
            if (!this.steps.length) return "等待诊断计划";
            const failed = this.steps.some((step) => step.status === "failed");
            if (failed) return "诊断流程存在失败步骤";
            if (this.completedStepCount() === this.steps.length) return "诊断流程已完成";
            return `${this.completedStepCount()} / ${this.steps.length} 个步骤完成`;
        }

        formatDuration(step) {
            if (!step.startTime || !step.endTime) return "";
            return `${((step.endTime - step.startTime) / 1000).toFixed(1)}s`;
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

    window.AIOpsVisualizer = AIOpsVisualizer;
}());
