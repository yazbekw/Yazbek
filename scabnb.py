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
                'symbols_focus': ['BNBUSDT', 'ADAUSDT'],  # تركيز على BNB في الجلسة الآسيوية
                'active': False,
                'performance_multiplier': 0.6,
                'max_trades_per_hour': 2
            },
            'euro_american_overlap': {
                'name': 'تداخل أوروبا-أمريكا (الأفضل)',
                'start_hour_utc': 13,
                'end_hour_utc': 17,
                'symbols_focus': ['ETHUSDT', 'BTCUSDT', 'BNBUSDT'],
                'active': False,
                'performance_multiplier': 1.0,
                'max_trades_per_hour': 4
            },
            'american': {
                'name': 'الجلسة الأمريكية',
                'start_hour_utc': 13,
                'end_hour_utc': 21,
                'symbols_focus': ['ETHUSDT', 'BTCUSDT', 'BNBUSDT'],
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

class SupportResistanceSignalGenerator:
    """مولد إشارات التداول بناءً على ارتداد السعر من مستويات الدعم والمقاومة"""
    
    def __init__(self):
        self.min_confidence = 0.70
        self.min_conditions = 4  # 4 من أصل 6 شروط
    
    def generate_signal(self, symbol, data_1h, data_15m, current_price):
        """توليد إشارة تداول بناءً على مستويات الدعم والمقاومة"""
        try:
            if len(data_1h) < 30 or len(data_15m) < 20:
                return None
            
            # تحديد مستويات الدعم والمقاومة
            support_levels, resistance_levels = self._calculate_support_resistance(data_1h, data_15m)
            
            # تحليل الشموع اليابانية
            candlestick_patterns = self._analyze_candlestick_patterns(data_15m)
            
            # حساب مؤشر RSI
            rsi_14 = self._calculate_rsi(data_15m['close'], 14)
            current_rsi = rsi_14.iloc[-1]
            
            # تحليل الحجم
            volume_analysis = self._analyze_volume(data_15m)
            
            # تحليل الإشارات
            long_signal = self._analyze_long_signal(
                current_price, support_levels, candlestick_patterns, 
                current_rsi, volume_analysis, data_15m
            )
            
            short_signal = self._analyze_short_signal(
                current_price, resistance_levels, candlestick_patterns,
                current_rsi, volume_analysis, data_15m
            )
            
            # اختيار أفضل إشارة
            return self._select_best_signal(symbol, long_signal, short_signal, {
                'support_levels': support_levels,
                'resistance_levels': resistance_levels,
                'current_rsi': current_rsi,
                'volume_ratio': volume_analysis['volume_ratio'],
                'current_price': current_price
            })
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد الإشارة لـ {symbol}: {e}")
            return None
    
    def _calculate_support_resistance(self, data_1h, data_15m):
        """حساب مستويات الدعم والمقاومة"""
        # استخدام الإطار الزمني 1 ساعة للمستويات الرئيسية
        support_levels = self._find_key_levels(data_1h, 'support')
        resistance_levels = self._find_key_levels(data_1h, 'resistance')
        
        # استخدام الإطار الزمني 15 دقيقة للمستويات الثانوية
        support_levels_15m = self._find_key_levels(data_15m, 'support')
        resistance_levels_15m = self._find_key_levels(data_15m, 'resistance')
        
        # دمج المستويات مع إعطاء أولوية للمستويات الرئيسية
        all_support = self._merge_levels(support_levels, support_levels_15m)
        all_resistance = self._merge_levels(resistance_levels, resistance_levels_15m)
        
        return all_support, all_resistance
    
    def _find_key_levels(self, data, level_type='support'):
        """العثور على مستويات الدعم أو المقاومة الرئيسية"""
        prices = data['close'].values
        highs = data['high'].values
        lows = data['low'].values
        
        if level_type == 'support':
            # البحث عن القيعان المحلية
            min_distance = len(prices) // 10  # مسافة دنيا بين القيعان
            min_prominence = np.std(prices) * 0.3  # بروز كافٍ
            
            valleys, properties = find_peaks(-prices, distance=min_distance, prominence=min_prominence)
            levels = [lows[i] for i in valleys]
        else:
            # البحث عن القمم المحلية
            min_distance = len(prices) // 10  # مسافة دنيا بين القمم
            min_prominence = np.std(prices) * 0.3  # بروز كافٍ
            
            peaks, properties = find_peaks(prices, distance=min_distance, prominence=min_prominence)
            levels = [highs[i] for i in peaks]
        
        # تصفية المستويات بناءً على عدد المرات التي تم لمسها
        filtered_levels = []
        for level in levels:
            touch_count = self._count_level_touches(data, level, level_type)
            if touch_count >= 2:  # اشتراط تلامس المستوى مرتين على الأقل
                filtered_levels.append({
                    'price': level,
                    'touch_count': touch_count,
                    'strength': min(touch_count / 3.0, 1.0)  # قوة المستوى من 0 إلى 1
                })
        
        # ترتيب المستويات حسب القوة
        filtered_levels.sort(key=lambda x: x['strength'], reverse=True)
        return filtered_levels[:5]  # إرجاع أقوى 5 مستويات
    
    def _count_level_touches(self, data, level, level_type, tolerance_pct=0.001):
        """عد عدد مرات لمس مستوى الدعم/المقاومة"""
        touches = 0
        tolerance = level * tolerance_pct
        
        for i in range(len(data)):
            high = data['high'].iloc[i]
            low = data['low'].iloc[i]
            
            if level_type == 'support':
                if abs(low - level) <= tolerance or (low <= level and high >= level):
                    touches += 1
            else:
                if abs(high - level) <= tolerance or (low <= level and high >= level):
                    touches += 1
        
        return touches
    
    def _merge_levels(self, primary_levels, secondary_levels, merge_distance_pct=0.002):
        """دمج المستويات المتقاربة"""
        all_levels = primary_levels + secondary_levels
        if not all_levels:
            return []
        
        # ترتيب المستويات حسب السعر
        all_levels.sort(key=lambda x: x['price'])
        
        merged_levels = []
        current_group = [all_levels[0]]
        
        for level in all_levels[1:]:
            last_price = current_group[-1]['price']
            merge_distance = last_price * merge_distance_pct
            
            if abs(level['price'] - last_price) <= merge_distance:
                current_group.append(level)
            else:
                # دمج المجموعة الحالية
                avg_price = np.mean([l['price'] for l in current_group])
                max_touches = max([l['touch_count'] for l in current_group])
                max_strength = max([l['strength'] for l in current_group])
                
                merged_levels.append({
                    'price': avg_price,
                    'touch_count': max_touches,
                    'strength': max_strength
                })
                current_group = [level]
        
        # دمج المجموعة الأخيرة
        if current_group:
            avg_price = np.mean([l['price'] for l in current_group])
            max_touches = max([l['touch_count'] for l in current_group])
            max_strength = max([l['strength'] for l in current_group])
            
            merged_levels.append({
                'price': avg_price,
                'touch_count': max_touches,
                'strength': max_strength
            })
        
        return merged_levels
    
    def _analyze_candlestick_patterns(self, data):
        """تحليل أنماط الشموع اليابانية"""
        if len(data) < 3:
            return {'patterns': [], 'strength': 0}
        
        patterns = []
        current_candle = data.iloc[-1]
        prev_candle = data.iloc[-2]
        prev_prev_candle = data.iloc[-3] if len(data) >= 3 else prev_candle
        
        # المطرقة (Hammer)
        if self._is_hammer(current_candle):
            patterns.append({'name': 'hammer', 'direction': 'bullish', 'strength': 0.7})
        
        # engulfing الصاعد
        if self._is_bullish_engulfing(prev_candle, current_candle):
            patterns.append({'name': 'bullish_engulfing', 'direction': 'bullish', 'strength': 0.8})
        
        # engulfing الهابط
        if self._is_bearish_engulfing(prev_candle, current_candle):
            patterns.append({'name': 'bearish_engulfing', 'direction': 'bearish', 'strength': 0.8})
        
        # النجمة المسائية
        if self._is_evening_star(prev_prev_candle, prev_candle, current_candle):
            patterns.append({'name': 'evening_star', 'direction': 'bearish', 'strength': 0.8})
        
        # الدوجي
        if self._is_doji(current_candle):
            patterns.append({'name': 'doji', 'direction': 'neutral', 'strength': 0.6})
        
        # حساب قوة الأنماط
        total_strength = sum([p['strength'] for p in patterns if p['direction'] in ['bullish', 'bearish']])
        
        return {
            'patterns': patterns,
            'strength': min(total_strength, 1.0)
        }
    
    def _is_hammer(self, candle):
        """التحقق من شمعة المطرقة"""
        body_size = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['open'], candle['close']) - candle['low']
        upper_shadow = candle['high'] - max(candle['open'], candle['close'])
        
        return (lower_shadow >= 2 * body_size and 
                upper_shadow <= body_size * 0.5 and
                body_size > 0)
    
    def _is_bullish_engulfing(self, prev_candle, current_candle):
        """التحقق من engulfing الصاعد"""
        prev_body = prev_candle['close'] - prev_candle['open']
        current_body = current_candle['close'] - current_candle['open']
        
        return (prev_body < 0 and current_body > 0 and
                current_candle['open'] < prev_candle['close'] and
                current_candle['close'] > prev_candle['open'])
    
    def _is_bearish_engulfing(self, prev_candle, current_candle):
        """التحقق من engulfing الهابط"""
        prev_body = prev_candle['close'] - prev_candle['open']
        current_body = current_candle['close'] - current_candle['open']
        
        return (prev_body > 0 and current_body < 0 and
                current_candle['open'] > prev_candle['close'] and
                current_candle['close'] < prev_candle['open'])
    
    def _is_evening_star(self, first, second, third):
        """التحقق من النجمة المسائية"""
        first_bullish = first['close'] > first['open']
        second_small = abs(second['close'] - second['open']) < (first['high'] - first['low']) * 0.3
        third_bearish = third['close'] < third['open']
        
        gap_up = second['low'] > first['high']
        gap_down = third['open'] < second['low']
        
        return first_bullish and second_small and third_bearish and (gap_up or gap_down)
    
    def _is_doji(self, candle):
        """التحقق من شمعة الدوجي"""
        body_size = abs(candle['close'] - candle['open'])
        total_range = candle['high'] - candle['low']
        
        return body_size <= total_range * 0.1 and total_range > 0
    
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
    
    def _analyze_volume(self, data):
        """تحليل الحجم"""
        if len(data) < 20:
            return {'volume_ratio': 1.0, 'trend': 'normal'}
        
        current_volume = data['volume'].iloc[-1]
        avg_volume = data['volume'].rolling(20).mean().iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        
        return {
            'volume_ratio': volume_ratio,
            'trend': 'high' if volume_ratio > 1.2 else 'normal'
        }
    
    def _analyze_long_signal(self, current_price, support_levels, candlestick_patterns, rsi, volume_analysis, data_15m):
        """تحليل إشارة الشراء"""
        conditions = []
        reasons = []
        
        # 1. التحقق من قرب السعر من مستوى دعم قوي
        nearest_support = self._find_nearest_level(current_price, support_levels)
        if nearest_support and nearest_support['strength'] >= 0.6:
            price_diff_pct = abs(current_price - nearest_support['price']) / nearest_support['price'] * 100
            if price_diff_pct <= 0.2:  # ضمن 0.2% من مستوى الدعم
                conditions.append(True)
                reasons.append(f"قرب من دعم قوي (قوة: {nearest_support['strength']:.2f})")
            else:
                conditions.append(False)
        else:
            conditions.append(False)
        
        # 2. تحليل أنماط الشموع الانعكاسية
        bullish_patterns = [p for p in candlestick_patterns['patterns'] if p['direction'] == 'bullish']
        if bullish_patterns:
            conditions.append(True)
            reasons.append(f"نمط شمعي صاعد: {bullish_patterns[0]['name']}")
        else:
            conditions.append(False)
        
        # 3. مؤشر RSI في منطقة التشبع البيعي
        if rsi < 35:
            conditions.append(True)
            reasons.append(f"RSI في التشبع البيعي: {rsi:.1f}")
        else:
            conditions.append(False)
        
        # 4. الحجم أعلى من المتوسط
        if volume_analysis['volume_ratio'] > 1.0:
            conditions.append(True)
            reasons.append(f"حجم مرتفع: {volume_analysis['volume_ratio']:.2f}x")
        else:
            conditions.append(False)
        
        # 5. تأكيد من الشمعة التالية (إذا كانت البيانات كافية)
        if len(data_15m) >= 2:
            prev_close = data_15m['close'].iloc[-2]
            current_close = data_15m['close'].iloc[-1]
            if current_close > prev_close:
                conditions.append(True)
                reasons.append("تأكيد صعود من الشمعة الحالية")
            else:
                conditions.append(False)
        else:
            conditions.append(False)
        
        # 6. تجنب المناطق المتطرفة
        if 20 <= rsi <= 80:
            conditions.append(True)
            reasons.append("RSI في نطاق آمن")
        else:
            conditions.append(False)
        
        confidence = sum(conditions) / len(conditions) if conditions else 0
        
        return {
            'direction': 'LONG',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'reasons': reasons,
            'nearest_level': nearest_support,
            'strategy': 'SUPPORT_RESISTANCE'
        }
    
    def _analyze_short_signal(self, current_price, resistance_levels, candlestick_patterns, rsi, volume_analysis, data_15m):
        """تحليل إشارة البيع"""
        conditions = []
        reasons = []
        
        # 1. التحقق من قرب السعر من مستوى مقاومة قوي
        nearest_resistance = self._find_nearest_level(current_price, resistance_levels)
        if nearest_resistance and nearest_resistance['strength'] >= 0.6:
            price_diff_pct = abs(current_price - nearest_resistance['price']) / nearest_resistance['price'] * 100
            if price_diff_pct <= 0.2:  # ضمن 0.2% من مستوى المقاومة
                conditions.append(True)
                reasons.append(f"قرب من مقاومة قوية (قوة: {nearest_resistance['strength']:.2f})")
            else:
                conditions.append(False)
        else:
            conditions.append(False)
        
        # 2. تحليل أنماط الشموع الانعكاسية
        bearish_patterns = [p for p in candlestick_patterns['patterns'] if p['direction'] == 'bearish']
        if bearish_patterns:
            conditions.append(True)
            reasons.append(f"نمط شمعي هابط: {bearish_patterns[0]['name']}")
        else:
            conditions.append(False)
        
        # 3. مؤشر RSI في منطقة التشبع الشرائي
        if rsi > 65:
            conditions.append(True)
            reasons.append(f"RSI في التشبع الشرائي: {rsi:.1f}")
        else:
            conditions.append(False)
        
        # 4. الحجم أعلى من المتوسط
        if volume_analysis['volume_ratio'] > 1.0:
            conditions.append(True)
            reasons.append(f"حجم مرتفع: {volume_analysis['volume_ratio']:.2f}x")
        else:
            conditions.append(False)
        
        # 5. تأكيد من الشمعة التالية (إذا كانت البيانات كافية)
        if len(data_15m) >= 2:
            prev_close = data_15m['close'].iloc[-2]
            current_close = data_15m['close'].iloc[-1]
            if current_close < prev_close:
                conditions.append(True)
                reasons.append("تأكيد هبوط من الشمعة الحالية")
            else:
                conditions.append(False)
        else:
            conditions.append(False)
        
        # 6. تجنب المناطق المتطرفة
        if 20 <= rsi <= 80:
            conditions.append(True)
            reasons.append("RSI في نطاق آمن")
        else:
            conditions.append(False)
        
        confidence = sum(conditions) / len(conditions) if conditions else 0
        
        return {
            'direction': 'SHORT',
            'confidence': confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'reasons': reasons,
            'nearest_level': nearest_resistance,
            'strategy': 'SUPPORT_RESISTANCE'
        }
    
    def _find_nearest_level(self, price, levels, max_distance_pct=0.5):
        """العثور على أقرب مستوى دعم/مقاومة"""
        if not levels:
            return None
        
        nearest_level = None
        min_distance = float('inf')
        
        for level in levels:
            distance = abs(price - level['price'])
            distance_pct = distance / price * 100
            
            if distance_pct <= max_distance_pct and distance < min_distance:
                min_distance = distance
                nearest_level = level
        
        return nearest_level
    
    def _select_best_signal(self, symbol, long_signal, short_signal, indicators):
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
            'reasons': best_signal['reasons'],
            'nearest_level': best_signal['nearest_level'],
            'indicators': indicators,
            'timestamp': datetime.now(damascus_tz),
            'strategy': best_signal.get('strategy', 'SUPPORT_RESISTANCE')
        }
        
        logger.info(f"🎯 إشارة دعم/مقاومة {symbol}: {best_signal['direction']} "
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
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            return response.status_code == 200
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال إشعار التلغرام: {e}")
            return False
    
    def send_signal(self, signal_info):
        """إرسال إشعار إشارة تداول"""
        symbol = signal_info['symbol']
        direction = signal_info['direction']
        confidence = signal_info['confidence']
        reasons = signal_info['reasons']
        
        emoji = "🟢" if direction == 'LONG' else "🔴"
        
        message = f"""
{emoji} <b>إشارة تداول جديدة</b> {emoji}

<b>الرمز:</b> {symbol}
<b>الاتجاه:</b> {direction}
<b>الثقة:</b> {confidence:.2%}
<b>الشروط المحققة:</b> {signal_info['conditions_met']}/{signal_info['total_conditions']}

<b>الأسباب:</b>
"""
        for reason in reasons:
            message += f"• {reason}\n"
        
        if 'nearest_level' in signal_info and signal_info['nearest_level']:
            level = signal_info['nearest_level']
            message += f"\n<b>المستوى:</b> {level['price']:.4f}"
            message += f"\n<b>قوة المستوى:</b> {level['strength']:.2f}"
        
        message += f"\n\n⏰ {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_message(message)
    
    def send_trade_opened(self, symbol, side, quantity, entry_price, stop_loss, take_profit):
        emoji = "🟢" if side == 'LONG' else "🔴"
        
        message = f"""
{emoji} <b>تم فتح صفقة</b> {emoji}

<b>الرمز:</b> {symbol}
<b>الاتجاه:</b> {side}
<b>الكمية:</b> {quantity}
<b>سعر الدخول:</b> {entry_price:.4f}
<b>وقف الخسارة:</b> {stop_loss:.4f}
<b>جني الأرباح:</b> {take_profit:.4f}

⏰ {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def send_trade_closed(self, symbol, side, quantity, pnl, pnl_percent, reason):
        emoji = "💰" if pnl >= 0 else "💸"
        
        message = f"""
{emoji} <b>تم إغلاق صفقة</b> {emoji}

<b>الرمز:</b> {symbol}
<b>الاتجاه:</b> {side}
<b>الكمية:</b> {quantity}
<b>الربح/الخسارة:</b> {pnl:.4f} ({pnl_percent:+.2f}%)
<b>السبب:</b> {reason}

⏰ {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def send_error(self, error_message):
        message = f"""
🚨 <b>خطأ في البوت</b> 🚨

<b>الرسالة:</b> {error_message}

⏰ {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)
    
    def send_session_info(self, session_info):
        message = f"""
🌍 <b>معلومات الجلسة</b> 🌍

<b>الجلسة:</b> {session_info['name']}
<b>الوقت:</b> {session_info['time_damascus']}
<b>شدة التداول:</b> {session_info['intensity']}
<b>الحد الأقصى للصفقات:</b> {session_info['max_trades_per_hour']}/ساعة

⏰ {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}
"""
        return self.send_message(message)

class ScalpingTradingBot:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        return cls._instance
    
    def __init__(self, api_key, api_secret, telegram_token=None, telegram_chat_id=None):
        if ScalpingTradingBot._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            ScalpingTradingBot._instance = self
            
        self.client = Client(api_key, api_secret)
        self.notifier = TelegramNotifier(telegram_token, telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        self.session_manager = TradingSessionManager()
        self.signal_generator = SupportResistanceSignalGenerator()
        
        # إعدادات التداول
        self.max_active_trades = 2
        self.max_daily_trades = 10
        self.risk_per_trade = 0.02  # 2% من رأس المال
        self.min_volume_usdt = 1000000  # الحد الأدنى لحجم التداول
        
        # تتبع الأداء
        self.daily_trades_count = 0
        self.last_trade_time = None
        self.consecutive_losses = 0
        self.daily_reset_time = None
        
        # رموز التداول
        self.trading_symbols = ["BNBUSDT"]
        
        # إحصائيات
        self.performance_stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0,
            'daily_pnl': 0,
            'best_trade': 0,
            'worst_trade': 0,
            'current_streak': 0
        }
        
        logger.info("🤖 بدء تشغيل بوت التداول باستراتيجية الدعم والمقاومة")
    
    def reset_daily_stats(self):
        """إعادة تعيين الإحصائيات اليومية"""
        current_time = datetime.now(damascus_tz)
        if (self.daily_reset_time is None or 
            current_time.date() > self.daily_reset_time.date()):
            self.daily_trades_count = 0
            self.performance_stats['daily_pnl'] = 0
            self.daily_reset_time = current_time
            logger.info("🔄 تم إعادة تعيين الإحصائيات اليومية")
    
    def get_symbol_info(self, symbol):
        """الحصول على معلومات الرمز"""
        try:
            exchange_info = self.client.futures_exchange_info()
            for s in exchange_info['symbols']:
                if s['symbol'] == symbol:
                    return s
            return None
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على معلومات الرمز {symbol}: {e}")
            return None
    
    def get_current_price(self, symbol):
        """الحصول على السعر الحالي"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر {symbol}: {e}")
            return None
    
    def get_klines_data(self, symbol, interval, limit=100):
        """الحصول على بيانات الشموع"""
        try:
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # تحويل الأنواع
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
            
            return df.dropna()
            
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على بيانات {symbol} {interval}: {e}")
            return None
    
    def calculate_position_size(self, symbol, entry_price, stop_loss_price):
        """حجم المركز بناءً على إدارة رأس المال"""
        try:
            # الحصول على رصيد الحساب
            account_info = self.client.futures_account()
            total_balance = float(account_info['totalWalletBalance'])
            
            if total_balance <= 0:
                logger.error("❌ رصيد المحفظة غير صالح")
                return 0
            
            # حساب المخاطرة
            risk_amount = total_balance * self.risk_per_trade
            
            # حساب المسافة إلى وقف الخسارة
            if entry_price > stop_loss_price:  # LONG
                price_diff = entry_price - stop_loss_price
            else:  # SHORT
                price_diff = stop_loss_price - entry_price
            
            if price_diff <= 0:
                logger.error("❌ فرق السعر غير صالح لوقف الخسارة")
                return 0
            
            # حساب حجم المركز
            position_size = risk_amount / price_diff
            
            # الحصول على معلومات الرمز
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return 0
            
            # البحث عن عوامل التصفية
            lot_size_filter = next(
                (f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'),
                None
            )
            
            if lot_size_filter:
                min_qty = float(lot_size_filter['minQty'])
                step_size = float(lot_size_filter['stepSize'])
                
                # تقريب الحجم ليتناسب مع stepSize
                position_size = max(min_qty, position_size)
                position_size = (position_size // step_size) * step_size
            
            logger.info(f"📊 حجم المركز لـ {symbol}: {position_size:.4f} (رصيد: {total_balance:.2f})")
            return position_size
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return 0
    
    def calculate_stop_loss_take_profit(self, signal_info, current_price):
        """حساب وقف الخسارة وجني الأرباح"""
        direction = signal_info['direction']
        nearest_level = signal_info.get('nearest_level')
        
        if not nearest_level:
            return None, None
        
        level_price = nearest_level['price']
        
        if direction == 'LONG':
            # وقف الخسارة: أسفل مستوى الدعم بـ 0.15%
            stop_loss = level_price * (1 - 0.0015)
            
            # جني الأرباح: مستوى المقاومة المقابل أو 1.5x مسافة وقف الخسارة
            take_profit_1 = level_price * (1 + 0.002)  # الهدف الأول
            take_profit_2 = current_price + 1.5 * (current_price - stop_loss)  # الهدف الثاني
            
            take_profit = min(take_profit_1, take_profit_2)
            
        else:  # SHORT
            # وقف الخسارة: فوق مستوى المقاومة بـ 0.15%
            stop_loss = level_price * (1 + 0.0015)
            
            # جني الأرباح: مستوى الدعم المقابل أو 1.5x مسافة وقف الخسارة
            take_profit_1 = level_price * (1 - 0.002)  # الهدف الأول
            take_profit_2 = current_price - 1.5 * (stop_loss - current_price)  # الهدف الثاني
            
            take_profit = max(take_profit_1, take_profit_2)
        
        # التحقق من نسبة المكافأة/المخاطرة
        if direction == 'LONG':
            risk = current_price - stop_loss
            reward = take_profit - current_price
        else:
            risk = stop_loss - current_price
            reward = current_price - take_profit
        
        reward_risk_ratio = reward / risk if risk > 0 else 0
        
        if reward_risk_ratio < 1.0:
            # ضبط جني الأرباح لتحقيق نسبة 1:1.5 على الأقل
            if direction == 'LONG':
                take_profit = current_price + 1.5 * risk
            else:
                take_profit = current_price - 1.5 * risk
        
        logger.info(f"🎯 مستويات {signal_info['symbol']} {direction}: "
                   f"الدخول {current_price:.4f}, وقف {stop_loss:.4f}, جني {take_profit:.4f}")
        
        return stop_loss, take_profit
    
    def check_market_conditions(self, symbol):
        """التحقق من ظروف السوق"""
        try:
            # الحصول على بيانات الإطار الزمني 15 دقيقة
            data_15m = self.get_klines_data(symbol, Client.KLINE_INTERVAL_15MINUTE, 50)
            if data_15m is None or len(data_15m) < 20:
                return False, "بيانات غير كافية"
            
            # حساب التقلبات
            volatility = data_15m['close'].pct_change().std()
            if volatility > 0.05:  # تجنب التقلبات العالية
                return False, f"تقلبات عالية: {volatility:.2%}"
            
            # التحقق من الحجم
            avg_volume = data_15m['volume'].mean()
            current_volume = data_15m['volume'].iloc[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            
            if volume_ratio < 0.5:  # تجنب فترات السيولة المنخفضة
                return False, f"حجم منخفض: {volume_ratio:.2f}x"
            
            return True, "ظروف سوق مناسبة"
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من ظروف السوق لـ {symbol}: {e}")
            return False, f"خطأ في التحقق: {str(e)}"
    
    def execute_trade(self, signal_info):
        """تنفيذ صفقة بناءً على الإشارة"""
        symbol = signal_info['symbol']
        direction = signal_info['direction']
        
        try:
            # التحقق من الشروط الأساسية
            if self.trade_manager.get_active_trades_count() >= self.max_active_trades:
                logger.info(f"⏹️  الحد الأقصى للصفقات النشطة ({self.max_active_trades})")
                return False
            
            if self.daily_trades_count >= self.max_daily_trades:
                logger.info(f"⏹️  الحد الأقصى للصفقات اليومية ({self.max_daily_trades})")
                return False
            
            # الحصول على الجلسة الحالية
            current_session = self.session_manager.get_current_session()
            if not current_session['active']:
                logger.info("⏹️  خارج أوقات التداول النشطة")
                return False
            
            # التحقق من إمكانية التداول على الرمز في الجلسة الحالية
            if not self.session_manager.should_trade_symbol(symbol, current_session):
                logger.info(f"⏹️  {symbol} غير مناسب للجلسة الحالية")
                return False
            
            # التحقق من ظروف السوق
            market_ok, market_reason = self.check_market_conditions(symbol)
            if not market_ok:
                logger.info(f"⏹️  ظروف السوق غير مناسبة لـ {symbol}: {market_reason}")
                return False
            
            # التحقق من نظام التبريد
            can_trade, cooldown_reason = self.trade_manager.can_trade_symbol(symbol, current_session['name'])
            if not can_trade:
                logger.info(f"⏹️  {symbol} في فترة تبريد: {cooldown_reason}")
                return False
            
            # الحصول على السعر الحالي
            current_price = self.get_current_price(symbol)
            if current_price is None:
                logger.error(f"❌ فشل في الحصول على سعر {symbol}")
                return False
            
            # حساب وقف الخسارة وجني الأرباح
            stop_loss, take_profit = self.calculate_stop_loss_take_profit(signal_info, current_price)
            if stop_loss is None or take_profit is None:
                logger.error(f"❌ فشل في حساب مستويات وقف الخسارة وجني الأرباح لـ {symbol}")
                return False
            
            # حساب حجم المركز
            quantity = self.calculate_position_size(symbol, current_price, stop_loss)
            if quantity <= 0:
                logger.error(f"❌ حجم مركز غير صالح لـ {symbol}")
                return False
            
            # تنفيذ الصفقة
            side = order_side = "BUY" if direction == "LONG" else "SELL"
            
            try:
                # فتح المركز
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=order_side,
                    type=Client.ORDER_TYPE_MARKET,
                    quantity=quantity
                )
                
                # إعداد أوامر وقف الخسارة وجني الأرباح
                self.client.futures_create_order(
                    symbol=symbol,
                    side="SELL" if direction == "LONG" else "BUY",
                    type=Client.ORDER_TYPE_STOP_MARKET,
                    quantity=quantity,
                    stopPrice=round(stop_loss, 4),
                    closePosition=True
                )
                
                self.client.futures_create_order(
                    symbol=symbol,
                    side="SELL" if direction == "LONG" else "BUY",
                    type=Client.ORDER_TYPE_TAKE_PROFIT_MARKET,
                    quantity=quantity,
                    stopPrice=round(take_profit, 4),
                    closePosition=True
                )
                
                # تسجيل الصفقة
                trade_data = {
                    'symbol': symbol,
                    'side': direction,
                    'quantity': quantity,
                    'entry_price': current_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'timestamp': datetime.now(damascus_tz),
                    'status': 'open',
                    'signal_confidence': signal_info['confidence']
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.daily_trades_count += 1
                self.last_trade_time = datetime.now(damascus_tz)
                
                # إرسال إشعار
                self.notifier.send_trade_opened(
                    symbol, direction, quantity, current_price, stop_loss, take_profit
                )
                
                logger.info(f"✅ تم فتح صفقة {direction} على {symbol}: "
                           f"الكمية {quantity}, السعر {current_price:.4f}")
                
                return True
                
            except Exception as e:
                logger.error(f"❌ خطأ في تنفيذ الصفقة لـ {symbol}: {e}")
                return False
            
        except Exception as e:
            logger.error(f"❌ خطأ عام في تنفيذ الصفقة لـ {symbol}: {e}")
            return False
    
    def monitor_and_close_trades(self):
        """مراقبة وإغلاق الصفقات"""
        try:
            self.trade_manager.sync_with_exchange()
            active_trades = self.trade_manager.get_all_trades()
            
            for symbol, trade in active_trades.items():
                current_price = self.get_current_price(symbol)
                if current_price is None:
                    continue
                
                # التحقق من إغلاق الصفقة يدويًا (إذا تم إغلاقها خارج البوت)
                try:
                    position_info = self.client.futures_position_information(symbol=symbol)
                    for position in position_info:
                        if float(position['positionAmt']) == 0:
                            self.trade_manager.remove_trade(symbol)
                            logger.info(f"🔄 تم إغلاق صفقة {symbol} خارج البوت")
                            continue
                except Exception as e:
                    logger.error(f"❌ خطأ في التحقق من صفقة {symbol}: {e}")
        
        except Exception as e:
            logger.error(f"❌ خطأ في مراقبة الصفقات: {e}")
    
    def run_trading_cycle(self):
        """تشغيل دورة التداول"""
        try:
            # إعادة تعيين الإحصائيات اليومية
            self.reset_daily_stats()
            
            # تنظيف فترات التبريد
            self.trade_manager.cleanup_cooldowns()
            
            # الحصول على الجلسة الحالية
            current_session = self.session_manager.get_current_session()
            
            if not current_session['active']:
                logger.info("💤 خارج أوقات التداول النشطة")
                return
            
            logger.info(f"🌍 جلسة التداول: {current_session['name']}")
            
            # التحقق من عدد الصفقات النشطة
            if self.trade_manager.get_active_trades_count() >= self.max_active_trades:
                logger.info("⏹️  الحد الأقصى للصفقات النشطة تم الوصول إليه")
                return
            
            # مسح الرموز الممكنة
            for symbol in self.trading_symbols:
                try:
                    # التحقق من إمكانية التداول على الرمز
                    if not self.session_manager.should_trade_symbol(symbol, current_session):
                        continue
                    
                    # التحقق من عدم وجود صفقة نشطة على الرمز
                    if self.trade_manager.is_symbol_trading(symbol):
                        continue
                    
                    # الحصول على بيانات الأسعار
                    data_1h = self.get_klines_data(symbol, Client.KLINE_INTERVAL_1HOUR, 50)
                    data_15m = self.get_klines_data(symbol, Client.KLINE_INTERVAL_15MINUTE, 30)
                    current_price = self.get_current_price(symbol)
                    
                    if data_1h is None or data_15m is None or current_price is None:
                        continue
                    
                    # توليد الإشارة
                    signal = self.signal_generator.generate_signal(symbol, data_1h, data_15m, current_price)
                    
                    if signal and signal['confidence'] >= 0.70:
                        logger.info(f"🎯 إشارة قوية على {symbol}: {signal['direction']} (ثقة: {signal['confidence']:.2%})")
                        
                        # تنفيذ الصفقة
                        if self.execute_trade(signal):
                            # إرسال إشعار بالإشارة
                            self.notifier.send_signal(signal)
                            
                            # إضافة تأخير بين الصفقات
                            time.sleep(2)
                            
                            # الخروج إذا وصلنا للحد الأقصى
                            if self.trade_manager.get_active_trades_count() >= self.max_active_trades:
                                break
                    
                except Exception as e:
                    logger.error(f"❌ خطأ في معالجة الرمز {symbol}: {e}")
                    continue
            
            # مراقبة الصفقات النشطة
            self.monitor_and_close_trades()
            
        except Exception as e:
            logger.error(f"❌ خطأ في دورة التداول: {e}")
            self.notifier.send_error(str(e))
    
    def get_active_trades_details(self):
        """الحصول على تفاصيل الصفقات النشطة"""
        active_trades = self.trade_manager.get_all_trades()
        result = []
        
        for symbol, trade in active_trades.items():
            current_price = self.get_current_price(symbol)
            if current_price:
                if trade['side'] == 'LONG':
                    pnl = (current_price - trade['entry_price']) * trade['quantity']
                    pnl_percent = (current_price / trade['entry_price'] - 1) * 100
                else:
                    pnl = (trade['entry_price'] - current_price) * trade['quantity']
                    pnl_percent = (trade['entry_price'] / current_price - 1) * 100
            else:
                pnl = 0
                pnl_percent = 0
            
            result.append({
                'symbol': symbol,
                'side': trade['side'],
                'quantity': trade['quantity'],
                'entry_price': trade['entry_price'],
                'current_price': current_price,
                'pnl': pnl,
                'pnl_percent': pnl_percent,
                'stop_loss': trade['stop_loss'],
                'take_profit': trade['take_profit'],
                'timestamp': trade['timestamp'].isoformat() if isinstance(trade['timestamp'], datetime) else trade['timestamp']
            })
        
        return result
    
    def get_market_analysis(self, symbol):
        """الحصول على تحليل السوق للرمز"""
        try:
            data_1h = self.get_klines_data(symbol, Client.KLINE_INTERVAL_1HOUR, 50)
            data_15m = self.get_klines_data(symbol, Client.KLINE_INTERVAL_15MINUTE, 30)
            current_price = self.get_current_price(symbol)
            
            if data_1h is None or data_15m is None or current_price is None:
                return {'error': 'لا توجد بيانات كافية'}
            
            # تحليل مستويات الدعم والمقاومة
            support_levels, resistance_levels = self.signal_generator._calculate_support_resistance(data_1h, data_15m)
            
            # تحليل الشموع
            candlestick_patterns = self.signal_generator._analyze_candlestick_patterns(data_15m)
            
            # حساب RSI
            rsi_14 = self.signal_generator._calculate_rsi(data_15m['close'], 14)
            current_rsi = rsi_14.iloc[-1]
            
            # تحليل الحجم
            volume_analysis = self.signal_generator._analyze_volume(data_15m)
            
            # توليد إشارة
            signal = self.signal_generator.generate_signal(symbol, data_1h, data_15m, current_price)
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'support_levels': support_levels,
                'resistance_levels': resistance_levels,
                'candlestick_patterns': candlestick_patterns,
                'rsi': current_rsi,
                'volume_analysis': volume_analysis,
                'signal': signal,
                'timestamp': datetime.now(damascus_tz).isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def get_current_session_info(self):
        """الحصول على معلومات الجلسة الحالية"""
        current_session = self.session_manager.get_current_session()
        schedule_info = self.session_manager.get_session_schedule()
        
        return {
            'current_session': current_session,
            'schedule': schedule_info,
            'active_trades': self.trade_manager.get_active_trades_count(),
            'max_active_trades': self.max_active_trades,
            'daily_trades': self.daily_trades_count,
            'max_daily_trades': self.max_daily_trades,
            'timestamp': datetime.now(damascus_tz).isoformat()
        }
    
    def get_performance_stats(self):
        """الحصول على إحصائيات الأداء"""
        return {
            **self.performance_stats,
            'active_trades': self.trade_manager.get_active_trades_count(),
            'daily_trades': self.daily_trades_count,
            'consecutive_losses': self.consecutive_losses,
            'last_trade_time': self.last_trade_time.isoformat() if self.last_trade_time else None,
            'timestamp': datetime.now(damascus_tz).isoformat()
        }

def main():
    """الدالة الرئيسية"""
    try:
        # تحميل المتغيرات البيئية
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not api_key or not api_secret:
            logger.error("❌ مفاتيح API غير موجودة")
            return
        
        # إنشاء البوت
        bot = ScalpingTradingBot(api_key, api_secret, telegram_token, telegram_chat_id)
        
        # بدء تطبيق Flask في خيط منفصل
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        logger.info("🚀 بدء تشغيل بوت التداول باستراتيجية الدعم والمقاومة")
        logger.info("📊 الإستراتيجية: التداول بناءً على ارتداد السعر من مستويات الدعم والمقاومة")
        
        if telegram_token and telegram_chat_id:
            bot.notifier.send_message("🤖 بدء تشغيل بوت التداول باستراتيجية الدعم والمقاومة")
        
        # الجدولة
        schedule.every(1).minutes.do(bot.run_trading_cycle)
        schedule.every(5).minutes.do(bot.monitor_and_close_trades)
        schedule.every(1).hours.do(bot.trade_manager.cleanup_cooldowns)
        
        # تشغيل الدورة الأولى فورًا
        bot.run_trading_cycle()
        
        # الحلقة الرئيسية
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("⏹️  إيقاف البوت بواسطة المستخدم")
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع: {e}")
        time.sleep(60)

if __name__ == "__main__":
    main()
