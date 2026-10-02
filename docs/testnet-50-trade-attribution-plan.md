# خطة Testnet لجمع 50 صفقة حسب `strategy_subtype`

## الهدف

جمع 50 صفقة **مغلقة ومؤكدة بالـfills** على Binance Testnet، مع تسجيل `strategy_subtype` لكل إشارة مقبولة وكل صفقة، دون تفعيل Live ودون تغيير القواعد بعد كل صفقة.

> الإشارة ليست صفقة. لا تدخل الصفقة في العينة إلا بعد تأكيد Fill الدخول وFill الخروج والرسوم.

## التوزيع المستهدف

| المسار الفرعي | الوصف | الهدف | الحد الأدنى التحليلي |
|---|---|---:|---:|
| `trend_pullback_long` / `trend_pullback_short` | اتجاه EMA200 مع Pullback وRSI | 20 (10/10 قدر الإمكان) | 15 |
| `mean_reversion_scalp` | ارتداد Bollinger/RSI | 15 | 10 |
| `volatility_breakout` | Explosion بعد squeeze/volume/momentum | 15 | 10 |
| **الإجمالي** |  | **50** |  |

هذه أهداف عينة وليست أوامر مصطنعة. إذا لم يولد السوق إشارات كافية لمسار معين، نستمر في التسجيل ولا نفتح صفقات قسرية فقط لإكمال الحصة.

## بيانات تُحفظ لكل إشارة

يُحفظ في `strategy_signals`:

- `symbol`, `mode`, `strategy`, `strategy_subtype`
- `action`, `confidence`, `rule_score`, `reason`
- `entry_price`, `atr_value`, `atr_multiplier`
- `stop_distance`, `stop_loss`, `take_profit`
- `risk_budget_usd`
- `status`: `candidate` ثم `executed` عند تنفيذ Fill الدخول
- `trade_id` عند ربط الإشارة بصفقة

ويُحفظ في `trades` نفس الإسناد، إضافة إلى `signal_id` وبيانات الـledger والـfills.

## حساب الحجم

المتغيرات:

```text
risk_budget_usd = min(
    MAX_RISK_PER_TRADE_USD إذا كان > 0،
    account_balance × MAX_RISK_PER_TRADE_PCT / 100
)
stop_distance = ATR × ATR_STOP_MULTIPLIER
notional_usd = risk_budget_usd / (stop_distance / entry_price)
margin_usd = notional_usd / leverage
quantity = notional_usd / entry_price
```

الإعداد المحافظ المقترح في Testnet:

```text
MAX_LEVERAGE=5
MAX_RISK_PER_TRADE_PCT=1.0 أو 2.0
MAX_RISK_PER_TRADE_USD=10.0  # اختياري؛ صفر يعني الاعتماد على النسبة
ATR_PERIOD=14
ATR_STOP_MULTIPLIER=2.0
ALLOW_LIVE_TRADING=false
```

الرسوم والانزلاق غير داخلين في معادلة المخاطرة الأساسية؛ لذلك يجب أن تكون النتيجة الفعلية أقل من أو مساوية لميزانية المخاطرة قبل الرسوم، ولا يجوز اعتبارها ضمانًا للخسارة القصوى في فجوة سعرية.

## قواعد قبول الصفقة في العينة

1. Fill الدخول مؤكد من Binance.
2. `entry_price_source`, `entry_quantity_source`, و`entry_fee_source` من exchange fill.
3. Fill الخروج مؤكد من Binance.
4. الرسوم وسعر/كمية الخروج مسجلة.
5. لا توجد حالة `NEEDS_RECONCILIATION` غير محسومة للصفقة.
6. `strategy_subtype` غير فارغ وموجود في `strategy_signals` و`trades`.
7. تسجيل `atr_value`, `atr_multiplier`, `stop_distance`, و`risk_budget_usd`.

## التقرير بعد كل 10 صفقات

نحسب لكل subtype:

- عدد الصفقات المغلقة المؤكدة.
- Win rate.
- متوسط الربح ومتوسط الخسارة.
- Profit factor.
- Expectancy بعد الرسوم.
- Maximum drawdown.
- متوسط الانزلاق.
- النتائج حسب الرمز والاتجاه.
- نسبة إشارات `candidate` التي تحولت إلى Fill.

لا يصدر حكم ربحية نهائي قبل اكتمال 50 صفقة أو مرور 2–4 أسابيع، أيهما أبعد، ولا يتم الانتقال إلى Live من هذه العينة وحدها.
