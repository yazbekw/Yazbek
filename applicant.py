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
from flask import Flask, jsonify, request
import pytz
from dotenv import load_dotenv
from functools import wraps
import secrets

warnings.filterwarnings('ignore')
load_dotenv()

# ========== الإعدادات الأساسية ==========
TRADING_SETTINGS = {
    'symbols': [
        "BNBUSDT",
        "ETHUSDT",
        #"SOLUSDT",
        #"XRPUSDT", 
        #"BTCUSDT",
        #"ADAUSDT",
        #"AVAXUSDT",
        #"DOTUSDT",
        #"LINKUSDT"
    ],
    'base_trade_amount': 2,  # 2 USD
    'leverage': 75,  # 75x leverage
    'position_size': 2 * 75,  # 150 USD position size
    'max_simultaneous_trades': 2,  # Max 1 trade at same time
    'max_trades_per_symbol': 1,  # Only 1 trade per symbol
    'min_balance_required': 2,  # Minimum balance required
}
# إزالة مستويات جني الأرباح التلقائية
# سيتم إغلاق الصفقات يدوياً أو بإشارة خارجية فقط

# ضبط التوقيت
damascus_tz = pytz.timezone('Asia/Damascus')
os.environ['TZ'] = 'Asia/Damascus'

# تطبيق Flask للرصد
app = Flask(__name__)

# ========== إعدادات الأمان ==========
API_KEYS = {
    os.getenv("EXECUTOR_API_KEY", "default_key_here"): "bot_scanner"
}

def require_api_key(f):
    """مصادقة على الـ API"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not api_key or api_key not in API_KEYS:
            return jsonify({'success': False, 'message': 'غير مصرح بالوصول'}), 401
        return f(*args, **kwargs)
    return decorated_function

class PrecisionManager:
    """مدير دقة الأسعار والكميات فقط"""
    
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
        """ضبط الكمية حسب الدقة - إصدار محسن"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                logger.warning(f"⚠️ لا توجد معلومات دقة لـ {symbol}، استخدام القيمة الافتراضية")
                return round(quantity, 3)  # دقة افتراضية آمنة
        
            lot_size_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
            if lot_size_filter:
                step_size = float(lot_size_filter['stepSize'])
                min_qty = float(lot_size_filter.get('minQty', 0))
                max_qty = float(lot_size_filter.get('maxQty', float('inf')))
            
                # حساب الدقة المناسبة
                precision = 0
                if step_size < 1:
                    precision = len(str(step_size).split('.')[1].rstrip('0'))
            
                # ضبط الكمية حسب step_size
                adjusted_quantity = float(int(quantity / step_size) * step_size)
            
                # التأكد من الحدود
                adjusted_quantity = max(adjusted_quantity, min_qty)
                adjusted_quantity = min(adjusted_quantity, max_qty)
            
                # تقريب للدقة المناسبة
                adjusted_quantity = round(adjusted_quantity, precision)
            
                logger.info(f"🎯 ضبط كمية {symbol}: {quantity} -> {adjusted_quantity} (step: {step_size}, precision: {precision})")
            
                return adjusted_quantity
        
            # إذا لم يوجد فلتر، استخدام دقة آمنة
            return round(quantity, 3)
        
        except Exception as e:
            logger.error(f"❌ خطأ في ضبط كمية {symbol}: {e}")
            # قيمة آمنة للطوارئ
            return round(quantity, 3)

