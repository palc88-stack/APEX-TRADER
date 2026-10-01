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
    bot_status VARCHAR(20) DEFAULT 'stopped',
    environment VARCHAR(20) DEFAULT 'testnet',
    heartbeat_at TIMESTAMPTZ,
    cycle_completed_at TIMESTAMPTZ,
    exchange_connected BOOLEAN,
    database_connected BOOLEAN,
    redis_connected BOOLEAN,
    daily_loss DECIMAL(10, 4) DEFAULT 0,

    -- الإحصاءات
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,

    -- ✅ إضافة: المالية والوضع الحالي
    current_balance DECIMAL(10, 4) DEFAULT 0,
    available_balance DECIMAL(10, 4),
    daily_unrealized_pnl DECIMAL(10, 4),
    active_mode VARCHAR(20) DEFAULT 'HUNTER',
    active_symbols TEXT DEFAULT '[]',      -- JSON array

    -- ✅ إضافة: مراقبة الأخطاء
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    reconciliation_alert_key TEXT,
    reconciliation_alerted_at TIMESTAMPTZ,

    -- ✅ إضافة: الخسائر والربح اليومي
    daily_loss_limit_usd DECIMAL(10, 2) DEFAULT 100.00,
    daily_loss_used_usd DECIMAL(10, 2) DEFAULT 0.00,
    daily_realized_pnl DECIMAL(10, 2) DEFAULT 0.00,
    risk_day DATE,

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
    ADD COLUMN IF NOT EXISTS reconciliation_alert_key TEXT;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS reconciliation_alerted_at TIMESTAMPTZ;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS daily_loss_limit_usd DECIMAL(10, 2) DEFAULT 100.00;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS daily_loss_used_usd DECIMAL(10, 2) DEFAULT 0.00;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS daily_realized_pnl DECIMAL(10, 2) DEFAULT 0.00;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS risk_day DATE;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS bot_status VARCHAR(20) DEFAULT 'stopped';
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS environment VARCHAR(20) DEFAULT 'testnet';
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS cycle_completed_at TIMESTAMPTZ;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS exchange_connected BOOLEAN;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS database_connected BOOLEAN;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS redis_connected BOOLEAN;
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS available_balance DECIMAL(10, 4);
ALTER TABLE bot_state
    ADD COLUMN IF NOT EXISTS daily_unrealized_pnl DECIMAL(10, 4);

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
    strategy VARCHAR(40),
    signal_confidence DECIMAL(6, 4),
    signal_reason TEXT,
    exchange VARCHAR(20) DEFAULT 'binance',
    source VARCHAR(20) DEFAULT 'engine',        -- 'engine' أو 'webhook'

    entry_price DECIMAL(18, 8) NOT NULL,
    entry_order_id TEXT,
    entry_client_order_id TEXT,
    stop_algo_id TEXT,
    take_profit_algo_id TEXT,
    take_profit_1_algo_id TEXT,
    take_profit_2_algo_id TEXT,
    closing_order_id TEXT,
    entry_price_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    entry_quantity_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    entry_fee_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    exit_price_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    exit_quantity_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    exit_fee_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    pnl_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    reconciliation_note TEXT,
    exit_price DECIMAL(18, 8),
    stop_loss DECIMAL(18, 8),
    take_profit_1 DECIMAL(18, 8),
    take_profit_2 DECIMAL(18, 8),
    strategy_subtype VARCHAR(80),
    rule_score DECIMAL(6, 4),
    account_balance_at_entry DECIMAL(18, 8),
    pnl_account_pct DECIMAL(10, 4),
    entry_fee_currency VARCHAR(20),
    exit_fee_currency VARCHAR(20),
    entry_filled_at TIMESTAMPTZ,
    exit_filled_at TIMESTAMPTZ,
    entry_slippage_bps DECIMAL(18, 8),
    exit_slippage_bps DECIMAL(18, 8),
    entry_mark_price DECIMAL(30, 12),
    exit_mark_price DECIMAL(30, 12),
    entry_trigger_price DECIMAL(30, 12),
    exit_trigger_price DECIMAL(30, 12),

    size_usd DECIMAL(18, 4) NOT NULL,
    margin_usd DECIMAL(18, 4),
    notional_usd DECIMAL(18, 4),
    entry_quantity DECIMAL(18, 8),
    remaining_quantity DECIMAL(18, 8),
    leverage INTEGER DEFAULT 10,

    entry_fee DECIMAL(18, 8) DEFAULT 0,
    exit_fee DECIMAL(18, 8) DEFAULT 0,

    confidence DECIMAL(5, 4) DEFAULT 0,

    status VARCHAR(20) DEFAULT 'OPEN',          -- OPEN | CLOSED | NEEDS_RECONCILIATION
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

