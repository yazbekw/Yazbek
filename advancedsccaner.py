from fastapi import FastAPI, HTTPException
import httpx
import asyncio
import os
import time
import math
from datetime import datetime, timedelta
import logging
from typing import Dict, Any, List, Tuple, Optional
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
import base64
from logging.handlers import RotatingFileHandler
import pytz

# =============================================================================
# الإعدادات الرئيسية - يمكن تعديلها بسهولة
# =============================================================================

# إعدادات التطبيق
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PORT = int(os.getenv("PORT", 8000))

# إعدادات البوت المنفذ
EXECUTOR_BOT_URL = os.getenv("EXECUTOR_BOT_URL", "https://your-executor-bot.onrender.com")
EXECUTOR_BOT_API_KEY = os.getenv("EXECUTOR_BOT_API_KEY", "")
EXECUTE_TRADES = os.getenv("EXECUTE_TRADES", "false").lower() == "true"

# إعدادات التداول
SCAN_INTERVAL = 1800  # 30 دقيقة بين كل فحص (بالثواني)
HEARTBEAT_INTERVAL = 1800  # 30 دقيقة بين كل نبضة (بالثواني)
EXECUTOR_HEARTBEAT_INTERVAL = 3600  # ساعة بين كل نبضة للمنفذ (بالثواني)
CONFIDENCE_THRESHOLD = 60  # الحد الأدنى للنقاط لإرسال الإشعار

# 🔧 نظام المؤشرات الجديد - قابل للتعديل
ENABLE_BCMI = True  # تفعيل/إلغاء مؤشر BCMI
ENABLE_DIVERGENCE = True  # تفعيل/إلغاء كشف التباعد
ENABLE_CONFIRMATION_SYSTEM = True  # تفعيل/إلغاء نظام تأكيد الإطار

# أوزان المؤشرات القابلة للتعديل (المجموع = 100)
INDICATOR_WEIGHTS = {
    "MOMENTUM": 25,           # RSI + Stochastic + MACD
    "PRICE_ACTION": 25,       # أنماط الشموع + اختراق المتوسطات
    "KEY_LEVELS": 20,         # الدعم/المقاومة + فيبوناتشي
    "VOLUME_CONFIRMATION": 20, # تحليل الحجم
    "BLOCKCHAIN_HEALTH": 5,   # BCMI (إذا مفعل)
    "DIVERGENCE_SIGNALS": 5   # التباعد (إذا مفعل)
}

# إعدادات نظام التأكيد
PRIMARY_TIMEFRAME = '1h'           # الإطار الرئيسي
CONFIRMATION_TIMEFRAME = '15m'     # إطار التأكيد
CONFIRMATION_THRESHOLD = 40        # الحد الأدنى لنقاط التأكيد
CONFIRMATION_BONUS = 5            # نقاط المكافأة للتأكيد

# أوزان BCMI الداخلية
BCMI_WEIGHTS = {
    'MVRV': 0.25,
    'SOPR': 0.25, 
    'SENTIMENT': 0.25,
    'MOMENTUM': 0.25
}

# الأصول والأطر الزمنية
SUPPORTED_COINS = {
    'eth': {'name': 'Ethereum', 'binance_symbol': 'ETHUSDT', 'symbol': 'ETH'},
    'bnb': {'name': 'Binance Coin', 'binance_symbol': 'BNBUSDT', 'symbol': 'BNB'},
    #'dot': {'name': 'Polkadot', 'binance_symbol': 'DOTUSDT', 'symbol': 'DOT'},
    #'link': {'name': 'Chainlink', 'binance_symbol': 'LINKUSDT', 'symbol': 'LINK'},
}

TIMEFRAMES = ['1h', '15m']

# توقيت سوريا (GMT+3)
SYRIA_TZ = pytz.timezone('Asia/Damascus')

# أوقات الجلسات مع التوقيت السوري
TRADING_SESSIONS = {
    "asian": {"start": 0, "end": 8, "weight": 0.7, "name": "آسيوية", "emoji": "🌏"},
    "european": {"start": 8, "end": 16, "weight": 1.0, "name": "أوروبية", "emoji": "🌍"}, 
    "american": {"start": 16, "end": 24, "weight": 0.8, "name": "أمريكية", "emoji": "🌎"}
}

# مستويات التنبيه المحدثة
ALERT_LEVELS = {
    "LOW": {"min": 0, "max": 40, "emoji": "⚪", "send_alert": False, "color": "gray"},
    "MEDIUM": {"min": 41, "max": 49, "emoji": "🟡", "send_alert": True, "color": "gold"},
    "HIGH": {"min": 60, "max": 70, "emoji": "🟠", "send_alert": True, "color": "darkorange"},
    "STRONG": {"min": 71, "max": 80, "emoji": "🔴", "send_alert": True, "color": "red"},
    "EXTREME": {"min": 81, "max": 100, "emoji": "💥", "send_alert": True, "color": "darkred"}
}

# ألوان التصميم
COLORS = {
    "top": {"primary": "#FF4444", "secondary": "#FFCCCB", "bg": "#FFF5F5"},
    "bottom": {"primary": "#00C851", "secondary": "#C8F7C5", "bg": "#F5FFF5"},
    "neutral": {"primary": "#4A90E2", "secondary": "#D1E8FF", "bg": "#F5F9FF"}
}

# =============================================================================
# نهاية الإعدادات الرئيسية
# =============================================================================

# إعداد التسجيل
logger = logging.getLogger("crypto_scanner")
logger.setLevel(logging.INFO)

for handler in logger.handlers[:]:
    logger.removeHandler(handler)

console_handler = logging.StreamHandler()
console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

try:
    file_handler = RotatingFileHandler("scanner.log", maxBytes=5*1024*1024, backupCount=3)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
except Exception as e:
    print(f"تعذر إنشاء ملف التسجيل: {e}")

logger.propagate = False
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

app = FastAPI(title="Crypto Top/Bottom Scanner", version="3.0")

# إحصائيات النظام
system_stats = {
    "start_time": time.time(),
    "total_scans": 0,
    "total_alerts_sent": 0,
    "total_signals_sent": 0,
    "total_heartbeats_sent": 0,
    "last_heartbeat": None,
    "last_executor_heartbeat": None,
    "last_scan_time": None,
    "executor_connected": False,
    "performance_metrics": {
        "successful_signals": 0,
        "failed_signals": 0,
        "indicator_performance": {}
    }
}

def safe_log_info(message: str, coin: str = "system", source: str = "app"):
    try:
        logger.info(f"{message} - Coin: {coin} - Source: {source}")
    except Exception as e:
        print(f"خطأ في التسجيل: {e} - الرسالة: {message}")

def safe_log_error(message: str, coin: str = "system", source: str = "app"):
    try:
        logger.error(f"{message} - Coin: {coin} - Source: {source}")
    except Exception as e:
        print(f"خطأ في تسجيل الخطأ: {e} - الرسالة: {message}")

def get_syria_time():
    """الحصول على التوقيت السوري الحالي"""
    return datetime.now(SYRIA_TZ)

def get_current_session():
    """الحصول على الجلسة الحالية حسب التوقيت السوري"""
    current_time = get_syria_time()
    current_hour = current_time.hour
    
    for session, config in TRADING_SESSIONS.items():
        if config["start"] <= current_hour < config["end"]:
            return config
    
    return TRADING_SESSIONS["asian"]

def get_session_weight():
    """الحصول على وزن الجلسة الحالية حسب التوقيت السوري"""
    return get_current_session()["weight"]

def get_alert_level(score: int) -> Dict[str, Any]:
    """تحديد مستوى التنبيه بناء على النقاط"""
    for level, config in ALERT_LEVELS.items():
        if config["min"] <= score <= config["max"]:
            return {
                "level": level,
                "emoji": config["emoji"],
                "send_alert": config["send_alert"],
                "color": config["color"],
                "min": config["min"],
                "max": config["max"]
            }
    return ALERT_LEVELS["LOW"]

