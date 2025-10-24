import os
import pandas as pd
import numpy as np
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

warnings.filterwarnings('ignore')
load_dotenv()

# ========== الإعدادات الأساسية ==========
TRADING_SETTINGS = {
    'symbols': ["BNBUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "LTCUSDT", 
                "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT"],
    'base_trade_amount': 4,
    'leverage': 50,
}

RISK_SETTINGS = {
    'atr_period': 14,
    'risk_ratio': 0.5,
    'volatility_multiplier': 1.5,
    'margin_risk_threshold': 0.7,
}

TAKE_PROFIT_LEVELS = {
    'LEVEL_1': {'target': 0.0025, 'allocation': 0.4},
    'LEVEL_2': {'target': 0.0035, 'allocation': 0.3},
    'LEVEL_3': {'target': 0.0050, 'allocation': 0.3}
}

damascus_tz = pytz.timezone('Asia/Damascus')
app = Flask(__name__)

# ========== إعدادات الأمان ==========
MANAGER_API_KEY = os.getenv("MANAGER_API_KEY", "manager_key_here")
API_KEYS = {MANAGER_API_KEY: "trade_manager"}

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not api_key or api_key not in API_KEYS:
            return jsonify({'success': False, 'message': 'غير مصرح بالوصول'}), 401
        return f(*args, **kwargs)
    return decorated_function

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TelegramNotifier:
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
            
            response = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=15)
            return response.status_code == 200
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False

class DynamicStopLoss:
    def __init__(self, atr_period=14, risk_ratio=0.5):
        self.atr_period = atr_period
        self.risk_ratio = risk_ratio
    
    def calculate_atr(self, df):
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        true_range = np.maximum(high_low, np.maximum(high_close, low_close))
        return true_range.rolling(self.atr_period).mean()
    
    def calculate_support_resistance(self, df):
        """حساب مستويات الدعم والمقاومة مع معالجة الأخطاء"""
        try:
            # ✅ حساب ATR مع معالجة الأخطاء
            df_with_atr = df.copy()
            df_with_atr['atr'] = self.calculate_atr(df_with_atr)
        
            # ✅ إذا فشل حساب ATR، استخدام قيمة افتراضية
            if df_with_atr['atr'].isna().all():
                current_price = df_with_atr['close'].iloc[-1]
                default_atr = current_price * 0.01  # 1% افتراضي
                df_with_atr['atr'] = default_atr
        
            # حساب الدعم والمقاومة
            df_with_atr['resistance'] = df_with_atr['high'].rolling(20, min_periods=1).max()
            df_with_atr['support'] = df_with_atr['low'].rolling(20, min_periods=1).min()
        
            # ✅ ملء القيم NaN
            df_with_atr['resistance'].fillna(method='bfill', inplace=True)
            df_with_atr['support'].fillna(method='bfill', inplace=True)
            df_with_atr['atr'].fillna(method='bfill', inplace=True)
        
            return df_with_atr
        
        except Exception as e:
            logger.error(f"❌ خطأ في حساب الدعم/المقاومة: {e}")
            # إرجاع DataFrame مع قيم افتراضية في حالة الخطأ
            df_default = df.copy()
            current_price = df['close'].iloc[-1]
            df_default['atr'] = current_price * 0.01
            df_default['resistance'] = current_price * 1.02
            df_default['support'] = current_price * 0.98
            return df_default
    
    def calculate_dynamic_stop_loss(self, symbol, entry_price, direction, df):
        try:
            current_atr = df['atr'].iloc[-1] if not df['atr'].isna().iloc[-1] else 0
            
            if direction == 'LONG':
                support_level = df['support'].iloc[-1]
                stop_loss_price = support_level - (current_atr * self.risk_ratio)
                max_stop_distance = entry_price * 0.02
                if entry_price - stop_loss_price > max_stop_distance:
                    stop_loss_price = entry_price - max_stop_distance
                stop_loss_price = min(stop_loss_price, entry_price * 0.995)
            else:
                resistance_level = df['resistance'].iloc[-1]
                stop_loss_price = resistance_level + (current_atr * self.risk_ratio)
                max_stop_distance = entry_price * 0.02
                if stop_loss_price - entry_price > max_stop_distance:
                    stop_loss_price = entry_price + max_stop_distance
                stop_loss_price = max(stop_loss_price, entry_price * 1.005)
            
            return stop_loss_price
        except Exception as e:
            logger.error(f"❌ خطأ في حساب وقف الخسارة: {e}")
            return entry_price * 0.985 if direction == 'LONG' else entry_price * 1.015

