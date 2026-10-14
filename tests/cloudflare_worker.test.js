import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/worker.js";

const SUPABASE_URL = "https://apex-test.supabase.co";
const BINANCE_BASE = "https://testnet.binancefuture.com";

function response(body, status = 200, headers = {}) {
  return new Response(typeof body === "string" ? body : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function replaceFetch(implementation) {
  const original = globalThis.fetch;
  globalThis.fetch = implementation;
  return () => { globalThis.fetch = original; };
}

function replaceConsoleError() {
  const original = console.error;
  const records = [];
  console.error = (...args) => records.push(args.join(" "));
  return { records, restore: () => { console.error = original; } };
}

test("/api/health checks Supabase and Binance Testnet and returns no-store", async () => {
  const calls = [];
  const restore = replaceFetch(async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.startsWith(SUPABASE_URL)) return response([{ id: 1 }]);
    if (url === `${BINANCE_BASE}/fapi/v1/ping`) return response({});
    throw new Error(`unexpected request ${url}`);
  });
  try {
    const result = await worker.fetch(
      new Request("https://worker.example/api/health"),
      { SUPABASE_URL, SUPABASE_WRITE_KEY: "test-key" },
    );
    const body = await result.json();
    assert.equal(result.status, 200);
    assert.equal(result.headers.get("cache-control"), "no-store");
    assert.equal(body.status, "ok");
    assert.equal(body.testnet_only, true);
    assert.equal(body.checks.supabase.status, "ok");
    assert.equal(body.checks.binance_testnet.status, "ok");
    assert.ok(calls.some((url) => url.includes("bot_state?select=id&limit=1")));
    assert.ok(calls.includes(`${BINANCE_BASE}/fapi/v1/ping`));
  } finally {
    restore();
  }
});

test("/api/health returns degraded when a dependency fails without leaking its response body", async () => {
  const restore = replaceFetch(async (input) => {
    const url = String(input);
    if (url.startsWith(SUPABASE_URL)) return response({ message: "internal database detail" }, 503);
    if (url === `${BINANCE_BASE}/fapi/v1/ping`) return response({});
    throw new Error(`unexpected request ${url}`);
  });
  try {
    const result = await worker.fetch(
      new Request("https://worker.example/api/health"),
      { SUPABASE_URL, SUPABASE_WRITE_KEY: "test-key" },
    );
    const body = await result.json();
    assert.equal(result.status, 503);
    assert.equal(body.status, "degraded");
    assert.equal(body.checks.supabase.status, "error");
    assert.equal(body.checks.binance_testnet.status, "ok");
    assert.doesNotMatch(JSON.stringify(body), /internal database detail/);
  } finally {
    restore();
  }
});

test("Binance public 403 logs a bounded, useful, redacted response diagnostic", async () => {
  const restoreFetch = replaceFetch(async (input) => {
    const url = String(input);
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/rpc/acquire_execution_lease`)) return response(true);
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/rpc/release_execution_lease`)) return response(null);
    if (url.includes("/fapi/v1/exchangeInfo")) {
      return response(
        '{"code":-1003,"msg":"egress denied","token":"super-secret"}',
        403,
        {
          "content-type": "application/json",
          "retry-after": "30",
          "x-mbx-used-weight-1m": "42",
          "cf-ray": "diagnostic-ray",
        },
      );
    }
    if (url.includes("/fapi/v1/ticker/24hr")) return response([]);
    throw new Error(`unexpected request ${url}`);
  });
  const logs = replaceConsoleError();
  try {
    const pending = [];
    worker.scheduled(
      { cron: "0 */4 * * *" },
      { SUPABASE_URL, SUPABASE_WRITE_KEY: "test-key", BINANCE_BASE_URL: BINANCE_BASE, ALLOW_LIVE_CRON: "false" },
      { waitUntil: (promise) => pending.push(promise) },
    );
    await Promise.all(pending);
    const events = logs.records.map((record) => {
      try { return JSON.parse(record); } catch { return null; }
    }).filter(Boolean);
    const binance = events.find((event) => event.event === "binance_http_error");
    assert.ok(binance);
    assert.equal(binance.status, 403);
    assert.equal(binance.endpoint, "/fapi/v1/exchangeInfo");
    assert.equal(binance.request_host, "testnet.binancefuture.com");
    assert.equal(binance.response_headers.retry_after, "30");
    assert.equal(binance.response_headers.cf_ray, "diagnostic-ray");
    assert.match(binance.response_body, /egress denied/);
    assert.doesNotMatch(binance.response_body, /super-secret/);
    assert.ok(events.some((event) => event.event === "cron_error"));
  } finally {
    restoreFetch();
    logs.restore();
  }
});