class AdvancedMarketAnalyzer:
    """محلل متقدم للقمم والقيعان - النسخة المحسنة"""
    
    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        """حساب RSI"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gains = pd.Series(gains).rolling(period).mean().dropna().values
        avg_losses = pd.Series(losses).rolling(period).mean().dropna().values
        
        if len(avg_gains) == 0 or len(avg_losses) == 0:
            return 50.0
        
        rs = avg_gains[-1] / (avg_losses[-1] + 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return min(max(rsi, 0), 100)

    @staticmethod
    def calculate_stochastic(prices: List[float], period: int = 14) -> Dict[str, float]:
        """حساب Stochastic"""
        if len(prices) < period:
            return {'k': 50, 'd': 50}
        
        low_min = min(prices[-period:])
        high_max = max(prices[-period:])
        
        if high_max == low_min:
            k = 50
        else:
            k = 100 * ((prices[-1] - low_min) / (high_max - low_min))
        
        k_values = []
        for i in range(len(prices) - period + 1):
            period_low = min(prices[i:i+period])
            period_high = max(prices[i:i+period])
            if period_high != period_low:
                k_val = 100 * ((prices[i+period-1] - period_low) / (period_high - period_low))
                k_values.append(k_val)
            else:
                k_values.append(50)
        
        if len(k_values) >= 3:
            d = np.mean(k_values[-3:])
        else:
            d = k
        
        return {'k': round(k, 2), 'd': round(d, 2)}

    @staticmethod
    def calculate_macd(prices: List[float]) -> Dict[str, float]:
        """حساب MACD"""
        if len(prices) < 26:
            return {'macd': 0, 'signal': 0, 'histogram': 0}
        
        ema_12 = pd.Series(prices).ewm(span=12, adjust=False).mean().values
        ema_26 = pd.Series(prices).ewm(span=26, adjust=False).mean().values
        
        macd_line = ema_12[-1] - ema_26[-1]
        signal_line = pd.Series([ema_12[i] - ema_26[i] for i in range(len(prices))]).ewm(span=9, adjust=False).mean().values[-1]
        histogram = macd_line - signal_line
        
        return {
            'macd': round(macd_line, 4),
            'signal': round(signal_line, 4),
            'histogram': round(histogram, 4)
        }

    @staticmethod
    def calculate_moving_averages(prices: List[float]) -> Dict[str, float]:
        """حساب المتوسطات المتحركة"""
        if len(prices) < 50:
            return {'ema_20': prices[-1] if prices else 0, 'ema_50': prices[-1] if prices else 0}
        
        ema_20 = pd.Series(prices).ewm(span=20, adjust=False).mean().values[-1]
        ema_50 = pd.Series(prices).ewm(span=50, adjust=False).mean().values[-1]
        
        return {
            'ema_20': round(ema_20, 4),
            'ema_50': round(ema_50, 4)
        }

    @staticmethod
    def detect_candle_pattern(prices: List[float], highs: List[float], lows: List[float]) -> Dict[str, Any]:
        """الكشف عن أنماط الشموع الانعكاسية"""
        if len(prices) < 3:
            return {"pattern": "none", "strength": 0, "description": "لا توجد بيانات كافية", "direction": "none"}
        
        current_close = prices[-1]
        current_high = highs[-1]
        current_low = lows[-1]
        prev_close = prices[-2]
        prev_high = highs[-2]
        prev_low = lows[-2]
        prev2_close = prices[-3] if len(prices) >= 3 else prev_close
        
        current_body = abs(current_close - prev_close)
        current_upper_wick = current_high - max(current_close, prev_close)
        current_lower_wick = min(current_close, prev_close) - current_low
        
        is_hammer = (current_lower_wick > 2 * current_body and 
                    current_upper_wick < current_body * 0.3 and
                    current_close > prev_close)
        
        is_shooting_star = (current_upper_wick > 2 * current_body and 
                           current_lower_wick < current_body * 0.3 and
                           current_close < prev_close)
        
        is_bullish_engulfing = (prev_close < prev2_close and current_close > prev_high and prev_close < prev_low)
        is_bearish_engulfing = (prev_close > prev2_close and current_close < prev_low and prev_close > prev_high)
        
        body_ratio = current_body / (current_high - current_low) if (current_high - current_low) > 0 else 1
        is_doji = body_ratio < 0.1
        
        if is_hammer:
            return {"pattern": "hammer", "strength": 12, "description": "🔨 مطرقة - إشارة قاع قوية", "direction": "bottom"}
        elif is_shooting_star:
            return {"pattern": "shooting_star", "strength": 12, "description": "💫 نجم ساقط - إشارة قمة قوية", "direction": "top"}
        elif is_bullish_engulfing:
            return {"pattern": "bullish_engulfing", "strength": 10, "description": "🟢 ابتلاع صاعد - إشارة قاع", "direction": "bottom"}
        elif is_bearish_engulfing:
            return {"pattern": "bearish_engulfing", "strength": 10, "description": "🔴 ابتلاع هابط - إشارة قمة", "direction": "top"}
        elif is_doji:
            return {"pattern": "doji", "strength": 6, "description": "⚪ دوجي - تردد في السوق", "direction": "neutral"}
        else:
            return {"pattern": "none", "strength": 0, "description": "⚪ لا يوجد نمط واضح", "direction": "none"}

    @staticmethod
    def analyze_support_resistance(prices: List[float]) -> Dict[str, Any]:
        """تحليل مستويات الدعم والمقاومة"""
        if len(prices) < 20:
            return {"support": 0, "resistance": 0, "strength": 0, "direction": "none", "distance_percent": 1.0}
        
        recent_lows = min(prices[-20:])
        recent_highs = max(prices[-20:])
        current_price = prices[-1]
        
        distance_to_support = abs(current_price - recent_lows) / current_price
        distance_to_resistance = abs(current_price - recent_highs) / current_price
        
        strength = 0
        direction = "none"
        closest_distance = min(distance_to_support, distance_to_resistance)
        
        if distance_to_support < 0.01:
            strength = 12
            direction = "bottom"
        elif distance_to_support < 0.02:
            strength = 8
            direction = "bottom"
        elif distance_to_support < 0.03:
            strength = 4
            direction = "bottom"
        elif distance_to_resistance < 0.01:
            strength = 12
            direction = "top"
        elif distance_to_resistance < 0.02:
            strength = 8
            direction = "top"
        elif distance_to_resistance < 0.03:
            strength = 4
            direction = "top"
            
        return {
            "support": recent_lows,
            "resistance": recent_highs,
            "strength": strength,
            "direction": direction,
            "current_price": current_price,
            "distance_percent": closest_distance
        }

    @staticmethod
    def analyze_volume_trend(volumes: List[float], price_trend: str = "neutral") -> Dict[str, Any]:
        """تحليل اتجاه الحجم"""
        if len(volumes) < 10:
            return {"trend": "stable", "strength": 0, "description": "⚪ حجم مستقر", "volume_ratio": 1.0}
        
        recent_volume = np.mean(volumes[-5:])
        previous_volume = np.mean(volumes[-10:-5])
        
        volume_ratio = recent_volume / (previous_volume + 1e-10)
        
        if volume_ratio > 2.0:
            strength = 10
            trend_desc = "📈 حجم متزايد بقوة"
        elif volume_ratio > 1.5:
            strength = 7
            trend_desc = "📈 حجم متزايد"
        elif volume_ratio > 1.2:
            strength = 4
            trend_desc = "📈 حجم متزايد قليلاً"
        elif volume_ratio < 0.5:
            strength = 6
            trend_desc = "📉 حجم متراجع بقوة"
        elif volume_ratio < 0.8:
            strength = 4
            trend_desc = "📉 حجم متراجع"
        else:
            strength = 3
            trend_desc = "⚪ حجم مستقر"
        
        confirmation_bonus = 0
        if (price_trend == "up" and volume_ratio > 1.2) or (price_trend == "down" and volume_ratio > 1.2):
            confirmation_bonus = 5
            trend_desc += " - مؤكد بالحجم"
        
        return {
            "trend": "rising" if volume_ratio > 1.1 else "falling" if volume_ratio < 0.9 else "stable",
            "strength": strength + confirmation_bonus,
            "description": trend_desc,
            "volume_ratio": volume_ratio
        }

    @staticmethod
    def calculate_fibonacci_levels(prices: List[float]) -> Dict[str, Any]:
        """حساب مستويات فيبوناتشي"""
        if len(prices) < 20:
            return {"closest_level": None, "distance": None, "strength": 0}
        
        high = max(prices[-20:])
        low = min(prices[-20:])
        current = prices[-1]
        
        if high == low:
            return {"closest_level": None, "distance": None, "strength": 0}
        
        diff = high - low
        
        levels = {
            '0.0': low,
            '0.236': low + diff * 0.236,
            '0.382': low + diff * 0.382,
            '0.5': low + diff * 0.5,
            '0.618': low + diff * 0.618,
            '0.786': low + diff * 0.786,
            '1.0': high
        }
        
        closest_level = None
        min_distance = float('inf')
        
        for level_name, level_price in levels.items():
            distance = abs(current - level_price) / current
            if distance < min_distance:
                min_distance = distance
                closest_level = level_name
        
        strength = 0
        if closest_level in ['0.0', '0.236', '0.382', '0.618', '0.786', '1.0'] and min_distance < 0.02:
            strength = 8
        elif closest_level == '0.5' and min_distance < 0.02:
            strength = 4
        
        return {
            'closest_level': closest_level,
            'distance': min_distance,
            'strength': strength
        }

    def detect_divergence(self, prices: List[float], indicator_values: List[float]) -> Dict[str, bool]:
        """كشف التباعد بين السعر والمؤشر"""
        if len(prices) < 10 or len(indicator_values) < 10:
            return {}
        
        divergences = {
            'regular_bullish': False,
            'regular_bearish': False, 
            'hidden_bullish': False,
            'hidden_bearish': False
        }
        
        try:
            # البحث عن القمم والقيعان
            price_peaks = self._find_peaks(prices)
            indicator_peaks = self._find_peaks(indicator_values)
            price_troughs = self._find_troughs(prices)
            indicator_troughs = self._find_troughs(indicator_values)
            
            if len(price_peaks) >= 2 and len(indicator_peaks) >= 2:
                # Regular Bearish Divergence
                if (prices[price_peaks[-1]] > prices[price_peaks[-2]] and 
                    indicator_values[indicator_peaks[-1]] < indicator_values[indicator_peaks[-2]]):
                    divergences['regular_bearish'] = True
                
                # Hidden Bearish Divergence
                if (prices[price_peaks[-1]] < prices[price_peaks[-2]] and 
                    indicator_values[indicator_peaks[-1]] > indicator_values[indicator_peaks[-2]]):
                    divergences['hidden_bearish'] = True
            
            if len(price_troughs) >= 2 and len(indicator_troughs) >= 2:
                # Regular Bullish Divergence
                if (prices[price_troughs[-1]] < prices[price_troughs[-2]] and 
                    indicator_values[indicator_troughs[-1]] > indicator_values[indicator_troughs[-2]]):
                    divergences['regular_bullish'] = True
                
                # Hidden Bullish Divergence
                if (prices[price_troughs[-1]] > prices[price_troughs[-2]] and 
                    indicator_values[indicator_troughs[-1]] < indicator_values[indicator_troughs[-2]]):
                    divergences['hidden_bullish'] = True
                    
        except Exception as e:
            safe_log_error(f"خطأ في كشف التباعد: {e}", "analyzer", "divergence")
        
        return divergences

    def _find_peaks(self, data: List[float], window: int = 3) -> List[int]:
        """إيجاد القمم في البيانات"""
        peaks = []
        for i in range(window, len(data) - window):
            if (all(data[i] > data[i-j] for j in range(1, window+1)) and
                all(data[i] > data[i+j] for j in range(1, window+1))):
                peaks.append(i)
        return peaks

    def _find_troughs(self, data: List[float], window: int = 3) -> List[int]:
        """إيجاد القيعان في البيانات"""
        troughs = []
        for i in range(window, len(data) - window):
            if (all(data[i] < data[i-j] for j in range(1, window+1)) and
                all(data[i] < data[i+j] for j in range(1, window+1))):
                troughs.append(i)
        return troughs

    def calculate_free_bcmi_score(self, symbol: str) -> Dict[str, Any]:
        """حساب مؤشر BCMI مجاني مبسط"""
        try:
            # هذه دمية - تحتاج مصادر حقيقية للبيانات
            mvrv_score = 0.6  # تقدير من LookIntoBitcoin
            sopr_score = 0.55  # تقدير من Glassnode
            sentiment_score = 0.65  # تقدير من Fear & Greed
            momentum_score = 0.7  # تقدير من الزخم
            
            bcmi_score = (
                mvrv_score * BCMI_WEIGHTS['MVRV'] +
                sopr_score * BCMI_WEIGHTS['SOPR'] + 
                sentiment_score * BCMI_WEIGHTS['SENTIMENT'] +
                momentum_score * BCMI_WEIGHTS['MOMENTUM']
            )
            
            return {
                'score': bcmi_score,
                'components': {
                    'mvrv': mvrv_score,
                    'sopr': sopr_score, 
                    'sentiment': sentiment_score,
                    'momentum': momentum_score
                },
                'source': 'free_estimation'
            }
            
        except Exception as e:
            safe_log_error(f"خطأ في حساب BCMI: {e}", symbol, "bcmi")
            return {'score': 0.5, 'source': 'error'}

    def analyze_market_condition(self, prices: List[float], volumes: List[float], 
                               highs: List[float], lows: List[float]) -> Dict[str, Any]:
        """تحليل شامل لحالة السوق - النسخة المحسنة"""
        
        if len(prices) < 20:
            return self._get_empty_analysis()
        
        try:
            # حساب المؤشرات الأساسية
            rsi = self.calculate_rsi(prices)
            stoch = self.calculate_stochastic(prices)
            macd = self.calculate_macd(prices)
            moving_averages = self.calculate_moving_averages(prices)
            candle_pattern = self.detect_candle_pattern(prices, highs, lows)
            support_resistance = self.analyze_support_resistance(prices)
            price_trend = "up" if prices[-1] > prices[-5] else "down" if prices[-1] < prices[-5] else "neutral"
            volume_analysis = self.analyze_volume_trend(volumes, price_trend)
            fib_levels = self.calculate_fibonacci_levels(prices)
            
            # حساب نقاط الأساس
            top_score = self._calculate_top_score(rsi, stoch, macd, moving_averages, candle_pattern, 
                                                support_resistance, volume_analysis, fib_levels, prices[-1])
            bottom_score = self._calculate_bottom_score(rsi, stoch, macd, moving_averages, candle_pattern,
                                                      support_resistance, volume_analysis, fib_levels, prices[-1])
            
            # تطبيق وزن الجلسة
            session_weight = get_session_weight()
            top_score = int(top_score * session_weight)
            bottom_score = int(bottom_score * session_weight)
            
            # تحديد الإشارة الأقوى
            strongest_signal = "top" if top_score > bottom_score else "bottom"
            strongest_score = max(top_score, bottom_score)
            
            # 🔧 إضافة المؤشرات الجديدة إذا كانت مفعلة
            divergence_analysis = {}
            bcmi_analysis = {}
            enhanced_score = strongest_score
            
            if ENABLE_DIVERGENCE:
                # كشف التباعد لـ RSI و MACD
                rsi_values = [self.calculate_rsi(prices[:i+1]) for i in range(len(prices))]
                macd_values = [self.calculate_macd(prices[:i+1])['histogram'] for i in range(len(prices))]
                
                rsi_divergence = self.detect_divergence(prices, rsi_values)
                macd_divergence = self.detect_divergence(prices, macd_values)
                
                divergence_analysis = {
                    'rsi': rsi_divergence,
                    'macd': macd_divergence
                }
                
                # إضافة نقاط التباعد
                divergence_score = self._calculate_divergence_score(rsi_divergence, macd_divergence)
                enhanced_score = min(100, enhanced_score + divergence_score)
            
            if ENABLE_BCMI:
                # حساب BCMI (استخدم symbol من البيانات المتاحة)
                bcmi_analysis = self.calculate_free_bcmi_score("BTC")  # مؤقت
                bcmi_bonus = int(bcmi_analysis['score'] * 20)  # تحويل إلى 0-20 نقطة
                enhanced_score = min(100, enhanced_score + bcmi_bonus)
            
            return {
                "top_score": min(top_score, 100),
                "bottom_score": min(bottom_score, 100),
                "strongest_signal": strongest_signal,
                "strongest_score": enhanced_score,
                "alert_level": get_alert_level(enhanced_score),
                "indicators": {
                    "rsi": round(rsi, 2),
                    "stoch_k": stoch['k'],
                    "stoch_d": stoch['d'],
                    "macd_histogram": macd['histogram'],
                    "ema_20": moving_averages['ema_20'],
                    "ema_50": moving_averages['ema_50'],
                    "candle_pattern": candle_pattern,
                    "support_resistance": support_resistance,
                    "volume_trend": volume_analysis,
                    "fibonacci": fib_levels,
                    "session_weight": session_weight,
                    "divergence": divergence_analysis if ENABLE_DIVERGENCE else {},
                    "bcmi": bcmi_analysis if ENABLE_BCMI else {}
                },
                "timestamp": time.time()
            }
            
        except Exception as e:
            safe_log_error(f"خطأ في تحليل السوق: {e}", "analyzer", "market_analysis")
            return self._get_empty_analysis()

    def _calculate_divergence_score(self, rsi_divergence: Dict, macd_divergence: Dict) -> int:
        """حساب نقاط التباعد"""
        score = 0
        
        # التباعد العادي أقوى من المخفي
        if rsi_divergence.get('regular_bullish') or macd_divergence.get('regular_bullish'):
            score += 8
        if rsi_divergence.get('regular_bearish') or macd_divergence.get('regular_bearish'):
            score += 8
        if rsi_divergence.get('hidden_bullish') or macd_divergence.get('hidden_bullish'):
            score += 4
        if rsi_divergence.get('hidden_bearish') or macd_divergence.get('hidden_bearish'):
            score += 4
            
        return min(score, 20)  # حد أقصى 20 نقطة

    def _calculate_top_score(self, rsi: float, stoch: Dict, macd: Dict, moving_averages: Dict,
                           candle_pattern: Dict, support_resistance: Dict,
                           volume_analysis: Dict, fib_levels: Dict, current_price: float) -> int:
        """حساب نقاط القمة"""
        score = 0
        
        # MOMENTUM
        if rsi > 80: score += 12
        elif rsi > 70: score += 8
        elif rsi > 60: score += 4
        
        if stoch['k'] > 85 and stoch['d'] > 85: score += 12
        elif stoch['k'] > 75 and stoch['d'] > 75: score += 8
        elif stoch['k'] > 65 and stoch['d'] > 65: score += 4
        
        if macd['histogram'] < -0.02: score += 6
        elif macd['histogram'] < -0.01: score += 4
        elif macd['histogram'] < 0: score += 1
        
        if macd['histogram'] < 0 and macd['macd'] < macd['signal']: score += 5
        
        # PRICE_ACTION
        if candle_pattern["direction"] == "top":
            score += candle_pattern["strength"]
        
        if current_price < moving_averages['ema_20'] and current_price < moving_averages['ema_50']:
            score += 10
        elif current_price < moving_averages['ema_20']:
            score += 5
        
        # KEY_LEVELS
        if support_resistance["direction"] == "top":
            score += support_resistance["strength"]
        
        score += fib_levels["strength"]
        
        if fib_levels.get('closest_level') in ['0.618', '0.786', '1.0'] and fib_levels['distance'] < 0.015:
            score += 5
        
        # VOLUME_CONFIRMATION
        score += volume_analysis["strength"]
        
        if volume_analysis["volume_ratio"] > 1.2 and volume_analysis["trend"] == "rising":
            score += 5
        
        return min(score, 100)

    def _calculate_bottom_score(self, rsi: float, stoch: Dict, macd: Dict, moving_averages: Dict,
                              candle_pattern: Dict, support_resistance: Dict,
                              volume_analysis: Dict, fib_levels: Dict, current_price: float) -> int:
        """حساب نقاط القاع"""
        score = 0
        
        # MOMENTUM
        if rsi < 20: score += 12
        elif rsi < 30: score += 8
        elif rsi < 40: score += 4
        
        if stoch['k'] < 15 and stoch['d'] < 15: score += 12
        elif stoch['k'] < 25 and stoch['d'] < 25: score += 8
        elif stoch['k'] < 35 and stoch['d'] < 35: score += 4
        
        if macd['histogram'] > 0.02: score += 6
        elif macd['histogram'] > 0.01: score += 4
        elif macd['histogram'] > 0: score += 1
        
        if macd['histogram'] > 0 and macd['macd'] > macd['signal']: score += 5
        
        # PRICE_ACTION
        if candle_pattern["direction"] == "bottom":
            score += candle_pattern["strength"]
        
        if current_price > moving_averages['ema_20'] and current_price > moving_averages['ema_50']:
            score += 10
        elif current_price > moving_averages['ema_20']:
            score += 5
        
        # KEY_LEVELS
        if support_resistance["direction"] == "bottom":
            score += support_resistance["strength"]
        
        score += fib_levels["strength"]
        
        if fib_levels.get('closest_level') in ['0.0', '0.236', '0.382'] and fib_levels['distance'] < 0.015:
            score += 5
        
        # VOLUME_CONFIRMATION
        score += volume_analysis["strength"]
        
        if volume_analysis["volume_ratio"] > 1.2 and volume_analysis["trend"] == "rising":
            score += 5
        
        return min(score, 100)

    def _get_empty_analysis(self) -> Dict[str, Any]:
        """تحليل افتراضي عند عدم وجود بيانات كافية"""
        return {
            "top_score": 0,
            "bottom_score": 0,
            "strongest_signal": "none",
            "strongest_score": 0,
            "alert_level": get_alert_level(0),
            "indicators": {},
            "timestamp": time.time()
        }
class TelegramNotifier:
    """إشعارات التليجرام مع صور الشارت - النسخة المحدثة"""
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"

    async def send_alert(self, coin: str, timeframe: str, analysis: Dict[str, Any], 
                        price: float, prices: List[float], highs: List[float], lows: List[float]) -> bool:
        """إرسال تنبيه مع صورة الشارت"""
        
        alert_level = analysis["alert_level"]
        strongest_signal = analysis["strongest_signal"]
        strongest_score = analysis["strongest_score"]
        
        if not alert_level["send_alert"] or strongest_score < CONFIDENCE_THRESHOLD:
            return False
        
        try:
            # بناء الرسالة النصية المحسنة
            message = self._build_enhanced_message(coin, timeframe, analysis, price)
            
            # إنشاء صورة الشارت
            chart_image = self._create_beautiful_chart(coin, timeframe, prices, highs, lows, analysis, price)
            
            if chart_image:
                success = await self._send_photo_with_caption(message, chart_image)
                if success:
                    safe_log_info(f"📨 تم إرسال إشعار بصورة لـ {coin} ({timeframe}) - {strongest_signal} - {strongest_score} نقطة", 
                                coin, "telegram")
                    system_stats["total_alerts_sent"] += 1
                    return True
            else:
                success = await self._send_text_message(message)
                if success:
                    safe_log_info(f"📨 تم إرسال إشعار نصي لـ {coin} ({timeframe}) - {strongest_signal} - {strongest_score} نقطة", 
                                coin, "telegram")
                    system_stats["total_alerts_sent"] += 1
                    return True
            
            return False
                    
        except Exception as e:
            safe_log_error(f"خطأ في إرسال الإشعار: {e}", coin, "telegram")
            return False

    def _build_enhanced_message(self, coin: str, timeframe: str, analysis: Dict[str, Any], price: float) -> str:
        """بناء رسالة محسنة مع المؤشرات الجديدة"""
        
        alert_level = analysis["alert_level"]
        strongest_signal = analysis["strongest_signal"]
        strongest_score = analysis["strongest_score"]
        indicators = analysis["indicators"]
        current_session = get_current_session()
        
        # الرأس حسب نوع الإشارة
        if strongest_signal == "top":
            signal_emoji = "🔴"
            signal_text = "قمة سعرية"
        else:
            signal_emoji = "🟢" 
            signal_text = "قاع سعري"
        
        message = f"{signal_emoji} *{signal_text} - {coin.upper()}* {signal_emoji}\n"
        message += "═" * 40 + "\n\n"
        
        # معلومات السعر والإطار
        message += f"💰 *السعر الحالي:* `${price:,.2f}`\n"
        message += f"⏰ *الإطار الزمني:* `{timeframe}`\n"
        message += f"🕒 *التوقيت السوري:* `{get_syria_time().strftime('%H:%M %d/%m/%Y')}`\n\n"
        
        # قوة الإشارة
        message += f"🎯 *قوة الإشارة:* {alert_level['emoji']} *{strongest_score}/100*\n"
        message += f"📊 *مستوى الثقة:* `{alert_level['level']}`\n\n"
        
        # الجلسة الحالية
        message += f"🌍 *الجلسة:* {current_session['emoji']} {current_session['name']}\n"
        message += f"⚖️ *وزن الجلسة:* `{current_session['weight']*100}%`\n\n"
        
        # المؤشرات الفنية الأساسية
        message += "📈 *المؤشرات الفنية:*\n"
        
        if 'rsi' in indicators:
            rsi_emoji = "🔴" if indicators['rsi'] > 70 else "🟢" if indicators['rsi'] < 30 else "🟡"
            rsi_status = "تشبع شرائي" if indicators['rsi'] > 70 else "تشبع بيعي" if indicators['rsi'] < 30 else "محايد"
            message += f"• {rsi_emoji} *RSI:* `{indicators['rsi']}` ({rsi_status})\n"
        
        if 'stoch_k' in indicators:
            stoch_emoji = "🔴" if indicators['stoch_k'] > 80 else "🟢" if indicators['stoch_k'] < 20 else "🟡"
            stoch_status = "تشبع شرائي" if indicators['stoch_k'] > 80 else "تشبع بيعي" if indicators['stoch_k'] < 20 else "محايد"
            message += f"• {stoch_emoji} *Stochastic:* `K={indicators['stoch_k']}, D={indicators['stoch_d']}` ({stoch_status})\n"
        
        if 'macd_histogram' in indicators:
            macd_emoji = "🟢" if indicators['macd_histogram'] > 0 else "🔴"
            macd_trend = "صاعد" if indicators['macd_histogram'] > 0 else "هابط"
            message += f"• {macd_emoji} *MACD Hist:* `{indicators['macd_histogram']:.4f}` ({macd_trend})\n"
        
        # 🔧 المؤشرات الجديدة
        if ENABLE_DIVERGENCE and indicators.get('divergence'):
            divergence_text = self._format_divergence_info(indicators['divergence'])
            if divergence_text:
                message += f"• 🎯 *التباعد:* {divergence_text}\n"
        
        if ENABLE_BCMI and indicators.get('bcmi'):
            bcmi_score = indicators['bcmi'].get('score', 0)
            bcmi_emoji = "🟢" if bcmi_score > 0.6 else "🟡" if bcmi_score > 0.4 else "🔴"
            message += f"• 🌡️ *صحة البلوكتشين:* {bcmi_emoji} `{bcmi_score:.2f}/1.0`\n"
        
        message += "\n"
        
        # التوصية
        if strongest_signal == "top":
            recommendation = "💡 *التوصية:* مراقبة فرص البيع والربح"
        else:
            recommendation = "💡 *التوصية:* مراقبة فرص الشراء والدخول"
        
        message += f"{recommendation}\n\n"
        
        # التوقيع
        message += "─" * 30 + "\n"
        message += f"⚡ *ماسح القمم والقيعان v3.0*"
        message += f"\n🔧 *المؤشرات النشطة:*"
        if ENABLE_BCMI: message += " BCMI"
        if ENABLE_DIVERGENCE: message += " التباعد"
        if ENABLE_CONFIRMATION_SYSTEM: message += " التأكيد"
        
        return message

    def _format_divergence_info(self, divergence_data: Dict) -> str:
        """تنسيق معلومات التباعد"""
        parts = []
        
        if divergence_data.get('rsi', {}).get('regular_bullish') or divergence_data.get('macd', {}).get('regular_bullish'):
            parts.append("صاعد عادي")
        if divergence_data.get('rsi', {}).get('regular_bearish') or divergence_data.get('macd', {}).get('regular_bearish'):
            parts.append("هابط عادي")
        if divergence_data.get('rsi', {}).get('hidden_bullish') or divergence_data.get('macd', {}).get('hidden_bullish'):
            parts.append("صاعد مخفي")
        if divergence_data.get('rsi', {}).get('hidden_bearish') or divergence_data.get('macd', {}).get('hidden_bearish'):
            parts.append("هابط مخفي")
            
        return "، ".join(parts) if parts else "لا يوجد"

    def _create_beautiful_chart(self, coin: str, timeframe: str, prices: List[float], 
                              highs: List[float], lows: List[float], analysis: Dict[str, Any], 
                              current_price: float) -> Optional[str]:
        """إنشاء رسم بياني جميل"""
        try:
            if len(prices) < 10:
                return None
            
            if analysis["strongest_signal"] == "top":
                colors = COLORS["top"]
            else:
                colors = COLORS["bottom"]
            
            plt.figure(figsize=(12, 8))
            plt.gca().set_facecolor(colors["bg"])
            plt.grid(True, alpha=0.3, linestyle='--')
            
            display_prices = prices[-50:] if len(prices) > 50 else prices
            x_values = list(range(len(display_prices)))
            
            plt.plot(x_values, display_prices, color=colors["primary"], linewidth=3, 
                    label=f'سعر {coin.upper()}', alpha=0.8, marker='o', markersize=3)
            
            plt.scatter([x_values[-1]], [display_prices[-1]], color=colors["primary"], 
                      s=200, zorder=5, edgecolors='white', linewidth=2)
            
            if 'support_resistance' in analysis["indicators"]:
                sr_data = analysis["indicators"]["support_resistance"]
                if sr_data["support"] > 0:
                    plt.axhline(y=sr_data["support"], color='green', linestyle='--', 
                              alpha=0.7, label=f'دعم: ${sr_data["support"]:,.2f}')
                if sr_data["resistance"] > 0:
                    plt.axhline(y=sr_data["resistance"], color='red', linestyle='--', 
                              alpha=0.7, label=f'مقاومة: ${sr_data["resistance"]:,.2f}')
            
            # إضافة عنوان محسن
            title = f'{coin.upper()} - إطار {timeframe}\n'
            title += f'إشارة {analysis["strongest_signal"]} - قوة {analysis["strongest_score"]}/100'
            
            if ENABLE_BCMI and analysis["indicators"].get('bcmi'):
                bcmi_score = analysis["indicators"]['bcmi'].get('score', 0)
                title += f' - BCMI: {bcmi_score:.2f}'
                
            plt.title(title, fontsize=16, fontweight='bold', color=colors["primary"], pad=20)
            
            plt.xlabel('الوقت', fontsize=12)
            plt.ylabel('السعر (USDT)', fontsize=12)
            plt.legend()
            plt.tight_layout()
            
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=100, bbox_inches='tight',
                       facecolor=colors["bg"], edgecolor='none')
            buffer.seek(0)
            plt.close()
            
            return base64.b64encode(buffer.read()).decode('utf-8')
            
        except Exception as e:
            safe_log_error(f"خطأ في إنشاء الرسم البياني: {e}", coin, "chart")
            return None

    async def _send_photo_with_caption(self, caption: str, photo_base64: str) -> bool:
        """إرسال صورة مع تسمية توضيحية"""
        try:
            caption = self._clean_message(caption)
            if len(caption) > 1024:
                caption = caption[:1020] + "..."
                
            payload = {
                'chat_id': self.chat_id,
                'caption': caption,
                'parse_mode': 'Markdown'
            }
            
            files = {
                'photo': ('chart.png', base64.b64decode(photo_base64), 'image/png')
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.base_url}/sendPhoto", 
                                           data=payload, files=files, timeout=15.0)
                
            return response.status_code == 200
            
        except Exception as e:
            safe_log_error(f"خطأ في إرسال الصورة: {e}", "system", "telegram")
            return False

    async def _send_text_message(self, message: str) -> bool:
        """إرسال رسالة نصية فقط"""
        try:
            message = self._clean_message(message)
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.base_url}/sendMessage", 
                                           json=payload, timeout=10.0)
                
            return response.status_code == 200
            
        except Exception as e:
            safe_log_error(f"خطأ في إرسال الرسالة النصية: {e}", "system", "telegram")
            return False

    def _clean_message(self, message: str) -> str:
        """تنظيف الرسالة من الأحرف الخاصة"""
        clean_message = message.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
        return clean_message

    async def send_heartbeat(self) -> bool:
        """إرسال نبضة عن حالة النظام"""
        try:
            uptime_seconds = time.time() - system_stats["start_time"]
            uptime_str = self._format_uptime(uptime_seconds)
            
            current_session = get_current_session()
            syria_time = get_syria_time()
            
            message = f"""
