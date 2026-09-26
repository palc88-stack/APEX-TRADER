// APEX-TRADER hardened Cloudflare Worker.
// Required secrets: WEBHOOK_SECRET, SUPABASE_URL, SUPABASE_WRITE_KEY.

const MAX_BODY_BYTES = 16 * 1024;
const REQUEST_TIMEOUT_MS = 8000;
const ALLOWED_ACTIONS = new Set(["BUY", "SELL", "LONG", "SHORT"]);
const ALLOWED_SIDES = new Set(["buy", "sell"]);
const SYMBOL_RE = /^[A-Z0-9]{2,15}\/[A-Z0-9]{2,10}$/;

function json(data, status = 200, origin = "") {
  const headers = { "content-type": "application/json; charset=utf-8" };
  if (origin) headers["access-control-allow-origin"] = origin;
  return new Response(JSON.stringify(data), { status, headers });
}

function validPrice(value) {
  return value === null || (typeof value === "number" && Number.isFinite(value) && value > 0);
}

async function readJsonWithLimit(request) {
  const length = Number(request.headers.get("content-length") || 0);
  if (length > MAX_BODY_BYTES) throw new Error("body_too_large");
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) throw new Error("body_too_large");
  return JSON.parse(text);
}

export default {
  async fetch(request, env) {
    const allowedOrigin = env.TRADINGVIEW_ORIGIN || "https://www.tradingview.com";
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "access-control-allow-origin": allowedOrigin,
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "content-type, x-webhook-secret",
        },
      });
    }
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405, allowedOrigin);
    if (!env.WEBHOOK_SECRET || !env.SUPABASE_URL || !env.SUPABASE_WRITE_KEY) {
      return json({ error: "server_not_configured" }, 503, allowedOrigin);
    }
    if (request.headers.get("x-webhook-secret") !== env.WEBHOOK_SECRET) {
      return json({ error: "unauthorized" }, 401, allowedOrigin);
    }

    let signal;
    try {
      signal = await readJsonWithLimit(request);
    } catch (error) {
      return json({ error: error.message === "body_too_large" ? "body_too_large" : "invalid_json" }, 400, allowedOrigin);
    }

    const symbol = typeof signal.symbol === "string" ? signal.symbol.trim().toUpperCase() : "";
    const side = typeof signal.side === "string" ? signal.side.trim().toLowerCase() : "";
    const action = typeof signal.action === "string" ? signal.action.trim().toUpperCase() : "";
    const webhookId = typeof signal.id === "string" ? signal.id.trim() : "";
    const price = signal.price === undefined ? null : signal.price;

    if (!SYMBOL_RE.test(symbol) || !ALLOWED_SIDES.has(side) || !ALLOWED_ACTIONS.has(action)) {
      return json({ error: "invalid_signal_format" }, 400, allowedOrigin);
    }
    if (!webhookId || webhookId.length > 100 || !validPrice(price)) {
      return json({ error: "invalid_signal_identity_or_price" }, 400, allowedOrigin);
    }

    const payload = { symbol, side, action, price, webhook_id: webhookId, status: "pending" };
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(`${env.SUPABASE_URL}/rest/v1/pending_signals`, {
        method: "POST",
        signal: controller.signal,
        headers: {
          "content-type": "application/json",
          "apikey": env.SUPABASE_WRITE_KEY,
          "authorization": `Bearer ${env.SUPABASE_WRITE_KEY}`,
          "prefer": "resolution=ignore-duplicates,return=minimal",
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        console.error("pending_signal_insert_failed", response.status);
        return json({ error: "signal_not_stored" }, 502, allowedOrigin);
      }
      return json({ success: true }, 202, allowedOrigin);
    } catch (error) {
      console.error("pending_signal_request_failed", error.name);
      return json({ error: "upstream_timeout" }, 504, allowedOrigin);
    } finally {
      clearTimeout(timeout);
    }
  },
};
