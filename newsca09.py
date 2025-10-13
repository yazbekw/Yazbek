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
    'symbols': ["ETHUSDT"],
    'used_balance_per_trade': 12,
    'max_leverage': 4,
    'nominal_trade_size': 48,
    'max_active_trades': 1,
    'data_interval': '5m',
    'rescan_interval_minutes': 3,
    'min_signal_confidence': 0.85,
    'target_profit_pct': 0.20,
    'stop_loss_pct': 0.08,
    'max_trade_duration_minutes': 10,
    'max_daily_trades': 30,
    'cooldown_after_loss': 5,
    'max_trades_per_symbol': 1,
    'order_timeout_minutes': 1,
    'btc_confirmation_required': False,
    'min_btc_confidence': 0.70,
    'min_price_distance': 0.001,
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

class PrecisionManager:
    """مدير دقة الأسعار والكميات حسب متطلبات كل عملة"""
    
    def __init__(self, client):
        self.client = client
        self.symbols_info = {}
        self.last_update = None
        
    def get_symbol_info(self, symbol):
        """الحصول على معلومات العملة مع التخزين المؤقت"""
        try:
            if (self.last_update is None or 
                (datetime.now(damascus_tz) - self.last_update).total_seconds() > 600):
                self._update_symbols_info()
            
            return self.symbols_info.get(symbol, {})
            
        except Exception as e:
            logger.error(f"❌ خطأ في جلب معلومات الدقة لـ {symbol}: {e}")
            return {}
    
    def _update_symbols_info(self):
        """تحديث معلومات جميع العملات"""
        try:
            exchange_info = self.client.futures_exchange_info()
            for symbol_info in exchange_info['symbols']:
                symbol = symbol_info['symbol']
                self.symbols_info[symbol] = {
                    'filters': symbol_info['filters'],
                    'baseAsset': symbol_info['baseAsset'],
                    'quoteAsset': symbol_info['quoteAsset']
                }
            self.last_update = datetime.now(damascus_tz)
            logger.info("✅ تم تحديث معلومات الدقة للعملات")
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحديث معلومات العملات: {e}")
    
    def adjust_price(self, symbol, price):
        """ضبط السعر حسب متطلبات الدقة"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return round(price, 4)
            
            price_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
            if not price_filter:
                return round(price, 4)
            
            tick_size = float(price_filter['tickSize'])
            adjusted_price = float(int(price / tick_size) * tick_size)
            
            logger.debug(f"🔧 ضبط السعر {symbol}: {price:.6f} -> {adjusted_price:.6f} (tickSize: {tick_size})")
            return adjusted_price
            
        except Exception as e:
            logger.error(f"❌ خطأ في ضبط سعر {symbol}: {e}")
            return round(price, 4)
    
    def adjust_quantity(self, symbol, quantity):
        """ضبط الكمية حسب متطلبات الدقة"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return round(quantity, 6)
            
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if not lot_size_filter:
                return round(quantity, 6)
            
            step_size = float(lot_size_filter['stepSize'])
            min_qty = float(lot_size_filter.get('minQty', 0))
            
            adjusted_quantity = float(int(quantity / step_size) * step_size)
            
            if adjusted_quantity < min_qty:
                adjusted_quantity = min_qty
            
            logger.debug(f"🔧 ضبط الكمية {symbol}: {quantity:.8f} -> {adjusted_quantity:.8f} (stepSize: {step_size})")
            return round(adjusted_quantity, 8)
            
        except Exception as e:
            logger.error(f"❌ خطأ في ضبط كمية {symbol}: {e}")
            return round(quantity, 6)


