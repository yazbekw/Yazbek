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

# ========== الإعدادات الجديدة المعدلة ==========
TRADING_SETTINGS = {
    'symbols': ["BNBUSDT", "ETHUSDT"],           # ⬅️ العملات المدعومة فقط BNB و ETH
    'used_balance_per_trade': 10,                # ⬅️ حجم الصفقة: 10$
    'max_leverage': 5,                           # ⬅️ الرافعة: 5x
    'nominal_trade_size': 50,                    # ⬅️ الرصيد الاسمي: 50$ (10$ × 5)
    'max_active_trades': 1,
    'data_interval': '5m',                       # ⬅️ إطار زمني مناسب للاستراتيجية
    'rescan_interval_minutes': 3,                # ⬅️ مسح كل 3 دقائق
    'min_signal_confidence': 0.90,
    'target_profit_pct': 0.13,                    # ⬅️ هدف 3%
    'stop_loss_pct': 0.07,                        # ⬅️ وقف 1%
    'max_trade_duration_minutes': 20,            # ⬅️ مدة الصفقة 15 دقيقة
    'max_daily_trades': 30,
    'cooldown_after_loss': 5,
}

# ضبط التوقيت
damascus_tz = pytz.timezone('Asia/Damascus')
os.environ['TZ'] = 'Asia/Damascus'
if hasattr(time, 'tzset'):
    time.tzset()

# تطبيق Flask للرصد
app = Flask(__name__)

@app.route('/')
def health_check():
    return {'status': 'healthy', 'service': 'scalping-trading-bot', 'timestamp': datetime.now(damascus_tz).isoformat()}

@app.route('/active_trades')
def active_trades():
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            return jsonify(bot.get_active_trades_details())
        return jsonify([])
    except Exception as e:
        return {'error': str(e)}

