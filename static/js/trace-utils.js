(function () {
    "use strict";

    class TraceManager {
        constructor() {
            this.prefix = "fe";
            this.sessionId = this.generateSessionId();
            this.installed = false;
            this.originalFetch = null;
            this.lastTraceId = "";
            this.lastRequestId = "";
        }

        generateSessionId() {
            return Math.random().toString(36).slice(2, 10);
        }

        generateTraceId() {
            return `${this.prefix}-${this.sessionId}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        }

        generateRequestId() {
            return `req-${this.sessionId}-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
        }

        ensureHeaders(headersLike) {
            const headers = new Headers(headersLike || {});
            const traceId = headers.get("X-Trace-Id") || this.generateTraceId();
            const requestId = headers.get("X-Request-Id") || this.generateRequestId();
            headers.set("X-Trace-Id", traceId);
            headers.set("X-Request-Id", requestId);
            this.lastTraceId = traceId;
            this.lastRequestId = requestId;
            return { headers, traceId, requestId };
        }

        install() {
            if (this.installed || typeof window.fetch !== "function") return;

            this.originalFetch = window.fetch.bind(window);
            window.fetch = async (input, init = {}) => {
                const requestInit = { ...init };
                const sourceHeaders = requestInit.headers
                    || (input instanceof Request ? input.headers : undefined);
                const { headers, traceId, requestId } = this.ensureHeaders(sourceHeaders);
                requestInit.headers = headers;

                const method = requestInit.method
                    || (input instanceof Request ? input.method : "GET");
                const url = input instanceof Request ? input.url : input;
                console.log(`[${traceId}] ${method || "GET"} ${url}`);

                try {
                    const response = await this.originalFetch(input, requestInit);
                    response.frontendTraceId = traceId;
                    response.frontendRequestId = requestId;
                    console.log(`[${traceId}] Response ${response.status}`);
                    return response;
                } catch (error) {
                    error.traceId = error.traceId || traceId;
                    error.requestId = error.requestId || requestId;
                    console.error(`[${traceId}] Error:`, error);
                    throw error;
                }
            };
            window.fetch.__traceWrapped = true;
            this.installed = true;
        }
    }

    window.TraceManager = TraceManager;
    window.traceManager = new TraceManager();
    window.traceManager.install();
}());
