import os
import traceback
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
warnings.filterwarnings('ignore')
from dotenv import load_dotenv
import threading
import schedule
from flask import Flask, jsonify
import pytz

# تشخيص مفصل للخطأ
def debug_initialization():
    """دالة تشخيصية مفصلة"""
    print("🔍 بدء التشخيص التفصيلي...")
    
    try:
        # 1. فحص متغيرات البيئة
        print("1. فحص متغيرات البيئة...")
        load_dotenv()
        api_key = os.environ.get('BINANCE_API_KEY')
        api_secret = os.environ.get('BINANCE_API_SECRET')
        
        print(f"   API_KEY موجود: {bool(api_key)}")
        print(f"   API_SECRET موجود: {bool(api_secret)}")
        
        if not api_key or not api_secret:
            raise ValueError("مفاتيح API غير مكتملة")
        
        # 2. فحص إعدادات التداول
        print("2. فحص إعدادات التداول...")
        from config import TRADING_SETTINGS
        
        # فحص أن جميع المفاتيح قابلة للتجزئة
        for key, value in TRADING_SETTINGS.items():
            print(f"   المفتاح: {key}, النوع: {type(key)}, القيمة: {value}")
            # محاولة استخدام المفتاح في مجموعة (سيظهر الخطأ هنا إذا كان غير قابل للتجزئة)
            test_set = set()
            test_set.add(key)  # إذا فشل هنا، سيعرفنا على المفتاح المشكلة
        
        print("✅ جميع المفاتيح قابلة للتجزئة")
        
        # 3. فحص تهيئة العميل
        print("3. فحص تهيئة عميل Binance...")
        client = Client(api_key, api_secret)
        server_time = client.futures_time()
        print("✅ اتصال Binance API ناجح")
        
        return True
        
    except Exception as e:
        print(f"❌ خطأ في التشخيص: {e}")
        print("🔍 تتبع الخطأ:")
        traceback.print_exc()
        return False

# تشغيل التشخيص قبل أي شيء
print("🚀 بدء تشخيص البوت...")
debug_success = debug_initialization()

if not debug_success:
    print("❌ فشل التشخيص، إيقاف البوت...")
    exit(1)

# ثم استمر في بقية الكود...
print("✅ التشخيص ناجح، متابعة التشغيل...")

# بقية imports
from config import *
from utils import setup_logging
from notifications import TelegramNotifier
from trade_manager import TradeManager
from market_analyzer import MarketAnalyzer
from price_manager import PriceManager
from performance_reporter import PerformanceReporter
from continuous_monitor import ContinuousMonitor
from web_server import run_flask_app

logger = setup_logging()

# ثم بقية الكود كما هو...

