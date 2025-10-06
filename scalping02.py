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
                'active': False,
                'performance_multiplier': 0.7,
                'relaxed_conditions': True  # ⬅️ شروط مخففة
            },
            'euro_american_overlap': {
                'name': 'تداخل أوروبا-أمريكا (الأفضل)',
                'start_hour_utc': 13,
                'end_hour_utc': 17,
                'active': False,
                'performance_multiplier': 1.0,
                'relaxed_conditions': True  # ⬅️ شروط مخففة
            },
            'american': {
                'name': 'الجلسة الأمريكية',
                'start_hour_utc': 13,
                'end_hour_utc': 21,
                'active': False,
                'performance_multiplier': 0.8,
                'relaxed_conditions': True  # ⬅️ شروط مخففة
            },
            'low_liquidity': {
                'name': 'فترات سيولة منخفضة',
                'start_hour_utc': 21,
                'end_hour_utc': 0,
                'active': False,
                'performance_multiplier': 0.3,
                'relaxed_conditions': False  # ⬅️ شروط مشددة
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
        
        condition_type = "مخففة" if session_data.get('relaxed_conditions', False) else "مشددة"
        logger.info(f"🌍 الجلسة: {session_data['name']} | دمشق {start_damascus}-{end_damascus} | الشروط: {condition_type}")
    
    def are_conditions_relaxed(self, session_name):
        """التحقق إذا كانت الشروط مخففة في الجلسة الحالية"""
        return self.sessions.get(session_name, {}).get('relaxed_conditions', False)
    
    def get_session_performance_multiplier(self, session_name):
        """مضاعف الأداء بناءً على الجلسة"""
        return self.sessions.get(session_name, {}).get('performance_multiplier', 0.6)
    
    def get_trading_intensity(self, session_name):
        """شدة التداول بناءً على الجلسة"""
        intensity = {
            'euro_american_overlap': 'عالية جداً',
            'american': 'عالية', 
            'asian': 'متوسطة',
            'low_liquidity': 'منخفضة'
        }
        return intensity.get(session_name, 'متوسطة')
    
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
                'relaxed_conditions': session_data.get('relaxed_conditions', False)
            }
        
        return schedule_info

