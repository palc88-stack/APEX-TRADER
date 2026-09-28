# تقرير فحص Supabase وExchangeManager وجاهزية جلسة Binance Testnet

**المشروع:** APEX-TRADER  
**التاريخ:** 2026-09-28  
**النطاق:** قراءة فقط من Supabase + مراجعة الكود؛ لم يتم إرسال أي أمر إلى Binance.

## 1. الملخص التنفيذي

- لا توجد حالياً صفقات بحالة `OPEN`.
- لا توجد صفقات بحالة `NEEDS_RECONCILIATION`.
- لا توجد سجلات في `partial_closes`.
- آخر حالة محفوظة في `bot_state` تشير إلى اتصال Binance وSupabase، ولا يوجد خطأ محفوظ.
- توجد **مخالفة إعداد مهمة**: قيمة `bot_state.environment` الحالية هي `production`، بينما Workflow Testnet يفرض `ENVIRONMENT=testnet` و`BINANCE_TESTNET=true` و`ALLOW_LIVE_TRADING=false`.
- لذلك يجب التحقق من السجل بعد الجلسة القصيرة، ولا ينبغي اعتبار قيمة `production` القديمة دليلاً على تشغيل Live أو تعديلها يدوياً.

## 2. نتيجة فحص جداول Supabase

### 2.1 `bot_state`

آخر صف مقروء (`id=1`):

| الحقل | القيمة |
|---|---|
| `is_running` | `false` |
| `bot_status` | `stopped` |
| `environment` | `production` — **configuration drift** |
| `heartbeat_at` | `2026-09-28 12:44:35.588479+00` |
| `last_run_at` | `2026-09-28 12:44:35.588479+00` |
| `cycle_completed_at` | `2026-09-28 12:44:34.850899+00` |
| `exchange_connected` | `true` |
| `database_connected` | `true` |
| `redis_connected` | `null` |
| `last_error` | `null` |

`redis_connected=null` متوقع حالياً لأن Redis ليس جزءاً من التشغيل الحالي؛ لا ينبغي عرضه كاتصال ناجح أو فاشل دون فحص فعلي.

### 2.2 الصفقات المعلقة للمصالحة

الاستعلام المستخدم:

```sql
SELECT id, symbol, status, strategy, entry_order_id, closing_order_id,
       pnl_source, reconciliation_note, opened_at, closed_at
FROM public.trades
WHERE status IN ('OPEN', 'NEEDS_RECONCILIATION')
ORDER BY opened_at DESC
LIMIT 100;
```

**النتيجة:** `0` صفوف.

الحكم الحالي:

```text
لا توجد صفقات مفتوحة أو صفقات معلقة بحاجة إلى مصالحة في Supabase.
```

### 2.3 `partial_closes`

الاستعلام المستخدم:

```sql
SELECT id, trade_id, reason, price, amount_closed, pnl, fee,
       price_source, quantity_source, fee_source, pnl_source,
       exchange_order_id, created_at
FROM public.partial_closes
ORDER BY created_at DESC
LIMIT 100;
```

**النتيجة:** `0` صفوف.

هذا يعني عدم وجود TP1 أو إغلاق جزئي محفوظ حتى وقت الفحص، وليس دليلاً على عدم حدوث إغلاق جزئي خارج قاعدة البيانات.

## 3. سياسات RLS الحالية

تم التحقق من السياسات التالية:

- `authenticated_read_bot_state` — قراءة `bot_state` للمستخدم المصادق.
- `authenticated_read_trades` — قراءة `trades` للمستخدم المصادق.
- `authenticated_read_partial_closes` — قراءة `partial_closes` للمستخدم المصادق.

الواجهة لا تملك صلاحيات إدخال أو تحديث أو حذف. البوت يستخدم مفتاح الكتابة الخلفي `SUPABASE_WRITE_KEY`.

## 4. مراجعة `bot/core/exchange.py`

### 4.1 سعر السوق

`get_ticker()` يستدعي:

```python
exchange.fetch_ticker(symbol)
```

ويصنف النتيجة كـ `exchange_market_data`. ولا يستخدمها وحدها كإثبات Fill.

### 4.2 بيانات Fill والرسوم

`fetch_fill_details(order_id, symbol)` يعمل بالترتيب التالي:

1. يستدعي:

```python
exchange.fetch_order(order_id, symbol)
```

2. يستخرج:

```text
filled
average أو price
fee.cost
fee.currency
```

3. إذا لم تكن الرسوم مؤكدة من `fetch_order`، يستدعي:

```python
exchange.fetch_my_trades(symbol, limit=100)
```

4. يربط التنفيذات بالطلب عبر:

