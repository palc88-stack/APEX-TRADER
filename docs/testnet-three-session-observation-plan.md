# خطة مراقبة جلسات Binance Testnet الثلاث القادمة

**المستودع:** `palc88-stack/APEX-TRADER`  
**الالتزام المستهدف:** `34e2e0a`  
**النطاق:** Binance Testnet فقط — لا تشمل التداول الحي أو Walk-Forward  
**الهدف:** إثبات أن كل جلسة تستمر عند رفض رمز واحد، وأن حالة Binance تتطابق مع Supabase، وأن الـledger وقيود المخاطر ولوحة التحكم متسقة.

> هذه الخطة مراقبة وتحقيق. لا نغير إعدادات المخاطر أو نفعّل Live أثناء تنفيذها.

## 1. حالة التشغيل الحالية

- Workflow الجلسة: `.github/workflows/testnet-session.yml`
- الجدولة: كل ساعتين، بحد أقصى 12 دورة، والفاصل الافتراضي 300 ثانية.
- الحواجز الحالية:
  - `BINANCE_TESTNET=true`
  - `ALLOW_LIVE_TRADING=false`
  - `TRADING_EXECUTION_ENABLED=true`
  - `AUTO_RECONCILE_CLOSE_ENABLED=true`
  - `AUTO_RECONCILE_CLOSE_LIVE=false`
  - Distributed Lease باسم `apex-trading-execution`
- Worker المصالحة في Cloudflare **قراءة فقط بالنسبة لأوامر Binance**؛ لا يفتح أو يغلق أو يعدّل أوامر.

## 2. قواعد السلامة قبل البدء

1. لا نطلق جلسة يدوية إضافية إذا كانت جلسة مجدولة أو Worker يحمل الـlease.
2. لا نغير `TRADING_SYMBOLS` أو `UNIVERSE_SIZE` أو الرافعة أثناء الجلسات الثلاث.
3. لا نستخدم Live API ولا نغير `BINANCE_BASE_URL`.
4. لا نغلق أو نعدّل مركزًا يدويًا بغرض الاختبار.
5. إذا ظهر فرق غير مفسر بين Binance وSupabase، نوقف فتح جلسات جديدة ونشغل مسار المصالحة فقط.
6. لقطات Binance وSupabase يجب أن تحتوي وقت UTC واضحًا، لأن View اليومية تستخدم `NOW()` و`date_trunc('day', NOW())`.

## 3. بوابات النجاح العامة

تعتبر الخطة ناجحة إذا تحققت الشروط التالية في **كل جلسة**:

- الجلسة تعمل على الالتزام `34e2e0a` أو التزام أحدث معتمد.
- لا يوجد `KeyError` في Loguru ولا فشل عام بسبب رفض رمز واحد.
- لا يوجد أكثر من مالك واحد للـexecution lease.
- عدد المراكز المفتوحة في Binance يساوي عدد الصفقات المحلية القابلة للمطابقة، مع تفسير صريح لأي فرق مؤقت.
- كميات المراكز المتطابقة ضمن هامش `max(1e-8, DB quantity × 0.001)`، وهو نفس منطق Worker الحالي.
- كل أمر مُرسل له سجل في `trade_orders`، وكل fill مؤكد له سجل في `trade_fills`.
- لا توجد صفقة جديدة بحالة `NEEDS_RECONCILIATION` دون تنبيه وتفسير.
- PnL المؤكد في `dashboard_daily_summary` يساوي مجموع الصفقات المغلقة المؤكدة، ولا يدخل فيه `pnl_source='unconfirmed'`.
- `bot_state` يحتوي heartbeat ووقت آخر دورة منطقيين.
- لا توجد أوامر مكررة لنفس الإشارة أو نفس هوية الأمر/idempotency key.

## 4. اللقطة المرجعية قبل كل جلسة

سجّل هذه القيم قبل بدء الجلسة، مع وقت UTC ورقم Run ID السابق:

### من GitHub Actions

- آخر commit.
- حالة آخر جلسة.
- Run ID للجلسة الجديدة.
- هل يوجد Run آخر قيد التنفيذ؟

### من Binance Testnet

- الرصيد المتاح.
- المراكز المفتوحة: `symbol`, `positionAmt`, `entryPrice`, `markPrice`, `leverage`, `unRealizedProfit`.
- الأوامر المفتوحة: `symbol`, `orderId`, `side`, `type`, `origQty`, `executedQty`, `status`, `reduceOnly`, `stopPrice`.

### من Supabase

احفظ نتائج الاستعلامات في ملف باسم مثل:

```text
session-1-before-YYYYMMDDTHHMMSSZ.json
```

الاستعلامات المنطقية المطلوبة:

