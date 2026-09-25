// src/worker.js - الكود المُصحَّح
// يكتب الإشارات مباشرة في Supabase pending_signals
// لا يحتاج إلى BOT_SERVER_URL أو INTERNAL_API_KEY بعد الآن

export default {
  async fetch(request, env, ctx) {
    // ✅ POST فقط
    if (request.method !== 'POST') {
      return new Response(
        JSON.stringify({ error: 'Method Not Allowed' }),
        { status: 405 }
      );
    }

    try {
      // 1. ✅ التحقق من WEBHOOK_SECRET
      const secret = request.headers.get('x-webhook-secret');
      if (!secret || secret !== env.WEBHOOK_SECRET) {
        return new Response(
          JSON.stringify({ error: 'Unauthorized' }),
          { status: 401 }
        );
      }

      const signal = await request.json();

      // 2. ✅ التحقق من صحة الإشارة
      if (!signal.symbol || !signal.side || !signal.action) {
        return new Response(
          JSON.stringify({ error: 'Invalid signal format' }),
          { status: 400 }
        );
      }

      // 3. ✅ كتابة الإشارة مباشرة في Supabase pending_signals
      const projectUrl = env.SUPABASE_URL;
      const apiKey = env.SUPABASE_ANON_KEY || env.SUPABASE_SERVICE_KEY;

      if (!projectUrl || !apiKey) {
        console.error('❌ Supabase env vars not configured (SUPABASE_URL, SUPABASE_ANON_KEY)');
        return new Response(
          JSON.stringify({ error: 'Server configuration error' }),
          { status: 500 }
        );
      }

      const payload = {
        symbol: signal.symbol,
        side: signal.side.toLowerCase(),
        action: signal.action.toUpperCase(),
        price: signal.price || null,
        webhook_id: signal.id || `wv-${Date.now()}`,
        status: 'pending',
      };

      const response = await fetch(
        `${projectUrl}/rest/v1/pending_signals`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'apikey': apiKey,
            'Prefer': 'return=minimal',
          },
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`❌ Supabase write failed: ${response.status} ${errorText}`);
        return new Response(
          JSON.stringify({ error: 'Failed to store signal' }),
          { status: 502 }
        );
      }

      // ✅ CORS محدود: فقط TradingView origin
      const allowedOrigin =
        env.TRADINGVIEW_ORIGIN || 'https://www.tradingview.com';

      return new Response(
        JSON.stringify({ success: true, message: 'Signal stored in Supabase' }),
        {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': allowedOrigin,
          }
        }
      );

    } catch (err) {
      // ✅ لا نكشف err.message للخارج
      console.error('Worker Error:', err.message);
      return new Response(
        JSON.stringify({ success: false, error: 'Internal error' }),
        { status: 500 }
      );
    }
  }
}
