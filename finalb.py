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
    return {'status': 'healthy', 'service': 'multi-scalping-bot', 'timestamp': datetime.now(damascus_tz).isoformat()}

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
        logging.FileHandler('multi_scalping_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MA_RSI_SignalGenerator:
    """مولد إشارات السكالبينج باستراتيجية المتوسطات المتحركة + RSI"""
    
    def __init__(self):
        self.min_confidence = 0.65  # زيادة الحد الأدنى للثقة
        self.min_conditions = 5     # زيادة عدد الشروط المطلوبة
    
    def generate_signal(self, data, current_price, symbol):
        """توليد إشارة سكالبينج باستراتيجية EMA + RSI"""
        try:
            if len(data) < 50:
                return None
            
            # حساب المؤشرات
            indicators = self._calculate_ma_rsi_indicators(data, current_price)
            
            # تحليل الإشارات
            long_signal = self._analyze_long_signal(indicators)
            short_signal = self._analyze_short_signal(indicators)
            
            # اختيار أفضل إشارة
            return self._select_best_signal(long_signal, short_signal, indicators, symbol)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد الإشارة لـ {symbol}: {e}")
            return None
    
    def _calculate_ma_rsi_indicators(self, data, current_price):
        """حساب مؤشرات EMA + RSI + ATR"""
        df = data.copy()
        
        # 1. المتوسطات المتحركة الأسية
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()  # إضافة EMA200 للاتجاه العام
        
        # 2. RSI مع فترات متعددة
        df['rsi14'] = self._calculate_rsi(df['close'], 14)
        df['rsi9'] = self._calculate_rsi(df['close'], 9)
        
        # 3. زخم الاتجاه
        df['ema9_slope'] = df['ema9'].diff(3) / df['ema9'].shift(3) * 100
        df['ema21_slope'] = df['ema21'].diff(3) / df['ema21'].shift(3) * 100
        
        # 4. مؤشر الحجم
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # 5. حساب ATR
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift()),
                abs(df['low'] - df['close'].shift())
            )
        )
        df['atr'] = df['tr'].rolling(14).mean()
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        return {
            'ema9': latest['ema9'],
            'ema21': latest['ema21'],
            'ema50': latest['ema50'],
            'ema200': latest['ema200'],  # إضافة EMA200
            'rsi14': latest['rsi14'],
            'rsi9': latest['rsi9'],
            'ema9_slope': latest['ema9_slope'],
            'ema21_slope': latest['ema21_slope'],
            'volume_ratio': latest['volume_ratio'],
            'atr': latest['atr'],  # إضافة ATR
            'current_price': current_price,
            'prev_close': prev['close'],
            'price_above_ema9': current_price > latest['ema9'],
            'price_above_ema21': current_price > latest['ema21'],
            'ema9_above_ema21': latest['ema9'] > latest['ema21'],
            'ema21_above_ema50': latest['ema21'] > latest['ema50'],
            'ema21_above_ema200': latest['ema21'] > latest['ema200']  # شرط الاتجاه
        }
    
    def _calculate_rsi(self, prices, period):
        """حساب RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _analyze_long_signal(self, indicators):
        """تحليل إشارة الشراء باستراتيجية EMA + RSI"""
        conditions = []
        
        # 1. تقاطع المتوسطات الصاعد
        conditions.append(indicators['ema9_above_ema21'])
        conditions.append(indicators['ema21_above_ema50'])
        conditions.append(indicators['ema21_above_ema200'])  # إضافة شرط الاتجاه العام
        
        # 2. موقع السعر بالنسبة للمتوسطات
        conditions.append(indicators['price_above_ema9'])
        conditions.append(indicators['price_above_ema21'])
        
        # 3. زخم RSI
        conditions.append(indicators['rsi14'] > 50)  # فوق مستوى 50
        conditions.append(30 < indicators['rsi9'] < 70)  # RSI قصير في نطاق معقول
        
        # 4. زخم المتوسطات
        conditions.append(indicators['ema9_slope'] > 0.05)
        conditions.append(indicators['ema21_slope'] > 0.02)
        
        # 5. تأكيد الحجم
        conditions.append(indicators['volume_ratio'] > 1.2)  # زيادة شرط الحجم
        
        confidence = sum(conditions) / len(conditions)
        
        return {
            'direction': 'LONG',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'strategy': 'EMA_RSI'
        }
    
    def _analyze_short_signal(self, indicators):
        """تحليل إشارة البيع باستراتيجية EMA + RSI"""
        conditions = []
        
        # 1. تقاطع المتوسطات الهابط
        conditions.append(not indicators['ema9_above_ema21'])
        conditions.append(not indicators['ema21_above_ema50'])
        conditions.append(not indicators['ema21_above_ema200'])  # إضافة شرط الاتجاه العام
        
        # 2. موقع السعر بالنسبة للمتوسطات
        conditions.append(not indicators['price_above_ema9'])
        conditions.append(not indicators['price_above_ema21'])
        
        # 3. زخم RSI
        conditions.append(indicators['rsi14'] < 50)  # تحت مستوى 50
        conditions.append(30 < indicators['rsi9'] < 70)  # RSI قصير في نطاق معقول
        
        # 4. زخم المتوسطات
        conditions.append(indicators['ema9_slope'] < -0.05)
        conditions.append(indicators['ema21_slope'] < -0.02)
        
        # 5. تأكيد الحجم
        conditions.append(indicators['volume_ratio'] > 1.2)  # زيادة شرط الحجم
        
        confidence = sum(conditions) / len(conditions)
        
        return {
            'direction': 'SHORT',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'strategy': 'EMA_RSI'
        }
    
    def _select_best_signal(self, long_signal, short_signal, indicators, symbol):
        """اختيار أفضل إشارة"""
        signals = []
        
        min_conditions_met = self.min_conditions
        
        if (long_signal['confidence'] >= self.min_confidence and 
            long_signal['conditions_met'] >= min_conditions_met):
            signals.append(long_signal)
        
        if (short_signal['confidence'] >= self.min_confidence and 
            short_signal['conditions_met'] >= min_conditions_met):
            signals.append(short_signal)
        
        if not signals:
            return None
        
        best_signal = max(signals, key=lambda x: x['confidence'])
        
        signal_info = {
            'symbol': symbol,
            'direction': best_signal['direction'],
            'confidence': best_signal['confidence'],
            'conditions_met': best_signal['conditions_met'],
            'total_conditions': best_signal['total_conditions'],
            'indicators': indicators,
            'timestamp': datetime.now(damascus_tz),
            'strategy': best_signal.get('strategy', 'EMA_RSI')
        }
        
        logger.info(f"🎯 إشارة EMA+RSI {symbol}: {best_signal['direction']} "
                   f"(ثقة: {best_signal['confidence']:.2%}, "
                   f"شروط: {best_signal['conditions_met']}/{best_signal['total_conditions']})")
        
        return signal_info

class TradeManager:
    """مدير الصفقات"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.trade_history = []
        self.symbol_cooldown = {}
    
    def sync_with_exchange(self):
        """مزامنة الصفقات مع المنصة"""
        try:
            account_info = self.client.futures_account()
            positions = account_info['positions']
            
            for position in positions:
                symbol = position['symbol']
                quantity = float(position['positionAmt'])
                
                if quantity != 0 and symbol in ['ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'LINKUSDT']:
                    if symbol not in self.active_trades:
                        side = "LONG" if quantity > 0 else "SHORT"
                        self.active_trades[symbol] = {
                            'symbol': symbol,
                            'quantity': abs(quantity),
                            'entry_price': float(position['entryPrice']),
                            'side': side,
                            'timestamp': datetime.now(damascus_tz),
                            'status': 'open',
                            'trailing_stop_price': None  # إضافة لحساب Trailing Stop
                        }
                elif symbol in ['ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'LINKUSDT'] and symbol in self.active_trades:
                    closed_trade = self.active_trades[symbol]
                    closed_trade['status'] = 'closed'
                    closed_trade['close_time'] = datetime.now(damascus_tz)
                    self.trade_history.append(closed_trade)
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
                return False, f"فترة تبريد: {remaining:.1f} دقائق"
        
        return True, ""
    
    def add_symbol_cooldown(self, symbol, minutes=30):  # زيادة التبريد إلى 30 دقيقة
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
    """مدير إشعارات التلغرام"""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
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
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            return response.status_code == 200
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False

class ScalpingTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbols': ["ETHUSDT","SOLUSDT"],
        'symbol_settings': {
            'ETHUSDT': {'used_balance': 5.5, 'leverage': 9, 'nominal_trade_size': 49.5},
            'SOLUSDT': {'used_balance': 5.5, 'leverage': 9, 'nominal_trade_size': 48.5},
        },
        'max_active_trades': 2,
        'data_interval': '5m',
        'rescan_interval_minutes': 5,  # زيادة إلى 5 دقائق
        'min_signal_confidence': 0.70,  # زيادة الحد الأدنى للثقة
        'max_daily_trades': 30,
        'cooldown_after_loss': 30,  # زيادة التبريد إلى 30 دقيقة
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

        # تهيئة مكونات السكالبينج
        self.signal_generator = MA_RSI_SignalGenerator()
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
            'consecutive_losses': 0,
            'consecutive_wins': 0,
            'symbol_stats': {
                symbol: {'trades': 0, 'wins': 0, 'losses': 0, 'total_pnl': 0.0}
                for symbol in self.TRADING_SETTINGS['symbols']
            }
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت السكالبينج متعدد العملات بنجاح")

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

    def is_trading_hours(self):
        """التحقق من ساعات التداول (8 صباحاً - 8 مساءً UTC)"""
        utc_time = datetime.now(pytz.UTC)
        hour = utc_time.hour
        return 6 <= hour <= 22  # جلسات لندن/نيويورك

    def can_open_trade(self, symbol, direction):
        """التحقق من إمكانية فتح صفقة"""
        reasons = []
        
        # التحقق من ساعات التداول
        if not self.is_trading_hours():
            reasons.append("خارج ساعات التداول النشطة (8 صباحاً - 8 مساءً UTC)")
        
        # التحقق من وجود صفقة نشطة على نفس الرمز
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append(f"يوجد صفقة نشطة على {symbol}")
        
        # التحقق من الحد الأقصى للصفقات النشطة
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("تم الوصول للحد الأقصى للصفقات النشطة")
        
        # التحقق من الرصيد المتاح
        available_balance = self.real_time_balance['available_balance']
        symbol_balance = self.TRADING_SETTINGS['symbol_settings'][symbol]['used_balance']
        if available_balance < symbol_balance:
            reasons.append("رصيد غير كافي")
        
        # التحقق من الحد اليومي
        if self.performance_stats['daily_trades_count'] >= self.TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
        
        # التحقق من نظام التبريد
        can_trade, cooldown_reason = self.trade_manager.can_trade_symbol(symbol)
        if not can_trade:
            reasons.append(cooldown_reason)
        
        # التحقق من الخسائر المتتالية
        if self.performance_stats['consecutive_losses'] >= 3:  # زيادة الحد إلى 3
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
                self.check_trade_exit(symbol, trade)
        except Exception as e:
            logger.error(f"❌ خطأ في إدارة الصفقات: {e}")

    def check_trade_exit(self, symbol, trade):
        """التحقق من خروج الصفقة"""
        try:
            current_price = self.get_current_price(symbol)
            if not current_price:
                return
            
            entry_price = trade['entry_price']
            data = self.get_historical_data(symbol)
            if data is None:
                return
            
            indicators = self.signal_generator._calculate_ma_rsi_indicators(data, current_price)
            atr = indicators['atr']
            
            # حساب TP وSL ديناميكياً بناءً على ATR
            target_profit_pct = max(1.5 * atr / current_price * 100, 0.35)  # حد أدنى 0.35% لتغطية الرسوم
            stop_loss_pct = 1.0 * atr / current_price * 100
            trailing_stop_pct = 0.15  # Trailing Stop بنسبة 0.15%
            
            if trade['side'] == 'LONG':
                pnl_pct = (current_price - entry_price) / entry_price * 100
                
                # تحديث Trailing Stop
                if trade['trailing_stop_price'] is None and pnl_pct >= 0.20:
                    trade['trailing_stop_price'] = current_price * (1 - trailing_stop_pct / 100)
                elif trade['trailing_stop_price'] is not None:
                    new_trailing_stop = current_price * (1 - trailing_stop_pct / 100)
                    trade['trailing_stop_price'] = max(trade['trailing_stop_price'], new_trailing_stop)
                
                # شروط الخروج
                if pnl_pct >= target_profit_pct:
                    self.close_trade(symbol, f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                if trade['trailing_stop_price'] is not None and current_price <= trade['trailing_stop_price']:
                    self.close_trade(symbol, f"Trailing Stop {pnl_pct:.2f}%")
                    return
                if pnl_pct <= -stop_loss_pct:
                    self.close_trade(symbol, f"وقف الخسارة {pnl_pct:.2f}%")
                    return
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                
                # تحديث Trailing Stop
                if trade['trailing_stop_price'] is None and pnl_pct >= 0.20:
                    trade['trailing_stop_price'] = current_price * (1 + trailing_stop_pct / 100)
                elif trade['trailing_stop_price'] is not None:
                    new_trailing_stop = current_price * (1 + trailing_stop_pct / 100)
                    trade['trailing_stop_price'] = min(trade['trailing_stop_price'], new_trailing_stop)
                
                # شروط الخروج
                if pnl_pct >= target_profit_pct:
                    self.close_trade(symbol, f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                if trade['trailing_stop_price'] is not None and current_price >= trade['trailing_stop_price']:
                    self.close_trade(symbol, f"Trailing Stop {pnl_pct:.2f}%")
                    return
                if pnl_pct <= -stop_loss_pct:
                    self.close_trade(symbol, f"وقف الخسارة {pnl_pct:.2f}%")
                    return
                    
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من خروج الصفقة لـ {symbol}: {e}")

    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            balance = self.real_time_balance
            
            message = (
                "⚡ <b>بدء تشغيل بوت السكالبينج متعدد العملات</b>\n"
                f"<b>الاستراتيجية:</b> المتوسطات المتحركة + RSI\n"
                f"<b>العملات:</b> ETH, ADA, DOT, LINK\n"
                f"<b>المؤشرات:</b> EMA 9/21/50/200 + RSI 9/14 + ATR\n"
                f"<b>الإعدادات:</b>\n"
                f"• الصفقات النشطة: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"• الصفقات اليومية: {self.TRADING_SETTINGS['max_daily_trades']}\n"
                f"• ساعات التداول: 8 صباحاً - 8 مساءً UTC\n"
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
        
        message = (
            f"📊 <b>تقرير أداء البوت متعدد العملات</b>\n"
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

    def get_historical_data(self, symbol, limit=100):
        """جلب البيانات التاريخية"""
        time.sleep(0.1)
        try:
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=self.TRADING_SETTINGS['data_interval'],
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

    def calculate_position_size(self, symbol, current_price):
        """حساب حجم المركز"""
        try:
            symbol_settings = self.TRADING_SETTINGS['symbol_settings'][symbol]
            nominal_size = symbol_settings['used_balance'] * symbol_settings['leverage']
            quantity = nominal_size / current_price
            
            # ضبط الكمية حسب متطلبات المنصة
            exchange_info = self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            
            if symbol_info:
                lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                if lot_size_filter:
                    step_size = float(lot_size_filter['stepSize'])
                    quantity = float(int(quantity / step_size) * step_size)
            
            if quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol}: {quantity:.6f}")
                return quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return None

    def set_leverage(self, symbol, leverage):
        """تعيين الرافعة المالية"""
        try:
            self.client.futures_change_leverage(
                symbol=symbol, 
                leverage=leverage
            )
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة لـ {symbol}: {e}")
            return False

    def execute_trade(self, symbol, trade_data):
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
            symbol_settings = self.TRADING_SETTINGS['symbol_settings'][symbol]
            self.set_leverage(symbol, symbol_settings['leverage'])
            
            # تنفيذ الأمر
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"⚡ تنفيذ صفقة {symbol}: {direction} | الكمية: {quantity:.6f}")
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order['orderId']:
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(
                        symbol=symbol, 
                        orderId=order['orderId']
                    )
                    if order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                except:
                    pass
                
                nominal_value = quantity * executed_price
                data = self.get_historical_data(symbol)
                if data is None:
                    return False
                indicators = self.signal_generator._calculate_ma_rsi_indicators(data, current_price)
                atr = indicators['atr']
                expected_profit = nominal_value * (max(1.5 * atr / current_price, 0.35) / 100)
                
                # تسجيل الصفقة
                trade_data = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': symbol_settings['leverage'],
                    'timestamp': datetime.now(damascus_tz),
                    'status': 'open',
                    'signal_confidence': signal['confidence'],
                    'nominal_value': nominal_value,
                    'expected_profit': expected_profit,
                    'strategy': 'EMA_RSI',
                    'trailing_stop_price': None  # إضافة Trailing Stop
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                self.performance_stats['symbol_stats'][symbol]['trades'] += 1
                
                # إرسال إشعار
                if self.notifier:
                    risk_reward_ratio = 1.5  # نسبة افتراضية بناءً على ATR
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة {symbol}</b>\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"القيمة الاسمية: ${nominal_value:.2f}\n"
                        f"الرافعة: {symbol_settings['leverage']}x\n"
                        f"🎯 الهدف: {max(1.5 * atr / current_price * 100, 0.35):.2f}%\n"
                        f"🛡️ الوقف: {1.0 * atr / current_price * 100:.2f}%\n"
                        f"⚖️ النسبة: {risk_reward_ratio:.2f}:1\n"
                        f"💰 الربح المتوقع: ${expected_profit:.4f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
                        f"الاستراتيجية: EMA+RSI\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol}")
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
                    self.performance_stats['consecutive_wins'] += 1
                    self.performance_stats['symbol_stats'][symbol]['wins'] += 1
                else:
                    self.performance_stats['losing_trades'] += 1
                    self.performance_stats['consecutive_losses'] += 1
                    self.performance_stats['consecutive_wins'] = 0
                    self.performance_stats['symbol_stats'][symbol]['losses'] += 1
                    
                    # إضافة تبديد بعد خسائر متتالية
                    if self.performance_stats['consecutive_losses'] >= 3:
                        self.trade_manager.add_symbol_cooldown(symbol, self.TRADING_SETTINGS['cooldown_after_loss'])
                
                self.performance_stats['total_pnl'] += pnl_pct
                self.performance_stats['symbol_stats'][symbol]['total_pnl'] += pnl_pct
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة {symbol}</b>\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"السبب: {reason}\n"
                        f"الاستراتيجية: {trade.get('strategy', 'EMA_RSI')}\n"
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

    def scan_market(self, symbol):
        """مسح السوق للعثور على فرص السكالبينج"""
        logger.info(f"🔍 بدء مسح السوق لـ {symbol}...")
        
        try:
            data = self.get_historical_data(symbol)
            if data is None or len(data) < 50:
                return None
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return None
            
            signal = self.signal_generator.generate_signal(data, current_price, symbol)
            if signal:
                logger.info(f"🎯 تم العثور على إشارة {symbol}: {signal['direction']} (ثقة: {signal['confidence']:.2%})")
                return signal
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
            return None

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول"""
        try:
            start_time = time.time()
            
            # مسح جميع العملات
            for symbol in self.TRADING_SETTINGS['symbols']:
                try:
                    signal = self.scan_market(symbol)
                    if signal and self.execute_trade(signal):
                        logger.info(f"✅ تم تنفيذ صفقة {symbol} بنجاح")
                        # انتظار قصير بين الصفقات
                        time.sleep(2)
                except Exception as e:
                    logger.error(f"❌ خطأ في معالجة {symbol}: {e}")
                    continue
            
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
                'strategy': trade.get('strategy', 'EMA_RSI')
            }
            for trade in trades.values()
        ]

    def get_market_analysis(self):
        """الحصول على تحليل السوق"""
        try:
            analysis = {}
            for symbol in self.TRADING_SETTINGS['symbols']:
                data = self.get_historical_data(symbol)
                if data is None:
                    analysis[symbol] = {'error': 'لا توجد بيانات'}
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    analysis[symbol] = {'error': 'لا يمكن الحصول على السعر'}
                    continue
                
                signal = self.signal_generator.generate_signal(data, current_price, symbol)
                
                analysis[symbol] = {
                    'current_price': current_price,
                    'signal': signal,
                    'timestamp': datetime.now(damascus_tz).isoformat()
                }
            
            return analysis
            
        except Exception as e:
            return {'error': str(e)}

    def get_performance_stats(self):
        """الحصول على إحصائيات الأداء"""
        win_rate = 0
        if self.performance_stats['trades_closed'] > 0:
            win_rate = (self.performance_stats['winning_trades'] / self.performance_stats['trades_closed']) * 100
        
        return {
            'performance': {
                'trades_opened': self.performance_stats['trades_opened'],
                'trades_closed': self.performance_stats['trades_closed'],
                'winning_trades': self.performance_stats['winning_trades'],
                'losing_trades': self.performance_stats['losing_trades'],
                'win_rate': round(win_rate, 1),
                'total_pnl': round(self.performance_stats['total_pnl'], 2),
                'daily_trades_count': self.performance_stats['daily_trades_count'],
                'consecutive_losses': self.performance_stats['consecutive_losses'],
                'consecutive_wins': self.performance_stats['consecutive_wins'],
                'symbol_stats': self.performance_stats['symbol_stats']
            },
            'risk_management': {
                'max_active_trades': self.TRADING_SETTINGS['max_active_trades'],
                'max_daily_trades': self.TRADING_SETTINGS['max_daily_trades']
            },
            'symbol_settings': self.TRADING_SETTINGS['symbol_settings'],
            'strategy': 'EMA_RSI',
            'trading_pairs': self.TRADING_SETTINGS['symbols']
        }

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت السكالبينج متعدد العملات...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت السكالبينج متعدد العملات</b>\n"
                f"الاستراتيجية: المتوسطات المتحركة + RSI\n"
                f"العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"الصفقات النشطة: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"الصفقات اليومية: {self.TRADING_SETTINGS['max_daily_trades']}\n"
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
            logger.info("🛑 إيقاف بوت السكالبينج متعدد العملات...")

def main():
    """الدالة الرئيسية"""
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
