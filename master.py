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
    """مولد إشارات تداول متقدم"""
    
    def __init__(self, phase_analyzer):
        self.phase_analyzer = phase_analyzer
    
    def generate_signal(self, symbol, data, current_price):
        """توليد إشارة تداول متكاملة"""
        try:
            if len(data) < 50:
                return None
            
            # تحليل مرحلة السوق
            phase_analysis = self.phase_analyzer.analyze_phase(data)
            
            # التحليل الفني
            technical_analysis = self._technical_analysis(data, current_price)
            
            # تحليل القوة
            strength_analysis = self._strength_analysis(data)
            
            # توليد الإشارات
            long_signal = self._long_signal(technical_analysis, strength_analysis, phase_analysis)
            short_signal = self._short_signal(technical_analysis, strength_analysis, phase_analysis)
            
            # اختيار أفضل إشارة
            return self._select_signal(symbol, long_signal, short_signal, phase_analysis)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد الإشارة لـ {symbol}: {e}")
            return None
    
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
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # الزخم
        df['momentum'] = df['close'].pct_change(5)
        
        # الحجم
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        latest = df.iloc[-1]
        
        return {
            'sma10': latest['sma10'],
            'sma20': latest['sma20'], 
            'sma50': latest['sma50'],
            'rsi': latest['rsi'],
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'momentum': latest['momentum'],
            'volume_ratio': latest['volume_ratio'],
            'price_vs_sma20': (current_price - latest['sma20']) / latest['sma20'] * 100,
            'trend_strength': (latest['sma10'] - latest['sma50']) / latest['sma50'] * 100
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
        trend_strength = abs(df['close'].iloc[-1] - df['close'].rolling(20).mean().iloc[-1]) / df['close'].rolling(20).std().iloc[-1]
        volume_strength = df['volume'].iloc[-1] / df['volume'].rolling(20).mean().iloc[-1]
        
        return {
            'volatility': volatility,
            'trend_strength': trend_strength,
            'volume_strength': volume_strength
        }
    
    def _long_signal(self, technical, strength, phase_analysis):
        """إشارة الشراء"""
        conditions = [
            technical['sma10'] > technical['sma20'] > technical['sma50'],
            technical['rsi'] > 45 and technical['rsi'] < 70,
            technical['macd'] > technical['macd_signal'],
            technical['momentum'] > 0.001,
            technical['volume_ratio'] > 0.8,
            technical['trend_strength'] > 0.5,
            phase_analysis['phase'] in ['تجميع', 'صعود'],
            phase_analysis['confidence'] > 0.6
        ]
        
        weights = [2.0, 1.5, 1.5, 1.3, 1.0, 1.2, 2.0, 1.8]
        score = sum(cond * weight for cond, weight in zip(conditions, weights))
        
        return {
            'direction': 'LONG',
            'score': score,
            'confidence': score / sum(weights),
            'conditions_met': sum(conditions)
        }
    
    def _short_signal(self, technical, strength, phase_analysis):
        """إشارة البيع"""
        conditions = [
            technical['sma10'] < technical['sma20'] < technical['sma50'],
            technical['rsi'] < 55 and technical['rsi'] > 30,
            technical['macd'] < technical['macd_signal'],
            technical['momentum'] < -0.001,
            technical['volume_ratio'] > 0.8,
            technical['trend_strength'] < -0.5,
            phase_analysis['phase'] in ['توزيع', 'هبوط'],
            phase_analysis['confidence'] > 0.6
        ]
        
        weights = [2.0, 1.5, 1.5, 1.3, 1.0, 1.2, 2.0, 1.8]
        score = sum(cond * weight for cond, weight in zip(conditions, weights))
        
        return {
            'direction': 'SHORT', 
            'score': score,
            'confidence': score / sum(weights),
            'conditions_met': sum(conditions)
        }
    
    def _select_signal(self, symbol, long_signal, short_signal, phase_analysis):
        """اختيار أفضل إشارة"""
        min_confidence = 0.65
        min_conditions = 5
        
        valid_signals = []
        
        if (long_signal['confidence'] >= min_confidence and 
            long_signal['conditions_met'] >= min_conditions):
            valid_signals.append(long_signal)
            
        if (short_signal['confidence'] >= min_confidence and 
            short_signal['conditions_met'] >= min_conditions):
            valid_signals.append(short_signal)
        
        if not valid_signals:
            return None
        
        best_signal = max(valid_signals, key=lambda x: x['confidence'])
        
        return {
            'symbol': symbol,
            'direction': best_signal['direction'],
            'confidence': best_signal['confidence'],
            'score': best_signal['score'],
            'phase_analysis': phase_analysis,
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
    
    # إعدادات التداول
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
        'total_capital': 100
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
            self.test_connection()
        except Exception as e:
            logger.error(f"❌ فشل تهيئة العميل: {e}")
            raise
        
        # تهيئة المكونات
        self.phase_analyzer = MarketPhaseAnalyzer()
        self.signal_generator = AdvancedSignalGenerator(self.phase_analyzer)
        self.notifier = TelegramNotifier(self.telegram_token, self.telegram_chat_id)
        self.trade_manager = TradeManager(self.client, self.notifier)
        
        # إدارة الرصيد
        self.symbol_balances = self._initialize_balances()
        self.performance_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0
        }
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self.start_services()
        self.send_startup_message()
        
        AdvancedTradingBot._instance = self
        logger.info("✅ تم تهيئة البوت المتقدم بنجاح")
    
    def _initialize_balances(self):
        """تهيئة أرصدة الرموز"""
        total_symbols = len(self.TRADING_SETTINGS['symbols'])
        base_allocation = self.TRADING_SETTINGS['total_capital'] / total_symbols
        
        return {symbol: base_allocation for symbol in self.TRADING_SETTINGS['symbols']}
    
    def test_connection(self):
        """اختبار اتصال API"""
        try:
            self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise
    
    def start_services(self):
        """بدء الخدمات المساعدة"""
        # خدمة المزامنة
        def sync_thread():
            while True:
                try:
                    self.trade_manager.sync_with_exchange()
                    time.sleep(60)
                except Exception as e:
                    logger.error(f"❌ خطأ في المزامنة: {e}")
                    time.sleep(30)
        
        threading.Thread(target=sync_thread, daemon=True).start()
        
        # خدمة التقارير
        if self.notifier:
            schedule.every(4).hours.do(self.send_performance_report)
            schedule.every(1).hours.do(self.send_heartbeat)
    
    def send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            message = (
                "🚀 <b>بدء تشغيل البوت المتقدم</b>\n"
                f"الوقت: {datetime.now(damascus_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"الأصول: {len(self.TRADING_SETTINGS['symbols'])}\n"
                f"رأس المال: ${self.TRADING_SETTINGS['total_capital']}\n"
                f"الصفقات القصوى: {self.TRADING_SETTINGS['max_active_trades']}\n"
                f"📊 <b>الإستراتيجية:</b> تحليل المراحل + الإشارات المتقدمة"
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
            f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
        )
        self.notifier.send_message(message)
    
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
        
        # التحقق من الحد الأقصى للصفقات
        if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
            reasons.append("الحد الأقصى للصفقات")
        
        # التحقق من صفقات البيع
        if direction == 'SHORT':
            active_shorts = sum(1 for trade in self.trade_manager.get_all_trades().values() 
                              if trade['side'] == 'SHORT')
            if active_shorts >= self.TRADING_SETTINGS['max_short_trades']:
                reasons.append("الحد الأقصى لصفقات البيع")
        
        # التحقق من الصفقات النشطة على الرمز
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append("صفقة نشطة على الرمز")
        
        # التحقق من الرصيد
        available_balance = self.symbol_balances.get(symbol, 0)
        if available_balance < 5:
            reasons.append("رصيد غير كافي")
        
        return len(reasons) == 0, reasons
    
    def calculate_position_size(self, symbol, direction, current_price):
        """حساب حجم المركز"""
        try:
            available_balance = self.symbol_balances.get(symbol, self.TRADING_SETTINGS['base_trade_size'])
            
            # استخدام رافعة أقل للبيع
            leverage = self.TRADING_SETTINGS['max_leverage']
            if direction == 'SHORT':
                leverage = min(leverage, 3)  # حد أقصى 3x للبيع
            
            position_value = min(available_balance * leverage, self.TRADING_SETTINGS['base_trade_size'])
            quantity = position_value / current_price
            
            # تقريب الكمية
            quantity = self.adjust_quantity(symbol, quantity)
            
            return quantity if quantity and quantity > 0 else None
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return None
    
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
    
    def execute_trade(self, signal):
        """تنفيذ الصفقة"""
        try:
            symbol = signal['symbol']
            direction = signal['direction']
            
            # التحقق من إمكانية التداول
            can_trade, reasons = self.can_open_trade(symbol, direction)
            if not can_trade:
                logger.info(f"⏭️ تخطي {symbol} {direction}: {', '.join(reasons)}")
                return False
            
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False
            
            # حساب حجم المركز
            quantity = self.calculate_position_size(symbol, direction, current_price)
            if not quantity:
                return False
            
            # تعيين الرافعة
            leverage = self.TRADING_SETTINGS['max_leverage'] if direction == 'LONG' else 3
            try:
                self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
                self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
            except Exception as e:
                logger.warning(f"⚠️ خطأ في تعيين الرافعة: {e}")
            
            # تنفيذ الأمر
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            if order and order['orderId']:
                # الحصول على سعر التنفيذ
                executed_price = current_price
                try:
                    order_info = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                    if order_info.get('avgPrice'):
                        executed_price = float(order_info['avgPrice'])
                except:
                    pass
                
                # تسجيل الصفقة
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
                    'phase_analysis': signal['phase_analysis']
                }
                
                self.trade_manager.add_trade(symbol, trade_data)
                self.performance_stats['trades_opened'] += 1
                
                # تحديث الرصيد
                trade_cost = (quantity * executed_price) / leverage
                self.symbol_balances[symbol] = max(0, self.symbol_balances[symbol] - trade_cost)
                
                # إرسال إشعار
                if self.notifier:
                    direction_emoji = "🟢" if direction == 'LONG' else "🔴"
                    message = (
                        f"{direction_emoji} <b>تم فتح صفقة جديدة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"الكمية: {quantity:.4f}\n"
                        f"السعر: ${executed_price:.4f}\n"
                        f"الرافعة: {leverage}x\n"
                        f"الثقة: {signal['confidence']:.2%}\n"
                        f"المرحلة: {signal['phase_analysis']['phase']}\n"
                        f"الوقت: {datetime.now(damascus_tz).strftime('%H:%M:%S')}"
                    )
                    self.notifier.send_message(message)
                
                logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol}")
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
            
            # تحديد اتجاه الإغلاق
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
                # حساب الربح/الخسارة
                entry_price = trade['entry_price']
                if trade['side'] == 'LONG':
                    pnl_percentage = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_percentage = (entry_price - current_price) / entry_price * 100
                
                # تحديث الإحصائيات
                self.performance_stats['trades_closed'] += 1
                if pnl_percentage > 0:
                    self.performance_stats['winning_trades'] += 1
                else:
                    self.performance_stats['losing_trades'] += 1
                
                # استعادة الرصيد
                trade_cost = (quantity * entry_price) / trade['leverage']
                self.symbol_balances[symbol] += trade_cost
                
                # إرسال إشعار
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
                # تخطي الرموز ذات الصفقات النشطة
                if self.trade_manager.is_symbol_trading(symbol):
                    continue
                
                # جلب البيانات وتحليلها
                data = self.get_historical_data(symbol, self.TRADING_SETTINGS['data_interval'])
                if data is None or len(data) < 50:
                    continue
                
                current_price = self.get_current_price(symbol)
                if not current_price:
                    continue
                
                # توليد الإشارة
                signal = self.signal_generator.generate_signal(symbol, data, current_price)
                if signal and signal['confidence'] >= self.TRADING_SETTINGS['min_signal_confidence']:
                    opportunities.append(signal)
                    
                    # إرسال إشعار بالإشارة
                    if self.notifier:
                        self.notifier.send_trade_alert(symbol, signal, current_price, signal['phase_analysis'])
                
            except Exception as e:
                logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
                continue
        
        # ترتيب الفرص حسب الثقة
        opportunities.sort(key=lambda x: x['confidence'], reverse=True)
        
        logger.info(f"🎯 تم العثور على {len(opportunities)} فرصة تداول")
        return opportunities
    
    def execute_trading_cycle(self):
        """تنفيذ دورة التداول الكاملة"""
        try:
            # مسح السوق
            opportunities = self.scan_market()
            
            # تنفيذ أفضل الفرص
            for signal in opportunities[:2]:  # تنفيذ أفضل فرصتين فقط
                if self.trade_manager.get_active_trades_count() >= self.TRADING_SETTINGS['max_active_trades']:
                    break
                
                if self.execute_trade(signal):
                    time.sleep(2)  # انتظار بين الصفقات
            
            logger.info("✅ اكتملت دورة التداول")
            
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
        
        # بدء خادم Flask
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        try:
            while True:
                try:
                    # تشغيل المهام المجدولة
                    schedule.run_pending()
                    
                    # تنفيذ دورة التداول
                    self.execute_trading_cycle()
                    
                    # انتظار حتى الدورة القادمة
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
