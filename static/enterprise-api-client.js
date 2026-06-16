(function () {
    "use strict";

    const API_BASE_URL = "/api";
    const TOKEN_STORAGE_KEY = "enterpriseAuthToken";

    class EnterpriseApiError extends Error {
        constructor(message, options = {}) {
            super(message);
            this.name = "EnterpriseApiError";
            this.category = options.category || "backend_error";
            this.status = options.status || 0;
            this.payload = options.payload || null;
        }
    }

    function storage() {
        try {
            return window.localStorage || localStorage;
        } catch (_error) {
            return null;
        }
    }

    function getToken() {
        const store = storage();
        return store ? store.getItem(TOKEN_STORAGE_KEY) || "" : "";
    }

    function setToken(token) {
        const store = storage();
        if (store && token) {
            store.setItem(TOKEN_STORAGE_KEY, token);
        }
    }

    function clearToken() {
        const store = storage();
        if (store) {
            store.removeItem(TOKEN_STORAGE_KEY);
        }
    }

    function apiUrl(path) {
        if (/^https?:\/\//.test(path)) {
            return path;
        }
        if (path.startsWith("/api/") || path === "/api") {
            return path;
        }
        return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
    }

    function authHeaders(extraHeaders = {}) {
        const headers = { ...extraHeaders };
        const token = getToken();
        if (token) {
            headers.Authorization = `Bearer ${token}`;
        }
        return headers;
    }

    async function readJson(response) {
        try {
            return await response.clone().json();
        } catch (_error) {
            return null;
        }
    }

    function detailFromPayload(payload) {
        return payload?.detail
            || payload?.message
            || payload?.data?.user_message
            || payload?.data?.reason
            || "";
    }

    async function readError(response) {
        const payload = await readJson(response);
        const detail = detailFromPayload(payload);
        if (response.status === 401) {
            return new EnterpriseApiError(detail || "登录已过期，请重新登录。", {
                category: "unauthenticated",
                status: response.status,
                payload,
            });
        }
        if (response.status === 403) {
            return new EnterpriseApiError(detail || "你没有权限使用该功能，请联系管理员授权。", {
                category: "forbidden",
                status: response.status,
                payload,
            });
        }
        if (response.status === 404) {
            return new EnterpriseApiError(detail || "接口不存在，可能是旧后端、旧端口或接口未挂载。", {
                category: "not_found_or_old_backend",
                status: response.status,
                payload,
            });
        }
        if (response.status >= 500) {
            const traceId = payload?.data?.trace_id || payload?.trace_id;
            return new EnterpriseApiError(
                detail
                    || (traceId
                        ? `后端处理失败，请复制 trace_id=${traceId} 给开发者排查。`
                        : "后端处理失败，请查看服务日志。"),
                {
                    category: "backend_error",
                    status: response.status,
                    payload,
                },
            );
        }
        return new EnterpriseApiError(detail || `HTTP错误: ${response.status}`, {
            category: "backend_error",
            status: response.status,
            payload,
        });
    }

    async function rawRequest(path, options = {}) {
        const fetchImpl = options.fetchImpl || window.fetch;
        const requestOptions = { ...options };
        delete requestOptions.fetchImpl;
        const headers = authHeaders(requestOptions.headers || {});
        if (
            Object.prototype.hasOwnProperty.call(requestOptions, "body")
            && !headers["Content-Type"]
            && !(typeof FormData !== "undefined" && requestOptions.body instanceof FormData)
        ) {
            headers["Content-Type"] = "application/json";
        }
        let response;
        try {
            response = await fetchImpl(apiUrl(path), {
                ...requestOptions,
                headers,
            });
        } catch (_error) {
            throw new EnterpriseApiError("无法连接后端服务。请确认启动窗口仍然打开，或确认当前端口是新后端。", {
                category: "network_error",
            });
        }

        if (response.status === 401) {
            clearToken();
        }
        if (!response.ok) {
            throw await readError(response);
        }
        return response;
    }

    async function request(path, options = {}) {
        const response = await rawRequest(path, options);
        return response.json();
    }

    async function getProfile() {
        return request("/me/profile", { method: "GET" });
    }

    async function healthCheck() {
        return request("/health", { method: "GET" });
    }

    async function loadCapabilityHealth() {
        const profilePayload = await getProfile();
        return profilePayload?.data?.capabilities || {
            profile: {
                status: "unknown",
                reason: "profile_missing_capabilities",
            },
        };
    }

    window.EnterpriseApiClient = {
        EnterpriseApiError,
        TOKEN_STORAGE_KEY,
        getToken,
        setToken,
        clearToken,
        authHeaders,
        readError,
        rawRequest,
        request,
        getProfile,
        healthCheck,
        loadCapabilityHealth,
    };
}());
