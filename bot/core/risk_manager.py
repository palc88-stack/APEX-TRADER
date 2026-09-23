# ======================================
# APEX TRADER - Risk Manager
# النسخة النهائية الإنتاجية v5.0
# ======================================

import math
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from loguru import logger

from bot.config import config
from bot.core.fee_calculator import FeeCalculator
from bot.signals.signal_engine import TradeSignal


# ══════════════════════════════════════════════════════════════
# أدوات مساعدة
# ══════════════════════════════════════════════════════════════

def _utc_today() -> date:
    """التاريخ الحالي بتوقيت UTC — آمن لجميع السيرفرات."""
    return datetime.now(timezone.utc).date()


def _safe_float(value: object, default: float = 0.0) -> float:
    """
    تحويل آمن إلى float.
    يرفض NaN و Infinity ويعيد القيمة الافتراضية بدلاً منهما.
    """
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _get_risk_setting(value: object, name: str) -> Optional[float]:
    """
    قراءة إعداد مخاطر حرج.
    يرفض أي قيمة غير صالحة أو سالبة أو صفر.
    يسجل خطأ حرج بدل استخدام قيمة افتراضية صامتة.
    """
    result = _safe_float(value, default=-1.0)
    if result <= 0:
        logger.critical(
            f"❌ إعداد المخاطر غير صالح: {name}={value!r} — "
            f"سيتم رفض جميع الصفقات"
        )
        return None
    return result


def _validate_leverage_setting(
    value: object,
    name: str,
) -> Optional[int]:
    """
    التحقق من إعداد الرافعة — يجب أن يكون عدداً صحيحاً >= 1.
    يرفض القيم غير الصحيحة مثل 0.5 أو -1 أو NaN.
    """
    raw = _safe_float(value, default=-1.0)

    if raw < 1:
        logger.critical(
            f"❌ إعداد الرافعة غير صالح: {name}={value!r} — "
            f"يجب أن يكون >= 1"
        )
        return None

    if not float(raw).is_integer():
        logger.critical(
            f"❌ إعداد الرافعة غير صحيح: {name}={value!r} — "
            f"يجب أن يكون عدداً صحيحاً"
        )
        return None

    return int(raw)


# ══════════════════════════════════════════════════════════════
# الثوابت
# ══════════════════════════════════════════════════════════════

_MAX_OPEN_POSITIONS: int    = 5      # الحد الأقصى للمراكز المفتوحة
_WARN_OPEN_POSITIONS: int   = 3      # حد التحذير للمراكز المفتوحة
_MIN_BALANCE_USD: float     = 10.0   # الحد الأدنى للرصيد بالدولار
_MIN_TRADE_SIZE_USD: float  = 1.0    # الحد الأدنى لحجم الصفقة بالدولار
_RECOVERY_MAX_LEVERAGE: int = 10     # الحد الأقصى للرافعة في وضع الاسترداد
_RECOVERY_THRESHOLD: float  = 0.50   # عتبة تفعيل وضع الاسترداد (50%)
_WARNING_THRESHOLD: float   = 0.75   # عتبة التحذير (75%)


# ══════════════════════════════════════════════════════════════
# نتيجة الفحص
# ══════════════════════════════════════════════════════════════

@dataclass
class RiskCheckResult:
    """
    نتيجة فحص المخاطر.

    Attributes:
        approved:           هل تمت الموافقة على الصفقة؟
        reason:             سبب القبول أو الرفض.
        adjusted_size:      الهامش المعدَّل بالدولار.
        adjusted_leverage:  الرافعة المعدَّلة.
        warnings:           تحذيرات غير حاجبة للصفقة.
        reservation_id:     معرف الحجز (يُملأ فقط بعد approve_and_reserve).
    """
    approved: bool
    reason: str = ""
    adjusted_size: float = 0.0
    adjusted_leverage: int = 0
    warnings: List[str] = field(default_factory=list)
    reservation_id: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# مدير المخاطر
# ══════════════════════════════════════════════════════════════

