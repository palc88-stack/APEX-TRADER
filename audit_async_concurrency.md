# تدقيق asyncio / aiohttp / ccxt / Redis / Supabase / HTTP وسباقات الحالة

**النطاق:** قراءة وفحص ساكن للمستودع `/home/ubuntu/APEX-TRADER`، مع التركيز على `bot/main.py` و`bot/core/exchange.py` و`bot/data/market_data.py` و`bot/data/state_manager.py` و`bot/notifications/telegram_notifier.py` و`src/worker.js` و`database/schema.sql` والاختبارات ذات الصلة. لم تُستخدم مفاتيح أو بيانات خارجية، ولم يُشغّل تداول أو اتصال خارجي.

## الملخص

وجدت **9 مشاكل مثبتة** مرتبطة مباشرة بدورة حياة المهام، حجب event loop، إغلاق جلسات ccxt، التزامن بين webhook والحلقة، idempotency، واتساق الأوامر مع الحالة المخزنة. أخطرها: (1) إلغاء مهمة heartbeat دون انتظارها، مع احتمال استمرارها بالتوازي مع إغلاق exchange، (2) تنفيذ Supabase المتزامن داخل مسار async، (3) عدم وجود claim/lock ذري للإشارة أو المركز، ما يسمح بالتنفيذ المكرر والمتوازي، و(4) اعتبار أمر الدخول ناجحاً رغم ابتلاع فشل SL/TP.

## النتائج المثبتة

### ACON-001 — إلغاء heartbeat دون انتظار يترك سباقاً أثناء الإغلاق

- **الخطورة:** عالية
- **الملف/الأسطر:** `bot/main.py:567-569, 582-600`
- **الدليل:** تُنشأ `heartbeat_task` بـ`asyncio.create_task(...)`، ثم في `finally` يُستدعى `heartbeat_task.cancel()` فقط ولا يوجد `await heartbeat_task` ولا `asyncio.gather(..., return_exceptions=True)`. بعد ذلك تُنفذ كتابة Supabase (`update_heartbeat` و`mark_bot_stopped`) ثم `shutdown()` التي تغلق exchange في السطر 598. أما heartbeat نفسها فتجلب الرصيد من exchange في الأسطر 78-91. إذا كانت المهمة بين `update_heartbeat()` و`get_balance()` أو داخل استدعاء شبكي، فإن cancel لا يوقف العمل المتزامن فوراً؛ وقد تتسابق مع إغلاق exchange وكتابة حالة التوقف.
- **الأثر:** طلبات رصيد/كتابات heartbeat قد تستمر بعد بدء الإغلاق، وقد تظهر أخطاء `unclosed`/طلبات متزامنة مع connector مغلق، أو تُكتب حالة heartbeat بعد `is_running=false`.
- **الإصلاح:** في `finally` ألغِ المهمة ثم انتظرها داخل `try/except asyncio.CancelledError` (أو `await asyncio.gather(task, return_exceptions=True)`) قبل كتابة حالة التوقف وإغلاق الموارد. اجعل `start_heartbeat_loop` يتعامل صراحة مع `CancelledError` ويخرج بلا أعمال إضافية.
- **الثقة:** مؤكدة من مسار التنفيذ المقروء؛ لم أختبر اتصالاً فعلياً.

### ACON-002 — استدعاءات Supabase المتزامنة تحجب event loop داخل مسارات async