class TelegramNotifier:
    """مدير إشعارات التلغرام مبسط"""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, message, message_type='info'):
        """إرسال رسالة مبسطة"""
        try:
            if not self.token or not self.chat_id:
                logger.warning("⚠️ مفاتيح Telegram غير موجودة")
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
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
            
            if response.status_code == 200:
                logger.info(f"✅ تم إرسال إشعار Telegram بنجاح")
                return True
            else:
                logger.warning(f"⚠️ فشل إرسال إشعار Telegram: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False


class MultiLevelTradeExecutor:
    """منفذ الصفقات متعدد المستويات - بدون تتبع تلقائي"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.precision_manager = PrecisionManager(client)
        self.active_trades = {}
        self.start_periodic_cleanup()

    def start_periodic_cleanup(self):
        """بدء التنظيف الدوري للصفقات المغلقة"""
        def cleanup_loop():
            while True:
                try:
                    time.sleep(300)  # كل 5 دقائق
                    self.cleanup_closed_trades()
                    logger.info("🔄 تنظيف دوري للصفقات المغلقة")
                except Exception as e:
                    logger.error(f"❌ خطأ في التنظيف الدوري: {e}")
    
        cleanup_thread = threading.Thread(target=cleanup_loop, daemon=True)
        cleanup_thread.start()

    def _get_current_price(self, symbol):
        """الحصول على السعر الحالي"""
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

    def sync_with_binance_positions(self):
        """مزامنة الصفقات النشطة مع المواقع الفعلية في Binance - حل جذري"""
        try:
            # الحصول على جميع المواقع الفعلية من Binance
            positions = self.client.futures_account()['positions']
            
            # إنشاء مجموعة من الرموز التي لديها صفقات نشطة فعلياً
            active_symbols_in_binance = set()
            for position in positions:
                position_amt = float(position['positionAmt'])
                if position_amt != 0:  # فقط الصفقات النشطة فعلياً
                    active_symbols_in_binance.add(position['symbol'])
            
            # الآن تحديث الحالة المحلية بناءً على الواقع في Binance
            trades_to_close = []
            
            for trade_id, trade in list(self.active_trades.items()):
                symbol = trade['symbol']
                
                if trade['status'] == 'open':
                    if symbol not in active_symbols_in_binance:
                        # الصفقة مسجلة كمفتوحة محلياً ولكنها مغلقة في Binance
                        logger.warning(f"🔄 اكتشاف صفقة مغلقة في Binance ولكنها مفتوحة محلياً: {trade_id}")
                        trades_to_close.append(trade_id)
                    else:
                        # تحديث السعر الحالي للصفقات النشطة
                        current_price = self._get_current_price(symbol)
                        if current_price:
                            trade['current_price'] = current_price
            
            # إغلاق الصفقات التي تم اكتشاف إغلاقها في Binance
            for trade_id in trades_to_close:
                trade = self.active_trades[trade_id]
                trade.update({
                    'status': 'closed',
                    'close_price': trade.get('current_price', trade['entry_price']),
                    'close_time': datetime.now(damascus_tz),
                    'close_reason': 'اكتشاف إغلاق من Binance',
                    'pnl_pct': 0,
                    'pnl_usd': 0
                })
                logger.info(f"✅ تمت مزامنة إغلاق الصفقة: {trade_id}")
            
            return len(trades_to_close)
            
        except Exception as e:
            logger.error(f"❌ خطأ في مزامنة الصفقات مع Binance: {e}")
            return 0

    def cleanup_closed_trades(self):
        """تنظيف الصفقات المغلقة من الذاكرة - نسخة محسنة وقوية"""
        try:
            closed_trades = []
            old_trades = []
            inconsistent_trades = []
        
            current_time = datetime.now(damascus_tz)
        
            for trade_id, trade in list(self.active_trades.items()):
                # 1. الصفقات المعلنة كمغلقة
                if trade['status'] == 'closed':
                    closed_trades.append(trade_id)
            
                # 2. الصفقات القديمة جداً (أكثر من 12 ساعة)
                elif trade['status'] == 'open':
                    trade_age = current_time - trade['timestamp']
                    if trade_age.total_seconds() > 12 * 3600:  # 12 ساعة فقط للاحتياط
                        old_trades.append(trade_id)
                        logger.warning(f"⏳ صفقة قديمة: {trade_id} - عمرها {trade_age}")
                
                # 3. صفقات بدون بيانات كافية (غير متسقة)
                elif not trade.get('symbol') or not trade.get('entry_price'):
                    inconsistent_trades.append(trade_id)
                    logger.warning(f"❓ صفقة غير متسقة: {trade_id}")
        
            # حذف جميع الصفقات المشبوهة
            all_trades_to_remove = set(closed_trades + old_trades + inconsistent_trades)
            
            for trade_id in all_trades_to_remove:
                if trade_id in self.active_trades:
                    trade_info = self.active_trades[trade_id]
                    logger.info(f"🗑️ إزالة صفقة: {trade_id} - السبب: {'مغلقة' if trade_id in closed_trades else 'قديمة' if trade_id in old_trades else 'غير متسقة'}")
                    del self.active_trades[trade_id]
        
            if all_trades_to_remove:
                logger.info(f"🧹 تم تنظيف {len(all_trades_to_remove)} صفقة (مغلقة: {len(closed_trades)}, قديمة: {len(old_trades)}, غير متسقة: {len(inconsistent_trades)})")
            
            return len(all_trades_to_remove)
        
        except Exception as e:
            logger.error(f"❌ خطأ في تنظيف الصفقات المغلقة: {e}")
            return 0

                    
    def can_execute_trade(self, symbol, direction):
        """التحقق من إمكانية تنفيذ الصفقة - النسخة الكاملة مع المزامنة والرصيد"""
        try:
            # 🔄 أولاً: مزامنة كاملة مع Binance
            self.sync_with_binance_positions()
        
            # 🔄 ثانياً: تنظيف الصفقات المغلقة
            self.cleanup_closed_trades()
        
            # 🔍 ثالثاً: التحقق من Binance مباشرة
            try:
                positions = self.client.futures_account()['positions']
                active_symbols = []
                symbol_positions = 0
            
                for position in positions:
                    position_amt = float(position['positionAmt'])
                    if position_amt != 0:  # فقط الصفقات النشطة فعلياً
                        if position['symbol'] == symbol:
                            symbol_positions += 1
                        active_symbols.append(position['symbol'])
            
                logger.info(f"🔍 التحقق من Binance - {symbol}: {symbol_positions} صفقات نشطة")
            
                # ✅ التحقق من العدد المسموح لكل عملة
                max_per_symbol = TRADING_SETTINGS['max_trades_per_symbol']
                if symbol_positions >= max_per_symbol:
                    logger.warning(f"⚠️ وصل الحد الأقصى للصفقات على {symbol}: {symbol_positions}/{max_per_symbol}")
                    return False, f"وصل الحد الأقصى للصفقات على {symbol} ({symbol_positions}/{max_per_symbol})"
            
                # التحقق من العدد الإجمالي للصفقات النشطة
                unique_active_symbols = [s for s in active_symbols if s in TRADING_SETTINGS['symbols']]
                total_active_trades = len(set(unique_active_symbols))
            
                max_simultaneous = TRADING_SETTINGS['max_simultaneous_trades']
                if total_active_trades >= max_simultaneous:
                    logger.warning(f"⚠️ وصل الحد الأقصى للصفقات النشطة في Binance: {total_active_trades}/{max_simultaneous}")
                    return False, f"وصل الحد الأقصى للصفقات النشطة: {total_active_trades}/{max_simultaneous}"
            
                logger.info(f"✅ Binance: {symbol_positions} صفقة على {symbol}, إجمالي {total_active_trades} صفقات نشطة")
            
            except Exception as binance_error:
                logger.error(f"❌ فشل التحقق من Binance: {binance_error}")
                return False, f"فشل التحقق من حالة الحساب: {str(binance_error)}"

            # 💰 رابعاً: التحقق من الرصيد المتاح
            try:
                balance_info = self.client.futures_account_balance()
                usdt_balance = next((float(b['balance']) for b in balance_info if b['asset'] == 'USDT'), 0)
            
                # حساب الهامش المطلوب للصفقة
                required_margin = TRADING_SETTINGS['base_trade_amount']
                min_balance_required = TRADING_SETTINGS.get('min_balance_required', 2)
            
                # التحقق من الرصيد الإجمالي
                if usdt_balance < min_balance_required:
                    logger.warning(f"⚠️ رصيد إجمالي غير كافي: {usdt_balance:.2f} USDT < {min_balance_required} USDT")
                    return False, f"رصيد إجمالي غير كافي: {usdt_balance:.2f} USDT"
            
                # التحقق من الرصيد المتاح للهامش
                account_info = self.client.futures_account()
                available_balance = float(account_info.get('availableBalance', 0))
            
                if available_balance < required_margin:
                    logger.warning(f"⚠️ رصيد متاح غير كافي: {available_balance:.2f} USDT < {required_margin} USDT المطلوبة")
                    return False, f"رصيد متاح غير كافي: {available_balance:.2f} USDT"
            
                logger.info(f"✅ الرصيد كافي: {usdt_balance:.2f} USDT إجمالي, {available_balance:.2f} USDT متاح")
            
            except Exception as balance_error:
                logger.error(f"❌ فشل التحقق من الرصيد: {balance_error}")
                return False, f"فشل التحقق من الرصيد: {str(balance_error)}"

            # ✅ كل الشروط متوفرة
            logger.info(f"✅ يمكن تنفيذ صفقة {symbol} - جميع الشروط متوفرة")
            return True, "يمكن تنفيذ الصفقة"

        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من إمكانية التنفيذ: {e}")
            return False, f"خطأ في التحقق: {str(e)}"
                        
        
    def get_trade_level(self, confidence_score):
        """تحديد مستوى التداول بناء على درجة الثقة - محدث"""
        if confidence_score >= 65:
            return 'LEVEL_3'
        elif confidence_score >= 50:
            return 'LEVEL_2'
        elif confidence_score >= 25:  # ⬅️ تغيير من 41 إلى 50
            return 'LEVEL_1'
        else:
            return None
    
    def calculate_position_size(self, symbol, current_price, level):
        """حساب حجم المركز حسب المستوى"""
        try:
            # إعدادات مبسطة بدون مستويات جني أرباح
            if level == 'LEVEL_3':
                allocation = 0.99  # 99% من المركز
            elif level == 'LEVEL_2':
                allocation = 0.75  # 75% من المركز
            else:  # LEVEL_1
                allocation = 0.5   # 50% من المركز
            
            # الحجم الإجمالي للمركز
            total_size = TRADING_SETTINGS['position_size']
            
            # الحجم حسب التخصيص
            allocated_size = total_size * allocation
            
            # حساب الكمية
            quantity = allocated_size / current_price
            
            adjusted_quantity = self.precision_manager.adjust_quantity(symbol, quantity)
            
            if adjusted_quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol} - المستوى {level}: {adjusted_quantity:.6f} (تخصيص: {allocation*100}%)")
                return adjusted_quantity, allocated_size
            
            return None, 0
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز: {e}")
            return None, 0
    
    def set_leverage(self, symbol, leverage):
        """تعيين الرافعة المالية"""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة: {e}")
            return False
    
    def execute_trade(self, signal_data):
        """تنفيذ صفقة متعددة المستويات بناء على إشارة من البوت الخارجي"""
        try:
            # التحقق من البيانات المطلوبة
            required_fields = ['symbol', 'direction', 'signal_type', 'confidence_score']
            for field in required_fields:
                if field not in signal_data:
                    logger.error(f"❌ حقل مفقود في الإشارة: {field}")
                    return False, f"حقل مفقود: {field}"
            
            symbol = signal_data['symbol']
            direction = signal_data['direction']
            signal_type = signal_data['signal_type']
            confidence_score = signal_data['confidence_score']
            
            if direction not in ['LONG', 'SHORT']:
                logger.error(f"❌ اتجاه غير صالح: {direction}")
                return False, f"اتجاه غير صالح: {direction}"
            
            # 🔍 التحقق من إمكانية التنفيذ قبل أي شيء
            can_execute, message = self.can_execute_trade(symbol, direction)
            if not can_execute:
                return False, message
            
            # تحديد مستوى التداول
            trade_level = self.get_trade_level(confidence_score)
            if not trade_level:
                logger.error(f"❌ درجة ثقة غير كافية: {confidence_score} - الحد الأدنى 50 نقطة")
                return False, f"درجة ثقة غير كافية: {confidence_score}% - الحد الأدنى 50%"
            
            # الحصول على السعر الحالي
            current_price = self._get_current_price(symbol)
            if not current_price:
                logger.error(f"❌ لا يمكن الحصول على سعر {symbol}")
                return False, "لا يمكن الحصول على السعر"
            
            # حساب حجم المركز
            quantity, allocated_size = self.calculate_position_size(symbol, current_price, trade_level)
            if not quantity:
                logger.error(f"❌ لا يمكن حساب حجم المركز لـ {symbol}")
                return False, "لا يمكن حساب حجم المركز"
            
            # تعيين الرافعة
            self.set_leverage(symbol, TRADING_SETTINGS['leverage'])
            
            # تحديد اتجاه الأمر
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"⚡ تنفيذ صفقة {symbol}: {direction} | المستوى: {trade_level} | الثقة: {confidence_score}%")
            
            # تنفيذ الأمر السوقي
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order.get('orderId'):
                # الحصول على سعر التنفيذ الفعلي
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                    if order_info and order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                        logger.info(f"💰 سعر التنفيذ الفعلي لـ {symbol}: {executed_price:.4f}")
                except Exception as price_error:
                    logger.warning(f"⚠️ لا يمكن الحصول على سعر التنفيذ: {price_error}")
                
                # حفظ بيانات الصفقة بدون أهداف جني أرباح
                trade_id = f"{symbol}_{int(time.time())}"
                self.active_trades[trade_id] = {
                    'trade_id': trade_id,
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'order_id': order['orderId'],
                    'signal_type': signal_type,
                    'trade_level': trade_level,
                    'confidence_score': confidence_score,
                    'allocated_size': allocated_size,
                    'timestamp': datetime.now(damascus_tz),
                    'status': 'open'
                }
                
                # إرسال إشعار النجاح
                if self.notifier:
                    message = (
                        f"✅ <b>تم تنفيذ صفقة جديدة - المستوى {trade_level}</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"المستوى: {trade_level}\n"
                        f"درجة الثقة: {confidence_score}%\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"الحجم: ${allocated_size:.2f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"رقم الأمر: {order['orderId']}\n"
                        f"الصفقات النشطة: {len(self.get_active_trades())}/{TRADING_SETTINGS['max_simultaneous_trades']}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم تنفيذ صفقة {direction} لـ {symbol} بنجاح - المستوى {trade_level}")
                return True, f"تم التنفيذ بنجاح - المستوى {trade_level} - سعر الدخول: {executed_price:.4f}"
            
            else:
                logger.error(f"❌ فشل تنفيذ الأمر لـ {symbol}")
                return False, "فشل تنفيذ الأمر"
                
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة: {e}")
            return False, f"خطأ في التنفيذ: {str(e)}"
    
    def close_trade(self, trade_id, reason):
        """إغلاق صفقة مفتوحة"""
        try:
            if trade_id not in self.active_trades:
                return False, "لا توجد صفقة مفتوحة بهذا المعرف"
            
            trade = self.active_trades[trade_id]
            if trade['status'] != 'open':
                return False, "الصفقة ليست مفتوحة"
            
            symbol = trade['symbol']
            quantity = trade['quantity']
            direction = trade['side']
            
            # تحديد اتجاه الإغلاق
            close_side = 'SELL' if direction == 'LONG' else 'BUY'
            
            logger.info(f"🔄 إغلاق صفقة {symbol}: {direction} -> {close_side}")
            
            # تنفيذ أمر الإغلاق
            order = self.client.futures_create_order(
                symbol=symbol,
                side=close_side,
                type='MARKET',
                quantity=quantity,
                reduceOnly=True
            )
            
            if order and order.get('orderId'):
                # الحصول على سعر الإغلاق
                current_price = self._get_current_price(symbol)
                close_price = current_price if current_price else trade['entry_price']
                
                # حساب PnL
                entry_price = trade['entry_price']
                if direction == 'LONG':
                    pnl_pct = (close_price - entry_price) / entry_price * 100
                    pnl_usd = (close_price - entry_price) * quantity
                else:
                    pnl_pct = (entry_price - close_price) / entry_price * 100
                    pnl_usd = (entry_price - close_price) * quantity
                
                # تحديث بيانات الصفقة
                trade.update({
                    'status': 'closed',
                    'close_price': close_price,
                    'close_time': datetime.now(damascus_tz),
                    'pnl_pct': pnl_pct,
                    'pnl_usd': pnl_usd,
                    'close_reason': reason
                })
                
                # إرسال إشعار الإغلاق
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة - المستوى {trade['trade_level']}</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"المستوى: {trade['trade_level']}\n"
                        f"سعر الدخول: ${entry_price:.4f}\n"
                        f"سعر الخروج: ${close_price:.4f}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}% (${pnl_usd:+.2f})\n"
                        f"السبب: {reason}\n"
                        f"الصفقات النشطة: {len(self.get_active_trades())}/{TRADING_SETTINGS['max_simultaneous_trades']}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم إغلاق صفقة {symbol} - PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f})")
                return True, f"تم الإغلاق بنجاح - PnL: {pnl_pct:+.2f}% (${pnl_usd:+.2f})"
            
            else:
                logger.error(f"❌ فشل إغلاق صفقة {symbol}")
                return False, "فشل إغلاق الصفقة"
                
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {trade_id}: {e}")
            return False, f"خطأ في الإغلاق: {str(e)}"

        
    def get_active_trades(self):
        """الحصول على الصفقات النشطة - بدون تتبع تلقائي"""
        self.cleanup_closed_trades()
        active = {}
        for trade_id, trade in self.active_trades.items():
            if trade['status'] == 'open':
                # فقط إرجاع المعلومات بدون تتبع أو إغلاق تلقائي
                current_price = self._get_current_price(trade['symbol'])
                trade_info = trade.copy()
                if current_price:
                    trade_info['current_price'] = current_price
                active[trade_id] = trade_info
        return active
    
    def get_trade_history(self):
        """الحصول على سجل الصفقات"""
        history = []
        for trade_id, trade in self.active_trades.items():
            if trade['status'] == 'closed':
                history.append(trade)
        return history

class SimpleSignalReceiver:
    """مستقبل الإشارات المبسط - محدث"""
    
    def __init__(self, trade_executor):
        self.trade_executor = trade_executor
        self.received_signals = []
    
    def process_signal(self, signal_data):
        """معالجة إشارة من البوت الخارجي - تأخذ العدد المسموح من الإعدادات"""
        try:
            logger.info(f"📨 استقبال إشارة جديدة: {signal_data}")
        
            # التحقق من صحة الإشارة
            if not self._validate_signal(signal_data):
                return False, "إشارة غير صالحة"
        
            # حفظ الإشارة
            signal_data['received_time'] = datetime.now(damascus_tz)
            signal_data['processed'] = False
            self.received_signals.append(signal_data)
        
            # معالجة الإشارة حسب النوع
            signal_type = signal_data.get('signal_type', 'UNKNOWN')
        
            if signal_type == 'OPEN_TRADE':
                symbol = signal_data['symbol']
            
                # ✅ التحقق من العدد المسموح لكل عملة من الإعدادات
                active_trades = self.trade_executor.get_active_trades()
                symbol_trades_count = sum(1 for trade in active_trades.values() 
                                    if trade['symbol'] == symbol and trade['status'] == 'open')
            
                max_per_symbol = TRADING_SETTINGS.get('max_trades_per_symbol', 2)
            
                if symbol_trades_count >= max_per_symbol:
                    logger.warning(f"⚠️ وصل الحد الأقصى للصفقات على {symbol}: {symbol_trades_count}/{max_per_symbol}")
                    signal_data['result'] = 'FAILED'
                    signal_data['error_reason'] = f"وصل الحد الأقصى للصفقات على {symbol} ({symbol_trades_count}/{max_per_symbol})"
                    return False, f"وصل الحد الأقصى للصفقات على {symbol} ({symbol_trades_count}/{max_per_symbol})"
            
                # ✅ التحقق من العدد الإجمالي المسموح
                total_active_trades = len(active_trades)
                max_simultaneous = TRADING_SETTINGS.get('max_simultaneous_trades', 2)
            
                if total_active_trades >= max_simultaneous:
                    logger.warning(f"⚠️ وصل الحد الأقصى الإجمالي للصفقات: {total_active_trades}/{max_simultaneous}")
                    signal_data['result'] = 'FAILED'
                    signal_data['error_reason'] = f"وصل الحد الأقصى الإجمالي للصفقات ({total_active_trades}/{max_simultaneous})"
                    return False, f"وصل الحد الأقصى الإجمالي للصفقات ({total_active_trades}/{max_simultaneous})"
            
                # ✅ التحقق من الرصيد
                can_execute, message = self.trade_executor.can_execute_trade(symbol, signal_data['direction'])
            
                if not can_execute:
                    signal_data['result'] = 'FAILED'
                    signal_data['error_reason'] = message
                    return False, message
            
                # ✅ تنفيذ الصفقة
                success, message = self.trade_executor.execute_trade(signal_data)
                if success:
                    signal_data['processed'] = True
                    signal_data['result'] = 'SUCCESS'
                    signal_data['current_symbol_trades'] = symbol_trades_count + 1
                    signal_data['current_total_trades'] = total_active_trades + 1
                else:
                    signal_data['result'] = 'FAILED'
                    signal_data['error_reason'] = message
                return success, message
        
            elif signal_type == 'CLOSE_TRADE':
                symbol = signal_data.get('symbol')
                reason = signal_data.get('reason', 'إغلاق بإشارة خارجية')
                if symbol:
                    # البحث عن جميع الصفقات النشطة لهذه العملة
                    active_trades = self.trade_executor.get_active_trades()
                    trades_to_close = []
                
                    for trade_id, trade in active_trades.items():
                        if trade['symbol'] == symbol and trade['status'] == 'open':
                            trades_to_close.append(trade_id)
                
                    if trades_to_close:
                        # إغلاق جميع الصفقات النشطة لهذه العملة
                        success_count = 0
                        error_messages = []
                    
                        for trade_id in trades_to_close:
                            success, message = self.trade_executor.close_trade(trade_id, reason)
                            if success:
                                success_count += 1
                            else:
                                error_messages.append(message)
                    
                        if success_count > 0:
                            signal_data['processed'] = True
                            signal_data['result'] = 'PARTIAL_SUCCESS'
                            signal_data['closed_trades'] = success_count
                            signal_data['errors'] = error_messages
                            return True, f"تم إغلاق {success_count} صفقة - أخطاء: {error_messages}"
                        else:
                            signal_data['result'] = 'FAILED'
                            signal_data['errors'] = error_messages
                            return False, f"فشل إغلاق الصفقات: {error_messages}"
                    else:
                        signal_data['result'] = 'FAILED'
                        return False, f"لا توجد صفقات مفتوحة لـ {symbol}"
                else:
                    signal_data['result'] = 'FAILED'
                    return False, "رمز العملة مطلوب للإغلاق"
        
            else:
                signal_data['result'] = 'FAILED'
                return False, f"نوع إشارة غير معروف: {signal_type}"
            
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة الإشارة: {e}")
            if 'signal_data' in locals():
                signal_data['result'] = 'ERROR'
                signal_data['error'] = str(e)
            return False, f"خطأ في المعالجة: {str(e)}"    
    
    def _validate_signal(self, signal_data):
        """التحقق من صحة الإشارة - محدث"""
        required_fields = ['symbol', 'direction', 'signal_type', 'confidence_score']
        
        for field in required_fields:
            if field not in signal_data:
                logger.error(f"❌ حقل مطلوب مفقود: {field}")
                return False
        
        symbol = signal_data['symbol']
        if symbol not in TRADING_SETTINGS['symbols']:
            logger.error(f"❌ عملة غير مدعومة: {symbol} - المدعومة: {TRADING_SETTINGS['symbols']}")
            return False
        
        if signal_data['direction'] not in ['LONG', 'SHORT']:
            logger.error(f"❌ اتجاه غير صالح: {signal_data['direction']}")
            return False
        
        # 🔄 تحديث: التحقق من درجة الثقة لتكون 50 بدلاً من 41
        confidence_score = signal_data['confidence_score']
        if confidence_score < 25:  # ⬅️ تغيير من 41 إلى 50
            logger.error(f"❌ درجة ثقة غير كافية: {confidence_score}% - الحد الأدنى 50%")
            return False
        
        return True
    
    def get_recent_signals(self, limit=10):
        """الحصول على آخر الإشارات المستلمة"""
        return self.received_signals[-limit:]

def convert_signal_format(signal_data):
    """تحويل تنسيق الإشارة من البوت المرسل إلى البوت المنفذ - محدث"""
    try:
        # التحقق من الحقول الأساسية
        if 'symbol' not in signal_data or 'action' not in signal_data:
            logger.error("❌ إشارة ناقصة للحقول الأساسية")
            return None
        
        # 🔄 التحقق من عتبة الثقة أولاً
        confidence_score = signal_data.get('confidence_score', 0)
        if confidence_score < 25:  # ⬅️ تحديث العتبة
            logger.error(f"❌ درجة ثقة غير كافية في التحويل: {confidence_score}% - الحد الأدنى 50%")
            return None
        
        symbol = signal_data['symbol']
        action = signal_data['action'].upper()
        
        # تحويل ACTION إلى DIRECTION
        if action == 'BUY':
            direction = 'LONG'
            signal_type = 'OPEN_TRADE'
        elif action == 'SELL':
            direction = 'SHORT' 
            signal_type = 'OPEN_TRADE'
        else:
            logger.error(f"❌ إجراء غير معروف: {action}")
            return None
        
        # بناء الإشارة المحولة
        converted_signal = {
            'symbol': symbol,
            'direction': direction,
            'signal_type': signal_type,
            'confidence_score': signal_data.get('confidence_score', 0),
            'original_signal': signal_data,
            'reason': signal_data.get('reason', 'إشارة من البوت المرسل'),
            'source': 'top_bottom_scanner'
        }
        
        # إضافة معلومات إضافية إذا كانت متوفرة
        if 'coin' in signal_data:
            converted_signal['coin'] = signal_data['coin']
        if 'timeframe' in signal_data:
            converted_signal['timeframe'] = signal_data['timeframe']
        if 'analysis' in signal_data:
            converted_signal['analysis'] = signal_data['analysis']
        
        logger.info(f"✅ تم تحويل الإشارة: {action} -> {direction} | الثقة: {converted_signal['confidence_score']}%")
        return converted_signal
        
    except Exception as e:
        logger.error(f"❌ خطأ في تحويل تنسيق الإشارة: {e}")
        return None

def create_signal_notification(signal_data, success, message):
    """إنشاء إشعار تلغرام لاستقبال الإشارة"""
    try:
        symbol = signal_data.get('symbol', 'Unknown')
        action = signal_data.get('action', 'Unknown')
        confidence = signal_data.get('confidence_score', 0)
        coin = signal_data.get('coin', symbol.replace('USDT', ''))
        timeframe = signal_data.get('timeframe', 'Unknown')
        
        status_emoji = "✅" if success else "❌"
        status_text = "ناجح" if success else "فاشل"
        
        # تحديد مستوى التداول
        trade_level = "LEVEL_1" if 50 <= confidence <= 65 else "LEVEL_2" if 66 <= confidence <= 80 else "LEVEL_3" if confidence >= 81 else "غير مؤهل"
        
        notification = (
            f"📡 <b>استقبال إشارة تداول</b>\n"
            f"العملة: {coin} ({symbol})\n"
            f"الإجراء: {action}\n" 
            f"الإطار: {timeframe}\n"
            f"الثقة: {confidence}%\n"
            f"المستوى: {trade_level}\n"
            f"الحالة: {status_emoji} {status_text}\n"
            f"الرسالة: {message}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        
        return notification
        
    except Exception as e:
        logger.error(f"❌ خطأ في إنشاء الإشعار: {e}")
        return f"📡 إشارة مستلمة - {symbol} - الحالة: {success}"

class SimpleTradeBot:
    """البوت المبسط الرئيسي"""
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if SimpleTradeBot._instance is not None:
            raise Exception("هذه الفئة تستخدم نمط Singleton")
        
        # الحصول على مفاتيح API
        self.api_key = os.environ.get('BINANCE_API_KEY')
        self.api_secret = os.environ.get('BINANCE_API_SECRET')
        self.telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        
        if not all([self.api_key, self.api_secret]):
            raise ValueError("مفاتيح Binance مطلوبة")
        
        # تهيئة العميل
        try:
            self.client = Client(self.api_key, self.api_secret)
            self.test_connection()
        except Exception as e:
            logger.error(f"❌ فشل تهيئة العميل: {e}")
            raise
        
        # تهيئة المكونات
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_executor = MultiLevelTradeExecutor(self.client, self.notifier)
        self.signal_receiver = SimpleSignalReceiver(self.trade_executor)
        
        SimpleTradeBot._instance = self
        logger.info("✅ تم تهيئة البوت المنفذ متعدد المستويات بنجاح")
    
    def test_connection(self):
        """اختبار الاتصال"""
        try:
            self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise
    
    def get_status(self):
        """الحصول على حالة البوت"""
        active_trades = self.trade_executor.get_active_trades()
        return {
            'status': 'running',
            'active_trades': len(active_trades),
            'max_simultaneous_trades': TRADING_SETTINGS['max_simultaneous_trades'],
            'total_signals_received': len(self.signal_receiver.received_signals),
            'trading_settings': TRADING_SETTINGS,
            'timestamp': datetime.now(damascus_tz).isoformat()
        }

# ========== واجهة Flask المبسطة ==========

@app.route('/')
def health_check():
    """فحص صحة البوت والاتصال"""
    try:
        bot = SimpleTradeBot.get_instance()
        status = bot.get_status()
        
        # إضافة معلومات الاتصال
        status.update({
            'api_status': 'active',
            'supported_symbols': TRADING_SETTINGS['symbols'],
            'executor_version': '3.0-multi-level',
            'timestamp': datetime.now(damascus_tz).isoformat()
        })
        
        return jsonify(status)
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.now(damascus_tz).isoformat()
        }), 500

@app.route('/api/trade/signal', methods=['POST'])
@require_api_key
def receive_trade_signal():
    """استقبال إشارات تداول من البوت الخارجي - محدث"""
    try:
        bot = SimpleTradeBot.get_instance()
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': 'لا توجد بيانات'})
        
        # استخراج بيانات الإشارة من الهيكل الجديد
        signal_data = data.get('signal', {})
        if not signal_data:
            return jsonify({'success': False, 'message': 'بيانات الإشارة مفقودة'})
        
        logger.info(f"📨 استقبال إشارة جديدة من البوت المرسل: {signal_data}")
        
        # تحويل تنسيق البيانات من البوت المرسل إلى تنسيق البوت المنفذ
        converted_signal = convert_signal_format(signal_data)
        if not converted_signal:
            return jsonify({'success': False, 'message': 'تنسيق الإشارة غير صالح'})
        
        # معالجة الإشارة
        success, message = bot.signal_receiver.process_signal(converted_signal)
        
        response_data = {
            'success': success,
            'message': message,
            'signal_received': signal_data,
            'signal_processed': converted_signal,
            'timestamp': datetime.now(damascus_tz).isoformat()
        }
        
        # إرسال إشعار بالاستقبال
        if bot.notifier:
            notification_msg = create_signal_notification(signal_data, success, message)
            bot.notifier.send_message(notification_msg)
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ خطأ في استقبال إشارة التداول: {e}")
        return jsonify({'success': False, 'message': f'خطأ في المعالجة: {str(e)}'})

@app.route('/api/heartbeat', methods=['POST'])
@require_api_key
def receive_heartbeat():
    """استقبال نبضات من البوت المرسل - جديد"""
    try:
        data = request.get_json()
        
        if not data or not data.get('heartbeat'):
            return jsonify({'success': False, 'message': 'بيانات نبضة غير صالحة'})
        
        source = data.get('source', 'unknown')
        timestamp = data.get('timestamp')
        syria_time = data.get('syria_time')
        system_stats = data.get('system_stats', {})
        
        logger.info(f"💓 استقبال نبضة من {source} - الوقت: {syria_time}")
        
        response_data = {
            'success': True,
            'message': 'تم استقبال النبضة بنجاح',
            'executor_status': 'active',
            'active_trades': len(SimpleTradeBot.get_instance().trade_executor.get_active_trades()),
            'executor_version': '3.0-multi-level',
            'timestamp': datetime.now(damascus_tz).isoformat(),
            'received_heartbeat': {
                'source': source,
                'syria_time': syria_time,
                'scanner_stats': system_stats
            }
        }
        
        # إرسال إشعار تلغرام للنبضة (اختياري)
        bot = SimpleTradeBot.get_instance()
        if bot.notifier:
            heartbeat_msg = (
                f"💓 <b>نبضة اتصال من البوت المرسل</b>\n"
                f"المصدر: {source}\n"
                f"الوقت السوري: {syria_time}\n"
                f"الحالة: ✅ اتصال نشط\n"
                f"الصفقات النشطة: {response_data['active_trades']}\n"
                f"إحصائيات الماسح:\n"
                f"• عمليات المسح: {system_stats.get('total_scans', 0)}\n"
                f"• التنبيهات المرسلة: {system_stats.get('total_alerts_sent', 0)}\n"
                f"• الإشارات المرسلة: {system_stats.get('total_signals_sent', 0)}\n"
                f"آخر مسح: {system_stats.get('last_scan_time', 'غير معروف')}\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            bot.notifier.send_message(heartbeat_msg)
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"❌ خطأ في استقبال النبضة: {e}")
        return jsonify({'success': False, 'message': f'خطأ في استقبال النبضة: {str(e)}'})

@app.route('/debug/positions')
def debug_positions():
    """فحص تفصيلي للمواقع والصفقات - للتشخيص"""
    try:
        bot = SimpleTradeBot.get_instance()
        
        # الحصول على المواقع الفعلية من Binance
        positions_info = []
        try:
            positions = bot.client.futures_account()['positions']
            for position in positions:
                position_amt = float(position['positionAmt'])
                if position_amt != 0:
                    positions_info.append({
                        'symbol': position['symbol'],
                        'positionAmt': position_amt,
                        'entryPrice': position['entryPrice'],
                        'unrealizedProfit': position['unrealizedProfit']
                    })
        except Exception as e:
            positions_info = {'error': str(e)}
        
        # الحصول على الصفقات النشطة في الذاكرة
        active_trades = bot.trade_executor.get_active_trades()
        
        # الحصول على الرصيد
        balance_info = {}
        try:
            balance = bot.client.futures_account_balance()
            usdt_balance = next((b for b in balance if b['asset'] == 'USDT'), {})
            balance_info = usdt_balance
        except Exception as e:
            balance_info = {'error': str(e)}
        
        debug_info = {
            'binance_positions': positions_info,
            'local_active_trades': active_trades,
            'local_trades_count': len(active_trades),
            'balance_info': balance_info,
            'settings': {
                'max_simultaneous_trades': TRADING_SETTINGS['max_simultaneous_trades'],
                'max_trades_per_symbol': TRADING_SETTINGS['max_trades_per_symbol']
            },
            'timestamp': datetime.now(damascus_tz).isoformat()
        }
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({'error': str(e)})
    
@app.route('/health')
def health_check_endpoint():
    """فحص صحة البوت والاتصال - جديد"""
    try:
        bot = SimpleTradeBot.get_instance()
        status = bot.get_status()
        
        status.update({
            'api_status': 'active',
            'supported_symbols': TRADING_SETTINGS['symbols'],
            'executor_version': '3.0-multi-level',
            'timestamp': datetime.now(damascus_tz).isoformat()
        })
        
        return jsonify(status)
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.now(damascus_tz).isoformat()
        }), 500

@app.route('/active_trades')
def get_active_trades():
    """الحصول على الصفقات النشطة"""
    try:
        bot = SimpleTradeBot.get_instance()
        active_trades = bot.trade_executor.get_active_trades()
        return jsonify(active_trades)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/close_trade/<trade_id>', methods=['POST'])
def close_trade(trade_id):
    """إغلاق صفقة يدوياً"""
    try:
        bot = SimpleTradeBot.get_instance()
        data = request.get_json() or {}
        reason = data.get('reason', 'إغلاق يدوي')
        
        success, message = bot.trade_executor.close_trade(trade_id, reason)
        
        return jsonify({
            'success': success,
            'message': message,
            'timestamp': datetime.now(damascus_tz).isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ خطأ في إغلاق الصفقة: {e}")
        return jsonify({'success': False, 'message': f'خطأ: {str(e)}'})

@app.route('/recent_signals')
def get_recent_signals():
    """الحصول على آخر الإشارات المستلمة"""
    try:
        bot = SimpleTradeBot.get_instance()
        limit = request.args.get('limit', 10, type=int)
        signals = bot.signal_receiver.get_recent_signals(limit)
        
        # تحويل التاريخ إلى تنسيق قابل للقراءة
        for signal in signals:
            if 'received_time' in signal:
                signal['received_time'] = signal['received_time'].isoformat()
        
        return jsonify(signals)
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/signals/recent')
@require_api_key
def get_recent_signals_api():
    """الحصول على آخر الإشارات المستلمة - مع مصادقة"""
    try:
        bot = SimpleTradeBot.get_instance()
        limit = request.args.get('limit', 10, type=int)
        signals = bot.signal_receiver.get_recent_signals(limit)
        
        # تحويل التاريخ إلى تنسيق قابل للقراءة
        for signal in signals:
            if 'received_time' in signal:
                signal['received_time'] = signal['received_time'].isoformat()
        
        return jsonify({
            'success': True,
            'signals': signals,
            'total_count': len(signals),
            'timestamp': datetime.now(damascus_tz).isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/trading_levels')
def get_trading_levels():
    """الحصول على إعدادات مستويات التداول"""
    return jsonify({
        'trading_settings': TRADING_SETTINGS,
        'timestamp': datetime.now(damascus_tz).isoformat()
    })

def run_flask_app():
    """تشغيل تطبيق Flask"""
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('multi_level_trade_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def main():
    """الدالة الرئيسية"""
    try:
        # تهيئة البوت
        bot = SimpleTradeBot()
        
        # بدء Flask في thread منفصل
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        logger.info("🚀 بدء تشغيل البوت المنفذ متعدد المستويات...")
        
        # إرسال رسالة بدء التشغيل
        if bot.notifier:
            message = (
                "🚀 <b>بدء تشغيل البوت المنفذ متعدد المستويات v3.0</b>\n"
                f"الوظيفة: استقبال وتنفيذ الأوامر من البوت المرسل\n"
                f"العملات المدعومة: {', '.join(TRADING_SETTINGS['symbols'])}\n"
                f"حجم الصفقة: ${TRADING_SETTINGS['base_trade_amount']} × {TRADING_SETTINGS['leverage']} رافعة\n"
                f"أقصى صفقات: {TRADING_SETTINGS['max_simultaneous_trades']} صفقة في نفس الوقت\n"
                f"المستويات:\n"
                f"• LEVEL_1 (50-65%): تخصيص 50%\n"
                f"• LEVEL_2 (66-80%): تخصيص 75%\n"
                f"• LEVEL_3 (81-100%): تخصيص 99%\n"
                f"التتبع: بدون تتبع تلقائي للصفقات\n"
                f"جني الأرباح: يدوي أو بإشارة خارجية فقط\n"
                f"المنفذ: {os.environ.get('PORT', 10000)}\n"
                f"الحالة: جاهز لاستقبال الإشارات ✅\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            bot.notifier.send_message(message)
        
        # الحلقة الرئيسية المبسطة - بدون تتبع تلقائي
        while True:
            try:
                # فقط تسجيل الصفقات النشطة بدون أي تتبع تلقائي
                active_trades = bot.trade_executor.get_active_trades()
                if active_trades:
                    logger.info(f"📊 الصفقات النشطة: {len(active_trades)}/{TRADING_SETTINGS['max_simultaneous_trades']}")
                time.sleep(30)  # فحص كل 30 ثانية فقط للتسجيل
                
            except KeyboardInterrupt:
                logger.info("⏹️ إيقاف البوت يدوياً...")
                break
            except Exception as e:
                logger.error(f"❌ خطأ في الحلقة الرئيسية: {e}")
                time.sleep(30)
                
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
