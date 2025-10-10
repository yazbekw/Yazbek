import asyncio
import logging
import time
import os
import math
from datetime import datetime, timedelta
import pytz
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
from telegram import Bot
from telegram.error import TelegramError
import numpy as np
import requests
from flask import Flask
import schedule
import threading

# إعدادات التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)

# تطبيق Flask للحفاظ على تشغيل البوت على Render
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 بوت تداول BNB يعمل بنجاح!"

@app.route('/health')
def health():
    return "✅ البوت في حالة صحية جيدة"

def enable_trailing_stop():
    """تفعيل الوقف المتحرك عبر متغير البيئة"""
    trailing_env = os.getenv('ENABLE_TRAILING_STOP', 'false').lower()
    return trailing_env == 'true'

class BNBScalpingBot:
    def __init__(self):
        # إعدادات API
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        # إعدادات البوت
        self.symbol = 'BNBUSDT'
        self.timeframe = '5m'
        self.leverage = 5
        self.trade_amount = 10  # 10 دولار
        self.max_consecutive_losses = 3
        
        # إعدادات الاستراتيجية
        self.ema_fast = 9
        self.ema_slow = 21
        self.rsi_period = 14
        self.take_profit = 0.008  # 0.8%
        self.stop_loss = 0.005   # 0.5%
        
        # إعدادات الوقف المتحرك
        self.trailing_stop = enable_trailing_stop()
        self.atr_period = 14  # فترة ATR
        self.atr_multiplier = 1.0  # مضاعف ATR للوقف المتحرك
        self.trailing_activation_profit = 0.3  # نسبة الربح الأولي لتفعيل الوقف المتحرك (%)
        
        # حالة البوت
        self.client = None
        self.telegram_bot = None
        self.is_running = True
        self.consecutive_losses = 0
        self.daily_trades = 0
        self.daily_profit = 0
        self.open_position = None
        self.health_check_counter = 0
        self.last_price = 0
        self.symbol_info = None
        self.initialized = False
        
        # وقت دمشق
        self.damascus_tz = pytz.timezone('Asia/Damascus')
        
        logging.info(f"الوقف المتحرك: {'مفعل' if self.trailing_stop else 'غير مفعل'}")

    async def send_telegram_notification(self, message, level="info"):
        """إرسال اشعار تلغرام مع إيموجي حسب المستوى"""
        # التحقق من أن Telegram bot مهيأ
        if self.telegram_bot is None:
            logging.error("Telegram bot not initialized - cannot send notification")
            return
        
        emojis = {
            "info": "ℹ️",
            "success": "✅", 
            "warning": "⚠️",
            "error": "❌",
            "buy": "🟢",
            "sell": "🔴",
            "analysis": "📊",
            "monitoring": "👀",
            "execution": "⚡",
            "market": "📈"
        }
        
        emoji = emojis.get(level, "📢")
        formatted_message = f"{emoji} {message}"
        
        try:
            await self.telegram_bot.send_message(
                chat_id=self.telegram_chat_id,
                text=formatted_message,
                parse_mode='Markdown'
            )
            logging.info(f"Telegram notification sent: {message}")
        except TelegramError as e:
            logging.error(f"Failed to send Telegram notification: {e}")
        except Exception as e:
            logging.error(f"Unexpected error sending Telegram notification: {e}")

    async def get_symbol_info(self):
        """الحصول على معلومات الزوج لتحديد الدقة"""
        try:
            if self.symbol_info is None:
                await self.send_telegram_notification("🔍 جاري الحصول على معلومات الزوج...", "market")
                info = self.client.futures_exchange_info()
                for symbol in info['symbols']:
                    if symbol['symbol'] == self.symbol:
                        self.symbol_info = symbol
                        await self.send_telegram_notification("✅ تم تحميل معلومات الزوج بنجاح", "success")
                        logging.info(f"Symbol info loaded: {symbol['symbol']}")
                        break
            return self.symbol_info
        except Exception as e:
            error_msg = f"❌ خطأ في الحصول على معلومات الزوج: {str(e)}"
            await self.send_telegram_notification(error_msg, "error")
            logging.error(f"Error getting symbol info: {e}")
            return None

    async def adjust_quantity(self, quantity):
        """ضبط الكمية حسب الدقة المسموحة"""
        try:
            symbol_info = await self.get_symbol_info()
            if symbol_info:
                # الحصول على دقة الكمية
                quantity_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                if quantity_filter:
                    step_size = float(quantity_filter['stepSize'])
                    # تقريب الكمية حسب stepSize
                    precision = int(round(-math.log(step_size, 10))) if step_size < 1 else 0
                    adjusted_quantity = math.floor(quantity / step_size) * step_size
                    adjusted_quantity = round(adjusted_quantity, precision)
                    logging.info(f"Adjusted quantity: {quantity} -> {adjusted_quantity} (step: {step_size}, precision: {precision})")
                    return adjusted_quantity
            
            # إذا لم نتمكن من الحصول على المعلومات، نستخدم دقة افتراضية
            default_quantity = round(quantity, 3)
            logging.info(f"Using default quantity: {default_quantity}")
            return default_quantity
        except Exception as e:
            logging.error(f"Error adjusting quantity: {e}")
            default_quantity = round(quantity, 3)
            return default_quantity

    async def validate_chat_id(self):
        """التحقق من صحة معرف الدردشة"""
        try:
            # محاولة إرسال رسالة اختبار
            await self.send_telegram_notification("🔍 اختبار اتصال البوت...", "info")
            logging.info("✅ Chat ID is valid")
            return True
        except TelegramError as e:
            if "bots can't send messages to bots" in str(e):
                error_msg = "❌ معرف الدردشة ينتمي لبوت آخر - البوتات لا يمكنها إرسال رسائل لبوتات أخرى"
                await self.send_telegram_notification(error_msg, "error")
                return False
            else:
                logging.error(f"Telegram error: {e}")
                return False
        except Exception as e:
            logging.error(f"Unexpected error validating chat ID: {e}")
            return False

    async def initialize(self):
        """تهيئة الاتصالات"""
        try:
            # التحقق من وجود جميع المتغيرات البيئية
            if not all([self.api_key, self.api_secret, self.telegram_token, self.telegram_chat_id]):
                error_msg = "❌ متغيرات بيئية مفقودة. يرجى التحقق من BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID"
                logging.error(error_msg)
                return False

            await self.send_telegram_notification("🚀 بدء تهيئة البوت...", "info")
            
            # Binance Client
            try:
                self.client = Client(self.api_key, self.api_secret, testnet=False)
                await self.send_telegram_notification("✅ تم الاتصال بـ Binance بنجاح", "success")
            except Exception as e:
                error_msg = f"❌ فشل الاتصال بـ Binance: {str(e)}"
                await self.send_telegram_notification(error_msg, "error")
                return False
            
            # Telegram Bot
            try:
                self.telegram_bot = Bot(token=self.telegram_token)
                # اختبار اتصال Telegram
                await self.telegram_bot.get_me()
                await self.send_telegram_notification("✅ تم الاتصال بـ Telegram بنجاح", "success")
            except Exception as e:
                error_msg = f"❌ فشل الاتصال بـ Telegram: {str(e)}"
                logging.error(error_msg)
                return False
            
            # التحقق من صحة معرف الدردشة
            if not await self.validate_chat_id():
                return False
            
            # تعيين الرافعة المالية
            try:
                self.client.futures_change_leverage(symbol=self.symbol, leverage=self.leverage)
                await self.send_telegram_notification(f"⚡ تم تعيين الرافعة المالية: {self.leverage}x", "success")
            except Exception as e:
                error_msg = f"⚠️ تحذير: فشل تعيين الرافعة المالية: {str(e)}"
                await self.send_telegram_notification(error_msg, "warning")
            
            # الحصول على معلومات الزوج مسبقاً
            await self.get_symbol_info()
            
            # الحصول على معلومات الحساب الكاملة
            try:
                account_info = self.client.futures_account()
                
                # البحث عن رصيد USDT الصحيح
                usdt_balance = 0
                for asset in account_info['assets']:
                    if asset['asset'] == 'USDT':
                        usdt_balance = float(asset['walletBalance'])
                        break
                
                # استخدام الرصيد المتاح للتداول
                available_balance = float(account_info['availableBalance'])
                total_wallet_balance = float(account_info['totalWalletBalance'])
                
                # الحصول على السعر الحالي للتحقق
                current_price = self.get_current_price()
                
                await self.send_telegram_notification(f"""
📈 **بوت التداول بدأ العمل بنجاح!** 📈
• **الرصيد الإجمالي:** {total_wallet_balance:.2f} USDT 💰
• **الرصيد المتاح:** {available_balance:.2f} USDT 💵
• **رصيد المحفظة:** {usdt_balance:.2f} USDT 💳
• **السعر الحالي:** {current_price:.4f} USD 💲
• **الرافعة المالية:** {self.leverage}x ⚙️
• **الوقف المتحرك:** {'🟢 مفعل' if self.trailing_stop else '🔴 غير مفعل'} 🔄
• **زمن التشغيل:** {datetime.now(self.damascus_tz).strftime('%Y-%m-%d %H:%M:%S')} ⏰
                """, "success")
                
                logging.info(f"Bot initialized successfully - Total Balance: {total_wallet_balance}, Available: {available_balance}, Current Price: {current_price}")
                
            except Exception as e:
                error_msg = f"⚠️ تحذير: فشل الحصول على معلومات الحساب: {str(e)}"
                await self.send_telegram_notification(error_msg, "warning")
            
            self.initialized = True
            return True
            
        except Exception as e:
            error_msg = f"❌ خطأ في التهيئة: {str(e)}"
            logging.error(f"Initialization error: {e}")
            # محاولة إرسال رسالة خطأ عبر Telegram إذا كان متصلاً
            if self.telegram_bot:
                await self.send_telegram_notification(error_msg, "error")
            return False
    
    def calculate_ema(self, data, period):
        """حساب المتوسط المتحرك الأسي"""
        return data.ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, data, period=14):
        """حساب مؤشر RSI"""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_atr(self, df, period=14):
        """حساب Average True Range (ATR)"""
        try:
            high_low = df['high'] - df['low']
            high_close = abs(df['high'] - df['close'].shift())
            low_close = abs(df['low'] - df['close'].shift())
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = true_range.rolling(window=period).mean()
            return atr.iloc[-1]  # إرجاع آخر قيمة ATR
        except Exception as e:
            logging.error(f"Error calculating ATR: {e}")
            return 0
    
    async def get_ohlc_data(self, limit=100):
        """الحصول على بيانات OHLC"""
        try:
            await self.send_telegram_notification("📊 جاري جمع بيانات السوق...", "market")
            
            klines = self.client.futures_klines(
                symbol=self.symbol,
                interval=self.timeframe,
                limit=limit
            )
            
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # تحويل الأعمدة إلى أرقام
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna()
            
            await self.send_telegram_notification(f"✅ تم جمع {len(df)} شمعة من بيانات السوق", "market")
            
            return df
            
        except Exception as e:
            error_msg = f"❌ خطأ في جمع بيانات السوق: {str(e)}"
            await self.send_telegram_notification(error_msg, "error")
            logging.error(f"Error getting OHLC data: {e}")
            return None
    
    def get_current_price(self):
        """الحصول على السعر الحالي"""
        try:
            if self.client is None:
                logging.error("Binance client not initialized")
                return 0
                
            ticker = self.client.futures_symbol_ticker(symbol=self.symbol)
            price = float(ticker['price'])
            if price <= 0:
                logging.error(f"Invalid price received: {price}")
                return 0
            self.last_price = price
            return price
        except Exception as e:
            logging.error(f"Error getting current price: {e}")
            return 0
    
    async def analyze_signals(self, df):
        """تحليل الإشارات بناءً على الاستراتيجية"""
        if df is None or len(df) < 50:
            return None
        
        await self.send_telegram_notification("🔍 جاري تحليل الإشارات...", "analysis")
        
        # حساب المؤشرات
        df['ema_fast'] = self.calculate_ema(df['close'], self.ema_fast)
        df['ema_slow'] = self.calculate_ema(df['close'], self.ema_slow)
        df['rsi'] = self.calculate_rsi(df['close'], self.rsi_period)
        
        current = df.iloc[-1]
        previous = df.iloc[-2]
        
        signals = {
            'long_signal': False,
            'short_signal': False,
            'ema_fast': current['ema_fast'],
            'ema_slow': current['ema_slow'],
            'rsi': current['rsi'],
            'price': current['close'],
            'timestamp': datetime.now()
        }
        
        # إشارة شراء (Long)
        if (current['ema_fast'] > current['ema_slow'] and 
            previous['ema_fast'] <= previous['ema_slow'] and
            current['rsi'] > 50 and
            current['close'] > current['open']):
            signals['long_signal'] = True
            await self.send_telegram_notification(f"""
🟢 **إشارة شراء تم اكتشافها!**
• EMA السريع: {current['ema_fast']:.4f} ↗️
• EMA البطيء: {current['ema_slow']:.4f} ↘️  
• RSI: {current['rsi']:.2f} 📊
• السعر: {current['close']:.4f} USD 💲
            """, "buy")
            
        # إشارة بيع (Short)
        elif (current['ema_fast'] < current['ema_slow'] and 
              previous['ema_fast'] >= previous['ema_slow'] and
              current['rsi'] < 50 and
              current['close'] < current['open']):
            signals['short_signal'] = True
            await self.send_telegram_notification(f"""
🔴 **إشارة بيع تم اكتشافها!**
• EMA السريع: {current['ema_fast']:.4f} ↘️
• EMA البطيء: {current['ema_slow']:.4f} ↗️
• RSI: {current['rsi']:.2f} 📊
• السعر: {current['close']:.4f} USD 💲
            """, "sell")
        else:
            await self.send_telegram_notification("⏸️ لا توجد إشارات تداول حالياً", "info")
            
        return signals
    
    async def execute_trade(self, signal_type, price):
        """تنفيذ صفقة"""
        try:
            if self.consecutive_losses >= self.max_consecutive_losses:
                await self.send_telegram_notification("🛑 **توقف التداول!** 3 خسائر متتالية. يرجى التحقق يدويًا.", "warning")
                return None
            
            # التحقق من صحة السعر
            if price <= 0:
                logging.error(f"Invalid price for trade: {price}")
                await self.send_telegram_notification(f"❌ **سعر غير صالح للتداول!** السعر: {price}", "error")
                return None
            
            await self.send_telegram_notification(f"⚡ محاولة تنفيذ صفقة {signal_type}...", "execution")
            
            # حساب الكمية مع الضبط
            raw_quantity = self.trade_amount / price
            logging.info(f"Raw quantity calculation: {self.trade_amount} / {price} = {raw_quantity}")
            
            if raw_quantity <= 0:
                logging.error(f"Invalid raw quantity: {raw_quantity}")
                await self.send_telegram_notification(f"❌ **الكمية غير صالحة!** الكمية المحسوبة: {raw_quantity}", "error")
                return None
            
            quantity = await self.adjust_quantity(raw_quantity)
            
            # التحقق النهائي من الكمية
            if quantity <= 0:
                logging.error(f"Adjusted quantity is invalid: {quantity}")
                await self.send_telegram_notification(f"❌ **الكمية المعدلة غير صالحة!** الكمية: {quantity}", "error")
                return None

            # التحقق من الحد الأدنى للكمية
            symbol_info = await self.get_symbol_info()
            if symbol_info:
                quantity_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                if quantity_filter:
                    min_qty = float(quantity_filter['minQty'])
                    if quantity < min_qty:
                        logging.error(f"Quantity below minimum: {quantity} < {min_qty}")
                        await self.send_telegram_notification(f"❌ **الكمية أقل من المسموح!** الكمية: {quantity} < الحد الأدنى: {min_qty}", "error")
                        return None

            if signal_type == 'LONG':
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=Client.SIDE_BUY,
                    type=Client.ORDER_TYPE_MARKET,
                    quantity=quantity
                )
            else:  # SHORT
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side=Client.SIDE_SELL,
                    type=Client.ORDER_TYPE_MARKET,
                    quantity=quantity
                )
            
            # إعداد وقف الخسارة وجني الربح
            stop_price = price * (1 - self.stop_loss) if signal_type == 'LONG' else price * (1 + self.stop_loss)
            take_profit_price = price * (1 + self.take_profit) if signal_type == 'LONG' else price * (1 - self.take_profit)
            
            self.open_position = {
                'order_id': order['orderId'],
                'side': signal_type,
                'entry_price': price,
                'quantity': quantity,
                'stop_loss': stop_price,
                'take_profit': take_profit_price,
                'timestamp': datetime.now()
            }
            
            trailing_info = " (مع وقف متحرك ديناميكي)" if self.trailing_stop else ""
            
            message = f"""
🎯 **صفقة جديدة مفتوحة{trailing_info}!** 🎯
• **النوع:** {signal_type} 📊
• **سعر الدخول:** {price:.4f} USD 💲
• **الكمية:** {quantity} BNB 📦
• **القيمة:** {quantity * price:.2f} USD 💰
• **وقف الخسارة:** {stop_price:.4f} USD 🛑
• **جني الربح:** {take_profit_price:.4f} USD ✅
• **الوقت:** {datetime.now(self.damascus_tz).strftime('%H:%M:%S')} ⏰
• **الرافعة:** {self.leverage}x ⚙️
            """
            
            await self.send_telegram_notification(message, "success")
            logging.info(f"New {signal_type} trade executed at {price} with quantity {quantity}")
            
            return order
            
        except BinanceAPIException as e:
            error_msg = f"❌ **خطأ في تنفيذ الصفقة!** التفاصيل: {str(e)}"
            if "Precision" in str(e):
                error_msg += "\n🔧 **تم تعديل الدقة تلقائياً، جاري إعادة المحاولة...**"
                logging.error(f"Precision error, retrying with adjusted quantity: {e}")
            await self.send_telegram_notification(error_msg, "error")
            return None
        except Exception as e:
            logging.error(f"Trade execution error: {e}")
            await self.send_telegram_notification(f"❌ **خطأ في تنفيذ الصفقة!** التفاصيل: {str(e)}", "error")
            return None

    async def monitor_position(self):
        """مراقبة الصفقة المفتوحة مع الوقف المتحرك الديناميكي"""
        await self.send_telegram_notification("👀 بدء مراقبة الصفقة المفتوحة...", "monitoring")
        
        while self.open_position and self.is_running:
            try:
                current_price = self.get_current_price()
                if current_price == 0:
                    await asyncio.sleep(10)
                    continue

                position = self.open_position

                # حساب نسبة الربح/الخسارة الحالية
                if position['side'] == 'LONG':
                    profit_percent = (current_price - position['entry_price']) / position['entry_price'] * 100
                else:  # SHORT
                    profit_percent = (position['entry_price'] - current_price) / position['entry_price'] * 100

                # تفعيل الوقف المتحرك فقط إذا تحقق ربح أولي 0.3%
                trailing_active = profit_percent >= self.trailing_activation_profit

                # تطبيق الوقف المتحرك إذا كان مفعلاً
                if self.trailing_stop and trailing_active:
                    # الحصول على بيانات OHLC لحساب ATR
                    df = await self.get_ohlc_data(limit=50)
                    if df is None:
                        await asyncio.sleep(10)
                        continue

                    # حساب ATR
                    atr = self.calculate_atr(df, period=self.atr_period)
                    if atr == 0:
                        await asyncio.sleep(10)
                        continue

                    # تعديل الوقف المتحرك بناءً على ATR (مثل 1x ATR)
                    dynamic_stop = atr * self.atr_multiplier

                    if position['side'] == 'LONG' and current_price > position['entry_price']:
                        new_stop = current_price - dynamic_stop
                        if new_stop > position['stop_loss']:
                            position['stop_loss'] = new_stop
                            logging.info(f"🔄 تحديث الوقف المتحرك للشراء: {new_stop:.4f} (ATR: {atr:.4f})")
                            await self.send_telegram_notification(
                                f"🔄 **تحديث الوقف المتحرك للشراء!** 🔄\n• **الوقف الجديد:** {new_stop:.4f} USD 🛑\n• **ATR الحالي:** {atr:.4f} 📊\n• **السعر الحالي:** {current_price:.4f} USD 💲",
                                "monitoring"
                            )

                    elif position['side'] == 'SHORT' and current_price < position['entry_price']:
                        new_stop = current_price + dynamic_stop
                        if new_stop < position['stop_loss']:
                            position['stop_loss'] = new_stop
                            logging.info(f"🔄 تحديث الوقف المتحرك للبيع: {new_stop:.4f} (ATR: {atr:.4f})")
                            await self.send_telegram_notification(
                                f"🔄 **تحديث الوقف المتحرك للبيع!** 🔄\n• **الوقف الجديد:** {new_stop:.4f} USD 🛑\n• **ATR الحالي:** {atr:.4f} 📊\n• **السعر الحالي:** {current_price:.4f} USD 💲",
                                "monitoring"
                            )

                # التحقق من وقف الخسارة وجني الربح
                should_close = False
                close_reason = ""

                if position['side'] == 'LONG':
                    if current_price <= position['stop_loss']:
                        should_close = True
                        close_reason = "وقف الخسارة"
                    elif current_price >= position['take_profit']:
                        should_close = True
                        close_reason = "جني الربح"
                        
                elif position['side'] == 'SHORT':
                    if current_price >= position['stop_loss']:
                        should_close = True
                        close_reason = "وقف الخسارة"
                    elif current_price <= position['take_profit']:
                        should_close = True
                        close_reason = "جني الربح"
                
                # إغلاق الصفقة بعد 15 دقيقة كحد أقصى
                time_in_position = datetime.now() - position['timestamp']
                if time_in_position.total_seconds() > 15 * 60:  # 15 دقيقة
                    should_close = True
                    close_reason = "انتهاء الوقت"
                
                if should_close:
                    await self.send_telegram_notification(f"📋 سبب إغلاق الصفقة: {close_reason}", "monitoring")
                    await self.close_position(current_price, close_reason)
                    break
                
                await asyncio.sleep(10)  # التحقق كل 10 ثواني
                
            except Exception as e:
                logging.error(f"Position monitoring error: {e}")
                await self.send_telegram_notification(f"❌ خطأ في مراقبة الصفقة: {str(e)}", "error")
                await asyncio.sleep(30)

    async def close_position(self, exit_price, reason=""):
        """إغلاق الصفقة مع ذكر السبب"""
        try:
            position = self.open_position
            
            if position['side'] == 'LONG':
                side = Client.SIDE_SELL
            else:
                side = Client.SIDE_BUY
            
            await self.send_telegram_notification("🔄 جاري إغلاق الصفقة...", "execution")
            
            order = self.client.futures_create_order(
                symbol=self.symbol,
                side=side,
                type=Client.ORDER_TYPE_MARKET,
                quantity=position['quantity']
            )
            
            # حساب الربح/الخسارة
            if position['side'] == 'LONG':
                pnl_percent = (exit_price - position['entry_price']) / position['entry_price'] * 100
            else:
                pnl_percent = (position['entry_price'] - exit_price) / position['entry_price'] * 100
            
            pnl_usd = pnl_percent * self.trade_amount / 100
            
            # تحديث الإحصائيات
            self.daily_trades += 1
            self.daily_profit += pnl_usd
            
            if pnl_usd < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0
            
            # إرسال إشعار مع سبب الإغلاق
            emoji = "✅" if pnl_usd > 0 else "❌"
            result_text = "ربح" if pnl_usd > 0 else "خسارة"
            trailing_info = " (مع وقف متحرك ديناميكي)" if self.trailing_stop else ""
            
            # حساب المدة
            time_in_position = datetime.now() - position['timestamp']
            
            message = f"""
{emoji} **صفقة مغلقة{trailing_info}!** {emoji}
• **السبب:** {reason} 📌
• **النوع:** {position['side']} 📊
• **سعر الدخول:** {position['entry_price']:.4f} USD 💲
• **سعر الخروج:** {exit_price:.4f} USD 💲
• **النتيجة:** {result_text} 📈
• **المبلغ:** {pnl_usd:.2f} USD ({pnl_percent:.2f}%) 💰
• **الخسائر المتتالية:** {self.consecutive_losses} ⚠️
• **المدة:** {str(time_in_position).split('.')[0]} ⏱️
            """
            
            await self.send_telegram_notification(message, "success" if pnl_usd > 0 else "error")
            logging.info(f"Position closed with PnL: {pnl_usd:.2f} USD, Reason: {reason}")
            
            self.open_position = None
            
        except Exception as e:
            logging.error(f"Position closing error: {e}")
            await self.send_telegram_notification(f"❌ **خطأ في إغلاق الصفقة!** التفاصيل: {str(e)}", "error")
    
    async def health_check(self):
        """فحص صحي للبوت"""
        self.health_check_counter += 1
        
        try:
            await self.send_telegram_notification("🏥 جاري الفحص الصحي للبوت...", "info")
            
            # التحقق من اتصال Binance
            self.client.futures_exchange_info()
            
            # التحقق من اتصال Telegram
            await self.telegram_bot.get_me()
            
            # التحقق من الرصيد
            account_info = self.client.futures_account()
            available_balance = float(account_info['availableBalance'])
            total_wallet_balance = float(account_info['totalWalletBalance'])
            
            # إرسال تقرير صحي كل 6 ساعات
            if self.health_check_counter % 72 == 0:  # كل 6 ساعات (12 فحص × 6 = 72)
                status_message = f"""
🏥 **فحص صحي للبوت:** 🏥
• **اتصال Binance:** ✅ متصل
• **اتصال Telegram:** ✅ متصل  
• **الرصيد الإجمالي:** {total_wallet_balance:.2f} USDT 💰
• **الرصيد المتاح:** {available_balance:.2f} USDT 💵
• **الصفقات النشطة:** {'1 (نشطة)' if self.open_position else '0 (لا صفقات نشطة)'} 📊
• **الخسائر المتتالية:** {self.consecutive_losses} ⚠️
• **الوقت الحالي:** {datetime.now(self.damascus_tz).strftime('%H:%M:%S')} ⏰
                """
                await self.send_telegram_notification(status_message, "info")
                logging.info("Health check passed")
            
            await self.send_telegram_notification("✅ الفحص الصحي تم بنجاح", "success")
            return True
            
        except Exception as e:
            error_msg = f"❌ **فحص صحي فاشل!** التفاصيل: {str(e)}\nيرجى التحقق من الاتصال أو الإعدادات."
            await self.send_telegram_notification(error_msg, "error")
            logging.error(f"Health check failed: {e}")
            return False
    
    async def daily_report(self):
        """تقرير يومي الساعة 23 بتوقيت دمشق"""
        while self.is_running:
            now = datetime.now(self.damascus_tz)
            target_time = now.replace(hour=23, minute=0, second=0, microsecond=0)
            
            if now >= target_time:
                target_time += timedelta(days=1)
            
            wait_seconds = (target_time - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            
            # الحصول على الرصيد الحالي
            try:
                account_info = self.client.futures_account()
                available_balance = float(account_info['availableBalance'])
                total_wallet_balance = float(account_info['totalWalletBalance'])
            except:
                available_balance = 0
                total_wallet_balance = 0
            
            # إرسال التقرير اليومي
            report = f"""
📊 **التقرير اليومي للتداول:** 📊
• **عدد الصفقات:** {self.daily_trades} 📊
• **إجمالي الربح/الخسارة:** {self.daily_profit:.2f} USD 💰
• **الخسائر المتتالية:** {self.consecutive_losses} ⚠️
• **الرصيد الإجمالي:** {total_wallet_balance:.2f} USDT 💰
• **الرصيد المتاح:** {available_balance:.2f} USDT 💵
• **الوقف المتحرك:** {'🟢 مفعل' if self.trailing_stop else '🔴 غير مفعل'} 🔄
• **حالة البوت:** {'🟢 نشط' if self.is_running else '🔴 متوقف'} 📡

**التاريخ:** {datetime.now(self.damascus_tz).strftime('%Y-%m-%d %H:%M:%S')} ⏰
            """
            
            await self.send_telegram_notification(report, "info")
            
            # إعادة تعيين الإحصائيات اليومية
            self.daily_trades = 0
            self.daily_profit = 0
            
            logging.info("Daily report sent and statistics reset")
    
    async def run_bot(self):
        """الدالة الرئيسية لتشغيل البوت"""
        if not await self.initialize():
            logging.error("Failed to initialize bot. Stopping...")
            return
    
        logging.info("Starting trading bot...")
        await self.send_telegram_notification("🚀 بدء تشغيل بوت التداول...", "info")
    
        # تشغيل المهام المتزامنة
        tasks = [
            asyncio.create_task(self.daily_report()),
        ]
    
        try:
            while self.is_running:
                # فحص صحي كل 5 دقائق
                if not await self.health_check():
                    await asyncio.sleep(60)
                    continue
            
                # إذا كانت هناك صفقة مفتوحة، انتقل للدورة التالية
                if self.open_position:
                    await asyncio.sleep(30)
                    continue
            
                # الحصول على البيانات وتحليلها
                df = await self.get_ohlc_data()
                if df is None:
                    await asyncio.sleep(60)
                    continue
                    
                signals = await self.analyze_signals(df)
            
                if signals:
                    logging.info(f"Signals - EMA Fast: {signals['ema_fast']:.4f}, EMA Slow: {signals['ema_slow']:.4f}, RSI: {signals['rsi']:.2f}, Price: {signals['price']:.4f}")
                
                    # ✅ الحل: استخدام السعر الحالي المباشر من Binance
                    current_price = self.get_current_price()
                    logging.info(f"Current market price: {current_price}")
                
                    # ✅ التحقق النهائي من السعر
                    if current_price > 0:
                        if signals['long_signal'] and not self.open_position:
                            await self.execute_trade('LONG', current_price)
                            if self.open_position:
                                tasks.append(asyncio.create_task(self.monitor_position()))
                    
                        elif signals['short_signal'] and not self.open_position:
                            await self.execute_trade('SHORT', current_price)
                            if self.open_position:
                                tasks.append(asyncio.create_task(self.monitor_position()))
                    else:
                        logging.error(f"Invalid current price: {current_price}")
                        await self.send_telegram_notification(f"❌ سعر حالي غير صالح: {current_price}", "error")
            
                # انتظر دقيقة قبل التحليل التالي
                await asyncio.sleep(60)
                
        except KeyboardInterrupt:
            logging.info("Bot stopped by user")
            await self.send_telegram_notification("🛑 **البوت توقف بواسطة المستخدم!**", "warning")
        except Exception as e:
            logging.error(f"Bot error: {e}")
            await self.send_telegram_notification(f"🆘 **البوت توقف بسبب خطأ!** التفاصيل: {str(e)}", "error")
        finally:
            self.is_running = False
            # إلغاء جميع المهام
            for task in tasks:
                task.cancel()
            
            await self.send_telegram_notification("🛑 **البوت توقف عن العمل!**", "warning")

async def main():
    """الدالة الرئيسية"""
    bot = BNBScalpingBot()
    await bot.run_bot()

def run_flask():
    """تشغيل Flask في thread منفصل"""
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    # التحقق من وجود المتغيرات البيئية
    required_env_vars = ['BINANCE_API_KEY', 'BINANCE_API_SECRET', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        print(f"❌ المتغيرات البيئية المفقودة: {', '.join(missing_vars)}")
        print("⏹️  إيقاف التشغيل...")
        exit(1)
    
    print("🚀 بدء تشغيل بوت التداول...")
    print("⏰ الوقت الحالي في دمشق:", datetime.now(pytz.timezone('Asia/Damascus')).strftime('%Y-%m-%d %H:%M:%S'))
    
    # تشغيل Flask في thread منفصل
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # تشغيل البوت
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ خطأ في التشغيل: {e}")
