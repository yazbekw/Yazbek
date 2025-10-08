import os
import pandas as pd
import numpy as np
import hashlib
from binance.client import Client
from binance.enums import *
import time
from datetime import datetime, timedelta
import requests
import logging
import warnings
import threading
import schedule
from flask import Flask, jsonify
import pytz
from scipy.signal import find_peaks
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
load_dotenv()

# ضبط التوقيت
damascus_tz = pytz.timezone('Asia/Damascus')
os.environ['TZ'] = 'Asia/Damascus'
if hasattr(time, 'tzset'):
    time.tzset()

# تطبيق Flask للرصد
app = Flask(__name__)

@app.route('/')
def health_check():
    return {'status': 'healthy', 'service': 'bnb-scalping-bot', 'timestamp': datetime.now(damascus_tz).isoformat()}

@app.route('/active_trades')
def active_trades():
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            return jsonify(bot.get_active_trades_details())
        return jsonify([])
    except Exception as e:
        return {'error': str(e)}

@app.route('/market_analysis')
def market_analysis():
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            analysis = bot.get_market_analysis()
            return jsonify(analysis)
        return {'error': 'Bot not initialized'}
    except Exception as e:
        return {'error': str(e)}

@app.route('/performance')
def performance():
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            return jsonify(bot.get_performance_stats())
        return {'error': 'Bot not initialized'}
    except Exception as e:
        return {'error': str(e)}

