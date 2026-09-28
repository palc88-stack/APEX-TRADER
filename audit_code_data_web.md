# تدقيق مستقل للكود والبيانات والويب — APEX TRADER

## النطاق والمنهج

تمت قراءة ملفات Python وJavaScript/JSX/CSS وSQL وCI المتتبعة في المستودع، مع تتبع المسار: exchange → market data/indicators → signal/risk → order → Supabase state/trades → React. أُجري فحص ترجمة Python و`node --check` للـ Worker وبناء Vite واختبارات الوحدة المحلية فقط؛ لم تُشغّل صفقات ولم تُستخدم مفاتيح أو بيانات خارجية.

## الملخص التنفيذي

يوجد **تعارض جوهري بين عقد قاعدة البيانات والواجهة**، إضافة إلى أخطاء مؤثرة في تنفيذ الإغلاق الجزئي، حساب المخاطر/الرافعة، حد الخسارة اليومية، وتعدد المنصات. مسار webhook قابل لفقدان حالة الصفقة أو تكرار التنفيذ عند فشل الحفظ/العلامة، كما أن مخطط SQL لا يفعّل RLS. البناء المحلي ينجح، ونجحت الاختبارات المحلية المحددة (`14 passed`) لكنها لا تغطي مسارات التداول الحقيقية التي تستبعدها CI.

## تدفق البيانات المرصود

1. `ExchangeManager` يجلب ticker/ OHLCV وينفذ أوامر Binance.
2. `MarketDataManager` يحوّل OHLCV إلى DataFrame ثم المؤشرات/الإشارات.
3. `ApexTraderBot` يطبق RiskManager، يرسل أمر السوق وأوامر SL/TP، ثم يحفظ سجل `trades`.
4. Worker يكتب `pending_signals`، والبوت يقرأها وينفذها ثم يعلّمها processed.
5. `StateManager` يكتب `bot_state` و`trades`، بينما React يقرأ `bot_state` و`trades` مباشرة من Supabase.

## النتائج

### APEX-001 — حرج — عقد bot_state لا يطابق React

React يطلب حقولاً غير موجودة في schema أو غير مكتوبة من البوت (`available_balance`, `bot_status`, `heartbeat_at`, `daily_unrealized_pnl`, حالات الخدمات، ووقت الدورة). النتيجة المتوقعة من الكود هي ظهور `—`/`غير معروف` وتقرير نبض مختلف: الحساب يستعمل `last_run_at` للحساب لكن العرض يستخدم `heartbeat_at`.

**Evidence:**

`database/schema.sql:25-57; bot/data/state_manager.py:73-111; web/src/App.jsx:280-375; web/src/App.jsx:392-443; web/src/App.jsx:518-535`

**الأثر:** لوحة المتابعة لا تمثل حالة البوت/الحساب الفعلية، وقد تُخفي فشل المزامنة.

**الإصلاح:** وحّد DTO وجدول `bot_state`: إمّا تعديل React إلى أسماء الأعمدة الموجودة، أو إضافة/كتابة الحقول المطلوبة مع migration واختبار عقد آلي؛ استخدم اسماً واحداً للنبض.

### APEX-002 — حرج — لا توجد حماية RLS فعلية لجداول Supabase

الـ schema يعرّف الجداول لكنه لا يفعّل RLS ولا سياسات القراءة/الكتابة. الواجهة تحمل anon key، والـ Worker يستخدم anon key إن كان موجوداً.

**Evidence:**

`database/schema.sql:171-187; src/worker.js:35-38; web/src/App.jsx:15-21`

**الأثر:** يمكن تجاوز شاشة الدخول والوصول/التعديل على بيانات التداول إذا كانت صلاحيات Data API تسمح بذلك؛ كما قد يستطيع Worker كتابة إشارات عامة عند كشف secret.

**الإصلاح:** فعّل RLS على `bot_state`, `trades`, `pending_signals`، اسمح للـ authenticated بالقراءة فقط، واجعل كتابة البوت/Worker عبر service role محفوظة server-side؛ لا تعرض service key للويب.

### APEX-003 — حرج — الإغلاق الجزئي يستخدم أمر فتح لا أمر تقليل

مسار TP1 يستدعي `ExchangeManager.place_order`، لكن الدالة تثبّت `reduceOnly: False` دائماً. بذلك قد يفتح أمر TP1 مركزاً جديداً/يعكس التعرض بدلاً من إغلاق 50%.

**Evidence:**

`bot/main.py:180-196; bot/core/exchange.py:153-159`

**الأثر:** حجم المركز والاتجاه في المنصة قد ينحرفان عن قاعدة البيانات، مع خطر زيادة التعرض.