class AdvancedScalpingSignalGenerator:
    """مولد إشارات السكالبينج المتقدم مع شروط مرنة أثناء الجلسات"""
    
    def __init__(self):
        self.strict_min_confidence = 0.71    # ⬅️ للشروط المشددة
        self.relaxed_min_confidence = 0.65   # ⬅️ للشروط المخففة
        self.strict_min_conditions = 5       # ⬅️ للشروط المشددة
        self.relaxed_min_conditions = 4      # ⬅️ للشروط المخففة
    
    def generate_signal(self, symbol, data, current_price, relaxed_conditions=False):
        """توليد إشارة سكالبينج متقدمة مع خيار الشروط المخففة"""
        try:
            if len(data) < 50:
                return None
            
            # حساب المؤشرات المتقدمة
            indicators = self._calculate_advanced_indicators(data, current_price)
            
            # تحليل الإشارات مع الشروط المناسبة
            long_signal = self._analyze_long_signal(indicators, relaxed_conditions)
            short_signal = self._analyze_short_signal(indicators, relaxed_conditions)
            
            # اختيار أفضل إشارة
            return self._select_best_signal(symbol, long_signal, short_signal, indicators, relaxed_conditions)
            
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
        
        # 5. مؤشر الحجم
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
    
    def _analyze_long_signal(self, indicators, relaxed_conditions=False):
        """تحليل إشارة الشراء بشروط مرنة"""
        conditions = []
        
        # 1. تقاطع المتوسطات المتحركة (مخفف أثناء الجلسات)
        if relaxed_conditions:
            conditions.append(indicators['ema5'] > indicators['ema10'])
            conditions.append(indicators['ema10'] > indicators['ema20'] * 0.998)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['ema5'] > indicators['ema10'])
            conditions.append(indicators['ema10'] > indicators['ema20'])
            conditions.append(indicators['ema5'] > indicators['ema5'] * 1.002)
        
        # 2. موقع السعر من بولينجر باند (مخفف)
        bb_position = (indicators['current_price'] - indicators['bb_lower']) / (indicators['bb_upper'] - indicators['bb_lower'])
        if relaxed_conditions:
            conditions.append(bb_position < 0.4)  # ⬅️ تخفيف من 0.3 إلى 0.4
        else:
            conditions.append(bb_position < 0.3)
        
        conditions.append(indicators['bb_width'] > 0.015)  # ⬅️ تخفيف تقلبات
        
        # 3. تأكيد فيبوناتشي (مخفف)
        fib_618 = indicators['fib_levels']['fib_618']
        fib_786 = indicators['fib_levels']['fib_786']
        price_vs_fib_618 = abs(indicators['current_price'] - fib_618) / fib_618
        price_vs_fib_786 = abs(indicators['current_price'] - fib_786) / fib_786
        if relaxed_conditions:
            conditions.append(price_vs_fib_618 < 0.006 or price_vs_fib_786 < 0.006)  # ⬅️ تخفيف
        else:
            conditions.append(price_vs_fib_618 < 0.004 or price_vs_fib_786 < 0.004)
        
        # 4. زخم RSI (مخفف)
        if relaxed_conditions:
            conditions.append(35 < indicators['rsi'] < 70)  # ⬅️ نطاق أوسع
        else:
            conditions.append(40 < indicators['rsi'] < 65)
        
        # 5. تأكيد الحجم (مخفف)
        if relaxed_conditions:
            conditions.append(indicators['volume_ratio'] > 0.6)  # ⬅️ تخفيف
            conditions.append(indicators['volume_trend'] > 0.7)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['volume_ratio'] > 0.8)
            conditions.append(indicators['volume_trend'] > 0.9)
        
        # 6. الزخم (مخفف)
        if relaxed_conditions:
            conditions.append(indicators['momentum'] > -0.002)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['momentum'] > -0.001)
        
        # 7. التقلبات (مخفف)
        if relaxed_conditions:
            conditions.append(indicators['volatility'] < 6.0)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['volatility'] < 5.0)
        
        confidence = sum(conditions) / len(conditions)
        
        return {
            'direction': 'LONG',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'relaxed_conditions': relaxed_conditions
        }
    
    def _analyze_short_signal(self, indicators, relaxed_conditions=False):
        """تحليل إشارة البيع بشروط مرنة"""
        conditions = []
        
        # 1. تقاطع المتوسطات المتحركة (مخفف أثناء الجلسات)
        if relaxed_conditions:
            conditions.append(indicators['ema5'] < indicators['ema10'])
            conditions.append(indicators['ema10'] < indicators['ema20'] * 1.002)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['ema5'] < indicators['ema10'])
            conditions.append(indicators['ema10'] < indicators['ema20'])
            conditions.append(indicators['ema5'] < indicators['ema5'] * 0.998)
        
        # 2. موقع السعر من بولينجر باند (مخفف)
        bb_position = (indicators['current_price'] - indicators['bb_lower']) / (indicators['bb_upper'] - indicators['bb_lower'])
        if relaxed_conditions:
            conditions.append(bb_position > 0.6)  # ⬅️ تخفيف من 0.7 إلى 0.6
        else:
            conditions.append(bb_position > 0.7)
        
        conditions.append(indicators['bb_width'] > 0.015)  # ⬅️ تخفيف تقلبات
        
        # 3. تأكيد فيبوناتشي (مخفف)
        fib_236 = indicators['fib_levels']['fib_236']
        fib_382 = indicators['fib_levels']['fib_382']
        price_vs_fib_236 = abs(indicators['current_price'] - fib_236) / fib_236
        price_vs_fib_382 = abs(indicators['current_price'] - fib_382) / fib_382
        if relaxed_conditions:
            conditions.append(price_vs_fib_236 < 0.006 or price_vs_fib_382 < 0.006)  # ⬅️ تخفيف
        else:
            conditions.append(price_vs_fib_236 < 0.004 or price_vs_fib_382 < 0.004)
        
        # 4. زخم RSI (مخفف)
        if relaxed_conditions:
            conditions.append(30 < indicators['rsi'] < 65)  # ⬅️ نطاق أوسع
        else:
            conditions.append(35 < indicators['rsi'] < 60)
        
        # 5. تأكيد الحجم (مخفف)
        if relaxed_conditions:
            conditions.append(indicators['volume_ratio'] > 0.6)  # ⬅️ تخفيف
            conditions.append(indicators['volume_trend'] > 0.7)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['volume_ratio'] > 0.8)
            conditions.append(indicators['volume_trend'] > 0.9)
        
        # 6. الزخم (مخفف)
        if relaxed_conditions:
            conditions.append(indicators['momentum'] < 0.002)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['momentum'] < 0.001)
        
        # 7. التقلبات (مخفف)
        if relaxed_conditions:
            conditions.append(indicators['volatility'] < 6.0)  # ⬅️ تخفيف
        else:
            conditions.append(indicators['volatility'] < 5.0)
        
        confidence = sum(conditions) / len(conditions)
        
        return {
            'direction': 'SHORT',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'relaxed_conditions': relaxed_conditions
        }
    
    def _select_best_signal(self, symbol, long_signal, short_signal, indicators, relaxed_conditions):
        """اختيار أفضل إشارة مع الشروط المناسبة"""
        signals = []
        
        min_confidence = self.relaxed_min_confidence if relaxed_conditions else self.strict_min_confidence
        min_conditions = self.relaxed_min_conditions if relaxed_conditions else self.strict_min_conditions
        
        if (long_signal['confidence'] >= min_confidence and 
            long_signal['conditions_met'] >= min_conditions):
            signals.append(long_signal)
        
        if (short_signal['confidence'] >= min_confidence and 
            short_signal['conditions_met'] >= min_conditions):
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
            'relaxed_conditions': best_signal.get('relaxed_conditions', False)
        }
        
        condition_type = "مخففة" if relaxed_conditions else "مشددة"
        logger.info(f"🎯 إشارة {condition_type} {symbol}: {best_signal['direction']} "
                   f"(ثقة: {best_signal['confidence']:.2%}, "
                   f"شروط: {best_signal['conditions_met']}/{best_signal['total_conditions']})")
        
        return signal_info

