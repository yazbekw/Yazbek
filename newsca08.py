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
    'symbols': ["ETHUSDT","BNBUSDT"],
    'used_balance_per_trade': 12,
    'max_leverage': 4,
    'nominal_trade_size': 48,
    'max_active_trades': 1,
    'data_interval': '5m',
    'rescan_interval_minutes': 3,
    'min_signal_confidence': 0.85,
    'target_profit_pct': 0.15,
    'stop_loss_pct': 0.07,
    'max_trade_duration_minutes': 20,
    'max_daily_trades': 30,
    'cooldown_after_loss': 5,
    'max_trades_per_symbol': 2,
    'order_timeout_minutes': 1,
    'btc_confirmation_required': True,
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

class ScalpingTradingBot:
    _instance = None
    
    def __init__(self):
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        self.client = Client(self.api_key, self.api_secret)
        self.settings = TRADING_SETTINGS
        self.active_trades = {}
        self.daily_trades_count = 0
        self.last_trade_time = None
        self.daily_reset_time = datetime.now(damascus_tz).date()
        self.trade_history = []
        
        # اختبار الاتصال
        try:
            self.client.get_account()
            logger.info("تم الاتصال بنجاح مع Binance API")
        except Exception as e:
            logger.error(f"فشل الاتصال مع Binance API: {e}")
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = ScalpingTradingBot()
        return cls._instance

    def calculate_technical_indicators(self, df):
        """حساب المؤشرات الفنية"""
        try:
            # RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # MACD
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
            
            # Bollinger Bands
            df['bb_middle'] = df['close'].rolling(20).mean()
            bb_std = df['close'].rolling(20).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
            
            # الزخم
            df['momentum'] = df['close'] - df['close'].shift(5)
            
            return df
        except Exception as e:
            logger.error(f"خطأ في حساب المؤشرات الفنية: {e}")
            return df

    def detect_peaks_and_valleys(self, prices):
        """كشف القمم والقيعان"""
        try:
            peaks, _ = find_peaks(prices, distance=5, prominence=0.01)
            valleys, _ = find_peaks(-prices, distance=5, prominence=0.01)
            return peaks, valleys
        except Exception as e:
            logger.error(f"خطأ في كشف القمم والقيعان: {e}")
            return [], []

    def analyze_market_structure(self, df):
        """تحليل هيكل السوق"""
        try:
            prices = df['close'].values
            peaks, valleys = self.detect_peaks_and_valleys(prices)
            
            # تحليل الاتجاه
            if len(peaks) > 1 and len(valleys) > 1:
                recent_peak = prices[peaks[-1]] if len(peaks) > 0 else prices[-1]
                recent_valley = prices[valleys[-1]] if len(valleys) > 0 else prices[-1]
                
                higher_highs = all(prices[peaks[i]] > prices[peaks[i-1]] for i in range(1, len(peaks)))
                higher_lows = all(prices[valleys[i]] > prices[valleys[i-1]] for i in range(1, len(valleys)))
                lower_highs = all(prices[peaks[i]] < prices[peaks[i-1]] for i in range(1, len(peaks)))
                lower_lows = all(prices[valleys[i]] < prices[valleys[i-1]] for i in range(1, len(valleys)))
                
                if higher_highs and higher_lows:
                    return "UPTREND", 0.8
                elif lower_highs and lower_lows:
                    return "DOWNTREND", 0.8
                else:
                    return "RANGING", 0.6
            else:
                return "NEUTRAL", 0.5
                
        except Exception as e:
            logger.error(f"خطأ في تحليل هيكل السوق: {e}")
            return "NEUTRAL", 0.5

    def generate_trading_signal(self, df):
        """توليد إشارة تداول"""
        try:
            current_price = df['close'].iloc[-1]
            rsi = df['rsi'].iloc[-1]
            macd = df['macd'].iloc[-1]
            macd_signal = df['macd_signal'].iloc[-1]
            bb_upper = df['bb_upper'].iloc[-1]
            bb_lower = df['bb_lower'].iloc[-1]
            momentum = df['momentum'].iloc[-1]
            
            # تحليل هيكل السوق
            market_structure, structure_confidence = self.analyze_market_structure(df)
            
            signal_confidence = 0.5
            signal = "HOLD"
            
            # استراتيجية التداول
            buy_signals = 0
            sell_signals = 0
            
            # شروط الشراء
            if rsi < 30:
                buy_signals += 1
            if macd > macd_signal:
                buy_signals += 1
            if current_price < bb_lower:
                buy_signals += 1
            if momentum > 0:
                buy_signals += 1
            if market_structure == "UPTREND":
                buy_signals += 2
            
            # شروط البيع
            if rsi > 70:
                sell_signals += 1
            if macd < macd_signal:
                sell_signals += 1
            if current_price > bb_upper:
                sell_signals += 1
            if momentum < 0:
                sell_signals += 1
            if market_structure == "DOWNTREND":
                sell_signals += 2
            
            # تحديد الإشارة النهائية
            if buy_signals >= 3 and buy_signals > sell_signals:
                signal = "BUY"
                signal_confidence = min(0.95, 0.5 + (buy_signals * 0.1))
            elif sell_signals >= 3 and sell_signals > buy_signals:
                signal = "SELL"
                signal_confidence = min(0.95, 0.5 + (sell_signals * 0.1))
            
            # تعديل الثقة بناء على ثقة هيكل السوق
            signal_confidence = (signal_confidence + structure_confidence) / 2
            
            return signal, signal_confidence, {
                'rsi': rsi,
                'macd': macd,
                'bb_position': (current_price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5,
                'momentum': momentum,
                'market_structure': market_structure
            }
            
        except Exception as e:
            logger.error(f"خطأ في توليد إشارة التداول: {e}")
            return "HOLD", 0.5, {}

    def get_btc_confirmation(self):
        """الحصول على تأكيد من BTC"""
        try:
            btc_klines = self.client.get_klines(
                symbol='BTCUSDT',
                interval=self.client.KLINE_INTERVAL_5MINUTE,
                limit=50
            )
            
            btc_df = pd.DataFrame(btc_klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close']:
                btc_df[col] = pd.to_numeric(btc_df[col])
            
            btc_df = self.calculate_technical_indicators(btc_df)
            btc_signal, btc_confidence, _ = self.generate_trading_signal(btc_df)
            
            return btc_signal, btc_confidence
            
        except Exception as e:
            logger.error(f"خطأ في الحصول على تأكيد BTC: {e}")
            return "HOLD", 0.5

    def calculate_stop_loss_price(self, entry_price, side, stop_loss_pct):
        """حساب سعر وقف الخسارة"""
        if side == "BUY":
            return entry_price * (1 - stop_loss_pct)
        else:  # SELL
            return entry_price * (1 + stop_loss_pct)

    def calculate_take_profit_price(self, entry_price, side, target_profit_pct):
        """حساب سعر جني الأرباح"""
        if side == "BUY":
            return entry_price * (1 + target_profit_pct)
        else:  # SELL
            return entry_price * (1 - target_profit_pct)

    def get_symbol_info(self, symbol):
        """الحصول على معلومات الزوج"""
        try:
            info = self.client.get_symbol_info(symbol)
            return info
        except Exception as e:
            logger.error(f"Error getting symbol info for {symbol}: {e}")
            return None

    def format_quantity(self, symbol, quantity):
        """تقريب الكمية حسب متطلبات بينانس"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return round(quantity, 6)
            
            for filter in symbol_info['filters']:
                if filter['filterType'] == 'LOT_SIZE':
                    step_size = float(filter['stepSize'])
                    precision = int(round(-np.log10(step_size)))
                    return round(quantity, precision)
            
            return round(quantity, 6)
        except Exception as e:
            logger.error(f"Error formatting quantity: {e}")
            return round(quantity, 6)

    def format_price(self, symbol, price):
        """تقريب السعر حسب متطلبات بينانس"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return round(price, 6)
            
            for filter in symbol_info['filters']:
                if filter['filterType'] == 'PRICE_FILTER':
                    tick_size = float(filter['tickSize'])
                    precision = int(round(-np.log10(tick_size)))
                    return round(price, precision)
            
            return round(price, 6)
        except Exception as e:
            logger.error(f"Error formatting price: {e}")
            return round(price, 6)

    def open_trade_with_stop_orders(self, symbol, side, signal_confidence):
        """فتح صفقة مع أوامر وقف الخسارة وجني الأرباح فوراً"""
        try:
            # الحصول على السعر الحالي
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
            
            # حساب حجم الصفقة
            quantity = self.settings['nominal_trade_size'] / current_price
            quantity = self.format_quantity(symbol, quantity)
            
            # فتح أمر السوق
            market_order = self.client.create_order(
                symbol=symbol,
                side=side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            
            logger.info(f"تم فتح صفقة {side} على {symbol} - الكمية: {quantity} - السعر: {current_price}")
            
            # الحصول على سعر الدخول الفعلي من الأوامر الممتلئة
            entry_price = current_price
            if 'fills' in market_order and market_order['fills']:
                filled_prices = [float(fill['price']) for fill in market_order['fills']]
                entry_price = sum(filled_prices) / len(filled_prices)
            
            # حساب أسعار الوقف والجني
            stop_loss_price = self.calculate_stop_loss_price(
                entry_price, side, self.settings['stop_loss_pct']
            )
            take_profit_price = self.calculate_take_profit_price(
                entry_price, side, self.settings['target_profit_pct']
            )
            
            # تقريب الأسعار حسب متطلبات بينانس
            stop_loss_price = self.format_price(symbol, stop_loss_price)
            take_profit_price = self.format_price(symbol, take_profit_price)
            
            # وضع أمر وقف الخسارة
            stop_loss_order = None
            if side == "BUY":
                stop_loss_order = self.client.create_order(
                    symbol=symbol,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_STOP_LOSS_LIMIT,
                    quantity=quantity,
                    price=stop_loss_price,
                    stopPrice=stop_loss_price,
                    timeInForce=TIME_IN_FORCE_GTC
                )
            else:  # SELL
                stop_loss_order = self.client.create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_STOP_LOSS_LIMIT,
                    quantity=quantity,
                    price=stop_loss_price,
                    stopPrice=stop_loss_price,
                    timeInForce=TIME_IN_FORCE_GTC
                )
            
            logger.info(f"تم وضع وقف الخسارة لـ {symbol} عند السعر: {stop_loss_price}")
            
            # وضع أمر جني الأرباح
            take_profit_order = None
            if side == "BUY":
                take_profit_order = self.client.create_order(
                    symbol=symbol,
                    side=SIDE_SELL,
                    type=ORDER_TYPE_TAKE_PROFIT_LIMIT,
                    quantity=quantity,
                    price=take_profit_price,
                    stopPrice=take_profit_price,
                    timeInForce=TIME_IN_FORCE_GTC
                )
            else:  # SELL
                take_profit_order = self.client.create_order(
                    symbol=symbol,
                    side=SIDE_BUY,
                    type=ORDER_TYPE_TAKE_PROFIT_LIMIT,
                    quantity=quantity,
                    price=take_profit_price,
                    stopPrice=take_profit_price,
                    timeInForce=TIME_IN_FORCE_GTC
                )
            
            logger.info(f"تم وضع جني الأرباح لـ {symbol} عند السعر: {take_profit_price}")
            
            # حفظ معلومات الصفقة
            trade_info = {
                'symbol': symbol,
                'side': side,
                'entry_price': entry_price,
                'quantity': quantity,
                'open_time': datetime.now(damascus_tz),
                'stop_loss_order_id': stop_loss_order['orderId'],
                'take_profit_order_id': take_profit_order['orderId'],
                'stop_loss_price': stop_loss_price,
                'take_profit_price': take_profit_price,
                'signal_confidence': signal_confidence
            }
            
            self.active_trades[symbol] = trade_info
            self.daily_trades_count += 1
            self.last_trade_time = datetime.now(damascus_tz)
            
            return {
                'success': True,
                'trade_info': trade_info,
                'message': f'تم فتح الصفقة بنجاح مع أوامر الوقف'
            }
            
        except Exception as e:
            logger.error(f"خطأ في فتح الصفقة مع أوامر الوقف: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def monitor_active_trades(self):
        """مراقبة الصفقات النشطة وإدارة أوامر الوقف"""
        try:
            current_time = datetime.now(damascus_tz)
            symbols_to_remove = []
            
            for symbol, trade_info in self.active_trades.items():
                # التحقق من مدة الصفقة
                trade_duration = (current_time - trade_info['open_time']).total_seconds() / 60
                if trade_duration > self.settings['max_trade_duration_minutes']:
                    logger.info(f"إغلاق الصفقة على {symbol} بسبب تجاوز المدة الزمنية")
                    self.close_trade(symbol)
                    symbols_to_remove.append(symbol)
                    continue
                
                # التحقق من حالة أوامر الوقف
                try:
                    # التحقق من أمر وقف الخسارة
                    sl_order = self.client.get_order(
                        symbol=symbol,
                        orderId=trade_info['stop_loss_order_id']
                    )
                    
                    # التحقق من أمر جني الأرباح
                    tp_order = self.client.get_order(
                        symbol=symbol,
                        orderId=trade_info['take_profit_order_id']
                    )
                    
                    # إذا تم تنفيذ أحد الأوامر
                    if sl_order['status'] == 'FILLED' or tp_order['status'] == 'FILLED':
                        logger.info(f"تم إغلاق الصفقة على {symbol} عبر أمر الوقف")
                        symbols_to_remove.append(symbol)
                        
                except Exception as e:
                    logger.error(f"خطأ في مراقبة أوامر الوقف لـ {symbol}: {e}")
            
            # إزالة الصفقات المغلقة
            for symbol in symbols_to_remove:
                if symbol in self.active_trades:
                    del self.active_trades[symbol]
                    
        except Exception as e:
            logger.error(f"خطأ في مراقبة الصفقات النشطة: {e}")

    def close_trade(self, symbol):
        """إغلاق الصفقة يدوياً"""
        try:
            if symbol not in self.active_trades:
                return {'success': False, 'error': 'الصفقة غير موجودة'}
            
            trade_info = self.active_trades[symbol]
            quantity = trade_info['quantity']
            
            # تحديد اتجاه الإغلاق
            if trade_info['side'] == "BUY":
                close_side = SIDE_SELL
            else:
                close_side = SIDE_BUY
            
            # إغلاق الصفقة بأمر السوق
            close_order = self.client.create_order(
                symbol=symbol,
                side=close_side,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            
            # إلغاء أوامر الوقف
            try:
                self.client.cancel_order(
                    symbol=symbol,
                    orderId=trade_info['stop_loss_order_id']
                )
                self.client.cancel_order(
                    symbol=symbol,
                    orderId=trade_info['take_profit_order_id']
                )
            except Exception as e:
                logger.warning(f"لم يتم إلغاء أوامر الوقف: {e}")
            
            # حساب الربح/الخسارة
            current_price = float(self.client.get_symbol_ticker(symbol=symbol)['price'])
            if trade_info['side'] == "BUY":
                pnl_pct = (current_price - trade_info['entry_price']) / trade_info['entry_price'] * 100
            else:
                pnl_pct = (trade_info['entry_price'] - current_price) / trade_info['entry_price'] * 100
            
            logger.info(f"تم إغلاق الصفقة على {symbol} - الربح/الخسارة: {pnl_pct:.2f}%")
            
            # حفظ في السجل
            trade_history_entry = {
                'symbol': symbol,
                'side': trade_info['side'],
                'entry_price': trade_info['entry_price'],
                'exit_price': current_price,
                'quantity': quantity,
                'pnl_pct': pnl_pct,
                'open_time': trade_info['open_time'],
                'close_time': datetime.now(damascus_tz)
            }
            self.trade_history.append(trade_history_entry)
            
            del self.active_trades[symbol]
            return {
                'success': True,
                'pnl_pct': pnl_pct,
                'message': f'تم إغلاق الصفقة بنجاح'
            }
            
        except Exception as e:
            logger.error(f"خطأ في إغلاق الصفقة: {e}")
            return {
                'success': False,
                'error': str(e)
            }

    def get_market_analysis(self, symbol):
        """تحليل السوق الكامل"""
        try:
            # جلب البيانات
            klines = self.client.get_klines(
                symbol=symbol,
                interval=self.client.KLINE_INTERVAL_5MINUTE,
                limit=100
            )
            
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # تحويل الأنواع
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            
            # حساب المؤشرات الفنية
            df = self.calculate_technical_indicators(df)
            
            # توليد الإشارة
            signal, confidence, indicators = self.generate_trading_signal(df)
            
            # الحصول على تأكيد BTC إذا مطلوب
            btc_signal, btc_confidence = "HOLD", 0.5
            if self.settings['btc_confirmation_required']:
                btc_signal, btc_confidence = self.get_btc_confirmation()
            
            return {
                'symbol': symbol,
                'current_price': float(df['close'].iloc[-1]),
                'signal': signal,
                'confidence': confidence,
                'btc_signal': btc_signal,
                'btc_confidence': btc_confidence,
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz).isoformat()
            }
            
        except Exception as e:
            logger.error(f"خطأ في تحليل السوق: {e}")
            return {'error': str(e)}

    def check_trading_conditions(self):
        """التحقق من شروط التداول"""
        try:
            current_time = datetime.now(damascus_tz)
            
            # إعادة تعيين العداد اليومي
            if current_time.date() > self.daily_reset_time:
                self.daily_trades_count = 0
                self.daily_reset_time = current_time.date()
                logger.info("تم إعادة تعيين العداد اليومي للصفقات")
            
            # التحقق من الحد الأقصى اليومي
            if self.daily_trades_count >= self.settings['max_daily_trades']:
                logger.info("تم الوصول إلى الحد الأقصى اليومي للصفقات")
                return False
            
            # التحقق من فترة التبريد بعد خسارة
            if self.last_trade_time:
                time_since_last_trade = (current_time - self.last_trade_time).total_seconds() / 60
                if time_since_last_trade < self.settings['cooldown_after_loss']:
                    return False
            
            # التحقق من عدد الصفقات النشطة
            if len(self.active_trades) >= self.settings['max_active_trades']:
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"خطأ في التحقق من شروط التداول: {e}")
            return False

    def run_trading_cycle(self):
        """دورة التداول الرئيسية"""
        try:
            # مراقبة الصفقات النشطة
            self.monitor_active_trades()
            
            # التحقق من شروط التداول
            if not self.check_trading_conditions():
                return
            
            # تحليل الأسواق واتخاذ القرارات
            for symbol in self.settings['symbols']:
                if symbol not in self.active_trades:
                    analysis = self.get_market_analysis(symbol)
                    
                    if 'error' in analysis:
                        continue
                    
                    # التحقق من ثقة الإشارة وتأكيد BTC
                    valid_signal = (
                        analysis['confidence'] >= self.settings['min_signal_confidence'] and
                        analysis['signal'] != "HOLD"
                    )
                    
                    valid_btc_confirmation = (
                        not self.settings['btc_confirmation_required'] or
                        analysis['btc_confidence'] >= self.settings['min_btc_confidence']
                    )
                    
                    if valid_signal and valid_btc_confirmation:
                        logger.info(f"إشارة تداول على {symbol}: {analysis['signal']} - ثقة: {analysis['confidence']:.2f}")
                        
                        # فتح الصفقة مع أوامر الوقف
                        result = self.open_trade_with_stop_orders(
                            symbol, analysis['signal'], analysis['confidence']
                        )
                        
                        if result['success']:
                            logger.info(f"تم فتح الصفقة بنجاح على {symbol}")
                        else:
                            logger.error(f"فشل فتح الصفقة على {symbol}: {result['error']}")
            
        except Exception as e:
            logger.error(f"خطأ في دورة التداول: {e}")

    def start_trading(self):
        """بدء التداول"""
        logger.info("بدء تشغيل بوت التداول السريع")
        
        # تشغيل دورة التداول كل فترة
        schedule.every(self.settings['rescan_interval_minutes']).minutes.do(self.run_trading_cycle)
        
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                logger.error(f"خطأ في التشغيل الرئيسي: {e}")
                time.sleep(60)

def main():
    # تشغيل تطبيق Flask في thread منفصل
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
    
    # بدء التداول
    bot = ScalpingTradingBot.get_instance()
    bot.start_trading()

if __name__ == "__main__":
    main()
