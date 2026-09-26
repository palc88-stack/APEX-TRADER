-- database/schema.sql - الكود المُصحَّح
-- ═══════════════════════════════════════════════════════════════════════
-- ✅ إصلاح خلل حرج #1 (مؤكَّد بالقراءة المباشرة): كان السطر يبدأ بـ "|--"
--    بدلاً من "--" قبل تعريف جدول pending_signals. هذا الحرف "|" ليس جزءاً
--    من صيغة SQL الصحيحة، وإذا نُفِّذ هذا الملف كسكربت واحد (وهو الاستخدام
--    الشائع في محرر SQL الخاص بـ Supabase)، سيتوقف التنفيذ عند هذا السطر
--    بخطأ Syntax Error، ولن يُنشأ جدول pending_signals إطلاقاً — أي أن كل
--    مسار إشارات TradingView/webhook سيفشل بالكامل من قاعدته.
--
-- ✅ إصلاح خلل حرج #2 (مؤكَّد بالبحث الشامل grep في كامل الريبو): جدول
--    "trades" غير معرَّف إطلاقاً في أي مكان بالمشروع، رغم أن bot/main.py
--    وbot/data/state_manager.py وweb/src/App.jsx (لوحة المتابعة) تعتمد
--    عليه بشكل كامل لحفظ/قراءة كل الصفقات. بدون هذا الجدول:
--      - save_trade_state() تفشل بصمت في كل مرة (يُلتقط الخطأ ويُسجَّل فقط)
--      - لا تُحفظ أي صفقة إطلاقاً، ولا يمكن استعادة المراكز بعد إعادة التشغيل
--      - لوحة المتابعة (App.jsx) تعرض خطأ "الصفقات: relation trades does not
--        exist" ولا تُظهر أي بيانات أبداً.
--    تم بناء الأعمدة أدناه بمطابقة تامة لكل حقل يُستخدم فعلياً في:
--      bot/main.py (trade_record في الفتح والإغلاق والـ webhook)
--      web/src/App.jsx (استعلام SELECT الخاص بالصفقات، بما فيها "mode"
--        و"duration_minutes" اللذان تم أيضاً إصلاح حفظهما في main.py).
-- ═══════════════════════════════════════════════════════════════════════

-- ===== جدول حالة البوت (مُحسَّن) =====
CREATE TABLE IF NOT EXISTS bot_state (
    id INTEGER PRIMARY KEY DEFAULT 1,

    -- الحالة
    is_running BOOLEAN DEFAULT FALSE,
    is_paused BOOLEAN DEFAULT FALSE,
    daily_loss DECIMAL(10, 4) DEFAULT 0,

    -- الإحصاءات
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,

    -- ✅ إضافة: المالية والوضع الحالي
    current_balance DECIMAL(10, 4) DEFAULT 0,
    active_mode VARCHAR(20) DEFAULT 'HUNTER',
    active_symbols TEXT DEFAULT '[]',      -- JSON array

    -- ✅ إضافة: مراقبة الأخطاء
    error_count INTEGER DEFAULT 0,
    last_error TEXT,

    -- ✅ إضافة: الخسائر والربح اليومي
    daily_loss_limit_usd DECIMAL(10, 2) DEFAULT 100.00,
    daily_loss_used_usd DECIMAL(10, 2) DEFAULT 0.00,
    daily_realized_pnl DECIMAL(10, 2) DEFAULT 0.00,

    -- التوقيت
    last_run_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- قيد: صف واحد فقط
    CONSTRAINT single_row CHECK (id = 1)
);

