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
                'symbols_focus': ['BTCUSDT'],  # تركيز على BTC فقط
                'active': False,
                'performance_multiplier': 0.6,
                'max_trades_per_hour': 2
            },
            'euro_american_overlap': {
                'name': 'تداخل أوروبا-أمريكا (الأفضل)',
                'start_hour_utc': 13,
                'end_hour_utc': 17,
                'symbols_focus': ['BTCUSDT'],  # تركيز على BTC فقط
                'active': False,
                'performance_multiplier': 1.0,
                'max_trades_per_hour': 4
            },
            'american': {
                'name': 'الجلسة الأمريكية',
                'start_hour_utc': 13,
                'end_hour_utc': 21,
                'symbols_focus': ['BTCUSDT'],  # تركيز على BTC فقط
                'active': False,
                'performance_multiplier': 0.8,
                'max_trades_per_hour': 3
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

class BreakoutSignalGenerator:
    """مولد إشارات الاختراق بناءً على استراتيجية اختراق النطاق"""
    
    def __init__(self):
        self.min_confidence = 0.75
        self.breakout_buffer = 0.001  # 0.1% كما في الاستراتيجية
        self.max_trading_hours = 6    # 6 ساعات كحد أقصى كما في الاستراتيجية
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارة اختراق بناءً على استراتيجية النطاق"""
        try:
            if len(data) < 100:  # نحتاج بيانات أكثر لتحليل النطاق
                return None
            
            # تحليل النطاق على الإطار الزمني 1 ساعة (48 شمعة لـ 30 دقيقة)
            range_data = self._get_range_analysis_data(data)
            if range_data is None or len(range_data) < 20:
                return None
            
            # تحديد مستويات الدعم والمقاومة
            support, resistance = self._calculate_support_resistance(range_data)
            if support is None or resistance is None:
                return None
            
            # حساب عرض النطاق
            range_width = (resistance - support) / support * 100
            
            # تحليل الاختراق على الإطار الزمني 5-15 دقيقة
            breakout_analysis = self._analyze_breakout(data, current_price, support, resistance)
            
            if breakout_analysis['signal']:
                signal_info = {
                    'symbol': symbol,
                    'direction': breakout_analysis['direction'],
                    'confidence': breakout_analysis['confidence'],
                    'conditions_met': breakout_analysis['conditions_met'],
                    'total_conditions': breakout_analysis['total_conditions'],
                    'support': support,
                    'resistance': resistance,
                    'range_width_pct': range_width,
                    'current_price': current_price,
                    'indicators': {
                        'support': support,
                        'resistance': resistance,
                        'range_width_pct': range_width,
                        'volume_ratio': breakout_analysis.get('volume_ratio', 1),
                        'breakout_strength': breakout_analysis.get('breakout_strength', 0)
                    },
                    'timestamp': datetime.now(damascus_tz),
                    'strategy': 'BREAKOUT'
                }
                
                logger.info(f"🎯 إشارة اختراق {symbol}: {breakout_analysis['direction']} "
                           f"(ثقة: {breakout_analysis['confidence']:.2%}, "
                           f"شروط: {breakout_analysis['conditions_met']}/{breakout_analysis['total_conditions']})")
                
                return signal_info
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد إشارة الاختراق لـ {symbol}: {e}")
            return None
    
    def _get_range_analysis_data(self, data):
        """الحصول على البيانات لتحليل النطاق (4-6 ساعات)"""
        try:
            # استخدام آخر 48 شمعة (24 ساعة بفاصل 30 دقيقة)
            if len(data) >= 48:
                return data.tail(48)
            else:
                return data
        except Exception as e:
            logger.error(f"❌ خطأ في تحضير بيانات النطاق: {e}")
            return None
    
    def _calculate_support_resistance(self, data):
        """حساب مستويات الدعم والمقاومة"""
        try:
            highs = data['high'].values
            lows = data['low'].values
            
            # استخدام طريقة بسيطة لتحديد القمم والقيعان
            resistance_level = np.max(highs[-24:])  # آخر 12 ساعة
            support_level = np.min(lows[-24:])      # آخر 12 ساعة
            
            # التأكد من وجود نطاق واضح
            if resistance_level <= support_level * 1.005:  # نطاق صغير جداً
                return None, None
            
            return support_level, resistance_level
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب الدعم والمقاومة: {e}")
            return None, None
    
    def _analyze_breakout(self, data, current_price, support, resistance):
        """تحليل إشارات الاختراق"""
        try:
            # استخدام آخر 20 شمعة (5 دقائق) للتحليل التفصيلي
            recent_data = data.tail(20)
            
            conditions_met = 0
            total_conditions = 4
            
            # 1. تحقق من اختراق مستوى المقاومة أو الدعم
            resistance_break = current_price > resistance * (1 + self.breakout_buffer)
            support_break = current_price < support * (1 - self.breakout_buffer)
            
            if not (resistance_break or support_break):
                return {'signal': False, 'confidence': 0}
            
            direction = 'LONG' if resistance_break else 'SHORT'
            
            # 2. تحليل الحجم عند نقطة الاختراق
            volume_condition = self._check_volume_breakout(recent_data)
            if volume_condition:
                conditions_met += 1
            
            # 3. تأكيد الاختراق بثلاث شموع متتالية في اتجاه الاختراق
            confirmation_condition = self._check_breakout_confirmation(recent_data, direction, 
                                                                      support if direction == 'SHORT' else resistance)
            if confirmation_condition:
                conditions_met += 1
            
            # 4. قوة الاختراق (المسافة من مستوى الدعم/المقاومة)
            strength_condition = self._check_breakout_strength(current_price, support, resistance, direction)
            if strength_condition:
                conditions_met += 1
            
            # 5. حالة النطاق (يجب أن يكون واضحاً)
            range_condition = (resistance - support) / support > 0.005  # نطاق لا يقل عن 0.5%
            if range_condition:
                conditions_met += 1
            
            confidence = conditions_met / total_conditions
            
            return {
                'signal': conditions_met >= 3,  # 3 من أصل 4 شروط
                'direction': direction,
                'confidence': confidence,
                'conditions_met': conditions_met,
                'total_conditions': total_conditions,
                'volume_ratio': self._get_volume_ratio(recent_data),
                'breakout_strength': self._calculate_breakout_strength(current_price, support, resistance, direction)
            }
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل الاختراق: {e}")
            return {'signal': False, 'confidence': 0}
    
    def _check_volume_breakout(self, recent_data):
        """التحقق من زيادة الحجم عند نقطة الاختراق"""
        try:
            if len(recent_data) < 10:
                return False
            
            current_volume = recent_data['volume'].iloc[-1]
            avg_volume = recent_data['volume'].tail(10).mean()
            
            return current_volume > avg_volume * 1.2  # زيادة 20% في الحجم
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل الحجم: {e}")
            return False
    
    def _check_breakout_confirmation(self, recent_data, direction, level):
        """تأكيد الاختراق بثلاث شموع متتالية"""
        try:
            if len(recent_data) < 4:
                return False
            
            # التحقق من آخر 3 شموع
            recent_candles = recent_data.tail(4)  # الشمعة الحالية + 3 سابقة
            
            if direction == 'LONG':
                # تأكيد الصعود: الشموع تغلق فوق مستوى المقاومة
                confirmations = 0
                for i in range(1, 4):  # الشموع 1، 2، 3 (بدون الحالية)
                    if recent_candles['close'].iloc[-i] > level:
                        confirmations += 1
                return confirmations >= 2  # شمعتين من أصل 3
            else:
                # تأكيد الهبوط: الشموع تغلق تحت مستوى الدعم
                confirmations = 0
                for i in range(1, 4):
                    if recent_candles['close'].iloc[-i] < level:
                        confirmations += 1
                return confirmations >= 2
                
        except Exception as e:
            logger.error(f"❌ خطأ في تأكيد الاختراق: {e}")
            return False
    
    def _check_breakout_strength(self, current_price, support, resistance, direction):
        """التحقق من قوة الاختراق"""
        try:
            if direction == 'LONG':
                distance = (current_price - resistance) / resistance * 100
                return distance > 0.05  # اختراق بأكثر من 0.05%
            else:
                distance = (support - current_price) / support * 100
                return distance > 0.05
        except Exception as e:
            logger.error(f"❌ خطأ في حساب قوة الاختراق: {e}")
            return False
    
    def _get_volume_ratio(self, recent_data):
        """حساب نسبة الحجم"""
        try:
            if len(recent_data) < 10:
                return 1.0
            
            current_volume = recent_data['volume'].iloc[-1]
            avg_volume = recent_data['volume'].tail(10).mean()
            
            return current_volume / avg_volume if avg_volume > 0 else 1.0
        except Exception as e:
            return 1.0
    
    def _calculate_breakout_strength(self, current_price, support, resistance, direction):
        """حساب قوة الاختراق"""
        try:
            if direction == 'LONG':
                return (current_price - resistance) / resistance * 100
            else:
                return (support - current_price) / support * 100
        except Exception as e:
            return 0.0

class TradeManager:
    """مدير الصفقات مع تحسينات التبريد"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.trade_history = []
        self.symbol_cooldown = {}  # نظام التبريد للرموز
        self.session_cooldown = {} # نظام التبريد للجلسات
    
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
        """إرسال إشعار صفقة اختراق"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        
        message = (
            f"{direction_emoji} <b>إشارة اختراق النطاق - BTC</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"السعر: ${current_price:.2f}\n"
            f"المقاومة: ${signal['resistance']:.2f}\n"
            f"الدعم: ${signal['support']:.2f}\n"
            f"عرض النطاق: {signal['range_width_pct']:.2f}%\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message, 'trade_signal')

class ScalpingTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbols': ["BTCUSDT"],  # BTC فقط
        'used_balance_per_trade': 5,
        'max_leverage': 5,
        'nominal_trade_size': 25,
        'max_active_trades': 1,
        'data_interval': '15m',  # تغيير إلى 15 دقيقة لاستراتيجية الاختراق
        'range_analysis_interval': '30m',  # إطار زمني إضافي لتحليل النطاق
        'rescan_interval_minutes': 5,  # فحص كل 5 دقائق
        'min_signal_confidence': 0.75,
        'target_profit_multiplier': 2.0,  # ضعف عرض النطاق كما في الاستراتيجية
        'stop_loss_buffer': 0.001,  # داخل النطاق
        'max_trade_hours': 6,  # 6 ساعات كحد أقصى
        'max_daily_trades': 15,  # تقليل عدد الصفقات اليومية لـ BTC
        'cooldown_after_loss': 20,
        
        # إعدادات التوقيت الذكي المحسنة
        'session_settings': {
            'euro_american_overlap': {
                'rescan_interval': 3,
                'max_trades_per_cycle': 1,
                'confidence_boost': 0.05,
                'max_trades_per_symbol_per_hour': 2
            },
            'american': {
                'rescan_interval': 4,
                'max_trades_per_cycle': 1,
                'confidence_boost': 0.03,
                'max_trades_per_symbol_per_hour': 2
            },
            'asian': {
                'rescan_interval': 6,
                'max_trades_per_cycle': 1,
                'confidence_boost': 0.08,
                'max_trades_per_symbol_per_hour': 1
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

        # تهيئة مكونات استراتيجية الاختراق
        self.signal_generator = BreakoutSignalGenerator()  # استخدام مولد إشارات الاختراق
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
        logger.info("✅ تم تهيئة بوت استراتيجية الاختراق لـ BTC بنجاح")

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
        """التحقق من إمكانية فتح صفقة اختراق مع القيود المحسنة"""
        reasons = []
        
        # التحقق من الحد الأقصى للصفقات النشطة (صفقة واحدة فقط)
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("يوجد صفقة نشطة بالفعل")
        
        # التحقق من وجود صفقة نشطة على الرمز
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append("صفقة نشطة على الرمز")
        
        # التحقق من الرصيد المتاح
        available_balance = self.real_time_balance['available_balance']
        if available_balance < self.TRADING_SETTINGS['used_balance_per_trade']:
            reasons.append("رصيد غير كافي")
        
        # التحقق من الحد اليومي للصفقات
        if self.performance_stats['daily_trades_count'] >= self.TRADING_SETTINGS['max_daily_trades']:
            reasons.append("تجاوز الحد اليومي للصفقات")
        
        # التحقق من نظام التبريد للرمز
        can_trade, cooldown_reason = self.trade_manager.can_trade_symbol(symbol, self.dynamic_settings['session_name'])
        if not can_trade:
            reasons.append(cooldown_reason)
        
        # التحقق من الحد الأقصى للصفقات في الساعة
        recent_trades = self.trade_manager.get_recent_trades_count(symbol, minutes=60)
        if recent_trades >= self.dynamic_settings['max_trades_per_symbol_per_hour']:
            reasons.append("تجاوز الحد الأقصى للصفقات في الساعة")
        
        # التحقق من السيولة والجلسة
        if self.should_skip_trading():
            reasons.append("تخطي التداول في الجلسة الحالية")
        
        if reasons:
            logger.info(f"⏸️ تخطي {symbol}: {'، '.join(reasons)}")
            return False, reasons
        
        return True, []

    def calculate_trade_size(self, symbol, direction, confidence):
        """حساب حجم صفقة الاختراق"""
        try:
            # الحجم الأساسي بناءً على الرصيد
            base_size = self.TRADING_SETTINGS['nominal_trade_size']
            
            # تعديل الحجم بناءً على الثقة
            confidence_multiplier = 0.5 + (confidence * 0.5)  # 0.75 إلى 1.0
            adjusted_size = base_size * confidence_multiplier
            
            # الحد الأقصى بناءً على الرصيد المتاح
            max_size = self.real_time_balance['available_balance'] * 0.8
            
            final_size = min(adjusted_size, max_size)
            
            logger.info(f"📊 حجم الصفقة لـ {symbol}: ${final_size:.2f} (ثقة: {confidence:.2%})")
            return final_size
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم الصفقة: {e}")
            return self.TRADING_SETTINGS['nominal_trade_size']

    def calculate_take_profit_stop_loss(self, entry_price, direction, support, resistance, range_width_pct):
        """حساب مستويات جني الأرباح ووقف الخسارة بناءً على استراتيجية الاختراق"""
        try:
            if direction == 'LONG':
                # جني الأرباح: ضعف عرض النطاق فوق المقاومة
                take_profit = entry_price + (resistance - support) * self.TRADING_SETTINGS['target_profit_multiplier']
                
                # وقف الخسارة: داخل النطاق (أسفل المقاومة)
                stop_loss = resistance * (1 - self.TRADING_SETTINGS['stop_loss_buffer'])
                
            else:  # SHORT
                # جني الأرباح: ضعف عرض النطاق تحت الدعم
                take_profit = entry_price - (resistance - support) * self.TRADING_SETTINGS['target_profit_multiplier']
                
                # وقف الخسارة: داخل النطاق (فوق الدعم)
                stop_loss = support * (1 + self.TRADING_SETTINGS['stop_loss_buffer'])
            
            # التأكد من أن وقف الخسارة ليس قريباً جداً
            min_sl_distance = entry_price * 0.001  # 0.1% كحد أدنى
            if direction == 'LONG' and (entry_price - stop_loss) < min_sl_distance:
                stop_loss = entry_price - min_sl_distance
            elif direction == 'SHORT' and (stop_loss - entry_price) < min_sl_distance:
                stop_loss = entry_price + min_sl_distance
            
            logger.info(f"🎯 مستويات {direction}: الدخول ${entry_price:.2f}, جني ${take_profit:.2f}, وقف ${stop_loss:.2f}")
            
            return take_profit, stop_loss
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب مستويات جني الأرباح ووقف الخسارة: {e}")
            # القيم الافتراضية في حالة الخطأ
            if direction == 'LONG':
                return entry_price * 1.01, entry_price * 0.995
            else:
                return entry_price * 0.99, entry_price * 1.005

    def execute_trade(self, symbol, signal):
        """تنفيذ صفقة اختراق"""
        try:
            direction = signal['direction']
            confidence = signal['confidence']
            
            # التحقق من إمكانية فتح الصفقة
            can_open, reasons = self.can_open_trade(symbol, direction)
            if not can_open:
                return False
            
            # الحصول على السعر الحالي
            current_price = signal['current_price']
            
            # حساب حجم الصفقة
            trade_size = self.calculate_trade_size(symbol, direction, confidence)
            
            # حساب مستويات جني الأرباح ووقف الخسارة
            take_profit, stop_loss = self.calculate_take_profit_stop_loss(
                current_price, direction, 
                signal['support'], signal['resistance'],
                signal['range_width_pct']
            )
            
            # إعداد أمر السوق
            side = self.client.SIDE_BUY if direction == 'LONG' else self.client.SIDE_SELL
            quantity = trade_size / current_price
            
            # تنفيذ الصفقة
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=round(quantity, 3)
            )
            
            # تسجيل الصفقة
            trade_data = {
                'symbol': symbol,
                'direction': direction,
                'quantity': quantity,
                'entry_price': current_price,
                'take_profit': take_profit,
                'stop_loss': stop_loss,
                'timestamp': datetime.now(damascus_tz),
                'status': 'open',
                'order_id': order['orderId'],
                'confidence': confidence,
                'strategy': 'BREAKOUT',
                'support': signal['support'],
                'resistance': signal['resistance'],
                'range_width_pct': signal['range_width_pct']
            }
            
            self.trade_manager.add_trade(symbol, trade_data)
            self.performance_stats['trades_opened'] += 1
            self.performance_stats['daily_trades_count'] += 1
            
            # إرسال إشعار
            self.notifier.send_trade_alert(symbol, signal, current_price)
            
            logger.info(f"✅ تم فتح صفقة {direction} على {symbol} - السعر: ${current_price:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            return False

    def monitor_and_close_trades(self):
        """مراقبة وإغلاق صفقات الاختراق"""
        try:
            closed_trades = []
            
            for symbol, trade in list(self.trade_manager.get_all_trades().items()):
                if trade['status'] != 'open':
                    continue
                
                # الحصول على السعر الحالي
                current_price = self.get_current_price(symbol)
                if current_price is None:
                    continue
                
                direction = trade['direction']
                entry_price = trade['entry_price']
                take_profit = trade['take_profit']
                stop_loss = trade['stop_loss']
                
                # التحقق من جني الأرباح
                if (direction == 'LONG' and current_price >= take_profit) or \
                   (direction == 'SHORT' and current_price <= take_profit):
                    self.close_trade(symbol, 'TP', current_price)
                    closed_trades.append((symbol, 'WIN'))
                
                # التحقق من وقف الخسارة
                elif (direction == 'LONG' and current_price <= stop_loss) or \
                     (direction == 'SHORT' and current_price >= stop_loss):
                    self.close_trade(symbol, 'SL', current_price)
                    closed_trades.append((symbol, 'LOSS'))
                
                # التحقق من انتهاء الوقت (6 ساعات كحد أقصى)
                elif (datetime.now(damascus_tz) - trade['timestamp']).total_seconds() >= self.TRADING_SETTINGS['max_trade_hours'] * 3600:
                    self.close_trade(symbol, 'TIME', current_price)
                    closed_trades.append((symbol, 'TIME'))
            
            return closed_trades
            
        except Exception as e:
            logger.error(f"❌ خطأ في مراقبة الصفقات: {e}")
            return []

    def close_trade(self, symbol, close_reason, current_price):
        """إغلاق صفقة الاختراق"""
        try:
            trade = self.trade_manager.get_trade(symbol)
            if not trade:
                return False
            
            # حساب الربح/الخسارة
            direction = trade['direction']
            entry_price = trade['entry_price']
            
            if direction == 'LONG':
                pnl_percent = (current_price - entry_price) / entry_price * 100
            else:
                pnl_percent = (entry_price - current_price) / entry_price * 100
            
            # إغلاق المركز
            side = self.client.SIDE_SELL if direction == 'LONG' else self.client.SIDE_BUY
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=round(trade['quantity'], 3)
            )
            
            # تحديث الإحصائيات
            self.performance_stats['trades_closed'] += 1
            
            if close_reason == 'TP':
                self.performance_stats['winning_trades'] += 1
                self.performance_stats['consecutive_wins'] += 1
                self.performance_stats['consecutive_losses'] = 0
                self.performance_stats['total_pnl'] += pnl_percent
            else:
                self.performance_stats['losing_trades'] += 1
                self.performance_stats['consecutive_losses'] += 1
                self.performance_stats['consecutive_wins'] = 0
                self.performance_stats['total_pnl'] -= abs(pnl_percent)
                
                # إضافة تبريد بعد الخسارة
                if close_reason == 'SL':
                    self.trade_manager.add_symbol_cooldown(symbol, self.TRADING_SETTINGS['cooldown_after_loss'])
            
            # إرسال إشعار الإغلاق
            reason_emoji = {
                'TP': '💰', 'SL': '🛑', 'TIME': '⏰'
            }.get(close_reason, '📄')
            
            message = (
                f"{reason_emoji} <b>إغلاق صفقة اختراق BTC</b>\n"
                f"العملة: {symbol}\n"
                f"الاتجاه: {direction}\n"
                f"سبب الإغلاق: {close_reason}\n"
                f"سعر الدخول: ${entry_price:.2f}\n"
                f"سعر الإغلاق: ${current_price:.2f}\n"
                f"الربح/الخسارة: {pnl_percent:+.2f}%\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            self.notifier.send_message(message)
            
            # إزالة الصفقة من المدير
            self.trade_manager.remove_trade(symbol)
            
            logger.info(f"📄 تم إغلاق {symbol} - السبب: {close_reason} - النتيجة: {pnl_percent:+.2f}%")
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {symbol}: {e}")
            return False

    def get_current_price(self, symbol):
        """الحصول على السعر الحالي"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في جلب السعر لـ {symbol}: {e}")
            return None

    def get_historical_data(self, symbol, interval, limit=100):
        """جلب البيانات التاريخية"""
        try:
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # تحويل الأنواع
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.dropna()
            
            return df
            
        except Exception as e:
            logger.error(f"❌ خطأ في جلب البيانات لـ {symbol}: {e}")
            return None

    def scan_for_breakout_signals(self):
        """مسح الأسواق للبحث عن إشارات اختراق"""
        try:
            signals_found = []
            
            for symbol in self.TRADING_SETTINGS['symbols']:  # سيكون BTCUSDT فقط
                # التحقق من الجلسة الحالية
                current_session = self.session_manager.get_current_session()
                if not self.session_manager.should_trade_symbol(symbol, current_session):
                    continue
                
                # جلب البيانات للإطار الزمني 15 دقيقة
                data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'], 100)
                if data is None or len(data) < 20:
                    continue
                
                # الحصول على السعر الحالي
                current_price = self.get_current_price(symbol)
                if current_price is None:
                    continue
                
                # توليد إشارة الاختراق
                signal = self.signal_generator.generate_signal(symbol, data, current_price)
                if signal and signal['confidence'] >= self.TRADING_SETTINGS['min_signal_confidence']:
                    # تعزيز الثقة بناءً على الجلسة
                    enhanced_confidence = self.get_session_enhanced_confidence(signal['confidence'])
                    signal['confidence'] = enhanced_confidence
                    
                    signals_found.append(signal)
            
            return signals_found
            
        except Exception as e:
            logger.error(f"❌ خطأ في مسح إشارات الاختراق: {e}")
            return []

    def trading_cycle(self):
        """دورة التداول الرئيسية لاستراتيجية الاختراق"""
        try:
            logger.info("🔄 بدء دورة تداول استراتيجية الاختراق لـ BTC...")
            
            # تحديث الإعدادات بناءً على الجلسة
            self.adjust_settings_for_session()
            
            # تخطي التداول إذا لزم الأمر
            if self.should_skip_trading():
                return
            
            # تحديث الرصيد
            self.real_time_balance = self.get_real_time_balance()
            
            # مزامنة الصفقات مع المنصة
            self.trade_manager.sync_with_exchange()
            
            # تنظيف فترات التبريد
            self.trade_manager.cleanup_cooldowns()
            
            # مراقبة وإغلاق الصفقات النشطة
            closed_trades = self.monitor_and_close_trades()
            if closed_trades:
                logger.info(f"📊 تم إغلاق {len(closed_trades)} صفقة")
            
            # التحقق من الحد الأقصى للصفقات في الدورة
            if self.trade_manager.get_active_trades_count() >= self.dynamic_settings['max_trades_per_cycle']:
                logger.info("⏸️ الوصول للحد الأقصى للصفقات في الدورة")
                return
            
            # البحث عن إشارات الاختراق
            signals = self.scan_for_breakout_signals()
            
            # تنفيذ أفضل إشارة
            if signals:
                # ترتيب الإشارات حسب الثقة
                signals.sort(key=lambda x: x['confidence'], reverse=True)
                best_signal = signals[0]
                
                # تنفيذ الصفقة
                if self.execute_trade(best_signal['symbol'], best_signal):
                    logger.info(f"✅ تم تنفيذ صفقة اختراق على {best_signal['symbol']}")
                else:
                    logger.info(f"⏸️ لم يتم تنفيذ صفقة {best_signal['symbol']} بسبب القيود")
            else:
                logger.info("🔍 لم يتم العثور على إشارات اختراق مناسبة لـ BTC")
            
            logger.info("✅ اكتملت دورة تداول استراتيجية الاختراق لـ BTC")
            
        except Exception as e:
            logger.error(f"❌ خطأ في دورة التداول: {e}")

    def start_services(self):
        """بدء خدمات البوت"""
        try:
            # جدولة دورة التداول
            schedule.every(self.dynamic_settings['rescan_interval']).minutes.do(self.trading_cycle)
            
            # جدولة مهام الصيانة
            schedule.every(1).hours.do(self.maintenance_tasks)
            schedule.every(1).days.at("00:00").do(self.reset_daily_stats)
            
            # بدء خيط الجدولة
            def run_scheduler():
                while True:
                    schedule.run_pending()
                    time.sleep(1)
            
            scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
            scheduler_thread.start()
            
            logger.info("✅ بدء خدمات البوت المخصص لـ BTC")
            
        except Exception as e:
            logger.error(f"❌ خطأ في بدء خدمات البوت: {e}")

    def maintenance_tasks(self):
        """مهام الصيانة الدورية"""
        try:
            # تحديث الرصيد
            self.real_time_balance = self.get_real_time_balance()
            
            # مزامنة الصفقات
            self.trade_manager.sync_with_exchange()
            
            # إعادة تعيين عداد الصفقات بالساعة
            current_time = datetime.now(damascus_tz)
            if (current_time - self.performance_stats['last_hour_reset']).total_seconds() >= 3600:
                self.performance_stats['hourly_trade_count'] = 0
                self.performance_stats['last_hour_reset'] = current_time
            
            logger.info("🔧 اكتملت مهام الصيانة لـ BTC")
            
        except Exception as e:
            logger.error(f"❌ خطأ في مهام الصيانة: {e}")

    def reset_daily_stats(self):
        """إعادة تعيين الإحصائيات اليومية"""
        self.performance_stats['daily_trades_count'] = 0
        logger.info("🔄 إعادة تعيين الإحصائيات اليومية لـ BTC")

    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        message = (
            "🚀 <b>بدء تشغيل بوت استراتيجية الاختراق - BTC فقط</b>\n\n"
            f"💰 الرصيد: ${self.real_time_balance['total_balance']:.2f}\n"
            f"🎯 العملة: BTCUSDT\n"
            f"📊 الاستراتيجية: اختراق النطاق\n"
            f"🎯 هدف الربح: ضعف عرض النطاق\n"
            f"🛑 وقف الخسارة: داخل النطاق\n"
            f"⏰ الحد الزمني: 6 ساعات\n"
            f"⏰ توقيت دمشق: {datetime.now(damascus_tz).strftime('%H:%M:%S')}\n\n"
            "<i>البوت جاهز للتداول الآلي على BTC</i>"
        )
        self.notifier.send_message(message)

    def get_active_trades_details(self):
        """الحصول على تفاصيل الصفقات النشطة"""
        active_trades = self.trade_manager.get_all_trades()
        details = []
        
        for symbol, trade in active_trades.items():
            current_price = self.get_current_price(symbol)
            if current_price:
                if trade['direction'] == 'LONG':
                    pnl_percent = (current_price - trade['entry_price']) / trade['entry_price'] * 100
                else:
                    pnl_percent = (trade['entry_price'] - current_price) / trade['entry_price'] * 100
            else:
                pnl_percent = 0.0
            
            details.append({
                'symbol': symbol,
                'direction': trade['direction'],
                'entry_price': trade['entry_price'],
                'current_price': current_price,
                'pnl_percent': pnl_percent,
                'quantity': trade['quantity'],
                'timestamp': trade['timestamp'].isoformat(),
                'take_profit': trade.get('take_profit', 0),
                'stop_loss': trade.get('stop_loss', 0),
                'confidence': trade.get('confidence', 0),
                'strategy': trade.get('strategy', 'BREAKOUT')
            })
        
        return details

    def get_market_analysis(self, symbol):
        """تحليل السوق للرمز المحدد"""
        try:
            data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'], 100)
            if data is None:
                return {'error': 'لا توجد بيانات'}
            
            current_price = self.get_current_price(symbol)
            if current_price is None:
                return {'error': 'لا يمكن جلب السعر الحالي'}
            
            # توليد إشارة تحليلية
            signal = self.signal_generator.generate_signal(symbol, data, current_price)
            
            analysis = {
                'symbol': symbol,
                'current_price': current_price,
                'signal_strength': signal['confidence'] if signal else 0,
                'signal_direction': signal['direction'] if signal else 'NONE',
                'support': signal['support'] if signal else 0,
                'resistance': signal['resistance'] if signal else 0,
                'range_width_pct': signal['range_width_pct'] if signal else 0,
                'conditions_met': signal['conditions_met'] if signal else 0,
                'total_conditions': signal['total_conditions'] if signal else 0,
                'volume_ratio': signal['indicators']['volume_ratio'] if signal else 1.0,
                'analysis_time': datetime.now(damascus_tz).isoformat()
            }
            
            return analysis
            
        except Exception as e:
            return {'error': str(e)}

    def get_current_session_info(self):
        """الحصول على معلومات الجلسة الحالية"""
        current_session = self.session_manager.get_current_session()
        session_name = [k for k, v in self.session_manager.sessions.items() if v['active']][0]
        
        return {
            'session_name': current_session['name'],
            'session_type': session_name,
            'trading_intensity': self.dynamic_settings['trading_intensity'],
            'rescan_interval': self.dynamic_settings['rescan_interval'],
            'max_trades_per_cycle': self.dynamic_settings['max_trades_per_cycle'],
            'confidence_boost': self.dynamic_settings['confidence_boost'],
            'damascus_time': datetime.now(damascus_tz).isoformat(),
            'utc_time': datetime.utcnow().isoformat(),
            'session_schedule': self.session_manager.get_session_schedule()
        }

    def get_performance_stats(self):
        """الحصول على إحصائيات الأداء"""
        total_trades = self.performance_stats['trades_opened']
        win_rate = (self.performance_stats['winning_trades'] / total_trades * 100) if total_trades > 0 else 0
        
        return {
            'total_trades_opened': total_trades,
            'total_trades_closed': self.performance_stats['trades_closed'],
            'winning_trades': self.performance_stats['winning_trades'],
            'losing_trades': self.performance_stats['losing_trades'],
            'win_rate_percent': win_rate,
            'total_pnl_percent': self.performance_stats['total_pnl'],
            'daily_trades_count': self.performance_stats['daily_trades_count'],
            'consecutive_wins': self.performance_stats['consecutive_wins'],
            'consecutive_losses': self.performance_stats['consecutive_losses'],
            'active_trades_count': self.trade_manager.get_active_trades_count(),
            'current_balance': self.real_time_balance['total_balance'],
            'available_balance': self.real_time_balance['available_balance'],
            'trading_symbol': 'BTCUSDT'
        }

def main():
    """الدالة الرئيسية"""
    try:
        # بدء تطبيق Flask في خيط منفصل
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        # تهيئة وتشغيل البوت
        bot = ScalpingTradingBot()
        
        # الحفاظ على التشغيل
        while True:
            time.sleep(60)
            
    except KeyboardInterrupt:
        logger.info("⏹️ إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع: {e}")
        raise

if __name__ == "__main__":
    main()
