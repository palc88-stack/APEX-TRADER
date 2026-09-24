// src/worker.js - كود الربط الاحترافي المحمي
export default {
  async fetch(request, env, ctx) {
    // السماح فقط لـ POST من TradingView
    if (request.method !== \'POST\') {
      return new Response(JSON.stringify({ error: \'Method Not Allowed\' }), { status: 405 });
    }

    try {
      // 1. حماية الـ Webhook - أهم خطوة
      const secret = request.headers.get(\'x-webhook-secret\');
      if (!secret || secret !== env.WEBHOOK_SECRET) {
        return new Response(JSON.stringify({ error: \'Unauthorized\' }), { status: 401 });
      }

      const signal = await request.json();
      
      // 2. التحقق من صحة الإشارة
      if (!signal.symbol || !signal.side || !signal.action) {
        return new Response(JSON.stringify({ error: \'Invalid signal format\' }), { status: 400 });
      }

      // 3. تمرير الإشارة للسيرفر الحقيقي المخفي خلف Tunnel
      const botResponse = await fetch(env.BOT_SERVER_URL + "/webhook", {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "Authorization": `Bearer ${env.INTERNAL_API_KEY}`
        },
        body: JSON.stringify(signal)
      });

      if (!botResponse.ok) {
        throw new Error(`Bot server failed: ${botResponse.status}`);
      }

      return new Response(JSON.stringify({ success: true, message: "Signal forwarded" }), {
        headers: { 
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*"
        }
      });

    } catch (err) {
      console.error("Worker Error:", err.message);
      return new Response(JSON.stringify({ success: false, error: err.message }), { status: 500 });
    }
  }
}