💓 *نبضة النظام - ماسح القمم والقيعان v3.0*

⏰ *الوقت السوري:* `{syria_time.strftime('%H:%M %d/%m/%Y')}`
🌍 *الجلسة الحالية:* {current_session['emoji']} `{current_session['name']}`
⚖️ *وزن الجلسة:* `{current_session['weight'] * 100}%`

📊 *إحصائيات النظام:*
• ⏱️ *مدة التشغيل:* `{uptime_str}`
• 🔍 *عدد عمليات المسح:* `{system_stats['total_scans']}`
• 📨 *التنبيهات المرسلة:* `{system_stats['total_alerts_sent']}`
• 📡 *الإشارات المرسلة:* `{system_stats['total_signals_sent']}`
• 💓 *نبضات المنفذ:* `{system_stats['total_heartbeats_sent']}`
• 🔗 *اتصال المنفذ:* `{'✅' if system_stats['executor_connected'] else '❌'}`
• 💾 *حجم الكاش:* `{len(data_fetcher.cache)}` عملة

🔧 *المؤشرات النشطة:*
• BCMI: `{'✅' if ENABLE_BCMI else '❌'}`
• التباعد: `{'✅' if ENABLE_DIVERGENCE else '❌'}`  
• نظام التأكيد: `{'✅' if ENABLE_CONFIRMATION_SYSTEM else '❌'}`