- **الخطورة:** عالية
- **الملف/الأسطر:** `bot/data/state_manager.py:37, 75-81, 111, 128-133`; `bot/main.py:100-115, 133-143, 158-163, 199-203, 233-245, 352, 395-497`
- **الدليل:** عميل Supabase يُستعمل عبر `.execute()` المتزامن مباشرة. حتى الدوال المعلنة `async` مثل `load_initial_state`, `update_heartbeat`, `update_bot_status`, و`mark_bot_stopped` تنفذ `.execute()` بلا `await` أو `asyncio.to_thread`. كما أن `process_market_cycle` يستدعي الدوال المتزامنة `get_pending_signals`, `get_open_trades_from_db`, `save_trade_state`, و`mark_signal_processed` مباشرة داخل الحلقة async. وتهيئة StateManager نفسها تنفذ probe شبكياً في `__init__` بالسطر 37.
- **الأثر:** كل طلب قاعدة بيانات يمكنه إيقاف event loop، فيؤخر webhook وheartbeat وإلغاء المهام والـtimeouts، ويزيد احتمال تداخل/تأخر دورة التداول. إذا طال HTTP أو علق، لا يستطيع aiohttp خدمة الطلبات أو ملاحظة الإلغاء في الوقت المناسب.
- **الإصلاح:** استخدم عميل Supabase async فعلياً إن كان مدعوماً، أو انقل كل الاستدعاءات المتزامنة إلى `await asyncio.to_thread(...)` مع timeout خارجي، وحدد semaphore/connection policy. لا تنفذ probe شبكياً في constructor؛ نفذه في `initialize` بعد بدء loop.
- **الثقة:** مؤكدة من استدعاءات API المتزامنة الظاهرة؛ لم أحتج لاتصال فعلي لإثبات الحجب.

### ACON-003 — لا توجد claim/lock ذرية للإشارات أو المراكز (تنفيذ webhook مكرر)

- **الخطورة:** حرجة
- **الملف/الأسطر:** `bot/main.py:132-143, 394-400, 458-497, 525-555`; `bot/data/state_manager.py:224-254`; `src/worker.js:47-67`; `database/schema.sql:82-113`
- **الدليل:** مسار pending يقرأ كل الصفوف `status='pending'` عبر `get_pending_signals()` ثم ينفذ الأمر، ولا يغير الحالة إلى `processed` إلا بعد التنفيذ في السطر 139. كذلك webhook HTTP يستدعي `handle_webhook_signal` مباشرة. داخل `handle_webhook_signal` يتم فحص المراكز المفتوحة ثم وضع الأمر ثم `save_trade_state`، بلا lock داخل العملية أو transaction/row claim في Supabase. Worker يدرج payload جديداً في كل POST، و`pending_signals.webhook_id` ليس `UNIQUE` ولا يوجد upsert/constraint على webhook ID.
- **الأثر:** طلبان متزامنان، أو طلب HTTP متزامن مع دورة pending، قد يريان عدم وجود مركز ويفتحان مركزين. وإذا نجح الأمر وفشل `mark_signal_processed` أو انقطع العامل قبل العلامة، تبقى الإشارة pending وتُنفذ مجدداً في الدورة التالية. إعادة إرسال نفس webhook لا تُمنع.
- **الإصلاح:** اجعل الاستلام idempotent بقيد `UNIQUE(webhook_id)` مع upsert/رفض التكرار. نفذ claim ذرياً مثل `UPDATE ... SET status='processing', locked_at=... WHERE id=? AND status='pending' RETURNING *`، ثم عالج timeout/recovery للحالات العالقة. وحّد direct webhook وpoller في طابور/مسار واحد، واستخدم lock/transaction لكل symbol أو قيداً/عملية ذرية تمنع فتح مركزين.
- **الثقة:** مؤكدة من ترتيب القراءة والتنفيذ والـschema؛ لم أرسل webhook فعلياً.

### ACON-004 — فشل SL/TP يُبتلع بعد نجاح أمر السوق

