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
            'BTCUSDT': {'name': 'Bitcoin', 'symbol': 'BTC'},
            'ETHUSDT': {'name': 'Ethereum', 'symbol': 'ETH'},
            'BNBUSDT': {'name': 'Binance Coin', 'symbol': 'BNB'},
            'SOLUSDT': {'name': 'Solana', 'symbol': 'SOL'},
            'ADAUSDT': {'name': 'Cardano', 'symbol': 'ADA'},
            'XRPUSDT': {'name': 'XRP', 'symbol': 'XRP'},
            'DOTUSDT': {'name': 'Polkadot', 'symbol': 'DOT'},
            'LINKUSDT': {'name': 'Chainlink', 'symbol': 'LINK'}
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
    """مولد إشارات تداول متقدم مع شروط شراء مشددة وبيع مخفف"""
    
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
            short_signal = self._relaxed_short_signal(technical_analysis, strength_analysis, phase_analysis)
            
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
            'strict_conditions': True  # 🎯 إشارة على أن الشروط مشددة
        }
    
    def _relaxed_short_signal(self, technical, strength, phase_analysis):
        """إشارة بيع بشروط مخففة"""
        # 🎯 شروط بيع مخففة
        relaxed_sell_conditions = [
            # 📉 شروط اتجاه مخففة
            technical['sma10'] < technical['sma20'],  # لا يشترط ترتيب كامل
            technical['ema12'] < technical['ema26'],
            technical['close'] < technical['sma20'] * 1.02,  # مسموح أن يكون قريب من المتوسط
            
            # 📉 شروط زخم مخففة
            technical['rsi'] < 58 and technical['rsi'] > 25,  # نطاق أوسع
            technical['momentum'] < -0.001,  # زخم سلبي طفيف
            technical['macd'] < technical['macd_signal'] * 1.01,  # MACD سلبي طفيف
            
            # 📉 شروط حجم مخففة
            technical['volume_ratio'] > 0.7,  # حجم مقبول (ليس بالضرورة عالي)
            technical['trend_strength'] < -0.3,  # اتجاه هابط طفيف
            strength['volume_strength'] > 0.6,
            
            # 📉 شروط مرحلة السوق مخففة
            phase_analysis['phase'] in ['توزيع', 'هبوط', 'تجميع'],  # مراحل متعددة مسموحة
            phase_analysis['confidence'] > 0.5,  # ثقة متوسطة
            
            # 📉 شروط إضافية مخففة
            technical['price_vs_sma20'] < 2.0,  # مسموح انحراف أكبر
            strength['volatility'] < 5.0,  # تقلبات أعلى مسموحة
        ]
        
        # 🎯 نظام ترجيح مخفف للبيع
        relaxed_weights = [
            2.0,  # اتجاه هابط
            1.8,  # EMA
            1.5,  # تحت المتوسط
            1.8,  # RSI مخفف
            1.6,  # زخم سلبي
            1.5,  # MACD سلبي
            1.0,  # حجم مقبول
            1.5,  # اتجاه هابط طفيف
            0.8,  # قوة حجم
            2.0,  # مراحل متعددة
            1.5,  # ثقة متوسطة
            1.0,  # انحراف مسموح
            0.8,  # تقلبات مسموحة
        ]
        
        signal_score = sum(cond * weight for cond, weight in zip(relaxed_sell_conditions, relaxed_weights))
        max_score = sum(relaxed_weights)
        
        return {
            'direction': 'SHORT',
            'score': signal_score,
            'confidence': signal_score / max_score,
            'conditions_met': sum(relaxed_sell_conditions),
            'total_conditions': len(relaxed_sell_conditions),
            'relaxed_conditions': True  # 🎯 إشارة على أن الشروط مخففة
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
        """اختيار أفضل إشارة مع عتبات مخصصة"""
        # 🎯 عتبات مختلفة للشراء والبيع
        min_long_confidence = 0.72      # 🔒 عتبة عالية للشراء
        min_short_confidence = 0.60     # 📉 عتبة منخفضة للبيع
        min_long_conditions = 9         # 🔒 شروط أكثر للشراء
        min_short_conditions = 7        # 📉 شروط أقل للبيع
        
        valid_signals = []
        
        # 🔒 التحقق من إشارة الشراء (بشروط مشددة)
        if (long_signal['confidence'] >= min_long_confidence and 
            long_signal['conditions_met'] >= min_long_conditions):
            valid_signals.append(long_signal)
            
        # 📉 التحقق من إشارة البيع (بشروط مخففة)
        if (short_signal['confidence'] >= min_short_confidence and 
            short_signal['conditions_met'] >= min_short_conditions):
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
            'strict_conditions': best_signal.get('strict_conditions', False),
            'relaxed_conditions': best_signal.get('relaxed_conditions', False)
        }
        
        # 📊 تسجيل معلومات الإشارة
        logger.info(f"🎯 إشارة {symbol}: {best_signal['direction']} "
                   f"(ثقة: {best_signal['confidence']:.2%}, "
                   f"شروط: {best_signal['conditions_met']}/{best_signal['total_conditions']}, "
                   f"نوع: {'مشددة' if best_signal.get('strict_conditions') else 'مخففة'})")
        
        return signal_info
    
    def get_signal_stats(self, symbol, technical, phase_analysis):
        """الحصول على إحصائيات الإشارة للمراقبة"""
        long_signal = self._strict_long_signal(technical, self._strength_analysis(pd.DataFrame([technical])), phase_analysis)
        short_signal = self._relaxed_short_signal(technical, self._strength_analysis(pd.DataFrame([technical])), phase_analysis)
        
        return {
            'symbol': symbol,
            'long_confidence': long_signal['confidence'],
            'short_confidence': short_signal['confidence'],
            'long_conditions': f"{long_signal['conditions_met']}/{long_signal['total_conditions']}",
            'short_conditions': f"{short_signal['conditions_met']}/{short_signal['total_conditions']}",
            'long_meets_threshold': long_signal['confidence'] >= 0.72 and long_signal['conditions_met'] >= 9,
            'short_meets_threshold': short_signal['confidence'] >= 0.60 and short_signal['conditions_met'] >= 7,
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

class AdvancedTradingBot:
    _instance = None
    
    TRADING_SETTINGS = {
        'symbols': ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOTUSDT", "LINKUSDT"],
        'base_trade_size': 15,
        'max_leverage': 5,
        'max_active_trades': 4,
        'data_interval': '30m',
        'rescan_interval_minutes': 15,
        'min_signal_confidence': 0.65,
        'short_trading_enabled': True,
        'max_short_trades': 2,
        'risk_per_trade': 0.15,
        'max_portfolio_risk': 0.40,
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
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(30)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        if self.notifier:
            schedule.every(4).hours.do(self.send_performance_report)
            schedule.every(2).hours.do(self.send_balance_report)
            schedule.every(1).hours.do(self.send_heartbeat)

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
                f"📊 <b>الإستراتيجية:</b> تحليل المراحل + الرصيد الحقيقي"
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

    def execute_trade(self, signal):
        """تنفيذ الصفقة مع الرصيد الحقيقي"""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            
            can_trade, reasons = self.can_open_trade(symbol, direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي {symbol} {direction}: {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False
            
            quantity = self.calculate_safe_position_size(symbol, direction, current_price)
            if not quantity:
                return False
            
            leverage = self.TRADING_SETTINGS['max_leverage'] if direction == 'LONG' else 3
            
            if not self.final_balance_check(symbol, quantity, current_price, leverage):
                return False
            
            margin_set_success = self.set_margin_and_leverage(symbol, leverage)
            
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
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
                    'position_value': quantity * executed_price
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                
                trade_cost = (quantity * executed_price) / leverage
                self.symbol_balances[symbol] = max(0, self.symbol_balances[symbol] - trade_cost)
                
                if self.notifier:
                    current_balance = self.real_time_balance['available_balance']
                    message = (
                        f"{'🟢' if direction == 'LONG' else '🔴'} <b>تم فتح صفقة جديدة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.6f}\n"
                        f"السعر: ${executed_price:.4f}\n"
                        f"القيمة: ${quantity * executed_price:.2f}\n"
                        f"الرافعة: {leverage}x\n"
                        f"الرصيد المتاح: ${current_balance:.2f}\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol} بالرصيد الحقيقي")
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
                'phase': trade.get('phase_analysis', {}).get('phase', 'غير محدد')
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
