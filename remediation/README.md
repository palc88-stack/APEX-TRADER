# حزمة إصلاحات APEX-TRADER

هذه الحزمة **لا تعدّل كود الإنتاج تلقائياً**. الملفات هنا حلول مرجعية كاملة للملفات الصغيرة/المعزولة، أُنشئت بعد التدقيق الساكن، ويجب تطبيقها أولاً في مشروع Supabase وبيئة Testnet مع مراجعة بشرية.

## الملفات

| الملف | الغرض | الحالة |
|---|---|---|
| `database/001_security_idempotency.sql` | تفعيل RLS، منع كتابة المتصفح، UNIQUE للإشارة، حالات processing، ودالة claim ذرية | يحتاج مراجعة grants واسم دور الكتابة |
| `src/worker.js` | Worker كامل يتحقق من body/schema/enum/price/id، يستخدم timeout، ولا يملك service-key fallback | يحتاج ضبط `SUPABASE_WRITE_KEY` كـsecret محدود |
| `.github/workflows/binance-testnet.yml` | CI كامل لـTestnet/unit/build مع concurrency ومنع Live | لا يشغّل البوت ولا أياً من مفاتيح Live |
| `verification/check_critical_findings.py` | فحص ساكن يعيد إنتاج الأنماط الخطرة الحالية دون شبكة | يجب تشغيله قبل وبعد كل إصلاح |

## ترتيب التطبيق

1. أنشئ مشروع Supabase اختبارياً، طبّق migration، وراجع RLS/grants من anon وauthenticated وservice-role.
2. اختبر Worker في بيئة معزولة. لا تستخدم `SUPABASE_SERVICE_KEY` كبديل؛ استخدم secret منفصلاً محدوداً أو backend موثوقاً.
3. أضف workflow الاختباري وشغّل compile/unit/build فقط. لا تنقل مفاتيح Live إلى هذا workflow.
4. أعد تصميم طبقة الأوامر قبل أي تشغيل حقيقي: `reduce_only_close`، precision/limits، set leverage، fill reconciliation، حماية fail-closed، وإلغاء SL/TP القديمة.
5. نفّذ state machine للإشارة والصفقة: `pending → processing → processed/failed`، مع lease وidempotency وربط order ID.
6. أصلح daily-loss: نسبة `/100` في موضع واحد، يوم UTC ثابت، استعادة ذرية، وعدم فتح صفقات عند فشل استعادة الحالة.
7. بعد ذلك فقط أضف contract tests للمنصة وrestart/concurrency/failure tests على Testnet، ثم راجع بوابة Live منفصلة ومحمية.

## ما لم أكتبه كتبديل تخميني

لم أضع إعادة كتابة كاملة لـ`bot/main.py` أو `bot/core/exchange.py` هنا، لأن ذلك يتطلب اختيار عقد Binance/Bybit النهائي (futures/spot، hedge/one-way، closePosition مقابل كمية reduce-only، semantics للـfills والرسوم) وبيانات اختبار Testnet حقيقية. تقديم ملف بديل كامل دون هذا العقد سيكون كوداً تخمينياً وقد يزيد خطر التداول، وهو مخالف لشرط عدم اختراع بيانات أو سلوك منصة.

## قرار التشغيل

حتى تُغلق النتائج C-01 إلى C-12 وتُثبت اختبارات الفشل/التزامن/إعادة التشغيل على بيئة معزولة، القرار هو **NO-GO للتداول الحقيقي**. نجاح `14 passed` وبناء React لا يثبت سلامة الأوامر أو صلاحيات Supabase أو الحماية المالية.
