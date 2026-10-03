# تدقيق أمان Supabase وخطة المعالجة

آخر فحص: 2026-10-04. تم فحص المشروع `apex-trader` قراءةً فقط بعد تطبيق RLS على `strategy_signals`.

## الحالة الحالية

- `strategy_signals`: **تمت معالجته**؛ RLS مفعّل، والقراءة للمستخدم المسجل فقط، والكتابة للبوت عبر `service_role`.
- لا يوجد تحذير `rls_disabled_in_public` لهذا الجدول.
- تحذير `RLS enabled without policy` المتبقي يخص الجداول الداخلية:
  - `execution_leases`
  - `pending_signals`
  - `position_slots`
  - `reconciliation_runs`
  - `system_logs`
- تحذير `security_definer_view`: سبعة Views للوحة تستخدم `SECURITY DEFINER`.
- تحذير `function_search_path_mutable`: الدالتان `update_updated_at()` و`handle_new_user()`.
- تحذيرا صلاحيات الدوال: ثماني دوال تشغيلية `SECURITY DEFINER` قابلة للتنفيذ حاليًا من `anon` و`authenticated`.
- حماية كلمات المرور المسربة في Supabase Auth غير مفعّلة؛ هذه إعدادات Auth Dashboard وليست SQL migration.

## SQL المقترح للجداول الداخلية

لم يتم تطبيق هذا الجزء تلقائيًا لأن منح/سحب الصلاحيات قد يغيّر سلوك خدمات الإنتاج. الاقتراح يحصر التعامل المباشر في `service_role` ولا يفتح الجداول للوحة:

```sql
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'execution_leases',
    'pending_signals',
    'position_slots',
    'reconciliation_runs',
    'system_logs'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', table_name);
    EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', table_name);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', table_name || '_service_role_all', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
      table_name || '_service_role_all', table_name
    );
  END LOOP;
END
$$;
```

## SQL المقترح للدوال التشغيلية

هذه الدوال تُستدعى من البوت/Worker عبر مفتاح الخدمة، وليست واجهة عامة للمستخدمين:

```sql
REVOKE EXECUTE ON FUNCTION public.acquire_execution_lease(text, text, integer, jsonb) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.activate_universe_snapshot(text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.bind_position_slot(text, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.release_execution_lease(text, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.release_position_slot(text, text, text) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.renew_execution_lease(text, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.reserve_position_slot(text, text, text, integer) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.acquire_execution_lease(text, text, integer, jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.activate_universe_snapshot(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.bind_position_slot(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.release_execution_lease(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.release_position_slot(text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_execution_lease(text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.reserve_position_slot(text, text, text, integer) TO service_role;
```

`handle_new_user()` is normally invoked by an Auth trigger as its owner; verify the trigger before revoking `PUBLIC`. If the trigger depends on an invoker grant, retain only the minimum required role instead of granting it to `anon`.

## SQL المقترح لـ search_path

```sql
ALTER FUNCTION public.update_updated_at() SET search_path = public, pg_catalog;
ALTER FUNCTION public.handle_new_user() SET search_path = public, pg_catalog;
```

## Views لوحة التحكم

تحويل Views إلى `SECURITY INVOKER` يزيل التحذير، لكنه قد يجعل لوحة المستخدمين ترى صفوفًا فارغة لأن الجداول الأساسية لديها RLS ولا توجد سياسات قراءة مباشرة. لذلك يجب اختيار أحد المسارين قبل التطبيق:

1. إنشاء سياسات `SELECT` دقيقة على جداول العرض للمستخدمين المسجلين، ثم تحويل Views إلى `SECURITY INVOKER`.
2. إبقاء Views كـ`SECURITY DEFINER` مع مراجعة مالكها، الأعمدة المكشوفة، وعدم استخدام مدخلات مستخدم داخل SQL ديناميكي.

Views المتأثرة: `dashboard_risk_state`, `dashboard_universe`, `dashboard_reconciliation_status`, `dashboard_daily_summary`, `dashboard_positions`, `dashboard_trade_summary`, `dashboard_strategy_subtype_performance`.

## اختبار RLS المضاف

أضيف اختبار تكامل اختياري يستخدم نفس مسار `StateManager.record_strategy_signal`:

- يختبر كتابة وقراءة `service_role`.
- يختبر رفض القراءة لدور `anon`.
- يختبر القراءة لدور `authenticated` عند توفير حساب اختبار مخصص.
- ينظف صف الاختبار في `finally`.
- لا يعمل تلقائيًا محليًا إلا عند ضبط `RUN_SUPABASE_INTEGRATION=1`.

لا تُستخدم بيانات حساب شخصي؛ يلزم حساب Supabase اختبار مخصص عبر متغيرات الأسرار.
