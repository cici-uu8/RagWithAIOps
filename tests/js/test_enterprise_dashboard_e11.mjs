import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync("static/enterprise-dashboard.js", "utf8");
const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  window: {},
  document: {
    addEventListener() {},
    getElementById() {
      return null;
    },
  },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

vm.runInNewContext(source, sandbox, { filename: "enterprise-dashboard.js" });

const helpers = sandbox.EnterpriseE11Dashboard;

test("normalizes frozen SSE envelope without backend-specific assumptions", () => {
  const event = helpers.normalizeEvent({
    type: "plan",
    trace_id: "trace-e11",
    request_id: "request-e11",
    message: "plan ready",
    plan: ["check alert"],
  });

  assert.equal(event.type, "plan");
  assert.equal(event.stage, "plan");
  assert.equal(event.status, "completed");
  assert.equal(event.trace_id, "trace-e11");
  assert.equal(event.request_id, "request-e11");
  assert.deepEqual(event.data.plan, ["check alert"]);
});

test("parses split SSE frames from chat_stream", () => {
  const events = [];
  const parser = helpers.createSseParser((event) => events.push(event));

  parser.feed('event: message\ndata: {"type":"content","trace_id":"t1",');
  parser.feed('"request_id":"r1","data":"hello"}\n\n');
  parser.feed('event: message\ndata: {"type":"done","trace_id":"t1","request_id":"r1","data":{"answer":"hello"}}\n\n');

  assert.equal(events.length, 2);
  assert.equal(events[0].type, "content");
  assert.equal(events[0].data, "hello");
  assert.equal(events[1].stage, "done");
  assert.equal(events[1].status, "completed");
});

test("updates run state for aiops report and terminal states", () => {
  const run = helpers.createRunState("aiops");

  helpers.applyEventToRun(run, helpers.normalizeEvent({
    type: "report",
    trace_id: "trace-aiops",
    request_id: "request-aiops",
    message: "report ready",
    report: "# Report",
  }));
  helpers.applyEventToRun(run, helpers.normalizeEvent({
    type: "complete",
    trace_id: "trace-aiops",
    request_id: "request-aiops",
    message: "done",
  }));

  assert.equal(run.traceId, "trace-aiops");
  assert.equal(run.requestId, "request-aiops");
  assert.equal(run.finalStatus, "done");
  assert.equal(run.reportText, "# Report");
  assert.equal(run.timeline.length, 2);
});

test("builds authenticated request headers from shared enterprise token", () => {
  sandbox.localStorage = {
    getItem(key) {
      return key === "enterpriseAuthToken" ? "token-demo" : "";
    },
  };

  const headers = helpers.buildRequestHeaders("trace-ui", "request-ui");

  assert.equal(headers["Content-Type"], "application/json");
  assert.equal(headers["X-Trace-Id"], "trace-ui");
  assert.equal(headers["X-Request-Id"], "request-ui");
  assert.equal(headers.Authorization, "Bearer token-demo");
});

test("leaves authorization header absent when no enterprise token exists", () => {
  sandbox.localStorage = {
    getItem() {
      return "";
    },
  };

  const headers = helpers.buildRequestHeaders("trace-ui", "request-ui");

  assert.equal(headers.Authorization, undefined);
});

test("marks blocked and error as terminal UI states", () => {
  const blockedRun = helpers.createRunState("chat_stream");
  helpers.applyEventToRun(blockedRun, helpers.normalizeEvent({
    type: "blocked",
    trace_id: "trace-blocked",
    request_id: "request-blocked",
    data: { reason: "rule_guardrail_blocked" },
  }));
  assert.equal(blockedRun.finalStatus, "blocked");

  const errorRun = helpers.createRunState("chat_stream");
  helpers.applyEventToRun(errorRun, helpers.normalizeEvent({
    type: "error",
    trace_id: "trace-error",
    request_id: "request-error",
    data: "boom",
  }));
  assert.equal(errorRun.finalStatus, "error");
});