class DynamicTakeProfit:
    def __init__(self, base_levels=None, volatility_multiplier=1.5):
        self.base_levels = base_levels or TAKE_PROFIT_LEVELS
        self.volatility_multiplier = volatility_multiplier
    
    def calculate_dynamic_take_profit(self, symbol, entry_price, direction, df):
        try:
            current_atr = df['atr'].iloc[-1] if 'atr' in df.columns and not df['atr'].isna().iloc[-1] else 0
            current_close = df['close'].iloc[-1]
            
            take_profit_levels = {}
            for level, config in self.base_levels.items():
                base_target = config['target']
                
                if current_atr > 0:
                    atr_ratio = current_atr / current_close
                    volatility_factor = 1 + (atr_ratio * self.volatility_multiplier)
                    adjusted_target = base_target * volatility_factor
                else:
                    adjusted_target = base_target
                
                if direction == 'LONG':
                    tp_price = entry_price * (1 + adjusted_target)
                else:
                    tp_price = entry_price * (1 - adjusted_target)
                
                take_profit_levels[level] = {
                    'price': tp_price,
                    'target_percent': adjusted_target * 100,
                    'allocation': config['allocation'],
                    'quantity': None
                }
            
            return take_profit_levels
        except Exception as e:
            logger.error(f"❌ خطأ في حساب جني الأرباح: {e}")
            return {}

class MarginMonitor:
    def __init__(self, risk_threshold=0.7):
        self.risk_threshold = risk_threshold
    
    def check_margin_health(self, client):
        try:
            account_info = client.futures_account()
            total_margin = float(account_info['totalMarginBalance'])
            available_balance = float(account_info['availableBalance'])
            total_wallet_balance = float(account_info['totalWalletBalance'])
            
            if total_wallet_balance > 0:
                margin_ratio = (total_margin / total_wallet_balance)
                return {
                    'total_margin': total_margin,
                    'available_balance': available_balance,
                    'total_wallet_balance': total_wallet_balance,
                    'margin_ratio': margin_ratio,
                    'is_risk_high': margin_ratio > self.risk_threshold
                }
            return None
        except Exception as e:
            logger.error(f"❌ خطأ في فحص الهامش: {e}")
            return None