class TradeManager:
    """مدير الصفقات بدون حدود للصفقات"""
    
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
        """التحقق من إمكانية التداول على الرمز - بدون حدود"""
        # التحقق فقط من التبريد بعد خسائر متتالية
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
        """عدد الصفقات الحديثة على الرمز - بدون حدود"""
        return 0  # ⬅️ إرجاع 0 دائمًا لأننا لا نريد حدود

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
        condition_type = " 🔓" if signal.get('relaxed_conditions') else " 🔒"
        
        message = (
            f"{direction_emoji} <b>إشارة سكالبينج{condition_type}</b>\n"
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
        'symbols': ["ETHUSDT", "LINKUSDT", "ADAUSDT", "SOLUSDT", "BNBUSDT", "BTCUSDT", 
                   "XRPUSDT", "DOTUSDT", "DOGEUSDT", "AVAXUSDT", "MATICUSDT", "ATOMUSDT"],  # ⬅️ المزيد من الرموز
        'used_balance_per_trade': 5,
        'max_leverage': 4,
        'nominal_trade_size': 24,
        'max_active_trades': 999,  # ⬅️ رقم كبير جداً (بدون حدود عملية)
        'data_interval': '3m',
        'rescan_interval_minutes': 2,
        'target_profit_pct': 0.25,
        'stop_loss_pct': 0.15,
        'max_daily_trades': 999,   # ⬅️ رقم كبير جداً (بدون حدود)
        'cooldown_after_loss': 10,
        
        # إعدادات التوقيت الذكي المحسنة
        'session_settings': {
            'euro_american_overlap': {
                'rescan_interval': 2,
                'confidence_boost': 0.0,
            },
            'american': {
                'rescan_interval': 3,
                'confidence_boost': 0.05,
            },
            'asian': {
                'rescan_interval': 5,
                'confidence_boost': 0.10,
            },
            'low_liquidity': {
                'rescan_interval': 10,
                'confidence_boost': 0.0,
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
        self.signal_generator = AdvancedScalpingSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        self.session_manager = TradingSessionManager()
        
        # الإعدادات الديناميكية
        self.dynamic_settings = {
            'rescan_interval': self.TRADING_SETTINGS['rescan_interval_minutes'],
            'confidence_boost': 0.0,
            'session_name': 'غير محدد',
            'trading_intensity': 'عالية',
            'relaxed_conditions': True  # ⬅️ افتراضيًا شروط مخففة
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
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        self.adjust_settings_for_session()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت السكالبينج المحسن (بدون حدود) بنجاح")

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
        
        # تحديد نوع الشروط
        relaxed_conditions = self.session_manager.are_conditions_relaxed(session_name)
        
        # تحديث الإعدادات الديناميكية
        self.dynamic_settings = {
            'rescan_interval': session_config.get('rescan_interval', 5),
            'confidence_boost': session_config.get('confidence_boost', 0.0),
            'session_name': current_session['name'],
            'trading_intensity': self.session_manager.get_trading_intensity(session_name),
            'relaxed_conditions': relaxed_conditions
        }
        
        condition_type = "مخففة" if relaxed_conditions else "مشددة"
        logger.info(f"🎯 جلسة التداول: {current_session['name']} - شدة: {self.dynamic_settings['trading_intensity']} - الشروط: {condition_type}")

    def should_skip_trading(self):
        """التحقق إذا كان يجب تخطي التداول في الجلسة الحالية"""
        # ⬅️ لا تخطي أي جلسة، التداول في جميع الجلسات
        return False

    def get_session_enhanced_confidence(self, original_confidence):
        """تعزيز ثقة الإشارة بناءً على الجلسة"""
        boosted_confidence = original_confidence + self.dynamic_settings['confidence_boost']
        return min(boosted_confidence, 0.95)

    def can_open_trade(self, symbol, direction):
        """التحقق من إمكانية فتح صفقة سكالبينج - بدون حدود"""
        reasons = []
        
        # التحقق فقط من الرصيد المتاح
        available_balance = self.real_time_balance['available_balance']
        if available_balance < self.TRADING_SETTINGS['used_balance_per_trade']:
            reasons.append("رصيد غير كافي")
        
        # التحقق من وجود صفقة نشطة على الرمز (يمكن إزالته إذا أردت تداول متعدد على نفس الرمز)
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append("صفقة نشطة على الرمز")
        
        # التحقق من نظام التبريد للرمز فقط
        can_trade_symbol, cooldown_reason = self.trade_manager.can_trade_symbol(symbol, self.dynamic_settings['session_name'])
        if not can_trade_symbol:
            reasons.append(cooldown_reason)
        
        # ⬅️ إزالة جميع الحدود الأخرى
        
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
            schedule.every(1).hours.do(self.send_heartbeat)
            schedule.every(4).hours.do(self.send_session_report)

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
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(symbol, f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                if pnl_pct <= -self.TRADING_SETTINGS['stop_loss_pct']:
                    self.close_trade(symbol, f"وقف الخسارة {pnl_pct:.2f}%")
                    return
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(symbol, f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
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
                condition_type = "مخففة" if info['relaxed_conditions'] else "مشددة"
                schedule_text += f"\n• {info['name']}: {info['time_damascus']} ({info['intensity']}) - الشروط: {condition_type}"
            
            message = (
                "⚡ <b>بدء تشغيل بوت السكالبينج المحسن (بدون حدود)</b>\n"
                f"<b>المميزات الجديدة:</b>\n"
                f"• التداول على جميع الرموز في جميع الجلسات ✅\n"
                f"• لا حدود للصفقات النشطة ✅\n"
                f"• لا حدود يومية للصفقات ✅\n"
                f"• شروط مخففة أثناء الجلسات النشطة 🔓\n"
                f"• شروط مشددة خارج أوقات الجلسات 🔒\n"
                f"<b>جدول الجلسات (توقيت دمشق):</b>{schedule_text}\n"
                f"الرموز المدعومة: {len(self.TRADING_SETTINGS['symbols']} رمز\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الوقت دمشق: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.notifier.send_message(message)

    # ... (بقية الدوال تبقى كما هي مع تعديلات بسيطة في الرسائل)

    def scan_market(self):
        """مسح السوق للعثور على فرص السكالبينج - جميع الرموز"""
        logger.info("🔍 بدء مسح السوق للسكالبينج المحسن (جميع الرموز)...")
        
        opportunities = []
        current_session = self.session_manager.get_current_session()
        session_name = [k for k, v in self.session_manager.sessions.items() if v['active']][0]
        relaxed_conditions = self.session_manager.are_conditions_relaxed(session_name)
        
        for symbol in self.TRADING_SETTINGS['symbols']:
            try:
                # تخطي الرموز ذات الصفقات النشطة (يمكن إزالته إذا أردت)
                if self.trade_manager.is_symbol_trading(symbol):
                    continue
                
                data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'])
                if data is None or len(data) < 50:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                # ⬅️ استخدام الشروط المخففة أو المشددة حسب الجلسة
                signal = self.signal_generator.generate_signal(symbol, data, current_price, relaxed_conditions)
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
        
        condition_type = "مخففة" if relaxed_conditions else "مشددة"
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة سكالبينج في جلسة {self.dynamic_settings['session_name']} (شروط {condition_type})")
        return opportunities

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول للسكالبينج مع مراعاة الجلسة"""
        try:
            self.adjust_settings_for_session()
            
            # ⬅️ لا تخطي أي جلسة
            start_time = time.time()
            opportunities = self.scan_market()
            
            executed_trades = 0
            
            for signal in opportunities:
                if self.execute_trade(signal):
                    executed_trades += 1
                    time.sleep(1)  # فاصل بين الصفقات
            
            elapsed_time = time.time() - start_time
            wait_time = (self.dynamic_settings['rescan_interval'] * 60) - elapsed_time
            
            if wait_time > 0:
                condition_type = "مخففة" if self.dynamic_settings['relaxed_conditions'] else "مشددة"
                logger.info(f"⏳ انتظار {wait_time:.1f} ثانية للدورة القادمة في جلسة {self.dynamic_settings['session_name']} (شروط {condition_type})")
                time.sleep(wait_time)
            else:
                logger.info(f"⚡ بدء الدورة التالية فوراً في جلسة {self.dynamic_settings['session_name']}")
            
            logger.info(f"✅ اكتملت دورة السكالبينج في جلسة {self.dynamic_settings['session_name']} - تم تنفيذ {executed_trades} صفقة")
            
        except Exception as e:
            logger.error(f"❌ خطأ في دورة التداول: {e}")
            time.sleep(60)

    # ... (بقية الدوال تبقى كما هي)

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
                'relaxed_conditions': self.dynamic_settings['relaxed_conditions'],
                'unlimited_trading': True  # ⬅️ إشارة إلى عدم وجود حدود
            },
            'schedule': session_schedule,
            'time_info': {
                'utc_time': datetime.utcnow().strftime('%H:%M UTC'),
                'damascus_time': datetime.now(damascus_tz).strftime('%H:%M دمشق')
            }
        }

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت السكالبينج المحسن (بدون حدود)...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت السكالبينج المحسن (بدون حدود)</b>\n"
                f"المميزات:\n"
                f"• التداول على جميع الرموز ✅\n"
                f"• لا حدود للصفقات ✅\n"
                f"• شروط مخففة في الجلسات النشطة 🔓\n"
                f"• شروط مشددة خارج الجلسات 🔒\n"
                f"• نظام التبريد: نشط ⏰\n"
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