def run_flask_app():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bnb_scalping_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class SupportResistanceSignalGenerator:
    """مولد إشارات التداول المبسط"""
    
    def __init__(self):
        self.min_confidence = 0.70
    
    def generate_signal(self, data_1h, data_15m, current_price):
        """توليد إشارة تداول مبسطة"""
        try:
            if len(data_1h) < 20 or len(data_15m) < 10:
                return None
            
            # حساب RSI
            rsi = self._calculate_rsi(data_15m['close'], 14).iloc[-1]
            
            # تحديد مستويات الدعم والمقاومة
            support_levels = self._find_support_levels(data_1h)
            resistance_levels = self._find_resistance_levels(data_1h)
            
            # تحليل الشموع
            candlestick_signal = self._analyze_candlestick(data_15m)
            
            # تحليل الإشارات
            long_signal = self._analyze_long(current_price, support_levels, rsi, candlestick_signal)
            short_signal = self._analyze_short(current_price, resistance_levels, rsi, candlestick_signal)
            
            # اختيار أفضل إشارة
            return self._select_best_signal(long_signal, short_signal, rsi)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد الإشارة: {e}")
            return None
    
    def _calculate_rsi(self, prices, period):
        """حساب RSI مبسط"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - (100 / (1 + rs))
    
    def _find_support_levels(self, data):
        """إيجاد مستويات الدعم"""
        lows = data['low'].values
        min_distance = len(lows) // 8
        
        valleys, _ = find_peaks(-lows, distance=min_distance, prominence=np.std(lows)*0.2)
        return [lows[i] for i in valleys[-3:]]  # آخر 3 مستويات دعم
    
    def _find_resistance_levels(self, data):
        """إيجاد مستويات المقاومة"""
        highs = data['high'].values
        min_distance = len(highs) // 8
        
        peaks, _ = find_peaks(highs, distance=min_distance, prominence=np.std(highs)*0.2)
        return [highs[i] for i in peaks[-3:]]  # آخر 3 مستويات مقاومة
    
    def _analyze_candlestick(self, data):
        """تحليل الشموع المبسط"""
        if len(data) < 2:
            return 'neutral'
        
        current = data.iloc[-1]
        prev = data.iloc[-2]
        
        # engulfing صاعد
        if (prev['close'] < prev['open'] and 
            current['close'] > current['open'] and
            current['close'] > prev['open'] and
            current['open'] < prev['close']):
            return 'bullish'
        
        # engulfing هابط
        if (prev['close'] > prev['open'] and 
            current['close'] < current['open'] and
            current['close'] < prev['open'] and
            current['open'] > prev['close']):
            return 'bearish'
        
        return 'neutral'
    
    def _analyze_long(self, price, support_levels, rsi, candlestick):
        """تحليل إشارة الشراء المبسطة"""
        conditions = []
        
        # القرب من دعم
        nearest_support = min(support_levels, key=lambda x: abs(x - price)) if support_levels else None
        if nearest_support and abs(price - nearest_support) / price <= 0.002:  # ضمن 0.2%
            conditions.append(True)
        
        # RSI في التشبع البيعي
        if rsi < 35:
            conditions.append(True)
        
        # إشارة شمعة صاعدة
        if candlestick == 'bullish':
            conditions.append(True)
        
        confidence = sum(conditions) / 3 if conditions else 0
        
        return {
            'direction': 'LONG',
            'confidence': confidence,
            'conditions_met': sum(conditions)
        }
    
    def _analyze_short(self, price, resistance_levels, rsi, candlestick):
        """تحليل إشارة البيع المبسطة"""
        conditions = []
        
        # القرب من مقاومة
        nearest_resistance = min(resistance_levels, key=lambda x: abs(x - price)) if resistance_levels else None
        if nearest_resistance and abs(price - nearest_resistance) / price <= 0.002:  # ضمن 0.2%
            conditions.append(True)
        
        # RSI في التشبع الشرائي
        if rsi > 65:
            conditions.append(True)
        
        # إشارة شمعة هابطة
        if candlestick == 'bearish':
            conditions.append(True)
        
        confidence = sum(conditions) / 3 if conditions else 0
        
        return {
            'direction': 'SHORT',
            'confidence': confidence,
            'conditions_met': sum(conditions)
        }
    
    def _select_best_signal(self, long_signal, short_signal, rsi):
        """اختيار أفضل إشارة"""
        signals = []
        
        if long_signal['confidence'] >= self.min_confidence:
            signals.append(long_signal)
        
        if short_signal['confidence'] >= self.min_confidence:
            signals.append(short_signal)
        
        if not signals:
            return None
        
        best_signal = max(signals, key=lambda x: x['confidence'])
        
        return {
            'symbol': 'ETHUSDT',
            'direction': best_signal['direction'],
            'confidence': best_signal['confidence'],
            'conditions_met': best_signal['conditions_met'],
            'timestamp': datetime.now(damascus_tz),
            'strategy': 'SUPPORT_RESISTANCE'
        }

class TradeManager:
    """مدير الصفقات المبسط"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.symbol_cooldown = {}
    
    def sync_with_exchange(self):
        """مزامنة الصفقات مع المنصة"""
        try:
            account_info = self.client.futures_account()
            positions = account_info['positions']
            
            for position in positions:
                symbol = position['symbol']
                quantity = float(position['positionAmt'])
                
                if quantity != 0 and symbol == 'ETHUSDT':
                    if symbol not in self.active_trades:
                        side = "LONG" if quantity > 0 else "SHORT"
                        self.active_trades[symbol] = {
                            'symbol': symbol,
                            'quantity': abs(quantity),
                            'entry_price': float(position['entryPrice']),
                            'side': side,
                            'timestamp': datetime.now(damascus_tz),
                            'status': 'open'
                        }
                elif symbol == 'ETHUSDT' and symbol in self.active_trades:
                    closed_trade = self.active_trades[symbol]
                    closed_trade['status'] = 'closed'
                    del self.active_trades[symbol]
            
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في مزامنة الصفقات: {e}")
            return False
    
    def can_trade_symbol(self, symbol):
        """التحقق من إمكانية التداول على الرمز"""
        if symbol in self.symbol_cooldown:
            cooldown_end = self.symbol_cooldown[symbol]
            if datetime.now(damascus_tz) < cooldown_end:
                remaining = (cooldown_end - datetime.now(damascus_tz)).total_seconds() / 60
                logger.info(f"⏳ تبريد لـ {symbol}: {remaining:.1f} دقائق متبقية")
                return False
        
        return True
    
    def add_symbol_cooldown(self, symbol, minutes=10):
        """إضافة فترة تبريد للرمز"""
        cooldown_end = datetime.now(damascus_tz) + timedelta(minutes=minutes)
        self.symbol_cooldown[symbol] = cooldown_end
        logger.info(f"⏰ تبريد {symbol} لمدة {minutes} دقائق")
    
    def cleanup_cooldowns(self):
        """تنظيف فترات التبريد المنتهية"""
        current_time = datetime.now(damascus_tz)
        expired_symbols = [
            symbol for symbol, end_time in self.symbol_cooldown.items() 
            if current_time >= end_time
        ]
        for symbol in expired_symbols:
            del self.symbol_cooldown[symbol]
    
    def get_active_trades_count(self):
        return len(self.active_trades)
    
    def is_symbol_trading(self, symbol):
        return symbol in self.active_trades
    
    def add_trade(self, trade_data):
        self.active_trades['BNBUSDT'] = trade_data
    
    def remove_trade(self):
        if 'BNBUSDT' in self.active_trades:
            del self.active_trades['BNBUSDT']
    
    def get_trade(self):
        return self.active_trades.get('BNBUSDT')
    
    def get_all_trades(self):
        return self.active_trades.copy()

