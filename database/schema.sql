-- ======================================
-- APEX TRADER - Database Schema
-- ======================================
-- هيكل قاعدة بيانات Supabase

-- ===== جدول الصفقات =====
CREATE TABLE IF NOT EXISTS trades (
    id VARCHAR(8) PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(5) NOT NULL CHECK (direction IN ('LONG', 'SHORT')),
    exchange VARCHAR(20) NOT NULL,
    mode VARCHAR(10) NOT NULL,
    
    -- الأسعار
    entry_price DECIMAL(20, 8) NOT NULL,
    exit_price DECIMAL(20, 8),
    stop_loss DECIMAL(20, 8),
    take_profit_1 DECIMAL(20, 8),
    take_profit_2 DECIMAL(20, 8),
    
    -- الحجم
    size_usd DECIMAL(10, 4) NOT NULL,
    leverage INTEGER NOT NULL,
    position_value DECIMAL(10, 4),
    
    -- العمولات
    entry_fee DECIMAL(10, 6) DEFAULT 0,
    exit_fee DECIMAL(10, 6) DEFAULT 0,
    total_fees DECIMAL(10, 6) DEFAULT 0,
    
    -- الإشارة
    confidence DECIMAL(4, 3),
    signal_reasons JSONB,
    is_explosion BOOLEAN DEFAULT FALSE,
    
    -- النتيجة
    status VARCHAR(20) DEFAULT 'OPEN',
    pnl DECIMAL(10, 6),
    pnl_pct DECIMAL(8, 4),
    close_reason VARCHAR(30),
    
    -- التوقيت
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    duration_minutes DECIMAL(8, 2),
    
    -- الفهارس
    CONSTRAINT trades_pnl_check CHECK (
        status = 'OPEN' OR pnl IS NOT NULL
    )
);

-- ===== جدول الأداء اليومي =====
CREATE TABLE IF NOT EXISTS daily_performance (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE NOT NULL,
    
    -- الإحصاءات
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate DECIMAL(5, 2),
    
    -- المال
    gross_pnl DECIMAL(10, 4) DEFAULT 0,
    total_fees DECIMAL(10, 4) DEFAULT 0,
    net_pnl DECIMAL(10, 4) DEFAULT 0,
    
    -- الرصيد
    starting_balance DECIMAL(10, 4),
    ending_balance DECIMAL(10, 4),
    
    -- Compounding
    compounded_amount DECIMAL(10, 4) DEFAULT 0,
    reserved_amount DECIMAL(10, 4) DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== جدول حالة البوت =====
CREATE TABLE IF NOT EXISTS bot_state (
    id INTEGER PRIMARY KEY DEFAULT 1,
    
    -- الحالة
    is_running BOOLEAN DEFAULT FALSE,
    is_paused BOOLEAN DEFAULT FALSE,
    daily_loss DECIMAL(10, 4) DEFAULT 0,
    
    -- الإحصاءات
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    
    -- آخر تحديث
    last_run_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- قيد: صف واحد فقط
    CONSTRAINT single_row CHECK (id = 1)
);

-- إدراج الصف الأولي
INSERT INTO bot_state (id) VALUES (1)
ON CONFLICT (id) DO NOTHING;

-- ===== جدول السجلات =====
CREATE TABLE IF NOT EXISTS system_logs (
    id SERIAL PRIMARY KEY,
    level VARCHAR(10) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ===== الفهارس لتسريع الاستعلامات =====
CREATE INDEX IF NOT EXISTS idx_trades_symbol 
    ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status 
    ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_opened_at 
    ON trades(opened_at DESC);
CREATE INDEX IF NOT EXISTS idx_daily_perf_date 
    ON daily_performance(date DESC);

-- ===== دالة تحديث التوقيت =====
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger للتحديث التلقائي
CREATE TRIGGER update_daily_performance_updated_at
    BEFORE UPDATE ON daily_performance
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