🪙 *العملات النشطة:* `{', '.join(SUPPORTED_COINS.keys())}`
⏰ *الأطر الزمنية:* `{', '.join(TIMEFRAMES)}`

🎯 *آخر تحديث:* `{system_stats['last_scan_time'] or 'لم يبدأ بعد'}`
💓 *آخر نبضة:* `{system_stats['last_heartbeat'] or 'لم يبدأ بعد'}`
🔗 *آخر نبضة منفذ:* `{system_stats['last_executor_heartbeat'] or 'لم يبدأ بعد'}`

✅ *الحالة:* النظام يعمل بشكل طبيعي
            """
            
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.base_url}/sendMessage", 
                                           json=payload, timeout=10.0)
            
            if response.status_code == 200:
                system_stats["last_heartbeat"] = syria_time.strftime('%H:%M %d/%m/%Y')
                safe_log_info("تم إرسال نبضة النظام بنجاح", "system", "heartbeat")
                return True
            else:
                safe_log_error(f"فشل إرسال النبضة: {response.status_code}", "system", "heartbeat")
                return False
                
        except Exception as e:
            safe_log_error(f"خطأ في إرسال النبضة: {e}", "system", "heartbeat")
            return False

    def _format_uptime(self, seconds: float) -> str:
        """تنسيق مدة التشغيل"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        
        if days > 0:
            return f"{days} يوم, {hours} ساعة, {minutes} دقيقة"
        elif hours > 0:
            return f"{hours} ساعة, {minutes} دقيقة"
        else:
            return f"{minutes} دقيقة"

