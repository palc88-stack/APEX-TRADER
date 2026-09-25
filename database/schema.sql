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

-- ===== باقي الجداول بدون تغيير =====
-- (trades, daily_performance, system_logs - كما هي)