class ScalpingSignalGenerator:
    def __init__(self):
        self.min_confidence = TRADING_SETTINGS['min_signal_confidence']
    
    def generate_signal(self, symbol, data, current_price):
        try:
            if len(data) < 50:
                return None
            
            indicators = self._calculate_indicators(data, current_price)
            long_signal = self._analyze_long_signal(indicators)
            short_signal = self._analyze_short_signal(indicators)
            
            return self._select_best_signal(symbol, long_signal, short_signal, indicators)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد إشارة السكالبينج لـ {symbol}: {e}")
            return None
    
    def _calculate_indicators(self, data, current_price):
        df = data.copy()
        
        # المتوسطات المتحركة الأسية - إضافة EMA 9 و EMA 21
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()  # ✅ أضف هذا السطر
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # مؤشر RSI
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        # مؤشر الماكد (MACD)
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = df['ema12'] - df['ema26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        latest = df.iloc[-1]
        
        return {
            # المؤشرات الأساسية
            'ema5': latest['ema5'],
            'ema9': latest['ema9'],
            'ema10': latest['ema10'],
            'ema20': latest['ema20'],  # ✅ أضف هذا
            'ema21': latest['ema21'],
            'rsi': latest['rsi'],
            'current_price': current_price,
            
            # مؤشرات الماكد
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'macd_histogram': latest['macd_histogram'],
            'macd_above_signal': latest['macd'] > latest['macd_signal'],
            'macd_histogram_positive': latest['macd_histogram'] > 0,
            'macd_trend_up': latest['macd'] > df['macd'].iloc[-2] if len(df) > 1 else False,
            'macd_histogram_increasing': latest['macd_histogram'] > df['macd_histogram'].iloc[-2] if len(df) > 1 else False,
            
            'timestamp': datetime.now(damascus_tz)
        }
    
    def _calculate_rsi(self, prices, period):
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
        weights = []
    
        # الشروط الأساسية (المتوسطات + RSI) - معدلة
        conditions.append(indicators['ema5'] > indicators['ema10'])
        weights.append(0.15)
        
        conditions.append(indicators['ema10'] > indicators['ema20'])  # ✅ الآن ema20 موجود
        weights.append(0.20)
        
        # شروط بداية الصعود المضافة
        conditions.append(indicators['ema9'] > indicators['ema21'])
        weights.append(0.15)
        
        conditions.append(indicators['current_price'] > indicators['ema21'])
        weights.append(0.10)
        
        conditions.append(45 < indicators['rsi'] < 65)  # أكثر مرونة للصعود
        weights.append(0.15)
        
        # شروط الماكد
        conditions.append(indicators['macd_above_signal'])
        weights.append(0.10)
        
        conditions.append(indicators['macd_histogram_positive'])
        weights.append(0.08)
        
        conditions.append(indicators.get('macd_trend_up', False))
        weights.append(0.04)
        
        conditions.append(indicators.get('macd_histogram_increasing', False))
        weights.append(0.03)
    
        weighted_confidence = 0
        for condition, weight in zip(conditions, weights):
            if condition:
                weighted_confidence += weight
    
        return {
            'direction': 'LONG',
            'confidence': weighted_confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'weighted_confidence': weighted_confidence
        }

    def _analyze_short_signal(self, indicators):
        conditions = []
        weights = []
    
        # الشروط الأساسية (المتوسطات + RSI) - معدلة
        conditions.append(indicators['ema5'] < indicators['ema10'])
        weights.append(0.15)
        
        conditions.append(indicators['ema10'] < indicators['ema20'])  # ✅ الآن ema20 موجود
        weights.append(0.20)
        
        # شروط بداية الهبوط المضافة
        conditions.append(indicators['ema9'] < indicators['ema21'])
        weights.append(0.15)
        
        conditions.append(indicators['current_price'] < indicators['ema21'])
        weights.append(0.10)
        
        conditions.append(35 < indicators['rsi'] < 55)  # أكثر مرونة للهبوط
        weights.append(0.15)
        
        # شروط الماكد
        conditions.append(not indicators['macd_above_signal'])
        weights.append(0.10)
        
        conditions.append(not indicators['macd_histogram_positive'])
        weights.append(0.08)
        
        conditions.append(not indicators.get('macd_trend_up', True))
        weights.append(0.04)
        
        conditions.append(not indicators.get('macd_histogram_increasing', True))
        weights.append(0.03)
    
        weighted_confidence = 0
        for condition, weight in zip(conditions, weights):
            if condition:
                weighted_confidence += weight
    
        return {
            'direction': 'SHORT',
            'confidence': weighted_confidence,
            'conditions_met': sum(conditions),
            'total_conditions': len(conditions),
            'weighted_confidence': weighted_confidence
        }
    
    def _select_best_signal(self, symbol, long_signal, short_signal, indicators):
        signals = []
        
        if long_signal['confidence'] >= self.min_confidence:
            signals.append(long_signal)
        
        if short_signal['confidence'] >= self.min_confidence:
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
            'timestamp': datetime.now(damascus_tz)
        }
        
        logger.info(f"🎯 إشارة سكالبينج {symbol}: {best_signal['direction']} "
                   f"(ثقة: {best_signal['confidence']:.2%}, "
                   f"شروط: {best_signal['conditions_met']}/{best_signal['total_conditions']})")
        
        return signal_info