# باقي الفئات (ExecutorBotClient, BinanceDataFetcher) تبقى كما هي مع تحديثات بسيطة

class ExecutorBotClient:
    """عميل للتواصل مع بوت التنفيذ - بدون تغيير"""
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def send_trade_signal(self, signal_data: Dict[str, Any]) -> bool:
        if not EXECUTE_TRADES:
            safe_log_info("تنفيذ الصفقات معطل في الإعدادات", "executor", "trade")
            return False
            
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "signal": signal_data,
                "timestamp": time.time(),
                "source": "top_bottom_scanner_v3.0"
            }
            
            response = await self.client.post(
                f"{self.base_url}/api/trade/signal",
                json=payload,
                headers=headers
            )
            
            if response.status_code == 200:
                result = response.json()
                safe_log_info(f"✅ تم إرسال إشارة للتنفيذ: {result.get('message', '')}", 
                            signal_data.get('coin', 'unknown'), "executor")
                system_stats["total_signals_sent"] += 1
                return True
            else:
                safe_log_error(f"❌ فشل إرسال الإشارة: {response.status_code} - {response.text}", 
                             signal_data.get('coin', 'unknown'), "executor")
                return False
                
        except Exception as e:
            safe_log_error(f"❌ خطأ في التواصل مع البوت المنفذ: {e}", 
                         signal_data.get('coin', 'unknown'), "executor")
            return False

    async def send_heartbeat(self) -> bool:
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "heartbeat": True,
                "timestamp": time.time(),
                "source": "top_bottom_scanner_v3.0",
                "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
                "system_stats": {
                    "total_scans": system_stats["total_scans"],
                    "total_alerts_sent": system_stats["total_alerts_sent"],
                    "total_signals_sent": system_stats["total_signals_sent"],
                    "total_heartbeats_sent": system_stats["total_heartbeats_sent"],
                    "last_scan_time": system_stats["last_scan_time"],
                    "executor_connected": system_stats["executor_connected"]
                }
            }
            
            response = await self.client.post(
                f"{self.base_url}/api/heartbeat",
                json=payload,
                headers=headers
            )
            
            if response.status_code == 200:
                system_stats["executor_connected"] = True
                system_stats["total_heartbeats_sent"] += 1
                system_stats["last_executor_heartbeat"] = get_syria_time().strftime('%H:%M %d/%m/%Y')
                safe_log_info(f"✅ تم إرسال نبضة للبوت المنفذ بنجاح", "system", "executor_heartbeat")
                return True
            else:
                system_stats["executor_connected"] = False
                safe_log_error(f"❌ فشل إرسال النبضة: {response.status_code} - {response.text}", 
                             "system", "executor_heartbeat")
                return False
                
        except Exception as e:
            system_stats["executor_connected"] = False
            safe_log_error(f"❌ خطأ في إرسال النبضة: {e}", "system", "executor_heartbeat")
            return False

    async def health_check(self) -> bool:
        try:
            response = await self.client.get(f"{self.base_url}/health", timeout=10.0)
            system_stats["executor_connected"] = (response.status_code == 200)
            return response.status_code == 200
        except Exception as e:
            system_stats["executor_connected"] = False
            safe_log_error(f"فحص صحة البوت المنفذ فشل: {e}", "system", "executor")
            return False

    async def close(self):
        await self.client.aclose()

