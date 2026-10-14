// APEX-TRADER Cloudflare Worker.
// Dashboard assets plus read-only scheduled supervision.
// Cron jobs never place, cancel, or close exchange orders.

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };
const DEFAULT_BINANCE_BASE = "https://testnet.binancefuture.com";
const RECONCILIATION_LEASE = "apex-trading-reconciliation";
const BINANCE_ERROR_BODY_LIMIT = 2048;
const HEALTH_TIMEOUT_MS = 5000;

function json(data, status = 200, headers = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...JSON_HEADERS, ...headers },
  });
}

function requireSecret(env, name) {
  const value = env[name];
  if (!value) throw new Error(`missing Worker secret: ${name}`);
  return value;
}

function getBinanceBase(env) {
  const base = String(env.BINANCE_BASE_URL || DEFAULT_BINANCE_BASE).replace(/\/$/, "");
  if (base !== DEFAULT_BINANCE_BASE && env.ALLOW_LIVE_CRON !== "true") {
    throw new Error("non-Testnet Binance endpoint is disabled");
  }
  return base;
}

async function checkDependency(name, task) {
  const startedAt = Date.now();
  try {
    await task();
    return { status: "ok", latency_ms: Date.now() - startedAt };
  } catch (error) {
    console.error(JSON.stringify({
      event: "health_dependency_error",
      dependency: name,
      error_name: error?.name || "Error",
      error: safeErrorMessage(error),
      timestamp: new Date().toISOString(),
    }));
    return { status: "error", latency_ms: Date.now() - startedAt };
  }
}

async function healthResponse(env) {
  const signal = AbortSignal.timeout(HEALTH_TIMEOUT_MS);
  const [supabase, binance] = await Promise.all([
    checkDependency("supabase", () => supabaseRequest(
      env,
      "bot_state?select=id&limit=1",
      { signal },
    )),
    checkDependency("binance_testnet", () => binancePublic(
      "/fapi/v1/ping",
      {},
      DEFAULT_BINANCE_BASE,
    )),
  ]);
  const healthy = supabase.status === "ok" && binance.status === "ok";
  return json({
    service: "apex-trader-dashboard",
    worker: "ok",
    scheduler: "cron-enabled",
    status: healthy ? "ok" : "degraded",
    checked_at: new Date().toISOString(),
    testnet_only: true,
    checks: { worker: { status: "ok" }, supabase, binance_testnet: binance },
  }, healthy ? 200 : 503, { "cache-control": "no-store" });
}