```sql
-- حالة البوت والـheartbeat
SELECT id, is_running, bot_status, environment,
       heartbeat_at, last_run_at, cycle_completed_at,
       daily_realized_pnl, daily_loss_used_usd, risk_day,
       database_connected, updated_at
FROM public.bot_state
WHERE id = 1
LIMIT 1;
```

```sql
-- الصفقات المفتوحة أو المعلقة للمطابقة
SELECT id, symbol, status, entry_order_id, closing_order_id,
       entry_quantity, remaining_quantity, entry_price, exit_price,
       pnl, pnl_source, reconciliation_note, opened_at, closed_at,
       updated_at
FROM public.trades
WHERE status IN ('OPEN', 'NEEDS_RECONCILIATION')
ORDER BY symbol, id
LIMIT 100;
```

```sql
-- ملخص اليوم المؤكد
SELECT risk_day, confirmed_closed_trades,
       confirmed_realized_pnl, confirmed_loss_used_usd, confirmed_fees
FROM public.dashboard_daily_summary
LIMIT 1;
```

```sql
-- الحجوزات والمراكز المنطقية
SELECT slot_no, symbol, trade_id, reservation_id, status
FROM public.position_slots
WHERE status IN ('reserved', 'occupied')
ORDER BY slot_no
LIMIT 100;
```

```sql
-- أحدث دورات المصالحة
SELECT id, checked_at, source,
       db_open_count, exchange_open_count,
       occupied_slot_count, finding_count, findings
FROM public.reconciliation_runs
ORDER BY checked_at DESC
LIMIT 10;
```

```sql
-- أحدث سجلات الأوامر والـfills والأحداث
SELECT id, trade_id, symbol, exchange_order_id, status,
       created_at, updated_at
FROM public.trade_orders
ORDER BY created_at DESC
LIMIT 100;
```

```sql
SELECT id, trade_id, symbol, exchange_trade_id,
       price, quantity, fee, fee_currency, filled_at
FROM public.trade_fills
ORDER BY filled_at DESC
LIMIT 100;
```

> إذا كانت أسماء أعمدة `trade_orders` أو `trade_fills` مختلفة في البيئة الفعلية، استخدم الأعمدة الموجودة في schema/migrations بدل تعديل التطبيق أثناء فترة الاختبار.

## 5. مراقبة الجلسة أثناء التنفيذ

لكل دورة سجّل:

- رقم الدورة ووقت بدايتها ونهايتها.
- عدد الرموز التي عولجت.
- عدد الإشارات.
- عدد الأوامر المرسلة والمملوءة والمرفوضة.
- أي تحذير `-2027` أو `maximum allowable position`.
- هل استمرّت الرموز التالية بعد رفض رمز واحد؟
- هل بقي الـlease مملوكًا لنفس `APEX_LEASE_OWNER`؟
- هل تم تحديث heartbeat؟
- هل تم تحديث `cycle_completed_at`؟

### دليل نجاح خاص برفض Binance

إذا رفض Binance رمزًا بسبب الحد الأقصى للمركز:

1. يظهر تحذير خاص بذلك الرمز.
2. لا يحدث `RuntimeError` عام بسبب هذا الرفض.
3. لا يتكرر إرسال أمر لذلك الرمز في نفس الجلسة.
4. تستمر معالجة الرموز الأخرى.
5. لا يتحول الرفض وحده إلى `NEEDS_RECONCILIATION` ما لم توجد حالة تنفيذ غير مؤكدة.

## 6. اللقطة بعد كل جلسة

بعد انتهاء Run، انتظر اكتمال كتابة heartbeat و`mark_bot_stopped` ثم احفظ لقطة بعدية:

```text
session-1-after-YYYYMMDDTHHMMSSZ.json
```

تحقق من الآتي:

| المجال | تحقق القبول |
|---|---|
| Workflow | النتيجة `success` أو فشل مبرر غير متعلق بالتداول؛ لا فشل بسبب Loguru أو رمز منفرد |
| lease | تم تحرير lease أو انتهت صلاحيته، ولا يوجد مالك متضارب |
| bot_state | `updated_at` و`cycle_completed_at` أحدث من اللقطة السابقة؛ حالة التوقف منطقية بعد نهاية Run |
| Binance positions | لا يوجد مركز جديد بلا سجل محلي |
| trades | كل OPEN له مركز مطابق، وكل CLOSED الجديد له دليل fill مؤكد |
| reconciliation | `finding_count=0`، أو لكل finding تفسير موثق وإجراء لاحق |
| ledger | لا توجد سجلات أوامر مكررة لنفس هوية الأمر |
| PnL | View اليومية لا تشمل unconfirmed، ومجموعها يطابق السجلات المؤكدة |
| dashboard | القيم المعروضة مساوية لنتائج Supabase الأخيرة وليست cache قديمًا |

## 7. خطة الجلسات الثلاث

### الجلسة 1 — سلامة الإصلاح