**الإصلاح:** أضف API صريحاً للإغلاق الجزئي يرسل `reduceOnly: True`، ولا يرسل `closePosition` مع `amount` إلا وفق عقد المنصة؛ تحقق من fill قبل تحديث الحالة.

### APEX-004 — عالٍ — فشل أمر TP1 يُسجّل كأنه ناجح

الاستثناء من الإغلاق الجزئي يُلتقط، ثم يُحفظ `tp1_executed=True` وتُرسل رسالة النجاح خارج كتلة الفشل دون التحقق من نتيجة الأمر.

**Evidence:**

`bot/main.py:187-203`

**الأثر:** لا تُعاد محاولة TP1 الفاشلة، وتصبح حالة DB والإشعار مخالفة لمركز المنصة.

**الإصلاح:** لا تحدّث `tp1_executed` ولا ترسل الإشعار إلا بعد تأكيد order/fill؛ خزّن حالة فشل قابلة لإعادة المحاولة.

### APEX-005 — حرج — P&L والرسوم يفترضان رافعة لا يطبقها أمر المنصة

حجم الأمر المرسل هو `size_usd / entry_price`، ولا يوجد `leverage` في params أو استدعاء set leverage، بينما Position/P&L والرسوم يحسبان القيمة الاسمية كـ `size_usd * leverage`. هذا يخلق فرقاً بين التعرض الفعلي والتعرض المحفوظ/الربح المحسوب.

**Evidence:**

`bot/main.py:285-315; bot/main.py:322-324; bot/core/exchange.py:153-159; bot/core/position_manager.py:72-96`

**الأثر:** تقييم المخاطر، P&L، الرسوم، ولوحة الحساب قد تكون مضخمة أو أقل من الواقع؛ لا يوجد ضمان أن المنصة تعمل بالرافعة المسجلة.

**الإصلاح:** عرّف بوضوح هل `size_usd` هامش أم notional، طبّق الرافعة على المنصة قبل الأمر، واجعل amount/P&L/fees كلها مبنية على fill الفعلي وقيمة notional واحدة.

### APEX-006 — حرج — حد الخسارة اليومية محسوب كـ 400% افتراضياً

الإعداد `MAX_DAILY_LOSS_PCT` هو 4.0 كنسبة مئوية، لكن main يضربه مباشرة في الرصيد بلا قسمة على 100. التعليق في config لا يطابق التنفيذ.

**Evidence:**

`bot/config.py:132-141; bot/main.py:81-90; bot/main.py:102-107`

**الأثر:** لا يتوقف البوت عند حد 4%؛ حماية الخسارة اليومية قد لا تعمل إلا بعد خسارة أكبر بكثير.

**الإصلاح:** حوّل النسبة إلى كسر (`pct / 100`) في موضع واحد، اختبر 4% مقابل رصيد معروف، وأعد ضبط العدادات عند يوم UTC جديد.

### APEX-007 — عالٍ — حجم الصفقة يعتمد على initial balance ولا يتحدث مع الرصيد

`_calculate_position_size` يستخدم `initial_balance` الثابت، رغم أن heartbeat يجلب الرصيد الحالي وRiskManager يفحصه.

**Evidence:**

`bot/main.py:81-90; bot/main.py:359-365`

**الأثر:** بعد تغير الرصيد، الحجم لا يعكس الحساب الحالي؛ قد يزيد المخاطر النسبية بعد خسائر أو يقللها بعد نمو الحساب.

**الإصلاح:** مرّر الرصيد الحالي إلى حساب الحجم، اربط الحجم بحدود margin/notional، وارفض القيم غير الموجبة بدلاً من fallback صامت.

### APEX-008 — حرج — إعداد Bybit لا يطابق منفذ الأوامر

Config وMarketData يدعمان Bybit، لكن ExchangeManager ينشئ Binance USD-M دائماً. عند `PRIMARY_EXCHANGE=bybit` قد تُجلب البيانات من Bybit بينما تُرسل الأوامر إلى Binance، ثم يُحفظ السجل باسم المنصة الأساسية.

**Evidence:**

`bot/config.py:54-75; bot/core/exchange.py:37-53; bot/data/market_data.py:32-38; bot/data/market_data.py:65-86; bot/main.py:333-334`

**الأثر:** سعر/رمز/حساب ومكان تنفيذ الصفقة قد لا تكون نفس المنصة؛ هذا خلل backend/frontend/worker لا يظهر في build.

**الإصلاح:** أنشئ adapter واحداً حسب `primary_exchange` يملك fetch/order/close/close lifecycle، أو ارفض Bybit صراحة بدلاً من تنفيذه جزئياً.

### APEX-009 — عالٍ — مسار pending_signals ليس ذرياً ولا يمنع التكرار