class BTCConfirmationSignalGenerator:
    """مولد إشارات تأكيد البيتكوين"""
    
    def __init__(self):
        self.min_confidence = TRADING_SETTINGS['min_btc_confidence']
    
    def get_btc_confirmation(self, client, direction):
        """الحصول على تأكيد إشارة البيتكوين"""
        try:
            btc_data = self._get_btc_data(client)
            if btc_data is None or len(btc_data) < 50:
                return None
            
            current_btc_price = self._get_btc_current_price(client)
            if not current_btc_price:
                return None
            
            btc_signal = self._analyze_btc_trend(btc_data, current_btc_price)
            
            if not btc_signal:
                return None
            
            confirmation = self._check_direction_confirmation(btc_signal, direction)
            
            return confirmation
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل تأكيد البيتكوين: {e}")
            return None
    
    def _get_btc_data(self, client):
        """جلب البيانات التاريخية للبيتكوين"""
        try:
            klines = client.futures_klines(
                symbol="BTCUSDT",
                interval=TRADING_SETTINGS['data_interval'],
                limit=100
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
            logger.error(f"❌ خطأ في جلب بيانات البيتكوين: {e}")
            return None
    
    def _get_btc_current_price(self, client):
        """الحصول على السعر الحالي للبيتكوين"""
        try:
            ticker = client.futures_symbol_ticker(symbol="BTCUSDT")
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر البيتكوين: {e}")
            return None
    
    def _analyze_btc_trend(self, data, current_price):
        """تحليل اتجاه البيتكوين"""
        try:
            df = data.copy()
            
            df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
            
            df['rsi'] = self._calculate_btc_rsi(df['close'])
            
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            trend_conditions = []
            trend_weights = []
            
            trend_conditions.append(latest['ema10'] > latest['ema20'])
            trend_weights.append(0.25)
            
            trend_conditions.append(latest['ema20'] > latest['ema50'])
            trend_weights.append(0.25)
            
            trend_conditions.append(latest['close'] > latest['ema20'])
            trend_weights.append(0.20)
            
            trend_conditions.append(latest['rsi'] > 45 and latest['rsi'] < 70)
            trend_weights.append(0.15)
            
            trend_conditions.append(latest['close'] > prev['close'])
            trend_weights.append(0.15)
            
            bullish_confidence = sum(weight for condition, weight in zip(trend_conditions, trend_weights) if condition)
            
            bearish_conditions = [
                latest['ema10'] < latest['ema20'],
                latest['ema20'] < latest['ema50'],
                latest['close'] < latest['ema20'],
                latest['rsi'] < 55 and latest['rsi'] > 30,
                latest['close'] < prev['close']
            ]
            
            bearish_confidence = sum(weight for condition, weight in zip(bearish_conditions, trend_weights) if condition)
            
            if bullish_confidence > bearish_confidence and bullish_confidence >= self.min_confidence:
                return {
                    'direction': 'LONG',
                    'confidence': bullish_confidence,
                    'trend_strength': 'STRONG' if bullish_confidence > 0.8 else 'MODERATE',
                    'timestamp': datetime.now(damascus_tz)
                }
            elif bearish_confidence > bullish_confidence and bearish_confidence >= self.min_confidence:
                return {
                    'direction': 'SHORT',
                    'confidence': bearish_confidence,
                    'trend_strength': 'STRONG' if bearish_confidence > 0.8 else 'MODERATE',
                    'timestamp': datetime.now(damascus_tz)
                }
            else:
                return {
                    'direction': 'NEUTRAL',
                    'confidence': max(bullish_confidence, bearish_confidence),
                    'trend_strength': 'WEAK',
                    'timestamp': datetime.now(damascus_tz)
                }
                
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل اتجاه البيتكوين: {e}")
            return None
    
    def _calculate_btc_rsi(self, prices, period=14):
        """حساب RSI للبيتكوين"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1]
    
    def _check_direction_confirmation(self, btc_signal, required_direction):
        """التحقق من تأكيد اتجاه البيتكوين"""
        if btc_signal['direction'] == 'NEUTRAL':
            return {
                'confirmed': False,
                'reason': 'الاتجاه المحايد للبيتكوين',
                'btc_confidence': btc_signal['confidence'],
                'btc_trend_strength': btc_signal['trend_strength']
            }
        
        if btc_signal['direction'] == required_direction:
            return {
                'confirmed': True,
                'btc_direction': btc_signal['direction'],
                'btc_confidence': btc_signal['confidence'],
                'btc_trend_strength': btc_signal['trend_strength'],
                'message': f'البوتكوين يؤكد الاتجاه {required_direction}'
            }
        else:
            return {
                'confirmed': False,
                'reason': f'اتجاه البيتكوين {btc_signal["direction"]} لا يتوافق مع {required_direction}',
                'btc_confidence': btc_signal['confidence'],
                'btc_trend_strength': btc_signal['trend_strength']
            }

class SimpleTradeManager:
    """مدير صفقات مبسط مع تتبع مستمر للحدود"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.precision_manager = PrecisionManager(client)
        self.active_trades = {}
        self.monitoring_thread = None
        self.monitoring_active = True
        
        # بدء مراقبة الصفقات النشطة
        self.start_trade_monitoring()
    
    def _get_current_price(self, symbol):
        """الحصول على السعر الحالي للعملة"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر {symbol}: {e}")
            return None
    
    def calculate_trade_limits(self, symbol, direction, entry_price):
        """حساب حدود الربح والخسارة للصفقة"""
        try:
            target_profit_pct = TRADING_SETTINGS['target_profit_pct'] / 100
            stop_loss_pct = TRADING_SETTINGS['stop_loss_pct'] / 100
            
            if direction == 'LONG':
                take_profit_price = entry_price * (1 + target_profit_pct)
                stop_loss_price = entry_price * (1 - stop_loss_pct)
            else:  # SHORT
                take_profit_price = entry_price * (1 - target_profit_pct)
                stop_loss_price = entry_price * (1 + stop_loss_pct)
            
            # ضبط الدقة
            take_profit_price = self.precision_manager.adjust_price(symbol, take_profit_price)
            stop_loss_price = self.precision_manager.adjust_price(symbol, stop_loss_price)
            
            return take_profit_price, stop_loss_price
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حدود الصفقة لـ {symbol}: {e}")
            # قيم افتراضية آمنة
            if direction == 'LONG':
                return self.precision_manager.adjust_price(symbol, entry_price * 1.015), self.precision_manager.adjust_price(symbol, entry_price * 0.985)
            else:
                return self.precision_manager.adjust_price(symbol, entry_price * 0.985), self.precision_manager.adjust_price(symbol, entry_price * 1.015)
    
    def start_trade_monitoring(self):
        """بدء مراقبة الصفقات النشطة"""
        def monitor_trades():
            while self.monitoring_active:
                try:
                    self.check_trade_limits()
                    self.check_trade_duration()
                    self.cleanup_closed_trades()
                    time.sleep(10)  # التحقق كل دقيقة
                except Exception as e:
                    logger.error(f"❌ خطأ في مراقبة الصفقات: {e}")
                    time.sleep(60)
        
        self.monitoring_thread = threading.Thread(target=monitor_trades, daemon=True)
        self.monitoring_thread.start()
        logger.info("✅ بدء مراقبة الصفقات النشطة")
    
    def check_trade_limits(self):
        """التحقق من حدود الربح والخسارة للصفقات النشطة"""
        try:
            for symbol, trade in list(self.active_trades.items()):
                if trade['status'] != 'open':
                    continue
                
                current_price = self._get_current_price(symbol)
                if not current_price:
                    continue
                
                entry_price = trade['entry_price']
                direction = trade['side']
                take_profit_price = trade['take_profit_price']
                stop_loss_price = trade['stop_loss_price']
                
                should_close = False
                close_reason = ""
                pnl_pct = 0
                
                if direction == 'LONG':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    if current_price >= take_profit_price:
                        should_close = True
                        close_reason = f"جني الربح ({pnl_pct:+.2f}%)"
                    elif current_price <= stop_loss_price:
                        should_close = True
                        close_reason = f"وقف الخسارة ({pnl_pct:+.2f}%)"
                else:  # SHORT
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                    if current_price <= take_profit_price:
                        should_close = True
                        close_reason = f"جني الربح ({pnl_pct:+.2f}%)"
                    elif current_price >= stop_loss_price:
                        should_close = True
                        close_reason = f"وقف الخسارة ({pnl_pct:+.2f}%)"
                
                if should_close:
                    logger.info(f"🔒 إغلاق صفقة {symbol}: {close_reason}")
                    self.close_trade(symbol, close_reason, current_price)
                    
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من حدود الصفقات: {e}")
    
    def check_trade_duration(self):
        """التحقق من مدة الصفقات النشطة"""
        try:
            current_time = datetime.now(damascus_tz)
            max_duration = TRADING_SETTINGS['max_trade_duration_minutes']
            
            for symbol, trade in list(self.active_trades.items()):
                if trade['status'] != 'open':
                    continue
                
                trade_duration = (current_time - trade['timestamp']).total_seconds() / 60
                if trade_duration >= max_duration:
                    current_price = self._get_current_price(symbol)
                    if current_price:
                        logger.info(f"⏰ إغلاق صفقة {symbol} لانتهاء المدة ({trade_duration:.1f} دقيقة)")
                        self.close_trade(symbol, f"انتهت المدة الزمنية ({trade_duration:.1f} دقيقة)", current_price)
                        
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من مدة الصفقات: {e}")
    
    def cleanup_closed_trades(self):
        """تنظيف الصفقات المغلقة والتحقق من المراكز النشطة"""
        try:
            # الحصول على المراكز النشطة من المنصة
            account_info = self.client.futures_account()
            positions = account_info['positions']
            
            current_active_symbols = set()
            for position in positions:
                symbol = position['symbol']
                quantity = float(position['positionAmt'])
                if quantity != 0:
                    current_active_symbols.add(symbol)
            
            # إغلاق الصفقات التي لم تعد نشطة على المنصة
            for symbol in list(self.active_trades.keys()):
                if symbol not in current_active_symbols and self.active_trades[symbol]['status'] == 'open':
                    logger.info(f"🔄 اكتشاف إغلاق صفقة: {symbol}")
                    self._handle_externally_closed_trade(symbol)
                    
        except Exception as e:
            logger.error(f"❌ خطأ في تنظيف الصفقات: {e}")
    
    def _handle_externally_closed_trade(self, symbol):
        """معالجة الصفقات المغلقة خارجياً"""
        try:
            if symbol in self.active_trades:
                trade = self.active_trades[symbol]
                current_price = self._get_current_price(symbol)
                
                if current_price:
                    entry_price = trade['entry_price']
                    if trade['side'] == 'LONG':
                        pnl_pct = (current_price - entry_price) / entry_price * 100
                        pnl_usd = (current_price - entry_price) * trade['quantity']
                    else:
                        pnl_pct = (entry_price - current_price) / entry_price * 100
                        pnl_usd = (entry_price - current_price) * trade['quantity']
                else:
                    pnl_pct = 0
                    pnl_usd = 0
                
                # تحديث حالة الصفقة
                trade['status'] = 'closed'
                trade['close_price'] = current_price
                trade['close_time'] = datetime.now(damascus_tz)
                trade['pnl_pct'] = pnl_pct
                trade['pnl_usd'] = pnl_usd
                trade['close_reason'] = 'إغلاق خارجي'
                
                # إرسال إشعار
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة خارجي</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"سعر الدخول: ${entry_price:.4f}\n"
                        f"سعر الخروج: ${current_price:.4f if current_price else 'N/A'}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"الربح/الخسارة: {pnl_emoji} ${pnl_usd:+.2f}\n"
                        f"السبب: إغلاق يدوي أو خارجي\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم معالجة إغلاق صفقة {symbol} - PnL: {pnl_pct:+.2f}%")
                
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة الصفقة المغلقة خارجياً {symbol}: {e}")
    
    def close_trade(self, symbol, reason, current_price):
        """إغلاق صفقة نشطة"""
        try:
            trade = self.active_trades.get(symbol)
            if not trade or trade['status'] != 'open':
                return False
            
            quantity = trade['quantity']
            entry_price = trade['entry_price']
            direction = trade['side']
            
            # حساب الربح/الخسارة
            if direction == 'LONG':
                pnl_pct = (current_price - entry_price) / entry_price * 100
                pnl_usd = (current_price - entry_price) * quantity
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                pnl_usd = (entry_price - current_price) * quantity
            
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
                # تحديث حالة الصفقة
                trade['status'] = 'closed'
                trade['close_price'] = current_price
                trade['close_time'] = datetime.now(damascus_tz)
                trade['pnl_pct'] = pnl_pct
                trade['pnl_usd'] = pnl_usd
                trade['close_reason'] = reason
                
                # إرسال إشعار الإغلاق
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة تلقائي</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"سعر الدخول: ${entry_price:.4f}\n"
                        f"سعر الخروج: ${current_price:.4f}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"الربح/الخسارة: {pnl_emoji} ${pnl_usd:+.2f}\n"
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
    
    def add_trade(self, symbol, trade_data):
        """إضافة صفقة جديدة"""
        try:
            # حساب حدود الصفقة
            take_profit_price, stop_loss_price = self.calculate_trade_limits(
                symbol, trade_data['side'], trade_data['entry_price']
            )
            
            trade_data.update({
                'take_profit_price': take_profit_price,
                'stop_loss_price': stop_loss_price,
                'status': 'open',
                'timestamp': datetime.now(damascus_tz)
            })
            
            self.active_trades[symbol] = trade_data
            
            logger.info(f"✅ تمت إضافة صفقة جديدة لـ {symbol}")
            logger.info(f"  🎯 جني الربح: ${take_profit_price:.4f}")
            logger.info(f"  🛡️ وقف الخسارة: ${stop_loss_price:.4f}")
            
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة صفقة {symbol}: {e}")
    
    def remove_trade(self, symbol):
        """إزالة صفقة"""
        if symbol in self.active_trades:
            del self.active_trades[symbol]
    
    def get_trade(self, symbol):
        """الحصول على صفقة"""
        return self.active_trades.get(symbol)
    
    def get_all_trades(self):
        """الحصول على جميع الصفقات"""
        return self.active_trades.copy()
    
    def get_active_trades_count(self):
        """عدد الصفقات النشطة"""
        return len([t for t in self.active_trades.values() if t['status'] == 'open'])
    
    def is_symbol_trading(self, symbol):
        """التحقق إذا كانت العملة متداولة"""
        return symbol in self.active_trades and self.active_trades[symbol]['status'] == 'open'
    
    def get_symbol_trades_count(self, symbol):
        """عدد الصفقات على عملة معينة"""
        count = 0
        for trade_symbol, trade in self.active_trades.items():
            if trade_symbol == symbol and trade['status'] == 'open':
                count += 1
        return count
    
    def get_symbol_trades_direction(self, symbol):
        """اتجاهات الصفقات على عملة معينة"""
        directions = []
        for trade_symbol, trade in self.active_trades.items():
            if trade_symbol == symbol and trade['status'] == 'open':
                directions.append(trade['side'])
        return directions
    
    def can_open_trade_on_symbol(self, symbol, direction):
        """التحقق إذا كان يمكن فتح صفقة على عملة"""
        symbol_trades_count = self.get_symbol_trades_count(symbol)
        symbol_directions = self.get_symbol_trades_direction(symbol)
        
        if symbol_trades_count >= TRADING_SETTINGS['max_trades_per_symbol']:
            return False, "الحد الأقصى للصفقات على هذه العملة"
        
        if symbol_directions and direction not in symbol_directions:
            return False, "الاتجاه مختلف عن الصفقات الحالية على هذه العملة"
        
        return True, "يمكن فتح الصفقة"
    
    def stop_monitoring(self):
        """إيقاف مراقبة الصفقات"""
        self.monitoring_active = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=5)

class TelegramNotifier:
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
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        
        macd_info = ""
        if 'indicators' in signal:
            macd_status = "🟢 فوق الإشارة" if signal['indicators']['macd_above_signal'] else "🔴 تحت الإشارة"
            histogram_status = "🟢 موجب" if signal['indicators']['macd_histogram_positive'] else "🔴 سالب"
            macd_info = f"📊 الماكد: {macd_status} | الهيسطجرام: {histogram_status}\n"
        
        message = (
            f"{direction_emoji} <b>إشارة سكالبينج جديدة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"السعر: ${current_price:.4f}\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
            f"{macd_info}"
            f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message, 'trade_signal')

class ScalpingTradingBot:
    _instance = None
    
    TRADING_SETTINGS = TRADING_SETTINGS
    
    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self):
        if ScalpingTradingBot._instance is not None:
            raise Exception("هذه الفئة تستخدم نمط Singleton")
        
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

        self.signal_generator = ScalpingSignalGenerator()
        self.btc_confirmation = BTCConfirmationSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = SimpleTradeManager(self.client, self.notifier)
        
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
        
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت السكالبينج بنجاح مع نظام المراقبة المبسط")

    def test_connection(self):
        try:
            self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise

    def get_real_time_balance(self):
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

    # ... (الكود السابق يبقى كما هو)

    def start_services(self):
        def sync_thread():
            while True:
                try:
                    self.trade_manager.cleanup_closed_trades()
                    self.update_real_time_balance()
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(60)
    
        threading.Thread(target=sync_thread, daemon=True).start()
    
        if self.notifier:
            # ✅ إضافة التقرير اليومي عند الساعة 11 مساءً بتوقيت دمشق
            schedule.every().day.at("23:00").do(self.send_daily_report)
        
            schedule.every(6).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)
            schedule.every(1).hours.do(self.send_heartbeat)

    def send_daily_report(self):
        """إرسال تقرير يومي شامل عن أداء البوت"""
        try:
            if not self.notifier:
                return
        
            # الحصول على إحصائيات اليوم
            today = datetime.now(damascus_tz).date()
            daily_trades = self.performance_stats['daily_trades_count']
        
            # حساب الربح/الخسارة اليومي
            daily_pnl = self.calculate_daily_pnl()
        
            # الحصول على الصفقات النشطة الحالية
            active_trades = self.trade_manager.get_active_trades_count()
        
            # تحديث الرصيد
            self.update_real_time_balance()
            balance = self.real_time_balance
        
            # حساب معدل الفوز
            win_rate = 0
            if self.performance_stats['trades_closed'] > 0:
                win_rate = (self.performance_stats['winning_trades'] / self.performance_stats['trades_closed']) * 100
        
            # إعداد رسالة التقرير اليومي
            message = (
                f"📊 <b>التقرير اليومي - بوت السكالبينج</b>\n"
                f"📅 التاريخ: {today.strftime('%Y-%m-%d')}\n"
                f"⏰ الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}\n"
                f"═══════════════════\n"
                f"📈 <b>أداء اليوم:</b>\n"
                f"• عدد الصفقات: {daily_trades}\n"
                f"• الصفقات النشطة: {active_trades}\n"
                f"• الربح/الخسارة: {daily_pnl:+.2f}%\n"
                f"═══════════════════\n"
                f"💰 <b>الرصيد:</b>\n"
                f"• الإجمالي: ${balance['total_balance']:.2f}\n"
                f"• المتاح: ${balance['available_balance']:.2f}\n"
                f"═══════════════════\n"
                f"🎯 <b>الإعدادات النشطة:</b>\n"
                f"• العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"• الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"• وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"• جني الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"═══════════════════\n"
                f"📋 <b>ملخص الأداء الكلي:</b>\n"
                f"• إجمالي الصفقات: {self.performance_stats['trades_opened']}\n"
                f"• الصفقات المغلقة: {self.performance_stats['trades_closed']}\n"
                f"• الصفقات الرابحة: {self.performance_stats['winning_trades']}\n"
                f"• الصفقات الخاسرة: {self.performance_stats['losing_trades']}\n"
                f"• معدل الفوز: {win_rate:.1f}%\n"
                f"• الخسائر المتتالية: {self.performance_stats['consecutive_losses']}\n"
                f"🔚 <b>نهاية التقرير اليومي</b>"
            )
        
            success = self.notifier.send_message(message, 'daily_report')
            if success:
                logger.info("✅ تم إرسال التقرير اليومي بنجاح")
            
            return success
        
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال التقرير اليومي: {e}")
            return False

    def calculate_daily_pnl(self):
        """حساب الربح/الخسارة اليومي - نسخة مبسطة"""
        try:
            # هذه نسخة مبسطة - يمكن تطويرها لتتبع PnL يومي مفصل
            # حالياً نعود بقيمة إجمالية
            return self.performance_stats.get('total_pnl', 0.0)
        except Exception as e:
            logger.error(f"❌ خطأ في حساب PnL اليومي: {e}")
            return 0.0

# ... (بقية الكود يبقى كما هو)
    def update_real_time_balance(self):
        try:
            self.real_time_balance = self.get_real_time_balance()
            return True
        except Exception as e:
            logger.error(f"❌ فشل تحديث الرصيد: {e}")
            return False

    def send_startup_message(self):
        if self.notifier:
            balance = self.real_time_balance
            btc_status = "مفعل ✅" if self.TRADING_SETTINGS['btc_confirmation_required'] else "غير مفعل ❌"
            message = (
                "⚡ <b>بدء تشغيل بوت السكالبينج المبسط</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد + بداية الاتجاه\n"
                f"العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"🎯 جني الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"🛡️ وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"⏰ مدة الصفقة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                f"المسح كل: {self.TRADING_SETTINGS['rescan_interval_minutes']} دقائق\n"
                f"الحد الأقصى للصفقات: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"الحد الأقصى للصفقات لكل عملة: {self.TRADING_SETTINGS['max_trades_per_symbol']}\n"
                f"🔧 نظام إدارة الدقة: نشط ✅\n"
                f"₿ تأكيد البيتكوين: {btc_status}\n"
                f"📊 نظام المراقبة المستمرة: نشط ✅\n"
                f"🔄 التحقق من الصفقات: كل دقيقة\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.notifier.send_message(message)

    def send_performance_report(self):
        if not self.notifier:
            return
        
        active_trades = self.trade_manager.get_active_trades_count()
        win_rate = 0
        if self.performance_stats['trades_closed'] > 0:
            win_rate = (self.performance_stats['winning_trades'] / self.performance_stats['trades_closed']) * 100
        
        message = (
            f"📊 <b>تقرير أداء السكالبينج</b>\n"
            f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد + بداية الاتجاه\n"
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
        if not self.notifier:
            return
        
        try:
            self.update_real_time_balance()
            balance = self.real_time_balance
            active_trades = self.trade_manager.get_active_trades_count()
            
            message = (
                f"💰 <b>تقرير الرصيد الحقيقي</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد + بداية الاتجاه\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الرصيد المتاح: ${balance['available_balance']:.2f}\n"
                f"الصفقات النشطة: {active_trades}\n"
                f"آخر تحديث: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            
            self.notifier.send_message(message, 'balance_report')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تقرير الرصيد: {e}")

    def send_heartbeat(self):
        if self.notifier:
            active_trades = self.trade_manager.get_active_trades_count()
            message = f"💓 بوت السكالبينج نشط - الصفقات النشطة: {active_trades}"
            self.notifier.send_message(message)

    def get_historical_data(self, symbol, interval, limit=100):
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
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر {symbol}: {e}")
            return None

    def can_open_trade(self, symbol, direction):
        reasons = []
        
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات النشطة")
        
        can_open_symbol, symbol_reason = self.trade_manager.can_open_trade_on_symbol(symbol, direction)
        if not can_open_symbol:
            reasons.append(symbol_reason)
        
        available_balance = self.real_time_balance['available_balance']
        if available_balance < self.TRADING_SETTINGS['used_balance_per_trade']:
            reasons.append("رصيد غير كافي")
        
        if self.performance_stats['daily_trades_count'] >= self.TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
        
        if self.performance_stats['consecutive_losses'] >= 3:
            last_trade_time = self.performance_stats.get('last_trade_time')
            if last_trade_time and (datetime.now(damascus_tz) - last_trade_time).total_seconds() < self.TRADING_SETTINGS['cooldown_after_loss'] * 60:
                reasons.append("فترة تبريد بعد خسائر متتالية")
        
        return len(reasons) == 0, reasons

    def calculate_position_size(self, symbol, current_price):
        try:
            nominal_size = self.TRADING_SETTINGS['used_balance_per_trade'] * self.TRADING_SETTINGS['max_leverage']
            quantity = nominal_size / current_price
            
            adjusted_quantity = self.trade_manager.precision_manager.adjust_quantity(symbol, quantity)
            
            if adjusted_quantity and adjusted_quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol}: {adjusted_quantity:.6f} (رصيد مستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}, رافعة: {self.TRADING_SETTINGS['max_leverage']}x)")
                return adjusted_quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return None

    def set_leverage(self, symbol, leverage):
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة: {e}")
            return False

    def get_btc_confirmation(self, direction):
        """الحصول على تأكيد إشارة البيتكوين"""
        if not self.TRADING_SETTINGS['btc_confirmation_required']:
            return {'confirmed': True, 'reason': 'تأكيد البيتكوين غير مطلوب'}
        
        try:
            confirmation = self.btc_confirmation.get_btc_confirmation(self.client, direction)
            if confirmation:
                logger.info(f"₿ تأكيد البيتكوين لـ {direction}: {confirmation['confirmed']} - {confirmation.get('message', confirmation.get('reason', ''))}")
            return confirmation
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على تأكيد البيتكوين: {e}")
            return {'confirmed': False, 'reason': f'خطأ في تحليل البيتكوين: {e}'}

    def execute_trade(self, signal):
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            
            btc_confirmation = self.get_btc_confirmation(direction)
            if not btc_confirmation['confirmed']:
                logger.info(f"⏭️ تخطي {symbol} {direction}: {btc_confirmation.get('reason', 'تأكيد البيتكوين مطلوب')}")
                return False
            
            can_trade, reasons = self.can_open_trade(symbol, direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي {symbol} {direction}: {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                logger.error(f"❌ لا يمكن الحصول على سعر {symbol}")
                return False
            
            quantity = self.calculate_position_size(symbol, current_price)
            if not quantity:
                logger.warning(f"⚠️ لا يمكن حساب حجم آمن لـ {symbol}")
                return False
            
            leverage = self.TRADING_SETTINGS['max_leverage']
            self.set_leverage(symbol, leverage)
            
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"⚡ تنفيذ صفقة سكالبينج {symbol}: {direction} | الكمية: {quantity:.6f} | السعر: ${current_price:.4f}")
            
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
                
                trade_data = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': leverage,
                    'nominal_value': nominal_value,
                    'expected_profit': expected_profit,
                    'max_duration': self.TRADING_SETTINGS['max_trade_duration_minutes'],
                    'signal_confidence': signal['confidence'],
                    'btc_confirmation': btc_confirmation
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                
                if self.notifier:
                    symbol_trades_count = self.trade_manager.get_symbol_trades_count(symbol)
                    
                    btc_info = ""
                    if btc_confirmation.get('confirmed'):
                        btc_info = f"₿ تأكيد البيتكوين: {btc_confirmation.get('btc_trend_strength', 'N/A')} (ثقة: {btc_confirmation.get('btc_confidence', 0):.2%})\n"
                    
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة سكالبينج</b>\n"
                        f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد + بداية الاتجاه\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"القيمة الاسمية: ${nominal_value:.2f}\n"
                        f"الرافعة: {leverage}x\n"
                        f"🎯 جني الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                        f"🛡️ وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                        f"⏰ المدة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                        f"💰 الربح المتوقع: ${expected_profit:.4f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"{btc_info}"
                        f"📈 الصفقات النشطة على {symbol}: {symbol_trades_count}/{self.TRADING_SETTINGS['max_trades_per_symbol']}\n"
                        f"📊 نظام المراقبة: نشط ✅\n"
                        f"🔄 التحقق من الحدود: كل دقيقة\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة سكالبينج {direction} لـ {symbol} مع نظام المراقبة المستمرة")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            return False

    def scan_market(self):
        """مسح السوق للبحث عن إشارات - مع التحكم في البحث"""
        
        active_trades_count = self.trade_manager.get_active_trades_count()
        if active_trades_count >= self.TRADING_SETTINGS['max_active_trades']:
            logger.info(f"⏭️ تخطي البحث عن إشارات - عدد الصفقات النشطة ({active_trades_count}) وصل الحد الأقصى ({self.TRADING_SETTINGS['max_active_trades']})")
            return []
        
        logger.info("🔍 بدء مسح السوق للسكالبينج...")
        
        opportunities = []
        
        for symbol in self.TRADING_SETTINGS['symbols']:
            try:
                symbol_trades_count = self.trade_manager.get_symbol_trades_count(symbol)
                if symbol_trades_count >= self.TRADING_SETTINGS['max_trades_per_symbol']:
                    logger.info(f"⏭️ تخطي {symbol} - وصل الحد الأقصى للصفقات ({symbol_trades_count})")
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
        try:
            start_time = time.time()
            
            self.trade_manager.cleanup_closed_trades()
            
            opportunities = self.scan_market()
            
            executed_trades = 0
            for signal in opportunities:
                if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
                    logger.info("⏹️ إيقاف التنفيذ - وصل الحد الأقصى للصفقات النشطة")
                    break
                    
                if self.execute_trade(signal):
                    executed_trades += 1
                    break
            
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
                    'confidence': trade.get('signal_confidence', 0),
                    'nominal_value': trade.get('nominal_value', 0),
                    'expected_profit': trade.get('expected_profit', 0),
                    'max_duration': trade.get('max_duration', 15),
                    'btc_confirmation': trade.get('btc_confirmation', {})
                }
                
                # حساب الربح/الخسارة الحالي
                if current_price:
                    if trade['side'] == 'LONG':
                        pnl_pct = (current_price - trade['entry_price']) / trade['entry_price'] * 100
                    else:
                        pnl_pct = (trade['entry_price'] - current_price) / trade['entry_price'] * 100
                    trade_info['current_pnl_pct'] = pnl_pct
                
                active_trades.append(trade_info)
        
        return active_trades

    def get_market_analysis(self, symbol):
        try:
            data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'])
            if data is None:
                return {'error': 'لا توجد بيانات'}
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return {'error': 'لا يمكن الحصول على السعر'}
            
            signal = self.signal_generator.generate_signal(symbol, data, current_price)
            
            btc_analysis = None
            if signal and self.TRADING_SETTINGS['btc_confirmation_required']:
                btc_analysis = self.btc_confirmation.get_btc_confirmation(self.client, signal['direction'])
            
            return {
                'symbol': symbol,
                'current_price': current_price,
                'signal': signal,
                'btc_confirmation': btc_analysis,
                'timestamp': datetime.now(damascus_tz).isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}

    def run(self):
        logger.info("🚀 بدء تشغيل بوت السكالبينج مع نظام المراقبة المبسط...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            btc_status = "مفعل ✅" if self.TRADING_SETTINGS['btc_confirmation_required'] else "غير مفعل ❌"
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت السكالبينج المبسط</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد + بداية الاتجاه\n"
                f"العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"🎯 جني الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"🛡️ وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"⏰ مدة الصفقة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                f"الحد الأقصى للصفقات: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"الحد الأقصى للصفقات لكل عملة: {self.TRADING_SETTINGS['max_trades_per_symbol']}\n"
                f"🔧 نظام إدارة الدقة: نشط ✅\n"
                f"₿ تأكيد البيتكوين: {btc_status}\n"
                f"📊 نظام المراقبة المستمرة: نشط ✅\n"
                f"🔄 التحقق من الصفقات: كل دقيقة\n"
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
            self.trade_manager.stop_monitoring()

def main():
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
