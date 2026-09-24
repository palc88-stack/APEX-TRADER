import { useEffect, useMemo, useState } from "react";
import { createClient } from "@supabase/supabase-js";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  Clock3,
  LogOut,
  RefreshCw,
  ShieldAlert,
  Wallet,
} from "lucide-react";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const supabase = url && anonKey ? createClient(url, anonKey) : null;

const money = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n)
    ? new Intl.NumberFormat("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(n)
    : "—";
};

const dateTime = (value) => {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString("ar", { dateStyle: "medium", timeStyle: "short" });
};

function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    setBusy(false);
    if (error) setError("تعذر تسجيل الدخول. تحقق من البريد وكلمة المرور.");
    else onLogin();
  }

  return (
    <main className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand-mark">A</div>
        <p className="eyebrow">APEX TRADER</p>
        <h1>تسجيل الدخول</h1>
        <p className="muted">لوحة خاصة لمتابعة حالة البوت</p>

        <label>
          البريد الإلكتروني
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>

        <label>
          كلمة المرور
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error && <div className="error-banner">{error}</div>}
        <button className="primary-button" disabled={busy}>
          {busy ? "جارٍ التحقق..." : "دخول آمن"}
        </button>
      </form>
    </main>
  );
}

function Metric({ title, value, detail, icon: Icon, tone = "" }) {
  return (
    <article className={`metric ${tone}`}>
      <div className="metric-heading">
        <span>{title}</span>
        <span className="metric-icon"><Icon size={18} /></span>
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function ServiceRow({ title, value }) {
  const known = typeof value === "boolean";
  return (
    <div className="service-row">
      <i className={`dot ${value ? "ok" : known ? "bad" : "unknown"}`} />
      <span>{title}</span>
      <b>{value ? "متصل" : known ? "غير متصل" : "غير معروف"}</b>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState(null);
  const [status, setStatus] = useState(null);
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [resultFilter, setResultFilter] = useState("all");

  useEffect(() => {
    if (!supabase) {
      setError("متغيرات Supabase غير مضبوطة في إعدادات الواجهة.");
      setLoading(false);
      return;
    }

    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next);
    });

    return () => data.subscription.unsubscribe();
  }, []);

  async function loadData() {
    if (!supabase || !session) return;

    setError("");

    const [statusResult, tradesResult] = await Promise.all([
      supabase
        .from("bot_runtime_status")
        .select("*")
        .eq("id", 1)
        .maybeSingle(),

      supabase
        .from("trades")
        .select(
          "id,symbol,direction,mode,entry_price,exit_price,stop_loss," +
          "take_profit_1,take_profit_2,mark_price,quantity,size_usd," +
          "leverage,pnl,pnl_pct,unrealized_pnl,status,close_reason," +
          "opened_at,closed_at,duration_minutes"
        )
        .order("opened_at", { ascending: false })
        .limit(200),
    ]);

    if (statusResult.error || tradesResult.error) {
      setError(
        statusResult.error?.message ||
        tradesResult.error?.message ||
        "تعذر جلب البيانات من Supabase."
      );
    } else {
      setStatus(statusResult.data);
      setTrades(tradesResult.data || []);
    }

    setLoading(false);
  }

  useEffect(() => {
    if (!session || !supabase) return;

    loadData();

    const channel = supabase
      .channel("apex-dashboard")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "bot_runtime_status" },
        loadData
      )
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "trades" },
        loadData
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, [session]);

  const openTrades = useMemo(
    () => trades.filter((trade) => trade.status === "OPEN"),
    [trades]
  );

  const archive = useMemo(() => {
    const closed = trades.filter((trade) => trade.status !== "OPEN");

    return closed.filter((trade) => {
      const matchesSearch =
        !search ||
        String(trade.symbol || "").toLowerCase().includes(search.toLowerCase());

      const pnl = Number(trade.pnl || 0);
      const matchesResult =
        resultFilter === "all" ||
        (resultFilter === "wins" && pnl > 0) ||
        (resultFilter === "losses" && pnl < 0);

      return matchesSearch && matchesResult;
    });
  }, [trades, search, resultFilter]);

  if (!supabase) {
    return <main className="page"><div className="error-banner">{error}</div></main>;
  }

  if (loading && !session) {
    return <main className="page loading">جارٍ تجهيز لوحة APEX...</main>;
  }

  if (!session) return <Login onLogin={loadData} />;

  const heartbeat = status?.heartbeat_at
    ? new Date(status.heartbeat_at).getTime()
    : 0;
  const ageMinutes = heartbeat
    ? Math.max(0, Math.floor((Date.now() - heartbeat) / 60000))
    : null;
  const stale = ageMinutes === null || ageMinutes > 15;

  const limit = Number(status?.daily_loss_limit_usd);
  const used = Number(status?.daily_loss_used_usd);
  const remaining =
    Number.isFinite(limit) && Number.isFinite(used)
      ? Math.max(0, limit - used)
      : null;
  const lossPct =
    Number.isFinite(limit) && limit > 0 && Number.isFinite(used)
      ? Math.min(100, Math.max(0, (used / limit) * 100))
      : 0;

  const realized = Number(status?.daily_realized_pnl);
  const realizedTone =
    Number.isFinite(realized) && realized < 0 ? "negative" : "positive";

  return (
    <main className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark small">A</div>
          <div><b>APEX TRADER</b><span>لوحة متابعة التداول</span></div>
        </div>

        <div className="top-actions">
          <span className={`env ${status?.environment === "live" ? "live" : ""}`}>
            {status?.environment === "live" ? "LIVE" : "TESTNET"}
          </span>
          <span className={`freshness ${stale ? "stale" : "fresh"}`}>
            <i /> {stale ? "البيانات متأخرة" : "النبض حديث"}
          </span>
          <button className="icon-button" onClick={loadData} title="تحديث">
            <RefreshCw size={17} />
          </button>
          <button
            className="icon-button"
            onClick={() => supabase.auth.signOut()}
            title="تسجيل الخروج"
          >
            <LogOut size={17} />
          </button>
        </div>
      </header>

      <section className="heading">
        <div>
          <p className="eyebrow">نظرة عامة</p>
          <h1>حالة البوت والحساب</h1>
          <p className="muted">
            آخر نبضة: {dateTime(status?.heartbeat_at)}
            {ageMinutes !== null && ` · منذ ${ageMinutes} دقيقة`}
          </p>
        </div>
        <span className={`bot-status ${status?.bot_status === "running" ? "running" : ""}`}>
          <i /> {status?.bot_status || "غير معروف"}
        </span>
      </section>

      {error && <div className="error-banner"><Bell size={17} />{error}</div>}
      {status?.environment === "live" && (
        <div className="warning-banner">
          تنبيه: هذه لوحة متابعة وليست وسيلة حماية أو تنفيذ أوامر.
        </div>
      )}

      <section className="metrics">
        <Metric
          title="الرصيد المتاح"
          value={status?.available_balance == null
            ? "—"
            : `$${money(status.available_balance)}`}
          detail="USDT · آخر قيمة أبلغ بها البوت"
          icon={Wallet}
        />
        <Metric
          title="الأرباح المحققة اليوم"
          value={status?.daily_realized_pnl == null
            ? "—"
            : `$${money(status.daily_realized_pnl)}`}
          detail="للصفقات المغلقة المسجلة"
          icon={realized >= 0 ? ArrowUpRight : ArrowDownRight}
          tone={status?.daily_realized_pnl == null ? "" : realizedTone}
        />
        <Metric
          title="الربح/الخسارة العائمة"
          value={status?.daily_unrealized_pnl == null
            ? "—"
            : `$${money(status.daily_unrealized_pnl)}`}
          detail="للمراكز المفتوحة حسب آخر مزامنة"
          icon={Activity}
        />
        <Metric
          title="هامش الخسارة المتبقي"
          value={remaining == null ? "—" : `$${money(remaining)}`}
          detail={limit > 0 ? `من حد يومي $${money(limit)}` : "بانتظار بيانات حد الخسارة"}
          icon={ShieldAlert}
          tone={lossPct >= 75 ? "negative" : ""}
        />
      </section>

      <section className="columns">
        <article className="panel">
          <div className="panel-title">
            <div><h2>المراكز المفتوحة</h2><p className="muted">حسب آخر بيانات محفوظة</p></div>
            <span className="count">{openTrades.length}</span>
          </div>

          {!openTrades.length ? (
            <div className="empty">لا توجد مراكز مفتوحة مسجلة.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>العملة</th><th>الاتجاه</th><th>الدخول</th>
                    <th>السعر</th><th>وقف الخسارة</th><th>الرافعة</th><th>P&amp;L عائم</th>
                  </tr>
                </thead>
                <tbody>
                  {openTrades.map((t) => (
                    <tr key={t.id}>
                      <td><b>{t.symbol}</b></td>
                      <td><span className={`side ${t.direction === "LONG" ? "long" : "short"}`}>{t.direction || "—"}</span></td>
                      <td>${money(t.entry_price)}</td>
                      <td>{t.mark_price == null ? "—" : `$${money(t.mark_price)}`}</td>
                      <td>{t.stop_loss == null ? "—" : `$${money(t.stop_loss)}`}</td>
                      <td>{t.leverage == null ? "—" : `${t.leverage}x`}</td>
                      <td>{t.unrealized_pnl == null ? "—" : `$${money(t.unrealized_pnl)}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel services">
          <div className="panel-title">
            <div><h2>حالة الخدمات</h2><p className="muted">حسب آخر تقرير من البوت</p></div>
          </div>
          <ServiceRow title="Binance" value={status?.exchange_connected} />
          <ServiceRow title="Supabase" value={status?.database_connected} />
          <ServiceRow title="Redis" value={status?.redis_connected} />
          <div className="cycle">
            <Clock3 size={16} />
            <span>آخر دورة مكتملة</span>
            <b>{dateTime(status?.cycle_completed_at)}</b>
          </div>
          {status?.last_error && <div className="last-error">{status.last_error}</div>}
        </article>
      </section>

      <section className="panel archive">
        <div className="panel-title archive-head">
          <div><h2>أرشيف الصفقات</h2><p className="muted">آخر 200 سجل صفقة</p></div>
          <div className="filters">
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="بحث بالعملة..."
              aria-label="بحث بالعملة"
            />
            <select value={resultFilter} onChange={(e) => setResultFilter(e.target.value)}>
              <option value="all">كل النتائج</option>
              <option value="wins">رابحة</option>
              <option value="losses">خاسرة</option>
            </select>
          </div>
        </div>

        {!archive.length ? (
          <div className="empty">لا توجد صفقات مغلقة مطابقة.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>العملة</th><th>الاتجاه</th><th>الدخول</th>
                  <th>الخروج</th><th>النتيجة</th><th>سبب الإغلاق</th><th>وقت الإغلاق</th>
                </tr>
              </thead>
              <tbody>
                {archive.map((t) => (
                  <tr key={t.id}>
                    <td><b>{t.symbol}</b></td>
                    <td>{t.direction || "—"}</td>
                    <td>${money(t.entry_price)}</td>
                    <td>{t.exit_price == null ? "—" : `$${money(t.exit_price)}`}</td>
                    <td className={Number(t.pnl) >= 0 ? "text-positive" : "text-negative"}>
                      {t.pnl == null ? "—" : `$${money(t.pnl)}`}
                    </td>
                    <td>{t.close_reason || t.status || "—"}</td>
                    <td>{dateTime(t.closed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <footer className="footer">
        البيانات المعروضة هي آخر بيانات حفظها البوت؛ حداثتها مرتبطة بتكرار تشغيله ونجاح المزامنة.
      </footer>
    </main>
  );
}

function ServiceRow({ title, value }) {
  const known = typeof value === "boolean";
  return (
    <div className="service-row">
      <i className={`dot ${value ? "ok" : known ? "bad" : "unknown"}`} />
      <span>{title}</span>
      <b>{value ? "متصل" : known ? "غير متصل" : "غير معروف"}</b>
    </div>
  );
}