class CompleteTradeManager:
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.stop_loss_manager = DynamicStopLoss()
        self.take_profit_manager = DynamicTakeProfit()
        self.margin_monitor = MarginMonitor()
        self.managed_trades = {}
        self.performance_stats = {
            'total_trades_managed': 0,
            'profitable_trades': 0,
            'stopped_trades': 0,
            'take_profit_hits': 0,
            'total_pnl': 0
        }
        self.sync_interval = 300  # 5 دقائق بين كل مزامنة
    
    def get_price_data(self, symbol, interval='15m', limit=50):
        try:
            klines = self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            df = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close']:
                df[col] = pd.to_numeric(df[col])
            
            return df
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على بيانات السعر لـ {symbol}: {e}")
            return None
    
    def get_current_price(self, symbol):
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على سعر {symbol}: {e}")
            return None
    
    def get_active_positions_from_binance(self):
        try:
            positions = self.client.futures_account()['positions']
            active_positions = []
            
            for position in positions:
                position_amt = float(position['positionAmt'])
                if position_amt != 0 and position['symbol'] in TRADING_SETTINGS['symbols']:
                    active_positions.append({
                        'symbol': position['symbol'],
                        'quantity': abs(position_amt),
                        'entry_price': float(position['entryPrice']),
                        'direction': 'LONG' if position_amt > 0 else 'SHORT',
                        'leverage': int(position['leverage']),
                        'unrealized_pnl': float(position['unrealizedProfit'])
                    })
            
            return active_positions
        except Exception as e:
            logger.error(f"❌ خطأ في الحصول على الصفقات من Binance: {e}")
            return []
    
    def sync_with_binance_positions(self):
        try:
            active_positions = self.get_active_positions_from_binance()
            current_managed = set(self.managed_trades.keys())
            binance_symbols = {pos['symbol'] for pos in active_positions}
        
            # إضافة الصفقات الجديدة
            for position in active_positions:
                if position['symbol'] not in current_managed:
                    logger.info(f"🔄 إضافة صفقة جديدة للمراقبة: {position['symbol']}")
                
                    # ✅ إضافة تحقق قبل إدارة الصفقة
                    df = self.get_price_data(position['symbol'])
                    if df is not None and not df.empty:
                        # ✅ حساب ATR أولاً قبل إدارة الصفقة
                        df = self.stop_loss_manager.calculate_support_resistance(df)
                        if 'atr' in df.columns and not df['atr'].isna().iloc[-1]:
                            self.manage_new_trade(position)
                        else:
                            logger.warning(f"⚠️ لا يمكن إدارة {position['symbol']} - بيانات ATR غير متوفرة")
                    else:
                        logger.warning(f"⚠️ لا يمكن إدارة {position['symbol']} - بيانات السعر غير متوفرة")
        
            # إزالة الصفقات المغلقة
            for symbol in list(current_managed):
                if symbol not in binance_symbols:
                    logger.info(f"🔄 إزالة صفقة مغلقة: {symbol}")
                    if symbol in self.managed_trades:
                        del self.managed_trades[symbol]
        
            return len(active_positions)
        except Exception as e:
            logger.error(f"❌ خطأ في المزامنة مع Binance: {e}")
            return 0
    
    def manage_new_trade(self, trade_data):
        symbol = trade_data['symbol']
    
        logger.info(f"🔄 بدء إدارة صفقة جديدة: {symbol}")
    
        df = self.get_price_data(symbol)
        if df is None or df.empty:
            logger.error(f"❌ لا يمكن إدارة {symbol} - بيانات السعر غير متوفرة")
            return False
    
        try:
            # ✅ حساب الدعم والمقاومة و ATR أولاً
            df = self.stop_loss_manager.calculate_support_resistance(df)
        
            # ✅ التحقق من وجود عمود ATR
            if 'atr' not in df.columns or df['atr'].isna().iloc[-1]:
                logger.warning(f"⚠️ ATR غير متوفر لـ {symbol} - استخدام القيم الافتراضية")
                # استخدام قيم افتراضية إذا فشل حساب ATR
                current_price = self.get_current_price(symbol)
                if current_price:
                    atr_default = current_price * 0.01  # 1% افتراضي
                    df['atr'] = atr_default
        
            stop_loss = self.stop_loss_manager.calculate_dynamic_stop_loss(
                symbol, trade_data['entry_price'], trade_data['direction'], df
            )
        
            take_profit_levels = self.take_profit_manager.calculate_dynamic_take_profit(
                symbol, trade_data['entry_price'], trade_data['direction'], df
            )
        
            # إذا فشل حساب جني الأرباح، استخدام القيم الافتراضية
            if not take_profit_levels:
                logger.warning(f"⚠️ استخدام جني الأرباح الافتراضي لـ {symbol}")
                take_profit_levels = {
                    'LEVEL_1': {'price': trade_data['entry_price'] * 1.0025, 'target_percent': 0.25, 'allocation': 0.4, 'quantity': None},
                    'LEVEL_2': {'price': trade_data['entry_price'] * 1.0035, 'target_percent': 0.35, 'allocation': 0.3, 'quantity': None},
                    'LEVEL_3': {'price': trade_data['entry_price'] * 1.0050, 'target_percent': 0.50, 'allocation': 0.3, 'quantity': None}
                }
        
            total_quantity = trade_data['quantity']
            for level, config in take_profit_levels.items():
                config['quantity'] = total_quantity * config['allocation']
        
            self.managed_trades[symbol] = {
                **trade_data,
                'dynamic_stop_loss': stop_loss,
                'take_profit_levels': take_profit_levels,
                'closed_levels': [],
                'last_update': datetime.now(damascus_tz),
                'status': 'managed',
                'management_start': datetime.now(damascus_tz)
            }
        
            self.performance_stats['total_trades_managed'] += 1
            self.send_management_start_notification(symbol)
            return True
        
        except Exception as e:
            logger.error(f"❌ فشل إدارة الصفقة {symbol}: {e}")
            return False
    
    def check_managed_trades(self):
        closed_trades = []
        
        for symbol, trade in list(self.managed_trades.items()):
            try:
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                if self.check_stop_loss(symbol, current_price):
                    closed_trades.append(symbol)
                    continue
                
                self.check_take_profits(symbol, current_price)
                
                if (datetime.now(damascus_tz) - trade['last_update']).seconds > 3600:
                    self.update_dynamic_levels(symbol)
                
            except Exception as e:
                logger.error(f"❌ خطأ في فحص الصفقة {symbol}: {e}")
        
        return closed_trades
    
    def check_stop_loss(self, symbol, current_price):
        trade = self.managed_trades[symbol]
        stop_loss = trade['dynamic_stop_loss']
        
        should_close = False
        if trade['direction'] == 'LONG' and current_price <= stop_loss:
            should_close = True
            reason = "وقف خسارة ديناميكي"
        elif trade['direction'] == 'SHORT' and current_price >= stop_loss:
            should_close = True
            reason = "وقف خسارة ديناميكي"
        
        if should_close:
            success, message = self.close_entire_trade(symbol, reason)
            if success:
                self.performance_stats['stopped_trades'] += 1
                pnl_pct = self.calculate_pnl_percentage(trade, current_price)
                self.performance_stats['total_pnl'] += pnl_pct
                if pnl_pct > 0:
                    self.performance_stats['profitable_trades'] += 1
                self.send_trade_closed_notification(trade, current_price, reason, pnl_pct)
                return True
        
        return False
    
    def check_take_profits(self, symbol, current_price):
        trade = self.managed_trades[symbol]
        
        for level, config in trade['take_profit_levels'].items():
            if level in trade['closed_levels']:
                continue
            
            should_close = False
            if trade['direction'] == 'LONG' and current_price >= config['price']:
                should_close = True
            elif trade['direction'] == 'SHORT' and current_price <= config['price']:
                should_close = True
            
            if should_close:
                success = self.close_partial_trade(symbol, level, config)
                if success:
                    trade['closed_levels'].append(level)
                    self.performance_stats['take_profit_hits'] += 1
                    self.send_take_profit_notification(trade, level, current_price)
                    
                    if len(trade['closed_levels']) == len(trade['take_profit_levels']):
                        self.close_entire_trade(symbol, "تم جني جميع مستويات الربح")
                        self.performance_stats['profitable_trades'] += 1
    
    def close_partial_trade(self, symbol, level, config):
        try:
            trade = self.managed_trades[symbol]
            quantity = config['quantity']
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side='SELL' if trade['direction'] == 'LONG' else 'BUY',
                type='MARKET',
                quantity=quantity,
                reduceOnly=True
            )
            
            if order:
                logger.info(f"✅ جني رباح جزئي لـ {symbol} - المستوى {level}: {quantity:.6f}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ خطأ في الجني الجزئي لـ {symbol}: {e}")
            return False
    
    def close_entire_trade(self, symbol, reason):
        try:
            trade = self.managed_trades[symbol]
            
            total_quantity = trade['quantity']
            closed_quantity = sum(
                trade['take_profit_levels'][level]['quantity'] 
                for level in trade['closed_levels'] 
                if level in trade['take_profit_levels']
            )
            remaining_quantity = total_quantity - closed_quantity
            
            if remaining_quantity > 0:
                order = self.client.futures_create_order(
                    symbol=symbol,
                    side='SELL' if trade['direction'] == 'LONG' else 'BUY',
                    type='MARKET',
                    quantity=remaining_quantity,
                    reduceOnly=True
                )
                
                if order:
                    if symbol in self.managed_trades:
                        del self.managed_trades[symbol]
                    logger.info(f"✅ إغلاق كامل لـ {symbol}: {reason}")
                    return True, "تم الإغلاق بنجاح"
            
            return False, "لا توجد كمية للإغلاق"
        except Exception as e:
            logger.error(f"❌ خطأ في الإغلاق الكامل لـ {symbol}: {e}")
            return False, str(e)
    
    def calculate_pnl_percentage(self, trade, current_price):
        if trade['direction'] == 'LONG':
            return (current_price - trade['entry_price']) / trade['entry_price'] * 100
        else:
            return (trade['entry_price'] - current_price) / trade['entry_price'] * 100
    
    def update_dynamic_levels(self, symbol):
        if symbol not in self.managed_trades:
            return
        
        trade = self.managed_trades[symbol]
        df = self.get_price_data(symbol)
        if df is None:
            return
        
        df = self.stop_loss_manager.calculate_support_resistance(df)
        new_stop_loss = self.stop_loss_manager.calculate_dynamic_stop_loss(
            symbol, trade['entry_price'], trade['direction'], df
        )
        
        current_price = self.get_current_price(symbol)
        if current_price:
            if (trade['direction'] == 'LONG' and new_stop_loss > trade['dynamic_stop_loss']) or \
               (trade['direction'] == 'SHORT' and new_stop_loss < trade['dynamic_stop_loss']):
                self.managed_trades[symbol]['dynamic_stop_loss'] = new_stop_loss
                logger.info(f"🔄 تحديث وقف الخسارة لـ {symbol}: {new_stop_loss:.4f}")
        
        self.managed_trades[symbol]['last_update'] = datetime.now(damascus_tz)
    
    def monitor_margin_risk(self):
        margin_health = self.margin_monitor.check_margin_health(self.client)
        if margin_health and margin_health['is_risk_high']:
            logger.warning(f"🚨 مستوى خطورة مرتفع: {margin_health['risk_level']:.2%}")
            if self.notifier:
                self.send_margin_warning(margin_health)
            return True
        return False
    
    def auto_management_loop(self):
        last_sync = datetime.now(damascus_tz)
        last_report = datetime.now(damascus_tz)
        
        while True:
            try:
                current_time = datetime.now(damascus_tz)
                
                if (current_time - last_sync).seconds >= self.sync_interval:
                    synced_count = self.sync_with_binance_positions()
                    if synced_count > 0:
                        logger.info(f"🔄 مزامنة تلقائية: {synced_count} صفقة")
                    last_sync = current_time
                
                self.check_managed_trades()
                self.monitor_margin_risk()
                
                if (current_time - last_report).seconds >= 21600:  # 6 ساعات
                    self.send_performance_report()
                    last_report = current_time
                
                time.sleep(10)
                
            except Exception as e:
                logger.error(f"❌ خطأ في الحلقة التلقائية: {e}")
                time.sleep(30)
    
    def send_management_start_notification(self, symbol):
        trade = self.managed_trades[symbol]
        message = (
            f"🔄 <b>بدء إدارة صفقة جديدة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {trade['direction']}\n"
            f"سعر الدخول: ${trade['entry_price']:.4f}\n"
            f"الكمية: {trade['quantity']:.6f}\n"
            f"وقف الخسارة: ${trade['dynamic_stop_loss']:.4f}\n"
        )
        for level, config in trade['take_profit_levels'].items():
            message += f"• {level}: ${config['price']:.4f} ({config['target_percent']:.2f}%)\n"
        message += f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        self.notifier.send_message(message)
    
    def send_take_profit_notification(self, trade, level, current_price):
        config = trade['take_profit_levels'][level]
        message = (
            f"🎯 <b>جني أرباح جزئي</b>\n"
            f"العملة: {trade['symbol']}\n"
            f"المستوى: {level}\n"
            f"سعر الدخول: ${trade['entry_price']:.4f}\n"
            f"سعر الجني: ${current_price:.4f}\n"
            f"الربح: {config['target_percent']:.2f}%\n"
            f"الكمية: {config['quantity']:.6f}\n"
            f"المستويات المتبقية: {len(trade['take_profit_levels']) - len(trade['closed_levels'])}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)
    
    def send_trade_closed_notification(self, trade, current_price, reason, pnl_pct):
        pnl_emoji = "🟢" if pnl_pct > 0 else "🔴"
        message = (
            f"🔒 <b>إغلاق الصفقة</b>\n"
            f"العملة: {trade['symbol']}\n"
            f"الاتجاه: {trade['direction']}\n"
            f"سعر الدخول: ${trade['entry_price']:.4f}\n"
            f"سعر الخروج: ${current_price:.4f}\n"
            f"الربح/الخسارة: {pnl_emoji} {pnl_pct:+.2f}%\n"
            f"السبب: {reason}\n"
            f"المستويات المحققة: {len(trade['closed_levels'])}/{len(trade['take_profit_levels'])}\n"
            f"مدة الإدارة: {self.get_management_duration(trade)}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)
    
    def send_margin_warning(self, margin_health):
        message = (
            f"⚠️ <b>تحذير: مستوى خطورة مرتفع</b>\n"
            f"نسبة الهامش المستخدم: {margin_health['margin_ratio']:.2%}\n"
            f"الرصيد المتاح: ${margin_health['available_balance']:.2f}\n"
            f"إجمالي الرصيد: ${margin_health['total_wallet_balance']:.2f}\n"
            f"الحالة: مراقبة مستمرة ⚠️\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)
    
    def send_performance_report(self):
        if self.performance_stats['total_trades_managed'] > 0:
            win_rate = (self.performance_stats['profitable_trades'] / self.performance_stats['total_trades_managed']) * 100
        else:
            win_rate = 0
        
        message = (
            f"📊 <b>تقرير أداء مدير الصفقات</b>\n"
            f"إجمالي الصفقات: {self.performance_stats['total_trades_managed']}\n"
            f"الصفقات الرابحة: {self.performance_stats['profitable_trades']}\n"
            f"معدل الربح: {win_rate:.1f}%\n"
            f"أرباح Take Profit: {self.performance_stats['take_profit_hits']}\n"
            f"صفقات Stop Loss: {self.performance_stats['stopped_trades']}\n"
            f"الصفقات النشطة: {len(self.managed_trades)}\n"
            f"إجمالي PnL: {self.performance_stats['total_pnl']:.2f}%\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)
    
    def get_management_duration(self, trade):
        duration = datetime.now(damascus_tz) - trade['management_start']
        hours = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60
        return f"{hours}h {minutes}m"

class TradeManagerBot:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if TradeManagerBot._instance is not None:
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
        
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = CompleteTradeManager(self.client, self.notifier)
        
        TradeManagerBot._instance = self
        logger.info("✅ تم تهيئة مدير الصفقات بنجاح")
    
    def test_connection(self):
        try:
            self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise
    
    def start_management(self):
        try:
            active_count = self.trade_manager.sync_with_binance_positions()
            logger.info(f"🔄 بدء إدارة {active_count} صفقة نشطة")
            
            if self.notifier:
                message = (
                    f"🚀 <b>بدء تشغيل مدير الصفقات المتكامل</b>\n"
                    f"الوظيفة: إدارة وقف الخسارة وجني الأرباح تلقائياً\n"
                    f"العملات المدعومة: {', '.join(TRADING_SETTINGS['symbols'])}\n"
                    f"تقنية وقف الخسارة: ديناميكي حسب الدعم/المقاومة + ATR\n"
                    f"تقنية جني الأرباح: 3 مستويات مع تعديل التقلب\n"
                    f"المراقبة: كل 10 ثواني\n"
                    f"المزامنة: تلقائية مع Binance كل 5 دقائق\n"
                    f"الصفقات النشطة: {active_count}\n"
                    f"الحالة: جاهز للمراقبة ✅\n"
                    f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}"
                )
                self.notifier.send_message(message)
            
            return True
        except Exception as e:
            logger.error(f"❌ خطأ في بدء الإدارة: {e}")
            return False

@app.route('/')
def health_check():
    try:
        bot = TradeManagerBot.get_instance()
        status = {
            'status': 'running',
            'managed_trades': len(bot.trade_manager.managed_trades),
            'performance_stats': bot.trade_manager.performance_stats,
            'timestamp': datetime.now(damascus_tz).isoformat()
        }
        return jsonify(status)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/api/management/sync', methods=['POST'])
@require_api_key
def sync_positions():
    try:
        bot = TradeManagerBot.get_instance()
        count = bot.trade_manager.sync_with_binance_positions()
        return jsonify({
            'success': True,
            'message': f'تمت مزامنة {count} صفقة',
            'synced_positions': count
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/management/status')
def get_management_status():
    try:
        bot = TradeManagerBot.get_instance()
        status = {
            'managed_trades': len(bot.trade_manager.managed_trades),
            'performance_stats': bot.trade_manager.performance_stats,
            'active_trades': list(bot.trade_manager.managed_trades.keys())
        }
        return jsonify(status)
    except Exception as e:
        return jsonify({'error': str(e)})

def run_flask_app():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

def main():
    try:
        bot = TradeManagerBot.get_instance()
        bot.start_management()
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        logger.info("🚀 بدء تشغيل مدير الصفقات المتكامل...")
        bot.trade_manager.auto_management_loop()
                
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