class BinanceDataFetcher:
    """جلب البيانات من Binance - بدون تغيير"""
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.analyzer = AdvancedMarketAnalyzer()
        self.cache = {}

    async def get_coin_data(self, coin_data: Dict[str, str], timeframe: str) -> Dict[str, Any]:
        cache_key = f"{coin_data['binance_symbol']}_{timeframe}"
        current_time = time.time()
        
        if cache_key in self.cache:
            cache_data = self.cache[cache_key]
            if current_time - cache_data['timestamp'] < 300:
                return cache_data['data']
        
        try:
            data = await self._fetch_binance_data(coin_data['binance_symbol'], timeframe)
            
            if not data.get('prices'):
                safe_log_error(f"فشل جلب بيانات {timeframe} لـ {coin_data['symbol']}", 
                             coin_data['symbol'], "data_fetcher")
                return self._get_fallback_data()
            
            analysis = self.analyzer.analyze_market_condition(
                data['prices'], data['volumes'], data['highs'], data['lows']
            )
            
            result = {
                'price': data['prices'][-1],
                'analysis': analysis,
                'prices': data['prices'],
                'highs': data['highs'],
                'lows': data['lows'],
                'volumes': data['volumes'],
                'timestamp': current_time,
                'timeframe': timeframe
            }
            
            self.cache[cache_key] = {'data': result, 'timestamp': current_time}
            
            safe_log_info(f"تم تحليل {coin_data['symbol']} ({timeframe}) - قمة: {analysis['top_score']} - قاع: {analysis['bottom_score']}", 
                         coin_data['symbol'], "analyzer")
            
            return result
                
        except Exception as e:
            safe_log_error(f"خطأ في جلب بيانات {coin_data['symbol']}: {e}", 
                         coin_data['symbol'], "data_fetcher")
            return self._get_fallback_data()

    async def _fetch_binance_data(self, symbol: str, interval: str) -> Dict[str, List[float]]:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        
        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                data = response.json()
                return {
                    'prices': [float(item[4]) for item in data],
                    'highs': [float(item[2]) for item in data],
                    'lows': [float(item[3]) for item in data],
                    'volumes': [float(item[5]) for item in data]
                }
        except Exception as e:
            safe_log_error(f"خطأ في جلب البيانات من Binance: {e}", symbol, "binance")
        
        return {'prices': [], 'highs': [], 'lows': [], 'volumes': []}

    def _get_fallback_data(self) -> Dict[str, Any]:
        return {
            'price': 0,
            'analysis': self.analyzer._get_empty_analysis(),
            'prices': [],
            'highs': [],
            'lows': [],
            'volumes': [],
            'timestamp': time.time(),
            'timeframe': 'unknown'
        }

    async def close(self):
        await self.client.aclose()

# الدوال المساعدة المحدثة
async def prepare_trade_signal(coin_key: str, coin_data: Dict, timeframe: str, 
                             data: Dict, analysis: Dict) -> Optional[Dict[str, Any]]:
    """تحضير بيانات إشارة التداول للبوت المنفذ"""
    try:
        signal_type = analysis["strongest_signal"]
        score = analysis["strongest_score"]
        
        if signal_type == "top":
            action = "SELL"
            reason = "إشارة قمة سعرية قوية"
        else:
            action = "BUY" 
            reason = "إشارة قاع سعري قوية"
        
        signal_data = {
            "coin": coin_key,
            "symbol": coin_data["binance_symbol"],
            "action": action,
            "signal_type": signal_type,
            "timeframe": timeframe,
            "price": data["price"],
            "confidence_score": score,
            "reason": reason,
            "analysis": {
                "rsi": analysis["indicators"].get("rsi", 0),
                "stoch_k": analysis["indicators"].get("stoch_k", 0),
                "stoch_d": analysis["indicators"].get("stoch_d", 0),
                "macd_histogram": analysis["indicators"].get("macd_histogram", 0),
                "ema_20": analysis["indicators"].get("ema_20", 0),
                "ema_50": analysis["indicators"].get("ema_50", 0),
                "candle_pattern": analysis["indicators"].get("candle_pattern", {}),
                "volume_trend": analysis["indicators"].get("volume_trend", {}),
                "session_weight": analysis["indicators"].get("session_weight", 1.0)
            },
            "timestamp": time.time(),
            "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
            "current_session": get_current_session()["name"]
        }
        
        return signal_data
        
    except Exception as e:
        safe_log_error(f"خطأ في تحضير إشارة التداول: {e}", coin_key, "signal_prep")
        return None

