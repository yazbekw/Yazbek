import asyncio
import logging
import time
import os
from datetime import datetime, timedelta
import pytz
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.websockets import BinanceSocketManager
from telegram import Bot
from telegram.error import TelegramError
import numpy as np
import requests

# إعدادات التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)

def enable_trailing_stop():
    """سؤال المستخدم إذا كان يريد تفعيل الوقف المتحرك"""
    # على Render لن يعمل input، لذا نستخدم متغير بيئي أو نفعله افتراضيًا
    trailing_env = os.getenv('ENABLE_TRAILING_STOP', 'false').lower()
    if trailing_env == 'true':
        return True
    elif trailing_env == 'false':
        return False
    else:
        # لو كان التشغيل محليًا
        try:
            response = input("هل تريد تفعيل الوقف المتحرك؟ (y/n): ")
            return response.lower() == 'y'
        except:
            return False  # افتراضي غير مفعل على Render

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
        
        # تفعيل الوقف المتحرك
        self.trailing_stop = enable_trailing_stop()
        
        # حالة البوت
        self.client = None
        self.telegram_bot = None
        self.is_running = True
        self.consecutive_losses = 0
        self.daily_trades = 0
        self.daily_profit = 0
        self.open_position = None
        self.health_check_counter = 0
        
        # وقت دمشق
        self.damascus_tz = pytz.timezone('Asia/Damascus')
        
        logging.info(f"الوقف المتحرك: {'مفعل' if self.trailing_stop else 'غير مفعل'}")

    async def initialize(self):
        """تهيئة الاتصالات"""
        try:
            # Binance Client
            self.client = Client(self.api_key, self.api_secret, testnet=False)
            
            # Telegram Bot
            self.telegram_bot = Bot(token=self.telegram_token)
            
            # تعيين الرافعة المالية
            self.client.futures_change_leverage(symbol=self.symbol, leverage=self.leverage)
            
            # الحصول على رصيد الحساب
            balance_info = self.client.futures_account_balance()
            usdt_balance = next((item for item in balance_info if item['asset'] == 'USDT'), None)
            
            await self.send_telegram_message(f"""
🤖 بوت التداول بدأ العمل بنجاح!
• الرصيد: {float(usdt_balance['balance']):.2f} USDT
• الرافعة: {self.leverage}x
• الوقف المتحرك: {'🟢 مفعل' if self.trailing_stop else '🔴 غير مفعل'}
• زمن التشغيل: {datetime.now(self.damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}
            """)
            
            logging.info("Bot initialized successfully")
            return True
            
        except Exception as e:
            logging.error(f"Initialization error: {e}")
            return False
    
    def calculate_ema(self, data, period):
        """حساب المتوسط المتحرك الأسي"""
        return data.ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, data, period=14):
        """حساب مؤشر RSI"""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def get_ohlc_data(self, limit=100):
        """الحصول على بيانات OHLC"""
        try:
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
            
            df['close'] = pd.to_numeric(df['close'])
            df['high'] = pd.to_numeric(df['high'])
            df['low'] = pd.to_numeric(df['low'])
            df['open'] = pd.to_numeric(df['open'])
            
            return df
            
        except Exception as e:
            logging.error(f"Error getting OHLC data: {e}")
            return None
    
    def analyze_signals(self, df):
        """تحليل الإشارات بناءً على الاستراتيجية"""
        if df is None or len(df) < 50:
            return None
        
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
            
        # إشارة بيع (Short)
        elif (current['ema_fast'] < current['ema_slow'] and 
              previous['ema_fast'] >= previous['ema_slow'] and
              current['rsi'] < 50 and
              current['close'] < current['open']):
            signals['short_signal'] = True
            
        return signals
    
    async def execute_trade(self, signal_type, price):
        """تنفيذ صفقة"""
        try:
            if self.consecutive_losses >= self.max_consecutive_losses:
                await self.send_telegram_message("🛑 توقف التداول بعد 3 خسائر متتالية!")
                return None
            
            # حساب الكمية
            quantity = round(self.trade_amount / price, 3)
            
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
            
            trailing_info = " (مع وقف متحرك)" if self.trailing_stop else ""
            
            message = f"""
🎯 صفقة جديدة{trailing_info}:
• النوع: {signal_type}
• السعر: {price:.4f}
• الكمية: {quantity}
• وقف الخسارة: {stop_price:.4f}
• جني الربح: {take_profit_price:.4f}
• الوقت: {datetime.now(self.damascus_tz).strftime('%H:%M:%S')}
            """
            
            await self.send_telegram_message(message)
            logging.info(f"New {signal_type} trade executed at {price}")
            
            return order
            
        except Exception as e:
            logging.error(f"Trade execution error: {e}")
            await self.send_telegram_message(f"❌ خطأ في تنفيذ الصفقة: {e}")
            return None

    async def monitor_position(self):
        """مراقبة الصفقة المفتوحة مع الوقف المتحرك"""
        while self.open_position and self.is_running:
            try:
                current_price = float(self.client.futures_symbol_ticker(symbol=self.symbol)['price'])
                position = self.open_position
                
                # تطبيق الوقف المتحرك إذا كان مفعلاً
                if self.trailing_stop:
                    if position['side'] == 'LONG' and current_price > position['entry_price']:
                        new_stop = current_price * (1 - self.stop_loss)
                        if new_stop > position['stop_loss']:
                            position['stop_loss'] = new_stop
                            logging.info(f"🔄 تحديث الوقف المتحرك للشراء: {new_stop:.4f}")
                    
                    elif position['side'] == 'SHORT' and current_price < position['entry_price']:
                        new_stop = current_price * (1 + self.stop_loss)
                        if new_stop < position['stop_loss']:
                            position['stop_loss'] = new_stop
                            logging.info(f"🔄 تحديث الوقف المتحرك للبيع: {new_stop:.4f}")
                
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
                    await self.close_position(current_price, close_reason)
                    break
                
                await asyncio.sleep(10)  # التحقق كل 10 ثواني
                
            except Exception as e:
                logging.error(f"Position monitoring error: {e}")
                await asyncio.sleep(30)

    async def close_position(self, exit_price, reason=""):
        """إغلاق الصفقة مع ذكر السبب"""
        try:
            position = self.open_position
            
            if position['side'] == 'LONG':
                side = Client.SIDE_SELL
            else:
                side = Client.SIDE_BUY
            
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
            trailing_info = " (مع وقف متحرك)" if self.trailing_stop else ""
            
            message = f"""
{emoji} صفقة مغلقة{trailing_info}:
• السبب: {reason}
• النوع: {position['side']}
• سعر الدخول: {position['entry_price']:.4f}
• سعر الخروج: {exit_price:.4f}
• النتيجة: {'ربح' if pnl_usd > 0 else 'خسارة'}
• المبلغ: {pnl_usd:.2f} دولار ({pnl_percent:.2f}%)
• الخسائر المتتالية: {self.consecutive_losses}
• المدة: {str(datetime.now() - position['timestamp']).split('.')[0]}
            """
            
            await self.send_telegram_message(message)
            logging.info(f"Position closed with PnL: {pnl_usd:.2f} USD, Reason: {reason}")
            
            self.open_position = None
            
        except Exception as e:
            logging.error(f"Position closing error: {e}")
            await self.send_telegram_message(f"❌ خطأ في إغلاق الصفقة: {e}")
    
    async def health_check(self):
        """فحص صحي للبوت"""
        self.health_check_counter += 1
        
        try:
            # التحقق من اتصال Binance
            self.client.futures_exchange_info()
            
            # التحقق من اتصال Telegram
            await self.telegram_bot.get_me()
            
            # التحقق من الرصيد
            balance_info = self.client.futures_account_balance()
            usdt_balance = next((item for item in balance_info if item['asset'] == 'USDT'), None)
            
            # إرسال تقرير صحي كل 6 ساعات
            if self.health_check_counter % 72 == 0:  # كل 6 ساعات (12 فحص × 6 = 72)
                status_message = f"""
🏥 فحص صحي:
• اتصال Binance: ✅
• اتصال Telegram: ✅  
• الرصيد: {float(usdt_balance['balance']):.2f} USDT
• الصفقات النشطة: {'1' if self.open_position else '0'}
• الخسائر المتتالية: {self.consecutive_losses}
• الوقت: {datetime.now(self.damascus_tz).strftime('%H:%M:%S')}
                """
                await self.send_telegram_message(status_message)
                logging.info("Health check passed")
            
            return True
            
        except Exception as e:
            error_msg = f"❌ فحص صحي فاشل: {e}"
            await self.send_telegram_message(error_msg)
            logging.error(f"Health check failed: {e}")
            return False
    
    async def send_telegram_message(self, message):
        """إرسال رسالة عبر Telegram"""
        try:
            await self.telegram_bot.send_message(
                chat_id=self.telegram_chat_id,
                text=message,
                parse_mode='HTML'
            )
        except TelegramError as e:
            logging.error(f"Telegram error: {e}")
    
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
                balance_info = self.client.futures_account_balance()
                usdt_balance = next((item for item in balance_info if item['asset'] == 'USDT'), None)
                current_balance = float(usdt_balance['balance'])
            except:
                current_balance = 0
            
            # إرسال التقرير اليومي
            report = f"""
📊 التقرير اليومي:

• عدد الصفقات: {self.daily_trades}
• إجمالي الربح: {self.daily_profit:.2f} دولار
• الخسائر المتتالية: {self.consecutive_losses}
• الرصيد الحالي: {current_balance:.2f} USDT
• الوقف المتحرك: {'🟢 مفعل' if self.trailing_stop else '🔴 غير مفعل'}
• حالة البوت: {'🟢 نشط' if self.is_running else '🔴 متوقف'}

التاريخ: {datetime.now(self.damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}
            """
            
            await self.send_telegram_message(report)
            
            # إعادة تعيين الإحصائيات اليومية
            self.daily_trades = 0
            self.daily_profit = 0
            
            logging.info("Daily report sent and statistics reset")
    
    async def run_bot(self):
        """الدالة الرئيسية لتشغيل البوت"""
        if not await self.initialize():
            return
        
        logging.info("Starting trading bot...")
        
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
                df = self.get_ohlc_data()
                signals = self.analyze_signals(df)
                
                if signals:
                    logging.info(f"Signals - EMA Fast: {signals['ema_fast']:.4f}, EMA Slow: {signals['ema_slow']:.4f}, RSI: {signals['rsi']:.2f}")
                    
                    if signals['long_signal'] and not self.open_position:
                        await self.execute_trade('LONG', signals['price'])
                        # بدء مراقبة الصفقة الجديدة
                        tasks.append(asyncio.create_task(self.monitor_position()))
                    
                    elif signals['short_signal'] and not self.open_position:
                        await self.execute_trade('SHORT', signals['price'])
                        # بدء مراقبة الصفقة الجديدة
                        tasks.append(asyncio.create_task(self.monitor_position()))
                
                # انتظر دقيقة قبل التحليل التالي
                await asyncio.sleep(60)
                
        except KeyboardInterrupt:
            logging.info("Bot stopped by user")
            await self.send_telegram_message("🛑 البوت توقف بواسطة المستخدم")
        except Exception as e:
            logging.error(f"Bot error: {e}")
            await self.send_telegram_message(f"🆘 البوت توقف بسبب خطأ: {e}")
        finally:
            self.is_running = False
            # إلغاء جميع المهام
            for task in tasks:
                task.cancel()
            
            await self.send_telegram_message("🛑 البوت توقف عن العمل")

async def main():
    """الدالة الرئيسية"""
    bot = BNBScalpingBot()
    await bot.run_bot()

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
    
    # تشغيل البوت
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"❌ خطأ في التشغيل: {e}")
