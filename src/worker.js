// src/worker.js - الكود المُصحَّح
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

      // 3. ✅ تمرير الإشارة للسيرفر
      const botResponse = await fetch(
        env.BOT_SERVER_URL + '/webhook',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${env.INTERNAL_API_KEY}`
          },
          body: JSON.stringify(signal)
        }
      );

      if (!botResponse.ok) {
        // ✅ لا نكشف تفاصيل خطأ السيرفر
        console.error(`Bot server error: ${botResponse.status}`);
        return new Response(
          JSON.stringify({ error: 'Signal processing failed' }),
          { status: 502 }
        );
      }

      // ✅ CORS محدود: فقط TradingView origin
      const allowedOrigin =
        env.TRADINGVIEW_ORIGIN || 'https://www.tradingview.com';

      return new Response(
        JSON.stringify({ success: true, message: 'Signal received' }),
        {
          headers: {
            'Content-Type': 'application/json',
            // ✅ CORS محدود بدلاً من *
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