**الهدف:** إثبات أن إصلاح Logger وعزل رفض الرمز يعملان.

- استخدم الجدولة الطبيعية أو تشغيلًا يدويًا واحدًا فقط إذا لم تكن هناك جلسة قيد التنفيذ.
- راقب أي رمز يرفضه Binance، خصوصًا FXS إن ظهر ضمن الكون.
- ركز على استمرار الدورة بعد الرفض.
- لا تعتبر عدم ظهور رفض FXS فشلًا؛ السلوك المطلوب يمكن اختباره أيضًا عبر نجاح دورة كاملة دون أخطاء.

**معيار الخروج:** لا Crash عام، ولا `KeyError`، ولقطة Supabase بعدية متسقة.

### الجلسة 2 — المحاسبة والمطابقة

**الهدف:** إثبات أن أي فتح/إغلاق أو fill ينعكس بشكل صحيح في Supabase.

- قارن كل أمر جديد مع `trade_orders`.
- قارن كل fill مع `trade_fills`.
- أعد حساب الكمية المتبقية والرسوم وPnL من بيانات fill المؤكدة.
- تحقق أن `dashboard_daily_summary` يتغير فقط عند وجود صفقة مغلقة مؤكدة.
- تحقق من عدم احتساب `pnl_source='unconfirmed'`.

**معيار الخروج:** تطابق Binance ↔ ledger ↔ trades ↔ dashboard دون فرق غير مفسر.

### الجلسة 3 — الاستمرارية والتداخل

**الهدف:** إثبات التشغيل الآمن المتكرر ومنع التداخل.

- تحقق من الـlease أثناء وجود جلسة Testnet.
- تحقق أن أي تشغيل متزامن من Worker أو Workflow آخر يُرفض أو يُتخطى دون تنفيذ مزدوج.
- راقب تحرير الـlease عند النهاية.
- تحقق من heartbeat قبل وأثناء وبعد الجلسة.
- راجع عدم وجود slots عالقة بحالة `reserved` بعد فشل أمر أو نهاية الجلسة.

**معيار الخروج:** لا أوامر مكررة، لا lease متضارب، لا slots عالقة، ولا reconciliation جديد غير مفسر.

## 8. شروط الإيقاف الفوري

أوقف فتح الجلسات التالية، واترك المصالحة القراءة فقط، إذا حدث أي مما يلي:

- فشل جلسة جديدة بسبب `KeyError` أو استثناء عام داخل معالجة رمز.
- مركز Binance بلا سجل Supabase، أو سجل OPEN بلا مركز Binance، ولا يوجد تفسير زمني واضح.
- فرق كمية يتجاوز هامش 0.1% دون سبب fill جزئي موثق.
- أمر مكرر أو أكثر من ledger row لنفس exchange order identity.
- فقدان lease مع استمرار محاولة التداول.
- تحديث PnL غير المؤكد داخل الملخص اليومي.
- فشل heartbeat أو `cycle_completed_at` لجلستين متتاليتين.
- تشغيل أي مسار على Live أو ظهور `ALLOW_LIVE_TRADING=true`.

## 9. تقرير كل جلسة

استخدم هذا القالب:

```markdown
# Testnet Session N Report

- Run ID:
- Commit:
- Started UTC:
- Finished UTC:
- Workflow conclusion:
- Lease owner:
- Cycles completed:
- Symbols processed:
- Orders submitted / filled / rejected:
- Binance open positions:
- Supabase OPEN trades:
- NEEDS_RECONCILIATION count:
- Reconciliation findings:
- PnL view before / after:
- Fees before / after:
- Duplicate-order check:
- Heartbeat/cycle timestamps:
- Dashboard refresh verified:
- Stop condition triggered?:
- Evidence links:
- Final verdict: PASS / PASS WITH EXPLANATION / STOP
```

## 10. القرار بعد الجلسة الثالثة

- **PASS:** الجلسات الثلاث متسقة، ولا توجد reconciliation pending، ويمكن الانتقال إلى تقرير جاهزية Testnet.
- **PASS WITH EXPLANATION:** توجد فروقات مؤقتة بسبب fill جزئي أو توقيت snapshot، لكنها اختفت في دورة المصالحة التالية مع دليل واضح.
- **STOP:** أي فرق غير مفسر أو تكرار أو فشل عام؛ لا نفعّل Live، ونفتح إصلاحًا منفصلًا مع test case قبل استئناف المراقبة.

## 11. ما لا تختبره هذه الخطة

- لا تثبت ربحية الاستراتيجية.
- لا تختبر Walk-Forward.
- لا تبرر تفعيل التداول الحي.
- لا تستبدل مراجعة مفاتيح Binance وصلاحياتها.
- لا تعتبر نجاح GitHub Actions وحده دليلًا على تطابق Binance وSupabase؛ يجب حفظ لقطات المطابقة نفسها.