class RiskManager:
    """
    مدير المخاطر المركزي — الحارس الأول لرأس المال.

    ══════════════════════════════════════════
    التدفق الصحيح لفتح صفقة:
    ══════════════════════════════════════════

        result = risk.approve_and_reserve_position(signal, balance)
        if not result.approved:
            return

        try:
            order = await exchange.open_position(
                size=result.adjusted_size,
                leverage=result.adjusted_leverage,
            )
        except Exception:
            risk.release_reserved_position(result.reservation_id)
            raise

    ══════════════════════════════════════════
    التدفق الصحيح لإغلاق صفقة:
    ══════════════════════════════════════════

        risk.position_closed(pnl=realized_pnl)

    ══════════════════════════════════════════
    سياسة الخسارة اليومية:
    ══════════════════════════════════════════

        تشمل فقط الخسائر المحققة (Realized PnL).
        لاحتساب الخسائر العائمة، استدعِ:
            risk.update_unrealized_loss(current_unrealized_loss)
        من طبقة التنفيذ دورياً.

    ══════════════════════════════════════════
    حساب حجم الصفقة:
    ══════════════════════════════════════════

        يعتمد على المسافة إلى Stop Loss وليس position_size_pct فقط.
        المعادلة:
            الخسارة المسموحة = رصيد بداية اليوم × حد الخسارة - الخسارة الحالية
            الحجم الأقصى    = الخسارة المسموحة / نسبة المسافة إلى SL
    """

    def __init__(self) -> None:
        self.fee_calculator = FeeCalculator()
        self._lock = threading.RLock()

        # الحالة اليومية
        self._daily_loss: float               = 0.0
        self._daily_loss_date: date           = _utc_today()   # ✅ الإصلاح الجوهري
        self._day_start_balance: Optional[float] = None        # ✅ رصيد بداية اليوم
        self._daily_trades: int               = 0
        self._unrealized_loss: float          = 0.0            # ✅ الخسائر العائمة

        # المراكز
        self._open_positions: int = 0
        self._reservations: Dict[str, bool] = {}               # ✅ معرفات الحجز

        # حالة التداول
        self._trading_halted: bool = False                     # ✅ إيقاف الطوارئ

        logger.info("✅ Risk Manager جاهز")

    # ══════════════════════════════════════════════════════════
    # خصائص
    # ══════════════════════════════════════════════════════════

    @property
    def daily_loss(self) -> float:
        """
        الخسارة اليومية المحققة بالدولار بتوقيت UTC.
        تُصفَّر تلقائياً عند بداية يوم UTC جديد.
        """
        today = _utc_today()
        with self._lock:
            if self._daily_loss_date != today:
                self._daily_loss        = 0.0
                self._daily_trades      = 0
                self._day_start_balance = None
                self._unrealized_loss   = 0.0
                self._daily_loss_date   = today
                self._trading_halted    = False
                logger.info("🌅 يوم UTC جديد — تم تصفير الحالة اليومية")
            return max(0.0, self._daily_loss)

    @property
    def total_daily_loss(self) -> float:
        """
        مجموع الخسائر المحققة والعائمة.
        يُستخدم لاتخاذ قرار منع التداول بشكل استباقي.
        """
        with self._lock:
            return max(0.0, self._daily_loss + self._unrealized_loss)

    @property
    def open_positions(self) -> int:
        """عدد المراكز المفتوحة حالياً."""
        with self._lock:
            return self._open_positions

    @property
    def daily_trades(self) -> int:
        """عدد الصفقات المنفذة اليوم."""
        _ = self.daily_loss
        with self._lock:
            return self._daily_trades

    @property
    def is_trading_halted(self) -> bool:
        """هل تم إيقاف التداول بسبب حالة طارئة؟"""
        with self._lock:
            return self._trading_halted

    # ══════════════════════════════════════════════════════════
    # تعيين رصيد بداية اليوم
    # ══════════════════════════════════════════════════════════

    def set_day_start_balance(self, balance: float) -> bool:
        """
        تعيين رصيد بداية اليوم بشكل صريح.

        ✅ عند اكتشاف يوم UTC جديد، يتم تصفير الحالة القديمة
           قبل تسجيل رصيد بداية اليوم الجديد.

        يجب استدعاؤها مرة واحدة عند:
            - بدء دورة التداول اليومية.
            - استعادة الحالة بعد إعادة تشغيل البوت.

        Args:
            balance: رصيد الحساب الحقيقي من المنصة بالدولار.

        Returns:
            True عند النجاح.
            False إذا كانت القيمة غير صالحة أو مضبوطة مسبقاً.
        """
        value = _safe_float(balance)

        if value <= 0:
            logger.error(
                f"❌ رصيد بداية اليوم غير صالح: {balance!r}"
            )
            return False

        today = _utc_today()

        with self._lock:
            # ✅ تصفير الحالة القديمة إذا بدأ يوم UTC جديد
            if self._daily_loss_date != today:
                self._daily_loss        = 0.0
                self._daily_trades      = 0
                self._day_start_balance = None
                self._unrealized_loss   = 0.0
                self._daily_loss_date   = today
                self._trading_halted    = False
                logger.info(
                    "🌅 يوم UTC جديد — تم تصفير الحالة "
                    "قبل تعيين رصيد البداية"
                )

            # لا تسمح بتغيير baseline داخل نفس اليوم
            if self._day_start_balance is not None:
                logger.warning(
                    f"⚠️ رصيد بداية اليوم مضبوط مسبقاً: "
                    f"${self._day_start_balance:.2f} — "
                    f"لن يتم تغييره"
                )
                return False

            self._day_start_balance = value

        logger.info(f"📌 تم تعيين رصيد بداية اليوم: ${value:.2f}")
        return True

    # ══════════════════════════════════════════════════════════
    # استعادة الحالة
    # ══════════════════════════════════════════════════════════

    def restore_daily_state(
        self,
        daily_loss: float,
        daily_trades: int = 0,
        state_date: Optional[date] = None,
        day_start_balance: Optional[float] = None,
    ) -> None:
        """
        استعادة الحالة اليومية من التخزين الدائم.
        إذا كانت البيانات من يوم سابق تُتجاهَل وتبدأ الحالة من الصفر.

        Args:
            daily_loss:         الخسارة المحفوظة بالدولار.
            daily_trades:       عدد الصفقات المحفوظة.
            state_date:         تاريخ البيانات (None = اليوم).
            day_start_balance:  رصيد بداية اليوم المحفوظ.
        """
        today      = _utc_today()
        saved_date = state_date or today

        with self._lock:
            if saved_date != today:
                self._daily_loss        = 0.0
                self._daily_trades      = 0
                self._day_start_balance = None
                self._unrealized_loss   = 0.0
                self._daily_loss_date   = today
                self._trading_halted    = False
                logger.info("🔄 بيانات قديمة — تم تصفير الحالة اليومية")
                return

            # ── التحقق من قيمة الخسارة ─────────────────────────────────
            restored_loss = _safe_float(daily_loss, default=-1.0)
            if restored_loss < 0:
                logger.error(
                    f"❌ قيمة خسارة غير صالحة: {daily_loss!r} — "
                    f"سيتم استخدام 0.0"
                )
                restored_loss = 0.0

            # ── التحقق من عدد الصفقات ──────────────────────────────────
            restored_trades_f = _safe_float(daily_trades, default=-1.0)
            if restored_trades_f < 0:
                logger.error(
                    f"❌ عدد صفقات غير صالح: {daily_trades!r} — "
                    f"سيتم استخدام 0"
                )
                restored_trades_f = 0.0

            self._daily_loss      = restored_loss
            self._daily_trades    = int(restored_trades_f)
            self._daily_loss_date = today

            # ✅ دائماً نصفر baseline القديم أولاً
            self._day_start_balance = None

            if day_start_balance is not None:
                balance_value = _safe_float(day_start_balance, default=-1.0)
                if balance_value > 0:
                    self._day_start_balance = balance_value
                else:
                    logger.error(
                        f"❌ رصيد بداية اليوم غير صالح: "
                        f"{day_start_balance!r} — سيتم تجاهله"
                    )

        start_balance_str = (
            f"${self._day_start_balance:.2f}"
            if self._day_start_balance is not None
            else "غير محدد"
        )

        logger.info(
            f"♻️ حالة مستعادة | "
            f"خسارة: ${self._daily_loss:.2f} | "
            f"صفقات: {self._daily_trades} | "
            f"رصيد البداية: {start_balance_str}"
        )

    def restore_open_positions_count(self, count: int) -> None:
        """
        استعادة عدد المراكز المفتوحة من التخزين الدائم.

        ✅ إذا تجاوز العدد الحد الأقصى يتم إيقاف التداول
           بدل التقييد الصامت، لأن الحالة تشير إلى عدم اتساق
           مع المنصة يجب معالجته يدوياً.
        """
        count_value = _safe_float(count, default=0.0)
        restored    = max(0, int(count_value))

        with self._lock:
            if restored > _MAX_OPEN_POSITIONS:
                logger.critical(
                    f"❌ حالة غير متسقة: عدد المراكز المستعاد "
                    f"({restored}) يتجاوز الحد ({_MAX_OPEN_POSITIONS}) — "
                    f"تم إيقاف التداول لحين المزامنة"
                )
                self._open_positions  = restored
                self._trading_halted  = True
                return

            self._open_positions = restored

        logger.info(f"♻️ مراكز مفتوحة مستعادة: {self._open_positions}")

    # ══════════════════════════════════════════════════════════
    # تحديث الحالة
    # ══════════════════════════════════════════════════════════

    def update_unrealized_loss(self, loss: float) -> None:
        """
        تحديث الخسائر العائمة الحالية.

        يجب استدعاؤها دورياً من طبقة التنفيذ
        بعد جلب بيانات المراكز المفتوحة من المنصة.

        Args:
            loss: مجموع الخسائر العائمة الحالية (قيمة موجبة تعني خسارة).
        """
        value = _safe_float(loss, default=math.nan)

        if not math.isfinite(value) or value < 0:
            logger.warning(
                f"⚠️ قيمة خسارة عائمة غير صالحة: {loss!r} — "
                f"لن يتم تحديثها"
            )
            return

        with self._lock:
            self._unrealized_loss = value

    def update_daily_loss(
        self,
        pnl: float,
        count_as_trade: bool = False,
    ) -> None:
        """
        تحديث الخسارة اليومية من مصدر خارجي.

        مخصص للتحديثات الخارجية مثل:
            - رسوم التمويل (Funding Fee).
            - التصفية القسرية (Liquidation).

        Args:
            pnl:            القيمة السالبة تعني خسارة.
            count_as_trade: هل يُحسب كصفقة في العداد اليومي؟
                            False للرسوم والتصفية.
                            True للصفقات الفعلية.
        """
        pnl_value = _safe_float(pnl, default=math.nan)

        if not math.isfinite(pnl_value):
            logger.error(
                f"❌ P&L غير صالح: {pnl!r} — لن يتم تحديث الحالة"
            )
            return

        _ = self.daily_loss  # يضمن تصفير اليوم إن انتهى

        with self._lock:
            if pnl_value < 0:
                self._daily_loss += abs(pnl_value)

            if count_as_trade:
                self._daily_trades += 1

            current_loss   = self._daily_loss
            current_trades = self._daily_trades

        logger.info(
            f"📊 خسارة اليوم: ${current_loss:.2f} | "
            f"صفقات: {current_trades}"
        )

    # ══════════════════════════════════════════════════════════
    # إدارة المراكز
    # ══════════════════════════════════════════════════════════

    def position_opened(self) -> bool:
        """
        تسجيل فتح مركز جديد بدون فحص إشارة.

        ⚠️ استخدم approve_and_reserve_position() في البيئات
           متعددة الخيوط لضمان الذرية الكاملة.

        Returns:
            True عند النجاح.
            False عند تجاوز الحد الأقصى أو إيقاف التداول.
        """
        with self._lock:
            if self._trading_halted:
                logger.error("❌ التداول متوقف — لن يتم فتح مركز جديد")
                return False

            if self._open_positions >= _MAX_OPEN_POSITIONS:
                logger.error(
                    "❌ رُفض تسجيل مركز جديد: "
                    "تم الوصول إلى الحد الأقصى"
                )
                return False

            self._open_positions += 1
            current = self._open_positions

        logger.debug(f"📈 مراكز مفتوحة: {current}")
        return True

    def release_reserved_position(
        self,
        reservation_id: str,
    ) -> bool:
        """
        تحرير حجز مركز فشل تنفيذه على المنصة.

        ✅ يستخدم معرف الحجز لمنع التحرير المزدوج
           أو تحرير حجز خاطئ في البيئات متعددة الخيوط.

        يجب استدعاؤها في حالة:
            - فشل إرسال الأمر إلى المنصة.
            - انتهاء مهلة الاتصال.
            - أي خطأ يمنع تأكيد الأمر.

        مثال:
            result = risk.approve_and_reserve_position(signal, balance)
            try:
                order = await exchange.open_position(...)
            except Exception:
                risk.release_reserved_position(result.reservation_id)
                raise

        Args:
            reservation_id: معرف الحجز من RiskCheckResult.

        Returns:
            True عند النجاح، False إذا كان المعرف غير موجود.
        """
        with self._lock:
            if not self._reservations.pop(reservation_id, None):
                logger.warning(
                    f"⚠️ معرف حجز غير موجود أو تم تحريره مسبقاً: "
                    f"{reservation_id}"
                )
                return False

            self._open_positions = max(0, self._open_positions - 1)
            current = self._open_positions

        logger.warning(
            f"↩️ تم تحرير حجز مركز فاشل | "
            f"مراكز مفتوحة: {current}"
        )
        return True

    def position_closed(self, pnl: float) -> bool:
        """
        تسجيل إغلاق مركز وتحديث الخسارة اليومية ذرياً.

        ✅ يجمع تحديث عدد المراكز والخسارة والصفقات
           في عملية ذرية واحدة داخل قفل واحد.

        Args:
            pnl: الربح أو الخسارة المحققة للمركز.

        Returns:
            True عند النجاح.
            False إذا لم توجد مراكز أو كان P&L غير صالح.
        """
        pnl_value = _safe_float(pnl, default=math.nan)

        if not math.isfinite(pnl_value):
            logger.error(
                f"❌ P&L غير صالح عند إغلاق المركز: {pnl!r}"
            )
            return False

        _ = self.daily_loss  # يضمن تصفير اليوم إن انتهى

        with self._lock:
            if self._open_positions <= 0:
                logger.error(
                    "❌ محاولة إغلاق مركز رغم عدم وجود مراكز مفتوحة"
                )
                return False

            # ✅ تحديث ذري كامل داخل قفل واحد
            self._open_positions -= 1

            if pnl_value < 0:
                self._daily_loss += abs(pnl_value)

            self._daily_trades   += 1
            current_positions     = self._open_positions
            current_loss          = self._daily_loss
            current_trades        = self._daily_trades

        logger.info(
            f"📊 خسارة اليوم: ${current_loss:.2f} | "
            f"صفقات: {current_trades}"
        )
        logger.debug(
            f"📉 صفقة مغلقة | P&L: ${pnl_value:+.2f} | "
            f"مفتوحة: {current_positions}"
        )
        return True

    def resume_trading(self) -> None:
        """
        استئناف التداول بعد إيقاف طارئ.

        يجب استدعاؤها فقط بعد مزامنة الحالة مع المنصة
        والتأكد من اتساق عدد المراكز.
        """
        with self._lock:
            self._trading_halted = False
        logger.info("✅ تم استئناف التداول")

    # ══════════════════════════════════════════════════════════
    # الفحص الذري — الواجهة الرئيسية
    # ══════════════════════════════════════════════════════════

    def approve_and_reserve_position(
        self,
        signal: TradeSignal,
        balance: float,
    ) -> RiskCheckResult:
        """
        فحص الإشارة وحجز المركز بشكل ذري.

        ✅ يجمع check_signal() وحجز المركز في عملية واحدة
           مع معرف حجز فريد لضمان سلامة التحرير لاحقاً.

        ⚠️ عند استخدام هذه الدالة:
            - لا تستدعِ position_opened() بعدها.
            - استدعِ release_reserved_position(reservation_id)
              عند فشل المنصة.

        Args:
            signal:  إشارة التداول.
            balance: الرصيد المتاح بالدولار.

        Returns:
            RiskCheckResult مع reservation_id إذا تمت الموافقة.
        """
        with self._lock:
            result = self.check_signal(signal, balance)

            if not result.approved:
                return result

            # فحص ذري نهائي قبل الحجز
            if self._trading_halted:
                return RiskCheckResult(
                    approved=False,
                    reason="❌ التداول متوقف — يرجى مزامنة الحالة أولاً",
                    warnings=result.warnings,
                )

            if self._open_positions >= _MAX_OPEN_POSITIONS:
                return RiskCheckResult(
                    approved=False,
                    reason=(
                        f"❌ الحد الأقصى للمراكز المفتوحة "
                        f"({_MAX_OPEN_POSITIONS}) — رُفض بعد الفحص"
                    ),
                    warnings=result.warnings,
                )

            # ✅ حجز بمعرف فريد لمنع التحرير المزدوج
            reservation_id = str(uuid4())
            self._reservations[reservation_id] = True
            self._open_positions += 1

            result.reservation_id = reservation_id

            logger.debug(
                f"🔒 مركز محجوز ذرياً | "
                f"ID: {reservation_id[:8]} | "
                f"مفتوحة: {self._open_positions}"
            )

        return result

    # ══════════════════════════════════════════════════════════
    # الفحص الرئيسي
    # ══════════════════════════════════════════════════════════

    def check_signal(
        self,
        signal: TradeSignal,
        balance: float,
    ) -> RiskCheckResult:
        """
        التحقق الشامل من إشارة التداول قبل التنفيذ.

        ترتيب الفحوصات:
            1. إيقاف الطوارئ
            2. صحة الرصيد
            3. الحد الأدنى للرصيد
            4. صحة إعدادات المخاطر
            5. حد الخسارة اليومية (محققة + عائمة)
            6. عدد المراكز المفتوحة
            7. حساب الحجم الآمن وفق Stop Loss
            8. جدوى العمولة

        Args:
            signal:  إشارة التداول.
            balance: الرصيد المتاح بالدولار.

        Returns:
            RiskCheckResult مع تفاصيل القرار الكامل.
        """
        warnings: List[str] = []

        # ── 1. إيقاف الطوارئ ───────────────────────────────────────────
        with self._lock:
            if self._trading_halted:
                return RiskCheckResult(
                    approved=False,
                    reason="❌ التداول متوقف — يرجى مزامنة الحالة مع المنصة",
                )

        # ── 2. صحة الرصيد ──────────────────────────────────────────────
        balance = _safe_float(balance)
        if balance <= 0:
            return RiskCheckResult(
                approved=False,
                reason="❌ الرصيد غير صالح أو غير متاح",
            )

        # ── 3. الحد الأدنى للرصيد ──────────────────────────────────────
        if balance < _MIN_BALANCE_USD:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"❌ الرصيد أقل من الحد الأدنى "
                    f"(${_MIN_BALANCE_USD:.2f})"
                ),
            )

        # ── 4. صحة إعدادات المخاطر ─────────────────────────────────────
        max_daily_loss = _get_risk_setting(
            config.risk.max_daily_loss_pct,
            "max_daily_loss_pct",
        )
        if max_daily_loss is None:
            return RiskCheckResult(
                approved=False,
                reason="❌ إعداد حد الخسارة اليومية غير صالح",
            )

        max_pos_pct = _get_risk_setting(
            config.risk.max_position_pct,
            "max_position_pct",
        )
        if max_pos_pct is None:
            return RiskCheckResult(
                approved=False,
                reason="❌ إعداد الحد الأقصى لحجم الصفقة غير صالح",
            )

        if max_pos_pct > 100:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"❌ max_position_pct ({max_pos_pct}%) "
                    f"يجب أن يكون بين 0 و 100"
                ),
            )

        max_leverage_cfg = _validate_leverage_setting(
            config.risk.max_leverage,
            "max_leverage",
        )
        if max_leverage_cfg is None:
            return RiskCheckResult(
                approved=False,
                reason="❌ إعداد الحد الأقصى للرافعة غير صالح",
            )

        # ── 5. حد الخسارة اليومية ──────────────────────────────────────
        with self._lock:
            if self._day_start_balance is None:
                self._day_start_balance = balance
                logger.warning(
                    f"⚠️ لم يتم تعيين رصيد بداية اليوم — "
                    f"Fallback: ${balance:.2f} — "
                    f"استدعِ set_day_start_balance() عند بدء التداول"
                )
            loss_base       = self._day_start_balance
            realized_loss   = self._daily_loss
            unrealized_loss = self._unrealized_loss

        if loss_base <= 0:
            return RiskCheckResult(
                approved=False,
                reason="❌ رصيد بداية اليوم غير صالح",
            )

        # ✅ يشمل الخسائر المحققة والعائمة
        total_loss     = realized_loss + unrealized_loss
        daily_loss_pct = total_loss / loss_base * 100

        if daily_loss_pct >= max_daily_loss:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"🚨 تم الوصول إلى حد الخسارة اليومية "
                    f"({daily_loss_pct:.2f}%) "
                    f"[محقق: ${realized_loss:.2f} + "
                    f"عائم: ${unrealized_loss:.2f}]"
                ),
            )

        if daily_loss_pct >= max_daily_loss * _WARNING_THRESHOLD:
            warnings.append(
                f"⚠️ اقترب من حد الخسارة اليومية "
                f"({daily_loss_pct:.2f}% / {max_daily_loss:.2f}%)"
            )

        # ── 6. عدد المراكز المفتوحة ─────────────────────────────────────
        with self._lock:
            current_positions = self._open_positions

        if current_positions >= _MAX_OPEN_POSITIONS:
            return RiskCheckResult(
                approved=False,
                reason=(
                    f"❌ الحد الأقصى للمراكز المفتوحة "
                    f"({_MAX_OPEN_POSITIONS})"
                ),
            )

        if current_positions >= _WARN_OPEN_POSITIONS:
            warnings.append(
                f"⚠️ مراكز مفتوحة: {current_positions} "
                f"(حذر من التشتت)"
            )

        # ── 7. حساب الحجم الآمن وفق Stop Loss ─────────────────────────
        adjusted_size, adjusted_leverage = self._calculate_safe_size(
            signal=signal,
            balance=balance,
            loss_base=loss_base,
            realized_loss=realized_loss,
            daily_loss_pct=daily_loss_pct,
            max_daily_loss=max_daily_loss,
            max_pos_pct=max_pos_pct,
            max_leverage_cfg=max_leverage_cfg,
            warnings=warnings,
        )

        if adjusted_size <= 0 or adjusted_leverage <= 0:
            return RiskCheckResult(
                approved=False,
                reason="❌ تعذر حساب حجم أو رافعة صالحة",
                warnings=warnings,
            )

        # ── 8. جدوى العمولة ────────────────────────────────────────────
        position_value = adjusted_size * adjusted_leverage

        fees = self.fee_calculator.calculate(
            position_size=position_value,
            entry_type="taker",
            exit_type="taker",
        )

        if not fees.is_viable:
            return RiskCheckResult(
                approved=False,
                reason="❌ الصفقة غير مجدية بعد احتساب العمولة",
                warnings=warnings,
            )

        return RiskCheckResult(
            approved=True,
            reason="✅ فحص المخاطر اجتاز بنجاح",
            adjusted_size=adjusted_size,
            adjusted_leverage=adjusted_leverage,
            warnings=warnings,
        )

    # ══════════════════════════════════════════════════════════
    # حساب الحجم الآمن
    # ══════════════════════════════════════════════════════════

    def _calculate_stop_loss_distance(
        self,
        signal: TradeSignal,
    ) -> float:
        """
        حساب نسبة المسافة بين سعر الدخول ووقف الخسارة.

        Returns:
            نسبة المسافة [0.0 → 1.0].
            0.0 إذا كانت القيم غير صالحة.
        """
        entry = _safe_float(signal.entry_price, default=0.0)
        stop  = _safe_float(signal.stop_loss,   default=0.0)

        if entry <= 0 or stop <= 0 or entry == stop:
            return 0.0

        return abs(entry - stop) / entry

    def _calculate_safe_size(
        self,
        signal: TradeSignal,
        balance: float,
        loss_base: float,
        realized_loss: float,
        daily_loss_pct: float,
        max_daily_loss: float,
        max_pos_pct: float,
        max_leverage_cfg: int,
        warnings: List[str],
    ) -> Tuple[float, int]:
        """
        حساب الهامش الآمن والرافعة المناسبة للصفقة.

        ✅ المنطق مبني على المخاطرة الفعلية عند Stop Loss:
            risk_budget = (loss_base × max_daily_loss%) - realized_loss
            max_notional = risk_budget / stop_distance
            max_margin   = max_notional / leverage

        مع تطبيق Recovery Mode عند تجاوز 50% من الحد:
            - تخفيض الحجم 50%.
            - تحديد سقف الرافعة بـ 10x.

        Returns:
            Tuple[float, int]: (الهامش بالدولار، الرافعة).
        """
        if max_daily_loss <= 0:
            return 0.0, 0

        # ── التحقق من رافعة الإشارة ──────────────────────────────────────
        raw_leverage = _safe_float(signal.leverage, default=-1.0)
        if raw_leverage < 1:
            logger.warning(
                f"⚠️ رافعة الإشارة غير صالحة: {signal.leverage!r}"
            )
            return 0.0, 0

        requested_leverage = int(raw_leverage)
        leverage = min(requested_leverage, max_leverage_cfg)

        # ── Recovery Mode ────────────────────────────────────────────────
        in_recovery = daily_loss_pct > max_daily_loss * _RECOVERY_THRESHOLD
        if in_recovery:
            leverage = min(leverage, _RECOVERY_MAX_LEVERAGE)
            warnings.append("🔄 Recovery Mode: رافعة مقيدة")

        leverage = max(1, leverage)

        # ── الميزانية المتبقية ───────────────────────────────────────────
        risk_budget_usd = max(
            0.0,
            (loss_base * max_daily_loss / 100.0) - realized_loss,
        )

        if in_recovery:
            risk_budget_usd *= 0.5
            warnings.append("🔄 Recovery Mode: ميزانية مقلّلة 50%")

        if risk_budget_usd <= 0:
            return 0.0, 0

        # ── الحجم المبني على Stop Loss ──────────────────────────────────
        stop_distance = self._calculate_stop_loss_distance(signal)

        if stop_distance > 0:
            # ✅ الحجم الاسمي الأقصى بناءً على مخاطرة SL
            max_notional_by_sl = risk_budget_usd / stop_distance
            max_margin_by_sl   = max_notional_by_sl / leverage
        else:
            # Fallback: استخدام position_size_pct إذا لم يكن SL متاحاً
            logger.warning(
                "⚠️ Stop Loss غير متاح — سيتم استخدام position_size_pct"
            )
            requested_pct  = max(0.0, _safe_float(signal.position_size_pct))
            remaining_ratio = max(
                0.0,
                min(
                    1.0,
                    (max_daily_loss - daily_loss_pct) / max_daily_loss,
                ),
            )
            adjusted_pct   = requested_pct * remaining_ratio

            if in_recovery:
                adjusted_pct *= 0.5

            adjusted_pct   = min(adjusted_pct, max_pos_pct)
            max_margin_by_sl = balance * adjusted_pct / 100.0

        # ── الحجم المبني على max_position_pct ──────────────────────────
        max_margin_by_pct = balance * max_pos_pct / 100.0

        # ✅ الأصغر من الحدين
        raw_size = min(max_margin_by_sl, max_margin_by_pct)

        # ✅ رفض الحجم إذا كان أقل من الحد الأدنى
        #    بدل رفعه تلقائياً لتجنب تجاوز max_position_pct
        if raw_size < _MIN_TRADE_SIZE_USD:
            logger.warning(
                f"⚠️ الحجم المحسوب (${raw_size:.4f}) "
                f"أقل من الحد الأدنى (${_MIN_TRADE_SIZE_USD}) — "
                f"تم رفض الصفقة"
            )
            return 0.0, 0

        return round(raw_size, 2), leverage

    # ══════════════════════════════════════════════════════════
    # الحالة العامة
    # ══════════════════════════════════════════════════════════

    def get_status(self, balance: float) -> Dict:
        """
        تقرير شامل بحالة إدارة المخاطر.

        ✅ يستخدم _get_risk_setting للتوافق مع check_signal.
        ✅ يقرأ الحالة كاملة داخل قفل واحد.
        ✅ يُظهر حالة CONFIG_ERROR و BASELINE_MISSING بوضوح.

        Args:
            balance: الرصيد الحالي بالدولار.

        Returns:
            dict يحتوي على جميع مؤشرات الحالة.
        """
        balance = max(0.0, _safe_float(balance))

        # ✅ قراءة الحالة كاملة داخل قفل واحد
        with self._lock:
            loss_base        = self._day_start_balance
            open_positions   = self._open_positions
            daily_trades     = self._daily_trades
            realized_loss    = self._daily_loss
            unrealized_loss  = self._unrealized_loss
            trading_halted   = self._trading_halted

        max_loss = _get_risk_setting(
            config.risk.max_daily_loss_pct,
            "max_daily_loss_pct",
        )

        # حالة إعداد فاسد
        if max_loss is None:
            return {
                "daily_loss_usd":       round(realized_loss, 2),
                "unrealized_loss_usd":  round(unrealized_loss, 2),
                "daily_loss_pct":       None,
                "remaining_budget_pct": 0.0,
                "open_positions":       open_positions,
                "daily_trades":         daily_trades,
                "baseline_source":      "unknown",
                "status":               "🔴 CONFIG_ERROR",
            }

        # حالة baseline غير محدد
        baseline_source = "day_start"
        if loss_base is None or loss_base <= 0:
            loss_base       = balance
            baseline_source = "fallback"

        total_loss     = realized_loss + unrealized_loss
        daily_loss_pct = (
            total_loss / loss_base * 100
            if loss_base > 0
            else 100.0
        )

        if trading_halted:
            status = "🔴 HALTED"
        elif daily_loss_pct >= max_loss:
            status = "🔴 STOPPED"
        elif daily_loss_pct >= max_loss * _WARNING_THRESHOLD:
            status = "🟡 CAUTION"
        elif baseline_source == "fallback":
            status = "🟡 BASELINE_MISSING"
        else:
            status = "🟢 NORMAL"

        return {
            "daily_loss_usd":       round(realized_loss, 2),
            "unrealized_loss_usd":  round(unrealized_loss, 2),
            "total_loss_usd":       round(total_loss, 2),
            "daily_loss_pct":       round(daily_loss_pct, 2),
            "remaining_budget_pct": round(
                max(0.0, max_loss - daily_loss_pct), 2
            ),
            "open_positions":       open_positions,
            "daily_trades":         daily_trades,
            "baseline_source":      baseline_source,
            "status":               status,
        }
