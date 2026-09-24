import { useCallback, useEffect, useMemo, useState } from "react";
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

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

const supabase =
  supabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey)
    : null;

function formatMoney(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number);
}

function formatDate(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  return date.toLocaleString("ar", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    const { error: signInError } =
      await supabase.auth.signInWithPassword({
        email,
        password,
      });

    setBusy(false);

    if (signInError) {
      setError("تعذر تسجيل الدخول. تحقق من البريد وكلمة المرور.");
    }
  }

  return (
    <main className="login-wrap">
      <form className="login-card" onSubmit={handleSubmit}>
        <div className="brand-mark">A</div>
        <p className="eyebrow">APEX TRADER</p>
        <h1>تسجيل الدخول</h1>
        <p className="muted">لوحة متابعة خاصة بالمصرح لهم</p>

        <label>
          البريد الإلكتروني
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>

        <label>
          كلمة المرور
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>

        {error && <div className="error-banner">{error}</div>}

        <button className="primary-button" disabled={busy} type="submit">
          {busy ? "جارٍ التحقق..." : "دخول آمن"}
        </button>
      </form>
    </main>
  );
}

function MetricCard({ title, value, detail, icon: Icon, tone = "" }) {
  return (
    <article className={`metric ${tone}`}>
      <div className="metric-heading">
        <span>{title}</span>
        <span className="metric-icon">
          <Icon size={18} />
        </span>
      </div>

      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function ServiceRow({ title, value }) {
  const known = typeof value === "boolean";

  let statusText = "غير معروف";
  let dotClass = "unknown";

  if (value === true) {
    statusText = "متصل";
    dotClass = "ok";
  } else if (known) {
    statusText = "غير متصل";
    dotClass = "bad";
  }

  return (
    <div className="service-row">
      <i className={`dot ${dotClass}`} />
      <span>{title}</span>
      <b>{statusText}</b>
    </div>
  );
}

function Dashboard() {
  const [status, setStatus] = useState(null);
  const [trades, setTrades] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [resultFilter, setResultFilter] = useState("all");
  const [now, setNow] = useState(Date.now());

  const loadData = useCallback(async () => {
    if (!supabase) {
      return;
    }

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
            "take_profit_1,take_profit_2,size_usd,leverage,pnl,pnl_pct," +
            "status,close_reason,opened_at,closed_at,duration_minutes"
        )
        .order("opened_at", { ascending: false })
        .limit(200),
    ]);

    const errors = [];

    if (statusResult.error) {
      setStatus(null);
      errors.push(`حالة البوت: ${statusResult.error.message}`);
    } else {
      setStatus(statusResult.data);
    }

    if (tradesResult.error) {
      setTrades([]);
      errors.push(`الصفقات: ${tradesResult.error.message}`);
    } else {
      setTrades(tradesResult.data || []);
    }

    setError(errors.join(" · "));
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();

    const channel = supabase
      .channel("apex-dashboard-updates")
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "bot_runtime_status",
        },
        loadData
      )
      .on(
        "postgres_changes",
        {
          event: "*",
          schema: "public",
          table: "trades",
        },
        loadData
      )
      .subscribe();

    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 30000);

    return () => {
      window.clearInterval(timer);
      supabase.removeChannel(channel);
    };
  }, [loadData]);

  const openTrades = useMemo(
    () => trades.filter((trade) => trade.status === "OPEN"),
    [trades]
  );

  const archivedTrades = useMemo(() => {
    const closedTrades = trades.filter(
      (trade) => trade.status !== "OPEN"
    );

    return closedTrades.filter((trade) => {
      const symbol = String(trade.symbol || "").toLowerCase();
      const matchesSearch =
        search.length === 0 || symbol.includes(search.toLowerCase());

      const pnl = Number(trade.pnl || 0);

      let matchesResult = true;

      if (resultFilter === "wins") {
        matchesResult = pnl > 0;
      } else if (resultFilter === "losses") {
        matchesResult = pnl < 0;
      }

      return matchesSearch && matchesResult;
    });
  }, [trades, search, resultFilter]);

  if (loading) {
    return <main className="page loading">جارٍ تحميل لوحة APEX...</main>;
  }

  const heartbeatTimestamp = status?.heartbeat_at
    ? new Date(status.heartbeat_at).getTime()
    : null;

  const heartbeatAgeMinutes =
    heartbeatTimestamp === null
      ? null
      : Math.max(0, Math.floor((now - heartbeatTimestamp) / 60000));

  const stale =
    heartbeatAgeMinutes === null || heartbeatAgeMinutes > 15;

  const lossLimit = Number(status?.daily_loss_limit_usd);
  const lossUsed = Number(status?.daily_loss_used_usd);

  const remainingLoss =
    Number.isFinite(lossLimit) && Number.isFinite(lossUsed)
      ? Math.max(0, lossLimit - lossUsed)
      : null;

  const lossPercent =
    Number.isFinite(lossLimit) &&
    lossLimit > 0 &&
    Number.isFinite(lossUsed)
      ? Math.min(100, Math.max(0, (lossUsed / lossLimit) * 100))
      : 0;

  const realizedPnl = Number(status?.daily_realized_pnl);
  const realizedTone =
    Number.isFinite(realizedPnl) && realizedPnl < 0
      ? "negative"
      : "positive";

  return (
    <main className="page">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark small">A</div>
          <div>
            <b>APEX TRADER</b>
            <span>لوحة متابعة التداول</span>
          </div>
        </div>

        <div className="top-actions">
          <span
            className={`env ${
              status?.environment === "live" ? "live" : ""
            }`}
          >
            {status?.environment === "live" ? "LIVE" : "TESTNET"}
          </span>

          <span className={`freshness ${stale ? "stale" : "fresh"}`}>
            <i />
            {stale ? "البيانات متأخرة" : "النبض حديث"}
          </span>

          <button
            className="icon-button"
            onClick={loadData}
            title="تحديث البيانات"
            type="button"
          >
            <RefreshCw size={17} />
          </button>

          <button
            className="icon-button"
            onClick={() => supabase.auth.signOut()}
            title="تسجيل الخروج"
            type="button"
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
            آخر نبضة: {formatDate(status?.heartbeat_at)}
            {heartbeatAgeMinutes !== null &&
              ` · منذ ${heartbeatAgeMinutes} دقيقة`}
          </p>
        </div>

        <span
          className={`bot-status ${
            status?.bot_status === "running" ? "running" : ""
          }`}
        >
          <i />
          {status?.bot_status || "غير معروف"}
        </span>
      </section>

      {error && (
        <div className="error-banner">
          <Bell size={17} />
          <span>{error}</span>
        </div>
      )}

      {status?.environment === "live" && (
        <div className="warning-banner">
          تنبيه: هذه لوحة متابعة وليست وسيلة حماية أو تنفيذ أوامر.
        </div>
      )}

      <section className="metrics">
        <MetricCard
          title="الرصيد المتاح"
          value={
            status?.available_balance == null
              ? "—"
              : `$${formatMoney(status.available_balance)}`
          }
          detail="USDT · آخر قيمة أبلغ بها البوت"
          icon={Wallet}
        />

        <MetricCard
          title="الأرباح المحققة اليوم"
          value={
            status?.daily_realized_pnl == null
              ? "—"
              : `$${formatMoney(status.daily_realized_pnl)}`
          }
          detail="للصفقات المغلقة المسجلة"
          icon={realizedPnl < 0 ? ArrowDownRight : ArrowUpRight}
          tone={
            status?.daily_realized_pnl == null ? "" : realizedTone
          }
        />

        <MetricCard
          title="الربح/الخسارة العائمة"
          value={
            status?.daily_unrealized_pnl == null
              ? "—"
              : `$${formatMoney(status.daily_unrealized_pnl)}`
          }
          detail="للمراكز المفتوحة حسب آخر مزامنة"
          icon={Activity}
        />

        <MetricCard
          title="هامش الخسارة المتبقي"
          value={
            remainingLoss === null
              ? "—"
              : `$${formatMoney(remainingLoss)}`
          }
          detail={
            lossLimit > 0
              ? `من حد يومي $${formatMoney(lossLimit)}`
              : "بانتظار بيانات حد الخسارة"
          }
          icon={ShieldAlert}
          tone={lossPercent >= 75 ? "negative" : ""}
        />
      </section>

      <section className="columns">
        <article className="panel">
          <div className="panel-title">
            <div>
              <h2>المراكز المفتوحة</h2>
              <p className="muted">حسب آخر بيانات محفوظة</p>
            </div>
            <span className="count">{openTrades.length}</span>
          </div>

          {openTrades.length === 0 ? (
            <div className="empty">
              لا توجد مراكز مفتوحة مسجلة في قاعدة البيانات.
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>العملة</th>
                    <th>الاتجاه</th>
                    <th>الدخول</th>
                    <th>وقف الخسارة</th>
                    <th>الرافعة</th>
                    <th>الربح/الخسارة</th>
                  </tr>
                </thead>
                <tbody>
                  {openTrades.map((trade) => (
                    <tr key={trade.id}>
                      <td><b>{trade.symbol}</b></td>
                      <td>
                        <span
                          className={`side ${
                            trade.direction === "LONG" ? "long" : "short"
                          }`}
                        >
                          {trade.direction || "—"}
                        </span>
                      </td>
                      <td>${formatMoney(trade.entry_price)}</td>
                      <td>
                        {trade.stop_loss == null
                          ? "—"
                          : `$${formatMoney(trade.stop_loss)}`}
                      </td>
                      <td>
                        {trade.leverage == null
                          ? "—"
                          : `${trade.leverage}x`}
                      </td>
                      <td>
                        {trade.pnl == null
                          ? "—"
                          : `$${formatMoney(trade.pnl)}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </article>

        <article className="panel services">
          <div className="panel-title">
            <div>
              <h2>حالة الخدمات</h2>
              <p className="muted">حسب آخر تقرير من البوت</p>
            </div>
          </div>

          <ServiceRow
            title="Binance"
            value={status?.exchange_connected}
          />
          <ServiceRow
            title="Supabase"
            value={status?.database_connected}
          />
          <ServiceRow
            title="Redis"
            value={status?.redis_connected}
          />

          <div className="cycle">
            <Clock3 size={16} />
            <span>آخر دورة مكتملة</span>
            <b>{formatDate(status?.cycle_completed_at)}</b>
          </div>

          {status?.last_error && (
            <div className="last-error">{status.last_error}</div>
          )}
        </article>
      </section>

      <section className="panel archive">
        <div className="panel-title archive-head">
          <div>
            <h2>أرشيف الصفقات</h2>
            <p className="muted">آخر الصفقات المغلقة المسجلة</p>
          </div>

          <div className="filters">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="بحث بالعملة..."
              aria-label="بحث بالعملة"
            />

            <select
              value={resultFilter}
              onChange={(event) => setResultFilter(event.target.value)}
              aria-label="تصفية النتائج"
            >
              <option value="all">كل النتائج</option>
              <option value="wins">رابحة</option>
              <option value="losses">خاسرة</option>
            </select>
          </div>
        </div>

        {archivedTrades.length === 0 ? (
          <div className="empty">لا توجد صفقات مغلقة مطابقة.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>العملة</th>
                  <th>الاتجاه</th>
                  <th>الدخول</th>
                  <th>الخروج</th>
                  <th>النتيجة</th>
                  <th>سبب الإغلاق</th>
                  <th>وقت الإغلاق</th>
                </tr>
              </thead>
              <tbody>
                {archivedTrades.map((trade) => (
                  <tr key={trade.id}>
                    <td><b>{trade.symbol}</b></td>
                    <td>{trade.direction || "—"}</td>
                    <td>${formatMoney(trade.entry_price)}</td>
                    <td>
                      {trade.exit_price == null
                        ? "—"
                        : `$${formatMoney(trade.exit_price)}`}
                    </td>
                    <td
                      className={
                        Number(trade.pnl) >= 0
                          ? "text-positive"
                          : "text-negative"
                      }
                    >
                      {trade.pnl == null
                        ? "—"
                        : `$${formatMoney(trade.pnl)}`}
                    </td>
                    <td>{trade.close_reason || trade.status || "—"}</td>
                    <td>{formatDate(trade.closed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <footer className="footer">
        البيانات تعرض آخر ما حفظه البوت؛ حداثتها مرتبطة بتكرار تشغيله ونجاح المزامنة.
      </footer>
    </main>
  );
}

export default function App() {
  const [session, setSession] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);

  useEffect(() => {
    if (!supabase) {
      setAuthLoading(false);
      return undefined;
    }

    let active = true;

    supabase.auth.getSession().then(({ data }) => {
      if (active) {
        setSession(data.session);
        setAuthLoading(false);
      }
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setAuthLoading(false);
    });

    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  if (!supabase) {
    return (
      <main className="page">
        <div className="error-banner">
          أضف VITE_SUPABASE_URL و VITE_SUPABASE_ANON_KEY في إعدادات Cloudflare Pages.
        </div>
      </main>
    );
  }

  if (authLoading) {
    return <main className="page loading">جارٍ تحميل لوحة APEX...</main>;
  }

  if (!session) {
    return <LoginForm />;
  }

  return <Dashboard />;
}
