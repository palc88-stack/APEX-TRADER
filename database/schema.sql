-- database/schema.sql - bot_state المُحسَّن
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

|-- ===== جدول pending_signals (للاستقبال من Cloudflare Worker) =====
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
