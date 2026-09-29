// APEX-TRADER Cloudflare Worker.
// Dashboard assets plus read-only scheduled supervision.
// Cron jobs never place, cancel, or close exchange orders.

const JSON_HEADERS = { "content-type": "application/json; charset=utf-8" };
const DEFAULT_BINANCE_BASE = "https://testnet.binancefuture.com";

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function requireSecret(env, name) {
  const value = env[name];
  if (!value) throw new Error(`missing Worker secret: ${name}`);
  return value;
}

async function hmacSha256(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return [...new Uint8Array(signature)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function binancePublic(path, params = {}) {
  const query = new URLSearchParams(params).toString();
  const response = await fetch(`${DEFAULT_BINANCE_BASE}${path}${query ? `?${query}` : ""}`, {
    headers: { "user-agent": "apex-trader-cloudflare-cron" },
  });
  if (!response.ok) throw new Error(`Binance public ${path} returned ${response.status}`);
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
  const response = await fetch(`${base}${path}?${query}&signature=${signature}`, {
    headers: { "X-MBX-APIKEY": apiKey, "user-agent": "apex-trader-cloudflare-cron" },
  });
  if (!response.ok) throw new Error(`Binance signed ${path} returned ${response.status}: ${(await response.text()).slice(0, 160)}`);
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
  });
  if (!response.ok) throw new Error(`Supabase ${path} returned ${response.status}: ${(await response.text()).slice(0, 160)}`);
  const text = await response.text();
  return text ? JSON.parse(text) : null;
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

function normalizeSymbol(symbol) {
  return String(symbol || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

async function getOpenDbTrades(env) {
  return supabaseRequest(env, "trades?select=id,symbol,status,entry_quantity,remaining_quantity,entry_order_id,reconciliation_note&status=in.(OPEN,NEEDS_RECONCILIATION)&limit=100");
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
  await supabaseRequest(env, "reconciliation_runs", { method: "POST", body: report });

  if (findings.length) {
    const lines = findings.slice(0, 12).map((item) => `• ${item}`).join("\n");
    await telegram(env,
      `⬡ <b>APEX TRADER - مصالحة يومية</b>\n\n` +
      `🚨 <b>توجد حالات تحتاج مراجعة</b>\n` +
      `المطابقات غير المحسومة: <code>${findings.length}</code>\n\n${lines}\n\n` +
      `⛔ لم يتم فتح أو إغلاق أو تعديل أي أمر.`
    );
  } else {
    await telegram(env,
      `⬡ <b>APEX TRADER - مصالحة يومية</b>\n\n` +
      `✅ لا توجد فروقات بين Supabase وBinance\n` +
      `المراكز: <code>${exchangeOpen.size}</code> | Slots: <code>${(slots || []).length}</code>\n` +
      `🔒 الفحص قراءة فقط.`
    );
  }
  return report;
}

async function refreshUniverse(env) {
  const [exchangeInfo, tickers] = await Promise.all([
    binancePublic("/fapi/v1/exchangeInfo"),
    binancePublic("/fapi/v1/ticker/24hr"),
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
  const [risk, reconciliation, summary] = await Promise.all([
    supabaseRequest(env, "dashboard_risk_state?select=*&limit=1"),
    supabaseRequest(env, "dashboard_reconciliation_status?select=*&limit=1"),
    supabaseRequest(env, "dashboard_trade_summary?select=*&limit=1"),
  ]);
  const state = risk?.[0] || null;
  const recon = reconciliation?.[0] || null;
  const result = {
    event: "monitor",
    entry_gate: state?.entry_gate || "unknown",
    active_slots: state?.active_slots ?? null,
    unresolved_count: state?.unresolved_trades ?? null,
    heartbeat_at: state?.heartbeat_at || null,
    reconciliation_status: recon?.status || "unknown",
    confirmed_realized_pnl: summary?.[0]?.confirmed_realized_pnl ?? null,
  };
  console.log(JSON.stringify(result));
  return result;
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") return json({ error: "method_not_allowed" }, 405);
    const url = new URL(request.url);
    if (url.pathname === "/api/health") return json({ service: "apex-trader-dashboard", worker: "ok", scheduler: "cron-enabled", stage: "strategy-router" });
    return env.ASSETS.fetch(request);
  },

  async scheduled(controller, env, ctx) {
    const job = controller.cron;
    let task;
    if (job === "0 2 * * *") task = reconcileDaily(env);
    else if (job === "0 */4 * * *") task = refreshUniverse(env);
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