-- Existing deployments may have created this key as varchar(8); exchange order
-- IDs are longer, so widen it without changing existing values.
ALTER TABLE trades ALTER COLUMN id TYPE TEXT USING id::text;

ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_pnl_check;
ALTER TABLE trades ADD CONSTRAINT trades_pnl_check
    CHECK (status IN ('OPEN', 'NEEDS_RECONCILIATION', 'RECONCILED_FLAT') OR pnl IS NOT NULL) NOT VALID;

ALTER TABLE trades ADD COLUMN IF NOT EXISTS margin_usd DECIMAL(18, 4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS notional_usd DECIMAL(18, 4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_quantity DECIMAL(18, 8);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS remaining_quantity DECIMAL(18, 8);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS take_profit_1_algo_id TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS take_profit_2_algo_id TEXT;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS strategy_subtype VARCHAR(80);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS rule_score DECIMAL(6, 4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS account_balance_at_entry DECIMAL(18, 8);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS pnl_account_pct DECIMAL(10, 4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_fee_currency VARCHAR(20);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_fee_currency VARCHAR(20);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_filled_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_filled_at TIMESTAMPTZ;
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_slippage_bps DECIMAL(18, 8);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_slippage_bps DECIMAL(18, 8);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_mark_price DECIMAL(30, 12);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_mark_price DECIMAL(30, 12);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_trigger_price DECIMAL(30, 12);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_trigger_price DECIMAL(30, 12);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_quantity DECIMAL(18, 8);

-- فهارس لتسريع الاستعلامات المتكررة فعلياً في الكود:
-- state_manager.get_open_trades_from_db() → .eq("status","OPEN")
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status);
-- App.jsx → .order("opened_at", {ascending:false}).limit(200)
CREATE INDEX IF NOT EXISTS idx_trades_opened_at ON trades (opened_at DESC);
-- main.py → فلترة الصفقات المفتوحة حسب الرمز في كل دورة
CREATE INDEX IF NOT EXISTS idx_trades_symbol_status ON trades (symbol, status);

CREATE TABLE IF NOT EXISTS partial_closes (
    id BIGSERIAL PRIMARY KEY,
    trade_id TEXT NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    reason VARCHAR(30) NOT NULL,
    price DECIMAL(18, 8),
    amount_closed DECIMAL(18, 8),
    pnl DECIMAL(18, 4),
    fee DECIMAL(18, 8),
    price_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    quantity_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    fee_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    pnl_source VARCHAR(40) NOT NULL DEFAULT 'unconfirmed',
    exchange_order_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_partial_closes_trade_id
    ON partial_closes (trade_id, created_at DESC);
ALTER TABLE trades DROP CONSTRAINT IF EXISTS trades_status_check;
ALTER TABLE trades ADD CONSTRAINT trades_status_check
    CHECK (status IN ('OPEN', 'CLOSED', 'NEEDS_RECONCILIATION', 'RECONCILED_FLAT'));
ALTER TABLE partial_closes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS authenticated_read_partial_closes ON partial_closes;
CREATE POLICY authenticated_read_partial_closes ON partial_closes
    FOR SELECT TO authenticated USING (true);
REVOKE ALL ON TABLE partial_closes FROM anon, authenticated;
GRANT SELECT ON TABLE partial_closes TO authenticated;

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
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT SELECT ON TABLE bot_state, trades TO authenticated;
REVOKE INSERT, UPDATE, DELETE ON TABLE bot_state, trades FROM authenticated;

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