test("daily reconciliation uses an independent lease and records a completed run", async () => {
  const calls = [];
  const restoreFetch = replaceFetch(async (input, init = {}) => {
    const url = String(input);
    const method = init.method || "GET";
    calls.push({ url, method, body: init.body ? JSON.parse(init.body) : null });
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/reconciliation_runs`) && method === "POST") return response([{ id: 51 }]);
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/reconciliation_runs`) && method === "PATCH") return response(null);
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/rpc/acquire_execution_lease`)) return response(true);
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/rpc/release_execution_lease`)) return response(null);
    if (url.includes("/rest/v1/trades?")) return response([]);
    if (url.includes("/rest/v1/position_slots?")) return response([]);
    if (url.startsWith(`${BINANCE_BASE}/fapi/v2/positionRisk`)) return response([]);
    if (url.startsWith("https://api.telegram.org/")) return response({ ok: true });
    throw new Error(`unexpected request ${method} ${url}`);
  });
  try {
    const pending = [];
    worker.scheduled(
      { cron: "0 2 * * *" },
      {
        SUPABASE_URL,
        SUPABASE_WRITE_KEY: "test-key",
        BINANCE_API_KEY: "test-api-key",
        BINANCE_SECRET_KEY: "test-secret",
        TELEGRAM_BOT_TOKEN: "12345:test-telegram-token",
        TELEGRAM_CHAT_ID: "123",
      },
      { waitUntil: (promise) => pending.push(promise) },
    );
    await Promise.all(pending);
    const leaseCall = calls.find((call) => call.url.startsWith(`${SUPABASE_URL}/rest/v1/rpc/acquire_execution_lease`));
    assert.equal(leaseCall.body.p_lease_name, "apex-trading-reconciliation");
    const createRun = calls.find((call) => call.url.startsWith(`${SUPABASE_URL}/rest/v1/reconciliation_runs`) && call.method === "POST");
    assert.equal(createRun.body.run_status, "running");
    assert.equal(createRun.body.lease_name, "apex-trading-reconciliation");
    const finalizeRun = calls.find((call) => call.url.startsWith(`${SUPABASE_URL}/rest/v1/reconciliation_runs`) && call.method === "PATCH");
    assert.equal(finalizeRun.body.run_status, "completed");
    assert.equal(finalizeRun.body.exchange_open_count, 0);
    assert.ok(calls.some((call) => call.url.startsWith("https://api.telegram.org/")));
  } finally {
    restoreFetch();
  }
});

test("busy reconciliation lease still records a skipped run and performs no Binance call", async () => {
  const calls = [];
  const restoreFetch = replaceFetch(async (input, init = {}) => {
    const url = String(input);
    const method = init.method || "GET";
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, method, body });
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/reconciliation_runs`) && method === "POST") return response([{ id: 52 }]);
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/reconciliation_runs`) && method === "PATCH") return response(null);
    if (url.startsWith(`${SUPABASE_URL}/rest/v1/rpc/acquire_execution_lease`)) return response(false);
    if (url.includes("/fapi/")) throw new Error("Binance must not be called when lease is busy");
    throw new Error(`unexpected request ${method} ${url}`);
  });
  try {
    const pending = [];
    worker.scheduled(
      { cron: "0 2 * * *" },
      { SUPABASE_URL, SUPABASE_WRITE_KEY: "test-key" },
      { waitUntil: (promise) => pending.push(promise) },
    );
    await Promise.all(pending);
    const finalizeRun = calls.find((call) => call.url.startsWith(`${SUPABASE_URL}/rest/v1/reconciliation_runs`) && call.method === "PATCH");
    assert.equal(finalizeRun.body.run_status, "skipped");
    assert.match(finalizeRun.body.error_message, /lease is already held/);
    assert.ok(!calls.some((call) => call.url.includes("/fapi/")));
  } finally {
    restoreFetch();
  }
});
