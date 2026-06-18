(function () {
    "use strict";

    class ErrorHandler {
        constructor() {
            this.errorMap = {
                network: {
                    severity: "critical",
                    title: "无法连接后端服务",
                    message: "请确认启动窗口仍在运行，或刷新后重试。",
                    tone: "red",
                },
                auth: {
                    severity: "high",
                    title: "登录状态异常",
                    message: "请重新登录后继续操作。",
                    tone: "red",
                },
                permission: {
                    severity: "high",
                    title: "权限不足",
                    message: "请提交权限申请或联系管理员授权。",
                    tone: "amber",
                },
                backend: {
                    severity: "high",
                    title: "后端处理失败",
                    message: "请稍后重试；如有 trace_id，请用于排查。",
                    tone: "red",
                },
                validation: {
                    severity: "medium",
                    title: "输入需要调整",
                    message: "请检查输入内容后再试。",
                    tone: "amber",
                },
                unknown: {
                    severity: "medium",
                    title: "操作失败",
                    message: "请稍后重试。",
                    tone: "neutral",
                },
            };
        }

        classifyError(error) {
            const message = this.extractMessage(error);
            const status = error?.status || error?.payload?.status || 0;
            const category = error?.category || "";

            if (category === "network_error" || /无法连接|Failed to fetch|NetworkError/i.test(message)) {
                return "network";
            }
            if (category === "unauthenticated" || status === 401 || /登录已过期|Invalid credentials|未登录/.test(message)) {
                return "auth";
            }
            if (category === "forbidden" || status === 403 || /权限|授权|permission|forbidden/i.test(message)) {
                return "permission";
            }
            if (status >= 500 || /后端处理失败|trace_id|HTTP错误: 5/i.test(message)) {
                return "backend";
            }
            if (status >= 400 || /请输入|只支持|不能超过|校验|invalid/i.test(message)) {
                return "validation";
            }
            return "unknown";
        }

        normalize(error, fallbackMessage = "") {
            const type = this.classifyError(error);
            const config = this.errorMap[type] || this.errorMap.unknown;
            const message = this.extractMessage(error) || fallbackMessage || config.message;
            return {
                ...config,
                type,
                message,
                traceId: this.extractTraceId(error, message),
            };
        }

        renderError(error, traceId = null) {
            const normalized = typeof error === "string"
                ? this.normalize(new Error(error))
                : this.normalize(error);
            const effectiveTraceId = traceId || normalized.traceId;
            const traceMarkup = effectiveTraceId
                ? `<div class="error-card-trace">trace_id: <code>${this.escapeHtml(effectiveTraceId)}</code></div>`
                : "";
            return `
                <div class="error-card error-${this.escapeHtml(normalized.tone)}" data-error-type="${this.escapeHtml(normalized.type)}">
                    <div class="error-card-title">${this.escapeHtml(normalized.title)}</div>
                    <div class="error-card-message">${this.escapeHtml(normalized.message)}</div>
                    ${traceMarkup}
                </div>
            `;
        }

        show(error, containerId, traceId = null) {
            const container = typeof containerId === "string"
                ? document.getElementById(containerId)
                : containerId;
            if (!container) return false;
            container.innerHTML = this.renderError(error, traceId);
            return true;
        }

        extractMessage(error) {
            if (!error) return "";
            if (typeof error === "string") return error;
            return error.message || error.detail || error.reason || "";
        }

        extractTraceId(error, message = "") {
            const payloadTrace = error?.payload?.data?.trace_id
                || error?.payload?.trace_id
                || error?.traceId
                || error?.trace_id;
            if (payloadTrace) return payloadTrace;
            const match = String(message || "").match(/trace_id[=:]\s*([A-Za-z0-9_.:-]+)/);
            return match ? match[1] : "";
        }

        escapeHtml(value) {
            const div = document.createElement("div");
            div.textContent = String(value || "");
            return div.innerHTML;
        }
    }

    window.errorHandler = new ErrorHandler();
}());