INSERT INTO bot_state (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- ✅ Migration لقواعد بيانات موجودة
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS current_balance DECIMAL(10, 4) DEFAULT 0;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS active_mode VARCHAR(20) DEFAULT 'HUNTER';
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS active_symbols TEXT DEFAULT '[]';
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS error_count INTEGER DEFAULT 0;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS daily_loss_limit_usd DECIMAL(10, 2) DEFAULT 100.00;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS daily_loss_used_usd DECIMAL(10, 2) DEFAULT 0.00;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS daily_realized_pnl DECIMAL(10, 2) DEFAULT 0.00;

-- ===== جدول pending_signals (للاستقبال من Cloudflare Worker) =====
-- ✅ تم إصلاح "|--" → "--" (كانت هذه هي نقطة توقف تنفيذ السكربت بالكامل)
CREATE TABLE IF NOT EXISTS pending_signals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,
    price DECIMAL(18, 8),
    webhook_id VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS symbol VARCHAR(20) NOT NULL;
ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS side VARCHAR(10) NOT NULL;
ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS action VARCHAR(10) NOT NULL;
ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS price DECIMAL(18, 8);
ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS webhook_id VARCHAR(100);
ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending';
ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;

-- فهرس لتسريع get_pending_signals() في state_manager.py (يستعلم status='pending')
CREATE INDEX IF NOT EXISTS idx_pending_signals_status
    ON pending_signals (status, created_at);

-- ═══════════════════════════════════════════════════════════════════════
-- ===== جدول trades (مفقود بالكامل سابقاً — أُضيف هنا) =====
-- ═══════════════════════════════════════════════════════════════════════
-- ملاحظة: "id" نصي (TEXT) وليس رقمياً لأن الكود يحفظ فيه أحياناً معرّف
-- الأمر من المنصة (order id من ccxt، وقد يكون نصياً)، وأحياناً معرّفاً
-- مولَّداً محلياً بصيغة "web-<timestamp>" في مسار الـ webhook
-- (راجع bot/main.py: handle_webhook_signal).
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL,             -- LONG | SHORT
    mode VARCHAR(20),                           -- ✅ تُقرأ من App.jsx SELECT
    exchange VARCHAR(20) DEFAULT 'binance',
    source VARCHAR(20) DEFAULT 'engine',        -- 'engine' أو 'webhook'

    entry_price DECIMAL(18, 8) NOT NULL,
    exit_price DECIMAL(18, 8),
    stop_loss DECIMAL(18, 8),
    take_profit_1 DECIMAL(18, 8),
    take_profit_2 DECIMAL(18, 8),

    size_usd DECIMAL(18, 4) NOT NULL,
    leverage INTEGER DEFAULT 10,

    entry_fee DECIMAL(18, 8) DEFAULT 0,
    exit_fee DECIMAL(18, 8) DEFAULT 0,

    confidence DECIMAL(5, 4) DEFAULT 0,

    status VARCHAR(20) DEFAULT 'OPEN',          -- OPEN | CLOSED
    close_reason VARCHAR(30),                   -- tp1 | tp2 | stop_loss | trailing_stop | manual

    pnl DECIMAL(18, 4) DEFAULT 0,
    pnl_pct DECIMAL(10, 4) DEFAULT 0,
    duration_minutes DECIMAL(10, 2),            -- ✅ تُقرأ من App.jsx SELECT

    -- حقول متابعة Trailing/Break-even/Partial-TP لاستعادة الحالة بعد إعادة التشغيل
    tp1_executed BOOLEAN DEFAULT FALSE,
    trailing_active BOOLEAN DEFAULT FALSE,
    trailing_stop DECIMAL(18, 8) DEFAULT 0,
    breakeven_set BOOLEAN DEFAULT FALSE,
    highest_price DECIMAL(18, 8),
    lowest_price DECIMAL(18, 8),

    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);

-- فهارس لتسريع الاستعلامات المتكررة فعلياً في الكود:
-- state_manager.get_open_trades_from_db() → .eq("status","OPEN")
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
-- App.jsx → .order("opened_at", {ascending:false}).limit(200)
CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades (opened_at DESC);
-- main.py → فلترة الصفقات المفتوحة حسب الرمز في كل دورة
CREATE INDEX IF NOT EXISTS idx_trades_symbol_status ON trades (symbol, status);

-- ===== Idempotency, bounded state transitions, and RLS =====
ALTER TABLE pending_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_state ENABLE ROW LEVEL SECURITY;

ALTER TABLE pending_signals
    ADD COLUMN IF NOT EXISTS processing_owner TEXT,
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_error TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_signals_webhook_id
    ON pending_signals (webhook_id) WHERE webhook_id IS NOT NULL;

ALTER TABLE pending_signals DROP CONSTRAINT IF EXISTS pending_signals_status_check;
ALTER TABLE pending_signals ADD CONSTRAINT pending_signals_status_check
    CHECK (status IN ('pending', 'processing', 'processed', 'failed'));
ALTER TABLE pending_signals DROP CONSTRAINT IF EXISTS pending_signals_side_check;
ALTER TABLE pending_signals ADD CONSTRAINT pending_signals_side_check
    CHECK (lower(side) IN ('buy', 'sell'));
ALTER TABLE pending_signals DROP CONSTRAINT IF EXISTS pending_signals_action_check;
ALTER TABLE pending_signals ADD CONSTRAINT pending_signals_action_check
    CHECK (upper(action) IN ('BUY', 'SELL', 'LONG', 'SHORT'));
ALTER TABLE pending_signals DROP CONSTRAINT IF EXISTS pending_signals_price_check;
ALTER TABLE pending_signals ADD CONSTRAINT pending_signals_price_check
    CHECK (price IS NULL OR price > 0);

DROP POLICY IF EXISTS authenticated_read_bot_state ON bot_state;
CREATE POLICY authenticated_read_bot_state ON bot_state
    FOR SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS authenticated_read_trades ON trades;
CREATE POLICY authenticated_read_trades ON trades
    FOR SELECT TO authenticated USING (true);

REVOKE ALL ON TABLE pending_signals FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON TABLE bot_state FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON TABLE trades FROM anon, authenticated;

CREATE OR REPLACE FUNCTION public.claim_pending_signal(p_signal_id INTEGER, p_owner TEXT)
RETURNS SETOF public.pending_signals
LANGUAGE sql SECURITY DEFINER SET search_path = public
AS $$
    UPDATE public.pending_signals
       SET status = 'processing',
           processing_owner = p_owner,
           processing_started_at = now(),
           attempt_count = attempt_count + 1
     WHERE id = p_signal_id
       AND (status = 'pending'
            OR (status = 'processing' AND processing_started_at < now() - interval '10 minutes'))
    RETURNING *;
$$;

REVOKE ALL ON FUNCTION public.claim_pending_signal(INTEGER, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_pending_signal(INTEGER, TEXT) TO service_role;
