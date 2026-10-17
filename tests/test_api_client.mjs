import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";
import { LocalConnectionError, requestLocal } from "../src/carbontrace/static/api-client.mjs";

afterEach(() => mock.restoreAll());

test("a disconnected local server offers recovery and never retries", async () => {
  const fetch = mock.method(globalThis, "fetch", async () => { throw new TypeError("Failed to fetch"); });
  await assert.rejects(requestLocal("/api/preflight", { method: "POST", body: "draft" }), (error) => {
    assert.ok(error instanceof LocalConnectionError);
    assert.equal(error.reconnect, true);
    assert.match(error.message, /CarbonTrace: start local app/);
    assert.match(error.message, /draft is still here/);
    return true;
  });
  assert.equal(fetch.mock.callCount(), 1);
});

test("an unresponsive local request is bounded", async () => {
  mock.method(globalThis, "fetch", (_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
  await assert.rejects(requestLocal("/api/health", {}, 5), /took too long/);
});

test("successful local requests preserve payload and request options", async () => {
  const fetch = mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ live_model_calls: 0 })));
  assert.deepEqual(await requestLocal("/api/preflight", { method: "POST", body: "draft" }), { live_model_calls: 0 });
  const [path, options] = fetch.mock.calls[0].arguments;
  assert.equal(path, "/api/preflight");
  assert.equal(options.method, "POST");
  assert.equal(options.body, "draft");
  assert.ok(options.signal instanceof AbortSignal);
});

test("validation errors retain the server explanation", async () => {
  mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ detail: [{ msg: "Invalid token range" }] }), { status: 422 }));
  await assert.rejects(requestLocal("/api/preflight"), (error) => {
    assert.equal(error.message, "Invalid token range");
    assert.equal(error.reconnect, undefined);
    return true;
  });
});

test("a wrong service or non-JSON error produces a readable message", async () => {
  mock.method(globalThis, "fetch", async () => new Response("<html>Proxy error</html>", { status: 502 }));
  await assert.rejects(requestLocal("/api/tasks"), /unreadable response \(HTTP 502\)/);
});

test("blocked live execution is never retried or unlocked", async () => {
  const fetch = mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ detail: "Live execution is disabled" }), { status: 423 }));
  await assert.rejects(requestLocal("/api/live-runs"), /Live execution is disabled/);
  assert.equal(fetch.mock.callCount(), 1);
});
