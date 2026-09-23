@dataclass
class ExchangeConfig:
    """
    إعدادات جميع منصات التداول.

    TRADING_EXCHANGES:
        binance
        bybit
        binance,bybit

    المنصة لا تعتبر مفعلة إلا بوجود:
        API Key
        Secret Key
    """

    trading_exchanges: List[str] = field(
        default_factory=lambda: ["binance"]
    )

    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_testnet: bool = True

    bybit_api_key: str = ""
    bybit_secret_key: str = ""
    bybit_testnet: bool = True

    def __post_init__(self) -> None:
        raw_exchanges = _env_text(
            "TRADING_EXCHANGES",
            "binance",
        )

        requested = [
            item.strip().lower()
            for item in raw_exchanges.split(",")
            if item.strip()
        ]

        supported = {"binance", "bybit"}
        invalid = set(requested) - supported

        if invalid:
            raise ValueError(
                "Unsupported exchanges: "
                f"{sorted(invalid)}. "
                "Supported: binance, bybit."
            )

        self.trading_exchanges = list(dict.fromkeys(requested))

        self.binance_api_key = _env_text(
            "BINANCE_API_KEY",
            self.binance_api_key,
        )
        self.binance_secret_key = _env_text(
            "BINANCE_SECRET_KEY",
            self.binance_secret_key,
        )
        self.binance_testnet = _env_bool(
            "BINANCE_TESTNET",
            self.binance_testnet,
        )

        self.bybit_api_key = _env_text(
            "BYBIT_API_KEY",
            self.bybit_api_key,
        )
        self.bybit_secret_key = _env_text(
            "BYBIT_SECRET_KEY",
            self.bybit_secret_key,
        )
        self.bybit_testnet = _env_bool(
            "BYBIT_TESTNET",
            self.bybit_testnet,
        )

    def credentials_available(self, exchange_name: str) -> bool:
        exchange_name = exchange_name.lower()

        if exchange_name == "binance":
            return bool(
                self.binance_api_key
                and self.binance_secret_key
            )

        if exchange_name == "bybit":
            return bool(
                self.bybit_api_key
                and self.bybit_secret_key
            )

        return False

    def enabled_exchanges(self) -> List[str]:
        """
        إرجاع المنصات المطلوبة التي لديها مفاتيح كاملة فقط.
        """
        enabled = []

        for exchange_name in self.trading_exchanges:
            if self.credentials_available(exchange_name):
                enabled.append(exchange_name)
            else:
                logger.warning(
                    "⚠️ %s مطلوب لكنه لا يملك API credentials كاملة",
                    exchange_name,
                )

        return enabled

    def validate(self) -> bool:
        enabled = self.enabled_exchanges()

        if not enabled:
            logger.error(
                "❌ لا توجد منصة مفعلة بمفاتيح API كاملة"
            )
            return False

        return True