async def check_with_confirmation(coin_data):
    """فحص الإشارة مع التأكيد من إطار 15m"""
    if not ENABLE_CONFIRMATION_SYSTEM:
        # إذا كان نظام التأكيد معطل، ارجع تحليل الإطار الرئيسي فقط
        primary_data = await data_fetcher.get_coin_data(coin_data, PRIMARY_TIMEFRAME)
        return primary_data['analysis'] if primary_data['analysis']['strongest_score'] >= CONFIDENCE_THRESHOLD else None
    
    try:
        # 1. الفحص في الإطار الرئيسي (1h)
        primary_data = await data_fetcher.get_coin_data(coin_data, PRIMARY_TIMEFRAME)
        primary_signal = primary_data['analysis']
        
        if (not primary_signal['alert_level']['send_alert'] or 
            primary_signal['strongest_score'] < CONFIDENCE_THRESHOLD):
            return None
        
        # 2. الفحص الفوري في إطار التأكيد (15m)
        confirmation_data = await data_fetcher.get_coin_data(coin_data, CONFIRMATION_TIMEFRAME)
        confirmation_signal = confirmation_data['analysis']
        
        # 3. التحقق من التأكيد
        if (primary_signal['strongest_signal'] == confirmation_signal['strongest_signal'] and
            confirmation_signal['strongest_score'] >= CONFIRMATION_THRESHOLD):
            
            # 4. تعزيز قوة الإشارة
            confirmed_score = min(100, primary_signal['strongest_score'] + CONFIRMATION_BONUS)
            alert_level = get_alert_level(confirmed_score)
            
            safe_log_info(f"✅ إشارة مؤكدة لـ {coin_data['symbol']}: {primary_signal['strongest_score']} → {confirmed_score} نقطة", 
                         coin_data['symbol'], "confirmation")
            
            return {
                **primary_signal,
                'strongest_score': confirmed_score,
                'alert_level': alert_level,
                'confirmed': True,
                'confirmation_score': confirmation_signal['strongest_score'],
                'price': primary_data['price'],
                'prices': primary_data['prices'],
                'highs': primary_data['highs'],
                'lows': primary_data['lows']
            }
        else:
            safe_log_info(f"❌ إشارة غير مؤكدة لـ {coin_data['symbol']}: {primary_signal['strongest_signal']} vs {confirmation_signal['strongest_signal']}", 
                         coin_data['symbol'], "confirmation")
            return None
            
    except Exception as e:
        safe_log_error(f"خطأ في نظام التأكيد لـ {coin_data['symbol']}: {e}", coin_data['symbol'], "confirmation")
        return None

# =============================================================================
# تهيئة الكائنات الرئيسية - إضافة قبل نقاط API
# =============================================================================

# تهيئة الكائنات الرئيسية
notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
executor_client = ExecutorBotClient(EXECUTOR_BOT_URL, EXECUTOR_BOT_API_KEY) 
data_fetcher = BinanceDataFetcher()

# مهمة المسح الرئيسية
async def market_scanner_task():
    """المهمة الرئيسية لمسح السوق بشكل دوري"""
    safe_log_info("بدء مهمة مسح السوق الدورية", "system", "scanner")
    
    while True:
        try:
            current_time = get_syria_time()
            safe_log_info(f"بدء جولة المسح - {current_time.strftime('%H:%M %d/%m/%Y')}", "system", "scanner")
            
            # مسح جميع العملات
            for coin_key, coin_data in SUPPORTED_COINS.items():
                try:
                    # استخدام نظام التأكيد الجديد
                    confirmed_analysis = await check_with_confirmation(coin_data)
                    
                    if confirmed_analysis:
                        # جلب البيانات الكاملة للإشعار
                        primary_data = await data_fetcher.get_coin_data(coin_data, PRIMARY_TIMEFRAME)
                        
                        # إرسال إشعار التليجرام
                        await notifier.send_alert(
                            coin_key, PRIMARY_TIMEFRAME, confirmed_analysis,
                            primary_data['price'], primary_data['prices'],
                            primary_data['highs'], primary_data['lows']
                        )
                        
                        # إرسال إشارة التنفيذ إذا كانت مفعلة
                        if EXECUTE_TRADES and confirmed_analysis['strongest_score'] >= CONFIDENCE_THRESHOLD:
                            signal_data = await prepare_trade_signal(
                                coin_key, coin_data, PRIMARY_TIMEFRAME, 
                                primary_data, confirmed_analysis
                            )
                            if signal_data:
                                await executor_client.send_trade_signal(signal_data)
                                
                except Exception as e:
                    safe_log_error(f"خطأ في مسح {coin_key}: {e}", coin_key, "scanner")
            
            system_stats["total_scans"] += 1
            system_stats["last_scan_time"] = current_time.strftime('%H:%M %d/%m/%Y')
            
            safe_log_info(f"انتهت جولة المسح - العملات: {len(SUPPORTED_COINS)} - الإشارات: {system_stats['total_signals_sent']}", 
                         "system", "scanner")
            
            await asyncio.sleep(SCAN_INTERVAL)
            
        except Exception as e:
            safe_log_error(f"خطأ في مهمة المسح: {e}", "system", "scanner")
            await asyncio.sleep(60)

# =============================================================================
# نهاية التهيئة - يليها نقاط API من الجزء الثاني
# =============================================================================


async def health_check_task():
    """مهمة الفحص الصحي"""
    while True:
        try:
            # فحص بسيط للذاكرة والأداء
            current_time = time.time()
            cache_size = len(data_fetcher.cache)
            current_session = get_current_session()
            
            # فحص اتصال البوت المنفذ
            executor_health = await executor_client.health_check()
            
            safe_log_info(f"الفحص الصحي - الكاش: {cache_size} - الجلسة: {current_session['name']} - الوزن: {current_session['weight']} - المنفذ: {'متصل' if executor_health else 'غير متصل'}", 
                         "system", "health")
            
            await asyncio.sleep(300)  # فحص كل 5 دقائق
            
        except Exception as e:
            safe_log_error(f"خطأ في الفحص الصحي: {e}", "system", "health")
            await asyncio.sleep(60)

async def heartbeat_task():
    """مهمة إرسال النبضات الدورية"""
    safe_log_info("بدء مهمة النبضات الدورية كل 30 دقيقة", "system", "heartbeat")
    
    while True:
        try:
            # انتظار الفاصل الزمني المحدد
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            
            # إرسال النبضة
            success = await notifier.send_heartbeat()
            
            if success:
                safe_log_info("تم إرسال النبضة بنجاح", "system", "heartbeat")
            else:
                safe_log_error("فشل إرسال النبضة", "system", "heartbeat")
                
        except Exception as e:
            safe_log_error(f"خطأ في مهمة النبضات: {e}", "system", "heartbeat")
            await asyncio.sleep(60)  # انتظار قصير عند الخطأ

async def executor_heartbeat_task():
    """مهمة إرسال النبضات الدورية للبوت المنفذ"""
    safe_log_info("بدء مهمة النبضات الدورية للبوت المنفذ كل ساعة", "system", "executor_heartbeat")
    
    while True:
        try:
            # انتظار الفاصل الزمني المحدد
            await asyncio.sleep(EXECUTOR_HEARTBEAT_INTERVAL)
            
            # إرسال النبضة
            success = await executor_client.send_heartbeat()
            
            if success:
                safe_log_info("✅ تم إرسال النبضة للبوت المنفذ بنجاح", "system", "executor_heartbeat")
            else:
                safe_log_error("❌ فشل إرسال النبضة للبوت المنفذ", "system", "executor_heartbeat")
                
        except Exception as e:
            safe_log_error(f"❌ خطأ في مهمة نبضات المنفذ: {e}", "system", "executor_heartbeat")
            await asyncio.sleep(300)  # انتظار 5 دقائق عند الخطأ