البوت يقرأ كل `pending` ثم ينفذ قبل وضع `processed`، بلا claim/lock/idempotency. كما أن `handle_webhook_signal` يتجاهل قيمة `save_trade_state`؛ لذلك يمكن تعليم الإشارة processed بعد تنفيذ ناجح رغم فشل حفظ الصفقة، أو إعادة تنفيذها بعد crash قبل العلامة.

**Evidence:**

`bot/main.py:132-143; bot/main.py:468-497; bot/data/state_manager.py:139-149; bot/data/state_manager.py:241-251`

**الأثر:** صفقات مكررة أو تنفيذ موجود بلا سجل، مع صعوبة reconciliation.

**الإصلاح:** أضف حالات `pending/processing/processed/failed` مع claim ذري وlease، استخدم `webhook_id`/unique key وorder id كـ idempotency، ولا تعلّم processed إلا بعد تأكيد الحفظ.

### APEX-010 — عالٍ — Worker يقبل عقد webhook غير مقيّد

التحقق يختبر وجود `symbol/side/action` فقط، ثم يطبع side/action ويقبل أي قيم؛ لا يتحقق من allowlist أو نوع/نطاق السعر أو طول/شكل الرمز. مسار البوت يحوّل كل side غير `buy` إلى sell، وقد يفشل `float(price)` ويترك الإشارة pending.

**Evidence:**

`src/worker.js:25-33; src/worker.js:47-54; bot/main.py:368-393; bot/main.py:417-425`

**الأثر:** بيانات غير صحيحة قد تُخزّن، واتجاه غير صحيح قد يتحول إلى SELL، وإشارات فاسدة تعاد في كل دورة.

**الإصلاح:** تحقق صارم من JSON schema (symbol allowlist، side/action allowlist، price numeric موجب أو null، idempotency)، وارفض الطلب قبل الإدخال؛ وحّد validator بين Worker والبوت.

### APEX-011 — عالٍ — إغلاق أمر السوق لا يلغي أوامر الحماية المعلقة

`close_position` يرسل أمر reduce-only للسوق لكنه لا يلغي SL/TP اللذين أنشأهما `place_order`. بعد الإغلاق قد تبقى أوامر الحماية وتطلق على مركز لاحق أو ترفض/تفتح تعرضاً بحسب وضع المنصة.

**Evidence:**

`bot/core/exchange.py:165-203; bot/core/exchange.py:211-249`

**الأثر:** أوامر stale وتعارض مع إدارة المراكز.

**الإصلاح:** خزّن IDs لأوامر SL/TP، ألغها قبل/بعد الإغلاق وفق حالة fill، ثم تحقق من عدم بقاء أوامر مفتوحة.

### APEX-012 — عالٍ — `closePosition` مع `amount` عقد منصة متعارض محتمل

أوامر SL/TP ترسل `amount` وفي الوقت نفسه `closePosition: True`. Binance Futures عادة يميز بين close-position stop وكمية محددة؛ فشل هذه الأوامر يُلتقط كتحذير ويستمر فتح المركز بلا حماية.

**Evidence:**

`bot/core/exchange.py:168-197; bot/core/exchange.py:182-203`

**الأثر:** المركز قد يبقى بلا SL/TP رغم أن السجل يوحي بإعداد الحماية.

**الإصلاح:** استخدم صيغة API موثقة واحدة لكل وضع (كمية reduce-only أو close-position)، وافشل/اعزل فتح الصفقة إذا تعذر تثبيت الحماية حسب سياسة أمان صريحة.

### APEX-013 — متوسط — إعادة بناء المركز تفقد opened_at

`reconstruct_position` لا يمرر `opened_at` من DB، فتستخدم Position القيمة الافتراضية الحالية. duration بعد restart يبدأ من وقت الاستعادة لا وقت فتح الصفقة.

**Evidence:**

`bot/core/position_manager.py:60-63; bot/data/state_manager.py:170-213`

**الأثر:** `duration_minutes` وبيانات الأرشيف والإشعارات غير صحيحة بعد إعادة تشغيل.

**الإصلاح:** parse timestamp مع timezone ومرره إلى Position، مع اختبار restart/reconstruct.

### APEX-014 — عالٍ — P&L النهائي لا يخصم أثر TP1 الجزئي

بعد TP1 لا يُنقص `size_usd`/القيمة المتبقية ولا تُحفظ كمية التنفيذ، ثم `PositionManager.close_position` يحسب P&L النهائي على كامل `position_value` الأصلي.

**Evidence:**

`bot/main.py:180-205; bot/core/position_manager.py:350-375`

**الأثر:** P&L والرسوم والحد اليومي لا يطابقان fills الفعلية، وقد يعرض الأرشيف نتيجة غير صحيحة.

