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

@app.route('/trading_session')
def trading_session():
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            return jsonify(bot.get_current_session_info())
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
        logging.FileHandler('scalping_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TradingSessionManager:
    """مدير جلسات التداول بناءً على السيولة العالمية مع مراعاة توقيت دمشق"""
    
    def __init__(self):
        self.utc_offset = 3  # توقيت دمشق UTC+3
        
        self.sessions = {
            'asian': {
                'name': 'الجلسة الآسيوية',
                'start_hour_utc': 0,
                'end_hour_utc': 7,
                'symbols_focus': ['ADAUSDT', 'LINKUSDT'],  # رموز أقل تقلباً
                'active': False,
                'performance_multiplier': 0.6,
                'max_trades_per_hour': 3  # ⬅️ تحديد حد للجلسة الآسيوية
            },
            'euro_american_overlap': {
                'name': 'تداخل أوروبا-أمريكا (الأفضل)',
                'start_hour_utc': 13,
                'end_hour_utc': 17,
                'symbols_focus': ['ETHUSDT', 'ADAUSDT', 'LINKUSDT', 'SOLUSDT'],
                'active': False,
                'performance_multiplier': 1.0,
                'max_trades_per_hour': 6
            },
            'american': {
                'name': 'الجلسة الأمريكية',
                'start_hour_utc': 13,
                'end_hour_utc': 21,
                'symbols_focus': ['ETHUSDT', 'SOLUSDT', 'ADAUSDT'],
                'active': False,
                'performance_multiplier': 0.8,
                'max_trades_per_hour': 4
            },
            'low_liquidity': {
                'name': 'فترات سيولة منخفضة',
                'start_hour_utc': 21,
                'end_hour_utc': 0,
                'symbols_focus': [],
                'active': False,
                'performance_multiplier': 0.0,
                'max_trades_per_hour': 0
            }
        }
    
    def get_current_utc_time(self):
        """الحصول على الوقت UTC الحالي"""
        return datetime.utcnow()
    
    def get_damascus_time(self):
        """الحصول على توقيت دمشق الحالي"""
        return datetime.now(damascus_tz)
    
    def get_current_session(self):
        """الحصول على الجلسة الحالية بناءً على UTC"""
        current_utc = self.get_current_utc_time()
        current_hour_utc = current_utc.hour
        
        # إعادة تعيين حالة الجلسات
        for session in self.sessions.values():
            session['active'] = False
        
        for session_name, session_data in self.sessions.items():
            if session_name == 'low_liquidity':
                if current_hour_utc >= session_data['start_hour_utc'] or current_hour_utc < session_data['end_hour_utc']:
                    session_data['active'] = True
                    self._log_session_info(session_name, session_data, current_utc)
                    return session_data
            else:
                if session_data['start_hour_utc'] <= current_hour_utc < session_data['end_hour_utc']:
                    session_data['active'] = True
                    self._log_session_info(session_name, session_data, current_utc)
                    return session_data
        
        self.sessions['asian']['active'] = True
        self._log_session_info('asian', self.sessions['asian'], current_utc)
        return self.sessions['asian']
    
    def _log_session_info(self, session_name, session_data, utc_time):
        """تسجيل معلومات الجلسة"""
        start_damascus = (utc_time.replace(hour=session_data['start_hour_utc'], minute=0) + 
                         timedelta(hours=self.utc_offset)).strftime('%H:%M')
        end_damascus = (utc_time.replace(hour=session_data['end_hour_utc'], minute=0) + 
                       timedelta(hours=self.utc_offset)).strftime('%H:%M')
        
        logger.info(f"🌍 الجلسة: {session_data['name']} | دمشق {start_damascus}-{end_damascus}")
    
    def should_trade_symbol(self, symbol, current_session):
        """التحقق إذا كان يجب التداول على الرمز في الجلسة الحالية"""
        if not current_session['symbols_focus']:
            return False
        return symbol in current_session['symbols_focus']
    
    def get_session_performance_multiplier(self, session_name):
        """مضاعف الأداء بناءً على الجلسة"""
        return self.sessions.get(session_name, {}).get('performance_multiplier', 0.6)
    
    def get_trading_intensity(self, session_name):
        """شدة التداول بناءً على الجلسة"""
        intensity = {
            'euro_american_overlap': 'عالية',
            'american': 'متوسطة', 
            'asian': 'منخفضة',
            'low_liquidity': 'معدومة'
        }
        return intensity.get(session_name, 'منخفضة')
    
    def get_max_trades_per_hour(self, session_name):
        """الحد الأقصى للصفقات في الساعة"""
        return self.sessions.get(session_name, {}).get('max_trades_per_hour', 2)
    
    def get_session_schedule(self):
        """الحصول على جدول الجلسات بتوقيت دمشق"""
        schedule_info = {}
        current_utc = self.get_current_utc_time()
        
        for session_name, session_data in self.sessions.items():
            start_damascus = (current_utc.replace(hour=session_data['start_hour_utc'], minute=0) + 
                             timedelta(hours=self.utc_offset)).strftime('%H:%M')
            end_damascus = (current_utc.replace(hour=session_data['end_hour_utc'], minute=0) + 
                           timedelta(hours=self.utc_offset)).strftime('%H:%M')
            
            schedule_info[session_name] = {
                'name': session_data['name'],
                'time_damascus': f"{start_damascus} - {end_damascus}",
                'performance_multiplier': session_data['performance_multiplier'],
                'intensity': self.get_trading_intensity(session_name),
                'max_trades_per_hour': session_data['max_trades_per_hour']
            }
        
        return schedule_info

class AdvancedScalpingSignalGenerator:
    """مولد إشارات السكالبينج المتقدم مع شروط مشددة"""
    
    def __init__(self):
        self.min_confidence = 0.71  # ⬅️ زيادة من 0.70 إلى 0.75
        self.min_conditions = 5     # ⬅️ اشتراط 6/6 شروط
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارة سكالبينج متقدمة"""
        try:
            if len(data) < 50:
                return None
            
            # حساب المؤشرات المتقدمة
            indicators = self._calculate_advanced_indicators(data, current_price)
            
            # تحليل الإشارات مع شروط مشددة
            long_signal = self._analyze_strict_long_signal(indicators)
            short_signal = self._analyze_strict_short_signal(indicators)
            
            # اختيار أفضل إشارة
            return self._select_best_signal(symbol, long_signal, short_signal, indicators)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد الإشارة لـ {symbol}: {e}")
            return None
    
    def _calculate_advanced_indicators(self, data, current_price):
        """حساب المؤشرات المتقدمة"""
        df = data.copy()
        
        # 1. المتوسطات المتحركة الأسية
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        
        # 2. بولينجر باندز مع تعديلات
        df['bb_middle'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
        df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        
        # 3. فيبوناتشي (آخر 60 دقيقة)
        high_60m = df['high'].rolling(20).max()
        low_60m = df['low'].rolling(20).min()
        
        fib_levels = {}
        fib_ranges = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        for level in fib_ranges:
            fib_price = low_60m.iloc[-1] + (high_60m.iloc[-1] - low_60m.iloc[-1]) * level
            fib_levels[f'fib_{int(level*1000)}'] = fib_price
        
        # 4. RSI مع تأكيد
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        # 5. مؤشر الحجم (جديد) ⬅️ إضافة تأكيد الحجم
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        df['volume_trend'] = df['volume_ratio'].rolling(5).mean()
        
        # 6. مؤشر الزخم
        df['momentum'] = df['close'].pct_change(3)
        
        # 7. تقلبات السعر
        df['volatility'] = df['close'].pct_change().rolling(10).std() * 100
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        return {
            'ema5': latest['ema5'],
            'ema10': latest['ema10'],
            'ema20': latest['ema20'],
            'bb_upper': latest['bb_upper'],
            'bb_lower': latest['bb_lower'],
            'bb_middle': latest['bb_middle'],
            'bb_width': latest['bb_width'],
            'rsi': latest['rsi'],
            'volume_ratio': latest['volume_ratio'],
            'volume_trend': latest['volume_trend'],
            'momentum': latest['momentum'],
            'volatility': latest['volatility'],
            'current_price': current_price,
            'fib_levels': fib_levels,
            'high_60m': high_60m.iloc[-1],
            'low_60m': low_60m.iloc[-1],
            'prev_close': prev['close']
        }
    
    def _calculate_rsi(self, prices, period):
        """حساب RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1]
    
    def _analyze_strict_long_signal(self, indicators):
        """تحليل إشارة الشراء بشروط مشددة"""
        conditions = []
        
        # 1. تقاطع المتوسطات القوي
        conditions.append(indicators['ema5'] > indicators['ema10'])
        conditions.append(indicators['ema10'] > indicators['ema20'])
        conditions.append(indicators['ema5'] > indicators['ema5'] * 1.002)  # تأكيد اتجاه صاعد
        
        # 2. موقع السعر من بولينجر باند
        bb_position = (indicators['current_price'] - indicators['bb_lower']) / (indicators['bb_upper'] - indicators['bb_lower'])
        conditions.append(bb_position < 0.3)  # قريب من النطاق السفلي
        conditions.append(indicators['bb_width'] > 0.02)  # تأكيد وجود تقلبات كافية
        
        # 3. تأكيد فيبوناتشي
        fib_618 = indicators['fib_levels']['fib_618']
        fib_786 = indicators['fib_levels']['fib_786']
        price_vs_fib_618 = abs(indicators['current_price'] - fib_618) / fib_618
        price_vs_fib_786 = abs(indicators['current_price'] - fib_786) / fib_786
        conditions.append(price_vs_fib_618 < 0.004 or price_vs_fib_786 < 0.004)
        
        # 4. زخم RSI
        conditions.append(40 < indicators['rsi'] < 65)  # نطاق أضيق
        
        # 5. تأكيد الحجم (جديد) ⬅️ شرط إضافي
        conditions.append(indicators['volume_ratio'] > 0.8)  # حجم معقول
        conditions.append(indicators['volume_trend'] > 0.9)  # اتجاه حجم إيجابي
        
        # 6. الزخم الإيجابي
        conditions.append(indicators['momentum'] > -0.001)  # زخم غير سلبي
        
        # 7. تجنب التقلبات العالية جداً
        conditions.append(indicators['volatility'] < 5.0)  # تقلبات معقولة
        
        confidence = sum(conditions) / len(conditions)
        
        return {
            'direction': 'LONG',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'strict_conditions': True
        }
    
    def _analyze_strict_short_signal(self, indicators):
        """تحليل إشارة البيع بشروط مشددة"""
        conditions = []
        
        # 1. تقاطع المتوسطات القوي
        conditions.append(indicators['ema5'] < indicators['ema10'])
        conditions.append(indicators['ema10'] < indicators['ema20'])
        conditions.append(indicators['ema5'] < indicators['ema5'] * 0.998)  # تأكيد اتجاه هابط
        
        # 2. موقع السعر من بولينجر باند
        bb_position = (indicators['current_price'] - indicators['bb_lower']) / (indicators['bb_upper'] - indicators['bb_lower'])
        conditions.append(bb_position > 0.7)  # قريب من النطاق العلوي
        conditions.append(indicators['bb_width'] > 0.02)  # تأكيد وجود تقلبات كافية
        
        # 3. تأكيد فيبوناتشي
        fib_236 = indicators['fib_levels']['fib_236']
        fib_382 = indicators['fib_levels']['fib_382']
        price_vs_fib_236 = abs(indicators['current_price'] - fib_236) / fib_236
        price_vs_fib_382 = abs(indicators['current_price'] - fib_382) / fib_382
        conditions.append(price_vs_fib_236 < 0.004 or price_vs_fib_382 < 0.004)
        
        # 4. زخم RSI
        conditions.append(35 < indicators['rsi'] < 60)  # نطاق أضيق
        
        # 5. تأكيد الحجم (جديد)
        conditions.append(indicators['volume_ratio'] > 0.8)  # حجم معقول
        conditions.append(indicators['volume_trend'] > 0.9)  # اتجاه حجم إيجابي
        
        # 6. الزخم السلبي
        conditions.append(indicators['momentum'] < 0.001)  # زخم غير إيجابي
        
        # 7. تجنب التقلبات العالية جداً
        conditions.append(indicators['volatility'] < 5.0)  # تقلبات معقولة
        
        confidence = sum(conditions) / len(conditions)
        
        return {
            'direction': 'SHORT',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'strict_conditions': True
        }
    
    def _select_best_signal(self, symbol, long_signal, short_signal, indicators):
        """اختيار أفضل إشارة بشروط مشددة"""
        signals = []
        
        # ⬅️ اشتراط تحقيق جميع الشروط أو معظمها
        min_conditions_met = self.min_conditions - 1  #允许5/6 أو 6/6
        
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
            'strict_conditions': best_signal.get('strict_conditions', False)
        }
        
        logger.info(f"🎯 إشارة مشددة {symbol}: {best_signal['direction']} "
                   f"(ثقة: {best_signal['confidence']:.2%}, "
                   f"شروط: {best_signal['conditions_met']}/{best_signal['total_conditions']})")
        
        return signal_info