```python
str(trade.get("order")) == str(order_id)
```

5. يجمع رسوم التنفيذات المرتبطة فقط إذا كانت العملة `USDT` أو `BUSD`.

6. إذا تعذر إثبات السعر أو الكمية أو الرسوم، تصبح الحالة `unconfirmed`، ولا يكون Fill صالحاً لحساب PnL.

### 4.3 أوامر الدخول والحماية

- أمر الدخول يستخدم CCXT:

```python
exchange.create_order(..., type="market", ...)
```

- أوامر SL وTP تستخدم Binance Algo Order API:

```text
POST /fapi/v1/algoOrder
```

مع:

```text
algoType=CONDITIONAL
STOP_MARKET
TAKE_PROFIT_MARKET
reduceOnly=true
workingType=CONTRACT_PRICE
```

- يتم حفظ معرفات Algo في الصفقة:

```text
stop_algo_id
take_profit_algo_id
```

- عند فشل إنشاء الحماية، يحاول البوت تنفيذ `reduce_only_close` ثم يفحص بقاء المركز.

### 4.4 ملاحظات وحدود المراجعة

1. `fetch_my_trades(..., limit=100)` ليس pagination كاملاً؛ إذا تجاوزت التنفيذات النطاق، قد تبقى الرسوم غير مؤكدة.
2. الربط يعتمد على حقل CCXT الموحد `trade["order"]`؛ يجب التحقق من استجابة Binance الفعلية في جلسة Testnet.
3. إذا أعادت Binance العمولة بعملة غير `USDT` أو `BUSD`، فلن يعتبرها الكود مؤكدة دون تحويل موثق.
4. لن يحوّل `current_price` إلى Fill؛ في هذه الحالة تُحفظ الصفقة للمصالحة بدلاً من اختلاق PnL.

## 5. أمر جلسة Testnet قصيرة — 3 دورات

هذا الأمر **مجهز فقط ولم يتم تشغيله تلقائياً**:

```bash
gh workflow run testnet-session.yml \
  --repo palc88-stack/APEX-TRADER \
  -f cycles=3 \
  -f interval_seconds=60
```

هذا يستخدم إعدادات Workflow التالية:

```text
ENVIRONMENT=testnet
PRIMARY_EXCHANGE=binance
BINANCE_TESTNET=true
ALLOW_LIVE_TRADING=false
APEX_RUN_CYCLES=3
APEX_CYCLE_INTERVAL_SECONDS=60
TRADING_SYMBOLS=BTC/USDT
TRADING_TIMEFRAME=5m
```

بعد التشغيل اليدوي يمكن متابعة آخر Run بالأمر:

```bash
gh run list \
  --repo palc88-stack/APEX-TRADER \
  --workflow testnet-session.yml \
  --limit 1
```

ثم مراقبته:

```bash
gh run watch RUN_ID \
  --repo palc88-stack/APEX-TRADER \
  --exit-status
```

## 6. معايير قبول الجلسة

لا نعتبر الجلسة ناجحة لمجرد خروج Python بحالة `0`. يجب التحقق من:

```text
BINANCE_TESTNET=true
ALLOW_LIVE_TRADING=false
bot_state.environment = testnet
exchange_connected = true
database_connected = true
cycle_completed_at حديث
```

إذا لم تظهر إشارة، فهذا نجاح مراقبة وليس فشلاً؛ لا يجوز اصطناع صفقة أو Fill.

إذا فتحت إشارة صفقة، يجب أن يظهر في سجل `trades`:

```text
strategy
entry_order_id
stop_algo_id
take_profit_algo_id
entry_price_source
entry_quantity_source
entry_fee_source
```

وعند إغلاقها:

```text
closing_order_id
exit_price_source
exit_quantity_source
exit_fee_source
pnl_source
```

القيمة المقبولة للـPnL المحقق هي:

```text
pnl_source = exchange_fill
```

أما في حال عدم إثبات Fill:

```text
status = NEEDS_RECONCILIATION
pnl_source = unconfirmed
```

## 7. الحكم النهائي

```text
المصالحة الحالية: لا توجد صفقات معلقة في Supabase.
RLS: موجودة وصحيحة للقراءة المصادق عليها.
طريقة الرسوم: fetch_order ثم fetch_my_trades عند الحاجة، مع رفض المصدر غير المؤكد.
طريقة أوامر الحماية: Binance Algo Order API.
Live: غير مسموح.
Testnet: جاهز لجلسة قصيرة يدوية.
Configuration drift: environment في bot_state قديم/غير متوافق ويجب التحقق منه بعد الجلسة، دون تعديله يدوياً.
```
