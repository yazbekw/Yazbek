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
    'used_balance_per_trade': 8,
    'max_leverage': 6,
    'nominal_trade_size': 48,
    'max_active_trades': 2,
    'data_interval': '5m',
    'rescan_interval_minutes': 3,
    'min_signal_confidence': 0.90,
    'target_profit_pct': 0.22,
    'stop_loss_pct': 0.10,
    'max_trade_duration_minutes': 20,
    'max_daily_trades': 30,
    'cooldown_after_loss': 5,
    'max_trades_per_symbol': 2,
    'order_timeout_minutes': 1,
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
        
        # المتوسطات المتحركة الأسية
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        
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
            'ema10': latest['ema10'],
            'ema20': latest['ema20'],
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
    
        # الشروط الأساسية (المتوسطات + RSI)
        conditions.append(indicators['ema5'] > indicators['ema10'])
        weights.append(0.20)
        
        conditions.append(indicators['ema10'] > indicators['ema20'])
        weights.append(0.25)
        
        conditions.append(indicators['rsi'] < 65)
        weights.append(0.10)
        
        conditions.append(indicators['rsi'] > 30)
        weights.append(0.10)
        
        # شروط الماكد
        conditions.append(indicators['macd_above_signal'])
        weights.append(0.15)
        
        conditions.append(indicators['macd_histogram_positive'])
        weights.append(0.10)
        
        conditions.append(indicators.get('macd_trend_up', False))
        weights.append(0.05)
        
        conditions.append(indicators.get('macd_histogram_increasing', False))
        weights.append(0.05)
    
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
    
        # الشروط الأساسية (المتوسطات + RSI)
        conditions.append(indicators['ema5'] < indicators['ema10'])
        weights.append(0.20)
        
        conditions.append(indicators['ema10'] < indicators['ema20'])
        weights.append(0.25)
        
        conditions.append(indicators['rsi'] > 35)
        weights.append(0.10)
        
        conditions.append(indicators['rsi'] < 70)
        weights.append(0.10)
        
        # شروط الماكد
        conditions.append(not indicators['macd_above_signal'])
        weights.append(0.15)
        
        conditions.append(not indicators['macd_histogram_positive'])
        weights.append(0.10)
        
        conditions.append(not indicators.get('macd_trend_up', True))
        weights.append(0.05)
        
        conditions.append(not indicators.get('macd_histogram_increasing', True))
        weights.append(0.05)
    
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

