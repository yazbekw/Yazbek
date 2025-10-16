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

# ========== الإعدادات الأساسية ==========
TRADING_SETTINGS = {
    'symbols': ["BNBUSDT"],
    'used_balance_per_trade': 6,
    'max_leverage': 8,
    'max_active_trades': 2,
    'data_interval': '5m',
    'rescan_interval_minutes': 0.5,
    'target_profit_pct': 0.21,
    'stop_loss_pct': 0.11,
    'max_trade_duration_minutes': 10,
    'max_daily_trades': 30,
    'cooldown_after_loss': 3,
    'max_trades_per_symbol': 2,
    'max_trend_duration_minutes': 40,
    'min_trade_gap_minutes': 5,
    'macd_early_exit': True,
    'macd_required_additional': True,
    'first_trade_requirements': {
        'min_volume_ratio': 1.1,
        'min_rsi_strength': 5
    }
}

# ضبط التوقيت
damascus_tz = pytz.timezone('Asia/Damascus')
os.environ['TZ'] = 'Asia/Damascus'

# تطبيق Flask للرصد
app = Flask(__name__)

class PrecisionManager:
    """مدير دقة الأسعار والكميات"""
    
    def __init__(self, client):
        self.client = client
        self.symbols_info = {}
        
    def get_symbol_info(self, symbol):
        """الحصول على معلومات العملة"""
        try:
            if symbol not in self.symbols_info:
                self._update_symbols_info()
            return self.symbols_info.get(symbol, {})
        except Exception as e:
            logger.error(f"❌ خطأ في جلب معلومات الدقة لـ {symbol}: {e}")
            return {}
    
    def _update_symbols_info(self):
        """تحديث معلومات العملات"""
        try:
            exchange_info = self.client.futures_exchange_info()
            for symbol_info in exchange_info['symbols']:
                symbol = symbol_info['symbol']
                self.symbols_info[symbol] = {
                    'filters': symbol_info['filters'],
                    'baseAsset': symbol_info['baseAsset'],
                    'quoteAsset': symbol_info['quoteAsset']
                }
            logger.info("✅ تم تحديث معلومات الدقة للعملات")
        except Exception as e:
            logger.error(f"❌ خطأ في تحديث معلومات العملات: {e}")
    
    def adjust_price(self, symbol, price):
        """ضبط السعر حسب الدقة"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return round(price, 4)
            
            price_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
            if price_filter:
                tick_size = float(price_filter['tickSize'])
                return float(int(price / tick_size) * tick_size)
            return round(price, 4)
        except Exception as e:
            logger.error(f"❌ خطأ في ضبط سعر {symbol}: {e}")
            return round(price, 4)
    
    def adjust_quantity(self, symbol, quantity):
        """ضبط الكمية حسب الدقة"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return round(quantity, 6)
            
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if lot_size_filter:
                step_size = float(lot_size_filter['stepSize'])
                min_qty = float(lot_size_filter.get('minQty', 0))
                adjusted_quantity = float(int(quantity / step_size) * step_size)
                return max(adjusted_quantity, min_qty)
            return round(quantity, 6)
        except Exception as e:
            logger.error(f"❌ خطأ في ضبط كمية {symbol}: {e}")
            return round(quantity, 6)

class MACDTrendManager:
    """مدير الترندات مع دعم الماكد المتقدم"""
    
    def __init__(self):
        self.active_trends = {}
        self.trend_history = []
        self.macd_signals_log = []
    
    def start_new_trend(self, symbol, direction, signal_type, macd_status):
        """بدء ترند جديد مع حالة الماكد"""
        trend_id = f"{symbol}_{int(time.time())}"
        
        self.active_trends[symbol] = {
            'trend_id': trend_id,
            'symbol': symbol,
            'direction': direction,
            'start_time': datetime.now(damascus_tz),
            'trades_count': 1,
            'signal_type': signal_type,
            'last_trade_time': datetime.now(damascus_tz),
            'status': 'active',
            'total_pnl': 0.0,
            'successful_trades': 0,
            'failed_trades': 0,
            'macd_status_start': macd_status,
            'macd_confirmations': 1 if macd_status['bullish'] else 0,
            'last_macd_signal': macd_status
        }
        
        logger.info(f"🎯 بدء ترند جديد {symbol}: {direction} | الماكد: {macd_status['bullish']}")
        return trend_id
    
    def add_trade_to_trend(self, symbol, signal_type, macd_status):
        """إضافة صفقة إلى الترند مع تحديث الماكد"""
        if symbol not in self.active_trends:
            return False
        
        trend = self.active_trends[symbol]
        trend['trades_count'] += 1
        trend['last_trade_time'] = datetime.now(damascus_tz)
        trend['last_signal_type'] = signal_type
        trend['last_macd_signal'] = macd_status
        
        if macd_status['bullish'] and trend['direction'] == 'LONG':
            trend['macd_confirmations'] += 1
        elif not macd_status['bullish'] and trend['direction'] == 'SHORT':
            trend['macd_confirmations'] += 1
        
        logger.info(f"📈 إضافة صفقة للترند {symbol}: {signal_type} | الماكد: {macd_status['bullish']}")
        return True
    
    def update_trend_pnl(self, symbol, pnl_pct):
        """تحديد الربح/الخسارة في الترند"""
        if symbol in self.active_trends:
            self.active_trends[symbol]['total_pnl'] += pnl_pct
            if pnl_pct > 0:
                self.active_trends[symbol]['successful_trades'] += 1
            else:
                self.active_trends[symbol]['failed_trades'] += 1
    
    def can_add_trade_to_trend(self, symbol, signal_type, macd_status):
        """التحقق من إمكانية إضافة صفقة للترند مع شروط الماكد"""
        if symbol not in self.active_trends:
            return False, "لا يوجد ترند نشط"
        
        trend = self.active_trends[symbol]
        
        # التحقق من مدة الترند
        trend_duration = (datetime.now(damascus_tz) - trend['start_time']).total_seconds() / 60
        if trend_duration >= TRADING_SETTINGS['max_trend_duration_minutes']:
            return False, "انتهت مدة الترند"
        
        # التحقق من الحد الأقصى للصفقات
        if trend['trades_count'] >= TRADING_SETTINGS['max_trades_per_symbol']:
            return False, "الحد الأقصى للصفقات في الترند"
        
        # التحقق من الفاصل الزمني
        time_gap = (datetime.now(damascus_tz) - trend['last_trade_time']).total_seconds() / 60
        if time_gap < TRADING_SETTINGS['min_trade_gap_minutes']:
            return False, f"فاصل زمني غير كافي ({time_gap:.1f} دقيقة)"
        
        # التحقق من شروط الماكد للإشارات الإضافية
        if (TRADING_SETTINGS['macd_required_additional'] and 
            signal_type != 'BASE_CROSSOVER' and 
            not self._check_macd_for_additional_signal(trend, macd_status)):
            return False, "الماكد لا يؤكد الإشارة الإضافية"
        
        # التحقق من الخسائر المتتالية
        if trend['failed_trades'] >= 3:
            return False, "3 خسائر متتالية في الترند"
        
        return True, "يمكن إضافة الصفقة"
    
    def _check_macd_for_additional_signal(self, trend, current_macd):
        """التحقق من شروط الماكد للإشارات الإضافية"""
        if trend['direction'] == 'LONG':
            # للشراء: الماكد فوق الإشارة والهيستوجرام موجب
            return (current_macd['macd_above_signal'] and 
                   current_macd['histogram_positive'] and
                   current_macd['histogram_increasing'])
        else:
            # للبيع: الماكد تحت الإشارة والهيستوجرام سالب
            return (not current_macd['macd_above_signal'] and 
                   not current_macd['histogram_positive'] and
                   not current_macd['histogram_increasing'])
    
    def should_early_exit(self, symbol, current_macd, current_rsi):
        """التحقق من إغلاق مبكر بالماكد"""
        if symbol not in self.active_trends:
            return False, ""
        
        trend = self.active_trends[symbol]
        
        if trend['direction'] == 'LONG':
            # إغلاق مبكر للشراء: الماكد تحت الإشارة وRSI ضعيف
            if (not current_macd['macd_above_signal'] and 
                current_rsi < 48 and
                current_macd['histogram_decreasing']):
                return True, "ضعف الزخم (الماكد تحت الإشارة + RSI منخفض)"
        
        else:  # SHORT
            # إغلاق مبكر للبيع: الماكد فوق الإشارة وRSI مرتفع
            if (current_macd['macd_above_signal'] and 
                current_rsi > 52 and
                current_macd['histogram_increasing']):
                return True, "ضعف الزخم (الماكد فوق الإشارة + RSI مرتفع)"
        
        return False, ""
    
    def end_trend(self, symbol, reason="تم الإنهاء"):
        """إنهاء الترند"""
        if symbol in self.active_trends:
            trend = self.active_trends[symbol]
            trend['end_time'] = datetime.now(damascus_tz)
            trend['status'] = 'ended'
            trend['end_reason'] = reason
            
            # نقل إلى السجل
            self.trend_history.append(trend)
            del self.active_trends[symbol]
            
            logger.info(f"🛑 إنهاء ترند {symbol}: {reason}")
    
    def get_trend_status(self, symbol):
        """الحصول على حالة الترند"""
        return self.active_trends.get(symbol, {})
    
    def cleanup_expired_trends(self):
        """تنظيف الترندات المنتهية"""
        current_time = datetime.now(damascus_tz)
        symbols_to_remove = []
        
        for symbol, trend in self.active_trends.items():
            trend_duration = (current_time - trend['start_time']).total_seconds() / 60
            if trend_duration >= TRADING_SETTINGS['max_trend_duration_minutes']:
                symbols_to_remove.append(symbol)
        
        for symbol in symbols_to_remove:
            self.end_trend(symbol, "انتهت المدة الزمنية")
    
    def log_macd_signal(self, symbol, signal_type, macd_status, action):
        """تسجيل إشارات الماكد للتحليل"""
        log_entry = {
            'timestamp': datetime.now(damascus_tz),
            'symbol': symbol,
            'signal_type': signal_type,
            'macd': macd_status['macd'],
            'signal': macd_status['signal'],
            'histogram': macd_status['histogram'],
            'macd_above_signal': macd_status['macd_above_signal'],
            'action': action,
            'trend_direction': self.active_trends[symbol]['direction'] if symbol in self.active_trends else 'NONE'
        }
        self.macd_signals_log.append(log_entry)

