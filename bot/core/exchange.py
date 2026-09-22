# ======================================
# APEX TRADER - Exchange Manager
# ======================================
# اتصال حقيقي 100% بـ Binance و Bybit
# عبر مكتبة CCXT الموثوقة
# لا بيانات وهمية - كل شيء حقيقي!

import ccxt.async_support as ccxt
import asyncio
import time
from typing import Optional, Dict, List
from loguru import logger

from bot.config import config


class ExchangeManager:
    """
    مدير الاتصال بمنصات التداول
    
    يتعامل مع:
    - Binance Futures (رئيسي)
    - Bybit Futures (احتياطي)
    
    كل البيانات حقيقية من API المنصات
    """
    
    def __init__(self):
        self._binance: Optional[ccxt.binanceusdm] = None
        self._bybit: Optional[ccxt.bybit] = None
        self.active_exchange: str = "binance"
        self._last_latency: float = 0.0
        self._initialized: bool = False
        
        # تهيئة الاتصالات
        self._init_exchanges()
    
    def _init_exchanges(self) -> None:
        """
        تهيئة الاتصال الحقيقي بالمنصات
        باستخدام المفاتيح من .env
        """
        # === Binance Futures ===
        try:
            binance_config = {
                'apiKey': config.exchange.binance_api_key,
                'secret': config.exchange.binance_secret_key,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',
                    'adjustForTimeDifference': True,
                },
                'timeout': 10000,  # 10 ثوانٍ
            }
            
            # Testnet إذا لزم
            if config.exchange.binance_testnet:
                binance_config['options']['sandboxMode'] = True
                binance_config['urls'] = {
                    'api': {
                        'public': (
                            'https://testnet.binancefuture.com'
                        ),
                        'private': (
                            'https://testnet.binancefuture.com'
                        ),
                    }
                }
            
            self._binance = ccxt.binanceusdm(binance_config)
            logger.info("✅ Binance Futures جاهز")
            
        except Exception as e:
            logger.error(f"❌ Binance فشل التهيئة: {e}")
        
        # === Bybit Futures ===
        try:
            bybit_config = {
                'apiKey': config.exchange.bybit_api_key,
                'secret': config.exchange.bybit_secret_key,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'linear',
                },
                'timeout': 10000,
            }
            
            if config.exchange.bybit_testnet:
                bybit_config['options']['testnet'] = True
            
            self._bybit = ccxt.bybit(bybit_config)
            logger.info("✅ Bybit Futures جاهز")
            
        except Exception as e:
            logger.error(f"❌ Bybit فشل التهيئة: {e}")
        
        self._initialized = True
    
    @property
    def _exchange(self):
        """المنصة النشطة حالياً"""
        if self.active_exchange == "bybit" and self._bybit:
            return self._bybit
        if self._binance:
            return self._binance
        raise RuntimeError("❌ لا توجد منصة متاحة!")
    
    async def check_connection(self) -> bool:
        """
        التحقق من الاتصال الحقيقي بالمنصة
        عبر استدعاء API فعلي
        """
        try:
            start = time.time()
            
            # طلب حقيقي للمنصة
            await self._exchange.fetch_time()
            
            self._last_latency = (time.time() - start) * 1000
            
            logger.info(
                f"✅ اتصال جيد | "
                f"زمن: {self._last_latency:.0f}ms"
            )
            return True
            
        except ccxt.NetworkError as e:
            logger.error(f"❌ خطأ شبكة: {e}")
            return False
        except ccxt.ExchangeError as e:
            logger.error(f"❌ خطأ منصة: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ خطأ اتصال: {e}")
            return False
    
    async def get_latency(self) -> float:
        """قياس زمن الاستجابة الحقيقي"""
        try:
            start = time.time()
            await self._exchange.fetch_time()
            latency = (time.time() - start) * 1000
            self._last_latency = latency
            return latency
        except Exception:
            return 999.0
    
    async def get_balance(self) -> float:
        """
        جلب الرصيد الحقيقي من المنصة
        
        Returns:
            float: الرصيد بـ USDT
        """
        try:
            # طلب حقيقي للرصيد
            balance_data = await self._exchange.fetch_balance()
            
            # استخراج USDT المتاح
            usdt_balance = (
                balance_data
                .get('USDT', {})
                .get('free', 0.0)
            )
            
            if usdt_balance is None:
                usdt_balance = 0.0
            
            logger.debug(f"💰 الرصيد الحقيقي: ${usdt_balance:.2f}")
            return float(usdt_balance)
            
        except ccxt.AuthenticationError:
            logger.error("❌ خطأ مصادقة - تحقق من API Keys!")
            return 0.0
        except ccxt.ExchangeError as e:
            logger.error(f"❌ خطأ جلب الرصيد: {e}")
            return 0.0
        except Exception as e:
            logger.error(f"❌ خطأ غير متوقع: {e}")
            return 0.0
    
    async def get_ticker(self, symbol: str) -> dict:
        """
        جلب السعر الحالي الحقيقي
        
        Args:
            symbol: رمز العملة (BTC/USDT)
            
        Returns:
            dict: بيانات السعر الحقيقية
        """
        try:
            # بيانات حقيقية من المنصة
            ticker = await self._exchange.fetch_ticker(symbol)
            
            return {
                'last': float(ticker.get('last') or 0),
                'bid': float(ticker.get('bid') or 0),
                'ask': float(ticker.get('ask') or 0),
                'volume': float(ticker.get('baseVolume') or 0),
                'change_pct': float(
                    ticker.get('percentage') or 0
                ),
                'high': float(ticker.get('high') or 0),
                'low': float(ticker.get('low') or 0),
            }
            
        except ccxt.BadSymbol:
            logger.warning(f"⚠️ رمز غير صالح: {symbol}")
            return {}
        except Exception as e:
            logger.error(f"❌ خطأ جلب سعر {symbol}: {e}")
            return {}
    
    async def get_orderbook(
        self,
        symbol: str,
        limit: int = 10
    ) -> Optional[dict]:
        """
        جلب دفتر الأوامر الحقيقي
        
        Args:
            symbol: رمز العملة
            limit: عمق دفتر الأوامر
            
        Returns:
            dict: دفتر الأوامر الحقيقي
        """
        try:
            # بيانات حقيقية من المنصة
            ob = await self._exchange.fetch_order_book(
                symbol, limit=limit
            )
            
            return {
                'bids': ob.get('bids', []),
                'asks': ob.get('asks', []),
                'timestamp': ob.get('timestamp', 0)
            }
            
        except Exception as e:
            logger.debug(f"⚠️ خطأ جلب OrderBook {symbol}: {e}")
            return None
    
    async def set_leverage(
        self,
        symbol: str,
        leverage: int
    ) -> bool:
        """
        ضبط الرافعة المالية على المنصة
        
        Args:
            symbol: رمز العملة
            leverage: الرافعة المطلوبة
            
        Returns:
            bool: نجح؟
        """
        try:
            # ضبط حقيقي على المنصة
            await self._exchange.set_leverage(leverage, symbol)
            logger.debug(f"✅ رافعة {symbol}: {leverage}x")
            return True
            
        except ccxt.ExchangeError as e:
            # بعض العملات لها حد أقصى للرافعة
            logger.warning(f"⚠️ لا يمكن ضبط رافعة {symbol}: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ خطأ ضبط رافعة: {e}")
            return False
    
    async def place_order(
        self,
        symbol: str,
        direction: str,
        size_usd: float,
        leverage: int,
        stop_loss: float,
        take_profit: float
    ) -> Optional[dict]:
        """
        تنفيذ أمر تداول حقيقي على المنصة
        
        Args:
            symbol: رمز العملة
            direction: long أو short
            size_usd: حجم الهامش بالدولار
            leverage: الرافعة المالية
            stop_loss: سعر وقف الخسارة
            take_profit: سعر أخذ الربح
            
        Returns:
            dict: تفاصيل الأمر المنفذ
        """
        try:
            # 1. ضبط الرافعة أولاً
            await self.set_leverage(symbol, leverage)
            
            # 2. جلب السعر الحالي
            ticker = await self.get_ticker(symbol)
            current_price = ticker.get('last', 0)
            
            if not current_price:
                logger.error(f"❌ لا يوجد سعر لـ {symbol}")
                return None
            
            # 3. حساب الكمية الحقيقية
            position_value = size_usd * leverage
            quantity = self._calculate_quantity(
                symbol, position_value, current_price
            )
            
            if quantity <= 0:
                logger.error(f"❌ كمية غير صالحة: {quantity}")
                return None
            
            # 4. تحديد جانب الأمر
            side = 'buy' if direction == 'long' else 'sell'
            
            # 5. تنفيذ الأمر الحقيقي
            params = {
                'stopLoss': {
                    'type': 'market',
                    'stopPrice': stop_loss,
                },
                'takeProfit': {
                    'type': 'limit',
                    'stopPrice': take_profit,
                }
            }
            
            order = await self._exchange.create_order(
                symbol=symbol,
                type='market',
                side=side,
                amount=quantity,
                params=params
            )
            
            logger.info(
                f"✅ أمر منفذ: {symbol} {direction.upper()} "
                f"| الكمية: {quantity} "
                f"| القيمة: ${position_value:.2f}"
            )
            
            return order
            
        except ccxt.InsufficientFunds:
            logger.error(f"❌ رصيد غير كافٍ لـ {symbol}")
            return None
        except ccxt.InvalidOrder as e:
            logger.error(f"❌ أمر غير صالح {symbol}: {e}")
            return None
        except ccxt.ExchangeError as e:
            logger.error(f"❌ خطأ منصة {symbol}: {e}")
            return None
        except Exception as e:
            logger.exception(f"❌ خطأ تنفيذ أمر {symbol}: {e}")
            return None
    
    def _calculate_quantity(
        self,
        symbol: str,
        position_value: float,
        price: float
    ) -> float:
        """
        حساب الكمية الصحيحة للأمر
        مع احترام حدود المنصة
        """
        if price <= 0:
            return 0.0
        
        quantity = position_value / price
        
        # تدوير حسب رمز العملة
        precision_map = {
            'BTC/USDT': 3,
            'ETH/USDT': 3,
            'SOL/USDT': 1,
            'XRP/USDT': 0,
            'BNB/USDT': 2,
        }
        
        decimals = precision_map.get(symbol, 2)
        quantity = round(quantity, decimals)
        
        return max(quantity, 0)
    
    async def close_position(
        self,
        symbol: str,
        direction: str
    ) -> bool:
        """
        إغلاق صفقة مفتوحة بالكامل
        
        Args:
            symbol: رمز العملة
            direction: اتجاه الصفقة الأصلية
            
        Returns:
            bool: نجح؟
        """
        try:
            # الجانب المعاكس للإغلاق
            close_side = (
                'sell' if direction == 'long' else 'buy'
            )
            
            # جلب المركز الحالي
            positions = await self._exchange.fetch_positions(
                [symbol]
            )
            
            if not positions:
                logger.warning(f"⚠️ لا يوجد مركز مفتوح: {symbol}")
                return False
            
            # إيجاد المركز الصحيح
            target_position = None
            for pos in positions:
                pos_side = pos.get('side', '')
                if (pos_side == 'long' and direction == 'long' or
                        pos_side == 'short' and direction == 'short'):
                    if float(pos.get('contracts', 0)) > 0:
                        target_position = pos
                        break
            
            if not target_position:
                logger.warning(f"⚠️ لا يوجد مركز محدد: {symbol}")
                return False
            
            # كمية الإغلاق
            quantity = float(
                target_position.get('contracts', 0)
            )
            
            if quantity <= 0:
                return False
            
            # تنفيذ أمر الإغلاق الحقيقي
            await self._exchange.create_order(
                symbol=symbol,
                type='market',
                side=close_side,
                amount=quantity,
                params={'reduceOnly': True}
            )
            
            logger.info(f"✅ صفقة مغلقة: {symbol}")
            return True
            
        except ccxt.ExchangeError as e:
            logger.error(f"❌ خطأ إغلاق {symbol}: {e}")
            return False
        except Exception as e:
            logger.exception(f"❌ خطأ غير متوقع: {e}")
            return False
    
    async def partial_close(
        self,
        symbol: str,
        direction: str,
        percentage: int
    ) -> bool:
        """
        إغلاق جزئي للصفقة
        
        Args:
            symbol: رمز العملة
            direction: اتجاه الصفقة
            percentage: نسبة الإغلاق (50 = 50%)
            
        Returns:
            bool: نجح؟
        """
        try:
            close_side = (
                'sell' if direction == 'long' else 'buy'
            )
            
            # جلب المركز
            positions = await self._exchange.fetch_positions(
                [symbol]
            )
            
            if not positions:
                return False
            
            for pos in positions:
                pos_contracts = float(pos.get('contracts', 0))
                if pos_contracts > 0:
                    # حساب الكمية الجزئية
                    close_quantity = round(
                        pos_contracts * (percentage / 100), 3
                    )
                    
                    if close_quantity <= 0:
                        return False
                    
                    # تنفيذ الإغلاق الجزئي
                    await self._exchange.create_order(
                        symbol=symbol,
                        type='market',
                        side=close_side,
                        amount=close_quantity,
                        params={'reduceOnly': True}
                    )
                    
                    logger.info(
                        f"✅ إغلاق جزئي: {symbol} "
                        f"{percentage}% = {close_quantity}"
                    )
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ خطأ إغلاق جزئي {symbol}: {e}")
            return False
    
    async def get_open_positions(self) -> List[dict]:
        """
        جلب جميع المراكز المفتوحة الحقيقية
        من المنصة مباشرة
        """
        try:
            # جلب حقيقي من المنصة
            positions = await self._exchange.fetch_positions()
            
            # فلترة المراكز النشطة فقط
            open_positions = []
            for pos in positions:
                contracts = float(pos.get('contracts', 0))
                if contracts > 0:
                    open_positions.append({
                        'symbol': pos.get('symbol', ''),
                        'side': pos.get('side', ''),
                        'size': contracts,
                        'entry_price': float(
                            pos.get('entryPrice', 0)
                        ),
                        'unrealized_pnl': float(
                            pos.get('unrealizedPnl', 0)
                        ),
                        'leverage': float(
                            pos.get('leverage', 1)
                        ),
                        'liquidation_price': float(
                            pos.get('liquidationPrice', 0)
                        ),
                    })
            
            return open_positions
            
        except Exception as e:
            logger.error(f"❌ خطأ جلب المراكز: {e}")
            return []
    
    async def get_funding_rate(self, symbol: str) -> float:
        """
        جلب Funding Rate الحقيقي
        
        Returns:
            float: نسبة التمويل الحالية
        """
        try:
            funding = await self._exchange.fetch_funding_rate(
                symbol
            )
            rate = float(
                funding.get('fundingRate', 0) or 0
            )
            return rate
            
        except Exception as e:
            logger.debug(f"⚠️ خطأ جلب Funding {symbol}: {e}")
            return 0.0
    
    async def cancel_all_orders(self, symbol: str) -> bool:
        """إلغاء جميع الأوامر المعلقة"""
        try:
            await self._exchange.cancel_all_orders(symbol)
            logger.info(f"✅ تم إلغاء جميع أوامر {symbol}")
            return True
        except Exception as e:
            logger.error(f"❌ خطأ إلغاء أوامر {symbol}: {e}")
            return False
    
    async def close(self) -> None:
        """إغلاق الاتصالات بأمان"""
        try:
            if self._binance:
                await self._binance.close()
            if self._bybit:
                await self._bybit.close()
            logger.info("✅ تم إغلاق الاتصالات")
        except Exception as e:
            logger.error(f"❌ خطأ إغلاق الاتصالات: {e}")
