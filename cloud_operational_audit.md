# الفحص التشغيلي المنفصل للخدمات الخارجية — APEX-TRADER

**التاريخ:** 2026-09-26  
**الوضع:** قراءة وتشخيص آمن فقط؛ لم تُجرَ أي كتابة أو نشر أو صفقة أو رسالة Telegram من هذه الجلسة.

## القرار التشغيلي الحالي

المراجعة السحابية **لم تكتمل 100% من ناحية إعدادات الحسابات الخارجية** بسبب عدم وجود موصلات/اعتمادات Cloudflare وSupabase وTelegram في الجلسة. لكنها اكتملت بالنسبة إلى الحالة الخارجية التي يمكن قراءتها بأمان عبر GitHub ونتائج التشغيل السابقة.

النتيجة الحالية: **NO-GO للتداول الحقيقي**.

## الأدلة التشغيلية المؤكدة

### GitHub

- المستودع عام `palc88-stack/APEX-TRADER`، الفرع الافتراضي `main`، وActions مفعلة.
- Workflow `Binance Trading Cycle` ما زال نشطاً ويعمل بجدولة كل 15 دقيقة تقريباً.
- آخر تشغيل مرئي رقم `36243467282` انتهى بحالة GitHub `success`، لكنه لا يعني سلامة التداول؛ خطوة `Run bot cycle` نفسها نفذت خلال ثوانٍ مع أخطاء داخلية سجلها البوت.
- لا توجد حماية Branch Protection على `main`؛ واجهة GitHub أعادت `Branch not protected`.
- إعداد GitHub لا يفرض SHA pinning للـActions، وworkflow الحالي يستخدم tags مثل `actions/checkout@v4`.
- محاولة قراءة أسماء Repository Secrets أعادت HTTP 403 من GitHub API؛ لذلك لم يتم كشف أو اختبار أسماء/صلاحيات الأسرار الفعلية.
- توجد بيئات GitHub مسماة `Production` و`Preview`، لكن لم يمكن التحقق من قواعد الموافقة/الحماية الخاصة بها عبر صلاحية القراءة المتاحة.

### Supabase — دليل تشغيلي من آخر تشغيل GitHub

من سجل آخر تشغيل، وبقيم الأسرار محجوبة:

- إنشاء عميل Supabase نجح، واختبار الاتصال الأساسي نجح.
- استعلام `pending_signals` فشل صراحةً بالخطأ `PGRST205`: الجدول `public.pending_signals` غير موجود في schema cache، مع اقتراح جدول `public.positions`.
- هذا يثبت وجود عدم تطابق بين `database/schema.sql` في المستودع وقاعدة Supabase التي استخدمها GitHub وقت التشغيل، أو أن migration لم تُطبّق/لم تُحدّث schema cache.
- تشخيص الكتابة حاول الكتابة إلى `bot_state` بالصف `id=999` وفشل بالخطأ `23514` بسبب constraint `single_row`. الفشل متوقع بالنسبة لهذا الاختبار، لكنه يثبت أن ملف التشخيص الحالي يحاول الكتابة إلى قاعدة تشغيلية.
- التشخيص أعاد صف `bot_state` موجوداً في قاعدة التشغيل، ما يثبت أن قاعدة Supabase ليست مجرد placeholder.
- نتيجة التشغيل أظهرت أن حد الخسارة اليومي المخزن كان أكبر بكثير من نسبة 4% المقصودة، وهو متسق مع خطأ الحساب الموجود في الكود.
- آخر دورة سجلت فشل `get_ticker` لأن قيمة `last` كانت `None`، ثم استمر workflow كـ`success` لأن مسار الأخطاء داخل البوت لا يفشل Job بالضرورة.
- الـworkflow رفع artifact باسم تشخيص Supabase بحجم 789 bytes، حتى عند فشل التشخيص.

### Cloudflare Pages / Workers

