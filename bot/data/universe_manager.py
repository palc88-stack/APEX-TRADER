"""Dynamic high-liquidity trading universe management."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from uuid import uuid4

from loguru import logger


@dataclass(frozen=True)
class UniverseSymbol:
    symbol: str
    rank: int
    quote_volume_24h: float
    spread_bps: float
    liquidity_score: float
    selected_at: str
    expires_at: str
    snapshot_id: str


class UniverseManager:
    """Refresh and serve a persisted, fail-safe symbol universe."""

    def __init__(
        self,
        exchange: Any,
        state_manager: Any,
        config: Any,
        *,
        clock: Any = None,
    ) -> None:
        self.exchange = exchange
        self.state_manager = state_manager
        self.config = config
        trading = getattr(config, "trading", config)
        self.universe_size = max(1, int(getattr(trading, "universe_size", 20)))
        self.refresh_hours = max(1, int(getattr(trading, "universe_refresh_hours", 4)))
        self.quote = str(getattr(trading, "universe_quote", "USDT")).upper()
        self.fallback_symbols = list(getattr(trading, "symbols", ["BTC/USDT"]))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._symbols: list[str] = []
        self._expires_at: Optional[datetime] = None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _configured_symbols(self) -> list[str]:
        return list(dict.fromkeys(str(s).upper() for s in self.fallback_symbols if s))

    async def refresh_if_due(self, *, force: bool = False) -> list[str]:
        now = self._now()
        if not force and self._symbols and self._expires_at and now < self._expires_at:
            return list(self._symbols)

        persisted = self.state_manager.get_active_universe_symbols()
        if not force and persisted:
            expires_at = self._parse_time(persisted[0].get("expires_at"))
            symbols = [str(row["symbol"]).upper() for row in persisted if row.get("symbol")]
            if symbols and expires_at and now < expires_at:
                self._symbols = list(dict.fromkeys(symbols))
                self._expires_at = expires_at
                return list(self._symbols)

        try:
            candidates = await self.exchange.fetch_liquid_symbols(
                limit=self.universe_size,
                quote=self.quote,
            )
            if not candidates:
                raise RuntimeError("exchange returned an empty liquid-symbol universe")
            return self._activate(candidates, now)
        except Exception as exc:
            logger.error("Universe refresh failed; preserving previous/fallback symbols: {}", exc)
            if self._symbols:
                return list(self._symbols)
            if persisted:
                self._symbols = list(dict.fromkeys(
                    str(row["symbol"]).upper() for row in persisted if row.get("symbol")
                ))
                if self._symbols:
                    return list(self._symbols)
            self._symbols = self._configured_symbols()
            self._expires_at = now + timedelta(minutes=30)
            return list(self._symbols)

    def _activate(self, candidates: Iterable[dict[str, Any]], now: datetime) -> list[str]:
        snapshot_id = str(uuid4())
        expires_at = now + timedelta(hours=self.refresh_hours)
        rows = []
        symbols = []
        for rank, candidate in enumerate(candidates, start=1):
            symbol = str(candidate.get("symbol", "")).upper()
            if not symbol or symbol in symbols:
                continue
            symbols.append(symbol)
            rows.append({
                "snapshot_id": snapshot_id,
                "symbol": symbol,
                "rank": rank,
                "quote_volume_24h": float(candidate.get("quote_volume_24h", 0.0) or 0.0),
                "spread_bps": float(candidate.get("spread_bps", 0.0) or 0.0),
                "liquidity_score": float(candidate.get("liquidity_score", 0.0) or 0.0),
                "selected_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "source": "binance_usdm",
            })
            if len(rows) >= self.universe_size:
                break
        if not rows:
            raise RuntimeError("universe candidates contained no valid symbols")
        self.state_manager.replace_universe_snapshot(snapshot_id, rows, expires_at.isoformat())
        self._symbols = symbols
        self._expires_at = expires_at
        logger.info("Universe activated: {} symbols; expires {}", len(symbols), expires_at.isoformat())
        return list(self._symbols)

    def get_symbols_for_cycle(self, open_symbols: Iterable[str] = ()) -> list[str]:
        symbols = list(dict.fromkeys(self._symbols or self._configured_symbols()))
        for symbol in open_symbols:
            normalized = str(symbol).upper()
            if normalized and normalized not in symbols:
                symbols.append(normalized)
        return symbols

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            asdict(UniverseSymbol(
                symbol=symbol,
                rank=index,
                quote_volume_24h=0.0,
                spread_bps=0.0,
                liquidity_score=0.0,
                selected_at="",
                expires_at=self._expires_at.isoformat() if self._expires_at else "",
                snapshot_id="",
            ))
            for index, symbol in enumerate(self._symbols, start=1)
        ]

    @staticmethod
    def _parse_time(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return None
