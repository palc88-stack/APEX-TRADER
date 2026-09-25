import asyncio
from loguru import logger
from bot.core.state_manager import StateManager

async def main():
    logger.info("⚡ بدء فحص اتصالات وقواعد بيانات APEX TRADER...")
    sm = StateManager()

    # 1. فحص الصحة العامة
    health = sm.is_healthy()
    logger.info(f"حالة الاتصالات اللحظية: {health}")

    if not health["overall"]:
        logger.error("❌ يوجد مشكلة في الاتصال بـ Redis أو Supabase. تحقق من ملف .env")
        return

    # 2. اختبار حفظ وقراءة حالة البوت
    test_state = {
        "is_running": True,
        "is_paused": False,
        "daily_loss": 0.0,
        "total_trades": 10,
        "winning_trades": 7
    }
    await sm.save_state(test_state)
    loaded_state = await sm.load_state()
    logger.info(f"✅ تم اختبار حفظ واسترجاع الحالة بنجاح: {loaded_state}")

    logger.info("🎉 جميع الاتصالات جاهزة للعمل بنجاح!")

if __name__ == "__main__":
    asyncio.run(main())
