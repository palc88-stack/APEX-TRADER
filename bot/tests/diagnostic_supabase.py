#!/usr/bin/env python3
"""
diagnostic_supabase.py — تشخيص اتصال Supabase في بيئة GitHub Actions

يحاول:
1. قراءة SUPABASE_URL و SUPABASE_KEY من البيئة
2. إنشاء عميل Supabase
3. اختبار الاتصال (SELECT من bot_state)
4. محاولة كتابة صف تجريبي (upsert)
5. قراءته مجدداً
6. إخراج النتيجة كمخرجات 워크فロー

يُستخدم عبر workflow كخطوة تشخيصية.
"""

import os
import sys
import json
import traceback
from datetime import datetime, timezone

from supabase import create_client


def main():
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "supabase_url_set": False,
        "supabase_key_set": False,
        "url_value": None,
        "key_value": None,  # لن يتم إظهار القيمة الفعلية لأسباب أمنية
        "client_created": False,
        "connectivity_test": None,
        "connectivity_test_error": None,
        "write_test": None,
        "write_test_error": None,
        "read_back": None,
        "read_back_error": None,
        "overall_status": "unknown",
    }

    # 1. قراءة المتغيرات
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")

    results["supabase_url_set"] = bool(url and url.strip())
    results["supabase_key_set"] = bool(key and key.strip())
    results["url_value"] = url if url else ""
    # لا تظهر القيمة الفعلية
    results["key_value"] = "***SET***" if key else ""

    if not results["supabase_url_set"] or not results["supabase_key_set"]:
        results["overall_status"] = "failed_missing_env"
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1

    # 2. إنشاء العميل
    try:
        client = create_client(url, key)
        results["client_created"] = True
    except Exception as e:
        results["client_created"] = False
        results["connectivity_test_error"] = f"Client creation failed: {str(e)}"
        results["overall_status"] = "failed_client_creation"
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 1

    # 3. اختبار الاتصال (SELECT)
    try:
        resp = client.table("bot_state").select("*").limit(1).execute()
        results["connectivity_test"] = "success"
        # حفظ بيانات الاستجابة للتشخيص
        if hasattr(resp, 'data') and resp.data:
            results["existing_rows"] = len(resp.data)
            results["sample_row"] = resp.data[0] if resp.data else None
        else:
            results["existing_rows"] = 0
    except Exception as e:
        results["connectivity_test"] = "failed"
        results["connectivity_test_error"] = f"{type(e).__name__}: {str(e)}"
        # لا ن exit هنا — نكمل لاختبار الكتابة

    # 4. محاولة الكتابة (upsert صف تجريبي)
    test_row = {
        "id": 999,  # id مميز للتجربة
        "is_running": True,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current_balance": 99999.0,
        "active_mode": "DIAGNOSTIC",
    }
    try:
        write_resp = client.table("bot_state").upsert(test_row).execute()
        results["write_test"] = "success"
        # حفظ معلومات الاستجابة
        if hasattr(write_resp, 'data'):
            results["write_response_data"] = write_resp.data
        elif hasattr(write_resp, 'error'):
            results["write_test"] = f"error response: {write_resp.error}"
    except Exception as e:
        results["write_test"] = "failed"
        results["write_test_error"] = f"{type(e).__name__}: {str(e)}"

    # 5. قراءة الصف التجريبي
    try:
        read_resp = client.table("bot_state").select("*").eq("id", 999).execute()
        if hasattr(read_resp, 'data') and read_resp.data:
            results["read_back"] = "success"
            results["read_back_data"] = read_resp.data
        else:
            results["read_back"] = "not_found"
    except Exception as e:
        results["read_back"] = "failed"
        results["read_back_error"] = f"{type(e).__name__}: {str(e)}"

    # 6. تحديد الحالة الكلية
    if results["connectivity_test"] == "success" and results["write_test"] == "success":
        results["overall_status"] = "success"
    elif results["connectivity_test"] == "success" and results["write_test"] in ("failed", "error response"):
        results["overall_status"] = "failed_write"
    elif results["connectivity_test"] in ("failed", None):
        results["overall_status"] = "failed_connectivity"
    else:
        results["overall_status"] = "unknown"

    # إخراج النتيجة
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if results["overall_status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