class FuturesTradingBot:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self):
        if FuturesTradingBot._instance is not None:
            raise Exception("هذه الفئة تستخدم نمط Singleton")

        # تحميل المفاتيح من البيئة مباشرة (كما في الأصل)
        self.api_key = os.environ.get('BINANCE_API_KEY')
        self.api_secret = os.environ.get('BINANCE_API_SECRET')

        if not all([self.api_key, self.api_secret]):
            raise ValueError("مفاتيح Binance مطلوبة")

        # تهيئة العميل بنفس الطريقة الأصلية
        try:
            self.client = Client(self.api_key, self.api_secret)
            self.test_api_connection()
        except Exception as e:
            logger.error(f"❌ فشل تهيئة العميل: {e}")
            raise

        # تهيئة المكونات - تم إصلاح تمرير الإعدادات
        self.notifier = self._initialize_notifier()
        self.symbols = TRADING_SETTINGS['symbols']
        
        # تهيئة المدراء
        self.trade_manager = TradeManager(self.client, self.notifier)
        self.price_manager = PriceManager(self.symbols, self.client)
        self.market_analyzer = MarketAnalyzer(self.client, TRADING_SETTINGS)  # تمرير الإعدادات كاملة
        self.performance_reporter = PerformanceReporter(self.trade_manager, self.notifier)
        self.continuous_monitor = ContinuousMonitor(self)
        
        # بقية الكود يبقى كما هو...
        
        # تهيئة الأرصدة
        self.symbol_balances = self.initialize_symbol_balances()
        self.performance_reporter.initialize_balances(self.client)
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self._start_services()
        self._send_startup_message()

        FuturesTradingBot._instance = self
        logger.info("✅ تم تهيئة البوت بنجاح")

    def _initialize_notifier(self):
        """تهيئة نظام الإشعارات"""
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                logger.info("✅ تهيئة Telegram Notifier ناجحة")
                return notifier
            except Exception as e:
                logger.error(f"❌ فشل تهيئة Telegram: {e}")
        return None

    def _start_services(self):
        """بدء الخدمات المساعدة"""
        # بدء خادم Flask
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        # بدء تحديث الأسعار
        self._start_price_updater()
        
        # بدء مزامنة الصفقات
        self._start_trade_sync()
        
        # بدء المراقبة المستمرة
        self._start_continuous_monitoring()
        
        # جدولة المهام
        self._schedule_tasks()
        
        logger.info("✅ تم بدء جميع الخدمات المساعدة")

    def _start_price_updater(self):
        """بدء تحديث الأسعار"""
        def price_update_thread():
            while True:
                try:
                    self.price_manager.update_prices()
                    time.sleep(TRADING_SETTINGS['price_update_interval'] * 60)
                except Exception as e:
                    logger.error(f"❌ خطأ في تحديث الأسعار: {str(e)}")
                    time.sleep(30)

        threading.Thread(target=price_update_thread, daemon=True).start()

    def _start_trade_sync(self):
        """بدء مزامنة الصفقات"""
        def sync_thread():
            while True:
                try:
                    self.trade_manager.sync_with_exchange()
                    time.sleep(60)  # مزامنة كل دقيقة
                except Exception as e:
                    logger.error(f"❌ خطأ في مزامنة الصفقات: {str(e)}")
                    time.sleep(30)

        threading.Thread(target=sync_thread, daemon=True).start()

    def _start_continuous_monitoring(self):
        """بدء خدمة المراقبة المستمرة"""
        def monitor_thread():
            while True:
                try:
                    self.continuous_monitor.monitor_active_trades()
                    time.sleep(60)  # فحص كل دقيقة
                except Exception as e:
                    logger.error(f"❌ خطأ في مراقبة الصفقات: {e}")
                    time.sleep(30)
    
        threading.Thread(target=monitor_thread, daemon=True).start()
        logger.info("✅ بدء خدمة المراقبة المستمرة")

    def _schedule_tasks(self):
        """جدولة المهام الدورية"""
        if self.notifier:
            schedule.every(3).hours.do(self.send_performance_report)
            schedule.every(30).minutes.do(self.send_heartbeat)
            schedule.every(1).hours.do(self.check_trade_timeout)
            logger.info("✅ تم جدولة المهام الدورية")

    def _send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            message = (
                "🚀 <b>بدء تشغيل بوت العقود الآجلة - النسخة المحسنة</b>\n\n"
                f"📊 <b>الميزات الجديدة:</b>\n"
                f"• نظام مزامنة دقيق للصفقات\n"
                f"• تحسين جودة الإشارات\n"
                f"• إدارة محسنة للموارد\n"
                f"• تقارير أداء دقيقة\n\n"
                f"🕒 <b>وقت البدء:</b>\n"
                f"{datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.notifier.send_message(message, 'startup')

    def test_api_connection(self):
        """اختبار اتصال API"""
        try:
            server_time = self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise

    def initialize_symbol_balances(self):
        """تهيئة أرصدة الرموز"""
        weight_sum = sum(TRADING_SETTINGS['weights'].values())
        return {
            symbol: (weight / weight_sum) * TRADING_SETTINGS['total_capital']
            for symbol, weight in TRADING_SETTINGS['weights'].items()
        }

    def get_current_price(self, symbol):
        """الحصول على السعر الحالي"""
        return self.price_manager.get_price(symbol)

    def get_historical_data(self, symbol, interval='30m', limit=100):
        """جلب البيانات التاريخية"""
        return self.market_analyzer.get_historical_data(symbol, interval, limit)

    def calculate_indicators(self, data):
        """حساب المؤشرات الفنية"""
        from utils import calculate_indicators
        return calculate_indicators(data)

    def analyze_symbol(self, symbol):
        """تحليل الرمز"""
        return self.market_analyzer.analyze_symbol(symbol)

    def should_accept_signal(self, symbol, direction, analysis):
        """فلاتر الجودة المحسنة للإشارات"""
        # تجنب الذروة في RSI
        if analysis['rsi'] > 70 and direction == 'LONG':
            logger.info(f"⏸️ تجنب LONG - RSI مرتفع: {analysis['rsi']:.1f}")
            return False
        
        if analysis['rsi'] < 30 and direction == 'SHORT':
            logger.info(f"⏸️ تجنب SHORT - RSI منخفض: {analysis['rsi']:.1f}")
            return False
    
        # قوة الاتجاه
        if abs(analysis['trend_strength']) < TRADING_SETTINGS['min_trend_strength']:
            logger.info(f"⏸️ إشارة ضعيفة - اتجاه ضعيف: {analysis['trend_strength']:.2f}%")
            return False
    
        # تقلبات السعر
        if analysis['atr'] / analysis['price'] > TRADING_SETTINGS['max_volatility'] / 100:
            logger.info(f"⏸️ تقلبات عالية - ATR: {(analysis['atr']/analysis['price']*100):.1f}%")
            return False
        
        # انحراف السعر عن المتوسط
        if abs(analysis['price_vs_sma20']) > TRADING_SETTINGS['max_price_deviation']:
            logger.info(f"⏸️ سعر بعيد عن المتوسط: {analysis['price_vs_sma20']:.1f}%")
            return False
    
        # شرط الزخم - أكثر صرامة
        if direction == 'LONG' and analysis['momentum'] < 0.001:
            logger.info(f"⏸️ تجنب LONG - زخم ضعيف: {analysis['momentum']:.4f}")
            return False
        
        if direction == 'SHORT' and analysis['momentum'] > -0.001:
            logger.info(f"⏸️ تجنب SHORT - زخم ضعيف: {analysis['momentum']:.4f}")
            return False
    
        # شرط حجم أقوى
        if analysis['volume_ratio'] < 0.9:
            logger.info(f"⏸️ حجم تداول ضعيف: {analysis['volume_ratio']:.2f}")
            return False
    
        # كشف التناقضات بين المؤشرات
        contradiction_score = self.market_analyzer._detect_contradictions(analysis, direction)
        if contradiction_score >= 2:
            logger.info(f"⏸️ إشارة متناقضة - درجة التناقض: {contradiction_score}")
            return False
    
        # تأكيد الاتجاه من متعدد الإطار الزمني
        if not self.market_analyzer._confirm_trend_multi_timeframe(symbol, direction):
            logger.info(f"⏸️ اتجاه غير مؤكد في الإطارات الزمنية المتعددة")
            return False
    
        return True

    def send_enhanced_trade_signal_notification(self, symbol, direction, analysis, can_trade, reasons=None):
        """إشعار إشارة تداول محسن مع تحذيرات التناقض"""
        if not self.notifier:
            return
        
        try:
            contradiction_score = self.market_analyzer._detect_contradictions(analysis, direction)
            has_contradictions = contradiction_score >= 1
        
            if can_trade and not has_contradictions:
                message = (
                    f"🔔 <b>إشارة تداول قوية - جاهزة للتنفيذ</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"قوة الإشارة: {analysis['signal_strength']:.1f}%\n"
                    f"السعر الحالي: ${analysis['price']:.4f}\n"
                    f"الرصيد المتاح: ${self.symbol_balances.get(symbol, 0):.2f}\n"
                    f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"<b>تفاصيل المؤشرات:</b>\n"
                    f"• SMA10: {analysis['sma10']:.4f}\n"
                    f"• SMA20: {analysis['sma20']:.4f}\n"
                    f"• SMA50: {analysis['sma50']:.4f}\n"
                    f"• RSI: {analysis['rsi']:.2f}\n"
                    f"• Momentum: {analysis['momentum']:.4f}\n"
                    f"• Volume Ratio: {analysis['volume_ratio']:.2f}\n"
                    f"• MACD: {analysis['macd']:.4f}"
                )
            elif can_trade and has_contradictions:
                message = (
                    f"⚠️ <b>إشارة تداول مع تحذيرات - يرجى المراجعة</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"قوة الإشارة: {analysis['signal_strength']:.1f}%\n"
                    f"<b>تحذيرات التناقض:</b> {contradiction_score}\n"
                    f"السعر الحالي: ${analysis['price']:.4f}\n"
                    f"الرصيد المتاح: ${self.symbol_balances.get(symbol, 0):.2f}\n"
                    f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"<b>تفاصيل المؤشرات:</b>\n"
                    f"• SMA10: {analysis['sma10']:.4f}\n"
                    f"• SMA20: {analysis['sma20']:.4f}\n"
                    f"• SMA50: {analysis['sma50']:.4f}\n"
                    f"• RSI: {analysis['rsi']:.2f}\n"
                    f"• Momentum: {analysis['momentum']:.4f} {'⚠️' if analysis['momentum'] < 0.001 else ''}\n"
                    f"• Volume Ratio: {analysis['volume_ratio']:.2f} {'⚠️' if analysis['volume_ratio'] < 1.0 else ''}\n"
                    f"• MACD: {analysis['macd']:.4f}\n\n"
                    f"<b>ملاحظة:</b> هذه الإشارة تحتوي على تناقضات وقد تكون محفوفة بالمخاطر"
                )
            else:
                message = (
                    f"⏸️ <b>إشارة تداول - غير قابلة للتنفيذ</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"قوة الإشارة: {analysis['signal_strength']:.1f}%\n"
                    f"<b>أسباب عدم التنفيذ:</b>\n"
                )
                for reason in reasons:
                    message += f"• {reason}\n"
                message += f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
        
            self.notifier.send_message(message, 'trade_signal')
        
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال إشعار الإشارة المحسن: {e}")

    def can_open_trade(self, symbol):
        """التحقق من إمكانية فتح صفقة"""
        reasons = []
        
        # التحقق من الحد الأقصى للصفقات
        if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
            reasons.append(f"الحد الأقصى للصفقات ({TRADING_SETTINGS['max_active_trades']})")
            
        # التحقق من وجود صفقة نشطة لنفس الرمز
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append("صفقة نشطة موجودة")
            
        # التحقق من الرصيد المتاح
        available_balance = self.symbol_balances.get(symbol, 0)
        if available_balance < 5:
            reasons.append(f"رصيد غير كافي: ${available_balance:.2f}")
            
        return len(reasons) == 0, reasons

    def get_futures_precision(self, symbol):
        """الحصول على معلومات الدقة"""
        try:
            info = self.client.futures_exchange_info()
            symbol_info = next((s for s in info['symbols'] if s['symbol'] == symbol), None)
            
            if symbol_info:
                lot_size = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                price_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
                min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
                
                min_notional = float(min_notional_filter['notional']) if min_notional_filter else TRADING_SETTINGS['min_notional_value']
                step_size = float(lot_size['stepSize']) if lot_size else 0.001
                
                precision = 0
                if step_size < 1:
                    precision = int(round(-np.log10(step_size)))
                
                return {
                    'step_size': step_size,
                    'tick_size': float(price_filter['tickSize']) if price_filter else 0.001,
                    'precision': precision,
                    'min_qty': float(lot_size['minQty']) if lot_size else 0.001,
                    'min_notional': min_notional
                }
            
            return {
                'step_size': 0.001, 
                'tick_size': 0.001, 
                'precision': 3, 
                'min_qty': 0.001, 
                'min_notional': TRADING_SETTINGS['min_notional_value']
            }
        except Exception as e:
            logger.error(f"❌ خطأ في جلب دقة العقود: {e}")
            return {
                'step_size': 0.001, 
                'tick_size': 0.001, 
                'precision': 3, 
                'min_qty': 0.001, 
                'min_notional': TRADING_SETTINGS['min_notional_value']
            }

    def calculate_position_size(self, symbol, direction, analysis, available_balance):
        """حساب حجم المركز"""
        try:
            current_price = self.get_current_price(symbol)
            if not current_price:
                return None, None, None

            precision_info = self.get_futures_precision(symbol)
            step_size = precision_info['step_size']
            min_notional = precision_info['min_notional']
            
            leverage = TRADING_SETTINGS['max_leverage']
            position_value = min(available_balance * leverage, TRADING_SETTINGS['base_trade_size'])
            
            if position_value < min_notional:
                position_value = min_notional * 1.1
            
            quantity = position_value / current_price
            
            if step_size > 0:
                quantity = round(quantity / step_size) * step_size
            
            if quantity < precision_info['min_qty']:
                quantity = precision_info['min_qty']
                position_value = quantity * current_price
            
            if position_value < min_notional:
                return None, None, None
            
            atr = analysis.get('atr', current_price * 0.02)
            stop_loss_pct = (TRADING_SETTINGS['atr_stop_loss_multiplier'] * atr / current_price)
            take_profit_pct = (TRADING_SETTINGS['atr_take_profit_multiplier'] * atr / current_price)
            
            if direction == 'LONG':
                stop_loss_price = current_price * (1 - stop_loss_pct)
                take_profit_price = current_price * (1 + take_profit_pct)
            else:
                stop_loss_price = current_price * (1 + stop_loss_pct)
                take_profit_price = current_price * (1 - take_profit_pct)
            
            return quantity, stop_loss_price, take_profit_price
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return None, None, None

    def set_leverage(self, symbol, leverage):
        """ضبط الرافعة المالية"""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في ضبط الرافعة لـ {symbol}: {e}")
            return True

    def set_margin_type(self, symbol, margin_type):
        """ضبط نوع الهامش"""
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
            return True
        except Exception as e:
            error_msg = str(e)
            if "No need to change margin type" in error_msg:
                return True
            elif "Account has open positions" in error_msg:
                return True
            else:
                logger.warning(f"⚠️ فشل ضبط نوع الهامش لـ {symbol}: {error_msg}")
                return True

    def execute_trade(self, symbol, direction, quantity, stop_loss_price, take_profit_price, analysis):
        """تنفيذ الصفقة"""
        try:
            current_price = self.get_current_price(symbol)
            if not current_price:
                raise Exception("لا يمكن الحصول على السعر الحالي")
                
            notional_value = quantity * current_price
            min_notional = self.get_futures_precision(symbol)['min_notional']
            
            if notional_value < min_notional:
                raise Exception(f"القيمة الاسمية ${notional_value:.2f} أقل من الحد الأدنى ${min_notional:.2f}")
            
            if not self.set_leverage(symbol, TRADING_SETTINGS['max_leverage']):
                raise Exception("فشل ضبط الرافعة")
                
            if not self.set_margin_type(symbol, TRADING_SETTINGS['margin_type']):
                raise Exception("فشل ضبط نوع الهامش")
            
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity,
                reduceOnly=False
            )
            
            # انتظار التنفيذ
            executed_qty = 0
            for i in range(10):
                time.sleep(0.5)
                order_status = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                executed_qty = float(order_status.get('executedQty', 0))
                if executed_qty > 0:
                    break
            
            if executed_qty == 0:
                try:
                    self.client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                except:
                    pass
                raise Exception("الأمر لم ينفذ")
            
            # الحصول على سعر الدخول الفعلي
            avg_price = float(order_status.get('avgPrice', 0))
            if avg_price == 0:
                avg_price = current_price
            
            # تسجيل الصفقة
            trade_data = {
                'symbol': symbol,
                'quantity': quantity,
                'entry_price': avg_price,
                'leverage': TRADING_SETTINGS['max_leverage'],
                'side': direction,
                'timestamp': datetime.now(DAMASCUS_TZ),
                'status': 'open',
                'trade_type': 'futures',
                'stop_loss': stop_loss_price,
                'take_profit': take_profit_price,
                'order_id': order['orderId']
            }
            
            self.trade_manager.add_trade(symbol, trade_data)
            
            # تحديث الرصيد
            trade_value_leverage = notional_value / TRADING_SETTINGS['max_leverage']
            self.symbol_balances[symbol] = max(0, self.symbol_balances[symbol] - trade_value_leverage)
            
            if self.notifier:
                message = (
                    f"✅ <b>تم فتح الصفقة بنجاح</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"الكمية: {quantity:.6f}\n"
                    f"سعر الدخول: ${avg_price:.4f}\n"
                    f"وقف الخسارة: ${stop_loss_price:.4f}\n"
                    f"جني الأرباح: ${take_profit_price:.4f}\n"
                    f"الرافعة: {TRADING_SETTINGS['max_leverage']}x\n"
                    f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                )
                self.notifier.send_message(message, 'trade_open')
            
            logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            
            if self.notifier:
                message = (
                    f"❌ <b>فشل تنفيذ صفقة</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"السبب: {str(e)}"
                )
                self.notifier.send_message(message, 'trade_failed')
            
            return False

    def check_trade_timeout(self):
        """فحص انتهاء وقت الصفقات"""
        current_time = datetime.now(DAMASCUS_TZ)
        symbols_to_close = []
        
        for symbol, trade in self.trade_manager.get_all_trades().items():
            trade_age = current_time - trade['timestamp']
            hours_open = trade_age.total_seconds() / 3600
            
            if hours_open >= TRADING_SETTINGS['trade_timeout_hours']:
                symbols_to_close.append(symbol)
                logger.info(f"⏰ انتهاء وقت الصفقة لـ {symbol}")
        
        for symbol in symbols_to_close:
            self.close_trade(symbol, 'timeout')

    def close_trade(self, symbol, reason='manual'):
        """إغلاق الصفقة"""
        try:
            trade = self.trade_manager.get_trade(symbol)
            if not trade:
                return False

            current_price = self.get_current_price(symbol)
            if not current_price:
                return False

            side = 'SELL' if trade['side'] == 'LONG' else 'BUY'
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=trade['quantity'],
                reduceOnly=True
            )
            
            # انتظار التنفيذ
            executed_qty = 0
            for i in range(10):
                time.sleep(0.5)
                order_status = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                executed_qty = float(order_status.get('executedQty', 0))
                if executed_qty > 0:
                    break
            
            if executed_qty == 0:
                raise Exception("أمر الإغلاق لم ينفذ")
            
            # إزالة الصفقة
            self.trade_manager.remove_trade(symbol)
            
            # استعادة الرصيد
            trade_value_leverage = (trade['quantity'] * trade['entry_price']) / trade['leverage']
            self.symbol_balances[symbol] += trade_value_leverage
            
            if self.notifier:
                message = (
                    f"🔒 <b>تم إغلاق الصفقة</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {trade['side']}\n"
                    f"السبب: {reason}\n"
                    f"سعر الدخول: ${trade['entry_price']:.4f}\n"
                    f"سعر الخروج: ${current_price:.4f}\n"
                    f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                )
                self.notifier.send_message(message, 'trade_close')
            
            logger.info(f"✅ تم إغلاق صفقة {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {symbol}: {e}")
            return False

    def get_active_trades_details(self):
        """الحصول على تفاصيل الصفقات النشطة"""
        return self.trade_manager.get_all_trades()

    def scan_and_trade(self):
        """المسح الضوئي وتنفيذ الصفقات"""
        try:
            logger.info("🔍 بدء المسح الضوئي للفرص...")
            
            # فحص انتهاء وقت الصفقات
            self.check_trade_timeout()
            
            # التحقق من عدد الصفقات النشطة
            if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
                logger.info("⏸️ إيقاف المسح - الحد الأقصى للصفقات")
                return
            
            for symbol in self.symbols:
                try:
                    # تخطي الرموز التي بها صفقات نشطة
                    if self.trade_manager.is_symbol_trading(symbol):
                        continue
                    
                    # تحليل الرمز
                    has_signal, analysis, direction = self.analyze_symbol(symbol)
                    
                    if has_signal and direction:
                        # تطبيق فلاتر الجودة
                        if not self.should_accept_signal(symbol, direction, analysis):
                            continue
                        
                        can_trade, reasons = self.can_open_trade(symbol)
                        
                        self.send_enhanced_trade_signal_notification(symbol, direction, analysis, can_trade, reasons)
                        
                        if can_trade:
                            available_balance = self.symbol_balances.get(symbol, 0)
                            quantity, stop_loss, take_profit = self.calculate_position_size(
                                symbol, direction, analysis, available_balance
                            )
                            
                            if quantity and quantity > 0:
                                success = self.execute_trade(symbol, direction, quantity, stop_loss, take_profit, analysis)
                                
                                if success:
                                    logger.info(f"✅ تم تنفيذ صفقة {direction} لـ {symbol}")
                    
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"❌ خطأ في معالجة {symbol}: {e}")
                    continue
            
            logger.info("✅ اكتمل المسح الضوئي")
            
        except Exception as e:
            logger.error(f"❌ خطأ في المسح الضوئي: {e}")

    def send_performance_report(self):
        """إرسال تقرير الأداء"""
        self.performance_reporter.generate_performance_report()

    def send_heartbeat(self):
        """إرسال نبضة"""
        if self.notifier:
            active_trades = self.trade_manager.get_active_trades_count()
            heartbeat_msg = (
                "💓 <b>نبضة البوت</b>\n"
                f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}\n"
                f"الصفقات النشطة: {active_trades}\n"
                f"الحالة: 🟢 نشط"
            )
            self.notifier.send_message(heartbeat_msg, 'heartbeat')

    def run(self):
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل بوت العقود الآجلة...")
        
        try:
            while True:
                try:
                    schedule.run_pending()
                    self.scan_and_trade()
                    
                    sleep_minutes = TRADING_SETTINGS['rescan_interval_minutes']
                    logger.info(f"⏳ انتظار {sleep_minutes} دقيقة للمسح التالي...")
                    time.sleep(sleep_minutes * 60)
                    
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

def main():
    try:
        bot = FuturesTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
