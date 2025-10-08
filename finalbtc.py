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
    return {'status': 'healthy', 'service': 'btc-breakout-bot', 'timestamp': datetime.now(damascus_tz).isoformat()}

@app.route('/active_trades')
def active_trades():
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            return jsonify(bot.get_active_trades_details())
        return jsonify([])
    except Exception as e:
        return {'error': str(e)}

@app.route('/market_analysis')
def market_analysis():
    try:
        bot = ScalpingTradingBot.get_instance()
        if bot:
            analysis = bot.get_market_analysis()
            return jsonify(analysis)
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
        logging.FileHandler('btc_breakout_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BreakoutSignalGenerator:
    """مولد إشارات الاختراق المبسط"""
    
    def __init__(self):
        self.min_confidence = 0.75
        self.breakout_buffer = 0.001  # 0.1%
    
    def generate_signal(self, data, current_price):
        """توليد إشارة اختراق مبسطة"""
        try:
            if len(data) < 50:
                return None
            
            # تحديد مستويات الدعم والمقاومة
            support, resistance = self._calculate_support_resistance(data)
            if support is None or resistance is None:
                return None
            
            # تحليل الاختراق
            breakout_analysis = self._analyze_breakout(data, current_price, support, resistance)
            
            if breakout_analysis['signal']:
                signal_info = {
                    'symbol': 'BTCUSDT',
                    'direction': breakout_analysis['direction'],
                    'confidence': breakout_analysis['confidence'],
                    'conditions_met': breakout_analysis['conditions_met'],
                    'total_conditions': breakout_analysis['total_conditions'],
                    'support': support,
                    'resistance': resistance,
                    'range_width_pct': (resistance - support) / support * 100,
                    'current_price': current_price,
                    'timestamp': datetime.now(damascus_tz),
                    'strategy': 'BREAKOUT'
                }
                
                logger.info(f"🎯 إشارة اختراق BTC: {breakout_analysis['direction']} "
                           f"(ثقة: {breakout_analysis['confidence']:.2%})")
                
                return signal_info
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد إشارة الاختراق: {e}")
            return None
    
    def _calculate_support_resistance(self, data):
        """حساب مستويات الدعم والمقاومة المبسط"""
        try:
            # استخدام آخر 24 ساعة للتحليل
            recent_data = data.tail(24)
            
            resistance = np.max(recent_data['high'].values)
            support = np.min(recent_data['low'].values)
            
            # التأكد من وجود نطاق واضح
            if resistance <= support * 1.005:  # نطاق صغير جداً
                return None, None
            
            return support, resistance
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب الدعم والمقاومة: {e}")
            return None, None
    
    def _analyze_breakout(self, data, current_price, support, resistance):
        """تحليل إشارات الاختراق المبسط"""
        try:
            conditions_met = 0
            total_conditions = 3
            
            # 1. اختراق مستوى المقاومة أو الدعم
            resistance_break = current_price > resistance * (1 + self.breakout_buffer)
            support_break = current_price < support * (1 - self.breakout_buffer)
            
            if not (resistance_break or support_break):
                return {'signal': False, 'confidence': 0}
            
            direction = 'LONG' if resistance_break else 'SHORT'
            conditions_met += 1
            
            # 2. زيادة الحجم عند الاختراق
            volume_condition = self._check_volume(data)
            if volume_condition:
                conditions_met += 1
            
            # 3. تأكيد الاختراق بشمعتين متتاليتين
            confirmation_condition = self._check_confirmation(data, direction, support, resistance)
            if confirmation_condition:
                conditions_met += 1
            
            confidence = conditions_met / total_conditions
            
            return {
                'signal': conditions_met >= 2,  # 2 من أصل 3 شروط
                'direction': direction,
                'confidence': confidence,
                'conditions_met': conditions_met,
                'total_conditions': total_conditions
            }
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل الاختراق: {e}")
            return {'signal': False, 'confidence': 0}
    
    def _check_volume(self, data):
        """التحقق من زيادة الحجم"""
        try:
            if len(data) < 10:
                return False
            
            current_volume = data['volume'].iloc[-1]
            avg_volume = data['volume'].tail(10).mean()
            
            return current_volume > avg_volume * 1.2  # زيادة 20% في الحجم
            
        except Exception as e:
            return False
    
    def _check_confirmation(self, data, direction, support, resistance):
        """تأكيد الاختراق بشمعتين متتاليتين"""
        try:
            if len(data) < 3:
                return False
            
            # التحقق من آخر شمعتين
            if direction == 'LONG':
                # تأكيد الصعود: الشمعتين تغلقان فوق المقاومة
                return (data['close'].iloc[-1] > resistance and 
                        data['close'].iloc[-2] > resistance)
            else:
                # تأكيد الهبوط: الشمعتين تغلقان تحت الدعم
                return (data['close'].iloc[-1] < support and 
                        data['close'].iloc[-2] < support)
                
        except Exception as e:
            return False

class TradeManager:
    """مدير الصفقات المبسط"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.symbol_cooldown = {}
    
    def sync_with_exchange(self):
        """مزامنة الصفقات مع المنصة"""
        try:
            account_info = self.client.futures_account()
            positions = account_info['positions']
            
            for position in positions:
                symbol = position['symbol']
                quantity = float(position['positionAmt'])
                
                if quantity != 0 and symbol == 'BTCUSDT':
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
                elif symbol == 'BTCUSDT' and symbol in self.active_trades:
                    closed_trade = self.active_trades[symbol]
                    closed_trade['status'] = 'closed'
                    del self.active_trades[symbol]
            
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في مزامنة الصفقات: {e}")
            return False
    
    def can_trade_symbol(self, symbol):
        """التحقق من إمكانية التداول على الرمز"""
        if symbol in self.symbol_cooldown:
            cooldown_end = self.symbol_cooldown[symbol]
            if datetime.now(damascus_tz) < cooldown_end:
                remaining = (cooldown_end - datetime.now(damascus_tz)).total_seconds() / 60
                logger.info(f"⏳ تبريد لـ {symbol}: {remaining:.1f} دقائق متبقية")
                return False
        
        return True
    
    def add_symbol_cooldown(self, symbol, minutes=15):
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
    
    def add_trade(self, trade_data):
        self.active_trades['BTCUSDT'] = trade_data
    
    def remove_trade(self):
        if 'BTCUSDT' in self.active_trades:
            del self.active_trades['BTCUSDT']
    
    def get_trade(self):
        return self.active_trades.get('BTCUSDT')
    
    def get_all_trades(self):
        return self.active_trades.copy()

class TelegramNotifier:
    """مدير إشعارات التلغرام المبسط"""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, message):
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

class ScalpingTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbol': "BTCUSDT",  # BTC فقط
        'used_balance_per_trade': 5,
        'max_leverage': 5,
        'nominal_trade_size': 25,
        'max_active_trades': 1,  # صفقة واحدة فقط
        'data_interval': '15m',
        'rescan_interval_minutes': 5,
        'min_signal_confidence': 0.75,
        'target_profit_pct': 0.50,  # 0.5% لـ BTC
        'stop_loss_pct': 0.30,     # 0.3% لـ BTC
        'max_daily_trades': 10,
        'cooldown_after_loss': 20,
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

        # تهيئة المكونات المبسطة
        self.signal_generator = BreakoutSignalGenerator()
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        
        # إحصائيات الأداء المبسطة
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'daily_trades_count': 0,
            'last_trade_time': None,
            'consecutive_losses': 0,
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        ScalpingTradingBot._instance = self
        logger.info("✅ تم تهيئة بوت BTC الاختراق بنجاح")

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
        """جلب الرصيد الحقيقي"""
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
            logger.error(f"❌ فشل جلب الرصيد: {e}")
            return {
                'total_balance': 100.0,
                'available_balance': 100.0,
                'timestamp': datetime.now(damascus_tz)
            }

    def can_open_trade(self, direction):
        """التحقق من إمكانية فتح صفقة"""
        reasons = []
        
        # التحقق من وجود صفقة نشطة
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("يوجد صفقة نشطة بالفعل")
        
        # التحقق من الرصيد المتاح
        available_balance = self.real_time_balance['available_balance']
        if available_balance < self.TRADING_SETTINGS['used_balance_per_trade']:
            reasons.append("رصيد غير كافي")
        
        # التحقق من الحد اليومي
        if self.performance_stats['daily_trades_count'] >= self.TRADING_SETTINGS['max_daily_trades']:
            reasons.append("الحد اليومي للصفقات")
        
        # التحقق من نظام التبريد
        if not self.trade_manager.can_trade_symbol('BTCUSDT'):
            reasons.append("فترة تبريد نشطة")
        
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
                    time.sleep(30)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(60)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        if self.notifier:
            schedule.every(6).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)

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
                self.check_trade_exit(trade)
        except Exception as e:
            logger.error(f"❌ خطأ في إدارة الصفقات: {e}")

    def check_trade_exit(self, trade):
        """التحقق من خروج الصفقة"""
        try:
            current_price = self.get_current_price()
            if not current_price:
                return
            
            entry_price = trade['entry_price']
            
            if trade['side'] == 'LONG':
                pnl_pct = (current_price - entry_price) / entry_price * 100
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                if pnl_pct <= -self.TRADING_SETTINGS['stop_loss_pct']:
                    self.close_trade(f"وقف الخسارة {pnl_pct:.2f}%")
                    return
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100
                if pnl_pct >= self.TRADING_SETTINGS['target_profit_pct']:
                    self.close_trade(f"تحقيق هدف الربح {pnl_pct:.2f}%")
                    return
                if pnl_pct <= -self.TRADING_SETTINGS['stop_loss_pct']:
                    self.close_trade(f"وقف الخسارة {pnl_pct:.2f}%")
                    return
                    
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من خروج الصفقة: {e}")

    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            balance = self.real_time_balance
            
            message = (
                "⚡ <b>بدء تشغيل بوت BTC الاختراق</b>\n"
                f"<b>الاستراتيجية:</b> اختراق النطاق\n"
                f"<b>المؤشرات:</b> مستويات الدعم/المقاومة + الحجم\n"
                f"<b>الإعدادات:</b>\n"
                f"• وقف الخسارة: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                f"• هدف الربح: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                f"• الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                f"• القيمة الاسمية: ${self.TRADING_SETTINGS['nominal_trade_size']}\n"
                f"• صفقات نشطة: {self.TRADING_SETTINGS['max_active_trades']}\n"
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
        
        risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
        
        message = (
            f"📊 <b>تقرير أداء بوت BTC</b>\n"
            f"الاستراتيجية: اختراق النطاق\n"
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
        """إرسال تقرير الرصيد"""
        if not self.notifier:
            return
        
        try:
            self.update_real_time_balance()
            balance = self.real_time_balance
            active_trades = self.trade_manager.get_active_trades_count()
            
            message = (
                f"💰 <b>تقرير الرصيد</b>\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الرصيد المتاح: ${balance['available_balance']:.2f}\n"
                f"الصفقات النشطة: {active_trades}\n"
                f"آخر تحديث: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            
            self.notifier.send_message(message)
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تقرير الرصيد: {e}")

    def get_historical_data(self, interval, limit=100):
        """جلب البيانات التاريخية"""
        time.sleep(0.1)
        try:
            klines = self.client.futures_klines(
                symbol=self.TRADING_SETTINGS['symbol'],
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
            logger.error(f"❌ خطأ في جلب البيانات: {e}")
            return None

    def get_current_price(self):
        """الحصول على السعر الحالي"""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=self.TRADING_SETTINGS['symbol'])
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر BTC: {e}")
            return None

    def calculate_position_size(self, current_price):
        """حساب حجم المركز"""
        try:
            nominal_size = self.TRADING_SETTINGS['used_balance_per_trade'] * self.TRADING_SETTINGS['max_leverage']
            quantity = nominal_size / current_price
            
            # ضبط الكمية حسب متطلبات المنصة
            exchange_info = self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == self.TRADING_SETTINGS['symbol']), None)
            
            if symbol_info:
                lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                if lot_size_filter:
                    step_size = float(lot_size_filter['stepSize'])
                    quantity = float(int(quantity / step_size) * step_size)
            
            if quantity > 0:
                logger.info(f"💰 حجم الصفقة: {quantity:.6f}")
                return quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز: {e}")
            return None

    def set_leverage(self):
        """تعيين الرافعة المالية"""
        try:
            self.client.futures_change_leverage(
                symbol=self.TRADING_SETTINGS['symbol'], 
                leverage=self.TRADING_SETTINGS['max_leverage']
            )
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة: {e}")
            return False

    def execute_trade(self, signal):
        """تنفيذ صفقة الاختراق"""
        try:
            direction = signal['direction']
            
            # التحقق من إمكانية التداول
            can_trade, reasons = self.can_open_trade(direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي BTC {direction}: {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price()
            if not current_price:
                logger.error(f"❌ لا يمكن الحصول على سعر BTC")
                return False
            
            # حساب حجم المركز
            quantity = self.calculate_position_size(current_price)
            if not quantity:
                logger.warning(f"⚠️ لا يمكن حساب حجم آمن")
                return False
            
            # تعيين الرافعة
            self.set_leverage()
            
            # تنفيذ الأمر
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"⚡ تنفيذ صفقة BTC: {direction} | الكمية: {quantity:.6f}")
            
            order = self.client.futures_create_order(
                symbol=self.TRADING_SETTINGS['symbol'],
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order['orderId']:
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(
                        symbol=self.TRADING_SETTINGS['symbol'], 
                        orderId=order['orderId']
                    )
                    if order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                except:
                    pass
                
                nominal_value = quantity * executed_price
                expected_profit = nominal_value * (self.TRADING_SETTINGS['target_profit_pct'] / 100)
                
                # تسجيل الصفقة
                trade_data = {
                    'symbol': self.TRADING_SETTINGS['symbol'],
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': self.TRADING_SETTINGS['max_leverage'],
                    'timestamp': datetime.now(damascus_tz),
                    'status': 'open',
                    'signal_confidence': signal['confidence'],
                    'nominal_value': nominal_value,
                    'expected_profit': expected_profit,
                    'strategy': 'BREAKOUT',
                    'support': signal['support'],
                    'resistance': signal['resistance']
                }
                
                self.trade_manager.add_trade(trade_data)
                self.performance_stats['trades_opened'] += 1
                self.performance_stats['daily_trades_count'] += 1
                self.performance_stats['last_trade_time'] = datetime.now(damascus_tz)
                
                # إرسال إشعار
                if self.notifier:
                    risk_reward_ratio = self.TRADING_SETTINGS['target_profit_pct'] / self.TRADING_SETTINGS['stop_loss_pct']
                    
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>فتح صفقة BTC</b>\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.2f}\n"
                        f"القيمة الاسمية: ${nominal_value:.2f}\n"
                        f"الرافعة: {self.TRADING_SETTINGS['max_leverage']}x\n"
                        f"🎯 الهدف: {self.TRADING_SETTINGS['target_profit_pct']}%\n"
                        f"🛡️ الوقف: {self.TRADING_SETTINGS['stop_loss_pct']}%\n"
                        f"⚖️ النسبة: {risk_reward_ratio:.2f}:1\n"
                        f"💰 الربح المتوقع: ${expected_profit:.4f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"الشروط: {signal['conditions_met']}/{signal['total_conditions']}\n"
                        f"الدعم: ${signal['support']:.2f}\n"
                        f"المقاومة: ${signal['resistance']:.2f}\n"
                        f"الاستراتيجية: اختراق النطاق\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ BTC")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة BTC: {e}")
            return False

    def close_trade(self, reason="إغلاق طبيعي"):
        """إغلاق الصفقة"""
        try:
            trade = self.trade_manager.get_trade()
            if not trade:
                return False
            
            current_price = self.get_current_price()
            if not current_price:
                return False
            
            close_side = 'SELL' if trade['side'] == 'LONG' else 'BUY'
            quantity = trade['quantity']
            
            order = self.client.futures_create_order(
                symbol=self.TRADING_SETTINGS['symbol'],
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
                    
                    # إضافة تبديد بعد خسائر متتالية
                    if self.performance_stats['consecutive_losses'] >= 2:
                        self.trade_manager.add_symbol_cooldown('BTCUSDT', self.TRADING_SETTINGS['cooldown_after_loss'])
                
                self.performance_stats['total_pnl'] += pnl_pct
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة BTC</b>\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"السبب: {reason}\n"
                        f"الاستراتيجية: {trade.get('strategy', 'BREAKOUT')}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                self.trade_manager.remove_trade()
                logger.info(f"✅ تم إغلاق صفقة BTC - الربح/الخسارة: {pnl_pct:+.2f}%")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة BTC: {e}")
            return False

    def scan_market(self):
        """مسح السوق للعثور على فرص الاختراق"""
        logger.info("🔍 بدء مسح السوق لـ BTC...")
        
        try:
            data = self.get_historical_data(self.TRADING_SETTINGS['data_interval'])
            if data is None or len(data) < 50:
                return None
            
            current_price = self.get_current_price()
            if not current_price:
                return None
            
            signal = self.signal_generator.generate_signal(data, current_price)
            if signal:
                logger.info(f"🎯 تم العثور على إشارة BTC: {signal['direction']} (ثقة: {signal['confidence']:.2%})")
                return signal
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل BTC: {e}")
            return None

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول"""
        try:
            start_time = time.time()
            signal = self.scan_market()
            
            if signal and self.execute_trade(signal):
                logger.info("✅ تم تنفيذ صفقة BTC بنجاح")
            
            elapsed_time = time.time() - start_time
            wait_time = (self.TRADING_SETTINGS['rescan_interval_minutes'] * 60) - elapsed_time
            
            if wait_time > 0:
                logger.info(f"⏳ انتظار {wait_time:.1f} ثانية للدورة القادمة")
                time.sleep(wait_time)
            else:
                logger.info("⚡ بدء الدورة التالية فوراً")
            
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
                'strategy': trade.get('strategy', 'BREAKOUT'),
                'support': trade.get('support', 0),
                'resistance': trade.get('resistance', 0)
            }
            for trade in trades.values()
        ]

    def get_market_analysis(self):
        """الحصول على تحليل السوق"""
        try:
            data = self.get_historical_data(self.TRADING_SETTINGS['data_interval'])
            if data is None:
                return {'error': 'لا توجد بيانات'}
            
            current_price = self.get_current_price()
            if not current_price:
                return {'error': 'لا يمكن الحصول على السعر'}
            
            signal = self.signal_generator.generate_signal(data, current_price)
            
            return {
                'symbol': 'BTCUSDT',
                'current_price': current_price,
                'signal': signal,
                'timestamp': datetime.now(damascus_tz).isoformat()
            }
            
        except Exception as e:
            return {'error': str(e)}

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
                'consecutive_losses': self.performance_stats['consecutive_losses']
            },
            'risk_management': {
                'target_profit_pct': self.TRADING_SETTINGS['target_profit_pct'],
                'stop_loss_pct': self.TRADING_SETTINGS['stop_loss_pct'],
                'risk_reward_ratio': round(risk_reward_ratio, 2),
                'used_balance_per_trade': self.TRADING_SETTINGS['used_balance_per_trade'],
                'max_leverage': self.TRADING_SETTINGS['max_leverage'],
                'nominal_trade_size': self.TRADING_SETTINGS['nominal_trade_size']
            },
            'strategy': 'BREAKOUT',
            'symbol': 'BTCUSDT'
        }

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت BTC الاختراق...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        if self.notifier:
            self.notifier.send_message(
                "🚀 <b>بدء تشغيل بوت BTC الاختراق</b>\n"
                f"الاستراتيجية: اختراق النطاق\n"
                f"المؤشرات: مستويات الدعم/المقاومة + الحجم\n"
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
            logger.info("🛑 إيقاف بوت BTC الاختراق...")

def main():
    """الدالة الرئيسية"""
    try:
        bot = ScalpingTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