class TelegramNotifier:
    """مدير إشعارات التلغرام المبسط"""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, message):
        try:
            if not self.token or not self.chat_id:
                return False
                
            if len(message) > 4096:
                message = message[:4090] + "..."
            
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False

class ScalpingTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbol': "ETHUSDT",  # ETH فقط
        'used_balance_per_trade': 5,
        'max_leverage': 8,
        'nominal_trade_size': 40,
        'max_active_trades': 1,  # صفقة واحدة فقط
        'data_interval_1h': '1h',
        'data_interval_15m': '15m',
        'rescan_interval_minutes': 5,
        'min_signal_confidence': 0.70,
        'target_profit_pct': 0.30,
        'stop_loss_pct': 0.20,
        'max_daily_trades': 15,
        'cooldown_after_loss': 10,
    }
    
    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self):
        if ScalpingTradingBot._instance is not None:
            raise Exception("هذه الفئة تستخدم نمط Singleton")
        
        # تهيئة API
        self.api_key = os.environ.get('BINANCE_API_KEY')
        self.api_secret = os.environ.get('BINANCE_API_SECRET')
        self.telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        
        if not all([self.api_key, self.api_secret]):
            raise ValueError("مفاتيح Binance مطلوبة")
        
        try:
            self.client = Client(self.api_key, self.api_secret)
            self.real_time_balance = self.get_real_time_balance()
            self.test_connection()
        except Exception as e:
            logger.error(f"❌ فشل تهيئة العميل: {e}")
            raise

        # تهيئة المكونات المبسطة
        self.signal_generator = SupportResistanceSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        
        # إحصائيات الأداء المبسطة
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'daily_trades_count': 0,
            'last_trade_time': None,
            'consecutive_losses': 0,
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت ETH السكالبينج باستراتيجية الدعم والمقاومة بنجاح")

    def test_connection(self):
        """اختبار اتصال API"""
        try:
            self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise

    def get_real_time_balance(self):
        """جلب الرصيد الحقيقي"""
        try:
            account_info = self.client.futures_account()
            total_balance = float(account_info['totalWalletBalance'])
            available_balance = float(account_info['availableBalance'])
            
            balance_info = {
                'total_balance': total_balance,
                'available_balance': available_balance,
                'timestamp': datetime.now(damascus_tz)
            }
            
            logger.info(f"💰 الرصيد الحقيقي: ${total_balance:.2f} | المتاح: ${available_balance:.2f}")
            return balance_info
            
        except Exception as e:
            logger.error(f"❌ فشل جلب الرصيد: {e}")
            return {
                'total_balance': 100.0,
                'available_balance': 100.0,
                'timestamp': datetime.now(damascus_tz)
            }

    def can_open_trade(self, direction):
        """التحقق من إمكانية فتح صفقة"""
        reasons = []
        
        # التحقق من وجود صفقة نشطة
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("يوجد صفقة نشطة بالفعل")
        
        # التحقق من الرصيد المتاح
        available_balance = self.real_time_balance['available_balance']
        if available_balance < self.TRADING_SETTINGS['used_balance_per_trade']:
            reasons.append("رصيد غير كافي")
        
        # التحقق من الحد اليومي
        if self.performance_stats['daily_trades_count'] >= self.TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
        
        # التحقق من نظام التبريد
        if not self.trade_manager.can_trade_symbol('BNBUSDT'):
            reasons.append("فترة تبريد نشطة")
        
        # التحقق من الخسائر المتتالية
        if self.performance_stats['consecutive_losses'] >= 2:
            last_trade_time = self.performance_stats.get('last_trade_time')
            if last_trade_time and (datetime.now(damascus_tz) - last_trade_time).total_seconds() < self.TRADING_SETTINGS['cooldown_after_loss'] * 60:
                reasons.append("فترة تبريد بعد خسائر متتالية")
        
        return len(reasons) == 0, reasons

    def start_services(self):
        """بدء الخدمات المساعدة"""
        def sync_thread():
            while True:
                try:
                    self.trade_manager.sync_with_exchange()
                    self.update_real_time_balance()
                    self.manage_active_trades()
                    self.trade_manager.cleanup_cooldowns()
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(60)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        if self.notifier:
            schedule.every(6).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)

    def update_real_time_balance(self):
        """تحديث الرصيد الحقيقي"""
        try:
            self.real_time_balance = self.get_real_time_balance()
            return True
        except Exception as e:
            logger.error(f"❌ فشل تحديث الرصيد: {e}")
            return False

    def manage_active_trades(self):
        """إدارة الصفقات النشطة"""
        try:
            active_trades = self.trade_manager.get_all_trades()
            for symbol, trade in active_trades.items():
                self.check_trade_exit(trade)
        except Exception as e:
            logger.error(f"❌ خطأ في إدارة الصفقات: {e}")

    def check_trade_exit(self, trade):
        """التحقق من خروج الصفقة"""
        try:
            current_price = self.get_current_price()
            if not current_price:
                return
            
            entry_price = trade['entry_price']
            
            if trade['side'] == 'LONG':
                pnl_pct = (current_price - entry_price) / entry_price * 100
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                if pnl_pct <= -self.TRADING_SETTINGS['stop_loss_pct']:
                    self.close_trade(f"وقف الخسارة {pnl_pct:.2f}%")
                    return
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                if pnl_pct <= -self.TRADING_SETTINGS['stop_loss_pct']:
                    self.close_trade(f"وقف الخسارة {pnl_pct:.2f}%")
                    return
                    
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من خروج الصفقة: {e}")

    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            balance = self.real_time_balance
            
            message = (
                "⚡ <b>بدء تشغيل بوت ETH السكالبينج</b>\n"
                f"<b>الاستراتيجية:</b> ارتداد السعر من مستويات الدعم والمقاومة\n"
                f"<b>المؤشرات:</b> RSI + أنماط الشموع + مستويات الدعم/المقاومة\n"
                f"<b>الإعدادات:</b>\n"
                f"• وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"• هدف الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"• الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"• القيمة الاسمية: ${self.TRADING_SETTINGS['nominal_trade_size']}\n"
                f"• صفقات نشطة: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الوقت دمشق: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.notifier.send_message(message)

    def send_performance_report(self):
        """إرسال تقرير الأداء"""
        if not self.notifier:
            return
        
        active_trades = self.trade_manager.get_active_trades_count()
        win_rate = 0
        if self.performance_stats['trades_closed'] > 0:
            win_rate = (self.performance_stats['winning_trades'] / self.performance_stats['trades_closed']) * 100
        
        risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
        
        message = (
            f"📊 <b>تقرير أداء بوت ETH</b>\n"
            f"الاستراتيجية: ارتداد من الدعم والمقاومة\n"
            f"الصفقات النشطة: {active_trades}\n"
            f"الصفقات المفتوحة: {self.performance_stats['trades_opened']}\n"
            f"الصفقات المغلقة: {self.performance_stats['trades_closed']}\n"
            f"معدل الفوز: {win_rate:.1f}%\n"
            f"الصفقات اليوم: {self.performance_stats['daily_trades_count']}\n"
            f"الخسائر المتتالية: {self.performance_stats['consecutive_losses']}\n"
            f"نسبة المكافأة/المخاطرة: {risk_reward_ratio:.2f}:1\n"
            f"الرصيد الحالي: ${self.real_time_balance['total_balance']:.2f}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)

    def send_balance_report(self):
        """إرسال تقرير الرصيد"""
        if not self.notifier:
            return
        
        try:
            self.update_real_time_balance()
            balance = self.real_time_balance
            active_trades = self.trade_manager.get_active_trades_count()
            
            message = (
                f"💰 <b>تقرير الرصيد</b>\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الرصيد المتاح: ${balance['available_balance']:.2f}\n"
                f"الصفقات النشطة: {active_trades}\n"
                f"آخر تحديث: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            
            self.notifier.send_message(message)
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تقرير الرصيد: {e}")

    def get_historical_data(self, interval, limit=50):
        """جلب البيانات التاريخية"""
        time.sleep(0.1)
        try:
            klines = self.client.futures_klines(
                symbol=self.TRADING_SETTINGS['symbol'],
                interval=interval,
                limit=limit
            )
            
            if not klines:
                return None
            
            data = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                data[col] = pd.to_numeric(data[col], errors='coerce')
            
            return data.dropna()
            
        except Exception as e:
            logger.error(f"❌ خطأ في جلب البيانات: {e}")
            return None

    def get_current_price(self):
        """الحصول على السعر الحالي"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=self.TRADING_SETTINGS['symbol'])
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر BNB: {e}")
            return None

    def calculate_position_size(self, current_price):
        """حساب حجم المركز"""
        try:
            nominal_size = self.TRADING_SETTINGS['used_balance_per_trade'] * self.TRADING_SETTINGS['max_leverage']
            quantity = nominal_size / current_price
            
            # ضبط الكمية حسب متطلبات المنصة
            exchange_info = self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == self.TRADING_SETTINGS['symbol']), None)
            
            if symbol_info:
                lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                if lot_size_filter:
                    step_size = float(lot_size_filter['stepSize'])
                    quantity = float(int(quantity / step_size) * step_size)
            
            if quantity > 0:
                logger.info(f"💰 حجم الصفقة: {quantity:.6f}")
                return quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز: {e}")
            return None

    def set_leverage(self):
        """تعيين الرافعة المالية"""
        try:
            self.client.futures_change_leverage(
                symbol=self.TRADING_SETTINGS['symbol'], 
                leverage=self.TRADING_SETTINGS['max_leverage']
            )
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة: {e}")
            return False

    def execute_trade(self, signal):
        """تنفيذ صفقة السكالبينج"""
        try:
            direction = signal['direction']
            
            # التحقق من إمكانية التداول
            can_trade, reasons = self.can_open_trade(direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي ETH {direction}: {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price()
            if not current_price:
                logger.error(f"❌ لا يمكن الحصول على سعر BNB")
                return False
            
            # حساب حجم المركز
            quantity = self.calculate_position_size(current_price)
            if not quantity:
                logger.warning(f"⚠️ لا يمكن حساب حجم آمن")
                return False
            
            # تعيين الرافعة
            self.set_leverage()
            
            # تنفيذ الأمر
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"⚡ تنفيذ صفقة ETH: {direction} | الكمية: {quantity:.6f}")
            
            order = self.client.futures_create_order(
                symbol=self.TRADING_SETTINGS['symbol'],
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order['orderId']:
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(
                        symbol=self.TRADING_SETTINGS['symbol'], 
                        orderId=order['orderId']
                    )
                    if order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                except:
                    pass
                
                nominal_value = quantity * executed_price
                expected_profit = nominal_value * (self.TRADING_SETTINGS['target_profit_pct'] / 100)
                
                # تسجيل الصفقة
                trade_data = {
                    'symbol': self.TRADING_SETTINGS['symbol'],
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': self.TRADING_SETTINGS['max_leverage'],
                    'timestamp': datetime.now(damascus_tz),
                    'status': 'open',
                    'signal_confidence': signal['confidence'],
                    'nominal_value': nominal_value,
                    'expected_profit': expected_profit,
                    'strategy': 'SUPPORT_RESISTANCE'
                }
                
                self.trade_manager.add_trade(trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                
                # إرسال إشعار
                if self.notifier:
                    risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
                    
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة BNB</b>\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"القيمة الاسمية: ${nominal_value:.2f}\n"
                        f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                        f"🎯 الهدف: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                        f"🛡️ الوقف: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                        f"⚖️ النسبة: {risk_reward_ratio:.2f}:1\n"
                        f"💰 الربح المتوقع: ${expected_profit:.4f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"الشروط: {signal['conditions_met']}/3\n"
                        f"الاستراتيجية: ارتداد من الدعم/المقاومة\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ ETH")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة BNB: {e}")
            return False

    def close_trade(self, reason="إغلاق طبيعي"):
        """إغلاق الصفقة"""
        try:
            trade = self.trade_manager.get_trade()
            if not trade:
                return False
            
            current_price = self.get_current_price()
            if not current_price:
                return False
            
            close_side = 'SELL' if trade['side'] == 'LONG' else 'BUY'
            quantity = trade['quantity']
            
            order = self.client.futures_create_order(
                symbol=self.TRADING_SETTINGS['symbol'],
                side=close_side,
                type='MARKET',
                quantity=quantity,
                reduceOnly=True
            )
            
            if order and order['orderId']:
                entry_price = trade['entry_price']
                if trade['side'] == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                
                # تحديث الإحصائيات
                self.performance_stats['trades_closed'] += 1
                if pnl_pct > 0:
                    self.performance_stats['winning_trades'] += 1
                    self.performance_stats['consecutive_losses'] = 0
                else:
                    self.performance_stats['losing_trades'] += 1
                    self.performance_stats['consecutive_losses'] += 1
                    
                    # إضافة تبديد بعد خسائر متتالية
                    if self.performance_stats['consecutive_losses'] >= 2:
                        self.trade_manager.add_symbol_cooldown('BNBUSDT', self.TRADING_SETTINGS['cooldown_after_loss'])
                
                self.performance_stats['total_pnl'] += pnl_pct
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة ETH</b>\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"السبب: {reason}\n"
                        f"الاستراتيجية: {trade.get('strategy', 'SUPPORT_RESISTANCE')}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                self.trade_manager.remove_trade()
                logger.info(f"✅ تم إغلاق صفقة ETH - الربح/الخسارة: {pnl_pct:+.2f}%")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة BNB: {e}")
            return False

    def scan_market(self):
        """مسح السوق للعثور على فرص السكالبينج"""
        logger.info("🔍 بدء مسح السوق لـ BNB...")
        
        try:
            data_1h = self.get_historical_data(self.TRADING_SETTINGS['data_interval_1h'])
            data_15m = self.get_historical_data(self.TRADING_SETTINGS['data_interval_15m'])
            
            if data_1h is None or data_15m is None or len(data_1h) < 20 or len(data_15m) < 10:
                return None
            
            current_price = self.get_current_price()
            if not current_price:
                return None
            
            signal = self.signal_generator.generate_signal(data_1h, data_15m, current_price)
            if signal:
                logger.info(f"🎯 تم العثور على إشارة BNB: {signal['direction']} (ثقة: {signal['confidence']:.2%})")
                return signal
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل BNB: {e}")
            return None

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول"""
        try:
            start_time = time.time()
            signal = self.scan_market()
            
            if signal and self.execute_trade(signal):
                logger.info("✅ تم تنفيذ صفقة BNB بنجاح")
            
            elapsed_time = time.time() - start_time
            wait_time = (self.TRADING_SETTINGS['rescan_interval_minutes'] * 60) - elapsed_time
            
            if wait_time > 0:
                logger.info(f"⏳ انتظار {wait_time:.1f} ثانية للدورة القادمة")
                time.sleep(wait_time)
            else:
                logger.info("⚡ بدء الدورة التالية فوراً")
            
        except Exception as e:
            logger.error(f"❌ خطأ في دورة التداول: {e}")
            time.sleep(60)

    def get_active_trades_details(self):
        """الحصول على تفاصيل الصفقات النشطة"""
        trades = self.trade_manager.get_all_trades()
        return [
            {
                'symbol': trade['symbol'],
                'side': trade['side'],
                'quantity': trade['quantity'],
                'entry_price': trade['entry_price'],
                'leverage': trade['leverage'],
                'timestamp': trade['timestamp'].isoformat(),
                'confidence': trade.get('signal_confidence', 0),
                'nominal_value': trade.get('nominal_value', 0),
                'expected_profit': trade.get('expected_profit', 0),
                'strategy': trade.get('strategy', 'SUPPORT_RESISTANCE')
            }
            for trade in trades.values()
        ]

    def get_market_analysis(self):
        """الحصول على تحليل السوق"""
        try:
            data_1h = self.get_historical_data(self.TRADING_SETTINGS['data_interval_1h'])
            data_15m = self.get_historical_data(self.TRADING_SETTINGS['data_interval_15m'])
            
            if data_1h is None or data_15m is None:
                return {'error': 'لا توجد بيانات'}
            
            current_price = self.get_current_price()
            if not current_price:
                return {'error': 'لا يمكن الحصول على السعر'}
            
            signal = self.signal_generator.generate_signal(data_1h, data_15m, current_price)
            
            return {
                'symbol': 'ETHUSDT',
                'current_price': current_price,
                'signal': signal,
                'timestamp': datetime.now(damascus_tz).isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}

    def get_performance_stats(self):
        """الحصول على إحصائيات الأداء"""
        win_rate = 0
        if self.performance_stats['trades_closed'] > 0:
            win_rate = (self.performance_stats['winning_trades'] / self.performance_stats['trades_closed']) * 100
        
        risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
        
        return {
            'performance': {
                'trades_opened': self.performance_stats['trades_opened'],
                'trades_closed': self.performance_stats['trades_closed'],
                'winning_trades': self.performance_stats['winning_trades'],
                'losing_trades': self.performance_stats['losing_trades'],
                'win_rate': round(win_rate, 1),
                'total_pnl': round(self.performance_stats['total_pnl'], 2),
                'daily_trades_count': self.performance_stats['daily_trades_count'],
                'consecutive_losses': self.performance_stats['consecutive_losses']
            },
            'risk_management': {
                'target_profit_pct': self.TRADING_SETTINGS['target_profit_pct'],
                'stop_loss_pct': self.TRADING_SETTINGS['stop_loss_pct'],
                'risk_reward_ratio': round(risk_reward_ratio, 2),
                'used_balance_per_trade': self.TRADING_SETTINGS['used_balance_per_trade'],
                'max_leverage': self.TRADING_SETTINGS['max_leverage'],
                'nominal_trade_size': self.TRADING_SETTINGS['nominal_trade_size']
            },
            'strategy': 'SUPPORT_RESISTANCE',
            'symbol': 'ETHUSDT'
        }

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت ETH السكالبينج...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت ETH السكالبينج</b>\n"
                f"الاستراتيجية: ارتداد السعر من مستويات الدعم والمقاومة\n"
                f"المؤشرات: RSI + أنماط الشموع + مستويات الدعم/المقاومة\n"
                f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"القيمة الاسمية: ${self.TRADING_SETTINGS['nominal_trade_size']}\n"
                f"الصفقات النشطة: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"الوقت دمشق: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
        
        try:
            while True:
                try:
                    schedule.run_pending()
                    self.execute_trading_cycle()
                    
                except KeyboardInterrupt:
                    logger.info("⏹️ إيقاف البوت يدوياً...")
                    break
                except Exception as e:
                    logger.error(f"❌ خطأ في الحلقة الرئيسية: {e}")
                    time.sleep(60)
                    
        except Exception as e:
            logger.error(f"❌ خطأ غير متوقع: {e}")
        finally:
            logger.info("🛑 إيقاف بوت ETH السكالبينج...")

def main():
    """الدالة الرئيسية"""
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