- **الخطورة:** حرجة
- **الملف/الأسطر:** `bot/core/exchange.py:153-205`
- **الدليل:** `create_order(type='market')` يُنفذ أولاً. فشل أمر stop-loss يُلتقط في `except Exception as sl_err` ويُسجل فقط، وفشل take-profit يُلتقط بالطريقة نفسها، ثم تعيد الدالة `order` في السطر 205 وكأن العملية ناجحة. لا يوجد إلغاء لأمر الدخول أو retry مضبوط أو حالة `UNPROTECTED`.
- **الأثر:** يمكن أن يُحفظ المركز كـ`OPEN` في `main.py:321-352` مع عدم وجود SL أو TP، بينما النظام يفترض ضمنياً أنه محمي. هذا mismatch بين حالة المنصة والحالة المحلية قد يترك مركزاً مكشوفاً.
- **الإصلاح:** اعتبر العملية atomic على مستوى workflow: بعد فشل أي حماية، أعد المحاولة بتأخير محدود وtimeout، ثم ألغِ/اعكس أمر الدخول إن أمكن أو سجّل المركز فوراً كـ`UNPROTECTED` وأوقف فتح صفقات جديدة حتى reconciliation. خزّن IDs لأوامر الدخول والحماية وتحقق من حالتها قبل إعلان النجاح.
- **الثقة:** مؤكدة من control flow؛ لا يلزم تنفيذ أمر حقيقي لإثباتها.

### ACON-005 — عميل ccxt إضافي يُنشأ ولا يُغلق عند استخدام exchange مصدر موحد

- **الخطورة:** عالية
- **الملف/الأسطر:** `bot/data/market_data.py:29-38, 40-86` (والتعريف الفعلي المستخدم مكرر في `468-526`); `bot/main.py:36-38, 590-600`
- **الدليل:** `ApexTraderBot` ينشئ `ExchangeManager` ثم يمرره إلى `MarketDataManager`. رغم ذلك، `MarketDataManager.__init__` يستدعي `_init_exchange()` وينشئ ccxt client خاصاً به. عند وجود `exchange_source`، جلب OHLCV يستخدم `self._exchange_source._exchange` (الأسطر 568-574 في التعريف الفعلي)، بينما `_load_markets()` يستعمل العميل المحلي. في shutdown تُغلق `self.exchange` فقط؛ لا يوجد `await self.market_data.close()` في `bot/main.py:590-600`.
- **الأثر:** connector/session الخاص بعميل market-data المحلي يبقى مفتوحاً حتى GC/نهاية العملية، وقد يظهر تحذير `Unclosed connector` وتسرب موارد. كما أن load_markets وجلب OHLCV يحدثان على عميلين مختلفين، ما يجعل lifecycle والكاش/حدود المعدل غير موحدين.
- **الإصلاح:** لا تنشئ fallback client عندما يُمرر `exchange_source`، أو اجعل MarketDataManager يملك العميل الوحيد بوضوح. أضف إغلاقاً idempotent لكل المكونات (`await market_data.close()` ثم exchange) في shutdown، مع ترتيب إغلاق بعد توقف كل المهام.
- **الثقة:** مؤكدة من الإنشاء والإغلاق الظاهرين؛ لم أفتح اتصالاً.

### ACON-006 — عمليات load/cache غير محمية وقد تتكرر تحت `gather`

- **الخطورة:** متوسطة
- **الملف/الأسطر:** `bot/data/market_data.py:104-112, 120-135` (والنسخة الفعلية `539-570`); `bot/data/market_data.py:362-397` (والنسخة الفعلية `800-835`)
- **الدليل:** `get_multiple_ohlcv` ينشئ coroutines لكل symbol ثم يشغلها مع `asyncio.gather`. عند cache miss، كل coroutine قد يمر في `_load_markets` بينما `_markets_loaded` ما زال `False`، ثم يستدعي `load_markets()` بصورة متكررة. لا يوجد lock أو in-flight future، والكاش عبارة عن dict عادي بلا حماية من miss متزامن. التعريف المكرر للفئة يجعل النسخة الأولى ميتة، لكن النسخة الثانية تحتوي على السلوك نفسه.
- **الأثر:** طلبات market metadata مكررة، ضغط/تأخير غير ضروري على ccxt، واحتمال تجاوز حدود المعدل أو اختلاف ترتيب الكتابة في cache. لا توجد حماية من duplicate fetch لنفس key تحت استدعاءات متزامنة.
- **الإصلاح:** استخدم `asyncio.Lock` لـ`load_markets` وper-key single-flight/in-flight task للكاش، أو اجعل عملية التهيئة مرة واحدة قبل fan-out. وحّد تعريف MarketDataManager واحذف النسخة المكررة لتقليل أخطاء lifecycle.
- **الثقة:** مؤكدة كاحتمال تزامن من `gather` وغياب lock؛ الأثر التشغيلي المحدد يعتمد على عدد المستهلكين.

