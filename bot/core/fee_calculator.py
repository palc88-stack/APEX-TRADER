from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

from loguru import logger


@dataclass(frozen=True)
class FeeResult:
    """
    نتيجة حساب رسوم الصفقة.
    """

    entry_fee: float
    exit_fee: float
    total_fee: float
    breakeven_pct: float


class FeeCalculator:
    """
    حاسبة رسوم التداول.

    تدعم:

    FeeCalculator("binance")

    أو:

    FeeCalculator({
        "exchange": "binance",
        "maker_fee_rate": 0.0002,
        "taker_fee_rate": 0.0004,
    })
    """

    DEFAULT_RATES = {
        "binance": {
            "maker": 0.0002,
            "taker": 0.0004,
        },
        "bybit": {
            "maker": 0.0002,
            "taker": 0.00055,
        },
    }

    def __init__(
        self,
        config: Optional[
            Union[str, Dict[str, Any], Any]
        ] = None,
    ) -> None:
        self.exchange = "binance"
        self.config: Dict[str, Any] = {}

        if isinstance(config, str):
            self.exchange = config.strip().lower()

        elif isinstance(config, dict):
            self.config = dict(config)
            self.exchange = str(
                self.config.get("exchange", "binance")
            ).strip().lower()

        elif config is not None:
            self.config = self._config_to_dict(config)

            exchange_name = self.config.get(
                "exchange",
                "binance",
            )

            if isinstance(exchange_name, str):
                self.exchange = exchange_name.strip().lower()

        if self.exchange not in self.DEFAULT_RATES:
            logger.warning(
                "Unknown exchange '{}'; using Binance rates.",
                self.exchange,
            )
            self.exchange = "binance"

        default_rates = self.DEFAULT_RATES[self.exchange]

        self.maker_fee_rate = self._get_rate(
            "maker_fee_rate",
            default_rates["maker"],
        )

        self.taker_fee_rate = self._get_rate(
            "taker_fee_rate",
            default_rates["taker"],
        )

        if self.exchange == "binance":
            self.maker_fee_rate = self._get_rate(
                "binance_maker_fee",
                self.maker_fee_rate,
            )
            self.taker_fee_rate = self._get_rate(
                "binance_taker_fee",
                self.taker_fee_rate,
            )

        elif self.exchange == "bybit":
            self.maker_fee_rate = self._get_rate(
                "bybit_maker_fee",
                self.maker_fee_rate,
            )
            self.taker_fee_rate = self._get_rate(
                "bybit_taker_fee",
                self.taker_fee_rate,
            )

    @staticmethod
    def _config_to_dict(config: Any) -> Dict[str, Any]:
        """
        تحويل كائن الإعدادات إلى قاموس.
        """
        if isinstance(config, dict):
            return dict(config)

        result: Dict[str, Any] = {}

        attribute_names = (
            "exchange",
            "maker_fee_rate",
            "taker_fee_rate",
            "binance_maker_fee",
            "binance_taker_fee",
            "bybit_maker_fee",
            "bybit_taker_fee",
        )

        for name in attribute_names:
            if hasattr(config, name):
                value = getattr(config, name)

                if name == "exchange" and not isinstance(
                    value,
                    str,
                ):
                    continue

                result[name] = value

        risk_config = getattr(config, "risk", None)

        if risk_config is not None:
            risk_attributes = (
                "binance_maker_fee",
                "binance_taker_fee",
                "bybit_maker_fee",
                "bybit_taker_fee",
            )

            for name in risk_attributes:
                if hasattr(risk_config, name):
                    result[name] = getattr(
                        risk_config,
                        name,
                    )

        return result

    def _get_rate(
        self,
        name: str,
        default: float,
    ) -> float:
        value = self.config.get(name, default)

        try:
            rate = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid fee rate '{}'; using {}.",
                name,
                default,
            )
            return float(default)

        if rate < 0:
            logger.warning(
                "Negative fee rate '{}'; using {}.",
                name,
                default,
            )
            return float(default)

        return rate

    def _rate_for_type(self, order_type: str) -> float:
        normalized_type = str(order_type).strip().lower()

        if normalized_type == "maker":
            return self.maker_fee_rate

        if normalized_type == "taker":
            return self.taker_fee_rate

        raise ValueError(
            "order_type must be 'maker' or 'taker'"
        )

    def calculate(
        self,
        position_size: float,
        entry_type: str = "taker",
        exit_type: str = "taker",
    ) -> FeeResult:
        """
        حساب رسوم الدخول والخروج.

        position_size:
            القيمة الاسمية للصفقة بالدولار.

        breakeven_pct:
            نسبة الحركة المطلوبة لتغطية رسوم الدخول والخروج.
            مثال:
            0.0004 * 2 * 100 = 0.08%.
        """
        try:
            position_size = float(position_size)

            if position_size <= 0:
                return FeeResult(
                    entry_fee=0.0,
                    exit_fee=0.0,
                    total_fee=0.0,
                    breakeven_pct=0.0,
                )

            entry_rate = self._rate_for_type(entry_type)
            exit_rate = self._rate_for_type(exit_type)

            entry_fee = position_size * entry_rate
            exit_fee = position_size * exit_rate
            total_fee = entry_fee + exit_fee

            breakeven_pct = (
                (entry_rate + exit_rate) * 100.0
            )

            return FeeResult(
                entry_fee=round(entry_fee, 8),
                exit_fee=round(exit_fee, 8),
                total_fee=round(total_fee, 8),
                breakeven_pct=round(breakeven_pct, 8),
            )

        except (TypeError, ValueError) as error:
            logger.error(
                "❌ خطأ في حساب رسوم الصفقة: {}",
                error,
            )

            return FeeResult(
                entry_fee=0.0,
                exit_fee=0.0,
                total_fee=0.0,
                breakeven_pct=0.0,
            )

    def calculate_trade_fees(
        self,
        size_usd: float,
        is_maker: bool = False,
    ) -> float:
        """
        الواجهة القديمة لحساب رسوم الدخول والخروج.
        """
        order_type = (
            "maker"
            if is_maker
            else "taker"
        )

        result = self.calculate(
            position_size=size_usd,
            entry_type=order_type,
            exit_type=order_type,
        )

        return round(result.total_fee, 4)

    def is_trade_profitable_after_fees(
        self,
        entry_price: float,
        exit_price: float,
        size_usd: float,
        direction: str,
        is_maker: bool = False,
    ) -> bool:
        """
        التحقق من أن الصفقة مربحة بعد خصم الرسوم.
        """
        try:
            entry_price = float(entry_price)
            exit_price = float(exit_price)
            size_usd = float(size_usd)

            if (
                entry_price <= 0
                or exit_price <= 0
                or size_usd <= 0
            ):
                return False

            normalized_direction = (
                str(direction).strip().upper()
            )

            if normalized_direction in {"BUY", "LONG"}:
                price_difference = (
                    exit_price - entry_price
                )

            elif normalized_direction in {"SELL", "SHORT"}:
                price_difference = (
                    entry_price - exit_price
                )

            else:
                return False

            gross_profit = (
                price_difference / entry_price
            ) * size_usd

            total_fees = self.calculate_trade_fees(
                size_usd=size_usd,
                is_maker=is_maker,
            )

            return gross_profit - total_fees > 0.0

        except (TypeError, ValueError) as error:
            logger.error(
                "❌ خطأ أثناء تقييم ربح الصفقة: {}",
                error,
            )
            return False

    def adjust_targets(
        self,
        entry_price: float,
        direction: str,
        sl_pct: float,
        tp1_pct: float,
        tp2_pct: float,
        position_size: float,
    ) -> Dict[str, float]:
        """
        تعديل أهداف الصفقة لتغطية رسوم الدخول والخروج.

        جميع النسب مئوية:
        0.25 تعني 0.25%.
        """
        entry_price = float(entry_price)
        sl_pct = float(sl_pct)
        tp1_pct = float(tp1_pct)
        tp2_pct = float(tp2_pct)
        position_size = float(position_size)

        if entry_price <= 0:
            raise ValueError(
                "entry_price must be positive"
            )

        if position_size <= 0:
            raise ValueError(
                "position_size must be positive"
            )

        normalized_direction = (
            str(direction).strip().lower()
        )

        if normalized_direction in {"long", "buy"}:
            is_long = True

        elif normalized_direction in {"short", "sell"}:
            is_long = False

        else:
            raise ValueError(
                "direction must be long, short, buy, or sell"
            )

        fee_result = self.calculate(
            position_size=position_size,
            entry_type="taker",
            exit_type="taker",
        )

        fee_pct = fee_result.breakeven_pct

        if is_long:
            stop_loss = entry_price * (
                1.0 - sl_pct / 100.0
            )

            take_profit_1 = entry_price * (
                1.0 + (tp1_pct + fee_pct) / 100.0
            )

            take_profit_2 = entry_price * (
                1.0 + (tp2_pct + fee_pct) / 100.0
            )

            breakeven = entry_price * (
                1.0 + fee_pct / 100.0
            )

        else:
            stop_loss = entry_price * (
                1.0 + sl_pct / 100.0
            )

            take_profit_1 = entry_price * (
                1.0 - (tp1_pct + fee_pct) / 100.0
            )

            take_profit_2 = entry_price * (
                1.0 - (tp2_pct + fee_pct) / 100.0
            )

            breakeven = entry_price * (
                1.0 - fee_pct / 100.0
            )

        return {
            "stop_loss": round(stop_loss, 8),
            "tp1": round(take_profit_1, 8),
            "tp2": round(take_profit_2, 8),
            "breakeven": round(breakeven, 8),
        }