class AdvancedMACDSignalGenerator:
    """مولد إشارات متطور مع دعم الماكد الكامل"""
    
    def __init__(self):
        self.trend_manager = MACDTrendManager()
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارات متقدمة مع الماكد والتنبؤ بالتقاطعات"""
        try:
            if len(data) < 26:  # تحتاج 26 نقطة للماكد
                return None
        
            indicators = self._calculate_advanced_indicators(data)
            macd_status = self._analyze_macd_status(indicators, data)
        
            # البحث عن إشارات بأنواعها
            signals = []
        
            # الإشارة الأساسية (التقاطع)
            base_signal = self._analyze_base_signal(indicators, symbol, current_price, macd_status, data)
            if base_signal:
                signals.append(base_signal)
        
            # التنبؤ بالتقاطعات (الجديد)
            prediction_signal = self.predict_crossover(symbol, data, current_price)
            if prediction_signal:
                signals.append(prediction_signal)
        
            # الإشارات الإضافية في الترند النشط
            additional_signals = self._analyze_additional_signals(indicators, symbol, current_price, data, macd_status)
            signals.extend(additional_signals)
        
            # إرجاع أفضل إشارة
            if signals:
                best_signal = max(signals, key=lambda x: x.get('priority', 0))
                return best_signal
        
            return None
        
        except Exception as e:
            logger.error(f"❌ خطأ في توليد إشارة متقدمة لـ {symbol}: {e}")
            return None
    
    def _calculate_advanced_indicators(self, data):
        """حساب المؤشرات المتقدمة مع الماكد"""
        df = data.copy()
        
        # المتوسطات المتحركة الأساسية
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # مؤشر الماكد
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        # RSI
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        # المتوسطات للإشارات الإضافية
        df['high_5'] = df['high'].rolling(5).max()
        df['low_5'] = df['low'].rolling(5).min()
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        prev_2 = df.iloc[-3] if len(df) > 2 else prev
        
        return {
            'ema9': latest['ema9'],
            'ema21': latest['ema21'],
            'ema9_prev': prev['ema9'],
            'ema21_prev': prev['ema21'],
            'rsi': latest['rsi'],
            'current_close': latest['close'],
            'current_open': latest['open'],
            'prev_close': prev['close'],
            'prev_open': prev['open'],
            'prev_high': prev['high'],
            'prev_low': prev['low'],
            'high_5': latest['high_5'],
            'low_5': latest['low_5'],
            'volume': latest['volume'],
            'volume_avg': df['volume'].tail(20).mean(),
            # بيانات الماكد
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'macd_histogram': latest['macd_histogram'],
            'macd_prev': prev['macd'],
            'macd_signal_prev': prev['macd_signal'],
            'macd_histogram_prev': prev['macd_histogram'],
            'macd_histogram_prev_2': prev_2['macd_histogram'],
        }

    def predict_crossover(self, symbol, data, current_price):
        """التنبؤ بالتقاطعات قبل حدوثها بتحليل آخر 3 شمعات"""
        try:
            if len(data) < 10:  # تحتاج بيانات كافية
                return None
        
            indicators = self._calculate_advanced_indicators(data)
        
            # تحليل اتجاه وقوة المتوسطات
            crossover_prediction = self._analyze_crossover_momentum(indicators, data)
        
            if crossover_prediction and crossover_prediction['probability'] >= 0.7:
                return crossover_prediction
            
            return None
        
        except Exception as e:
            logger.error(f"❌ خطأ في التنبؤ بالتقاطع لـ {symbol}: {e}")
            return None

    def _analyze_crossover_momentum(self, indicators, data):
        """تحليل زخم التقاطع من آخر 3 شمعات"""
    
        # المسافة الحالية بين المتوسطات
        current_distance = indicators['ema9'] - indicators['ema21']
        abs_distance = abs(current_distance)
    
        # تحليل آخر 3 شمعات لتحديد الاتجاه
        df_last_3 = data.tail(3)
    
        # حساب سرعة تقارب/تباعد المتوسطات
        ema9_trend = self._calculate_ema_trend(df_last_3, 'ema9')
        ema21_trend = self._calculate_ema_trend(df_last_3, 'ema21')
    
        # اتجاه التقارب
        convergence_direction = ema9_trend['direction'] - ema21_trend['direction']
    
        # حساب احتمالية التقاطع
        crossover_probability = self._calculate_crossover_probability(
            current_distance, abs_distance, ema9_trend, ema21_trend, convergence_direction
        )
    
        if crossover_probability['high_probability']:
            return {
                'symbol': data.iloc[-1]['symbol'] if 'symbol' in data.columns else 'UNKNOWN',
                'type': crossover_probability['type'],
                'direction': crossover_probability['direction'],
                'probability': crossover_probability['probability'],
                'expected_time': crossover_probability['expected_time'],
                'current_distance_pct': crossover_probability['current_distance_pct'],
                'momentum_strength': crossover_probability['momentum_strength'],
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': indicators['current_close'],
                'signal_type': 'CROSSOVER_PREDICTION',
                'priority': 90  # أولوية عالية ولكن أقل من التقاطع الفعلي
            }
    
        return None

    def _calculate_ema_trend(self, data, ema_column):
        """حساب اتجاه وقوة المتوسط المتحرك"""
        if len(data) < 3:
            return {'direction': 0, 'strength': 0, 'angle': 0}
    
        # حساب المتوسط إذا لم يكن موجوداً
        if ema_column not in data.columns:
            if ema_column == 'ema9':
                data['ema9'] = data['close'].ewm(span=9, adjust=False).mean()
            else:
                data['ema21'] = data['close'].ewm(span=21, adjust=False).mean()
    
        values = data[ema_column].tail(3).values
    
        if len(values) < 3:
            return {'direction': 0, 'strength': 0, 'angle': 0}
    
        # اتجاه الحركة (آخر قيمة - أول قيمة)
        direction = 1 if values[-1] > values[0] else -1 if values[-1] < values[0] else 0
    
        # قوة الحركة (النسبة المئوية للتغير)
        strength = abs((values[-1] - values[0]) / values[0] * 100) if values[0] != 0 else 0
    
        # زاوية الحركة (الميل)
        angle = self._calculate_angle(values)
    
        return {
            'direction': direction,
            'strength': strength,
            'angle': angle,
            'acceleration': (values[-1] - values[-2]) - (values[-2] - values[-3]) if len(values) >= 3 else 0
        }

    def _calculate_angle(self, values):
        """حساب زاوية حركة المتوسط"""
        if len(values) < 2:
            return 0
    
        x = np.array(range(len(values)))
        y = np.array(values)
    
        try:
            # حساب الميل باستخدام الانحدار الخطي
            slope, _ = np.polyfit(x, y, 1)
            angle = np.degrees(np.arctan(slope / (max(y) - min(y) + 1e-10)))
            return angle
        except:
            return 0

    def _calculate_crossover_probability(self, current_distance, abs_distance, ema9_trend, ema21_trend, convergence_direction):
        """حساب احتمالية التقاطع"""
    
        # المسافة النسبية بين المتوسطات
        avg_price = (ema9_trend.get('current_value', 0) + ema21_trend.get('current_value', 0)) / 2
        distance_pct = (abs_distance / avg_price * 100) if avg_price != 0 else 100
    
        # تحديد نوع التقاطع المتوقع
        expected_type = "BULLISH" if current_distance < 0 and convergence_direction > 0 else "BEARISH" if current_distance > 0 and convergence_direction < 0 else "NONE"
    
        # حساب قوة الزخم
        momentum_strength = self._calculate_momentum_strength(ema9_trend, ema21_trend, convergence_direction)
    
        # حساب الاحتمالية
        probability = self._calculate_probability_score(distance_pct, momentum_strength, ema9_trend, ema21_trend)
    
        # الوقت المتوقع للتقاطع
        expected_time = self._estimate_crossover_time(distance_pct, momentum_strength)
    
        return {
            'type': expected_type,
            'direction': 'LONG' if expected_type == 'BULLISH' else 'SHORT',
            'probability': probability,
            'current_distance_pct': distance_pct,
            'momentum_strength': momentum_strength,
            'expected_time': expected_time,
            'high_probability': probability >= 0.7 and momentum_strength >= 0.6
        }

    def _calculate_momentum_strength(self, ema9_trend, ema21_trend, convergence_direction):
        """حساب قوة زخم التقارب"""
        strength_score = 0
    
        # قوة حركة EMA9
        if ema9_trend['strength'] > 0.1:  # تغير أكثر من 0.1%
            strength_score += 0.3
    
        # قوة حركة EMA21  
        if ema21_trend['strength'] > 0.05:  # تغير أكثر من 0.05%
            strength_score += 0.2
    
        # اتجاه التقارب
        if abs(convergence_direction) > 0.5:
            strength_score += 0.3
    
        # التسارع في الحركة
        if abs(ema9_trend.get('acceleration', 0)) > 0.01:
            strength_score += 0.2
    
        return min(strength_score, 1.0)  # تأكد من عدم تجاوز 1.0

    def _calculate_probability_score(self, distance_pct, momentum_strength, ema9_trend, ema21_trend):
        """حساب درجة الاحتمالية"""
        probability = 0
    
        # المسافة بين المتوسطات (كلما كانت أقل زادت الاحتمالية)
        if distance_pct < 0.05:  # أقل من 0.05%
            probability += 0.4
        elif distance_pct < 0.1:  # أقل من 0.1%
            probability += 0.3
        elif distance_pct < 0.2:  # أقل من 0.2%
            probability += 0.2
    
        # قوة الزخم
        probability += momentum_strength * 0.4
    
        # زاوية الحركة
        if abs(ema9_trend.get('angle', 0)) > 5:  # زاوية كبيرة
            probability += 0.1
        if abs(ema21_trend.get('angle', 0)) > 3:  # زاوية متوسطة
            probability += 0.1
    
        return min(probability, 1.0)

    def _estimate_crossover_time(self, distance_pct, momentum_strength):
        """تقدير الوقت المتوقع للتقاطع"""
        if momentum_strength > 0.8:
            return "1-2 شمعة"
        elif momentum_strength > 0.6:
            return "2-3 شمعات" 
        elif momentum_strength > 0.4:
            return "3-4 شمعات"
        else:
            return "4+ شمعات"
    
    def _calculate_rsi(self, prices, period):
        """حساب RSI بشكل صحيح وآمن"""
        try:
            if len(prices) < period + 1:
                return 50.0
            
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).fillna(0)
            loss = (-delta.where(delta < 0, 0)).fillna(0)
            
            avg_gain = gain.rolling(window=period, min_periods=1).mean()
            avg_loss = loss.rolling(window=period, min_periods=1).mean()
            
            rs = avg_gain / (avg_loss + 1e-10)
            rsi = 100 - (100 / (1 + rs))
            
            # إرجاع القيمة الأخيرة فقط كرقم
            return float(rsi.iloc[-1]) if not rsi.empty else 50.0
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب RSI: {e}")
            return 50.0

    def _analyze_macd_status(self, indicators, data):
        """تحليل حالة الماكد الشاملة"""
        macd_above_signal = indicators['macd'] > indicators['macd_signal']
        histogram_positive = indicators['macd_histogram'] > 0
        histogram_increasing = indicators['macd_histogram'] > indicators['macd_histogram_prev']
        histogram_decreasing = indicators['macd_histogram'] < indicators['macd_histogram_prev']
        
        # تحديد إذا كان الماكد في منطقة ذروة شراء/بيع
        macd_value = abs(indicators['macd'])
        macd_extreme = macd_value > 0.005  # حد معين للذروة
        
        return {
            'macd': indicators['macd'],
            'signal': indicators['macd_signal'],
            'histogram': indicators['macd_histogram'],
            'macd_above_signal': macd_above_signal,
            'histogram_positive': histogram_positive,
            'histogram_increasing': histogram_increasing,
            'histogram_decreasing': histogram_decreasing,
            'macd_extreme': macd_extreme,
            'bullish': macd_above_signal and histogram_positive,
            'bearish': not macd_above_signal and not histogram_positive
        }
    
    
    def _analyze_base_signal(self, indicators, symbol, current_price, macd_status, data):
        """تحليل الإشارة الأساسية مع التعديلات الجديدة"""
        ema9_cross_above_21 = (indicators['ema9'] > indicators['ema21'] and 
                              indicators['ema9_prev'] <= indicators['ema21_prev'])
        ema9_cross_below_21 = (indicators['ema9'] < indicators['ema21'] and 
                              indicators['ema9_prev'] >= indicators['ema21_prev'])

        # 🔴 🔴 🔴 الشرط المضاف - المسافات البادئة صحيحة هنا 🔴 🔴 🔴
        prev_distance_pct = abs(indicators['ema9_prev'] - indicators['ema21_prev']) / ((indicators['ema9_prev'] + indicators['ema21_prev'])/2) * 100
        min_required_distance = 0.1  # 0.1% حد أدنى للمسافة

        if prev_distance_pct < min_required_distance:
            logger.info(f"⏭️ تخطي {symbol} - التقاطع من مسافة قريبة جداً: {prev_distance_pct:.3f}%")
            return None
        # 🔴 🔴 🔴 نهاية الشرط المضاف 🔴 🔴 🔴

        # الشروط الجديدة للدخول المبكر - استخدام 20% من الشمعة السابقة
        prev_candle_range = indicators['prev_high'] - indicators['prev_low']
    
        # ✅ التعديل: دخول عند 20% من الشمعة السابقة
        price_confirmation_buy = current_price > (indicators['prev_low'] + prev_candle_range * 0.2)
        price_confirmation_sell = current_price < (indicators['prev_high'] - prev_candle_range * 0.2)

        # ✅ التعديل: تخفيف شرط الحجم إلى 10% بدل 20%
        volume_condition = indicators['volume'] > indicators['volume_avg'] * 1.1  # كان 1.2

        # شروط RSI المحسنة
        rsi_strength_condition_buy = indicators['rsi'] > (50 + TRADING_SETTINGS['first_trade_requirements']['min_rsi_strength'])
        rsi_strength_condition_sell = indicators['rsi'] < (50 - TRADING_SETTINGS['first_trade_requirements']['min_rsi_strength'])

        # إشارة شراء محسنة مع التعديلات الجديدة
        if (ema9_cross_above_21 and 
            price_confirmation_buy and  # ✅ استخدام الشرط الجديد
            rsi_strength_condition_buy and 
            macd_status['bullish'] and 
            volume_condition):         # ✅ الحجم المخفف

            self.trend_manager.log_macd_signal(symbol, 'BASE_CROSSOVER', macd_status, 'BUY_SIGNAL')

            return {
                'symbol': symbol,
                'direction': 'LONG',
                'confidence': 0.95,
                'reason': f'تقاطع صاعد + تأكيد 20% من الشمعة السابقة + حجم 10%',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'BASE_CROSSOVER',
                'priority': 100,
                'macd_status': macd_status,
                'improved_signal': True
            }

        # إشارة بيع محسنة مع التعديلات الجديدة
        if (ema9_cross_below_21 and 
            price_confirmation_sell and  # ✅ استخدام الشرط الجديد
            rsi_strength_condition_sell and 
            macd_status['bearish'] and 
            volume_condition):          # ✅ الحجم المخفف

            self.trend_manager.log_macd_signal(symbol, 'BASE_CROSSOVER', macd_status, 'SELL_SIGNAL')

            return {
                'symbol': symbol,
                'direction': 'SHORT',
                'confidence': 0.95,
                'reason': f'تقاطع هابط + تأكيد 20% من الشمعة السابقة + حجم 10%',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'BASE_CROSSOVER',
                'priority': 100,
                'macd_status': macd_status,
                'improved_signal': True
            }

        return None    
    
    def _analyze_additional_signals(self, indicators, symbol, current_price, data, macd_status):
        """تحليل الإشارات الإضافية في الترند النشط مع الماكد"""
        signals = []
        
        # التحقق من وجود ترند نشط
        trend_status = self.trend_manager.get_trend_status(symbol)
        if not trend_status or trend_status['status'] != 'active':
            return signals
        
        trend_direction = trend_status['direction']
        
        # جميع الإشارات الإضافية تتطلب تأكيد الماكد
        if not self._check_macd_for_additional_signal(trend_direction, macd_status):
            return signals
        
        # الفرصة 1: الارتداد للمتوسط
        pullback_signal = self._analyze_pullback_signal(indicators, symbol, current_price, trend_direction, macd_status)
        if pullback_signal:
            signals.append(pullback_signal)
        
        # الفرصة 2: تأكيد الزخم
        momentum_signal = self._analyze_momentum_signal(indicators, symbol, current_price, trend_direction, data, macd_status)
        if momentum_signal:
            signals.append(momentum_signal)
        
        # الفرصة 3: كسر المستوى
        breakout_signal = self._analyze_breakout_signal(indicators, symbol, current_price, trend_direction, macd_status)
        if breakout_signal:
            signals.append(breakout_signal)
        
        # الفرصة 4: تجديد الزخم
        renewal_signal = self._analyze_renewal_signal(indicators, symbol, current_price, trend_direction, trend_status, macd_status)
        if renewal_signal:
            signals.append(renewal_signal)
        
        return signals
    
    def _check_macd_for_additional_signal(self, trend_direction, macd_status):
        """التحقق من شروط الماكد للإشارات الإضافية"""
        if not TRADING_SETTINGS['macd_required_additional']:
            return True
            
        if trend_direction == 'LONG':
            return (macd_status['macd_above_signal'] and 
                   macd_status['histogram_positive'] and
                   macd_status['histogram_increasing'])
        else:
            return (not macd_status['macd_above_signal'] and 
                   not macd_status['histogram_positive'] and
                   not macd_status['histogram_increasing'])
    
    def _analyze_pullback_signal(self, indicators, symbol, current_price, trend_direction, macd_status):
        """تحليل إشارة الارتداد للمتوسط مع الماكد"""
        # حساب المسافة من المتوسطات
        distance_to_ema9 = abs(current_price - indicators['ema9']) / indicators['ema9'] * 100
        distance_to_ema21 = abs(current_price - indicators['ema21']) / indicators['ema21'] * 100
        
        is_near_ema = distance_to_ema9 < 0.1 or distance_to_ema21 < 0.15
        
        rsi_condition = (indicators['rsi'] > 45) if trend_direction == 'LONG' else (indicators['rsi'] < 55)
        
        if is_near_ema and rsi_condition:
            self.trend_manager.log_macd_signal(symbol, 'PULLBACK', macd_status, 'ADDITIONAL_ENTRY')
            
            return {
                'symbol': symbol,
                'direction': trend_direction,
                'confidence': 0.75,
                'reason': 'ارتداد للمتوسط - السعر قرب EMA مع تأكيد الماكد',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'PULLBACK',
                'priority': 80,
                'macd_status': macd_status
            }
        
        return None
    
    def _analyze_momentum_signal(self, indicators, symbol, current_price, trend_direction, data, macd_status):
        """تحليل إشارة تأكيد الزخم مع الماكد"""
        # تحقق من 3 شموع متتالية في اتجاه الترند
        df = data.tail(3)
        if len(df) < 3:
            return None
        
        if trend_direction == 'LONG':
            consecutive_bullish = all(df['close'] > df['open'])
            rsi_trend = indicators['rsi'] > 50
        else:
            consecutive_bearish = all(df['close'] < df['open'])
            rsi_trend = indicators['rsi'] < 50
        
        if ((trend_direction == 'LONG' and consecutive_bullish and rsi_trend) or
            (trend_direction == 'SHORT' and consecutive_bearish and rsi_trend)):
            
            self.trend_manager.log_macd_signal(symbol, 'MOMENTUM', macd_status, 'ADDITIONAL_ENTRY')
            
            return {
                'symbol': symbol,
                'direction': trend_direction,
                'confidence': 0.80,
                'reason': 'تأكيد الزخم - 3 شموع متتالية في اتجاه الترند مع تأكيد الماكد',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'MOMENTUM',
                'priority': 75,
                'macd_status': macd_status
            }
        
        return None
    
    def _analyze_breakout_signal(self, indicators, symbol, current_price, trend_direction, macd_status):
        """تحليل إشارة كسر المستوى مع الماكد"""
        if trend_direction == 'LONG' and current_price > indicators['high_5']:
            self.trend_manager.log_macd_signal(symbol, 'BREAKOUT', macd_status, 'ADDITIONAL_ENTRY')
            
            return {
                'symbol': symbol,
                'direction': 'LONG',
                'confidence': 0.85,
                'reason': 'كسر مستوى - كسر أعلى قمة 5 فترات مع تأكيد الماكد',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'BREAKOUT',
                'priority': 85,
                'macd_status': macd_status
            }
        
        elif trend_direction == 'SHORT' and current_price < indicators['low_5']:
            self.trend_manager.log_macd_signal(symbol, 'BREAKOUT', macd_status, 'ADDITIONAL_ENTRY')
            
            return {
                'symbol': symbol,
                'direction': 'SHORT',
                'confidence': 0.85,
                'reason': 'كسر مستوى - كسر أدنى قاع 5 فترات مع تأكيد الماكد',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'BREAKOUT',
                'priority': 85,
                'macd_status': macd_status
            }
        
        return None
    
    def _analyze_renewal_signal(self, indicators, symbol, current_price, trend_direction, trend_status, macd_status):
        """تحليل إشارة تجديد الزخم مع الماكد"""
        trend_duration = (datetime.now(damascus_tz) - trend_status['start_time']).total_seconds() / 60
        
        if trend_duration >= 30 and 40 <= indicators['rsi'] <= 60:
            self.trend_manager.log_macd_signal(symbol, 'RENEWAL', macd_status, 'ADDITIONAL_ENTRY')
            
            return {
                'symbol': symbol,
                'direction': trend_direction,
                'confidence': 0.70,
                'reason': 'تجديد الزخم - ترند مستمر مع RSI متوازن وتأكيد الماكد',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'RENEWAL',
                'priority': 70,
                'macd_status': macd_status
            }
        
        return None


class TelegramNotifier:
    """مدير إشعارات التلغرام محسّن"""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.last_message_time = {}
        self.min_interval = 2  # الحد الأدنى بين الإشعارات (ثواني)
    
    def _can_send_message(self, chat_id):
        """التحقق من إمكانية إرسال الرسالة بناءً على الوقت"""
        current_time = time.time()
        if chat_id in self.last_message_time:
            time_since_last = current_time - self.last_message_time[chat_id]
            if time_since_last < self.min_interval:
                time.sleep(self.min_interval - time_since_last)
        
        self.last_message_time[chat_id] = current_time
        return True
    
    def send_message(self, message, message_type='info', max_retries=3):
        """إرسال رسالة مع معالجة محسنة للأخطاء"""
        try:
            if not self.token or not self.chat_id:
                logger.warning("⚠️ مفاتيح Telegram غير موجودة")
                return False
            
            # التحقق من الوقت بين الرسائل
            if not self._can_send_message(self.chat_id):
                return False
            
            if not message or len(message.strip()) == 0:
                logger.warning("⚠️ محاولة إرسال رسالة فارغة")
                return False
            
            # تقليم الرسالة إذا كانت طويلة جداً
            if len(message) > 4096:
                message = message[:4090] + "..."
            
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            # إعادة المحاولة عند الفشل
            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        f"{self.base_url}/sendMessage", 
                        json=payload, 
                        timeout=15
                    )
                    
                    if response.status_code == 200:
                        logger.info(f"✅ تم إرسال إشعار Telegram بنجاح")
                        return True
                    else:
                        logger.warning(f"⚠️ فشل إرسال إشعار Telegram (المحاولة {attempt + 1}): {response.status_code}")
                        
                        if response.status_code == 429:  # Too Many Requests
                            retry_after = response.json().get('parameters', {}).get('retry_after', 30)
                            logger.info(f"⏳ انتظار {retry_after} ثانية بسبب الحد الأقصى للطلبات")
                            time.sleep(retry_after)
                        else:
                            time.sleep(2 ** attempt)  # Exponential backoff
                            
                except requests.exceptions.Timeout:
                    logger.warning(f"⚠️ انتهت مهلة إرسال Telegram (المحاولة {attempt + 1})")
                    time.sleep(2 ** attempt)
                except requests.exceptions.ConnectionError:
                    logger.warning(f"⚠️ خطأ اتصال Telegram (المحاولة {attempt + 1})")
                    time.sleep(2 ** attempt)
                except Exception as e:
                    logger.error(f"❌ خطأ غير متوقع في إرسال Telegram (المحاولة {attempt + 1}): {e}")
                    time.sleep(2 ** attempt)
            
            logger.error(f"❌ فشل جميع محاولات إرسال Telegram")
            return False
                
        except Exception as e:
            logger.error(f"❌ خطأ حرج في إرسال رسالة تلغرام: {e}")
            return False

    def send_signal_alert(self, symbol, signal, current_price, trend_status=None):
        """إرسال إشعار إشارة مع تحسينات الأمان"""
        try:
            # التحقق من صحة البيانات
            if not symbol or not signal or current_price is None:
                logger.error(f"❌ بيانات غير كافية لإرسال إشعار: symbol={symbol}, signal={bool(signal)}, price={current_price}")
                return False
            
            if signal.get('signal_type') == 'CROSSOVER_PREDICTION':
                return self.send_prediction_alert(symbol, signal, current_price)
            
            # التحقق من البيانات المطلوبة
            required_fields = ['direction', 'signal_type', 'confidence', 'reason']
            for field in required_fields:
                if field not in signal:
                    logger.error(f"❌ حقل مفقود في الإشارة: {field}")
                    return False

            direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
            signal_type_emoji = {
                'BASE_CROSSOVER': '🎯',
                'PULLBACK': '📈', 
                'MOMENTUM': '⚡',
                'BREAKOUT': '🚀',
                'RENEWAL': '🔄',
                'PREDICTED_CROSSOVER': '🔮'
            }.get(signal['signal_type'], '📊')
        
            # معلومات الماكد
            macd_info = ""
            if 'macd_status' in signal and signal['macd_status']:
                macd = signal['macd_status']
                macd_emoji = "🟢" if macd.get('bullish', False) else "🔴"
                histogram_emoji = "📈" if macd.get('histogram_increasing', False) else "📉"
                macd_info = (
                    f"🔮 <b>تحليل الماكد:</b>\n"
                    f"• الحالة: {macd_emoji} {'صاعد' if macd.get('bullish', False) else 'هابط'}\n"
                    f"• الماكد: {macd.get('macd', 0):.6f}\n"
                    f"• الإشارة: {macd.get('signal', 0):.6f}\n"
                    f"• الهيستوجرام: {histogram_emoji} {macd.get('histogram', 0):.6f}\n"
                )
        
            trend_info = ""
            if trend_status and isinstance(trend_status, dict):
                try:
                    trend_duration = (datetime.now(damascus_tz) - trend_status['start_time']).total_seconds() / 60
                    trend_info = (
                        f"📊 <b>حالة الترند:</b>\n"
                        f"• الصفقات: {trend_status.get('trades_count', 0)}\n"
                        f"• المدة: {trend_duration:.1f} دقيقة\n"
                        f"• إجمالي PnL: {trend_status.get('total_pnl', 0):+.2f}%\n"
                        f"• تأكيدات الماكد: {trend_status.get('macd_confirmations', 0)}\n"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ خطأ في معالجة بيانات الترند: {e}")
        
            message = (
                f"{direction_emoji} <b>إشارة تداول جديدة</b> {signal_type_emoji}\n"
                f"العملة: {symbol}\n"
                f"الاتجاه: {signal['direction']}\n"
                f"النوع: {signal['signal_type']}\n"
                f"السعر: ${current_price:.4f}\n"
                f"الثقة: {signal.get('confidence', 0):.2%}\n"
                f"السبب: {signal.get('reason', 'غير محدد')}\n"
                f"📊 المؤشرات:\n"
                f"• EMA 9: {signal['indicators'].get('ema9', 0):.4f}\n"
                f"• EMA 21: {signal['indicators'].get('ema21', 0):.4f}\n"
                f"• RSI: {signal['indicators'].get('rsi', 0):.1f}\n"
                f"{macd_info}"
                f"{trend_info}"
                f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
        
            return self.send_message(message)
        
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال إشعار الإشارة: {e}")
            return False

    def send_trade_closed_alert(self, symbol, trade_data, close_reason, pnl_pct):
        """إرسال إشعار إغلاق صفقة محسّن"""
        try:
            if not trade_data or not symbol:
                logger.error("❌ بيانات غير كافية لإشعار الإغلاق")
                return False
            
            direction = trade_data.get('side', 'UNKNOWN')
            entry_price = trade_data.get('entry_price', 0)
            close_price = trade_data.get('close_price', 0)
            
            pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
            
            message = (
                f"🔒 <b>إغلاق صفقة</b>\n"
                f"العملة: {symbol}\n"
                f"الاتجاه: {direction}\n"
                f"سعر الدخول: ${entry_price:.4f}\n"
                f"سعر الخروج: ${close_price:.4f}\n"
                f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                f"السبب: {close_reason}\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            
            return self.send_message(message)
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال إشعار الإغلاق: {e}")
            return False           

            

class AdvancedMACDTradeManager:
    def __init__(self, client, notifier, trend_manager, bot_instance=None):
        self.client = client
        self.notifier = notifier
        self.precision_manager = PrecisionManager(client)
        self.trend_manager = trend_manager
        self.bot_instance = bot_instance
        self.active_trades = {}
        self.monitoring_active = True
        self.last_monitor_check = datetime.now(damascus_tz)
        
        # تأخير بدء المراقبة لضمان اكتمال التهيئة
        threading.Timer(5.0, self.start_trade_monitoring).start()
        
    def _get_current_price(self, symbol):
        """الحصول على السعر الحالي مع إعادة المحاولة"""
        for attempt in range(3):
            try:
                ticker = self.client.futures_symbol_ticker(symbol=symbol)
                price = float(ticker['price'])
                if price > 0:
                    return price
            except Exception as e:
                if attempt == 2:
                    logger.error(f"❌ خطأ في الحصول على سعر {symbol}: {e}")
                time.sleep(1)
        return None
    
    def calculate_trade_limits(self, symbol, direction, entry_price):
        """حساب حدود الصفقة"""
        try:
            target_pct = TRADING_SETTINGS['target_profit_pct'] / 100
            stop_pct = TRADING_SETTINGS['stop_loss_pct'] / 100
            
            if direction == 'LONG':
                take_profit = entry_price * (1 + target_pct)
                stop_loss = entry_price * (1 - stop_pct)
            else:
                take_profit = entry_price * (1 - target_pct)
                stop_loss = entry_price * (1 + stop_pct)
            
            take_profit = self.precision_manager.adjust_price(symbol, take_profit)
            stop_loss = self.precision_manager.adjust_price(symbol, stop_loss)
            
            return take_profit, stop_loss
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حدود الصفقة: {e}")
            if direction == 'LONG':
                return entry_price * 1.002, entry_price * 0.998
            else:
                return entry_price * 0.998, entry_price * 1.002
    
    def check_and_handle_opposite_signals(self, symbol, new_direction):
        """التحقق من وجود صفقة معاكسة وإغلاقها - مصحح"""
        try:
            if not self.is_symbol_trading(symbol):
                return False
        
            current_trade = self.get_trade(symbol)
    
            # فحص إضافي للتأكد من وجود الصفقة
            if not current_trade or current_trade['status'] != 'open':
                return False
        
            current_direction = current_trade['side']
    
            # إذا كانت الإشارة الجديدة معاكسة للصفقة الحالية
            if current_direction != new_direction:
                current_price = self._get_current_price(symbol)
                if not current_price:
                    logger.error(f"❌ فشل الحصول على سعر {symbol} بعد 3 محاولات")
                    return True  # 🔴 التصحيح: منع فتح صفقة جديدة إذا لم نحصل على السعر
            
                logger.info(f"🔄 إشارة معاكسة لـ {symbol}: {current_direction} -> {new_direction}")
            
                # حساب PnL الحالي
                entry_price = current_trade['entry_price']
                if current_direction == 'LONG':
                    current_pnl = (current_price - entry_price) / entry_price * 100
                else:
                    current_pnl = (entry_price - current_price) / entry_price * 100
            
                # إغلاق الصفقة الحالية
                close_reason = f"إشارة معاكسة ({new_direction}) - PnL: {current_pnl:+.2f}%"
                close_success = self.close_trade(symbol, close_reason, current_price)
            
                if close_success:
                    # إنهاء الترند الحالي
                    self.trend_manager.end_trend(symbol, "إشارة معاكسة")
                
                    # زيادة وقت الانتظار
                    logger.info(f"⏳ انتظار 10 ثوانٍ بعد إغلاق الصفقة المعاكسة")
                    time.sleep(10)
                    return True  # 🔴 التصحيح: تم إغلاق صفقة معاكسة
                else:
                    logger.error(f"❌ فشل إغلاق الصفقة المعاكسة لـ {symbol}")
                    return True  # 🔴 التصحيح: منع فتح صفقة جديدة حتى لو فشل الإغلاق
    
            return False
    
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الإشارات المعاكسة لـ {symbol}: {e}")
            return True  # 🔴 التصحيح: في حالة الخطأ، منع فتح صفقات جديدة

    def enhanced_trade_monitoring(self):
        """مراقبة محسنة للصفقات مع معالجة الأخطاء - مصححة ومحسنة"""
        try:
            current_time = datetime.now(damascus_tz)
            self.last_monitor_check = current_time
        
            # معالجة أخطاء جلب بيانات الحساب
            try:
                account_info = self.client.futures_account()
                positions = {p['symbol']: float(p['positionAmt']) for p in account_info['positions']}
            except Exception as e:
                logger.error(f"❌ فشل جلب بيانات الحساب للمراقبة: {e}")
                return
        
            # نسخ القائمة لتجنب التعديل أثناء التكرار
            for symbol, trade in list(self.active_trades.items()):
                if trade.get('status') != 'open':
                    continue
              
                current_price = self._get_current_price(symbol)
                if not current_price:
                    logger.warning(f"⚠️ لا يمكن الحصول على السعر الحالي لـ {symbol}")
                    continue
            
                # التحقق من وقف الخسارة وجني الربح
                should_close = False
                close_reason = ""
                entry_price = trade.get('entry_price', 0)
            
                if entry_price == 0:
                    logger.warning(f"⚠️ سعر الدخول صفر لـ {symbol}")
                    continue
            
                if trade['side'] == 'LONG':
                    if current_price <= trade.get('stop_loss_price', 0):
                        should_close = True
                        close_reason = f"وقف خسارة ({current_price:.4f} <= {trade['stop_loss_price']:.4f})"
                    elif current_price >= trade.get('take_profit_price', float('inf')):
                        should_close = True
                        close_reason = f"جني ربح ({current_price:.4f} >= {trade['take_profit_price']:.4f})"
                
                else:  # SHORT
                    if current_price >= trade.get('stop_loss_price', float('inf')):
                        should_close = True
                        close_reason = f"وقف خسارة ({current_price:.4f} >= {trade['stop_loss_price']:.4f})"
                    elif current_price <= trade.get('take_profit_price', 0):
                        should_close = True
                        close_reason = f"جني ربح ({current_price:.4f} <= {trade['take_profit_price']:.4f})"
            
                # التحقق من المدة
                trade_duration = (current_time - trade['timestamp']).total_seconds() / 60
                if trade_duration >= TRADING_SETTINGS['max_trade_duration_minutes']:
                    should_close = True
                    close_reason = f"انتهت المدة ({trade_duration:.1f} دقيقة)"
            
                # إغلاق الصفقة إذا لزم الأمر
                if should_close:
                    logger.info(f"🔄 محاولة إغلاق {symbol}: {close_reason}")
                    success = self.close_trade(symbol, close_reason, current_price)
            
                    if not success:
                        logger.warning(f"⚠️ فشل الإغلاق الأول لـ {symbol}, إعادة المحاولة...")
                        # محاولة ثانية بعد 5 ثواني
                        time.sleep(5)
                        current_price_retry = self._get_current_price(symbol)
                        if current_price_retry:
                            self.close_trade(symbol, f"إعادة محاولة - {close_reason}", current_price_retry)
                        
        except Exception as e:
            logger.error(f"❌ خطأ في المراقبة المحسنة: {e}")  
        
    def start_trade_monitoring(self):
        """بدء مراقبة الصفقات مع المراقبة المحسنة"""
        def monitor():
            while self.monitoring_active:
                try:
                    self.enhanced_trade_monitoring()
                    self._cleanup_closed_trades()
                    self.trend_manager.cleanup_expired_trends()
                    self.last_monitor_check = datetime.now(damascus_tz)
                    time.sleep(10)
                except Exception as e:
                    logger.error(f"❌ خطأ في المراقبة: {e}")
                    time.sleep(30)
        
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
                    
    def _check_limits_and_duration(self):
        """التحقق من الحدود والمدة مع الإغلاق المبكر بالماكد - معدل"""
        current_time = datetime.now(damascus_tz)
    
        for symbol, trade in list(self.active_trades.items()):
            if trade['status'] != 'open':
                continue
        
            current_price = self._get_current_price(symbol)
            if not current_price:
                continue
        
            # التصحيح: التحقق من وقف الخسارة وجني الربح أولاً
            entry_price = trade['entry_price']
            direction = trade['side']
        
            if direction == 'LONG':
                pnl_pct = (current_price - entry_price) / entry_price * 100
            
                # التحقق من وقف الخسارة أولاً
                if current_price <= trade['stop_loss_price']:
                    self.close_trade(symbol, f"وقف الخسارة ({pnl_pct:+.2f}%)", current_price)
                    continue
                
                # ثم جني الربح
                if current_price >= trade['take_profit_price']:
                    self.close_trade(symbol, f"جني الربح ({pnl_pct:+.2f}%)", current_price)
                    continue
                
            else:  # SHORT
                pnl_pct = (entry_price - current_price) / entry_price * 100
            
                # التحقق من وقف الخسارة أولاً
                if current_price >= trade['stop_loss_price']:
                    self.close_trade(symbol, f"وقف الخسارة ({pnl_pct:+.2f}%)", current_price)
                    continue
                
                # ثم جني الربح
                if current_price <= trade['take_profit_price']:
                    self.close_trade(symbol, f"جني الربح ({pnl_pct:+.2f}%)", current_price)
                    continue
        
            # ثم التحقق من الإغلاق المبكر بالماكد
            if TRADING_SETTINGS['macd_early_exit']:
                macd_data = self._get_current_macd_data(symbol)
                if macd_data and self._check_macd_early_exit(symbol, trade, macd_data, current_price):
                    continue
        
            # أخيراً التحقق من المدة
            trade_duration = (current_time - trade['timestamp']).total_seconds() / 60
            if trade_duration >= TRADING_SETTINGS['max_trade_duration_minutes']:
                self.close_trade(symbol, f"انتهت المدة ({trade_duration:.1f} دقيقة)", current_price)
                continue
                
    def _get_current_macd_data(self, symbol):
        """الحصول على بيانات الماكد الحالية - مصححة"""
        try:
            # استخدام المرجع الممرر بدلاً من الاستيراد الدائري
            if self.bot_instance:
                data = self.bot_instance.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 26)
                if data is not None and len(data) >= 26:
                    signal_generator = AdvancedMACDSignalGenerator()
                    indicators = signal_generator._calculate_advanced_indicators(data)
                    return signal_generator._analyze_macd_status(indicators, data)
        
            # حل بديل إذا لم يكن bot_instance متوفراً
            data = self._get_historical_data_direct(symbol)
            if data is not None and len(data) >= 26:
                signal_generator = AdvancedMACDSignalGenerator()
                indicators = signal_generator._calculate_advanced_indicators(data)
                return signal_generator._analyze_macd_status(indicators, data)
            
        except Exception as e:
            logger.error(f"❌ خطأ في جلب بيانات الماكد لـ {symbol}: {e}")
        return None

    def _get_historical_data_direct(self, symbol):
        """دالة مساعدة لجلب البيانات التاريخية مباشرة"""
        try:
            klines = self.client.futures_klines(
                symbol=symbol,
                interval=TRADING_SETTINGS['data_interval'],
                limit=50
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
            logger.error(f"❌ خطأ في جلب البيانات المباشرة لـ {symbol}: {e}")
            return None

    def _check_macd_early_exit(self, symbol, trade, macd_data, current_price):
        """التحقق من الإغلاق المبكر بالماكد - مصححة"""
        try:
            if not macd_data:
                return False
            
            # الحصول على بيانات RSI الحالية
            data = self._get_historical_data_direct(symbol)
            if data is not None and len(data) >= 15:
                # حساب RSI بشكل آمن
                current_rsi = self._calculate_rsi_safe(data['close'].tail(15), 14)
            
                should_exit, reason = self.trend_manager.should_early_exit(symbol, macd_data, current_rsi)
                if should_exit:
                    self.close_trade(symbol, f"إغلاق مبكر: {reason}", current_price)
                    return True
                
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الإغلاق المبكر لـ {symbol}: {e}")
    
        return False

    def _calculate_rsi_safe(self, prices, period):
        """حساب RSI آمن مع معالجة الأخطاء"""
        try:
            if len(prices) < period + 1:
                return 50.0
            
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).fillna(0)
            loss = (-delta.where(delta < 0, 0)).fillna(0)
        
            avg_gain = gain.rolling(window=period, min_periods=1).mean()
            avg_loss = loss.rolling(window=period, min_periods=1).mean()
        
            rs = avg_gain / (avg_loss + 1e-10)
            rsi = 100 - (100 / (1 + rs))
        
            return float(rsi.iloc[-1]) if not rsi.empty else 50.0
        
        except Exception as e:
            logger.error(f"❌ خطأ في حساب RSI: {e}")
            return 50.0
            
    def _cleanup_closed_trades(self):
        """تنظيف الصفقات المغلقة"""
        try:
            account_info = self.client.futures_account()
            positions = account_info['positions']
            
            active_symbols = set()
            for position in positions:
                if float(position['positionAmt']) != 0:
                    active_symbols.add(position['symbol'])
            
            for symbol in list(self.active_trades.keys()):
                if symbol not in active_symbols and self.active_trades[symbol]['status'] == 'open':
                    self._handle_external_close(symbol)
                    
        except Exception as e:
            logger.error(f"❌ خطأ في التنظيف: {e}")
    
    def _handle_external_close(self, symbol):
        """معالجة الإغلاق الخارجي"""
        try:
            trade = self.active_trades[symbol]
            current_price = self._get_current_price(symbol)
            
            if current_price:
                entry_price = trade['entry_price']
                if trade['side'] == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
            else:
                pnl_pct = 0
            
            # تحديث الترند
            self.trend_manager.update_trend_pnl(symbol, pnl_pct)
            
            trade.update({
                'status': 'closed',
                'close_price': current_price,
                'close_time': datetime.now(damascus_tz),
                'pnl_pct': pnl_pct,
                'close_reason': 'إغلاق خارجي'
            })
            
            logger.info(f"✅ معالجة إغلاق خارجي لـ {symbol} - PnL: {pnl_pct:+.2f}%")
            
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة الإغلاق الخارجي: {e}")
    
    def close_trade(self, symbol, reason, current_price):
        """إغلاق الصفقة مع تحسين الإشعارات ومعالجة الأخطاء"""
        try:
            # التحقق من وجود الصفقة
            trade = self.active_trades.get(symbol)
            if not trade:
                logger.warning(f"⚠️ لا توجد صفقة نشطة لـ {symbol}")
                return False
            
            if trade['status'] != 'open':
                logger.warning(f"⚠️ صفقة {symbol} ليست مفتوحة (الحالة: {trade['status']})")
                return False
        
            # التحقق من البيانات المطلوبة
            required_fields = ['quantity', 'side', 'entry_price']
            for field in required_fields:
                if field not in trade:
                    logger.error(f"❌ حقل مفقود في صفقة {symbol}: {field}")
                    return False
        
            quantity = trade['quantity']
            direction = trade['side']
            entry_price = trade['entry_price']
        
            # التحقق من صحة البيانات
            if quantity <= 0:
                logger.error(f"❌ كمية غير صالحة لـ {symbol}: {quantity}")
                return False
            
            if entry_price <= 0:
                logger.error(f"❌ سعر دخول غير صالح لـ {symbol}: {entry_price}")
                return False
            
            if current_price <= 0:
                logger.error(f"❌ سعر حالى غير صالح لـ {symbol}: {current_price}")
                return False
        
            # تنفيذ أمر الإغلاق
            close_side = 'SELL' if direction == 'LONG' else 'BUY'
        
            logger.info(f"🔄 محاولة إغلاق {symbol}: {direction} -> {close_side}, الكمية: {quantity}")
        
            order = self.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='MARKET',
                quantity=quantity,
                reduceOnly=True
            )
        
            if order and order['orderId']:
                # حساب الربح/الخسارة
                if direction == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
            
                # تحديث الترند
                self.trend_manager.update_trend_pnl(symbol, pnl_pct)
            
                # تحديث بيانات الصفقة
                trade.update({
                    'status': 'closed',
                    'close_price': current_price,
                    'close_time': datetime.now(damascus_tz),
                    'pnl_pct': pnl_pct,
                    'close_reason': reason,
                    'order_id': order['orderId']
                })
            
                # إرسال إشعار محسّن
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    trend_status = self.trend_manager.get_trend_status(symbol)
                
                    trend_info = ""
                    if trend_status:
                        trend_duration = (datetime.now(damascus_tz) - trend_status['start_time']).total_seconds() / 60
                        trend_info = (
                            f"📊 <b>حالة الترند:</b>\n"
                            f"• الصفقات: {trend_status['trades_count']}\n"
                            f"• المدة: {trend_duration:.1f} دقيقة\n"
                            f"• إجمالي PnL: {trend_status.get('total_pnl', 0):+.2f}%\n"
                            f"• الناجحة: {trend_status.get('successful_trades', 0)}\n"
                            f"• الفاشلة: {trend_status.get('failed_trades', 0)}\n"
                        )
                
                    # معلومات الصفقة
                    trade_duration = (datetime.now(damascus_tz) - trade['timestamp']).total_seconds() / 60
                
                    message = (
                        f"🔒 <b>إغلاق صفقة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${entry_price:.4f}\n"
                        f"سعر الخروج: ${current_price:.4f}\n"
                        f"المدة: {trade_duration:.1f} دقيقة\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"{trend_info}"
                        f"السبب: {reason}\n"
                        f"رقم الأمر: {order['orderId']}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                
                    # إرسال الإشعار مع إعادة المحاولة
                    notification_sent = self.notifier.send_message(message, 'trade_close')
                    if not notification_sent:
                        logger.warning(f"⚠️ فشل إرسال إشعار إغلاق لـ {symbol}")
            
                logger.info(f"✅ تم إغلاق صفقة {symbol} - {reason} - PnL: {pnl_pct:+.2f}%")
                        
            
                return True
            else:
                logger.error(f"❌ فشل إنشاء أمر إغلاق لـ {symbol}")
                return False
        
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {symbol}: {e}")
        
            # محاولة إرسال إشعار خطأ
            try:
                if self.notifier:
                    error_message = (
                        f"❌ <b>فشل إغلاق صفقة</b>\n"
                        f"العملة: {symbol}\n"
                        f"السبب: {str(e)[:100]}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(error_message, 'error')
            except:
                pass
            
            return False
    
    def add_trade(self, symbol, trade_data, signal_type, macd_status):
        """إضافة صفقة جديدة مع بيانات الماكد"""
        try:
            take_profit, stop_loss = self.calculate_trade_limits(
                symbol, trade_data['side'], trade_data['entry_price']
            )
            
            trade_data.update({
                'take_profit_price': take_profit,
                'stop_loss_price': stop_loss,
                'status': 'open',
                'timestamp': datetime.now(damascus_tz),
                'signal_type': signal_type,
                'macd_status': macd_status
            })
            
            self.active_trades[symbol] = trade_data
            
            logger.info(f"✅ تمت إضافة صفقة {symbol} - نوع: {signal_type} | الماكد: {macd_status['bullish']}")
            logger.info(f"  🎯 جني الربح: ${take_profit:.4f}")
            logger.info(f"  🛡️ وقف الخسارة: ${stop_loss:.4f}")
            
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة صفقة: {e}")
    
    def get_trade(self, symbol):
        """الحصول على صفقة"""
        return self.active_trades.get(symbol)
    
    def get_active_trades_count(self):
        """عدد الصفقات النشطة"""
        return len([t for t in self.active_trades.values() if t['status'] == 'open'])
    
    def is_symbol_trading(self, symbol):
        """التحقق إذا كانت العملة متداولة"""
        return symbol in self.active_trades and self.active_trades[symbol]['status'] == 'open'
    
    def get_all_trades(self):
        """جميع الصفقات"""
        return self.active_trades.copy()
    
    def stop_monitoring(self):
        """إيقاف المراقبة"""
        self.monitoring_active = False

class AdvancedMACDTrendBot:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            # إنشاء نسخة جديدة إذا لم تكن موجودة
            try:
                cls._instance = cls()
            except Exception as e:
                logger.error(f"❌ فشل إنشاء نسخة البوت: {e}")
                return None
        return cls._instance

    def __init__(self):
        if AdvancedMACDTrendBot._instance is not None:
            raise Exception("هذه الفئة تستخدم نمط Singleton")
        
        # أولاً: الحصول على مفاتيح API
        self.api_key = os.environ.get('BINANCE_API_KEY')
        self.api_secret = os.environ.get('BINANCE_API_SECRET')
        self.telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        
        if not all([self.api_key, self.api_secret]):
            raise ValueError("مفاتيح Binance مطلوبة")
        
        # ثانياً: تهيئة عميل Binance
        try:
            self.client = Client(self.api_key, self.api_secret)
            self.test_connection()
        except Exception as e:
            logger.error(f"❌ فشل تهيئة العميل: {e}")
            raise

        # ثالثاً: تهيئة النظام المتطور مع الماكد (مرة واحدة فقط)
        self.signal_generator = AdvancedMACDSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trend_manager = self.signal_generator.trend_manager
        
        # رابعاً: تهيئة مدير الصفقات مع تمرير المرجع
        self.trade_manager = AdvancedMACDTradeManager(
            self.client, 
            self.notifier, 
            self.trend_manager,
            self  # تمرير المرجع الذاتي
        )
        
        # إحصائيات الأداء
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'daily_trades_count': 0,
            'total_trends': 0,
            'successful_trends': 0,
            'macd_early_exits': 0,
            'macd_filtered_signals': 0,
        }
        self.last_trade_times = {}
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        self.alert_status = {}

        self.performance_stats.update({
            'predicted_trades': 0,
            'successful_predictions': 0,
            'failed_predictions': 0,
            'macd_early_exits': 0,
            'macd_filtered_signals': 0,
        })
        
        AdvancedMACDTrendBot._instance = self
        logger.info("✅ تم تهيئة بوت الماكد المتقدم بنجاح")

    def test_connection(self):
        """اختبار الاتصال"""
        try:
            self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise

    def prepare_for_impending_crossover(self, symbol, prediction):
        """التحضير الاستباقي للتقاطع المتوقع"""
    
        # 1. إغلاق أي صفقات معاكسة فوراً
        if prediction['direction'] == 'LONG':
            self.trade_manager.check_and_handle_opposite_signals(symbol, 'LONG')
        else:
            self.trade_manager.check_and_handle_opposite_signals(symbol, 'SHORT')
    
        # 2. تعيين الرافعة المالية مسبقاً
        self.set_leverage(symbol, TRADING_SETTINGS['max_leverage'])
    
        # 3. حساب حجم المركز مسبقاً
        current_price = self.get_current_price(symbol)
        pre_calculated_quantity = self.calculate_position_size(symbol, current_price)
    
        # 4. تسجيل حالة التأهب في النظام
        self.alert_status[symbol] = {
            'prediction': prediction,
            'pre_calculated_quantity': pre_calculated_quantity,
            'alert_time': datetime.now(damascus_tz),
            'status': 'AWAITING_CROSSOVER'
        }
    
        logger.info(f"🟡 حالة تأهب لـ {symbol}: تقاطع {prediction['direction']} متوقع خلال {prediction['expected_time']}")

    def intensive_monitoring_mode(self, symbol, prediction):
        """تفعيل وضع المراقبة المكثفة للعملة"""
    
        # زيادة وتيرة المسح لهذه العملة
        monitoring_interval = 15  # ثانية بدلاً من دقيقة
    
        def intensive_scan():
            scan_count = 0
            while (scan_count < 10 and 
                   symbol in self.alert_status and 
                   self.alert_status[symbol]['status'] == 'AWAITING_CROSSOVER'):
            
                # مسح مكثف كل 15 ثانية
                data = self.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 10)
                current_price = self.get_current_price(symbol)
            
                if data is not None and current_price:
                    # التحقق من حدوث التقاطع فعلياً
                    crossover_occurred = self._check_crossover_occurrence(data, prediction)
                
                    if crossover_occurred:
                        self._execute_immediate_trade(symbol, prediction, data, current_price)
                        break
            
                scan_count += 1
                time.sleep(monitoring_interval)
    
        # تشغيل المراقبة المكثفة في thread منفصل
        threading.Thread(target=intensive_scan, daemon=True).start()

    def _execute_immediate_trade(self, symbol, prediction, data, current_price):
        """تنفيذ فوري عند تأكيد التقاطع"""
    
        try:
            # 1. إعادة حساب المؤشرات للتأكيد النهائي
            indicators = self.signal_generator._calculate_advanced_indicators(data)
            macd_status = self.signal_generator._analyze_macd_status(indicators, data)
        
            # 2. التحقق من شروط الصفقة المحسنة
            if not self._validate_enhanced_conditions(indicators, macd_status, prediction):
                logger.warning(f"⏹️ شروط التقاطع لم تتوفر لـ {symbol}")
                self.alert_status[symbol]['status'] = 'CANCELLED'
            
                # إرسال إشعار الإلغاء
                if self.notifier:
                    self.notifier.send_enhanced_prediction_alerts(symbol, prediction, "CANCELLED")
                return False
        
            # 3. إنشاء إشارة تداول فورية
            immediate_signal = {
                'symbol': symbol,
                'direction': prediction['direction'],
                'confidence': min(prediction['probability'] + 0.1, 0.99),  # زيادة الثقة
                'reason': f'تقاطع مؤكد بعد تنبؤ - {prediction["expected_time"]}',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'PREDICTED_CROSSOVER',
                'priority': 95,  # أولوية عالية جداً
                'macd_status': macd_status,
                'prediction_accuracy': prediction['probability']
            }
        
            # 4. تنفيذ الصفقة فوراً
            trade_executed = self.execute_trade(immediate_signal)
        
            if trade_executed:
                # 5. تحديث حالة النظام
                self.alert_status[symbol]['status'] = 'EXECUTED'
                self.alert_status[symbol]['execution_time'] = datetime.now(damascus_tz)
            
                # 6. إحصائية النجاح
                self.performance_stats['predicted_trades'] = self.performance_stats.get('predicted_trades', 0) + 1
                self.performance_stats['successful_predictions'] = self.performance_stats.get('successful_predictions', 0) + 1
            
                # 7. إرسال إشعار النجاح
                if self.notifier:
                    self.notifier.send_enhanced_prediction_alerts(symbol, prediction, "EXECUTION")
            
                logger.info(f"✅ تنفيذ ناجح للتقاطع المتوقع لـ {symbol}")
                return True
            else:
                self.alert_status[symbol]['status'] = 'FAILED'
                return False
            
        except Exception as e:
            logger.error(f"❌ فشل التنفيذ الفوري لـ {symbol}: {e}")
            self.alert_status[symbol]['status'] = 'ERROR'
            return False

    def _validate_enhanced_conditions(self, indicators, macd_status, prediction):
        """تحقق محسن من شروط التقاطع"""
    
        # شروط إضافية للتقاطع المؤكد
        conditions = []
    
        if prediction['direction'] == 'LONG':
            conditions.append(indicators['ema9'] > indicators['ema21'])  # التقاطع حدث
            conditions.append(indicators['rsi'] > 45)  # RSI معقول
            conditions.append(macd_status['bullish'])  # MACD يؤكد
            conditions.append(indicators['volume'] > indicators['volume_avg'] * 1.1)  # حجم جيد
        else:
            conditions.append(indicators['ema9'] < indicators['ema21'])  # التقاطع حدث
            conditions.append(indicators['rsi'] < 55)  # RSI معقول
            conditions.append(macd_status['bearish'])  # MACD يؤكد
            conditions.append(indicators['volume'] > indicators['volume_avg'] * 1.1)  # حجم جيد
    
        return all(conditions)

    def _handle_crossover_prediction(self, prediction_signal):
        """معالجة إشارات التنبؤ بالتقاطع"""
        try:
            symbol = prediction_signal['symbol']
        
            # إذا كانت الاحتمالية عالية جداً
            if prediction_signal['probability'] >= 0.85:
                # تفعيل النظام الاستباقي
                self.prepare_for_impending_crossover(symbol, prediction_signal)
                self.intensive_monitoring_mode(symbol, prediction_signal)
            
                # إرسال إشعار التأهب
                if self.notifier:
                    self.notifier.send_enhanced_prediction_alerts(
                        symbol, prediction_signal, "ALERT"
                    )
            
                logger.info(f"🚨 تفعيل النظام الاستباقي لـ {symbol} - احتمالية: {prediction_signal['probability']:.1%}")
            
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة تنبؤ التقاطع: {e}")

    def _check_crossover_occurrence(self, data, prediction):
        """التحقق من حدوث التقاطع فعلياً"""
        try:
            indicators = self.signal_generator._calculate_advanced_indicators(data)
        
            if prediction['direction'] == 'LONG':
                # تحقق من التقاطع الصاعد
                crossover_occurred = (indicators['ema9'] > indicators['ema21'] and 
                                    indicators['ema9_prev'] <= indicators['ema21_prev'])
            else:
                # تحقق من التقاطع الهابط
                crossover_occurred = (indicators['ema9'] < indicators['ema21'] and 
                                    indicators['ema9_prev'] >= indicators['ema21_prev'])
        
            return crossover_occurred
        
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من حدوث التقاطع: {e}")
            return False

    def cleanup_prediction_alerts(self):
        """تنظيف تنبيهات التنبؤ القديمة"""
        try:
            current_time = datetime.now(damascus_tz)
            alerts_to_remove = []
        
            for symbol, alert in self.alert_status.items():
                alert_age = (current_time - alert['alert_time']).total_seconds() / 60
            
                # إزالة التنبيهات الأقدم من 30 دقيقة
                if alert_age > 30:
                    alerts_to_remove.append(symbol)
            
                # إلغاء التنبيهات التي لم تنفذ خلال الوقت المتوقع
                elif (alert['status'] == 'AWAITING_CROSSOVER' and 
                      alert_age > 10):  # أكثر من 10 دقائق بدون تنفيذ
                    alerts_to_remove.append(symbol)
                    self.performance_stats['failed_predictions'] = self.performance_stats.get('failed_predictions', 0) + 1
                
                    if self.notifier:
                        self.notifier.send_enhanced_prediction_alerts(
                            symbol, alert['prediction'], "CANCELLED"
                        )
        
            for symbol in alerts_to_remove:
                del self.alert_status[symbol]
            
        except Exception as e:
            logger.error(f"❌ خطأ في تنظيف تنبيهات التنبؤ: {e}")

    def get_prediction_status(self):
        """الحصول على حالة التنبؤات الحالية"""
        return {
            'active_predictions': self.alert_status,
            'prediction_stats': {
                'total_predicted': self.performance_stats.get('predicted_trades', 0),
                'successful': self.performance_stats.get('successful_predictions', 0),
                'failed': self.performance_stats.get('failed_predictions', 0)
            }
        }

    def get_real_time_balance(self):
        """جلب الرصيد الحالي"""
        try:
            account_info = self.client.futures_account()
            return {
                'total_balance': float(account_info['totalWalletBalance']),
                'available_balance': float(account_info['availableBalance']),
                'timestamp': datetime.now(damascus_tz)
            }
        except Exception as e:
            logger.error(f"❌ فشل جلب الرصيد: {e}")
            return {'total_balance': 100.0, 'available_balance': 100.0}

    def start_services(self):
        """بدء الخدمات المساعدة"""
        def sync_thread():
            while True:
                try:
                    self.trade_manager._cleanup_closed_trades()
                    self.trend_manager.cleanup_expired_trends()
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(60)
    
        threading.Thread(target=sync_thread, daemon=True).start()
        
        # الجدولة
        if self.notifier:
            schedule.every().day.at("23:00").do(self.send_daily_report)
            schedule.every(6).hours.do(self.send_performance_report)

    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            balance = self.get_real_time_balance()
            macd_features = "✅" if TRADING_SETTINGS['macd_early_exit'] else "❌"
            macd_filter = "✅" if TRADING_SETTINGS['macd_required_additional'] else "❌"
            
            message = (
                "🚀 <b>بدء تشغيل بوت الماكد المتقدم</b>\n"
                f"الاستراتيجية: EMA 9/21 + RSI 14 + MACD + نظام الترندات\n"
                f"العملات: {', '.join(TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {TRADING_SETTINGS['max_leverage']}x\n"
                f"🎯 جني الربح: {TRADING_SETTINGS['target_profit_pct']}%\n"
                f"🛡️ وقف الخسارة: {TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"⏰ مدة الصفقة: {TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                f"📈 مدة الترند: {TRADING_SETTINGS['max_trend_duration_minutes']} دقيقة\n"
                f"🔄 الحد الأقصى للصفقات في الترند: {TRADING_SETTINGS['max_trades_per_symbol']}\n"
                f"⏱️ فاصل بين الصفقات: {TRADING_SETTINGS['min_trade_gap_minutes']} دقيقة\n"
                f"🔮 <b>ميزات الماكد:</b>\n"
                f"• الإغلاق المبكر بالماكد: {macd_features}\n"
                f"• تصفية الإشارات الإضافية: {macd_filter}\n"
                f"🔄 إغلاق عند الإشارات المعاكسة: نشط ✅\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.notifier.send_message(message)

    def send_daily_report(self):
        """إرسال التقرير اليومي"""
        if not self.notifier:
            return
        
        daily_trades = self.performance_stats['daily_trades_count']
        active_trades = self.trade_manager.get_active_trades_count()
        active_trends = len(self.trend_manager.active_trends)
        balance = self.get_real_time_balance()
        macd_exits = self.performance_stats['macd_early_exits']
        macd_filtered = self.performance_stats['macd_filtered_signals']
        
        message = (
            f"📊 <b>التقرير اليومي - بوت الماكد المتقدم</b>\n"
            f"📅 التاريخ: {datetime.now(damascus_tz).strftime('%Y-%m-%d')}\n"
            f"⏰ الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}\n"
            f"═══════════════════\n"
            f"📈 <b>أداء اليوم:</b>\n"
            f"• عدد الصفقات: {daily_trades}\n"
            f"• الصفقات النشطة: {active_trades}\n"
            f"• الترندات النشطة: {active_trends}\n"
            f"🔮 <b>إحصائيات الماكد:</b>\n"
            f"• إغلاق مبكر: {macd_exits}\n"
            f"• إشارات مفلترة: {macd_filtered}\n"
            f"═══════════════════\n"
            f"💰 <b>الرصيد:</b>\n"
            f"• الإجمالي: ${balance['total_balance']:.2f}\n"
            f"• المتاح: ${balance['available_balance']:.2f}\n"
            f"═══════════════════\n"
            f"🔚 <b>نهاية التقرير</b>"
        )
        
        self.notifier.send_message(message)

    def send_performance_report(self):
        """إرسال تقرير الأداء"""
        if not self.notifier:
            return
        
        active_trades = self.trade_manager.get_active_trades_count()
        active_trends = len(self.trend_manager.active_trends)
        total_trends = self.performance_stats['total_trends']
        successful_trends = self.performance_stats['successful_trends']
        macd_exits = self.performance_stats['macd_early_exits']
        
        success_rate = (successful_trends / total_trends * 100) if total_trends > 0 else 0
        
        message = (
            f"📈 <b>تقرير أداء البوت المتقدم</b>\n"
            f"الصفقات النشطة: {active_trades}\n"
            f"الترندات النشطة: {active_trends}\n"
            f"إجمالي الترندات: {total_trends}\n"
            f"الترندات الناجحة: {successful_trends}\n"
            f"معدل نجاح الترندات: {success_rate:.1f}%\n"
            f"الصفقات اليوم: {self.performance_stats['daily_trades_count']}\n"
            f"إغلاق مبكر بالماكد: {macd_exits}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)

    def get_historical_data(self, symbol, interval, limit=100):
        """جلب البيانات التاريخية"""
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

    def can_open_trade(self, symbol, direction, signal_type, macd_status):
        """التحقق من إمكانية فتح صفقة مع تحسينات الأمان"""
        reasons = []
    
        # الفحص الأساسي
        if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات النشطة")
    
        if self.performance_stats['daily_trades_count'] >= TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
    
        # 🔴 التصحيح: تطبيق min_trade_gap_minutes على جميع الصفقات (كان يطبق فقط على الإضافية)
        if symbol in self.last_trade_times:
            time_since_last = (datetime.now(damascus_tz) - self.last_trade_times[symbol]).total_seconds() / 60
            if time_since_last < TRADING_SETTINGS['min_trade_gap_minutes']:
                remaining = TRADING_SETTINGS['min_trade_gap_minutes'] - time_since_last
                reasons.append(f"الفاصل الزمني غير كافي ({time_since_last:.1f} دقيقة, متبقي {remaining:.1f} دقيقة)")
    
        # التحقق من الترند للإشارات الإضافية مع الماكد
        if signal_type != 'BASE_CROSSOVER':
            can_add, trend_reason = self.trend_manager.can_add_trade_to_trend(symbol, signal_type, macd_status)
            if not can_add:
                reasons.append(trend_reason)
                self.performance_stats['macd_filtered_signals'] += 1
    
        return len(reasons) == 0, reasons

    def calculate_position_size(self, symbol, current_price):
        """حساب حجم المركز"""
        try:
            nominal_size = TRADING_SETTINGS['used_balance_per_trade'] * TRADING_SETTINGS['max_leverage']
            quantity = nominal_size / current_price
            
            precision_manager = PrecisionManager(self.client)
            adjusted_quantity = precision_manager.adjust_quantity(symbol, quantity)
            
            if adjusted_quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol}: {adjusted_quantity:.6f}")
                return adjusted_quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز: {e}")
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
        """تنفيذ الصفقة في نظام الماكد المتقدم - محسّن مع الحفاظ على الهيكل الكامل"""
        try:
            # ========== تحسين 1: فحص شامل للبيانات المطلوبة ==========
            required_keys = ['symbol', 'direction', 'signal_type', 'macd_status', 'current_price']
            missing_keys = [key for key in required_keys if key not in signal]
            if missing_keys:
                logger.error(f"❌ إشارة ناقصة البيانات: المفاتيح المفقودة {missing_keys}")
                return False
        
            # تحقق إضافي من القيم
            if not signal['symbol'] or signal['current_price'] <= 0:
                logger.error(f"❌ بيانات غير صالحة في الإشارة: symbol={signal['symbol']}, price={signal['current_price']}")
                return False
        
            symbol = signal['symbol']
            direction = signal['direction']
            signal_type = signal['signal_type']
            macd_status = signal['macd_status']
            current_price = signal['current_price']
        
            if direction not in ['LONG', 'SHORT']:
                logger.error(f"❌ اتجاه غير صالح: {direction}")
                return False
        
            # ========== تحسين 2: فحص السعر والكمية بشكل منفصل ==========
            # فحص السعر الحالي أولاً
            if not current_price or current_price <= 0:
                logger.error(f"❌ سعر غير صالح لـ {symbol}: {current_price}")
                return False
        
            # فحص الكمية ثانياً
            quantity = self.calculate_position_size(symbol, current_price)
            if not quantity or quantity <= 0:
                logger.error(f"❌ كمية غير صالحة لـ {symbol}: {quantity}")
                return False
        
            # ========== تحسين 3: تسجيل مفصل قبل المعالجة ==========
            logger.info(f"🔍 معالجة إشارة {symbol}: {direction} | النوع: {signal_type} | السعر: {current_price:.4f}")
        
            # ========== تحسين 4: معالجة خاصة للإشارة الأساسية مع تحسين التسجيل ==========
            if signal_type == 'BASE_CROSSOVER':
                logger.info(f"🔄 معالجة إشارة أساسية لـ {symbol} - التحقق من الصفقات المعاكسة")
            
                # التحقق من وجود صفقة معاكسة وإغلاقها
                trade_closed = self.trade_manager.check_and_handle_opposite_signals(symbol, direction)
    
                if trade_closed:
                    logger.info(f"⏳ انتظار 15 ثانية بعد إغلاق الصفقة المعاكسة لـ {symbol}")
                    time.sleep(15)  # زيادة وقت الانتظار لضمان استقرار السوق
        
                # بدء ترند جديد مع حالة الماكد
                trend_id = self.trend_manager.start_new_trend(symbol, direction, signal_type, macd_status)
                self.performance_stats['total_trends'] += 1
                logger.info(f"🎯 بدء ترند جديد لـ {symbol}: {trend_id}")

            # ========== تحسين 5: التحقق من إمكانية فتح الصفقة مع تسجيل الأسباب ==========
            can_trade, reasons = self.can_open_trade(symbol, direction, signal_type, macd_status)
            if not can_trade:
                reason_text = ', '.join(reasons)
                logger.info(f"⏭️ تخطي {symbol} {direction} ({signal_type}): {reason_text}")
            
                # تسجيل الإشارات المفلترة للإحصائيات
                if "الفاصل الزمني غير كافي" in reason_text:
                    self.performance_stats['filtered_time_gap'] = self.performance_stats.get('filtered_time_gap', 0) + 1
                if "الحد الأقصى للصفقات النشطة" in reason_text:
                    self.performance_stats['filtered_max_trades'] = self.performance_stats.get('filtered_max_trades', 0) + 1
                
                return False

            # ========== تحسين 6: تعيين الرافعة مع معالجة أفضل للأخطاء ==========
            leverage_success = self.set_leverage(symbol, TRADING_SETTINGS['max_leverage'])
            if not leverage_success:
                logger.warning(f"⚠️ فشل تعيين الرافعة لـ {symbol}, المتابعة بأي حال")
                # لا نعود هنا لأن الرافعة قد تكون مضبوطة مسبقاً

            side = 'BUY' if direction == 'LONG' else 'SELL'

            logger.info(f"⚡ محاولة تنفيذ صفقة {symbol}: {direction} | النوع: {signal_type} | الكمية: {quantity:.6f}")

            # ========== تحسين 7: تنفيذ الأمر مع معالجة محسنة للأخطاء ==========
            try:
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side=side,
                    type='MARKET',
                    quantity=quantity
                )
            except Exception as order_error:
                logger.error(f"❌ فشل إنشاء أمر لـ {symbol}: {order_error}")
            
                # محاولة بديلة: إعادة المحاولة مرة واحدة بعد ثانية
                try:
                    logger.info(f"🔄 إعادة محاولة تنفيذ الأمر لـ {symbol} بعد فشل أولي")
                    time.sleep(1)
                    order = self.client.futures_create_order(
                        symbol=symbol,
                        side=side,
                        type='MARKET',
                        quantity=quantity
                    )
                except Exception as retry_error:
                    logger.error(f"❌ فشل إعادة المحاولة لـ {symbol}: {retry_error}")
                    return False

            if order and order.get('orderId'):
                # ========== تحسين 8: الحصول على سعر التنفيذ الفعلي مع معالجة أخطاء ==========
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                    if order_info and order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                        logger.info(f"💰 سعر التنفيذ الفعلي لـ {symbol}: {executed_price:.4f} (بدلاً من {current_price:.4f})")
                except Exception as price_error:
                    logger.warning(f"⚠️ لا يمكن الحصول على سعر التنفيذ لـ {symbol}: {price_error}, استخدام السعر المقدر: {executed_price:.4f}")
    
                # تحديث وقت آخر صفقة
                self.last_trade_times[symbol] = datetime.now(damascus_tz)
        
                # ========== تحسين 9: إعداد بيانات الصفقة مع معلومات إضافية ==========
                trade_data = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': TRADING_SETTINGS['max_leverage'],
                    'signal_confidence': signal.get('confidence', 0.5),
                    'order_id': order['orderId'],
                    'signal_type': signal_type,
                    'macd_status': macd_status
                }
    
                # إضافة الصفقة للنظام المناسب مع الماكد
                self.trade_manager.add_trade(symbol, trade_data, signal_type, macd_status)
    
                # تحديث الترند للإشارات الإضافية مع الماكد
                if signal_type != 'BASE_CROSSOVER':
                    trend_added = self.trend_manager.add_trade_to_trend(symbol, signal_type, macd_status)
                    if trend_added:
                        logger.info(f"📈 تمت إضافة صفقة للترند الحالي لـ {symbol}")
                    else:
                        logger.warning(f"⚠️ فشل إضافة صفقة للترند لـ {symbol}")
    
                # ========== تحسين 10: تحديث الإحصائيات بشكل شامل ==========
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
            
                # إحصائية نوع الإشارة
                signal_type_stats = self.performance_stats.get('signal_types', {})
                signal_type_stats[signal_type] = signal_type_stats.get(signal_type, 0) + 1
                self.performance_stats['signal_types'] = signal_type_stats
    
                # ========== تحسين 11: إرسال إشعار مع التحقق من النجاح ==========
                if self.notifier:
                    trend_status = self.trend_manager.get_trend_status(symbol)
                    notification_sent = self.notifier.send_signal_alert(symbol, signal, executed_price, trend_status)
                    if not notification_sent:
                        logger.warning(f"⚠️ فشل إرسال إشعار لـ {symbol}")
                    else:
                        logger.info(f"📨 تم إرسال إشعار فتح الصفقة لـ {symbol}")
     
                logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol} - النوع: {signal_type} - السعر: {executed_price:.4f}")
                return True
    
            else:
                logger.error(f"❌ فشل تنفيذ الأمر لـ {symbol}: لا يوجد orderId في الاستجابة")
                return False
    
        except KeyError as e:
            logger.error(f"❌ مفتاح مفقود في تنفيذ الصفقة: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {signal.get('symbol', 'UNKNOWN')}: {e}")
            return False

    def scan_market(self):
        """مسح السوق للبحث عن إشارات متقدمة مع الماكد"""
        logger.info("🔍 بدء مسح السوق المتقدم مع الماكد...")
        
        opportunities = []
        
        for symbol in TRADING_SETTINGS['symbols']:
            try:
                data = self.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 26)
                if data is None:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                signal = self.signal_generator.generate_signal(symbol, data, current_price)
                if signal:
                    opportunities.append(signal)
                
            except Exception as e:
                logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
                continue
        
        # ترتيب الإشارات حسب الأولوية
        opportunities.sort(key=lambda x: x.get('priority', 0), reverse=True)
        
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة متقدمة مع الماكد")
        return opportunities

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول المتقدمة مع التنبؤات"""
        try:
            opportunities = self.scan_market()
        
            # معالجة التنبؤات أولاً
            for signal in opportunities:
                if signal.get('signal_type') == 'CROSSOVER_PREDICTION':
                    self._handle_crossover_prediction(signal)
        
            executed_trades = 0
            for signal in opportunities:
                if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
                    break
                
                if self.execute_trade(signal):
                    executed_trades += 1
                    if signal['signal_type'] == 'BASE_CROSSOVER':
                        break  # نكتفي بصققة واحدة أساسية في الدورة
        
            # تنظيف التنبيهات القديمة
            self.cleanup_prediction_alerts()
        
            wait_time = TRADING_SETTINGS['rescan_interval_minutes'] * 60
            logger.info(f"⏳ انتظار {wait_time} ثانية للدورة القادمة...")
            time.sleep(wait_time)
        
        except Exception as e:
            logger.error(f"❌ خطأ في دورة التداول المتقدمة: {e}")
            time.sleep(60)

    def get_active_trades_details(self):
        """الحصول على تفاصيل الصفقات النشطة"""
        trades = self.trade_manager.get_all_trades()
        active_trades = []
        
        for symbol, trade in trades.items():
            if trade['status'] == 'open':
                current_price = self.get_current_price(symbol)
                trade_info = {
                    'symbol': trade['symbol'],
                    'side': trade['side'],
                    'quantity': trade['quantity'],
                    'entry_price': trade['entry_price'],
                    'current_price': current_price,
                    'leverage': trade['leverage'],
                    'timestamp': trade['timestamp'].isoformat(),
                    'take_profit_price': trade['take_profit_price'],
                    'stop_loss_price': trade['stop_loss_price'],
                    'signal_type': trade.get('signal_type', 'UNKNOWN'),
                    'macd_status': trade.get('macd_status', {})
                }
                
                if current_price:
                    if trade['side'] == 'LONG':
                        pnl_pct = (current_price - trade['entry_price']) / trade['entry_price'] * 100
                    else:
                        pnl_pct = (trade['entry_price'] - current_price) / trade['entry_price'] * 100
                    trade_info['current_pnl_pct'] = pnl_pct
                
                active_trades.append(trade_info)
        
        return active_trades

    def get_trend_status(self):
        """الحصول على حالة الترندات مع الماكد"""
        return {
            'active_trends': self.trend_manager.active_trends,
            'trend_history': self.trend_manager.trend_history[-10:],
            'performance_stats': self.performance_stats,
            'macd_signals_log': self.trend_manager.macd_signals_log[-20:]
        }

    def get_macd_analysis(self, symbol):
        """الحصول على تحليل الماكد المفصل"""
        try:
            data = self.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 50)
            if data is None:
                return {'error': 'لا توجد بيانات'}
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return {'error': 'لا يمكن الحصول على السعر'}
            
            indicators = self.signal_generator._calculate_advanced_indicators(data)
            macd_status = self.signal_generator._analyze_macd_status(indicators, data)
            trend_status = self.trend_manager.get_trend_status(symbol)
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'macd_analysis': macd_status,
                'trend_status': trend_status,
                'indicators': {
                    'ema9': indicators['ema9'],
                    'ema21': indicators['ema21'],
                    'rsi': indicators['rsi'],
                    'macd': indicators['macd'],
                    'macd_signal': indicators['macd_signal'],
                    'macd_histogram': indicators['macd_histogram']
                },
                'timestamp': datetime.now(damascus_tz).isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}

    def run(self):
        """بدء تشغيل البوت المتقدم مع الماكد"""
        logger.info("🚀 بدء تشغيل بوت الماكد المتقدم...")
        
        # بدء Flask في thread منفصل
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
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
            logger.info("🛑 إيقاف البوت المتقدم...")
            self.trade_manager.stop_monitoring()

@app.route('/')
def health_check():
    return {'status': 'healthy', 'service': 'ema-rsi-macd-trend-bot', 'timestamp': datetime.now(damascus_tz).isoformat()}

@app.route('/active_trades')
def active_trades():
    try:
        bot = AdvancedMACDTrendBot.get_instance()
        if bot:
            return jsonify(bot.get_active_trades_details())
        return jsonify([])
    except Exception as e:
        return {'error': str(e)}

@app.route('/trend_status')
def trend_status():
    try:
        bot = AdvancedMACDTrendBot.get_instance()
        if bot:
            return jsonify(bot.get_trend_status())
        return {'error': 'Bot not initialized'}
    except Exception as e:
        return {'error': str(e)}

@app.route('/macd_analysis/<symbol>')
def macd_analysis(symbol):
    try:
        bot = AdvancedMACDTrendBot.get_instance()
        if bot:
            analysis = bot.get_macd_analysis(symbol)
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
        logging.FileHandler('advanced_macd_trend_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    try:
        bot = AdvancedMACDTrendBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