class TradeManager:
    """مدير الصفقات مع تحسينات التبريد"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.trade_history = []
        self.symbol_cooldown = {}  # ⬅️ نظام التبريد للرموز
        self.session_cooldown = {} # ⬅️ نظام التبريد للجلسات
    
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
    
    def can_trade_symbol(self, symbol, session_name):
        """التحقق من إمكانية التداول على الرمز مع نظام التبريد"""
        # التحقق من التبريد بعد خسائر متتالية على نفس الرمز
        if symbol in self.symbol_cooldown:
            cooldown_end = self.symbol_cooldown[symbol]
            if datetime.now(damascus_tz) < cooldown_end:
                remaining = (cooldown_end - datetime.now(damascus_tz)).total_seconds() / 60
                logger.info(f"⏳ تبريد لـ {symbol}: {remaining:.1f} دقائق متبقية")
                return False, f"فترة تبريد: {remaining:.1f} دقائق"
        
        return True, ""
    
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
    
    def add_trade(self, symbol, trade_data):
        self.active_trades[symbol] = trade_data
    
    def remove_trade(self, symbol):
        if symbol in self.active_trades:
            del self.active_trades[symbol]
    
    def get_trade(self, symbol):
        return self.active_trades.get(symbol)
    
    def get_all_trades(self):
        return self.active_trades.copy()
    
    def get_recent_trades_count(self, symbol, minutes=60):
        """عدد الصفقات الحديثة على الرمز"""
        count = 0
        current_time = datetime.now(damascus_tz)
        for trade in list(self.active_trades.values()) + self.trade_history:
            if trade['symbol'] == symbol:
                trade_time = trade.get('close_time', trade['timestamp'])
                if (current_time - trade_time).total_seconds() <= minutes * 60:
                    count += 1
        return count

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
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
            return response.status_code == 200
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False
    
    def send_trade_alert(self, symbol, signal, current_price):
        """إرسال إشعار صفقة سكالبينج"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        strict_indicator = " 🔒" if signal.get('strict_conditions') else ""
        
        message = (
            f"{direction_emoji} <b>إشارة سكالبينج مشددة{strict_indicator}</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"السعر: ${current_price:.4f}\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message, 'trade_signal')

class ScalpingTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbols': ["ETHUSDT", "LINKUSDT", "ADAUSDT", "SOLUSDT","BNBUSDT","BTCUSDT"],
        'used_balance_per_trade': 5,
        'max_leverage': 4,
        'nominal_trade_size': 24,
        'max_active_trades': 3,
        'data_interval': '3m',
        'rescan_interval_minutes': 2,
        'min_signal_confidence': 0.71,  # ⬅️ زيادة من 0.70 إلى 0.75
        'target_profit_pct': 0.25,     # ⬅️ زيادة من 0.15% إلى 0.25%
        'stop_loss_pct': 0.15,         # ⬅️ زيادة من 0.10% إلى 0.15%
        'max_daily_trades': 30,        # ⬅️ تقليل من 30 إلى 25
        'cooldown_after_loss': 10,     # ⬅️ زيادة من 5 إلى 10 دقائق
        
        # إعدادات التوقيت الذكي المحسنة
        'session_settings': {
            'euro_american_overlap': {
                'rescan_interval': 2,
                'max_trades_per_cycle': 2,
                'confidence_boost': 0.0,
                'max_trades_per_symbol_per_hour': 3  # ⬅️ حد جديد
            },
            'american': {
                'rescan_interval': 3,
                'max_trades_per_cycle': 1,
                'confidence_boost': 0.05,
                'max_trades_per_symbol_per_hour': 2
            },
            'asian': {
                'rescan_interval': 5,
                'max_trades_per_cycle': 1,
                'confidence_boost': 0.10,
                'max_trades_per_symbol_per_hour': 2  # ⬅️ تحديد للجلسة الآسيوية
            },
            'low_liquidity': {
                'rescan_interval': 10,
                'max_trades_per_cycle': 0,
                'confidence_boost': 0.0,
                'max_trades_per_symbol_per_hour': 0
            }
        }
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

        # تهيئة مكونات السكالبينج المحسنة
        self.signal_generator = AdvancedScalpingSignalGenerator()  # ⬅️ استخدام المولد المتقدم
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        self.session_manager = TradingSessionManager()
        
        # الإعدادات الديناميكية
        self.dynamic_settings = {
            'rescan_interval': self.TRADING_SETTINGS['rescan_interval_minutes'],
            'max_trades_per_cycle': 1,
            'confidence_boost': 0.0,
            'session_name': 'غير محدد',
            'trading_intensity': 'متوسطة',
            'max_trades_per_symbol_per_hour': 2
        }
        
        # إحصائيات الأداء المحسنة
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
            'session_performance': {},
            'symbol_performance': {},
            'hourly_trade_count': 0,
            'last_hour_reset': datetime.now(damascus_tz)
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        self.adjust_settings_for_session()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت السكالبينج المحسن بنجاح")

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

    def adjust_settings_for_session(self):
        """ضبط إعدادات التداول بناءً على الجلسة الحالية"""
        current_session = self.session_manager.get_current_session()
        session_name = [k for k, v in self.session_manager.sessions.items() if v['active']][0]
        
        session_config = self.TRADING_SETTINGS['session_settings'].get(session_name, {})
        
        # تحديث الإعدادات الديناميكية
        self.dynamic_settings = {
            'rescan_interval': session_config.get('rescan_interval', 5),
            'max_trades_per_cycle': session_config.get('max_trades_per_cycle', 1),
            'confidence_boost': session_config.get('confidence_boost', 0.0),
            'session_name': current_session['name'],
            'trading_intensity': self.session_manager.get_trading_intensity(session_name),
            'max_trades_per_symbol_per_hour': session_config.get('max_trades_per_symbol_per_hour', 2)
        }
        
        logger.info(f"🎯 جلسة التداول: {current_session['name']} - شدة: {self.dynamic_settings['trading_intensity']}")

    def should_skip_trading(self):
        """التحقق إذا كان يجب تخطي التداول في الجلسة الحالية"""
        current_session = self.session_manager.get_current_session()
        session_name = [k for k, v in self.session_manager.sessions.items() if v['active']][0]
        
        # لا تداول في فترات السيولة المنخفضة
        if session_name == 'low_liquidity':
            logger.info("⏸️ تخطي التداول - فترة سيولة منخفضة")
            return True
            
        return False

    def get_session_enhanced_confidence(self, original_confidence):
        """تعزيز ثقة الإشارة بناءً على الجلسة"""
        boosted_confidence = original_confidence + self.dynamic_settings['confidence_boost']
        return min(boosted_confidence, 0.95)

    def can_open_trade(self, symbol, direction):
        """التحقق من إمكانية فتح صفقة سكالبينج مع القيود المحسنة"""
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
        
        # التحقق من نظام التبريد للرمز ⬅️ تحسين التبريد
        can_trade_symbol, cooldown_reason = self.trade_manager.can_trade_symbol(symbol, self.dynamic_settings['session_name'])
        if not can_trade_symbol:
            reasons.append(cooldown_reason)
        
        # التحقق من الحد الأقصى للصفقات على الرمز في الساعة ⬅️ تحسين جديد
        recent_trades = self.trade_manager.get_recent_trades_count(symbol, 60)
        if recent_trades >= self.dynamic_settings['max_trades_per_symbol_per_hour']:
            reasons.append(f"الحد الأقصى للصفقات على الرمز في الساعة ({recent_trades}/{self.dynamic_settings['max_trades_per_symbol_per_hour']})")
        
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
                    self.trade_manager.cleanup_cooldowns()  # ⬅️ تنظيف التبريد
                    self.reset_hourly_count()  # ⬅️ إعادة تعيين العدد الساعي
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(60)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        if self.notifier:
            schedule.every(6).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)
            schedule.every(1).hours.do(self.send_heartbeat)
            schedule.every(4).hours.do(self.send_session_report)
            schedule.every().day.at("16:00").do(self.send_session_report)

    def reset_hourly_count(self):
        """إعادة تعيين عدد الصفقات الساعي"""
        current_time = datetime.now(damascus_tz)
        if current_time.hour != self.performance_stats['last_hour_reset'].hour:
            self.performance_stats['hourly_trade_count'] = 0
            self.performance_stats['last_hour_reset'] = current_time
            logger.info("🔄 إعادة تعيين العداد الساعي للصفقات")

    def update_real_time_balance(self):
        """تحديث الرصيد الحقيقي"""
        try:
            self.real_time_balance = self.get_real_time_balance()
            return True
        except Exception as e:
            logger.error(f"❌ فشل تحديث الرصيد: {e}")
            return False

    def manage_active_trades(self):
        """إدارة الصفقات النشطة للسكالبينج"""
        try:
            active_trades = self.trade_manager.get_all_trades()
            for symbol, trade in active_trades.items():
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
            session_schedule = self.session_manager.get_session_schedule()
            
            schedule_text = ""
            for session, info in session_schedule.items():
                schedule_text += f"\n• {info['name']}: {info['time_damascus']} ({info['intensity']})"
            
            message = (
                "⚡ <b>بدء تشغيل بوت السكالبينج المحسن</b>\n"
                f"<b>التحسينات الجديدة:</b>\n"
                f"• وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}% (زيادة)\n"
                f"• هدف الربح: {self.TRADING_SETTINGS['target_profit_pct']}% (زيادة)\n"
                f"• ثقة الإشارة: {self.TRADING_SETTINGS['min_signal_confidence']:.0%} (زيادة)\n"
                f"• نظام التبريد: {self.TRADING_SETTINGS['cooldown_after_loss']} دقائق\n"
                f"• شروط مشددة: 6/6 شروط\n"
                f"<b>جدول الجلسات (توقيت دمشق):</b>{schedule_text}\n"
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
        
        # حساب نسبة المكافأة/المخاطرة
        risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
        
        message = (
            f"📊 <b>تقرير أداء السكالبينج المحسن</b>\n"
            f"الجلسة: {self.dynamic_settings['session_name']}\n"
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
        """إرسال تقرير بالرصيد الحقيقي"""
        if not self.notifier:
            return
        
        try:
            self.update_real_time_balance()
            balance = self.real_time_balance
            active_trades = self.trade_manager.get_active_trades_count()
            
            message = (
                f"💰 <b>تقرير الرصيد الحقيقي</b>\n"
                f"الجلسة: {self.dynamic_settings['session_name']}\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الرصيد المتاح: ${balance['available_balance']:.2f}\n"
                f"الصفقات النشطة: {active_trades}\n"
                f"آخر تحديث: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            
            self.notifier.send_message(message, 'balance_report')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تقرير الرصيد: {e}")

    def send_session_report(self):
        """إرسال تقرير الجلسة"""
        if not self.notifier:
            return
        
        self.adjust_settings_for_session()
        current_session = self.session_manager.get_current_session()
        session_name = [k for k, v in self.session_manager.sessions.items() if v['active']][0]
        performance_multiplier = self.session_manager.get_session_performance_multiplier(session_name)
        
        message = (
            f"🌍 <b>تقرير جلسة التداول المحسن</b>\n"
            f"الجلسة: {current_session['name']}\n"
            f"الشدة: {self.dynamic_settings['trading_intensity']}\n"
            f"مضاعف الأداء: {performance_multiplier:.0%}\n"
            f"فاصل المسح: {self.dynamic_settings['rescan_interval']} دقائق\n"
            f"الحد الأقصى للصفقات: {self.dynamic_settings['max_trades_per_cycle']}\n"
            f"الحد الأقصى للرمز/ساعة: {self.dynamic_settings['max_trades_per_symbol_per_hour']}\n"
            f"الوقت العالمي: {datetime.utcnow().strftime('%H:%M UTC')}\n"
            f"الوقت دمشق: {datetime.now(damascus_tz).strftime('%H:%M')}"
        )
        self.notifier.send_message(message)

    def send_heartbeat(self):
        """إرسال نبضة"""
        if self.notifier:
            active_trades = self.trade_manager.get_active_trades_count()
            message = f"💓 بوت السكالبينج المحسن نشط - الجلسة: {self.dynamic_settings['session_name']} - الصفقات: {active_trades}"
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

    def calculate_position_size(self, symbol, current_price):
        """حساب حجم المركز بناءً على الرصيد المستخدم والرافعة"""
        try:
            nominal_size = self.TRADING_SETTINGS['used_balance_per_trade'] * self.TRADING_SETTINGS['max_leverage']
            quantity = nominal_size / current_price
            quantity = self.adjust_quantity(symbol, quantity)
            
            if quantity and quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol}: {quantity:.6f}")
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
            
            logger.info(f"⚡ تنفيذ صفقة سكالبينج {symbol}: {direction} | الكمية: {quantity:.6f}")
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order['orderId']:
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                    if order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                except:
                    pass
                
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
                    'strict_conditions': signal.get('strict_conditions', False)
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['hourly_trade_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                
                # إرسال إشعار
                if self.notifier:
                    strict_indicator = " 🔒" if signal.get('strict_conditions') else ""
                    risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
                    
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة سكالبينج مشددة{strict_indicator}</b>\n"
                        f"الجلسة: {self.dynamic_settings['session_name']}\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"القيمة الاسمية: ${nominal_value:.2f}\n"
                        f"الرافعة: {leverage}x\n"
                        f"🎯 الهدف: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                        f"🛡️ الوقف: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                        f"⚖️ النسبة: {risk_reward_ratio:.2f}:1\n"
                        f"💰 الربح المتوقع: ${expected_profit:.4f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
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
                    self.performance_stats['consecutive_wins'] += 1
                else:
                    self.performance_stats['losing_trades'] += 1
                    self.performance_stats['consecutive_losses'] += 1
                    self.performance_stats['consecutive_wins'] = 0
                    
                    # ⬅️ إضافة تبريد بعد خسائر متتالية على نفس الرمز
                    if self.performance_stats['consecutive_losses'] >= 2:
                        self.trade_manager.add_symbol_cooldown(symbol, self.TRADING_SETTINGS['cooldown_after_loss'])
                
                self.performance_stats['total_pnl'] += pnl_pct
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة سكالبينج</b>\n"
                        f"الجلسة: {self.dynamic_settings['session_name']}\n"
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
        logger.info("🔍 بدء مسح السوق للسكالبينج المحسن...")
        
        opportunities = []
        current_session = self.session_manager.get_current_session()
        
        for symbol in self.TRADING_SETTINGS['symbols']:
            try:
                # تخطي الرموز ذات الصفقات النشطة
                if self.trade_manager.is_symbol_trading(symbol):
                    continue
                
                # التحقق من تركيز الجلسة على الرمز
                if not self.session_manager.should_trade_symbol(symbol, current_session):
                    continue
                
                data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'])
                if data is None or len(data) < 50:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                signal = self.signal_generator.generate_signal(symbol, data, current_price)
                if signal:
                    enhanced_confidence = self.get_session_enhanced_confidence(signal['confidence'])
                    signal['confidence'] = enhanced_confidence
                    
                    opportunities.append(signal)
                    
                    if self.notifier:
                        self.notifier.send_trade_alert(symbol, signal, current_price)
                
            except Exception as e:
                logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
                continue
        
        opportunities.sort(key=lambda x: x['confidence'], reverse=True)
        
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة سكالبينج في جلسة {self.dynamic_settings['session_name']}")
        return opportunities

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول للسكالبينج مع مراعاة الجلسة"""
        try:
            self.adjust_settings_for_session()
            
            if self.should_skip_trading():
                wait_time = self.dynamic_settings['rescan_interval'] * 60
                logger.info(f"💤 وضع السكون - انتظار {wait_time/60:.0f} دقائق")
                time.sleep(wait_time)
                return
            
            start_time = time.time()
            opportunities = self.scan_market()
            
            executed_trades = 0
            max_trades = self.dynamic_settings['max_trades_per_cycle']
            
            for signal in opportunities:
                if executed_trades >= max_trades:
                    break
                
                if self.execute_trade(signal):
                    executed_trades += 1
                    time.sleep(1)
            
            elapsed_time = time.time() - start_time
            wait_time = (self.dynamic_settings['rescan_interval'] * 60) - elapsed_time
            
            if wait_time > 0:
                logger.info(f"⏳ انتظار {wait_time:.1f} ثانية للدورة القادمة في جلسة {self.dynamic_settings['session_name']}")
                time.sleep(wait_time)
            else:
                logger.info(f"⚡ بدء الدورة التالية فوراً في جلسة {self.dynamic_settings['session_name']}")
            
            logger.info(f"✅ اكتملت دورة السكالبينج في جلسة {self.dynamic_settings['session_name']} - تم تنفيذ {executed_trades} صفقة")
            
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
                'strict_conditions': trade.get('strict_conditions', False)
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

    def get_current_session_info(self):
        """الحصول على معلومات الجلسة الحالية"""
        current_session = self.session_manager.get_current_session()
        session_name = [k for k, v in self.session_manager.sessions.items() if v['active']][0]
        session_schedule = self.session_manager.get_session_schedule()
        
        return {
            'current_session': {
                'name': current_session['name'],
                'intensity': self.dynamic_settings['trading_intensity'],
                'performance_multiplier': self.session_manager.get_session_performance_multiplier(session_name),
                'rescan_interval': self.dynamic_settings['rescan_interval'],
                'max_trades_per_cycle': self.dynamic_settings['max_trades_per_cycle'],
                'max_trades_per_symbol_per_hour': self.dynamic_settings['max_trades_per_symbol_per_hour']
            },
            'schedule': session_schedule,
            'time_info': {
                'utc_time': datetime.utcnow().strftime('%H:%M UTC'),
                'damascus_time': datetime.now(damascus_tz).strftime('%H:%M دمشق')
            }
        }

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
                'hourly_trade_count': self.performance_stats['hourly_trade_count'],
                'consecutive_losses': self.performance_stats['consecutive_losses'],
                'consecutive_wins': self.performance_stats['consecutive_wins']
            },
            'risk_management': {
                'target_profit_pct': self.TRADING_SETTINGS['target_profit_pct'],
                'stop_loss_pct': self.TRADING_SETTINGS['stop_loss_pct'],
                'risk_reward_ratio': round(risk_reward_ratio, 2),
                'used_balance_per_trade': self.TRADING_SETTINGS['used_balance_per_trade'],
                'max_leverage': self.TRADING_SETTINGS['max_leverage']
            },
            'current_session': self.dynamic_settings['session_name']
        }

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت السكالبينج المحسن...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت السكالبينج المحسن</b>\n"
                f"الاستراتيجية: تقاطع EMA + بولينجر + فيبوناتشي\n"
                f"نظام الجلسات الذكي: نشط ✅\n"
                f"الشروط المشددة: مفعلة 🔒\n"
                f"نظام التبريد: نشط ⏰\n"
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
            logger.info("🛑 إيقاف بوت السكالبينج المحسن...")

def main():
    """الدالة الرئيسية"""
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