### ACON-007 — حفظ الصفقة ليس جزءاً من workflow الأمر ولا يُتحقق من نتيجته

- **الخطورة:** عالية
- **الملف/الأسطر:** `bot/main.py:311-352, 458-497`; `bot/data/state_manager.py:139-152`
- **الدليل:** بعد نجاح `exchange.place_order` يستدعي main `save_trade_state(trade_record)` دون `await` (لأنها sync) ودون فحص قيمة الإرجاع. `save_trade_state` يلتقط كل Exception ويعيد `False`، لذلك يمكن أن يفشل upsert بينما يستمر main ويعتبر الصفقة مفتوحة. لا توجد reconciliation أو retry/idempotent transaction تربط order ID بسجل الحالة.
- **الأثر:** مركز موجود على المنصة قد لا يظهر في Supabase، وبالتالي لا يُستعاد في `get_open_trades_from_db` ولا تُدار حمايته/إغلاقه من التطبيق بعد restart. كما أن إعادة المحاولة قد تنشئ أمراً ثانياً لأن حالة الحفظ غير مؤكدة.
- **الإصلاح:** اجعل حفظ order intent/result جزءاً من state machine واضحة (`PENDING_ORDER`, `OPEN`, `STATE_SYNC_FAILED`) مع retry محدود وidempotency على `trades.id`، ثم reconciliation دوري من أوامر/مراكز ccxt قبل السماح بأمر جديد. لا تُرجع نجاح دورة التداول قبل معرفة نتيجة الحفظ أو عزل المركز غير المتزامن.
- **الثقة:** مؤكدة من تجاهل return value ومسار الاستثناء.

### ACON-008 — pending signal تُعلّم processed بلا تحقق من الصف المتأثر

- **الخطورة:** عالية
- **الملف/الأسطر:** `bot/data/state_manager.py:241-254`
- **الدليل:** `mark_signal_processed` ينفذ `.update({...}).eq('id', signal_id).execute()` بلا `.eq('status','pending')`، ولا يفحص `res.data`/عدد الصفوف المتأثرة، ومع ذلك يعيد `True` بعد عدم رفع Exception. هذا ليس claim مشروطاً بالحالة، ولا يثبت أن الصف الذي عولج ما زال pending أو أن update أصاب صفاً واحداً.
- **الأثر:** عاملان قد يعالجان الصف نفسه؛ كلاهما قد ينجح في وضع processed بعد تنفيذ أمرين. كما يمكن أن تُعتبر العملية ناجحة رغم أن update لم يغير صفاً، فتضيع قابلية إعادة المعالجة أو تُخفى حالة تناقض.
- **الإصلاح:** استخدم update مشروطاً `id AND status='pending'`، افحص عدد/بيانات الصفوف المتأثرة، واعتبر نجاح claim/transition شرطاً قبل تنفيذ الأمر. الأفضل تنفيذ claim ونتيجة التنفيذ في transaction أو RPC ذرية.
- **الثقة:** مؤكدة من الاستعلام المعروض؛ لم أختبر سلوك Supabase الفعلي.

### ACON-009 — لا توجد مهلة مستقلة لمسار HTTP في Worker أو عمليات Supabase المتزامنة

