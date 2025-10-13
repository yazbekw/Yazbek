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
    'symbols': ["BNBUSDT","ETHUSDT"],
    'used_balance_per_trade': 6,
    'max_leverage': 8,
    'max_active_trades': 2,
    'data_interval': '5m',
    'rescan_interval_minutes': 1,
    'target_profit_pct': 0.20,
    'stop_loss_pct': 0.08,
    'max_trade_duration_minutes': 10,
    'max_daily_trades': 30,
    'cooldown_after_loss': 3,
    'max_trades_per_symbol': 1,
}

# ضبط التوقيت
damascus_tz = pytz.timezone('Asia/Damascus')
os.environ['TZ'] = 'Asia/Damascus'

# تطبيق Flask للرصد
app = Flask(__name__)

@app.route('/')
def health_check():
    return {'status': 'healthy', 'service': 'ema-rsi-bot', 'timestamp': datetime.now(damascus_tz).isoformat()}

@app.route('/active_trades')
def active_trades():
    try:
        bot = EMARSITradingBot.get_instance()
        if bot:
            return jsonify(bot.get_active_trades_details())
        return jsonify([])
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
        logging.FileHandler('ema_rsi_bot.log', encoding='utf-8'),
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

class EMAStrategySignalGenerator:
    """مولد إشارات استراتيجية EMA 9/21 + RSI"""
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارة تداول"""
        try:
            if len(data) < 25:
                return None
            
            indicators = self._calculate_indicators(data)
            return self._analyze_signal(indicators, symbol, current_price)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد إشارة لـ {symbol}: {e}")
            return None
    
    def _calculate_indicators(self, data):
        """حساب المؤشرات"""
        df = data.copy()
        
        # حساب EMA 9 و EMA 21
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        
        # حساب RSI 14
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        return {
            'ema9': latest['ema9'],
            'ema21': latest['ema21'],
            'ema9_prev': prev['ema9'],
            'ema21_prev': prev['ema21'],
            'rsi': latest['rsi'],
            'current_close': latest['close'],
            'current_open': latest['open'],
            'prev_close': prev['close'],
        }
    
    def _calculate_rsi(self, prices, period):
        """حساب مؤشر RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        
        rs = avg_gain / (avg_loss + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1] if not rsi.empty else 50
    
    def _analyze_signal(self, indicators, symbol, current_price):
        """تحليل الإشارة"""
        # اكتشاف التقاطعات
        ema9_cross_above_21 = (indicators['ema9'] > indicators['ema21'] and 
                              indicators['ema9_prev'] <= indicators['ema21_prev'])
        ema9_cross_below_21 = (indicators['ema9'] < indicators['ema21'] and 
                              indicators['ema9_prev'] >= indicators['ema21_prev'])
        
        # تحليل الشمعة
        is_bullish_candle = indicators['current_close'] > indicators['current_open']
        is_bearish_candle = indicators['current_close'] < indicators['current_open']
        
        # إشارة شراء - يجب أن تتحقق جميع الشروط
        if ema9_cross_above_21 and indicators['rsi'] > 50 and is_bullish_candle:
            return {
                'symbol': symbol,
                'direction': 'LONG',
                'confidence': 0.85,
                'reason': 'EMA 9 تقاطع فوق EMA 21 مع RSI > 50 وشمعة صاعدة',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price
            }
        
        # إشارة بيع - يجب أن تتحقق جميع الشروط
        if ema9_cross_below_21 and indicators['rsi'] < 50 and is_bearish_candle:
            return {
                'symbol': symbol,
                'direction': 'SHORT',
                'confidence': 0.85,
                'reason': 'EMA 9 تقاطع تحت EMA 21 مع RSI < 50 وشمعة هابطة',
                'indicators': indicators,
                'timestamp': datetime.now(damascus_tz),
                'current_price': current_price
            }
        
        return None

