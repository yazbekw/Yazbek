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
    return {'status': 'healthy', 'service': 'advanced-trading-bot', 'timestamp': datetime.now(damascus_tz).isoformat()}

@app.route('/active_trades')
def active_trades():
    try:
        bot = AdvancedTradingBot.get_instance()
        if bot:
            return jsonify(bot.get_active_trades_details())
        return jsonify([])
    except Exception as e:
        return {'error': str(e)}

@app.route('/market_analysis/<symbol>')
def market_analysis(symbol):
    try:
        bot = AdvancedTradingBot.get_instance()
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
        logging.FileHandler('advanced_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MarketPhaseAnalyzer:
    """محلل متقدم لمراحل السوق"""
    
    def __init__(self):
        self.supported_coins = {
            'ETHUSDT': {'name': 'Ethereum', 'symbol': 'ETH'},
            'LINKUSDT': {'name': 'Chainlink', 'symbol': 'LINK'},
            'ADAUSDT': {'name': 'Cardano', 'symbol': 'ADA'},
            'SOLUSDT': {'name': 'Solana', 'symbol': 'SOL'}
        }
    
    def analyze_phase(self, data):
        """تحليل مرحلة السوق من البيانات"""
        if len(data) < 50:
            return {"phase": "غير محدد", "confidence": 0, "action": "انتظار"}
        
        try:
            df = data.copy()
            
            # المؤشرات الأساسية
            df['sma20'] = df['close'].rolling(20).mean()
            df['sma50'] = df['close'].rolling(50).mean()
            
            # RSI
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0)
            loss = (-delta).where(delta < 0, 0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / (avg_loss + 1e-10)
            df['rsi'] = 100 - (100 / (1 + rs))
            
            # الحجم النسبي
            df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
            
            # MACD
            ema12 = df['close'].ewm(span=12, adjust=False).mean()
            ema26 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = ema12 - ema26
            df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            
            # Bollinger Bands
            df['bb_middle'] = df['close'].rolling(20).mean()
            df['bb_std'] = df['close'].rolling(20).std()
            df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
            df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
            
            # ATR
            df['tr'] = pd.concat([
                df['high'] - df['low'],
                (df['high'] - df['close'].shift()).abs(),
                (df['low'] - df['close'].shift()).abs()
            ], axis=1).max(axis=1)
            df['atr'] = df['tr'].rolling(14).mean()
            
            # VSA
            df['spread'] = df['high'] - df['low']
            df['spread_volume_ratio'] = df['spread'] / df['volume'].replace(0, 1e-10)
            
            latest = df.iloc[-1]
            prev = df.iloc[-10] if len(df) > 10 else df.iloc[0]
            
            # تحليل المرحلة
            phase_analysis = self._determine_phase(latest, prev)
            return phase_analysis
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل المرحلة: {e}")
            return {"phase": "خطأ", "confidence": 0, "action": "انتظار"}
    
    def _determine_phase(self, latest, prev):
        """تحديد مرحلة السوق"""
        # شروط التجميع
        accumulation_signs = [
            latest['volume_ratio'] < 1.2,
            latest['rsi'] < 60,
            latest['macd_hist'] > -0.001,
            latest['close'] > latest['bb_lower'],
            latest['close'] > latest['sma20'] * 0.98,
        ]
        
        # شروط الصعود
        markup_signs = [
            latest['close'] > latest['sma20'] > latest['sma50'],
            latest['volume_ratio'] > 1.0,
            latest['rsi'] > 50,
            latest['macd'] > latest['macd_signal'],
            latest['close'] > prev['close'],
        ]
        
        # شروط التوزيع
        distribution_signs = [
            latest['volume_ratio'] > 1.5,
            latest['rsi'] > 70,
            latest['macd_hist'] < 0,
            latest['close'] < latest['bb_upper'],
            latest['close'] < latest['sma20'] * 1.02,
        ]
        
        # شروط الهبوط
        markdown_signs = [
            latest['close'] < latest['sma20'] < latest['sma50'],
            latest['volume_ratio'] > 1.0,
            latest['rsi'] < 40,
            latest['macd'] < latest['macd_signal'],
            latest['close'] < prev['close'],
        ]
        
        scores = {
            "تجميع": sum(accumulation_signs),
            "صعود": sum(markup_signs),
            "توزيع": sum(distribution_signs),
            "هبوط": sum(markdown_signs)
        }
        
        best_phase = max(scores, key=scores.get)
        confidence = scores[best_phase] / 5.0
        
        action = self._get_action(best_phase, confidence)
        
        return {
            "phase": best_phase,
            "confidence": round(confidence, 2),
            "action": action,
            "indicators": {
                "rsi": round(latest['rsi'], 1),
                "volume_ratio": round(latest['volume_ratio'], 2),
                "macd_hist": round(latest['macd_hist'], 4),
                "bb_position": round((latest['close'] - latest['bb_lower']) / (latest['bb_upper'] - latest['bb_lower']), 2),
                "trend": "صاعد" if latest['sma20'] > latest['sma50'] else "هابط"
            }
        }
    
    def _get_action(self, phase, confidence):
        """تحديد الإجراء المناسب"""
        actions = {
            "تجميع": "استعداد للشراء - مرحلة تجميع",
            "صعود": "شراء - اتجاه صاعد",
            "توزيع": "بيع - مرحلة توزيع", 
            "هبوط": "بيع - اتجاه هابط"
        }
        
        base_action = actions.get(phase, "انتظار")
        
        if confidence > 0.7:
            if phase == "تجميع":
                return f"🟢 {base_action} قوي"
            elif phase == "صعود":
                return f"🟢 {base_action} قوي"
            elif phase == "توزيع":
                return f"🔴 {base_action} قوي"
            elif phase == "هبوط":
                return f"🔴 {base_action} قوي"
        
        return f"⚪ {base_action}"

class AdvancedSignalGenerator:
    """مولد إشارات تداول متقدم مع شروط شراء وبيع مشددة"""
    
    def __init__(self, phase_analyzer):
        self.phase_analyzer = phase_analyzer
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارة تداول مع شروط مخصصة للشراء والبيع"""
        try:
            if len(data) < 50:
                return None
            
            # تحليل مرحلة السوق
            phase_analysis = self.phase_analyzer.analyze_phase(data)
            
            # التحليل الفني
            technical_analysis = self._technical_analysis(data, current_price)
            
            # تحليل القوة
            strength_analysis = self._strength_analysis(data)
            
            # توليد الإشارات بشروط مخصصة
            long_signal = self._strict_long_signal(technical_analysis, strength_analysis, phase_analysis)
            short_signal = self._strict_short_signal(technical_analysis, strength_analysis, phase_analysis)
            
            # اختيار أفضل إشارة
            return self._select_signal(symbol, long_signal, short_signal, phase_analysis)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد الإشارة لـ {symbol}: {e}")
            return None
    
    def _strict_long_signal(self, technical, strength, phase_analysis):
        """إشارة شراء بشروط مشددة"""
        # 🎯 شروط شراء مشددة جداً
        strict_buy_conditions = [
            # 🔒 شروط الاتجاه القوي
            technical['sma10'] > technical['sma20'] > technical['sma50'],
            technical['ema12'] > technical['ema26'],
            technical['close'] > technical['sma20'] * 1.01,  # فوق المتوسط بـ 1%
            
            # 🔒 شروط الزخم القوي
            technical['rsi'] > 52 and technical['rsi'] < 68,  # نطاق أضيق
            technical['momentum'] > 0.003,  # زخم أقوى
            technical['macd'] > technical['macd_signal'] * 1.02,  # MACD قوي
            
            # 🔒 شروط الحجم والقوة
            technical['volume_ratio'] > 1.1,  # حجم أعلى
            technical['trend_strength'] > 1.0,  # اتجاه أقوى
            strength['volume_strength'] > 1.0,
            
            # 🔒 شروط مرحلة السوق
            phase_analysis['phase'] in ['صعود'],  # فقط في مرحلة الصعود
            phase_analysis['confidence'] > 0.7,  # ثقة عالية
            
            # 🔒 شروط إضافية مشددة
            technical['price_vs_sma20'] > 0.5,  # سعر أعلى من المتوسط
            strength['volatility'] < 3.0,  # تقلبات منخفضة
        ]
        
        # 🎯 نظام ترجيح مشدد للشراء
        strict_weights = [
            2.5,  # اتجاه قوي
            2.0,  # EMA
            1.8,  # فوق المتوسط
            2.0,  # RSI مشدد
            2.2,  # زخم قوي
            1.8,  # MACD قوي
            1.5,  # حجم عالي
            1.8,  # اتجاه أقوى
            1.2,  # قوة حجم
            2.5,  # مرحلة صعود فقط
            2.0,  # ثقة عالية
            1.5,  # سعر أعلى
            1.2,  # تقلبات منخفضة
        ]
        
        signal_score = sum(cond * weight for cond, weight in zip(strict_buy_conditions, strict_weights))
        max_score = sum(strict_weights)
        
        return {
            'direction': 'LONG',
            'score': signal_score,
            'confidence': signal_score / max_score,
            'conditions_met': sum(strict_buy_conditions),
            'total_conditions': len(strict_buy_conditions),
            'strict_conditions': True
        }
    
    def _strict_short_signal(self, technical, strength, phase_analysis):
        """إشارة بيع بشروط مشددة بنفس مستوى الشراء"""
        # 🎯 شروط بيع مشددة بنفس مستوى الشراء
        strict_sell_conditions = [
            # 🔒 شروط اتجاه هابط قوي
            technical['sma10'] < technical['sma20'] < technical['sma50'],
            technical['ema12'] < technical['ema26'],
            technical['close'] < technical['sma20'] * 0.99,  # تحت المتوسط بـ 1%
            
            # 🔒 شروط زخم هابط قوي
            technical['rsi'] < 48 and technical['rsi'] > 25,  # نطاق مشدد
            technical['momentum'] < -0.003,  # زخم هابط قوي
            technical['macd'] < technical['macd_signal'] * 0.98,  # MACD هابط قوي
            
            # 🔒 شروط الحجم والقوة
            technical['volume_ratio'] > 1.1,  # حجم أعلى
            technical['trend_strength'] < -1.0,  # اتجاه هابط أقوى
            strength['volume_strength'] > 1.0,
            
            # 🔒 شروط مرحلة السوق المشددة
            phase_analysis['phase'] in ['هبوط'],  # فقط في مرحلة الهبوط
            phase_analysis['confidence'] > 0.7,  # ثقة عالية
            
            # 🔒 شروط إضافية مشددة
            technical['price_vs_sma20'] < -0.5,  # سعر أقل من المتوسط
            strength['volatility'] < 3.0,  # تقلبات منخفضة
        ]
        
        # 🎯 نظام ترجيح مشدد للبيع بنفس أوزان الشراء
        strict_weights = [
            2.5,  # اتجاه هابط قوي
            2.0,  # EMA
            1.8,  # تحت المتوسط
            2.0,  # RSI مشدد
            2.2,  # زخم هابط قوي
            1.8,  # MACD هابط قوي
            1.5,  # حجم عالي
            1.8,  # اتجاه هابط أقوى
            1.2,  # قوة حجم
            2.5,  # مرحلة هبوط فقط
            2.0,  # ثقة عالية
            1.5,  # سعر أقل
            1.2,  # تقلبات منخفضة
        ]
        
        signal_score = sum(cond * weight for cond, weight in zip(strict_sell_conditions, strict_weights))
        max_score = sum(strict_weights)
        
        return {
            'direction': 'SHORT',
            'score': signal_score,
            'confidence': signal_score / max_score,
            'conditions_met': sum(strict_sell_conditions),
            'total_conditions': len(strict_sell_conditions),
            'strict_conditions': True
        }
    
    def _technical_analysis(self, data, current_price):
        """التحليل الفني المتقدم"""
        df = data.copy()
        
        # المتوسطات المتحركة
        df['sma10'] = df['close'].rolling(10).mean()
        df['sma20'] = df['close'].rolling(20).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['ema12'] = df['close'].ewm(span=12).mean()
        df['ema26'] = df['close'].ewm(span=26).mean()
        
        # RSI
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        # MACD
        df['macd'] = df['ema12'] - df['ema26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        
        # الزخم
        df['momentum'] = df['close'].pct_change(5)
        
        # الحجم
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # قوة الاتجاه
        df['trend_strength'] = (df['sma10'] - df['sma50']) / df['sma50'] * 100
        
        latest = df.iloc[-1]
        
        return {
            'sma10': latest['sma10'],
            'sma20': latest['sma20'], 
            'sma50': latest['sma50'],
            'ema12': latest['ema12'],
            'ema26': latest['ema26'],
            'rsi': latest['rsi'],
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'momentum': latest['momentum'],
            'volume_ratio': latest['volume_ratio'],
            'trend_strength': latest['trend_strength'],
            'price_vs_sma20': (current_price - latest['sma20']) / latest['sma20'] * 100,
            'close': latest['close']
        }
    
    def _calculate_rsi(self, prices, period):
        """حساب RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - (100 / (1 + rs))
    
    def _strength_analysis(self, data):
        """تحليل قوة السوق"""
        df = data.copy()
        
        volatility = df['close'].pct_change().std() * 100
        volume_strength = df['volume'].iloc[-1] / df['volume'].rolling(20).mean().iloc[-1]
        
        return {
            'volatility': volatility,
            'volume_strength': volume_strength
        }
    
    def _select_signal(self, symbol, long_signal, short_signal, phase_analysis):
        """اختيار أفضل إشارة مع عتبات متماثلة للشراء والبيع"""
        # 🎯 عتبات متماثلة للشراء والبيع
        min_confidence = 0.72      # 🔒 عتبة عالية متماثلة
        min_conditions = 9         # 🔒 شروط أكثر متماثلة
        
        valid_signals = []
        
        # 🔒 التحقق من إشارة الشراء (بشروط مشددة)
        if (long_signal['confidence'] >= min_confidence and 
            long_signal['conditions_met'] >= min_conditions):
            valid_signals.append(long_signal)
            
        # 🔒 التحقق من إشارة البيع (بشروط مشددة بنفس المستوى)
        if (short_signal['confidence'] >= min_confidence and 
            short_signal['conditions_met'] >= min_conditions):
            valid_signals.append(short_signal)
        
        if not valid_signals:
            return None
        
        # اختيار الإشارة ذات الثقة الأعلى
        best_signal = max(valid_signals, key=lambda x: x['confidence'])
        
        # 🎯 إضافة معلومات عن صرامة الشروط
        signal_info = {
            'symbol': symbol,
            'direction': best_signal['direction'],
            'confidence': best_signal['confidence'],
            'score': best_signal['score'],
            'phase_analysis': phase_analysis,
            'timestamp': datetime.now(damascus_tz),
            'conditions_met': best_signal['conditions_met'],
            'total_conditions': best_signal['total_conditions'],
            'strict_conditions': best_signal.get('strict_conditions', False)
        }
        
        # 📊 تسجيل معلومات الإشارة
        logger.info(f"🎯 إشارة {symbol}: {best_signal['direction']} "
                   f"(ثقة: {best_signal['confidence']:.2%}, "
                   f"شروط: {best_signal['conditions_met']}/{best_signal['total_conditions']}, "
                   f"نوع: {'مشددة' if best_signal.get('strict_conditions') else 'عادية'})")
        
        return signal_info
    
    def get_signal_stats(self, symbol, technical, phase_analysis):
        """الحصول على إحصائيات الإشارة للمراقبة"""
        long_signal = self._strict_long_signal(technical, self._strength_analysis(pd.DataFrame([technical])), phase_analysis)
        short_signal = self._strict_short_signal(technical, self._strength_analysis(pd.DataFrame([technical])), phase_analysis)
        
        return {
            'symbol': symbol,
            'long_confidence': long_signal['confidence'],
            'short_confidence': short_signal['confidence'],
            'long_conditions': f"{long_signal['conditions_met']}/{long_signal['total_conditions']}",
            'short_conditions': f"{short_signal['conditions_met']}/{short_signal['total_conditions']}",
            'long_meets_threshold': long_signal['confidence'] >= 0.72 and long_signal['conditions_met'] >= 9,
            'short_meets_threshold': short_signal['confidence'] >= 0.72 and short_signal['conditions_met'] >= 9,
            'timestamp': datetime.now(damascus_tz)
        }


class TradeManager:
    """مدير الصفقات المتقدم"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.trade_history = []
    
    def sync_with_exchange(self):
        """مزامنة الصفقات مع المنصة"""
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
                        # إضافة صفقة جديدة
                        side = "LONG" if quantity > 0 else "SHORT"
                        self.active_trades[symbol] = {
                            'symbol': symbol,
                            'quantity': abs(quantity),
                            'entry_price': float(position['entryPrice']),
                            'side': side,
                            'timestamp': datetime.now(damascus_tz),
                            'status': 'open'
                        }
            
            # إزالة الصفقات المغلقة
            closed_symbols = set(self.active_trades.keys()) - active_symbols
            for symbol in closed_symbols:
                if symbol in self.active_trades:
                    closed_trade = self.active_trades[symbol]
                    closed_trade['status'] = 'closed'
                    closed_trade['close_time'] = datetime.now(damascus_tz)
                    self.trade_history.append(closed_trade)
                    del self.active_trades[symbol]
            
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في مزامنة الصفقات: {e}")
            return False
    
    def get_active_trades_count(self):
        return len(self.active_trades)
    
    def is_symbol_trading(self, symbol):
        return symbol in self.active_trades
    
    def add_trade(self, symbol, trade_data):
        self.active_trades[symbol] = trade_data
    
    def remove_trade(self, symbol):
        if symbol in self.active_trades:
            del self.active_trades[symbol]
    
    def get_trade(self, symbol):
        return self.active_trades.get(symbol)
    
    def get_all_trades(self):
        return self.active_trades.copy()

class TelegramNotifier:
    """مدير إشعارات التلغرام"""
    
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
    
    def send_trade_alert(self, symbol, signal, current_price, phase_analysis):
        """إرسال إشعار صفقة"""
        direction_emoji = "🟢" if signal['direction'] == 'LONG' else "🔴"
        message = (
            f"{direction_emoji} <b>إشارة تداول جديدة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {signal['direction']}\n"
            f"السعر: ${current_price:.4f}\n"
            f"الثقة: {signal['confidence']:.2%}\n"
            f"المرحلة: {phase_analysis['phase']}\n"
            f"التوصية: {phase_analysis['action']}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        return self.send_message(message, 'trade_signal')


class HybridExitManager:
    """مدير خروج هجين يجمع بين الوقف الآلي والمراقبة"""
    
    def __init__(self, bot):
        self.bot = bot
    
    def manage_trade_exits(self, symbol, trade):
        """إدارة خيارات الخروج للصفقة"""
        try:
            current_price = self.bot.get_current_price(symbol)
            if not current_price:
                return
            
            # 1. ✅ التحقق من أوامر الوقف على المنصة
            if self.check_stop_orders_active(symbol):
                return  # الأوامر نشطة، لا حاجة لفعل شيء
            
            # 2. 📊 المراقبة الاستباقية
            should_exit, reason = self.proactive_monitoring(symbol, trade, current_price)
            
            if should_exit:
                self.bot.close_trade(symbol, f"مراقبة استباقية: {reason}")
            
            # 3. 🔄 تحديث مستويات الوقف إذا لزم الأمر
            self.adjust_stop_levels(symbol, trade, current_price)
            
        except Exception as e:
            logger.error(f"❌ خطأ في إدارة الخروج لـ {symbol}: {e}")
    
    def check_stop_orders_active(self, symbol):
        """التحقق من وجود أوامر وقف نشطة"""
        try:
            open_orders = self.bot.client.futures_get_open_orders(symbol=symbol)
            stop_orders = [order for order in open_orders if order['type'] in ['STOP_MARKET', 'TAKE_PROFIT_MARKET']]
            return len(stop_orders) > 0
        except:
            return False
    
    def proactive_monitoring(self, symbol, trade, current_price):
        """مراقبة استباقية للخروج"""
        # حساب الربح/الخسارة
        if trade['side'] == 'LONG':
            pnl_pct = (current_price - trade['entry_price']) / trade['entry_price'] * 100
        else:
            pnl_pct = (trade['entry_price'] - current_price) / trade['entry_price'] * 100
        
        # شروط الخروج الاستباقية
        exit_conditions = [
            (pnl_pct >= 5.0, f"ربح استباقي {pnl_pct:.1f}%"),  # ربح عالي
            (pnl_pct <= -4.0, f"خسارة استباقية {pnl_pct:.1f}%"),  # خسارة كبيرة
        ]
        
        for condition, reason in exit_conditions:
            if condition:
                return True, reason
        
        return False, ""
    
    def adjust_stop_levels(self, symbol, trade, current_price):
        """تعديل مستويات الوقف (Trailing Stop)"""
        try:
            if trade['side'] == 'LONG' and trade.get('stop_loss_price'):
                # رفع وقف الخسارة عند تحقيق ربح
                profit_pct = (current_price - trade['entry_price']) / trade['entry_price'] * 100
                if profit_pct > 2.0:
                    new_stop = trade['entry_price'] * 1.005  # وقف عند 0.5% ربح
                    if new_stop > trade['stop_loss_price']:
                        self.update_stop_loss(symbol, trade, new_stop)
                        
        except Exception as e:
            logger.error(f"❌ خطأ في تعديل وقف الخسارة: {e}")
    
    def update_stop_loss(self, symbol, trade, new_stop_price):
        """تحديث وقف الخسارة"""
        try:
            # إلغاء وقف الخسارة القديم
            if trade.get('stop_loss_order_id'):
                self.bot.client.futures_cancel_order(
                    symbol=symbol, 
                    orderId=trade['stop_loss_order_id']
                )
            
            # وضع وقف خسارة جديد
            new_order = self.bot.place_stop_loss_order(
                symbol, trade['side'], trade['quantity'], new_stop_price
            )
            
            if new_order:
                # تحديث بيانات الصفقة
                trade['stop_loss_price'] = new_stop_price
                trade['stop_loss_order_id'] = new_order['orderId']
                logger.info(f"🔄 تم تحديث وقف الخسارة لـ {symbol} إلى ${new_stop_price:.4f}")
                
        except Exception as e:
            logger.error(f"❌ فشل تحديث وقف الخسارة لـ {symbol}: {e}")


class AdvancedTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbols': ["ETHUSDT", "LINKUSDT", "ADAUSDT", "SOLUSDT"],
        'base_trade_size': 20,
        'max_leverage': 8,
        'max_active_trades': 4,
        'data_interval': '30m',
        'rescan_interval_minutes': 15,
        'min_signal_confidence': 0.70,
        'short_trading_enabled': True,
        'max_short_trades': 2,
        'risk_per_trade': 0.20,
        'max_portfolio_risk': 0.50,
    }
    
    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self):
        if AdvancedTradingBot._instance is not None:
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

        # تهيئة المكونات
        self.phase_analyzer = MarketPhaseAnalyzer()
        self.signal_generator = AdvancedSignalGenerator(self.phase_analyzer)
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        self.exit_manager = HybridExitManager(self)
        
        # إدارة الرصيد الحقيقي
        self.symbol_balances = self._initialize_real_balances()
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'initial_balance': self.real_time_balance['total_balance'],
            'current_balance': self.real_time_balance['total_balance']
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        AdvancedTradingBot._instance = self
        logger.info("✅ تم تهيئة البوت المتقدم بنجاح مع الرصيد الحقيقي")

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
        """جلب الرصيد الحقيقي من منصة Binance"""
        try:
            account_info = self.client.futures_account()
            
            total_balance = float(account_info['totalWalletBalance'])
            available_balance = float(account_info['availableBalance'])
            total_margin_balance = float(account_info['totalMarginBalance'])
            unrealized_pnl = float(account_info['totalUnrealizedProfit'])
            
            assets = {}
            for asset in account_info['assets']:
                if float(asset['walletBalance']) > 0:
                    assets[asset['asset']] = {
                        'wallet_balance': float(asset['walletBalance']),
                        'available_balance': float(asset['availableBalance']),
                        'unrealized_pnl': float(asset.get('unrealizedProfit', 0))
                    }
            
            balance_info = {
                'total_balance': total_balance,
                'available_balance': available_balance,
                'total_margin_balance': total_margin_balance,
                'unrealized_pnl': unrealized_pnl,
                'assets': assets,
                'timestamp': datetime.now(damascus_tz)
            }
            
            logger.info(f"💰 الرصيد الحقيقي: ${total_balance:.2f} | المتاح: ${available_balance:.2f}")
            return balance_info
            
        except Exception as e:
            logger.error(f"❌ فشل جلب الرصيد الحقيقي: {e}")
            return {
                'total_balance': 100.0,
                'available_balance': 100.0,
                'total_margin_balance': 100.0,
                'unrealized_pnl': 0.0,
                'assets': {},
                'timestamp': datetime.now(damascus_tz)
            }

    def _initialize_real_balances(self):
        """تهيئة أرصدة الرموز بناءً على الرصيد الحقيقي"""
        try:
            total_balance = self.real_time_balance['available_balance']
            total_symbols = len(self.TRADING_SETTINGS['symbols'])
            
            base_allocation = total_balance / total_symbols
            
            symbol_balances = {}
            for symbol in self.TRADING_SETTINGS['symbols']:
                symbol_balances[symbol] = base_allocation
            
            logger.info(f"💰 توزيع الرصيد الحقيقي: ${total_balance:.2f} على {total_symbols} رموز")
            return symbol_balances
            
        except Exception as e:
            logger.error(f"❌ خطأ في توزيع الرصيد الحقيقي: {e}")
            return {symbol: 20.0 for symbol in self.TRADING_SETTINGS['symbols']}

    def update_real_time_balance(self):
        """تحديث الرصيد الحقيقي من المنصة"""
        try:
            old_balance = self.real_time_balance['total_balance']
            self.real_time_balance = self.get_real_time_balance()
            new_balance = self.real_time_balance['total_balance']
            
            self.performance_stats['current_balance'] = new_balance
            
            balance_change = new_balance - old_balance
            if abs(balance_change) > 0.01:
                logger.info(f"📈 تغير الرصيد: ${old_balance:.2f} → ${new_balance:.2f} ({balance_change:+.2f})")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل تحديث الرصيد الحقيقي: {e}")
            return False

    def start_services(self):
        """بدء الخدمات المساعدة"""
        def sync_thread():
            while True:
                try:
                    self.trade_manager.sync_with_exchange()
                    self.update_real_time_balance()
                    self.sync_stop_orders()  # ✅ مزامنة أوامر الوقف
                    self.manage_active_trades_exits()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(30)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        if self.notifier:
            schedule.every(4).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)
            schedule.every(1).hours.do(self.send_heartbeat)

    def manage_active_trades_exits(self):
        """إدارة خروج الصفقات النشطة باستخدام النظام الهجين"""
        try:
            active_trades = self.trade_manager.get_all_trades()
            for symbol, trade in active_trades.items():
                self.exit_manager.manage_trade_exits(symbol, trade)
        except Exception as e:
            logger.error(f"❌ خطأ في إدارة خروج الصفقات: {e}")

    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            balance = self.real_time_balance
            message = (
                "🚀 <b>بدء تشغيل البوت المتقدم بالرصيد الحقيقي</b>\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الرصيد المتاح: ${balance['available_balance']:.2f}\n"
                f"الأصول: {len(self.TRADING_SETTINGS['symbols'])}\n"
                f"الصفقات القصوى: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"📊 <b>الإستراتيجية:</b> تحليل المراحل + الرصيد الحقيقي + أوامر الوقف"
            )
            self.notifier.send_message(message)

    def send_performance_report(self):
        """إرسال تقرير الأداء"""
        if not self.notifier:
            return
        
        active_trades = self.trade_manager.get_active_trades_count()
        message = (
            f"📊 <b>تقرير أداء البوت</b>\n"
            f"الصفقات النشطة: {active_trades}\n"
            f"الصفقات المفتوحة: {self.performance_stats['trades_opened']}\n"
            f"الصفقات المغلقة: {self.performance_stats['trades_closed']}\n"
            f"الصفقات الرابحة: {self.performance_stats['winning_trades']}\n"
            f"الصفقات الخاسرة: {self.performance_stats['losing_trades']}\n"
            f"الرصيد الحالي: ${self.performance_stats['current_balance']:.2f}\n"
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)

    def send_balance_report(self):
        """إرسال تقرير بالرصيد الحقيقي"""
        if not self.notifier:
            return
        
        try:
            self.update_real_time_balance()
            
            balance = self.real_time_balance
            active_trades = self.trade_manager.get_active_trades_count()
            total_risk = self.calculate_total_portfolio_risk()
            
            message = (
                f"💰 <b>تقرير الرصيد الحقيقي</b>\n"
                f"الرصيد الإجمالي: ${balance['total_balance']:.2f}\n"
                f"الرصيد المتاح: ${balance['available_balance']:.2f}\n"
                f"الهامش الإجمالي: ${balance['total_margin_balance']:.2f}\n"
                f"PNL غير محقق: ${balance['unrealized_pnl']:+.2f}\n"
                f"الصفقات النشطة: {active_trades}\n"
                f"مخاطرة المحفظة: ${total_risk:.2f}\n"
                f"آخر تحديث: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
            )
            
            self.notifier.send_message(message, 'balance_report')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تقرير الرصيد: {e}")

    def send_heartbeat(self):
        """إرسال نبضة"""
        if self.notifier:
            active_trades = self.trade_manager.get_active_trades_count()
            message = f"💓 البوت نشط - الصفقات النشطة: {active_trades}"
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
        
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات")
        
        if direction == 'SHORT':
            active_shorts = sum(1 for trade in self.trade_manager.get_all_trades().values() 
                              if trade['side'] == 'SHORT')
            if active_shorts >= self.TRADING_SETTINGS['max_short_trades']:
                reasons.append("الحد الأقصى لصفقات البيع")
        
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append("صفقة نشطة على الرمز")
        
        available_balance = self.real_time_balance['available_balance']
        if available_balance < 5:
            reasons.append("رصيد غير كافي")
        
        return len(reasons) == 0, reasons

    def calculate_safe_position_size(self, symbol, direction, current_price):
        """حساب حجم آمن بناءً على الرصيد الحقيقي"""
        try:
            self.update_real_time_balance()
            
            available_balance = self.real_time_balance['available_balance']
            
            if available_balance <= 0:
                logger.error(f"❌ الرصيد المتاح صفر أو سالب: ${available_balance:.2f}")
                return None
            
            risk_amount = available_balance * self.TRADING_SETTINGS['risk_per_trade']
            
            leverage = self.TRADING_SETTINGS['max_leverage'] if direction == 'LONG' else 3
            
            position_value = min(risk_amount * leverage, self.TRADING_SETTINGS['base_trade_size'] * leverage)
            
            total_risk = self.calculate_total_portfolio_risk()
            if total_risk + risk_amount > available_balance * self.TRADING_SETTINGS['max_portfolio_risk']:
                logger.warning(f"⚠️ تجاوز حد مخاطرة المحفظة")
                position_value *= 0.5
            
            quantity = position_value / current_price
            
            quantity = self.adjust_quantity(symbol, quantity)
            
            if quantity and quantity > 0:
                logger.info(f"💰 حجم الصفقة لـ {symbol}: {quantity:.6f} (قيمة: ${position_value:.2f})")
                return quantity
            
            return None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز الآمن لـ {symbol}: {e}")
            return None

    def calculate_total_portfolio_risk(self):
        """حساب إجمالي مخاطرة المحفظة الحالية"""
        try:
            total_risk = 0.0
            
            for symbol, trade in self.trade_manager.get_all_trades().items():
                position_value = trade['quantity'] * trade['entry_price']
                risk_per_trade = position_value / trade['leverage']
                total_risk += risk_per_trade
            
            return total_risk
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب مخاطرة المحفظة: {e}")
            return 0.0

    def adjust_quantity(self, symbol, quantity):
        """ضبط الكمية حسب متطلبات المنصة"""
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

    def set_margin_and_leverage(self, symbol, leverage):
        """تعيين الرافعة والهامش"""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تعيين الرافعة/الهامش: {e}")
            return False

    def final_balance_check(self, symbol, quantity, current_price, leverage):
        """تحقق نهائي من الرصيد قبل التنفيذ"""
        try:
            self.update_real_time_balance()
            
            required_margin = (quantity * current_price) / leverage
            available_balance = self.real_time_balance['available_balance']
            
            if required_margin > available_balance:
                logger.error(f"❌ رصيد غير كافي لـ {symbol}: مطلوب ${required_margin:.2f} | متاح ${available_balance:.2f}")
                return False
            
            logger.info(f"✅ تحقق الرصيد: ${required_margin:.2f} مطلوب | ${available_balance:.2f} متاح")
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحقق من الرصيد: {e}")
            return False

    def calculate_stop_loss_take_profit(self, symbol, direction, entry_price, signal):
        """حساب مستويات الوقف وجني الأرباح بناءً على التقلبات والإستراتيجية"""
        try:
            # ✅ جلب البيانات التاريخية لحساب التقلبات
            data = self.get_historical_data(symbol, '1h', 50)
            if data is None:
                # استخدام نسب ثابتة إذا فشل جلب البيانات
                return self._calculate_fixed_stop_levels(direction, entry_price)
            
            # ✅ حساب ATR (Average True Range) للتقلبات
            atr = self.calculate_atr(data)
            if atr == 0:
                atr = entry_price * 0.02  # قيمة افتراضية إذا كان ATR صفر
            
            # ✅ تحديد المستويات بناءً على اتجاه الصفقة
            if direction == 'LONG':
                # 🟢 صفقات الشراء
                stop_loss_distance = atr * 1.8  # وقف عند 1.8x ATR
                take_profit_distance = atr * 3.2  # جني عند 3.2x ATP
                
                stop_loss_price = entry_price - stop_loss_distance
                take_profit_price = entry_price + take_profit_distance
                
                # ✅ ضمان مستويات واقعية
                stop_loss_price = max(stop_loss_price, entry_price * 0.97)  # أقصى خسارة 3%
                take_profit_price = min(take_profit_price, entry_price * 1.06)  # أقصى ربح 6%
                
            else:
                # 🔴 صفقات البيع
                stop_loss_distance = atr * 1.8
                take_profit_distance = atr * 3.2
                
                stop_loss_price = entry_price + stop_loss_distance
                take_profit_price = entry_price - take_profit_distance
                
                # ✅ ضمان مستويات واقعية
                stop_loss_price = min(stop_loss_price, entry_price * 1.03)  # أقصى خسارة 3%
                take_profit_price = max(take_profit_price, entry_price * 0.94)  # أقصى ربح 6%
            
            # ✅ تعديل المستويات بناءً على ثقة الإشارة
            confidence = signal.get('confidence', 0.5)
            if confidence > 0.75:
                # زيادة جني الأرباح للإشارات عالية الثقة
                if direction == 'LONG':
                    take_profit_price = min(take_profit_price * 1.1, entry_price * 1.08)
                else:
                    take_profit_price = max(take_profit_price * 0.9, entry_price * 0.92)
            
            # ✅ تقريب الأسعار حسب متطلبات المنصة
            stop_loss_price = self.adjust_price_to_tick_size(symbol, stop_loss_price)
            take_profit_price = self.adjust_price_to_tick_size(symbol, take_profit_price)
            
            logger.info(f"📊 مستويات {symbol}: دخول ${entry_price:.4f} | وقف ${stop_loss_price:.4f} | جني ${take_profit_price:.4f}")
            
            return stop_loss_price, take_profit_price
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب مستويات الوقف لـ {symbol}: {e}")
            return self._calculate_fixed_stop_levels(direction, entry_price)

    def _calculate_fixed_stop_levels(self, direction, entry_price):
        """حساب مستويات وقف ثابتة كبديل"""
        if direction == 'LONG':
            stop_loss_price = entry_price * 0.98  # وقف 2%
            take_profit_price = entry_price * 1.04  # جني 4%
        else:
            stop_loss_price = entry_price * 1.02  # وقف 2%
            take_profit_price = entry_price * 0.96  # جني 4%
        
        logger.info(f"📊 استخدام مستويات وقف ثابتة: وقف {stop_loss_price:.4f} | جني {take_profit_price:.4f}")
        return stop_loss_price, take_profit_price

    def calculate_atr(self, data, period=14):
        """حساب Average True Range"""
        try:
            df = data.copy()
            high = df['high']
            low = df['low']
            close = df['close']
            
            # حساب True Range
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            
            true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = true_range.rolling(period).mean().iloc[-1]
            
            return atr if not pd.isna(atr) else 0
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب ATR: {e}")
            return 0

    def adjust_price_to_tick_size(self, symbol, price):
        """تقريب السعر حسب tick size المنصة"""
        try:
            exchange_info = self.client.futures_exchange_info()
            symbol_info = next((s for s in exchange_info['symbols'] if s['symbol'] == symbol), None)
            
            if symbol_info:
                price_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
                if price_filter:
                    tick_size = float(price_filter['tickSize'])
                    price = round(price / tick_size) * tick_size
            
            return round(price, 6)
            
        except Exception as e:
            logger.error(f"❌ خطأ في تقريب السعر: {e}")
            return round(price, 4)

    def place_stop_loss_order(self, symbol, direction, quantity, stop_price):
        """وضع أمر وقف الخسارة"""
        try:
            if direction == 'LONG':
                stop_side = 'SELL'
            else:
                stop_side = 'BUY'
            
            # تقريب السعر حسب متطلبات المنصة
            stop_price = self.adjust_price_to_tick_size(symbol, stop_price)
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=stop_side,
                type='STOP_MARKET',
                quantity=quantity,
                stopPrice=stop_price,
                reduceOnly=True,
                timeInForce='GTC'
            )
            
            logger.info(f"🛡️ تم وضع وقف خسارة لـ {symbol} عند ${stop_price:.4f}")
            return order
            
        except Exception as e:
            logger.error(f"❌ فشل وضع وقف خسارة لـ {symbol}: {e}")
            return None

    def place_take_profit_order(self, symbol, direction, quantity, take_profit_price):
        """وضع أمر جني الأرباح"""
        try:
            if direction == 'LONG':
                tp_side = 'SELL'
            else:
                tp_side = 'BUY'
            
            # تقريب السعر حسب متطلبات المنصة
            take_profit_price = self.adjust_price_to_tick_size(symbol, take_profit_price)
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=tp_side,
                type='TAKE_PROFIT_MARKET',
                quantity=quantity,
                stopPrice=take_profit_price,
                reduceOnly=True,
                timeInForce='GTC'
            )
            
            logger.info(f"🎯 تم وضع جني أرباح لـ {symbol} عند ${take_profit_price:.4f}")
            return order
            
        except Exception as e:
            logger.error(f"❌ فشل وضع جني أرباح لـ {symbol}: {e}")
            return None

    def sync_stop_orders(self):
        """مزامنة أوامر الوقف مع الصفقات النشطة"""
        try:
            active_trades = self.trade_manager.get_all_trades()
            
            for symbol, trade in active_trades.items():
                try:
                    open_orders = self.client.futures_get_open_orders(symbol=symbol)
                    
                    # البحث عن أوامر الوقف المرتبطة بالصفقة
                    has_stop_loss = any(order['type'] == 'STOP_MARKET' for order in open_orders)
                    has_take_profit = any(order['type'] == 'TAKE_PROFIT_MARKET' for order in open_orders)
                    
                    # إذا لم توجد أوامر وقف، إنشاؤها
                    if not has_stop_loss and trade.get('stop_loss_price'):
                        logger.info(f"🔄 إعادة وضع وقف خسارة لـ {symbol}")
                        self.place_stop_loss_order(
                            symbol, trade['side'], trade['quantity'], trade['stop_loss_price']
                        )
                    
                    if not has_take_profit and trade.get('take_profit_price'):
                        logger.info(f"🔄 إعادة وضع جني أرباح لـ {symbol}")
                        self.place_take_profit_order(
                            symbol, trade['side'], trade['quantity'], trade['take_profit_price']
                        )
                        
                except Exception as e:
                    logger.error(f"❌ خطأ في مزامنة أوامر الوقف لـ {symbol}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"❌ خطأ عام في مزامنة أوامر الوقف: {e}")

    def execute_trade(self, signal):
        """تنفيذ الصفقة مع أوامر وقف خسارة وجني أرباح"""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            
            # ✅ التحقق من إمكانية التداول أولاً
            can_trade, reasons = self.can_open_trade(symbol, direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي {symbol} {direction}: {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                logger.error(f"❌ لا يمكن الحصول على سعر {symbol}")
                return False
            
            # ✅ حساب حجم آمن بناءً على الرصيد الحقيقي
            quantity = self.calculate_safe_position_size(symbol, direction, current_price)
            if not quantity:
                logger.warning(f"⚠️ لا يمكن حساب حجم آمن لـ {symbol}")
                return False
            
            leverage = self.TRADING_SETTINGS['max_leverage'] if direction == 'LONG' else 3
            
            # ✅ التحقق النهائي من الرصيد قبل التنفيذ
            if not self.final_balance_check(symbol, quantity, current_price, leverage):
                return False
            
            # ✅ حساب مستويات الوقف وجني الأرباح
            stop_loss_price, take_profit_price = self.calculate_stop_loss_take_profit(
                symbol, direction, current_price, signal
            )
            
            if not stop_loss_price or not take_profit_price:
                logger.error(f"❌ فشل حساب مستويات الوقف لـ {symbol}")
                return False
            
            # ✅ تعيين الرافعة والهامش
            margin_set_success = self.set_margin_and_leverage(symbol, leverage)
            
            # ✅ تنفيذ الأمر الرئيسي
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            logger.info(f"🎯 تنفيذ صفقة {symbol}: {direction} | الكمية: {quantity:.6f} | السعر: ${current_price:.4f}")
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order['orderId']:
                # ✅ الحصول على سعر التنفيذ الفعلي
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                    if order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                        logger.info(f"✅ سعر التنفيذ الفعلي لـ {symbol}: ${executed_price:.4f}")
                except Exception as e:
                    logger.warning(f"⚠️ لا يمكن الحصول على سعر التنفيذ الفعلي: {e}")
                
                # ✅ تحديث مستويات الوقف بناءً على سعر التنفيذ الفعلي
                stop_loss_price, take_profit_price = self.calculate_stop_loss_take_profit(
                    symbol, direction, executed_price, signal
                )
                
                # ✅ وضع أوامر الوقف وجني الأرباح
                stop_loss_order = None
                take_profit_order = None
                
                try:
                    stop_loss_order = self.place_stop_loss_order(symbol, direction, quantity, stop_loss_price)
                    time.sleep(0.5)  # انتظار بسيط بين الأوامر
                    
                    take_profit_order = self.place_take_profit_order(symbol, direction, quantity, take_profit_price)
                    time.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"❌ فشل وضع أوامر الوقف لـ {symbol}: {e}")
                    # محاولة وضع الأوامر مرة أخرى
                    try:
                        if not stop_loss_order:
                            stop_loss_order = self.place_stop_loss_order(symbol, direction, quantity, stop_loss_price)
                        if not take_profit_order:
                            take_profit_order = self.place_take_profit_order(symbol, direction, quantity, take_profit_price)
                    except Exception as retry_e:
                        logger.error(f"❌ فشل إعادة وضع أوامر الوقف لـ {symbol}: {retry_e}")
                
                # ✅ تسجيل الصفقة
                trade_data = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'entry_price': executed_price,
                    'side': direction,
                    'leverage': leverage,
                    'timestamp': datetime.now(damascus_tz),
                    'status': 'open',
                    'order_id': order['orderId'],
                    'signal_confidence': signal['confidence'],
                    'phase_analysis': signal['phase_analysis'],
                    'margin_set_success': margin_set_success,
                    'position_value': quantity * executed_price,
                    # ✅ معلومات الوقف الجديدة
                    'stop_loss_price': stop_loss_price,
                    'take_profit_price': take_profit_price,
                    'stop_loss_order_id': stop_loss_order['orderId'] if stop_loss_order else None,
                    'take_profit_order_id': take_profit_order['orderId'] if take_profit_order else None,
                    'initial_risk': abs(executed_price - stop_loss_price) / executed_price * 100,
                    'reward_ratio': abs(take_profit_price - executed_price) / abs(executed_price - stop_loss_price)
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                
                # ✅ تحديث الرصيد المحلي
                trade_cost = (quantity * executed_price) / leverage
                self.symbol_balances[symbol] = max(0, self.symbol_balances[symbol] - trade_cost)
                
                # ✅ إرسال إشعار مفصل
                if self.notifier:
                    current_balance = self.real_time_balance['available_balance']
                    risk_reward_ratio = trade_data['reward_ratio']
                    risk_percentage = trade_data['initial_risk']
                    
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>تم فتح صفقة جديدة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"سعر الدخول: ${executed_price:.4f}\n"
                        f"القيمة: ${quantity * executed_price:.2f}\n"
                        f"الرافعة: {leverage}x\n"
                        f"🛡️ وقف الخسارة: ${stop_loss_price:.4f}\n"
                        f"🎯 جني الأرباح: ${take_profit_price:.4f}\n"
                        f"📊 نسبة المخاطرة: {risk_percentage:.1f}%\n"
                        f"⚖️ نسبة المكافأة: {risk_reward_ratio:.1f}:1\n"
                        f"الرصيد المتاح: ${current_balance:.2f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"المرحلة: {signal['phase_analysis']['phase']}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol} بنجاح")
                logger.info(f"📊 تفاصيل الصفقة: وقف ${stop_loss_price:.4f} | جني ${take_profit_price:.4f} | نسبة {risk_reward_ratio:.1f}:1")
                
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            return False

    def close_trade(self, symbol, reason="إغلاق طبيعي"):
        """إغلاق الصفقة"""
        try:
            trade = self.trade_manager.get_trade(symbol)
            if not trade:
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False
            
            # ✅ إلغاء أوامر الوقف أولاً
            try:
                open_orders = self.client.futures_get_open_orders(symbol=symbol)
                for order in open_orders:
                    if order['type'] in ['STOP_MARKET', 'TAKE_PROFIT_MARKET']:
                        self.client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                        logger.info(f"✅ تم إلغاء أمر وقف لـ {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ لا يمكن إلغاء أوامر الوقف لـ {symbol}: {e}")
            
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
                    pnl_percentage = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_percentage = (entry_price - current_price) / entry_price * 100
                
                self.performance_stats['trades_closed'] += 1
                if pnl_percentage > 0:
                    self.performance_stats['winning_trades'] += 1
                else:
                    self.performance_stats['losing_trades'] += 1
                
                trade_cost = (quantity * entry_price) / trade['leverage']
                self.symbol_balances[symbol] += trade_cost
                
                if self.notifier:
                    pnl_emoji = "🟢" if pnl_percentage > 0 else "🔴"
                    message = (
                        f"🔒 <b>إغلاق صفقة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {trade['side']}\n"
                        f"الربح/الخسارة: {pnl_emoji} {pnl_percentage:+.2f}%\n"
                        f"السبب: {reason}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                self.trade_manager.remove_trade(symbol)
                logger.info(f"✅ تم إغلاق صفقة {symbol} - الربح/الخسارة: {pnl_percentage:+.2f}%")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ فشل إغلاق صفقة {symbol}: {e}")
            return False

    def scan_market(self):
        """مسح السوق للعثور على فرص التداول"""
        logger.info("🔍 بدء مسح السوق...")
        
        opportunities = []
        
        for symbol in self.TRADING_SETTINGS['symbols']:
            try:
                if self.trade_manager.is_symbol_trading(symbol):
                    continue
                
                data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'])
                if data is None or len(data) < 50:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                signal = self.signal_generator.generate_signal(symbol, data, current_price)
                if signal and signal['confidence'] >= self.TRADING_SETTINGS['min_signal_confidence']:
                    opportunities.append(signal)
                    
                    if self.notifier:
                        self.notifier.send_trade_alert(symbol, signal, current_price, signal['phase_analysis'])
                
            except Exception as e:
                logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
                continue
        
        opportunities.sort(key=lambda x: x['confidence'], reverse=True)
        
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة تداول")
        return opportunities

    def execute_trading_cycle(self):
        """تنفيذ دورة التداول الكاملة"""
        try:
            opportunities = self.scan_market()
            
            executed_trades = 0
            for signal in opportunities:
                if executed_trades >= 2:
                    break
                
                if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
                    break
                
                if self.execute_trade(signal):
                    executed_trades += 1
                    time.sleep(2)
            
            logger.info(f"✅ اكتملت الدورة - تم تنفيذ {executed_trades} صفقة")
            
        except Exception as e:
            logger.error(f"❌ خطأ في دورة التداول: {e}")

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
                'phase': trade.get('phase_analysis', {}).get('phase', 'غير محدد'),
                'stop_loss': trade.get('stop_loss_price'),
                'take_profit': trade.get('take_profit_price')
            }
            for trade in trades.values()
        ]

    def get_market_analysis(self, symbol):
        """الحصول على تحليل السوق لرمز معين"""
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
        """تشغيل البوت الرئيسي"""
        logger.info("🚀 بدء تشغيل البوت المتقدم...")
        
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        try:
            while True:
                try:
                    schedule.run_pending()
                    self.execute_trading_cycle()
                    
                    wait_time = self.TRADING_SETTINGS['rescan_interval_minutes'] * 60
                    logger.info(f"⏳ انتظار {wait_time} ثانية للدورة القادمة...")
                    time.sleep(wait_time)
                    
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
    """الدالة الرئيسية"""
    try:
        bot = AdvancedTradingBot()
        bot.run()
    except Exception as e:
        logger.error(f"❌ فشل تشغيل البوت: {e}")

if __name__ == "__main__":
    main()