- **الخطورة:** متوسطة
- **الملف/الأسطر:** `src/worker.js:56-67`; `bot/data/state_manager.py:75-81, 111, 145, 163, 246-249`
- **الدليل:** Worker يستدعي `fetch(...)` إلى REST API دون `AbortSignal`/timeout أو retry policy. في Python، كل استدعاءات Supabase المتزامنة المذكورة تستخدم `.execute()` مباشرة ولا توجد مهلة محلية. timeout ccxt (15 ثانية) لا يغطي Supabase أو Worker.
- **الأثر:** طلب webhook قد يظل معلقاً أو يتأخر حتى مهلة المنصة المستضيفة، وقد يتلقى المُرسل retry بينما الطلب الأصلي ربما وصل فعلاً؛ مع غياب idempotency (ACON-003) يؤدي ذلك إلى إشارات/أوامر مكررة. وفي Python يحجز الطلب event loop (ACON-002).
- **الإصلاح:** أضف timeout صريحاً قابلاً للإلغاء إلى HTTP Worker، وحدد retry فقط للأخطاء القابلة لإعادة المحاولة مع backoff ويدعم idempotency key. في Python استخدم عميل async أو thread offload مع timeout، ولا تعِد المحاولة تلقائياً على عمليات create order إلا عبر order/client ID idempotent.
- **الثقة:** مؤكدة من غياب timeout في المواضع المقروءة؛ حدود timeout الافتراضية الخارجية غير مفترضة.

## ما تم تغطيته

- `bot/main.py`: startup، initialize، heartbeat، دورة السوق، pending webhook، direct aiohttp webhook، run loop، cancellation، shutdown.
- `bot/core/exchange.py`: ccxt async client، fetch balance/ticker/OHLCV، create market/SL/TP، close position، close lifecycle، timeout 15s.
- `bot/data/market_data.py`: client duplication، load_markets، cache، `asyncio.gather`، الإغلاق، والتعريف المكرر للفئة.
- `bot/data/state_manager.py`: Supabase initialization/probe، synchronous `.execute()`، heartbeat/status/trades، pending signals، processed transition، reconstruction.
- `bot/notifications/telegram_notifier.py`: `aiohttp.ClientSession` داخل context لكل محاولة، total timeout 10s، retries و429 و`asyncio.sleep`; لم أجد leak مثبتاً في هذا المسار لأن الجلسة داخل `async with`.
- `src/worker.js`: POST validation، Supabase REST `fetch`، webhook ID generation، غياب timeout/idempotency.
- `database/schema.sql`: بنية `pending_signals` و`trades` والفهارس؛ لا يوجد قيد unique على `webhook_id` ولا آلية claim/processing.
- `tests/` وملفات التكامل: فحصت ما يتصل بالمكونات، ولم أشغّل اختبارات قد تتصل بخدمات أو تستخدم مفاتيح.
- بحثت عن Redis: الاستخدام الإنتاجي غير موجود في المسارات المدققة؛ `redis.asyncio` يظهر في `bot/main.py` كاستيراد غير مستخدم، بينما `test_connections.py` ينشئ Redis للاختبار فقط. لذلك لا يمكن إثبات race أو leak في Redis من هذا المستودع.

## الحدود

هذا تدقيق ساكن/قراءة فقط ولم يُنفّذ تداول، ولم تُستخدم مفاتيح أو بيانات خارجية، ولم تُختبر استجابات ccxt/Supabase/Telegram الحقيقية أو سياسات الشبكة/الخادم المستضيف. لم أعدّ السلوكيات التي لا دليل مباشر عليها عيوباً مؤكدة؛ مثلاً لم أبلغ عن تسرب جلسة Telegram لأن `ClientSession` مغلق داخل `async with`. كما أن نتائج الأداء الفعلية وتفاصيل timeout الافتراضية تعتمد على إصدارات العملاء والبيئة، بينما النتائج أعلاه مبنية على control flow والـschema الموجودين في المستودع.