- لم يوجد في GitHub deployment history أي deployment منشور بواسطة Cloudflare؛ السجلات المتاحة تشير إلى `vercel[bot]` فقط.
- إعداد `web/wrangler.jsonc` موجود في المستودع، لكنه لا يثبت وجود نشر Cloudflare فعلي أو ربط Pages فعلي.
- `workers_dev: true` في الملف المحلي لا يثبت أن Worker منشور أو أن Secrets موجودة.
- لم يمكن اختبار Cloudflare API أو Worker endpoint لعدم وجود `CLOUDFLARE_API_TOKEN` أو `CLOUDFLARE_ACCOUNT_ID` أو موصل Cloudflare.
- رابطا Vercel اللذان ظهرا في سجلات النشر أعادا HTTP 410 `Gone` عند فحص GET الآمن، ما يعني أن تلك deployment URLs غير صالحة حالياً أو انتهت.

### Vercel — اكتشاف غير متوقع

- GitHub يسجل عشرات deployments بواسطة `vercel[bot]` في بيئتي `Production – apex-trader` و`Production – apex-trader-66hc`.
- بعض deployments السابقة حالتها `success`، لكن URLs التي فُحصت الآن أعادت `410 Gone`.
- لا يوجد `homepageUrl` دائم للمستودع، لذلك لم يمكن تحديد النطاق الحالي للواجهة.
- هذا يحتاج قراراً معمارياً: هل النشر المقصود Vercel أم Cloudflare Pages؟ وجود الاثنين دون مصدر حقيقة واضح يزيد خطر تشغيل واجهة قديمة أو إعدادات Supabase مختلفة.

### Telegram

- لم يُختبر Telegram Bot API تشغيلياً؛ لا يوجد Token أو connector في الجلسة.
- لم تُرسل أي رسالة.
- من الكود فقط، Telegram يستخدم endpoint ثابتاً، لكن لا يمكن التحقق من صحة Token أو Chat ID أو صلاحيات البوت أو وصول الرسائل.
- يلزم اختبار آمن محدود مثل `getMe` فقط، ثم اختبار إرسال إلى Chat اختبار منفصل، وليس إلى قناة الإنتاج.

### Binance / Bybit

- لم يُجرَ اتصال مباشر من هذه الجلسة ولم تُستخدم مفاتيح.
- سجل GitHub يثبت أن workflow يملك متغيرات أسرار مرتبطة بالبورصة، لكنه لا يثبت نوع الحساب أو Testnet/Live أو عدم إرسال أمر.
- آخر تشغيل وصل إلى دورة البوت وسجل فشل ticker؛ لا توجد في السجل المقروء قرينة على نجاح `create_order`.
- لا يجوز اعتبار نجاح Job دليلاً على أن التشغيل Testnet أو أن بوابة Live موجودة.

## الخلاصة الفنية

أثبت الفحص التشغيلي ثلاث مشكلات إضافية/مؤكدة عملياً:

1. **Schema drift:** المستودع يتوقع `pending_signals`، بينما قاعدة Supabase التشغيلية التي وصل إليها GitHub لا تعرض الجدول في schema cache.
2. **False-success CI:** workflow ينتهي `success` رغم فشل ticker وفشل قراءة pending signals؛ لأن الأخطاء تُلتقط داخل التطبيق ولا تُحوّل إلى فشل Job.
3. **Deployment drift:** الكود يوثق Cloudflare، لكن سجلات GitHub الفعلية تشير إلى Vercel deployments، والروابط المفحوصة أصبحت `410 Gone`.

## ما يلزم لإكمال 100% بأمان

يلزم توفير/تفعيل موصلات أو صلاحيات قراءة فقط أولاً:

- Cloudflare: API Token محدود للقراءة + Account ID، أو موصل Cloudflare.
- Supabase: URL وAnon key للاختبار، ويفضل مشروع/Branch معزول لتجربة migration وRLS. لا يلزم service-role للفحص الأول.
- Telegram: Bot Token وChat ID لاختبار `getMe` فقط ثم رسالة اختبار إلى Chat غير إنتاجي.
- GitHub: صلاحية قراءة Actions secrets metadata/environments إن أريد التحقق من الحماية الفعلية؛ لا حاجة لكشف قيم الأسرار.
- Binance/Bybit: مفاتيح Testnet منفصلة فقط إذا أريد smoke test غير مالي؛ لا تستخدم مفاتيح Live.

لن تُنفذ أي كتابة في Supabase أو نشر Cloudflare أو إرسال Telegram أو أمر بورصة إلا بعد عزل البيئة وتحديد النطاق صراحةً.
