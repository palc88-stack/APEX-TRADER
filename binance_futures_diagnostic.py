import os
import sys
from typing import Optional

from dotenv import load_dotenv


load_dotenv()


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    return value


def _is_truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _print_header(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


try:
    from binance_sdk_derivatives_trading_usds_futures.derivatives_trading_usds_futures import (
        ConfigurationRestAPI,
        DerivativesTradingUsdsFutures,
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL,
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL,
    )
except ImportError:
    print("SDK الرسمي لـ Binance Futures غير مثبت.")
    print("قم بتشغيل:")
    print("  pip install binance-sdk-derivatives-trading-usds-futures")
    print("أو:")
    print("  pip install -r requirements.txt")
    sys.exit(1)


def main() -> int:
    api_key = _env("BINANCE_API_KEY")
    api_secret = _env("BINANCE_SECRET_KEY")
    testnet = _is_truthy(_env("BINANCE_TESTNET"))

    _print_header("Binance Futures Diagnostic")
    print(f"BINANCE_API_KEY present: {'yes' if api_key else 'no'}")
    print(f"BINANCE_SECRET_KEY present: {'yes' if api_secret else 'no'}")
    print(f"BINANCE_TESTNET: {str(testnet).lower()}")

    if not api_key or not api_secret:
        print("\n❌ المفتاحان مفقودان. أضفهما إلى .env أو GitHub Secrets.")
        return 1

    base_url = (
        DERIVATIVES_TRADING_USDS_FUTURES_REST_API_TESTNET_URL
        if testnet
        else DERIVATIVES_TRADING_USDS_FUTURES_REST_API_PROD_URL
    )

    print(f"Base URL: {base_url}")

    config = ConfigurationRestAPI(
        api_key=api_key,
        api_secret=api_secret,
        base_path=base_url,
    )

    client = DerivativesTradingUsdsFutures(config_rest_api=config)

    print("\n▶️ اختبار الاتصال... ")
    try:
        response = client.rest_api.test_connectivity()
        print("✅ test_connectivity OK")
        print(response.data())
    except Exception as exc:  # pragma: no cover
        print(f"❌ test_connectivity فشل: {exc}")

    print("\n▶️ اختبار قراءة الرصيد... ")
    try:
        balance_response = client.rest_api.futures_account_balance_v3()
        data = balance_response.data()
        print("✅ futures_account_balance_v3 OK")
        print(data)
    except Exception as exc:  # pragma: no cover
        print(f"❌ futures_account_balance_v3 فشل: {exc}")
        print("\nمعلومة مهمة: هذا غالبًا يعني أن المفاتيح غير صالحة أو ليست API Futures Testnet الصحيحة.")
        return 2

    print("\n✅ تم إنهاء التشخيص بنجاح.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