@app.route('/market_analysis/<symbol>')
def market_analysis(symbol):
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            analysis = bot.get_market_analysis(symbol)
            return jsonify(analysis)
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
        logging.FileHandler('scalping_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ScalpingSignalGenerator:
    """مولد إشارات السكالبينج المدمجة - معدل للاستراتيجية الجديدة"""
    
    def __init__(self):
        self.min_confidence = TRADING_SETTINGS['min_signal_confidence']
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارة سكالبينج مدمجة - استراتيجية تقاطع المتوسطات + RSI فقط"""
        try:
            if len(data) < 50:
                return None
            
            # حساب المؤشرات (المتوسطات + RSI فقط)
            indicators = self._calculate_indicators(data, current_price)
            
            # تحليل الإشارات
            long_signal = self._analyze_long_signal(indicators)
            short_signal = self._analyze_short_signal(indicators)
            
            # اختيار أفضل إشارة
            return self._select_best_signal(symbol, long_signal, short_signal, indicators)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد إشارة السكالبينج لـ {symbol}: {e}")
            return None
    
    def _calculate_indicators(self, data, current_price):
        """حساب مؤشرات تقاطع المتوسطات + RSI فقط"""
        df = data.copy()
        
        # 1. المتوسطات المتحركة الأسية (EMA) - الاستراتيجية الأساسية
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        
        # 2. RSI فقط - للتأكيد
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        latest = df.iloc[-1]
        
        return {
            'ema5': latest['ema5'],
            'ema10': latest['ema10'],
            'ema20': latest['ema20'],
            'rsi': latest['rsi'],
            'current_price': current_price,
            'timestamp': datetime.now(damascus_tz)
        }
    
    def _calculate_rsi(self, prices, period):
        """حساب RSI بدون TA-LIB"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1]
    
    def _analyze_long_signal(self, indicators):
        conditions = []
        weights = []  # ⬅️ أوزان الشروط
    
       # 1. تقاطع المتوسطات (الاتجاه الصاعد) - وزن عالي
        conditions.append(indicators['ema5'] > indicators['ema10'])
        weights.append(0.3)  # ⬅️ وزن 30%
    
        conditions.append(indicators['ema10'] > indicators['ema20'])
        weights.append(0.4)  # ⬅️ وزن 40% (الأهم)
    
        # 2. تأكيد RSI - وزن منخفض
        conditions.append(indicators['rsi'] < 65)
        weights.append(0.15)  # ⬅️ وزن 15%
    
        conditions.append(indicators['rsi'] > 30)
        weights.append(0.15)  # ⬅️ وزن 15%
    
        # حساب الثقة المرجحة
        weighted_confidence = 0
        for condition, weight in zip(conditions, weights):
            if condition:
                weighted_confidence += weight
    
        return {
            'direction': 'LONG',
            'confidence': weighted_confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'weighted_confidence': weighted_confidence  # ⬅️ الثقة المرجحة
        }

    def _analyze_short_signal(self, indicators):
        conditions = []
        weights = []  # ⬅️ أوزان الشروط
    
        # 1. تقاطع المتوسطات (الاتجاه الهابط) - وزن عالي
        conditions.append(indicators['ema5'] < indicators['ema10'])
        weights.append(0.3)  # ⬅️ وزن 30%
    
        conditions.append(indicators['ema10'] < indicators['ema20'])
        weights.append(0.4)  # ⬅️ وزن 40% (الأهم)
    
        # 2. تأكيد RSI - وزن منخفض
        conditions.append(indicators['rsi'] > 35)
        weights.append(0.15)  # ⬅️ وزن 15%
    
        conditions.append(indicators['rsi'] < 70)
        weights.append(0.15)  # ⬅️ وزن 15%
    
        # حساب الثقة المرجحة
        weighted_confidence = 0
        for condition, weight in zip(conditions, weights):
            if condition:
                weighted_confidence += weight
    
        return {
            'direction': 'SHORT',
            'confidence': weighted_confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'weighted_confidence': weighted_confidence  # ⬅️ الثقة المرجحة
        }
    
    def _select_best_signal(self, symbol, long_signal, short_signal, indicators):
        """اختيار أفضل إشارة"""
        signals = []
        
        if long_signal['confidence'] >= self.min_confidence:
            signals.append(long_signal)
        
        if short_signal['confidence'] >= self.min_confidence:
            signals.append(short_signal)
        
        if not signals:
            return None
        
        # اختيار الإشارة ذات الثقة الأعلى
        best_signal = max(signals, key=lambda x: x['confidence'])
        
        signal_info = {
            'symbol': symbol,
            'direction': best_signal['direction'],
            'confidence': best_signal['confidence'],
            'conditions_met': best_signal['conditions_met'],
            'total_conditions': best_signal['total_conditions'],
            'indicators': indicators,
            'timestamp': datetime.now(damascus_tz)
        }
        
        logger.info(f"🎯 إشارة سكالبينج {symbol}: {best_signal['direction']} "
                   f"(ثقة: {best_signal['confidence']:.2%}, "
                   f"شروط: {best_signal['conditions_met']}/{best_signal['total_conditions']})")
        
        return signal_info

class TradeManager:
    """مدير الصفقات - محفوظ كما هو"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.trade_history = []
    
    def sync_with_exchange(self):
        """مزامنة الصفقات مع المنصة"""
        try:
            account_info = self.client.futures_account()
            positions = account_info['positions']
            
            active_symbols = set()
            
            for position in positions:
                symbol = position['symbol']
                quantity = float(position['positionAmt'])
                
                if quantity != 0:
                    active_symbols.add(symbol)
                    
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
            
            closed_symbols = set(self.active_trades.keys()) - active_symbols
            for symbol in closed_symbols:
                if symbol in self.active_trades:
                    closed_trade = self.active_trades[symbol]
                    closed_trade['status'] = 'closed'
                    closed_trade['close_time'] = datetime.now(damascus_tz)
                    self.trade_history.append(closed_trade)
                    del self.active_trades[symbol]
            
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في مزامنة الصفقات: {e}")
            return False
    
    def get_active_trades_count(self):
        return len(self.active_trades)
    
    def is_symbol_trading(self, symbol):
        return symbol in self.active_trades
    
    def add_trade(self, symbol, trade_data):
        self.active_trades[symbol] = trade_data
    
    def remove_trade(self, symbol):
        if symbol in self.active_trades:
            del self.active_trades[symbol]
    
    def get_trade(self, symbol):
        return self.active_trades.get(symbol)
    
    def get_all_trades(self):
        return self.active_trades.copy()

class TelegramNotifier:
    """مدير إشعارات التلغرام - محفوظ كما هو"""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.recent_messages = {}
    
    def send_message(self, message, message_type='info'):
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
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
            return response.status_code == 200
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False
    
    def send_trade_alert(self, symbol, signal, current_price):
        """إرسال إشعار صفقة سكالبينج"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        message = (
            f"{direction_emoji} <b>إشارة سكالبينج جديدة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"السعر: ${current_price:.4f}\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
            f"الاستراتيجية: تقاطع المتوسطات + RSI\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message, 'trade_signal')

class ScalpingTradingBot:
    _instance = None
    
    # استخدام الإعدادات الجديدة من الأعلى
    TRADING_SETTINGS = TRADING_SETTINGS
    
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

        # تهيئة مكونات السكالبينج
        self.signal_generator = ScalpingSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        
        # إحصائيات الأداء
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'daily_trades_count': 0,
            'last_trade_time': None,
            'consecutive_losses': 0
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت السكالبينج بنجاح مع الإعدادات الجديدة")

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
        """جلب الرصيد الحقيقي من منصة Binance"""
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
            logger.error(f"❌ فشل جلب الرصيد الحقيقي: {e}")
            return {
                'total_balance': 100.0,
                'available_balance': 100.0,
                'timestamp': datetime.now(damascus_tz)
            }

    def start_services(self):
        """بدء الخدمات المساعدة"""
        def sync_thread():
            while True:
                try:
                    self.trade_manager.sync_with_exchange()
                    self.update_real_time_balance()
                    self.manage_active_trades()
                    time.sleep(30)  # ⬅️ مزامنة كل 30 ثانية
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(60)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        if self.notifier:
            schedule.every(6).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)
            schedule.every(1).hours.do(self.send_heartbeat)

    def update_real_time_balance(self):
        """تحديث الرصيد الحقيقي"""
        try:
            self.real_time_balance = self.get_real_time_balance()
            return True
        except Exception as e:
            logger.error(f"❌ فشل تحديث الرصيد: {e}")
            return False

    def manage_active_trades(self):
        """إدارة الصفقات النشطة للسكالبينج مع التحقق من المدة الزمنية"""
        try:
            active_trades = self.trade_manager.get_all_trades()
            current_time = datetime.now(damascus_tz)
            
            for symbol, trade in active_trades.items():
                # التحقق من مدة الصفقة
                trade_duration = (current_time - trade['timestamp']).total_seconds() / 60
                if trade_duration >= self.TRADING_SETTINGS['max_trade_duration_minutes']:
                    self.close_trade(symbol, f"انتهت المدة الزمنية ({trade_duration:.1f} دقيقة)")
                    continue
                
                self.check_trade_exit(symbol, trade)
        except Exception as e:
            logger.error(f"❌ خطأ في إدارة الصفقات: {e}")

    def check_trade_exit(self, symbol, trade):
        """التحقق من خروج الصفقة للسكالبينج"""
        try:
            current_price = self.get_current_price(symbol)
            if not current_price:
                return
            
            entry_price = trade['entry_price']
            
            if trade['side'] == 'LONG':
                pnl_pct = (current_price - entry_price) / entry_price * 100
                # تحقيق الربح المستهدف
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(symbol, f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                # وقف الخسارة
                if pnl_pct <= -self.TRADING_SETTINGS['stop_loss_pct']:
                    self.close_trade(symbol, f"وقف الخسارة {pnl_pct:.2f}%")
                    return
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                # تحقيق الربح المستهدف
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(symbol, f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                # وقف الخسارة
                if pnl_pct <= -self.TRADING_SETTINGS['stop_loss_pct']:
                    self.close_trade(symbol, f"وقف الخسارة {pnl_pct:.2f}%")
                    return
                    
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من خروج الصفقة {symbol}: {e}")

    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            balance = self.real_time_balance
            message = (
                "⚡ <b>بدء تشغيل بوت السكالبينج المعدل</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI فقط\n"
                f"العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"الحجم الاسمي: ${self.TRADING_SETTINGS['nominal_trade_size']}\n"
                f"الربح المستهدف: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"مدة الصفقة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                f"المسح كل: {self.TRADING_SETTINGS['rescan_interval_minutes']} دقائق\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
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
        
        message = (
            f"📊 <b>تقرير أداء السكالبينج المعدل</b>\n"
            f"الاستراتيجية: تقاطع المتوسطات + RSI\n"
            f"الصفقات النشطة: {active_trades}\n"
            f"الصفقات المفتوحة: {self.performance_stats['trades_opened']}\n"
            f"الصفقات المغلقة: {self.performance_stats['trades_closed']}\n"
            f"معدل الفوز: {win_rate:.1f}%\n"
            f"الصفقات اليوم: {self.performance_stats['daily_trades_count']}\n"
            f"الخسائر المتتالية: {self.performance_stats['consecutive_losses']}\n"
            f"الرصيد الحالي: ${self.real_time_balance['total_balance']:.2f}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)

    def send_balance_report(self):
        """إرسال تقرير بالرصيد الحقيقي"""
        if not self.notifier:
            return
        
        try:
            self.update_real_time_balance()
            balance = self.real_time_balance
            active_trades = self.trade_manager.get_active_trades_count()
            
            message = (
                f"💰 <b>تقرير الرصيد الحقيقي</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الرصيد المتاح: ${balance['available_balance']:.2f}\n"
                f"الصفقات النشطة: {active_trades}\n"
                f"آخر تحديث: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            
            self.notifier.send_message(message, 'balance_report')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تقرير الرصيد: {e}")

    def send_heartbeat(self):
        """إرسال نبضة"""
        if self.notifier:
            active_trades = self.trade_manager.get_active_trades_count()
            message = f"💓 بوت السكالبينج المعدل نشط - الصفقات النشطة: {active_trades}"
            self.notifier.send_message(message)

    def get_historical_data(self, symbol, interval, limit=100):
        """جلب البيانات التاريخية"""
        time.sleep(0.1)
        try:
            klines = self.client.futures_klines(
                symbol=symbol,
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
            logger.error(f"❌ خطأ في جلب البيانات لـ {symbol}: {e}")
            return None

    def get_current_price(self, symbol):
        """الحصول على السعر الحالي"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر {symbol}: {e}")
            return None

    def can_open_trade(self, symbol, direction):
        """التحقق من إمكانية فتح صفقة سكالبينج"""
        reasons = []
        
        # التحقق من الحد الأقصى للصفقات النشطة
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات")
        
        # التحقق من وجود صفقة نشطة على الرمز
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append("صفقة نشطة على الرمز")
        
        # التحقق من الرصيد المتاح
        available_balance = self.real_time_balance['available_balance']
        if available_balance < self.TRADING_SETTINGS['used_balance_per_trade']:
            reasons.append("رصيد غير كافي")
        
        # التحقق من الحد اليومي للصفقات
        if self.performance_stats['daily_trades_count'] >= self.TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
        
        # فترة التبريد بعد الخسائر المتتالية
        if self.performance_stats['consecutive_losses'] >= 3:
            last_trade_time = self.performance_stats.get('last_trade_time')
            if last_trade_time and (datetime.now(damascus_tz) - last_trade_time).total_seconds() < self.TRADING_SETTINGS['cooldown_after_loss'] * 60:
                reasons.append("فترة تبريد بعد خسائر متتالية")
        
        return len(reasons) == 0, reasons

    def calculate_position_size(self, symbol, current_price):
        """حساب حجم المركز بناءً على الرصيد المستخدم والرافعة"""
        try:
            # الرصيد الاسمي = الرصيد المستخدم × الرافعة
            nominal_size = self.TRADING_SETTINGS['used_balance_per_trade'] * self.TRADING_SETTINGS['max_leverage']
            
            # الكمية = الرصيد الاسمي ÷ السعر الحالي
            quantity = nominal_size / current_price
            
            # ضبط الكمية حسب متطلبات المنصة
            quantity = self.adjust_quantity(symbol, quantity)
            
            if quantity and quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol}: {quantity:.6f} (رصيد مستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}, رافعة: {self.TRADING_SETTINGS['max_leverage']}x)")
                return quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return None

    def adjust_quantity(self, symbol, quantity):
        """ضبط الكمية حسب متطلبات المنصة"""
        try:
            exchange_info = self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            
            if not symbol_info:
                return None
            
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if not lot_size_filter:
                return None
            
            step_size = float(lot_size_filter['stepSize'])
            min_qty = float(lot_size_filter.get('minQty', 0))
            
            quantity = float(int(quantity / step_size) * step_size)
            
            if quantity < min_qty:
                quantity = min_qty
            
            return round(quantity, 8)
            
        except Exception as e:
            logger.error(f"❌ خطأ في ضبط الكمية: {e}")
            return None

    def set_leverage(self, symbol, leverage):
        """تعيين الرافعة المالية"""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة: {e}")
            return False

    def execute_trade(self, signal):
        """تنفيذ صفقة السكالبينج"""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            
            # التحقق من إمكانية التداول
            can_trade, reasons = self.can_open_trade(symbol, direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي {symbol} {direction}: {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                logger.error(f"❌ لا يمكن الحصول على سعر {symbol}")
                return False
            
            # حساب حجم المركز
            quantity = self.calculate_position_size(symbol, current_price)
            if not quantity:
                logger.warning(f"⚠️ لا يمكن حساب حجم آمن لـ {symbol}")
                return False
            
            # تعيين الرافعة
            leverage = self.TRADING_SETTINGS['max_leverage']
            self.set_leverage(symbol, leverage)
            
            # تنفيذ الأمر الرئيسي
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"⚡ تنفيذ صفقة سكالبينج {symbol}: {direction} | الكمية: {quantity:.6f} | السعر: ${current_price:.4f}")
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order['orderId']:
                # الحصول على سعر التنفيذ الفعلي
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                    if order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                except:
                    pass
                
                # حساب الربح المتوقع
                nominal_value = quantity * executed_price
                expected_profit = nominal_value * (self.TRADING_SETTINGS['target_profit_pct'] / 100)
                
                # تسجيل الصفقة
                trade_data = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': leverage,
                    'timestamp': datetime.now(damascus_tz),
                    'status': 'open',
                    'signal_confidence': signal['confidence'],
                    'nominal_value': nominal_value,
                    'expected_profit': expected_profit,
                    'max_duration': self.TRADING_SETTINGS['max_trade_duration_minutes']
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                
                # إرسال إشعار
                if self.notifier:
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة سكالبينج</b>\n"
                        f"الاستراتيجية: تقاطع المتوسطات + RSI\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"القيمة الاسمية: ${nominal_value:.2f}\n"
                        f"الرافعة: {leverage}x\n"
                        f"🎯 الهدف: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                        f"🛡️ الوقف: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                        f"⏰ المدة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                        f"💰 الربح المتوقع: ${expected_profit:.4f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة سكالبينج {direction} لـ {symbol}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            return False

    def close_trade(self, symbol, reason="إغلاق طبيعي"):
        """إغلاق الصفقة"""
        try:
            trade = self.trade_manager.get_trade(symbol)
            if not trade:
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False
            
            close_side = 'SELL' if trade['side'] == 'LONG' else 'BUY'
            quantity = trade['quantity']
            
            order = self.client.futures_create_order(
                symbol=symbol,
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
                
                self.performance_stats['total_pnl'] += pnl_pct
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة سكالبينج</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"السبب: {reason}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                self.trade_manager.remove_trade(symbol)
                logger.info(f"✅ تم إغلاق صفقة {symbol} - الربح/الخسارة: {pnl_pct:+.2f}%")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {symbol}: {e}")
            return False

    def scan_market(self):
        """مسح السوق للعثور على فرص السكالبينج"""
        logger.info("🔍 بدء مسح السوق للسكالبينج المعدل...")
        
        opportunities = []
        
        for symbol in self.TRADING_SETTINGS['symbols']:
            try:
                # تخطي الرموز ذات الصفقات النشطة
                if self.trade_manager.is_symbol_trading(symbol):
                    continue
                
                data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'])
                if data is None or len(data) < 50:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                signal = self.signal_generator.generate_signal(symbol, data, current_price)
                if signal:
                    opportunities.append(signal)
                    
                    if self.notifier:
                        self.notifier.send_trade_alert(symbol, signal, current_price)
                
            except Exception as e:
                logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
                continue
        
        opportunities.sort(key=lambda x: x['confidence'], reverse=True)
        
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة سكالبينج")
        return opportunities

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول للسكالبينج"""
        try:
            start_time = time.time()
            
            opportunities = self.scan_market()
            
            executed_trades = 0
            for signal in opportunities:
                if executed_trades >= 1:  # ⬅️ صفقة واحدة فقط لكل دورة
                    break
                
                if self.execute_trade(signal):
                    executed_trades += 1
                    time.sleep(1)  # ⬅️ انتظار بسيط بين الصفقات
            
            # حساب الوقت المتبقي بدقة
            elapsed_time = time.time() - start_time
            wait_time = (self.TRADING_SETTINGS['rescan_interval_minutes'] * 60) - elapsed_time
            
            if wait_time > 0:
                logger.info(f"⏳ انتظار {wait_time:.1f} ثانية للدورة القادمة...")
                time.sleep(wait_time)
            else:
                logger.info("⚡ الدورة استغرقت وقتاً أطول من المخطط، بدء الدورة التالية فوراً")
            
            logger.info(f"✅ اكتملت دورة السكالبينج - تم تنفيذ {executed_trades} صفقة")
            
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
                'max_duration': trade.get('max_duration', 15)
            }
            for trade in trades.values()
        ]

    def get_market_analysis(self, symbol):
        """الحصول على تحليل السوق لرمز معين"""
        try:
            data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'])
            if data is None:
                return {'error': 'لا توجد بيانات'}
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return {'error': 'لا يمكن الحصول على السعر'}
            
            signal = self.signal_generator.generate_signal(symbol, data, current_price)
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'signal': signal,
                'timestamp': datetime.now(damascus_tz).isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت السكالبينج المعدل...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت السكالبينج المعدل</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI فقط\n"
                f"العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"الهدف: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"الوقف: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"مدة الصفقة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
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
            logger.info("🛑 إيقاف بوت السكالبينج...")

def main():
    """الدالة الرئيسية"""
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