function redactDiagnosticText(value) {
  return String(value || "")
    .replace(/("(?:authorization|api[_-]?key|token|secret|signature)"\s*:\s*")[^"]*(")/gi, "$1[redacted]$2")
    .replace(/(authorization|api[_-]?key|token|secret|signature)(\s*[:=]\s*)["']?[^\s,"'&}]+/gi, "$1$2[redacted]")
    .replace(/bot\d{5,}:[A-Za-z0-9_-]{20,}/g, "[redacted Telegram token]")
    .replace(/(https?:\/\/[^?\s"']+)\?[^\s"']+/gi, "$1?[redacted]");
}

async function readResponseSnippet(response, maxBytes = BINANCE_ERROR_BODY_LIMIT) {
  if (!response.body) return { body: "", truncated: false };
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  let truncated = false;
  try {
    while (size <= maxBytes) {
      const { done, value } = await reader.read();
      if (done) break;
      const remaining = maxBytes - size;
      if (value.byteLength > remaining) {
        chunks.push(value.slice(0, Math.max(0, remaining)));
        size += Math.max(0, remaining);
        truncated = true;
        await reader.cancel();
        break;
      }
      chunks.push(value);
      size += value.byteLength;
      if (size === maxBytes) {
        truncated = true;
        await reader.cancel();
        break;
      }
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { body: redactDiagnosticText(new TextDecoder().decode(bytes)), truncated };
}

function logBinanceHttpError(path, response, snippet, requestUrl) {
  console.error(JSON.stringify({
    event: "binance_http_error",
    endpoint: path,
    status: response.status,
    request_host: new URL(requestUrl).host,
    response_headers: {
      content_type: response.headers.get("content-type"),
      retry_after: response.headers.get("retry-after"),
      server: response.headers.get("server"),
      cf_ray: response.headers.get("cf-ray"),
      used_weight_1m: response.headers.get("x-mbx-used-weight-1m"),
      order_count_10s: response.headers.get("x-mbx-order-count-10s"),
      date: response.headers.get("date"),
    },
    response_body: snippet.body,
    body_truncated: snippet.truncated,
    timestamp: new Date().toISOString(),
  }));
}

async function hmacSha256(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function binancePublic(path, params = {}, base = DEFAULT_BINANCE_BASE) {
  const query = new URLSearchParams(params).toString();
  const requestUrl = `${base}${path}${query ? `?${query}` : ""}`;
  let response;
  try {
    response = await fetch(requestUrl, {
      headers: { "user-agent": "apex-trader-cloudflare-cron" },
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
  } catch (error) {
    console.error(JSON.stringify({
      event: "binance_network_error",
      endpoint: path,
      request_host: new URL(requestUrl).host,
      error_name: error?.name || "Error",
      error: redactDiagnosticText(error?.message || String(error)),
      timestamp: new Date().toISOString(),
    }));
    throw new Error(`Binance public ${path} network request failed`);
  }
  if (!response.ok) {
    const snippet = await readResponseSnippet(response);
    logBinanceHttpError(path, response, snippet, requestUrl);
    throw new Error(`Binance public ${path} returned ${response.status}`);
  }
  return response.json();
}

async function binanceSigned(path, env, params = {}) {
  const apiKey = requireSecret(env, "BINANCE_API_KEY");
  const secret = requireSecret(env, "BINANCE_SECRET_KEY");
  const queryParams = new URLSearchParams({
    ...params,
    timestamp: String(Date.now()),
    recvWindow: "10000",
  });
  const query = queryParams.toString();
  const signature = await hmacSha256(secret, query);
  const base = env.BINANCE_BASE_URL || DEFAULT_BINANCE_BASE;
  if (base !== DEFAULT_BINANCE_BASE && env.ALLOW_LIVE_CRON !== "true") {
    throw new Error("live Binance Cron is disabled; set ALLOW_LIVE_CRON=true only after approval");
  }
  const requestUrl = `${base}${path}?${query}&signature=${signature}`;
  const response = await fetch(requestUrl, {
    headers: { "X-MBX-APIKEY": apiKey, "user-agent": "apex-trader-cloudflare-cron" },
  });
  if (!response.ok) {
    const snippet = await readResponseSnippet(response);
    logBinanceHttpError(path, response, snippet, requestUrl);
    throw new Error(`Binance signed ${path} returned ${response.status}`);
  }
  return response.json();
}

async function supabaseRequest(env, tableOrPath, options = {}) {
  const base = requireSecret(env, "SUPABASE_URL").replace(/\/$/, "");
  // SUPABASE_SERVICE_ROLE_KEY is preferred; SUPABASE_WRITE_KEY is supported
  // for the repository's existing secret naming during migration.
  const key = env.SUPABASE_SERVICE_ROLE_KEY || env.SUPABASE_WRITE_KEY;
  if (!key) throw new Error("missing Worker secret: SUPABASE_SERVICE_ROLE_KEY");
  const path = tableOrPath.startsWith("/") ? tableOrPath : `/rest/v1/${tableOrPath}`;
  const response = await fetch(`${base}${path}`, {
    method: options.method || "GET",
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      "content-type": "application/json",
      Prefer: options.prefer || "return=representation",
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });
  if (!response.ok) throw new Error(`Supabase ${path} returned ${response.status}: ${(await response.text()).slice(0, 160)}`);
  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

async function withExecutionLease(env, leaseName, ownerId, task) {
  const acquired = await supabaseRequest(env, "/rest/v1/rpc/acquire_execution_lease", {
    method: "POST",
    body: {
      p_lease_name: leaseName,
      p_owner_id: ownerId,
      p_ttl_seconds: 120,
      p_metadata: { provider: "cloudflare_worker", cron: leaseName },
    },
    prefer: "return=representation",
  });

  if (acquired !== true) {
    console.log(JSON.stringify({ event: "lease_busy", lease_name: leaseName, owner_id: ownerId }));
    return { skipped: true, reason: "lease_busy" };
  }

  try {
    return await task();
  } finally {
    await supabaseRequest(env, "/rest/v1/rpc/release_execution_lease", {
      method: "POST",
      body: { p_lease_name: leaseName, p_owner_id: ownerId },
      prefer: "return=minimal",
    }).catch((error) => console.error(JSON.stringify({ event: "lease_release_error", error: String(error) })));
  }
}

async function telegram(env, message) {
  const token = requireSecret(env, "TELEGRAM_BOT_TOKEN");
  const chatId = requireSecret(env, "TELEGRAM_CHAT_ID");
  const response = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: chatId, text: message, parse_mode: "HTML", disable_web_page_preview: true }),
  });
  if (!response.ok) throw new Error(`Telegram returned ${response.status}`);
}

async function sendDedupedMonitorAlert(env, alertType, message) {
  const bucket = new Date().toISOString().slice(0, 13);
  const idempotencyKey = `cloudflare_monitor:${alertType}:${bucket}`;
  const existing = await supabaseRequest(
    env,
    `trading_events?select=event_id&idempotency_key=eq.${encodeURIComponent(idempotencyKey)}&limit=1`
  );
  if (existing?.length) return false;
  await telegram(env, message);
  await supabaseRequest(env, "trading_events", {
    method: "POST",
    body: {
      event_type: "SYSTEM_ALERT",
      idempotency_key: idempotencyKey,
      source: "cloudflare_monitor",
      payload: { alert_type: alertType },
    },
  });
  return true;
}

function normalizeSymbol(symbol) {
  return String(symbol || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

async function getOpenDbTrades(env) {
  return supabaseRequest(env, "trades?select=id,symbol,status,entry_quantity,remaining_quantity,entry_order_id,reconciliation_note&status=in.(OPEN,NEEDS_RECONCILIATION)&limit=100");
}

async function getUnresolvedTrades(env) {
  return supabaseRequest(
    env,
    "trades?select=id,symbol,status,entry_order_id,reconciliation_note&status=eq.NEEDS_RECONCILIATION&order=symbol.asc&limit=100"
  );
}

async function updateReconciliationRun(env, runId, fields) {
  await supabaseRequest(env, `reconciliation_runs?id=eq.${encodeURIComponent(runId)}`, {
    method: "PATCH",
    body: fields,
    prefer: "return=minimal",
  });
}

function safeErrorMessage(error) {
  return redactDiagnosticText(error?.message || String(error)).slice(0, 500);
}

async function runDailyReconciliation(env, ownerId) {
  const startedAt = new Date();
  const leaseName = RECONCILIATION_LEASE;
  const created = await supabaseRequest(env, "reconciliation_runs", {
    method: "POST",
    body: {
      checked_at: startedAt.toISOString(),
      started_at: startedAt.toISOString(),
      source: "cloudflare_cron_read_only",
      run_status: "running",
      lease_name: leaseName,
      findings: [],
    },
    prefer: "return=representation",
  });
  const run = Array.isArray(created) ? created[0] : created;
  if (!run?.id) throw new Error("reconciliation run insert did not return an id");

  let acquired = false;
  try {
    const leaseResult = await supabaseRequest(env, "/rest/v1/rpc/acquire_execution_lease", {
      method: "POST",
      body: {
        p_lease_name: leaseName,
        p_owner_id: ownerId,
        p_ttl_seconds: 120,
        p_metadata: { provider: "cloudflare_worker", cron: "0 2 * * *", mode: "read_only" },
      },
      prefer: "return=representation",
    });
    acquired = leaseResult === true;

    if (!acquired) {
      const finishedAt = new Date();
      await updateReconciliationRun(env, run.id, {
        run_status: "skipped",
        error_message: "reconciliation lease is already held",
        finished_at: finishedAt.toISOString(),
        duration_ms: finishedAt.getTime() - startedAt.getTime(),
      });
      console.log(JSON.stringify({
        event: "reconciliation_skipped",
        run_id: run.id,
        lease_name: leaseName,
        reason: "lease_busy",
      }));
      return { skipped: true, reason: "lease_busy", run_id: run.id };
    }

    const report = await reconcileDaily(env);
    const finishedAt = new Date();
    await updateReconciliationRun(env, run.id, {
      checked_at: report.checked_at,
      source: report.source,
      db_open_count: report.db_open_count,
      exchange_open_count: report.exchange_open_count,
      occupied_slot_count: report.occupied_slot_count,
      finding_count: report.finding_count,
      findings: report.findings,
      run_status: "completed",
      finished_at: finishedAt.toISOString(),
      duration_ms: finishedAt.getTime() - startedAt.getTime(),
      error_message: null,
    });

    try {
      if (report.findings.length) {
        const lines = report.findings.slice(0, 12).map((item) => `• ${item}`).join("\n");
        await telegram(env,
          `⬡ <b>APEX TRADER - مصالحة يومية</b>\n\n` +
          `🚨 <b>توجد حالات تحتاج مراجعة</b>\n` +
          `المطابقات غير المحسومة: <code>${report.findings.length}</code>\n\n${lines}\n\n` +
          `⛔ لم يتم فتح أو إغلاق أو تعديل أي أمر.`
        );
      } else {
        await telegram(env,
          `⬡ <b>APEX TRADER - مصالحة يومية</b>\n\n` +
          `✅ لا توجد فروقات بين Supabase وBinance\n` +
          `المراكز: <code>${report.exchange_open_count}</code> | Slots: <code>${report.occupied_slot_count}</code>\n` +
          `🔒 الفحص قراءة فقط.`
        );
      }
    } catch (error) {
      console.error(JSON.stringify({
        event: "reconciliation_notification_error",
        run_id: run.id,
        error: safeErrorMessage(error),
      }));
    }
    return { ...report, run_id: run.id };
  } catch (error) {
    const finishedAt = new Date();
    await updateReconciliationRun(env, run.id, {
      run_status: "failed",
      finding_count: 1,
      findings: [`فشل إجراء المصالحة: ${safeErrorMessage(error)}`],
      error_message: safeErrorMessage(error),
      finished_at: finishedAt.toISOString(),
      duration_ms: finishedAt.getTime() - startedAt.getTime(),
    }).catch((updateError) => console.error(JSON.stringify({
      event: "reconciliation_run_update_error",
      run_id: run.id,
      error: safeErrorMessage(updateError),
    })));
    throw error;
  } finally {
    if (acquired) {
      await supabaseRequest(env, "/rest/v1/rpc/release_execution_lease", {
        method: "POST",
        body: { p_lease_name: leaseName, p_owner_id: ownerId },
        prefer: "return=minimal",
      }).catch((error) => console.error(JSON.stringify({
        event: "lease_release_error",
        lease_name: leaseName,
        error: safeErrorMessage(error),
      })));
    }
  }
}

async function reconcileDaily(env) {
  const [dbTrades, exchangePositions, slots] = await Promise.all([
    getOpenDbTrades(env),
    binanceSigned("/fapi/v2/positionRisk", env),
    supabaseRequest(env, "position_slots?select=slot_no,symbol,trade_id,reservation_id,status&status=in.(reserved,occupied)&limit=10"),
  ]);

  const exchangeOpen = new Map(
    (exchangePositions || [])
      .filter((p) => Math.abs(Number(p.positionAmt || 0)) > 0)
      .map((p) => [normalizeSymbol(p.symbol), p])
  );
  const findings = [];
  const localOpen = new Set();

  for (const trade of dbTrades || []) {
    const symbolKey = normalizeSymbol(trade.symbol);
    localOpen.add(symbolKey);
    const exchange = exchangeOpen.get(symbolKey);
    if (!exchange) {
      findings.push(`${trade.symbol}: سجل ${trade.status} بلا مركز مطابق في Binance`);
      continue;
    }
    const dbQty = Number(trade.remaining_quantity || trade.entry_quantity || 0);
    const exchangeQty = Math.abs(Number(exchange.positionAmt || 0));
    if (dbQty > 0 && Math.abs(dbQty - exchangeQty) > Math.max(1e-8, dbQty * 0.001)) {
      findings.push(`${trade.symbol}: اختلاف كمية DB=${dbQty} Binance=${exchangeQty}`);
    }
  }

  for (const [symbolKey, position] of exchangeOpen) {
    if (!localOpen.has(symbolKey)) {
      findings.push(`${position.symbol}: مركز موجود في Binance بلا سجل محلي`);
    }
  }

  const report = {
    checked_at: new Date().toISOString(),
    source: "cloudflare_cron_read_only",
    db_open_count: (dbTrades || []).length,
    exchange_open_count: exchangeOpen.size,
    occupied_slot_count: (slots || []).length,
    finding_count: findings.length,
    findings,
  };
  return report;
}

async function refreshUniverse(env) {
  const [exchangeInfo, tickers] = await Promise.all([
    binancePublic("/fapi/v1/exchangeInfo", {}, getBinanceBase(env)),
    binancePublic("/fapi/v1/ticker/24hr", {}, getBinanceBase(env)),
  ]);
  const allowed = new Set((exchangeInfo.symbols || [])
    .filter((s) => s.status === "TRADING" && s.quoteAsset === "USDT" && s.contractType === "PERPETUAL")
    .map((s) => s.symbol));
  const ranked = (tickers || [])
    .filter((t) => allowed.has(t.symbol) && Number(t.quoteVolume) > 0)
    .sort((a, b) => Number(b.quoteVolume) - Number(a.quoteVolume))
    .slice(0, Number(env.UNIVERSE_SIZE || 20));
  if (!ranked.length) throw new Error("Binance returned an empty universe");

  const now = new Date();
  const expires = new Date(now.getTime() + 4 * 60 * 60 * 1000);
  const snapshotId = crypto.randomUUID();
  const rows = ranked.map((t, index) => ({
    snapshot_id: snapshotId,
    symbol: `${t.symbol.slice(0, -4)}/USDT:USDT`,
    rank: index + 1,
    quote_volume_24h: Number(t.quoteVolume),
    spread_bps: 0,
    liquidity_score: Number(t.quoteVolume),
    selected_at: now.toISOString(),
    expires_at: expires.toISOString(),
    source: "binance_usdm_cloudflare_cron",
  }));
  await supabaseRequest(env, "universe_snapshots", { method: "POST", body: { id: snapshotId, expires_at: expires.toISOString(), source: "binance_usdm_cloudflare_cron" } });
  await supabaseRequest(env, "universe_symbols", { method: "POST", body: rows });
  await supabaseRequest(env, "/rest/v1/rpc/activate_universe_snapshot", { method: "POST", body: { p_snapshot_id: snapshotId }, prefer: "return=minimal" });
  return { snapshot_id: snapshotId, symbols: rows.map((r) => r.symbol) };
}

async function monitor(env) {
  const [risk, reconciliation, summary, subtypePerformance, unresolved] = await Promise.all([
    supabaseRequest(env, "dashboard_risk_state?select=*&limit=1"),
    supabaseRequest(env, "dashboard_reconciliation_status?select=*&limit=1"),
    supabaseRequest(env, "dashboard_trade_summary?select=*&limit=1"),
    supabaseRequest(env, "dashboard_strategy_subtype_performance?select=*&order=closed_trades.desc&limit=20"),
    getUnresolvedTrades(env),
  ]);
  const state = risk?.[0] || null;
  const recon = reconciliation?.[0] || null;
  const result = {
    event: "monitor",
    entry_gate: state?.entry_gate || "unknown",
    active_slots: state?.active_slots ?? null,
    unresolved_count: state?.unresolved_trades ?? null,
    heartbeat_at: state?.heartbeat_at || null,
    bot_status: state?.bot_status || "unknown",
    is_running: state?.is_running === true,
    reconciliation_status: recon?.status || "unknown",
    confirmed_realized_pnl: summary?.[0]?.confirmed_realized_pnl ?? null,
    subtype_batch_size: Number(env.SUBTYPE_REPORT_BATCH_SIZE || 10),
    subtype_performance: subtypePerformance || [],
    unresolved_pairs: (unresolved || []).map((trade) => ({
      id: trade.id,
      symbol: trade.symbol,
      status: trade.status,
      entry_order_id: trade.entry_order_id,
    })),
  };
  console.log(JSON.stringify(result));
  if (unresolved?.length) {
    const pairs = unresolved.slice(0, 30).map((trade) =>
      `• ${trade.symbol} | trade=${trade.id} | order=${trade.entry_order_id || "n/a"}`
    ).join("\n");
    const stateKey = unresolved.map((trade) => `${trade.symbol}:${trade.id}`).join(",");
    await sendDedupedMonitorAlert(
      env,
      `needs_reconciliation:${stateKey}`,
      "⬡ <b>APEX TRADER - مصالحة معلقة</b>\n\n" +
      `🚨 <b>${unresolved.length} زوج/أزواج تحتاج مراجعة</b>\n` +
      `${pairs}\n\n` +
      "⛔ الدخول الجديد محجوب لهذه الحالات فقط؛ يجري الإغلاق الآلي في Testnet عند تفعيل البوابة، دون تبنّي مركز أو اختلاق Fill."
    );
  }
  const heartbeatMs = state?.heartbeat_at ? Date.parse(state.heartbeat_at) : NaN;
  const botExpectedToRun = state?.is_running === true && state?.bot_status === "running";
  if (botExpectedToRun && (!Number.isFinite(heartbeatMs) || Date.now() - heartbeatMs > 10 * 60 * 1000)) {
    await sendDedupedMonitorAlert(
      env,
      "stale_heartbeat",
      "⬡ <b>APEX TRADER - تنبيه مراقبة</b>\n\n" +
      "🚨 <b>Heartbeat متوقف أو قديم</b>\n" +
      "لم يتم تعديل أوامر؛ يرجى فحص GitHub Actions وSupabase."
    );
  }
  return result;
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") return json({ error: "method_not_allowed" }, 405);
    const url = new URL(request.url);
    if (url.pathname === "/api/health") return healthResponse(env);
    return env.ASSETS.fetch(request);
  },

  async scheduled(controller, env, ctx) {
    const job = controller.cron;
    let task;
    const ownerId = `cloudflare:${job}:${crypto.randomUUID()}`;
    if (job === "0 2 * * *") {
      task = runDailyReconciliation(env, ownerId);
    } else if (job === "0 */4 * * *") {
      task = withExecutionLease(env, "apex-universe-refresh", ownerId, () => refreshUniverse(env));
    }
    else if (job === "*/5 * * * *") task = monitor(env);
    else task = Promise.resolve();
    // Never leave a scheduled rejection unhandled; log the real cause instead.
    ctx.waitUntil(Promise.resolve(task).catch((error) => {
      console.error(JSON.stringify({
        event: "cron_error",
        cron: job,
        error: String(error),
        stack: error?.stack || ""
      }));
    }));
  },
};