# endpoints للـ API
@app.get("/")
async def root():
    return {
        "message": "ماسح القمم والقيعان للكريبتو",
        "version": "2.2.0",
        "supported_coins": list(SUPPORTED_COINS.keys()),
        "timeframes": TIMEFRAMES,
        "scan_interval": f"{SCAN_INTERVAL} ثانية",
        "heartbeat_interval": f"{HEARTBEAT_INTERVAL} ثانية",
        "executor_heartbeat_interval": f"{EXECUTOR_HEARTBEAT_INTERVAL} ثانية",
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
        "current_session": get_current_session()["name"],
        "executor_enabled": EXECUTE_TRADES,
        "executor_connected": system_stats["executor_connected"]
    }

@app.get("/health")
async def health_check():
    current_session = get_current_session()
    executor_health = await executor_client.health_check()
    
    return {
        "status": "نشط",
        "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
        "current_session": current_session["name"],
        "session_weight": current_session["weight"],
        "cache_size": len(data_fetcher.cache),
        "system_stats": system_stats,
        "uptime": time.time() - system_stats["start_time"],
        "executor_connected": executor_health,
        "trade_execution_enabled": EXECUTE_TRADES
    }

@app.get("/scan/{coin}")
async def scan_coin(coin: str, timeframe: str = "15m"):
    if coin not in SUPPORTED_COINS:
        raise HTTPException(404, "العملة غير مدعومة")
    if timeframe not in TIMEFRAMES:
        raise HTTPException(404, "الإطار الزمني غير مدعوم")
    
    coin_data = SUPPORTED_COINS[coin]
    data = await data_fetcher.get_coin_data(coin_data, timeframe)
    
    return {
        "coin": coin,
        "timeframe": timeframe,
        "price": data['price'],
        "analysis": data['analysis'],
        "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
        "current_session": get_current_session()["name"]
    }

@app.get("/session-info")
async def get_session_info():
    current_session = get_current_session()
    return {
        "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
        "current_hour": get_syria_time().hour,
        "current_session": current_session,
        "all_sessions": TRADING_SESSIONS
    }

@app.get("/system-stats")
async def get_system_stats():
    """الحصول على إحصائيات النظام"""
    uptime_seconds = time.time() - system_stats["start_time"]
    
    # تنسيق مدة التشغيل
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    
    if days > 0:
        uptime_str = f"{days} يوم, {hours} ساعة, {minutes} دقيقة"
    elif hours > 0:
        uptime_str = f"{hours} ساعة, {minutes} دقيقة"
    else:
        uptime_str = f"{minutes} دقيقة"
    
    return {
        "system_stats": system_stats,
        "uptime": uptime_str,
        "uptime_seconds": uptime_seconds,
        "current_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
        "cache_size": len(data_fetcher.cache),
        "supported_coins": len(SUPPORTED_COINS),
        "timeframes": TIMEFRAMES,
        "executor_connected": system_stats["executor_connected"],
        "trade_execution_enabled": EXECUTE_TRADES
    }

@app.get("/test-telegram")
async def test_telegram():
    """اختبار إرسال رسالة تجريبية للتليجرام"""
    try:
        test_message = """
🧪 *اختبار البوت - ماسح القمم والقيعان v2.2*

✅ *الحالة:* البوت يعمل بشكل صحيح
🕒 *الوقت:* {}
🌍 *الجلسة:* {} {}
⚡ *الإصدار:* 2.2.0

📊 *العملات المدعومة:* {}
⏰ *الأطر الزمنية:* {}

🔧 *الإعدادات:*
• عتبة الثقة: {} نقطة (إشارات متوسطة وفوق)
• فاصل المسح: {} ثانية
• فاصل النبضات: {} ثانية
• فاصل نبضات المنفذ: {} ثانية
• التوقيت: سوريا (GMT+3)
• تنفيذ الصفقات: {}
• اتصال المنفذ: {}

🎯 *الوظيفة:* كشف القمم والقيعان تلقائياً وإرسال إشارات التنفيذ
        """.format(
            get_syria_time().strftime('%H:%M %d/%m/%Y'),
            get_current_session()["emoji"],
            get_current_session()["name"],
            ", ".join(SUPPORTED_COINS.keys()),
            ", ".join(TIMEFRAMES),
            CONFIDENCE_THRESHOLD,
            SCAN_INTERVAL,
            HEARTBEAT_INTERVAL,
            EXECUTOR_HEARTBEAT_INTERVAL,
            "مفعل" if EXECUTE_TRADES else "معطل",
            "متصل" if system_stats["executor_connected"] else "غير متصل"
        )

        async with httpx.AsyncClient() as client:
            payload = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': test_message,
                'parse_mode': 'Markdown'
            }
            
            response = await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", 
                                       json=payload, timeout=10.0)
            
            if response.status_code == 200:
                return {"status": "success", "message": "تم إرسال رسالة الاختبار بنجاح"}
            else:
                return {"status": "error", "code": response.status_code, "details": response.text}
                
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/send-heartbeat")
async def send_heartbeat_manual():
    """إرسال نبضة يدوية"""
    try:
        success = await notifier.send_heartbeat()
        if success:
            return {"status": "success", "message": "تم إرسال النبضة بنجاح"}
        else:
            return {"status": "error", "message": "فشل إرسال النبضة"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/test-executor")
async def test_executor_connection():
    """اختبار الاتصال بالبوت المنفذ"""
    try:
        is_healthy = await executor_client.health_check()
        system_stats["executor_connected"] = is_healthy
        
        return {
            "status": "success" if is_healthy else "error",
            "executor_connected": is_healthy,
            "executor_url": EXECUTOR_BOT_URL,
            "trade_execution_enabled": EXECUTE_TRADES,
            "message": "البوت المنفذ متصل" if is_healthy else "البوت المنفذ غير متصل"
        }
    except Exception as e:
        system_stats["executor_connected"] = False
        return {"status": "error", "message": str(e)}

@app.get("/test-executor-heartbeat")
async def test_executor_heartbeat():
    """اختبار إرسال نبضة يدوية للبوت المنفذ"""
    try:
        success = await executor_client.send_heartbeat()
        if success:
            return {
                "status": "success", 
                "message": "تم إرسال النبضة للبوت المنفذ بنجاح",
                "executor_connected": system_stats["executor_connected"],
                "total_heartbeats_sent": system_stats["total_heartbeats_sent"],
                "last_executor_heartbeat": system_stats["last_executor_heartbeat"],
                "timestamp": get_syria_time().strftime('%H:%M %d/%m/%Y')
            }
        else:
            return {
                "status": "error", 
                "message": "فشل إرسال النبضة للبوت المنفذ",
                "executor_connected": system_stats["executor_connected"],
                "timestamp": get_syria_time().strftime('%H:%M %d/%m/%Y')
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# وقت بدء التشغيل
start_time = time.time()

@app.on_event("startup")
async def startup_event():
    safe_log_info("بدء تشغيل ماسح القمم والقيعان الإصدار 2.2", "system", "startup")
    safe_log_info(f"العملات المدعومة: {list(SUPPORTED_COINS.keys())}", "system", "config")
    safe_log_info(f"الأطر الزمنية: {TIMEFRAMES}", "system", "config")
    safe_log_info(f"فاصل المسح: {SCAN_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"فاصل النبضات: {HEARTBEAT_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"فاصل نبضات المنفذ: {EXECUTOR_HEARTBEAT_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"حد الثقة: {CONFIDENCE_THRESHOLD} نقطة", "system", "config")
    safe_log_info(f"التوقيت: سوريا (GMT+3)", "system", "config")
    safe_log_info(f"تنفيذ الصفقات: {'مفعل' if EXECUTE_TRADES else 'معطل'}", "system", "config")
    safe_log_info(f"رابط البوت المنفذ: {EXECUTOR_BOT_URL}", "system", "config")
    
    # فحص اتصال البوت المنفذ
    executor_health = await executor_client.health_check()
    safe_log_info(f"اتصال البوت المنفذ: {'متصل' if executor_health else 'غير متصل'}", "system", "config")
    
    # بدء المهام
    asyncio.create_task(market_scanner_task())
    asyncio.create_task(health_check_task())
    asyncio.create_task(heartbeat_task())
    asyncio.create_task(executor_heartbeat_task())  # ⬅️ جديد
    
    safe_log_info("✅ بدأت مهام المسح والفحص الصحي والنبضات", "system", "startup")

@app.on_event("shutdown")
async def shutdown_event():
    safe_log_info("إيقاف ماسح السوق", "system", "shutdown")
    await data_fetcher.close()
    await executor_client.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
