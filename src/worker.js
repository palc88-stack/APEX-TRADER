// APEX-TRADER dashboard-only Cloudflare Worker.
// Trading is performed by the Python bot through direct Binance/Bybit polling.

export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response(JSON.stringify({ error: "method_not_allowed" }), {
        status: 405,
        headers: { "content-type": "application/json; charset=utf-8" },
      });
    }

    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return new Response(JSON.stringify({
        service: "apex-trader-dashboard",
        worker: "ok",
        stage: "strategy-router",
      }), {
        status: 200,
        headers: { "content-type": "application/json; charset=utf-8" },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
