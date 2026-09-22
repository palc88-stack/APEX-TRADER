# ======================================
# APEX TRADER - Market Data Manager
# ======================================
# جلب بيانات السوق الحقيقية
# من Binance API مباشرة
# لا بيانات وهمية إطلاقاً!

import pandas as pd
import numpy as np
from typing import Optional, Dict
from datetime import datetime, timedelta
import asyncio
import ccxt.async_support as ccxt
from loguru import logger

from bot.config import config


class MarketDataManager:
    """
    مدير بيانات السوق الحقيقية
    
    يجلب بيانات OHLCV الحقيقية
    من Binance أو Bybit مباشرة
    مع Cache ذكي لتقليل الطلبات
    """
    
    # Cache لتجنب الطلبات المكررة
    _cache: Dict[str, dict] = {}
    CACHE_SECONDS = 60  # دقيقة واحدة
    
    def __init__(self):
        self._exchange: Optional[ccxt.Exchange] = None
        self._init_exchange()
    
    def _init_exchange(self) -> None:
        """تهيئة الاتصال لجلب البيانات"""
        try:
            # نستخدم Binance للبيانات العامة
            # لا تحتاج مفاتيح API للبيانات العامة!
            self._exchange = ccxt.binanceusdm({
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',
                },
                'timeout': 15000,
            })
            
            # Testnet للبيانات العامة
            if config.exchange.binance_testnet:
                self._exchange.urls['api'] = {
                    'public': (
                        'https://testnet.binancefuture.com'
                    ),
                    'private': (
                        'https://testnet.binancefuture.com'
                    ),
                }
            
            logger.info("✅ Market Data Manager جاهز")
            
        except Exception as e:
            logger.error(f"❌ خطأ تهيئة Market Data: {e}")
    
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = '5m',
        limit: int = 100
    ) -> Optional[pd.DataFrame]:
        """
        جلب بيانات الشموع الحقيقية
        
        Args:
            symbol: رمز العملة (BTC/USDT)
            timeframe: الإطار الزمني (1m/5m/15m)
            limit: عدد الشموع
            
        Returns:
            DataFrame حقيقي من المنصة
            الأعمدة: timestamp, open, high, low, close, volume
        """
        # فحص الـ Cache
        cache_key = f"{symbol}:{timeframe}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        try:
            if not self._exchange:
                logger.error("❌ Exchange غير مهيأ!")
                return None
            
            # جلب البيانات الحقيقية من المنصة
            raw_data = await self._exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit
            )
            
            if not raw_data or len(raw_data) == 0:
                logger.warning(f"⚠️ لا بيانات لـ {symbol}")
                return None
            
            # تحويل للـ DataFrame
            df = pd.DataFrame(
                raw_data,
                columns=[
                    'timestamp',
                    'open',
                    'high',
                    'low',
                    'close',
                    'volume'
                ]
            )
            
            # تحويل الأنواع
            df['timestamp'] = pd.to_datetime(
                df['timestamp'], unit='ms', utc=True
            )
            df = df.astype({
                'open': float,
                'high': float,
                'low': float,
                'close': float,
                'volume': float
            })
            
            # ترتيب حسب الوقت
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # التحقق من جودة البيانات
            if not self._validate_ohlcv(df, symbol):
                return None
            
            # حفظ في Cache
            self._save_to_cache(cache_key, df)
            
            logger.debug(
                f"📊 {symbol} {timeframe}: "
                f"{len(df)} شمعة | "
                f"آخر سعر: ${df['close'].iloc[-1]:,.2f}"
            )
            
            return df
            
        except ccxt.BadSymbol:
            logger.warning(f"⚠️ رمز غير صالح: {symbol}")
            return None
        except ccxt.NetworkError as e:
            logger.error(f"❌ خطأ شبكة {symbol}: {e}")
            return None
        except ccxt.ExchangeError as e:
            logger.error(f"❌ خطأ منصة {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ خطأ جلب بيانات {symbol}: {e}")
            return None
    
    def _validate_ohlcv(
        self,
        df: pd.DataFrame,
        symbol: str
    ) -> bool:
        """
        التحقق من جودة البيانات الحقيقية
        
        يكشف البيانات الفاسدة أو الناقصة
        """
        if df is None or len(df) == 0:
            logger.warning(f"⚠️ {symbol}: DataFrame فارغ")
            return False
        
        # التحقق من وجود الأعمدة
        required = ['open', 'high', 'low', 'close', 'volume']
        for col in required:
            if col not in df.columns:
                logger.warning(f"⚠️ {symbol}: عمود {col} مفقود")
                return False
        
        # التحقق من القيم
        if df['close'].isna().any():
            logger.warning(f"⚠️ {symbol}: قيم مفقودة في close")
            return False
        
        if (df['close'] <= 0).any():
            logger.warning(f"⚠️ {symbol}: أسعار سالبة!")
            return False
        
        # التحقق من منطقية High/Low
        invalid_candles = (df['high'] < df['low']).sum()
        if invalid_candles > 0:
            logger.warning(
                f"⚠️ {symbol}: {invalid_candles} شمعة غير صالحة"
            )
            return False
        
        # التحقق من حداثة البيانات
        last_timestamp = df['timestamp'].iloc[-1]
        age_minutes = (
            datetime.now(last_timestamp.tzinfo) - last_timestamp
        ).total_seconds() / 60
        
        if age_minutes > 30:  # أقدم من 30 دقيقة
            logger.warning(
                f"⚠️ {symbol}: بيانات قديمة ({age_minutes:.0f} دقيقة)"
            )
            # لا نرفض - نعطي تحذير فقط
        
        return True
    
    def _get_from_cache(
        self,
        key: str
    ) -> Optional[pd.DataFrame]:
        """جلب من الـ Cache إذا لم تنتهِ صلاحيته"""
        if key not in self._cache:
            return None
        
        cached = self._cache[key]
        age = (datetime.now() - cached['time']).total_seconds()
        
        if age > self.CACHE_SECONDS:
            del self._cache[key]
            return None
        
        return cached['data']
    
    def _save_to_cache(
        self,
        key: str,
        df: pd.DataFrame
    ) -> None:
        """حفظ في الـ Cache"""
        self._cache[key] = {
            'data': df.copy(),
            'time': datetime.now()
        }
    
    async def get_multiple_ohlcv(
        self,
        symbols: list,
        timeframe: str = '5m',
        limit: int = 100
    ) -> Dict[str, pd.DataFrame]:
        """
        جلب بيانات عدة عملات بشكل متوازٍ
        
        Args:
            symbols: قائمة العملات
            timeframe: الإطار الزمني
            limit: عدد الشموع
            
        Returns:
            dict: {symbol: DataFrame}
        """
        # جلب متوازٍ لجميع العملات
        tasks = [
            self.get_ohlcv(symbol, timeframe, limit)
            for symbol in symbols
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        data = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, pd.DataFrame):
                data[symbol] = result
            elif isinstance(result, Exception):
                logger.error(f"❌ خطأ {symbol}: {result}")
        
        logger.info(
            f"📊 جُلبت بيانات {len(data)}/{len(symbols)} عملة"
        )
        
        return data
    
    async def get_market_info(self, symbol: str) -> dict:
        """
        معلومات السوق الحقيقية
        مثل حجم التداول والتغيير
        """
        try:
            ticker = await self._exchange.fetch_ticker(symbol)
            
            return {
                'symbol': symbol,
                'last_price': float(ticker.get('last') or 0),
                'volume_24h': float(
                    ticker.get('baseVolume') or 0
                ),
                'change_24h_pct': float(
                    ticker.get('percentage') or 0
                ),
                'high_24h': float(ticker.get('high') or 0),
                'low_24h': float(ticker.get('low') or 0),
                'timestamp': ticker.get('timestamp', 0)
            }
            
        except Exception as e:
            logger.error(f"❌ خطأ معلومات السوق {symbol}: {e}")
            return {}
    
    async def close(self) -> None:
        """إغلاق الاتصال"""
        if self._exchange:
            await self._exchange.close()
