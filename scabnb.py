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
                'symbols_focus': ['BNBUSDT'],  # BNB فقط
                'active': False,
                'performance_multiplier': 0.6,
                'max_trades_per_hour': 2
            },
            'euro_american_overlap': {
                'name': 'تداخل أوروبا-أمريكا (الأفضل)',
                'start_hour_utc': 13,
                'end_hour_utc': 17,
                'symbols_focus': ['BNBUSDT'],  # BNB فقط
                'active': False,
                'performance_multiplier': 1.0,
                'max_trades_per_hour': 4
            },
            'american': {
                'name': 'الجلسة الأمريكية',
                'start_hour_utc': 13,
                'end_hour_utc': 21,
                'symbols_focus': ['BNBUSDT'],  # BNB فقط
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
    
    def send_trade_alert(self, symbol, signal, current_price):
        """إرسال إشعار صفقة"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        
        message = (
            f"{direction_emoji} <b>إشارة تداول BNB</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"السعر: ${current_price:.4f}\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
            f"الاستراتيجية: {signal.get('strategy', 'SUPPORT_RESISTANCE')}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message, 'trade_signal')

class ScalpingTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbols': ["BNBUSDT"],  # BNB فقط
        'used_balance_per_trade': 5,
        'max_leverage': 5,
        'nominal_trade_size': 25,
        'max_active_trades': 2,
        'data_interval_1h': '1h',
        'data_interval_15m': '15m',
        'rescan_interval_minutes': 5,
        'min_signal_confidence': 0.70,
        'target_profit_pct': 0.30,
        'stop_loss_pct': 0.20,
        'max_daily_trades': 10,
        'cooldown_after_loss': 15,
        
        # إعدادات التوقيت الذكي المحسنة
        'session_settings': {
            'euro_american_overlap': {
                'rescan_interval': 3,
                'max_trades_per_cycle': 2,
                'confidence_boost': 0.05,
                'max_trades_per_symbol_per_hour': 2
            },
            'american': {
                'rescan_interval': 5,
                'max_trades_per_cycle': 2,
                'confidence_boost': 0.03,
                'max_trades_per_symbol_per_hour': 2
            },
            'asian': {
                'rescan_interval': 8,
                'max_trades_per_cycle': 1,
                'confidence_boost': 0.08,
                'max_trades_per_symbol_per_hour': 1
            },
            'low_liquidity': {
                'rescan_interval': 15,
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

        # تهيئة مكونات التداول باستراتيجية الدعم والمقاومة
        self.signal_generator = SupportResistanceSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        self.session_manager = TradingSessionManager()
        
        # الإعدادات الديناميكية
        self.dynamic_settings = {
            'rescan_interval': self.TRADING_SETTINGS['rescan_interval_minutes'],
            'max_trades_per_cycle': 2,
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
        logger.info("✅ تم تهيئة بوت التداول باستراتيجية الدعم والمقاومة لـ BNB بنجاح")

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
            'max_trades_per_cycle': session_config.get('max_trades_per_cycle', 2),
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
        """التحقق من إمكانية فتح صفقة مع القيود المحسنة"""
        reasons = []
        
        # التحقق من الحد الأقصى للصفقات النشطة
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات النشطة")
        
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
        
        # التحقق من نظام التبريد للرمز
        can_trade_symbol, cooldown_reason = self.trade_manager.can_trade_symbol(symbol, self.dynamic_settings['session_name'])
        if not can_trade_symbol:
            reasons.append(cooldown_reason)
        
        # التحقق من الحد الأقصى للصفقات على الرمز في الساعة
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
                    self.trade_manager.cleanup_cooldowns()
                    self.reset_hourly_count()
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
                "⚡ <b>بدء تشغيل بوت التداول باستراتيجية الدعم والمقاومة</b>\n"
                f"<b>الاستراتيجية:</b> ارتداد السعر من مستويات الدعم والمقاومة\n"
                f"<b>الرمز:</b> BNBUSDT فقط\n"
                f"<b>المؤشرات:</b> RSI + أنماط الشموع + مستويات الدعم/المقاومة\n"
                f"<b>الإعدادات:</b>\n"
                f"• وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"• هدف الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"• الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"• القيمة الاسمية: ${self.TRADING_SETTINGS['nominal_trade_size']}\n"
                f"• صفقات نشطة: {self.TRADING_SETTINGS['max_active_trades']}\n"
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
            f"📊 <b>تقرير أداء بوت BNB</b>\n"
            f"الاستراتيجية: ارتداد من الدعم والمقاومة\n"
            f"الرمز: BNBUSDT\n"
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
                f"💰 <b>تقرير الرصيد الحقيقي - BNB</b>\n"
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
            f"🌍 <b>تقرير جلسة التداول BNB</b>\n"
            f"الاستراتيجية: ارتداد السعر من مستويات الدعم والمقاومة\n"
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
            message = f"💓 بوت BNB نشط - الجلسة: {self.dynamic_settings['session_name']} - الصفقات: {active_trades}"
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
        """تنفيذ صفقة التداول"""
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
                    'strategy': signal.get('strategy', 'SUPPORT_RESISTANCE')
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['hourly_trade_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                
                # إرسال إشعار
                if self.notifier:
                    risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
                    
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة BNB</b>\n"
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
                        f"الاستراتيجية: ارتداد من الدعم/المقاومة\n"
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
                else:
                    self.performance_stats['losing_trades'] += 1
                    self.performance_stats['consecutive_losses'] += 1
                    self.performance_stats['consecutive_wins'] = 0
                    
                    # إضافة تبريد بعد خسائر متتالية على نفس الرمز
                    if self.performance_stats['consecutive_losses'] >= 2:
                        self.trade_manager.add_symbol_cooldown(symbol, self.TRADING_SETTINGS['cooldown_after_loss'])
                
                self.performance_stats['total_pnl'] += pnl_pct
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة BNB</b>\n"
                        f"الجلسة: {self.dynamic_settings['session_name']}\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"السبب: {reason}\n"
                        f"الاستراتيجية: {trade.get('strategy', 'SUPPORT_RESISTANCE')}\n"
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
        """مسح السوق للعثور على فرص التداول"""
        logger.info("🔍 بدء مسح السوق باستراتيجية الدعم والمقاومة...")
        
        opportunities = []
        current_session = self.session_manager.get_current_session()
        
        for symbol in self.TRADING_SETTINGS['symbols']:  # BNB فقط
            try:
                # تخطي الرموز ذات الصفقات النشطة
                if self.trade_manager.is_symbol_trading(symbol):
                    continue
                
                # التحقق من تركيز الجلسة على الرمز
                if not self.session_manager.should_trade_symbol(symbol, current_session):
                    continue
                
                # جلب البيانات من إطارين زمنيين
                data_1h = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval_1h'])
                data_15m = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval_15m'])
                
                if data_1h is None or data_15m is None or len(data_1h) < 30 or len(data_15m) < 20:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                # استخدام مولد الإشارات الجديد
                signal = self.signal_generator.generate_signal(symbol, data_1h, data_15m, current_price)
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
        
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة تداول في جلسة {self.dynamic_settings['session_name']}")
        return opportunities

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول مع مراعاة الجلسة"""
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
            
            logger.info(f"✅ اكتملت دورة التداول في جلسة {self.dynamic_settings['session_name']} - تم تنفيذ {executed_trades} صفقة")
            
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

    def get_market_analysis(self, symbol):
        """الحصول على تحليل السوق لرمز معين"""
        try:
            # جلب البيانات من إطارين زمنيين
            data_1h = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval_1h'])
            data_15m = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval_15m'])
            
            if data_1h is None or data_15m is None:
                return {'error': 'لا توجد بيانات'}
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return {'error': 'لا يمكن الحصول على السعر'}
            
            # استخدام مولد الإشارات الجديد
            signal = self.signal_generator.generate_signal(symbol, data_1h, data_15m, current_price)
            
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
                'max_leverage': self.TRADING_SETTINGS['max_leverage'],
                'nominal_trade_size': self.TRADING_SETTINGS['nominal_trade_size']
            },
            'strategy': 'SUPPORT_RESISTANCE',
            'symbol': 'BNBUSDT',
            'current_session': self.dynamic_settings['session_name']
        }

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت التداول باستراتيجية الدعم والمقاومة لـ BNB...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت التداول باستراتيجية الدعم والمقاومة</b>\n"
                f"الاستراتيجية: ارتداد السعر من مستويات الدعم والمقاومة\n"
                f"الرمز: BNBUSDT فقط\n"
                f"المؤشرات: RSI + أنماط الشموع + مستويات الدعم/المقاومة\n"
                f"نظام الجلسات الذكي: نشط ✅\n"
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
            logger.info("🛑 إيقاف بوت التداول...")

def main():
    """الدالة الرئيسية"""
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