class SimpleOrderManager:
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.pending_orders = {}
        
    def place_stop_orders(self, symbol, direction, quantity, entry_price):
        """وضع أوامر الوقف والجني بشكل منفصل وبسيط"""
        try:
            logger.info(f"🔄 محاولة وضع أوامر الوقف لـ {symbol}...")
            
            # حساب الأسعار
            if direction == 'LONG':
                stop_price = entry_price * (1 - TRADING_SETTINGS['stop_loss_pct'] / 100)
                take_profit_price = entry_price * (1 + TRADING_SETTINGS['target_profit_pct'] / 100)
            else:
                stop_price = entry_price * (1 + TRADING_SETTINGS['stop_loss_pct'] / 100)
                take_profit_price = entry_price * (1 - TRADING_SETTINGS['target_profit_pct'] / 100)
            
            # تقريب الأسعار
            stop_price = round(stop_price, 4)
            take_profit_price = round(take_profit_price, 4)
            
            logger.info(f"📊 أسعار الأوامر لـ {symbol}:")
            logger.info(f"  🎯 الجني: ${take_profit_price:.4f}")
            logger.info(f"  🛡️ الوقف: ${stop_price:.4f}")
            
            # 1️⃣ وضع أمر وقف الخسارة
            sl_order = self.client.futures_create_order(
                symbol=symbol,
                side='SELL' if direction == 'LONG' else 'BUY',
                type='STOP_MARKET',
                quantity=quantity,
                stopPrice=stop_price,
                reduceOnly=True,
                timeInForce='GTC'
            )
            
            time.sleep(0.5)  # انتظار بين الأوامر
            
            # 2️⃣ وضع أمر جني الربح
            tp_order = self.client.futures_create_order(
                symbol=symbol,
                side='SELL' if direction == 'LONG' else 'BUY',
                type='TAKE_PROFIT_MARKET',
                quantity=quantity,
                stopPrice=take_profit_price,
                reduceOnly=True,
                timeInForce='GTC'
            )
            
            # حفظ معلومات الأوامر
            self.pending_orders[symbol] = {
                'stop_loss': sl_order['orderId'],
                'take_profit': tp_order['orderId'],
                'symbol': symbol
            }
            
            logger.info(f"✅ تم وضع أوامر الوقف والجني بنجاح لـ {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل وضع أوامر الوقف لـ {symbol}: {e}")
            return False
    
    def verify_orders_placed(self, symbol):
        """التحقق من أن الأوامر موجودة على المنصة"""
        try:
            open_orders = self.client.futures_get_open_orders(symbol=symbol)
            stop_orders = [o for o in open_orders if o['type'] in ['STOP_MARKET', 'TAKE_PROFIT_MARKET']]
            
            if len(stop_orders) >= 2:
                logger.info(f"✅ تم التحقق من وجود {len(stop_orders)} أمر وقف لـ {symbol}")
                return True
            else:
                logger.warning(f"⚠️ عدد أوامر الوقف غير كافي لـ {symbol}: {len(stop_orders)}/2")
                return False
                
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الأوامر لـ {symbol}: {e}")
            return False
    
    def cancel_all_orders(self, symbol):
        """إلغاء جميع الأوامر لعملة معينة"""
        try:
            # إلغاء الأوامر المخزنة
            if symbol in self.pending_orders:
                del self.pending_orders[symbol]
            
            # إلغاء الأوامر الفعلية من المنصة
            self.client.futures_cancel_all_open_orders(symbol=symbol)
            logger.info(f"🗑️ تم إلغاء جميع الأوامر لـ {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل إلغاء الأوامر لـ {symbol}: {e}")
            return False
    
    def sync_active_trades(self):
        """مزامنة المراكز النشطة مع المنصة"""
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
                        # اكتشاف صفقة جديدة
                        self._handle_new_position(symbol, position)
                else:
                    if symbol in self.active_trades:
                        # اكتشاف إغلاق صفقة
                        self._handle_closed_position(symbol)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في مزامنة المراكز: {e}")
            return False
    
    def _handle_new_position(self, symbol, position):
        """معالجة صفقة جديدة مكتشفة"""
        quantity = abs(float(position['positionAmt']))
        side = "LONG" if float(position['positionAmt']) > 0 else "SHORT"
        entry_price = float(position['entryPrice'])
        
        trade_data = {
            'symbol': symbol,
            'quantity': quantity,
            'entry_price': entry_price,
            'side': side,
            'timestamp': datetime.now(damascus_tz),
            'status': 'open',
            'has_orders': False
        }
        
        self.active_trades[symbol] = trade_data
        logger.info(f"🔄 اكتشاف صفقة جديدة: {symbol} {side}")
        
        # وضع أوامر الوقف فوراً
        self.place_stop_orders(symbol, side, quantity, entry_price)
    
    def _handle_closed_position(self, symbol):
        """معالجة صفقة مغلقة مكتشفة"""
        if symbol in self.active_trades:
            # تنظيف الأوامر أولاً
            self.cancel_all_orders(symbol)
            
            # ثم حذف الصفقة
            del self.active_trades[symbol]
            logger.info(f"🔄 اكتشاف إغلاق صفقة: {symbol}")
    
    def add_trade(self, symbol, trade_data):
        """إضافة صفقة جديدة"""
        self.active_trades[symbol] = trade_data
    
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
        return len(self.active_trades)
    
    def is_symbol_trading(self, symbol):
        """التحقق إذا كانت العملة متداولة"""
        return symbol in self.active_trades
    
    def get_symbol_trades_count(self, symbol):
        """عدد الصفقات على عملة معينة"""
        count = 0
        for trade_symbol in self.active_trades:
            if trade_symbol == symbol:
                count += 1
        return count
    
    def get_symbol_trades_direction(self, symbol):
        """اتجاهات الصفقات على عملة معينة"""
        directions = []
        for trade_symbol, trade in self.active_trades.items():
            if trade_symbol == symbol:
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
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.order_manager = SimpleOrderManager(self.client, self.notifier)
        
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
        
        self.order_manager.sync_active_trades()
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت السكالبينج بنجاح مع نظام الأوامر المبسط")

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

    def start_services(self):
        def sync_thread():
            while True:
                try:
                    # المزامنة المنتظمة
                    self.order_manager.sync_active_trades()
                    self.update_real_time_balance()
                    self.check_expired_trades()
                    time.sleep(30)  # مزامنة كل 30 ثانية
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(60)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        if self.notifier:
            schedule.every(6).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)
            schedule.every(1).hours.do(self.send_heartbeat)

    def update_real_time_balance(self):
        try:
            self.real_time_balance = self.get_real_time_balance()
            return True
        except Exception as e:
            logger.error(f"❌ فشل تحديث الرصيد: {e}")
            return False

    def check_expired_trades(self):
        """التحقق من الصفقات التي انتهت مدتها الزمنية"""
        try:
            active_trades = self.order_manager.get_all_trades()
            current_time = datetime.now(damascus_tz)
            
            for symbol, trade in active_trades.items():
                trade_duration = (current_time - trade['timestamp']).total_seconds() / 60
                if trade_duration >= self.TRADING_SETTINGS['max_trade_duration_minutes']:
                    self.force_close_trade(symbol, f"انتهت المدة الزمنية ({trade_duration:.1f} دقيقة)")
                    
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الصفقات المنتهية: {e}")

    def send_startup_message(self):
        if self.notifier:
            balance = self.real_time_balance
            message = (
                "⚡ <b>بدء تشغيل بوت السكالبينج المحسّن</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد\n"
                f"العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"🎯 جني الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"🛡️ وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"⏰ مدة الصفقة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                f"المسح كل: {self.TRADING_SETTINGS['rescan_interval_minutes']} دقائق\n"
                f"الحد الأقصى للصفقات: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"الحد الأقصى للصفقات لكل عملة: {self.TRADING_SETTINGS['max_trades_per_symbol']}\n"
                f"🔄 نظام الأوامر المبسط: نشط ✅\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.notifier.send_message(message)

    def send_performance_report(self):
        if not self.notifier:
            return
        
        active_trades = self.order_manager.get_active_trades_count()
        win_rate = 0
        if self.performance_stats['trades_closed'] > 0:
            win_rate = (self.performance_stats['winning_trades'] / self.performance_stats['trades_closed']) * 100
        
        message = (
            f"📊 <b>تقرير أداء السكالبينج</b>\n"
            f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد\n"
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
            active_trades = self.order_manager.get_active_trades_count()
            
            message = (
                f"💰 <b>تقرير الرصيد الحقيقي</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد\n"
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
            active_trades = self.order_manager.get_active_trades_count()
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
        
        if self.order_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات النشطة")
        
        can_open_symbol, symbol_reason = self.order_manager.can_open_trade_on_symbol(symbol, direction)
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
            quantity = self.adjust_quantity(symbol, quantity)
            
            if quantity and quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol}: {quantity:.6f} (رصيد مستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}, رافعة: {self.TRADING_SETTINGS['max_leverage']}x)")
                return quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return None

    def adjust_quantity(self, symbol, quantity):
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
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة: {e}")
            return False

    def execute_trade(self, signal):
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            
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
            
            # تنفيذ أمر السوق الرئيسي
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
                
                # وضع أوامر الوقف والجني بعد تنفيذ الصفقة
                time.sleep(1)  # انتظار بسيط قبل وضع الأوامر
                
                orders_success = self.order_manager.place_stop_orders(symbol, direction, quantity, executed_price)
                
                # التحقق من وضع الأوامر
                if orders_success:
                    time.sleep(2)
                    orders_verified = self.order_manager.verify_orders_placed(symbol)
                    if not orders_verified:
                        logger.warning(f"⚠️ الأوامر غير مؤكدة لـ {symbol}، إعادة المحاولة...")
                        self.order_manager.place_stop_orders(symbol, direction, quantity, executed_price)
                
                nominal_value = quantity * executed_price
                expected_profit = nominal_value * (self.TRADING_SETTINGS['target_profit_pct'] / 100)
                
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
                    'max_duration': self.TRADING_SETTINGS['max_trade_duration_minutes'],
                    'has_orders': orders_success
                }
                
                self.order_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                
                if self.notifier:
                    symbol_trades_count = self.order_manager.get_symbol_trades_count(symbol)
                    
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة سكالبينج</b>\n"
                        f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد\n"
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
                        f"📈 الصفقات النشطة على {symbol}: {symbol_trades_count}/{self.TRADING_SETTINGS['max_trades_per_symbol']}\n"
                        f"✅ أوامر الوقف: {'نعم' if orders_success else 'لا'}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة سكالبينج {direction} لـ {symbol} مع أوامر الوقف والجني")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            return False

    def force_close_trade(self, symbol, reason="إغلاق إجباري"):
        """إغلاق الصفقة قسراً عند انتهاء المدة"""
        try:
            trade = self.order_manager.get_trade(symbol)
            if not trade:
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False
            
            # 1️⃣ إلغاء جميع الأوامر أولاً
            self.order_manager.cancel_all_orders(symbol)
            
            # 2️⃣ إغلاق المركز
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
                else:
                    self.performance_stats['losing_trades'] += 1
                    self.performance_stats['consecutive_losses'] += 1
                
                self.performance_stats['total_pnl'] += pnl_pct
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة سكالبينج</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"السبب: {reason}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                self.order_manager.remove_trade(symbol)
                logger.info(f"✅ تم إغلاق صفقة {symbol} - الربح/الخسارة: {pnl_pct:+.2f}%")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {symbol}: {e}")
            return False

    def scan_market(self):
        logger.info("🔍 بدء مسح السوق للسكالبينج...")
        
        opportunities = []
        
        for symbol in self.TRADING_SETTINGS['symbols']:
            try:
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
            
            # 1️⃣ المزامنة أولاً
            self.order_manager.sync_active_trades()
            
            # 2️⃣ البحث عن إشارات
            opportunities = self.scan_market()
            
            # 3️⃣ تنفيذ صفقة واحدة فقط في كل دورة
            executed_trades = 0
            for signal in opportunities:
                if self.order_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
                    break
                    
                if self.execute_trade(signal):
                    executed_trades += 1
                    break  # صفقة واحدة فقط لكل دورة
            
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
        trades = self.order_manager.get_all_trades()
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
                'max_duration': trade.get('max_duration', 15),
                'has_orders': trade.get('has_orders', False)
            }
            for trade in trades.values()
        ]

    def get_market_analysis(self, symbol):
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

    def run(self):
        logger.info("🚀 بدء تشغيل بوت السكالبينج مع نظام الأوامر المبسط...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت السكالبينج المحسّن</b>\n"
                f"الاستراتيجية: تقاطع المتوسطات + RSI + الماكد\n"
                f"العملات: {', '.join(self.TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${self.TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"🎯 جني الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"🛡️ وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"⏰ مدة الصفقة: {self.TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
                f"الحد الأقصى للصفقات: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"الحد الأقصى للصفقات لكل عملة: {self.TRADING_SETTINGS['max_trades_per_symbol']}\n"
                f"🔄 نظام الأوامر المبسط: نشط ✅\n"
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

def main():
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
