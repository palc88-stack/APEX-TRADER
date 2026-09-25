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

    تدعم الواجهتين التالية:

    1. الواجهة المستخدمة في الاختبارات:
        FeeCalculator("binance")
        calculate(...)
        adjust_targets(...)

    2. الواجهة القديمة:
        FeeCalculator({...})
        calculate_trade_fees(...)
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
        config: Optional[Union[str, Dict[str, Any], Any]] = None,
    ):
        self.exchange = "binance"
        self.config: Dict[str, Any] = {}

        if isinstance(config, str):
            self.exchange = config.strip().lower()

        elif isinstance(config, dict):
            self.config = config
            self.exchange = str(
                config.get("exchange", "binance")
            ).strip().lower()

        elif config is not None:
            # دعم AppConfig / Config وRiskConfig
            self.config = self._config_to_dict(config)

            exchange_value = self.config.get(
                "exchange",
                "binance",
            )

            if isinstance(exchange_value, str):
                self.exchange = exchange_value.lower()

        if self.exchange not in self.DEFAULT_RATES:
            logger.warning(
                "Unknown exchange '{}'; using Binance fee rates.",
                self.exchange,
            )
            self.exchange = "binance"

        rates = self.DEFAULT_RATES[self.exchange]

        self.maker_fee_rate = self._get_rate(
            "maker_fee_rate",
            rates["maker"],
        )

        self.taker_fee_rate = self._get_rate(
            "taker_fee_rate",
            rates["taker"],
        )

        # دعم أسماء الإعدادات البديلة الموجودة في config.py
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
        تحويل القواميس وكائنات الإعدادات إلى قاموس مسطح.
        """
        if isinstance(config, dict):
            return dict(config)

        result: Dict[str, Any] = {}

        for name in (
            "exchange",
            "maker_fee_rate",
            "taker_fee_rate",
            "binance_maker_fee",
            "binance_taker_fee",
            "bybit_maker_fee",
            "bybit_taker_fee",
        ):
            if hasattr(config, name):
                value = getattr(config, name)

                if name == "exchange" and not isinstance(
                    value,
                    str,
                ):
                    continue

                result[name] = value

        # دعم AppConfig.risk
        risk = getattr(config, "risk", None)

        if risk is not None:
            for name in (
                "binance_maker_fee",
                "binance_taker_fee",
                "bybit_maker_fee",
                "bybit_taker_fee",
            ):
                if hasattr(risk, name):
                    result[name] = getattr(risk, name)

        return result

    def _get_rate(
        self,
        name: str,
        default: float,
    ) -> float:
        value = self.config.get(name, default)

        try:
            value = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid fee rate for '{}'; using {}.",
                name,
                default,
            )
            value = default

        if value < 0:
            logger.warning(
                "Negative fee rate for '{}'; using {}.",
                name,
                default,
            )
            value = default

        return value

    def _rate_for_type(self, order_type: str) -> float:
        normalized = str(order_type).strip().lower()

        if normalized == "maker":
            return self.maker_fee_rate

        if normalized == "taker":
            return self.taker_fee_rate

        raise ValueError(
            "order_type must be either 'maker' or 'taker'"
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
            نسبة التعادل المئوية. مثال:
            0.0004 * 2 * 100 = 0.08%.
        """
        try:
            position_size = float(position_size*

