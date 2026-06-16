import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = fs.readFileSync("static/enterprise-api-client.js", "utf8");

function createSandbox() {
  const storage = new Map();
  const sandbox = {
    console,
    window: {},
    localStorage: {
      getItem(key) {
        return storage.get(key) || "";
      },
      setItem(key, value) {
        storage.set(key, String(value));
      },
      removeItem(key) {
        storage.delete(key);
      },
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.runInNewContext(source, sandbox, { filename: "enterprise-api-client.js" });
  return sandbox;
}

function jsonResponse(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    clone() {
      return this;
    },
    async json() {
      return payload;
    },
  };
}

test("reads and clears the shared enterprise token", () => {
  const sandbox = createSandbox();
  sandbox.localStorage.setItem("enterpriseAuthToken", "token-demo");

  assert.equal(sandbox.EnterpriseApiClient.getToken(), "token-demo");
  sandbox.EnterpriseApiClient.clearToken();
  assert.equal(sandbox.EnterpriseApiClient.getToken(), "");
});

test("request attaches bearer token and parses ok JSON", async () => {
  const sandbox = createSandbox();
  sandbox.localStorage.setItem("enterpriseAuthToken", "token-demo");
  let seenHeaders = null;
  sandbox.fetch = async (_url, options) => {
    seenHeaders = options.headers;
    return jsonResponse(200, { code: 200, data: { ok: true } });
  };

  const payload = await sandbox.EnterpriseApiClient.request("/me/profile");

  assert.equal(seenHeaders.Authorization, "Bearer token-demo");
  assert.equal(payload.data.ok, true);
});

test("401 clears token and classifies unauthenticated", async () => {
  const sandbox = createSandbox();
  sandbox.localStorage.setItem("enterpriseAuthToken", "token-demo");
  sandbox.fetch = async () => jsonResponse(401, { detail: "expired" });

  await assert.rejects(
    () => sandbox.EnterpriseApiClient.request("/me/profile"),
    (error) => {
      assert.equal(error.category, "unauthenticated");
      assert.equal(error.message, "expired");
      return true;
    },
  );
  assert.equal(sandbox.EnterpriseApiClient.getToken(), "");
});

test("404 is classified as old backend or unmounted api", async () => {
  const sandbox = createSandbox();

  const error = await sandbox.EnterpriseApiClient.readError(jsonResponse(404, {}));

  assert.equal(error.category, "not_found_or_old_backend");
  assert.match(error.message, /旧后端|接口未挂载/);
});

test("network failure is classified separately from backend errors", async () => {
  const sandbox = createSandbox();
  sandbox.fetch = async () => {
    throw new Error("socket closed");
  };

  await assert.rejects(
    () => sandbox.EnterpriseApiClient.request("/health"),
    (error) => {
      assert.equal(error.category, "network_error");
      assert.match(error.message, /无法连接后端服务/);
      return true;
    },
  );
});

test("loadCapabilityHealth returns profile capabilities", async () => {
  const sandbox = createSandbox();
  sandbox.fetch = async () => jsonResponse(200, {
    code: 200,
    data: {
      user: { username: "demo" },
      capabilities: {
        profile: { status: "ok" },
        document_worker: { status: "degraded", reason: "worker_unknown" },
      },
    },
  });

  const health = await sandbox.EnterpriseApiClient.loadCapabilityHealth();

  assert.equal(health.profile.status, "ok");
  assert.equal(health.document_worker.status, "degraded");
});