**الإصلاح:** خزّن remaining quantity وrealized P&L لكل fill، احسب الجزء المتبقي فقط عند TP2/SL، واجمع الرسوم من executions الفعلية.

### APEX-015 — عالٍ — TelegramNotifier وTradeSignal عقدان غير متوافقين

`send_new_trade` يقرأ `signal.mode` و`signal.is_explosion`، لكن TradeSignal لا يعرّف هذين العضوين. المسار غير مستعمل حالياً في main، لكنه يفشل وقت التشغيل عند استدعائه.

**Evidence:**

`bot/notifications/telegram_notifier.py:147-160; bot/signals/signal_engine.py:21-68`

**الأثر:** فشل إشعار فتح الصفقة أو كشف dead code غير المختبر.

**الإصلاح:** وحّد DTO (أضف الحقول اختيارياً مع defaults أو عدّل notifier إلى الحقول الحالية)، وأضف اختبار استدعاء فعلي.

### APEX-016 — متوسط — MarketDataManager مكرر ويُسرّب اتصالاً

الملف يعرّف `MarketDataManager` مرتين؛ التعريف الثاني يخفي الأول. حتى عند تمرير `exchange_source`، constructor يفتح exchange fallback الخاص به، ثم fetch يستخدم source، بينما shutdown في Bot يغلق ExchangeManager فقط ولا يغلق MarketDataManager.

**Evidence:**

`bot/data/market_data.py:19-38; bot/data/market_data.py:450-474; bot/data/market_data.py:568-582; bot/data/market_data.py:862-868; bot/main.py:36-38; bot/main.py:596-600`

**الأثر:** dead code وسلوك صيانة ملتبس واتصالات aiohttp غير مغلقة.

**الإصلاح:** احذف التعريف المكرر، لا تنشئ fallback عند وجود source، واجعل Bot يغلق كل الموارد في finally.

### APEX-017 — متوسط — CI تستبعد اختبارات تكشف تكامل الإنتاج

CI تستبعد اختبارات real data و`test_signal_engine_no_mock` و`test_indicators_output_validity`، وتسمح بفشل diagnostic Supabase (`|| true`). الاختبار المحلي الناجح لا يغطي هذه المسارات.

**Evidence:**

`.github/workflows/binance.yml:83-100; tests/test_real_data.py:52-100`

**الأثر:** build أخضر مع غياب تحقق exchange/indicator/webhook الحقيقي؛ قد تُخفى أعطال العقد.

**الإصلاح:** افصل اختبارات unit/integration ببيئات واضحة، لا تستبعد اختبارات ثابتة لا تحتاج شبكة، اجعل diagnostic تقريراً غير حاجب لا بديلاً عن فحص schema/RLS، وأضف static/lint/contract tests.

### APEX-018 — منخفض — اختبار البيانات الوهمية لا يفشل عند العثور عليها

اختبار `test_no_hardcoded_prices_in_production` يسجل warning فقط ولا يستخدم assertion عند اكتشاف الأنماط، كما أن `fake_signal` موجود في production path.

**Evidence:**

`tests/test_full_system.py:108-153; bot/main.py:402-408`

**الأثر:** اسم الاختبار يوحي بمنع mock/fake لكنه لا يمنع regression.

**الإصلاح:** قسّم فحص النصوص عن اختبار السلوك، واجعل violations assertions صريحة أو احذف الاختبار المضلل.

## فحوصات منفذة ونتائجها

- `python -m compileall -q bot tests`: نجح.
- `node --check src/worker.js`: نجح.
- `npm run build` داخل `web`: نجح (Vite).
- `python -m pytest tests/test_full_system.py tests/test_exchange_config.py -q --timeout=30`: `14 passed` مع تحذير إعداد pytest-asyncio.

نجاح الترجمة/build لا يثبت صحة عقود Supabase أو تنفيذ أوامر exchange؛ ولم يتم تشغيل أي تداول أو اتصال خارجي خلال التدقيق.

## الحدود

لم تُنفذ استدعاءات Binance/Bybit/Supabase/Telegram/Redis، ولم تُستخدم مفاتيح أو بيانات خارجية. لذلك لا يمكن إثبات سلوك API الفعلي أو صلاحيات RLS أو شكل fills؛ النتائج أعلاه مستندة إلى القراءة الساكنة، العقود المحلية، وتشغيل build/اختبارات الوحدة فقط. ملفات `node_modules` وartifacts المبنية ليست نطاق مراجعة منطق المصدر، والملفات غير المتتبعة الموجودة مسبقاً لم تُعامل كجزء من المصدر الإنتاجي إلا عند الحاجة للسياق.
