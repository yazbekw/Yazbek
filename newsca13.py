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
    'symbols': ["ETHUSDT"],
    'used_balance_per_trade': 12,
    'max_leverage': 4,
    'max_active_trades': 5,
    'data_interval': '5m',
    'rescan_interval_minutes': 3,
    'target_profit_pct': 0.20,
    'stop_loss_pct': 0.08,
    'max_trade_duration_minutes': 10,
    'max_daily_trades': 30,
    'cooldown_after_loss': 5,
    'max_trades_per_symbol': 5,
    'max_trend_duration_minutes': 60,
    'min_trade_gap_minutes': 5,
    'macd_early_exit': True,  # 🆕 إغلاق مبكر بالماكد
    'macd_required_additional': True,  # 🆕 اشتراط الماكد للإشارات الإضافية
}

# ضبط التوقيت
damascus_tz = pytz.timezone('Asia/Damascus')
os.environ['TZ'] = 'Asia/Damascus'

# تطبيق Flask للرصد
app = Flask(__name__)

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
    """🆕 مدير الترندات مع دعم الماكد المتقدم"""
    
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
            'macd_status_start': macd_status,  # 🆕 حالة الماكد عند البدء
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
        
        # 🆕 التحقق من شروط الماكد للإشارات الإضافية
        if (TRADING_SETTINGS['macd_required_additional'] and 
            signal_type != 'BASE_CROSSOVER' and 
            not self._check_macd_for_additional_signal(trend, macd_status)):
            return False, "الماكد لا يؤكد الإشارة الإضافية"
        
        # التحقق من الخسائر المتتالية
        if trend['failed_trades'] >= 3:
            return False, "3 خسائر متتالية في الترند"
        
        return True, "يمكن إضافة الصفقة"
    
    def _check_macd_for_additional_signal(self, trend, current_macd):
        """🆕 التحقق من شروط الماكد للإشارات الإضافية"""
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
        """🆕 التحقق من إغلاق مبكر بالماكد"""
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
        """🆕 تسجيل إشارات الماكد للتحليل"""
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
    """🆕 مولد إشارات متطور مع دعم الماكد الكامل"""
    
    def __init__(self):
        self.trend_manager = MACDTrendManager()
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارات متقدمة مع الماكد"""
        try:
            if len(data) < 26:  # تحتاج 26 نقطة للماكد
                return None
            
            indicators = self._calculate_advanced_indicators(data)
            macd_status = self._analyze_macd_status(indicators, data)
            
            # البحث عن إشارات بأنواعها
            signals = []
            
            # الإشارة الأساسية (التقاطع)
            base_signal = self._analyze_base_signal(indicators, symbol, current_price, macd_status)
            if base_signal:
                signals.append(base_signal)
            
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
        
        # 🆕 مؤشر الماكد
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
            'high_5': latest['high_5'],
            'low_5': latest['low_5'],
            'volume': latest['volume'],
            'volume_avg': df['volume'].tail(20).mean(),
            # 🆕 بيانات الماكد
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'macd_histogram': latest['macd_histogram'],
            'macd_prev': prev['macd'],
            'macd_signal_prev': prev['macd_signal'],
            'macd_histogram_prev': prev['macd_histogram'],
            'macd_histogram_prev_2': prev_2['macd_histogram'],
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
        
        return rsi.iloc[-1] if not rsi.empty else 50
    
    def _analyze_macd_status(self, indicators, data):
        """🆕 تحليل حالة الماكد الشاملة"""
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
    
    def _analyze_base_signal(self, indicators, symbol, current_price, macd_status):
        """تحليل الإشارة الأساسية (التقاطع) مع الماكد"""
        # اكتشاف التقاطعات
        ema9_cross_above_21 = (indicators['ema9'] > indicators['ema21'] and 
                              indicators['ema9_prev'] <= indicators['ema21_prev'])
        ema9_cross_below_21 = (indicators['ema9'] < indicators['ema21'] and 
                              indicators['ema9_prev'] >= indicators['ema21_prev'])
        
        # تحليل الشمعة
        is_bullish_candle = indicators['current_close'] > indicators['current_open']
        is_bearish_candle = indicators['current_close'] < indicators['current_open']
        
        # 🆕 تحليل الماكد للتقاطع الأساسي
        macd_bullish_confirmation = macd_status['bullish'] or not TRADING_SETTINGS['macd_required_additional']
        macd_bearish_confirmation = macd_status['bearish'] or not TRADING_SETTINGS['macd_required_additional']
        
        # إشارة شراء أساسية
        if (ema9_cross_above_21 and indicators['rsi'] > 50 and 
            is_bullish_candle and macd_bullish_confirmation):
            
            self.trend_manager.log_macd_signal(symbol, 'BASE_CROSSOVER', macd_status, 'BUY_SIGNAL')
            
            return {
                'symbol': symbol,
                'direction': 'LONG',
                'confidence': 0.90,
                'reason': 'تقاطع أساسي - EMA 9 فوق EMA 21 مع RSI > 50 وتأكيد الماكد',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'BASE_CROSSOVER',
                'priority': 100,
                'macd_status': macd_status
            }
        
        # إشارة بيع أساسية
        if (ema9_cross_below_21 and indicators['rsi'] < 50 and 
            is_bearish_candle and macd_bearish_confirmation):
            
            self.trend_manager.log_macd_signal(symbol, 'BASE_CROSSOVER', macd_status, 'SELL_SIGNAL')
            
            return {
                'symbol': symbol,
                'direction': 'SHORT',
                'confidence': 0.90,
                'reason': 'تقاطع أساسي - EMA 9 تحت EMA 21 مع RSI < 50 وتأكيد الماكد',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price,
                'signal_type': 'BASE_CROSSOVER',
                'priority': 100,
                'macd_status': macd_status
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
        
        # 🆕 جميع الإشارات الإضافية تتطلب تأكيد الماكد
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
        """🆕 التحقق من شروط الماكد للإشارات الإضافية"""
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

class AdvancedMACDTradeManager:
    """🆕 مدير صفقات متطور مع دعم الماكد"""
    
    def __init__(self, client, notifier, trend_manager):
        self.client = client
        self.notifier = notifier
        self.precision_manager = PrecisionManager(client)
        self.trend_manager = trend_manager
        self.active_trades = {}
        self.monitoring_active = True
        self.start_trade_monitoring()
    
    def _get_current_price(self, symbol):
        """الحصول على السعر الحالي"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر {symbol}: {e}")
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
        """التحقق من وجود صفقة معاكسة وإغلاقها"""
        try:
            if self.is_symbol_trading(symbol):
                current_trade = self.get_trade(symbol)
                current_direction = current_trade['side']
                
                # إذا كانت الإشارة الجديدة معاكسة للصفقة الحالية
                if current_direction != new_direction:
                    current_price = self._get_current_price(symbol)
                    if current_price:
                        logger.info(f"🔄 إشارة معاكسة لـ {symbol}: {current_direction} -> {new_direction}")
                        self.close_trade(symbol, f"إشارة معاكسة ({new_direction})", current_price)
                        # إنهاء الترند الحالي
                        self.trend_manager.end_trend(symbol, "إشارة معاكسة")
                        return True
            return False
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الإشارات المعاكسة: {e}")
            return False
    
    def start_trade_monitoring(self):
        """بدء مراقبة الصفقات مع الماكد"""
        def monitor():
            while self.monitoring_active:
                try:
                    self._check_limits_and_duration()
                    self._cleanup_closed_trades()
                    self.trend_manager.cleanup_expired_trends()
                    time.sleep(10)
                except Exception as e:
                    logger.error(f"❌ خطأ في المراقبة: {e}")
                    time.sleep(30)
        
        threading.Thread(target=monitor, daemon=True).start()
        logger.info("✅ بدء مراقبة الصفقات النشطة مع الماكد")
    
    def _check_limits_and_duration(self):
        """التحقق من الحدود والمدة مع الإغلاق المبكر بالماكد"""
        current_time = datetime.now(damascus_tz)
        
        for symbol, trade in list(self.active_trades.items()):
            if trade['status'] != 'open':
                continue
            
            current_price = self._get_current_price(symbol)
            if not current_price:
                continue
            
            # 🆕 الحصول على بيانات الماكد الحالية
            macd_data = self._get_current_macd_data(symbol)
            if not macd_data:
                continue
            
            # 🆕 التحقق من الإغلاق المبكر بالماكد
            if (TRADING_SETTINGS['macd_early_exit'] and 
                self._check_macd_early_exit(symbol, trade, macd_data, current_price)):
                continue
            
            # التحقق من المدة
            trade_duration = (current_time - trade['timestamp']).total_seconds() / 60
            if trade_duration >= TRADING_SETTINGS['max_trade_duration_minutes']:
                self.close_trade(symbol, f"انتهت المدة ({trade_duration:.1f} دقيقة)", current_price)
                continue
            
            # التحقق من وقف الخسارة وجني الربح
            entry_price = trade['entry_price']
            direction = trade['side']
            
            if direction == 'LONG':
                pnl_pct = (current_price - entry_price) / entry_price * 100
                if current_price >= trade['take_profit_price']:
                    self.close_trade(symbol, f"جني الربح ({pnl_pct:+.2f}%)", current_price)
                elif current_price <= trade['stop_loss_price']:
                    self.close_trade(symbol, f"وقف الخسارة ({pnl_pct:+.2f}%)", current_price)
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                if current_price <= trade['take_profit_price']:
                    self.close_trade(symbol, f"جني الربح ({pnl_pct:+.2f}%)", current_price)
                elif current_price >= trade['stop_loss_price']:
                    self.close_trade(symbol, f"وقف الخسارة ({pnl_pct:+.2f}%)", current_price)
    
    def _get_current_macd_data(self, symbol):
        """🆕 الحصول على بيانات الماكد الحالية"""
        try:
            from AdvancedMACDTrendBot import AdvancedMACDTrendBot
            bot = AdvancedMACDTrendBot.get_instance()
            if bot:
                data = bot.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 26)
                if data is not None:
                    signal_generator = AdvancedMACDSignalGenerator()
                    indicators = signal_generator._calculate_advanced_indicators(data)
                    return signal_generator._analyze_macd_status(indicators, data)
        except Exception as e:
            logger.error(f"❌ خطأ في جلب بيانات الماكد لـ {symbol}: {e}")
        return None
    
    def _check_macd_early_exit(self, symbol, trade, macd_data, current_price):
        """🆕 التحقق من الإغلاق المبكر بالماكد"""
        try:
            # الحصول على بيانات RSI الحالية
            from AdvancedMACDTrendBot import AdvancedMACDTrendBot
            bot = AdvancedMACDTrendBot.get_instance()
            if bot:
                data = bot.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 20)
                if data is not None:
                    current_rsi = data['close'].tail(14).apply(lambda x: 
                        self._calculate_rsi(data['close'].tail(15), 14) if len(data) >= 15 else 50
                    ).iloc[-1]
                    
                    should_exit, reason = self.trend_manager.should_early_exit(symbol, macd_data, current_rsi)
                    if should_exit:
                        self.close_trade(symbol, f"إغلاق مبكر: {reason}", current_price)
                        return True
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الإغلاق المبكر: {e}")
        
        return False
    
    def _calculate_rsi(self, prices, period):
        """حساب RSI مساعد"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1] if not rsi.empty else 50
    
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
        """إغلاق الصفقة"""
        try:
            trade = self.active_trades.get(symbol)
            if not trade or trade['status'] != 'open':
                return False
            
            quantity = trade['quantity']
            direction = trade['side']
            
            # تنفيذ أمر الإغلاق
            close_side = 'SELL' if direction == 'LONG' else 'BUY'
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='MARKET',
                quantity=quantity,
                reduceOnly=True
            )
            
            if order and order['orderId']:
                # تحديث بيانات الصفقة
                entry_price = trade['entry_price']
                if direction == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                
                # تحديث الترند
                self.trend_manager.update_trend_pnl(symbol, pnl_pct)
                
                trade.update({
                    'status': 'closed',
                    'close_price': current_price,
                    'close_time': datetime.now(damascus_tz),
                    'pnl_pct': pnl_pct,
                    'close_reason': reason
                })
                
                # إرسال إشعار
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    trend_status = self.trend_manager.get_trend_status(symbol)
                    trend_info = ""
                    if trend_status:
                        trend_info = f"📊 الترند: {trend_status['trades_count']} صفقات | PnL: {trend_status['total_pnl']:+.2f}%\n"
                    
                    message = (
                        f"🔒 <b>إغلاق صفقة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"سعر الدخول: ${entry_price:.4f}\n"
                        f"سعر الخروج: ${current_price:.4f}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"{trend_info}"
                        f"السبب: {reason}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم إغلاق صفقة {symbol} - {reason} - PnL: {pnl_pct:+.2f}%")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {symbol}: {e}")
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
                'macd_status': macd_status  # 🆕 حفظ حالة الماكد
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
    
    def send_signal_alert(self, symbol, signal, current_price, trend_status=None):
        """إرسال إشعار إشارة مع بيانات الماكد"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        signal_type_emoji = {
            'BASE_CROSSOVER': '🎯',
            'PULLBACK': '📈', 
            'MOMENTUM': '⚡',
            'BREAKOUT': '🚀',
            'RENEWAL': '🔄'
        }.get(signal['signal_type'], '📊')
        
        # 🆕 معلومات الماكد
        macd_info = ""
        if 'macd_status' in signal:
            macd = signal['macd_status']
            macd_emoji = "🟢" if macd['bullish'] else "🔴"
            histogram_emoji = "📈" if macd['histogram_increasing'] else "📉"
            macd_info = (
                f"🔮 <b>تحليل الماكد:</b>\n"
                f"• الحالة: {macd_emoji} {'صاعد' if macd['bullish'] else 'هابط'}\n"
                f"• الماكد: {macd['macd']:.6f}\n"
                f"• الإشارة: {macd['signal']:.6f}\n"
                f"• الهيستوجرام: {histogram_emoji} {macd['histogram']:.6f}\n"
            )
        
        trend_info = ""
        if trend_status:
            trend_info = (
                f"📊 <b>حالة الترند:</b>\n"
                f"• الصفقات: {trend_status['trades_count']}/5\n"
                f"• المدة: {((datetime.now(damascus_tz) - trend_status['start_time']).total_seconds() / 60):.1f} دقيقة\n"
                f"• إجمالي PnL: {trend_status['total_pnl']:+.2f}%\n"
                f"• تأكيدات الماكد: {trend_status.get('macd_confirmations', 0)}\n"
            )
        
        message = (
            f"{direction_emoji} <b>إشارة تداول جديدة</b> {signal_type_emoji}\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"النوع: {signal['signal_type']}\n"
            f"السعر: ${current_price:.4f}\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"السبب: {signal['reason']}\n"
            f"📊 المؤشرات:\n"
            f"• EMA 9: {signal['indicators']['ema9']:.4f}\n"
            f"• EMA 21: {signal['indicators']['ema21']:.4f}\n"
            f"• RSI: {signal['indicators']['rsi']:.1f}\n"
            f"{macd_info}"
            f"{trend_info}"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

class AdvancedMACDTrendBot:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self):
        if AdvancedMACDTrendBot._instance is not None:
            raise Exception("هذه الفئة تستخدم نمط Singleton")
        
        self.api_key = os.environ.get('BINANCE_API_KEY')
        self.api_secret = os.environ.get('BINANCE_API_SECRET')
        self.telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        
        if not all([self.api_key, self.api_secret]):
            raise ValueError("مفاتيح Binance مطلوبة")
        
        try:
            self.client = Client(self.api_key, self.api_secret)
            self.test_connection()
        except Exception as e:
            logger.error(f"❌ فشل تهيئة العميل: {e}")
            raise

        # 🆕 تهيئة النظام المتطور مع الماكد
        self.signal_generator = AdvancedMACDSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trend_manager = self.signal_generator.trend_manager
        self.trade_manager = AdvancedMACDTradeManager(self.client, self.notifier, self.trend_manager)
        
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'daily_trades_count': 0,
            'total_trends': 0,
            'successful_trends': 0,
            'macd_early_exits': 0,  # 🆕 إحصائيات الماكد
            'macd_filtered_signals': 0,
        }
        
        self.start_services()
        self.send_startup_message()
        
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
        """التحقق من إمكانية فتح صفقة مع الماكد"""
        reasons = []
        
        if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات النشطة")
        
        if self.performance_stats['daily_trades_count'] >= TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
        
        # 🆕 التحقق من الترند للإشارات الإضافية مع الماكد
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
        """تنفيذ الصفقة في نظام الماكد المتقدم"""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            signal_type = signal['signal_type']
            macd_status = signal['macd_status']
            
            # 🆕 معالجة خاصة للإشارة الأساسية
            if signal_type == 'BASE_CROSSOVER':
                # التحقق من وجود صفقة معاكسة وإغلاقها
                trade_closed = self.trade_manager.check_and_handle_opposite_signals(symbol, direction)
                
                if trade_closed:
                    logger.info(f"⏳ انتظار قليل بعد إغلاق الصفقة المعاكسة لـ {symbol}")
                    time.sleep(2)
                
                # بدء ترند جديد مع حالة الماكد
                self.trend_manager.start_new_trend(symbol, direction, signal_type, macd_status)
                self.performance_stats['total_trends'] += 1
            
            # التحقق من إمكانية فتح الصفقة مع الماكد
            can_trade, reasons = self.can_open_trade(symbol, direction, signal_type, macd_status)
            if not can_trade:
                logger.info(f"⏭️ تخطي {symbol} {direction} ({signal_type}): {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False
            
            quantity = self.calculate_position_size(symbol, current_price)
            if not quantity:
                return False
            
            # تعيين الرافعة
            self.set_leverage(symbol, TRADING_SETTINGS['max_leverage'])
            
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"⚡ تنفيذ صفقة {symbol}: {direction} | النوع: {signal_type} | الماكد: {macd_status['bullish']}")
            
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
                
                trade_data = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': TRADING_SETTINGS['max_leverage'],
                    'signal_confidence': signal['confidence'],
                }
                
                # 🆕 إضافة الصفقة للنظام المناسب مع الماكد
                self.trade_manager.add_trade(symbol, trade_data, signal_type, macd_status)
                
                # 🆕 تحديث الترند للإشارات الإضافية مع الماكد
                if signal_type != 'BASE_CROSSOVER':
                    self.trend_manager.add_trade_to_trend(symbol, signal_type, macd_status)
                
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                
                # إرسال إشعار
                if self.notifier:
                    trend_status = self.trend_manager.get_trend_status(symbol)
                    self.notifier.send_signal_alert(symbol, signal, current_price, trend_status)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol} - النوع: {signal_type}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            return False

    def scan_market(self):
        """مسح السوق للبحث عن إشارات متقدمة مع الماكد"""
        logger.info("🔍 بدء مسح السوق المتقدم مع الماكد...")
        
        opportunities = []
        
        for symbol in TRADING_SETTINGS['symbols']:
            try:
                data = self.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 26)  # 🆕 تحتاج 26 للماكد
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
        """تنفيذ دورة التداول المتقدمة مع الماكد"""
        try:
            opportunities = self.scan_market()
            
            executed_trades = 0
            for signal in opportunities:
                if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
                    break
                    
                if self.execute_trade(signal):
                    executed_trades += 1
                    if signal['signal_type'] == 'BASE_CROSSOVER':
                        break  # نكتفي بصققة واحدة أساسية في الدورة
            
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
                    'macd_status': trade.get('macd_status', {})  # 🆕 إضافة حالة الماكد
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
        """🆕 الحصول على حالة الترندات مع الماكد"""
        return {
            'active_trends': self.trend_manager.active_trends,
            'trend_history': self.trend_manager.trend_history[-10:],
            'performance_stats': self.performance_stats,
            'macd_signals_log': self.trend_manager.macd_signals_log[-20:]  # 🆕 آخر 20 إشارة ماكد
        }

    def get_macd_analysis(self, symbol):
        """🆕 الحصول على تحليل الماكد المفصل"""
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

def main():
    try:
        bot = AdvancedMACDTrendBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