class SimpleTradeManager:
    """مدير الصفقات"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.precision_manager = PrecisionManager(client)
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
                        return True
            return False
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الإشارات المعاكسة: {e}")
            return False
    
    def start_trade_monitoring(self):
        """بدء مراقبة الصفقات"""
        def monitor():
            while self.monitoring_active:
                try:
                    self._check_limits_and_duration()
                    self._cleanup_closed_trades()
                    time.sleep(10)
                except Exception as e:
                    logger.error(f"❌ خطأ في المراقبة: {e}")
                    time.sleep(30)
        
        threading.Thread(target=monitor, daemon=True).start()
        logger.info("✅ بدء مراقبة الصفقات النشطة")
    
    def _check_limits_and_duration(self):
        """التحقق من الحدود والمدة"""
        current_time = datetime.now(damascus_tz)
        
        for symbol, trade in list(self.active_trades.items()):
            if trade['status'] != 'open':
                continue
            
            current_price = self._get_current_price(symbol)
            if not current_price:
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
                    message = (
                        f"🔒 <b>إغلاق صفقة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"سعر الدخول: ${entry_price:.4f}\n"
                        f"سعر الخروج: ${current_price:.4f}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
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
            take_profit, stop_loss = self.calculate_trade_limits(
                symbol, trade_data['side'], trade_data['entry_price']
            )
            
            trade_data.update({
                'take_profit_price': take_profit,
                'stop_loss_price': stop_loss,
                'status': 'open',
                'timestamp': datetime.now(damascus_tz)
            })
            
            self.active_trades[symbol] = trade_data
            
            logger.info(f"✅ تمت إضافة صفقة {symbol}")
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
    
    def send_signal_alert(self, symbol, signal, current_price):
        """إرسال إشعار إشارة"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        
        message = (
            f"{direction_emoji} <b>إشارة تداول جديدة - استراتيجية EMA+RSI</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"السعر: ${current_price:.4f}\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"السبب: {signal['reason']}\n"
            f"📊 المؤشرات:\n"
            f"• EMA 9: {signal['indicators']['ema9']:.4f}\n"
            f"• EMA 21: {signal['indicators']['ema21']:.4f}\n"
            f"• RSI: {signal['indicators']['rsi']:.1f}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message)

class EMARSITradingBot:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self):
        if EMARSITradingBot._instance is not None:
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

        self.signal_generator = EMAStrategySignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = SimpleTradeManager(self.client, self.notifier)
        
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'daily_trades_count': 0,
        }
        
        self.start_services()
        self.send_startup_message()
        
        EMARSITradingBot._instance = self
        logger.info("✅ تم تهيئة بوت EMA+RSI بنجاح")

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
            message = (
                "🚀 <b>بدء تشغيل بوت EMA+RSI</b>\n"
                f"الاستراتيجية: EMA 9/21 + RSI 14\n"
                f"العملات: {', '.join(TRADING_SETTINGS['symbols'])}\n"
                f"الرصيد المستخدم: ${TRADING_SETTINGS['used_balance_per_trade']}\n"
                f"الرافعة: {TRADING_SETTINGS['max_leverage']}x\n"
                f"🎯 جني الربح: {TRADING_SETTINGS['target_profit_pct']}%\n"
                f"🛡️ وقف الخسارة: {TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"⏰ مدة الصفقة: {TRADING_SETTINGS['max_trade_duration_minutes']} دقيقة\n"
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
        balance = self.get_real_time_balance()
        
        message = (
            f"📊 <b>التقرير اليومي - بوت EMA+RSI</b>\n"
            f"📅 التاريخ: {datetime.now(damascus_tz).strftime('%Y-%m-%d')}\n"
            f"⏰ الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}\n"
            f"═══════════════════\n"
            f"📈 <b>أداء اليوم:</b>\n"
            f"• عدد الصفقات: {daily_trades}\n"
            f"• الصفقات النشطة: {active_trades}\n"
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
        message = (
            f"📈 <b>تقرير أداء البوت</b>\n"
            f"الصفقات النشطة: {active_trades}\n"
            f"الصفقات المفتوحة: {self.performance_stats['trades_opened']}\n"
            f"الصفقات المغلقة: {self.performance_stats['trades_closed']}\n"
            f"الصفقات اليوم: {self.performance_stats['daily_trades_count']}\n"
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

    def can_open_trade(self, symbol, direction):
        """التحقق من إمكانية فتح صفقة"""
        reasons = []
        
        if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات النشطة")
        
        if self.performance_stats['daily_trades_count'] >= TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
        
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
        """تنفيذ الصفقة مع التحقق من الإشارات المعاكسة"""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            
            # التحقق أولاً من وجود صفقة معاكسة وإغلاقها
            trade_closed = self.trade_manager.check_and_handle_opposite_signals(symbol, direction)
            
            if trade_closed:
                logger.info(f"⏳ انتظار قليل بعد إغلاق الصفقة المعاكسة لـ {symbol}")
                time.sleep(2)  # انتظار بسيط للتأكد من الإغلاق
            
            # ثم التحقق من إمكانية فتح الصفقة الجديدة
            can_trade, reasons = self.can_open_trade(symbol, direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي {symbol} {direction}: {', '.join(reasons)}")
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
            
            logger.info(f"⚡ تنفيذ صفقة {symbol}: {direction} | الكمية: {quantity:.6f}")
            
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
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                
                # إرسال إشعار
                if self.notifier:
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"الرافعة: {TRADING_SETTINGS['max_leverage']}x\n"
                        f"🎯 جني الربح: {TRADING_SETTINGS['target_profit_pct']}%\n"
                        f"🛡️ وقف الخسارة: {TRADING_SETTINGS['stop_loss_pct']}%\n"
                        f"السبب: {signal['reason']}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            return False

    def scan_market(self):
        """مسح السوق للبحث عن إشارات"""
        logger.info("🔍 بدء مسح السوق...")
        
        opportunities = []
        
        for symbol in TRADING_SETTINGS['symbols']:
            try:
                data = self.get_historical_data(symbol, TRADING_SETTINGS['data_interval'])
                if data is None:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                signal = self.signal_generator.generate_signal(symbol, data, current_price)
                if signal:
                    opportunities.append(signal)
                    
                    if self.notifier:
                        self.notifier.send_signal_alert(symbol, signal, current_price)
                
            except Exception as e:
                logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
                continue
        
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة")
        return opportunities

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول"""
        try:
            opportunities = self.scan_market()
            
            executed_trades = 0
            for signal in opportunities:
                if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
                    break
                    
                if self.execute_trade(signal):
                    executed_trades += 1
                    break  # تنفيذ صفقة واحدة فقط في كل دورة
            
            wait_time = TRADING_SETTINGS['rescan_interval_minutes'] * 60
            logger.info(f"⏳ انتظار {wait_time} ثانية للدورة القادمة...")
            time.sleep(wait_time)
            
        except Exception as e:
            logger.error(f"❌ خطأ في دورة التداول: {e}")
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
                }
                
                if current_price:
                    if trade['side'] == 'LONG':
                        pnl_pct = (current_price - trade['entry_price']) / trade['entry_price'] * 100
                    else:
                        pnl_pct = (trade['entry_price'] - current_price) / trade['entry_price'] * 100
                    trade_info['current_pnl_pct'] = pnl_pct
                
                active_trades.append(trade_info)
        
        return active_trades

    def run(self):
        """بدء تشغيل البوت"""
        logger.info("🚀 بدء تشغيل بوت EMA+RSI...")
        
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
            logger.info("🛑 إيقاف البوت...")
            self.trade_manager.stop_monitoring()

def main():
    try:
        bot = EMARSITradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
