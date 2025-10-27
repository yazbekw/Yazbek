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
# الإعدادات الرئيسية المحسنة - تقليل التضارب وتحسين الدقة
# =============================================================================

# إعدادات التطبيق
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PORT = int(os.getenv("PORT", 8000))

# إعدادات البوت المنفذ
EXECUTOR_BOT_URL = os.getenv("EXECUTOR_BOT_URL", "https://your-executor-bot.onrender.com")
EXECUTOR_BOT_API_KEY = os.getenv("EXECUTOR_BOT_API_KEY", "")
EXECUTE_TRADES = os.getenv("EXECUTE_TRADES", "false").lower() == "true"

# إعدادات التداول المحسنة
SCAN_INTERVAL = 900  # 30 دقيقة بين كل فحص
HEARTBEAT_INTERVAL = 1800  # 30 دقيقة بين كل نبضة
EXECUTOR_HEARTBEAT_INTERVAL = 3600  # ساعة بين كل نبضة للمنفذ
CONFIDENCE_THRESHOLD = 35  # عتبة الثقة الأساسية

# =============================================================================
# النظام المحسن للأوزان وتقليل التضارب
# =============================================================================

ENHANCED_INDICATOR_WEIGHTS = {
    "MOMENTUM": {
        "weight": 35,
        "components": {
            "rsi": 12,           # تقليل تأثير RSI المنفرد
            "stochastic": 10,    # تقليل Stochastic  
            "macd": 13,          # زيادة وزن MACD الأكثر استقراراً
        }
    },
    "PRICE_ACTION": {
        "weight": 30,
        "components": {
            "candle_patterns": 15,  # زيادة وزن أنماط الشموع
            "moving_averages": 10,  # زيادة أهمية المتوسطات
            "trend_strength": 5     # جديد: قوة الاتجاه
        }
    },
    "KEY_LEVELS": {
        "weight": 25,
        "components": {
            "support_resistance": 10, # إعادة توازن
            "fibonacci": 9,          # تقليل فيبوناتشي
            "pivot_points": 6        # جديد: نقاط المحور
        }
    },
    "VOLUME_CONFIRMATION": {
        "weight": 25,
        "components": {
            "volume_trend": 15,      # زيادة وزن اتجاه الحجم
            "volume_spike": 10       # جديد: قمم الحجم
        }
    },
    "TREND_ALIGNMENT": {             # قسم جديد كلياً
        "weight": 15,
        "components": {
            "multi_timeframe": 8,    # محاذاة الإطارات الزمنية
            "market_structure": 7    # هيكل السوق العام
        }
    }
}

# إعدادات إدارة التضارب المحسنة
CONFLICT_MANAGEMENT = {
    "ENABLE_ENHANCED_FILTERING": True,
    "MAX_CONFLICT_PENALTY": 10,
    "CORE_CONFLICT_THRESHOLD": 2,
    "TREND_ALIGNMENT_BONUS": True,
    "REQUIRE_VOLUME_CONFIRMATION": True,
    "MIN_CONSISTENCY_SCORE": 6,
    "CONFLICT_RESOLUTION_STRATEGY": "enhanced"  # 'basic' or 'enhanced'
}

# إعدادات نظام التأكيد المحسن
PRIMARY_TIMEFRAME = '1h'
CONFIRMATION_TIMEFRAME = '15m'
CONFIRMATION_THRESHOLD = 30
CONFIRMATION_BONUS = 10
MIN_CONFIRMATION_GAP = 3

# إعدادات تصفية الإشارات المتضاربة المحسنة
MIN_SIGNAL_GAP = 8
CONFLICTING_SIGNAL_PENALTY = 15

# إعدادات التحسينات الطفيفة المحسنة
ENHANCEMENT_SETTINGS = {
    'ENABLE_QUICK_ENHANCE': True,
    'MIN_STRENGTH_FOR_ENHANCE': 35,
    'MAX_ENHANCEMENT_BONUS': 10,
    'ENABLE_TREND_ALIGNMENT': True
}

# الأصول والأطر الزمنية
SUPPORTED_COINS = {
    'eth': {'name': 'Ethereum', 'binance_symbol': 'ETHUSDT', 'symbol': 'ETH'},
    'bnb': {'name': 'Binance Coin', 'binance_symbol': 'BNBUSDT', 'symbol': 'BNB'},
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

# مستويات التنبيه المحسنة
ALERT_LEVELS = {
    "LOW": {"min": 0, "max": 35, "emoji": "⚪", "send_alert": False, "color": "gray"},
    "MEDIUM": {"min": 36, "max": 49, "emoji": "🟡", "send_alert": True, "color": "gold"},
    "HIGH": {"min": 50, "max": 65, "emoji": "🟠", "send_alert": True, "color": "darkorange"},
    "STRONG": {"min": 66, "max": 80, "emoji": "🔴", "send_alert": True, "color": "red"},
    "EXTREME": {"min": 81, "max": 100, "emoji": "💥", "send_alert": True, "color": "darkred"}
}

# ألوان التصميم
COLORS = {
    "top": {"primary": "#FF4444", "secondary": "#FFCCCB", "bg": "#FFF5F5"},
    "bottom": {"primary": "#00C851", "secondary": "#C8F7C5", "bg": "#F5FFF5"},
    "neutral": {"primary": "#4A90E2", "secondary": "#D1E8FF", "bg": "#F5F9FF"}
}

# =============================================================================
# نهاية الإعدادات الرئيسية المحسنة
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

app = FastAPI(title="Crypto Top/Bottom Scanner", version="3.0.0")  # تحديث الإصدار

# إحصائيات النظام المحدثة
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
    "conflicting_signals_filtered": 0,
    "enhanced_signals_sent": 0,
    "confirmation_bonus_applied": 0,
    "relaxed_signals_sent": 0,
    "trend_alignment_applied": 0,  # جديد
    "conflict_penalties_applied": 0  # جديد
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
    
    def __init__(self):
        self.conflict_stats = {
            "total_conflicts_detected": 0,
            "conflicts_resolved": 0,
            "signals_filtered": 0
        }
    
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
        
        # حساب جسم الشمعة وذيلها
        current_body = abs(current_close - prev_close)
        current_upper_wick = current_high - max(current_close, prev_close)
        current_lower_wick = min(current_close, prev_close) - current_low
        
        is_hammer = (current_lower_wick > 1.8 * current_body and
                    current_upper_wick < current_body * 0.4 and
                    current_close > prev_close)
        
        is_shooting_star = (current_upper_wick > 1.8 * current_body and 
                           current_lower_wick < current_body * 0.4 and
                           current_close < prev_close)
        
        is_bullish_engulfing = (prev_close < prev2_close and current_close > prev_close and abs(current_close - prev_close) > current_body * 0.5)
        is_bearish_engulfing = (prev_close > prev2_close and current_close < prev_close and abs(current_close - prev_close) > current_body * 0.5)
        
        body_ratio = current_body / (current_high - current_low) if (current_high - current_low) > 0 else 1
        is_doji = body_ratio < 0.15
        
        if is_hammer:
            return {"pattern": "hammer", "strength": 10, "description": "🔨 مطرقة - إشارة قاع", "direction": "bottom"}
        elif is_shooting_star:
            return {"pattern": "shooting_star", "strength": 10, "description": "💫 نجم ساقط - إشارة قمة", "direction": "top"}
        elif is_bullish_engulfing:
            return {"pattern": "bullish_engulfing", "strength": 8, "description": "🟢 ابتلاع صاعد - إشارة قاع", "direction": "bottom"}
        elif is_bearish_engulfing:
            return {"pattern": "bearish_engulfing", "strength": 8, "description": "🔴 ابتلاع هابط - إشارة قمة", "direction": "top"}
        elif is_doji:
            return {"pattern": "doji", "strength": 4, "description": "⚪ دوجي - تردد في السوق", "direction": "neutral"}
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
        
        if distance_to_support < 0.015:
            strength = 10
            direction = "bottom"
        elif distance_to_support < 0.025:
            strength = 6
            direction = "bottom"
        elif distance_to_support < 0.035:
            strength = 3
            direction = "bottom"
        elif distance_to_resistance < 0.015:
            strength = 10
            direction = "top"
        elif distance_to_resistance < 0.025:
            strength = 6
            direction = "top"
        elif distance_to_resistance < 0.035:
            strength = 3
            direction = "top"
            
        return {
            "support": recent_lows,
            "resistance": recent_highs,
            "strength": strength,
            "direction": direction,
            "current_price": current_price,
            "distance_percent": closest_distance
        }

    def calculate_pivot_points(self, high: float, low: float, close: float) -> Dict[str, float]:
        """حساب نقاط المحور"""
        pivot = (high + low + close) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        
        return {
            'pivot': pivot,
            'r1': r1,
            'r2': r2,
            's1': s1,
            's2': s2
        }

    def volume_analysis(self, volumes: List[float], price_trend: str, signal_type: str) -> Dict[str, Any]:
        """تحليل حجم محسن"""
        if len(volumes) < 10:
            return {"trend": "stable", "strength": 0, "description": "⚪ حجم مستقر", "volume_ratio": 1.0}
        
        recent_volume = np.mean(volumes[-3:])
        previous_volume = np.mean(volumes[-6:-3])
        volume_ratio = recent_volume / (previous_volume + 1e-10)
        
        strength = 0
        if volume_ratio > 2.2:
            strength = 10
            trend_desc = "📈 حجم متزايد بقوة"
        elif volume_ratio > 1.6:
            strength = 7
            trend_desc = "📈 حجم متزايد"
        elif volume_ratio > 1.2:
            strength = 4
            trend_desc = "📈 حجم متزايد قليلاً"
        elif volume_ratio < 0.5:
            strength = 6
            trend_desc = "📉 حجم متراجع بقوة"
        elif volume_ratio < 0.75:
            strength = 3
            trend_desc = "📉 حجم متراجع"
        else:
            strength = 1
            trend_desc = "⚪ حجم مستقر"
        
        # تحليل قمم الحجم
        volume_spike_bonus = 0
        if len(volumes) >= 20:
            avg_volume = np.mean(volumes[-20:])
            if recent_volume > avg_volume * 2.5:
                volume_spike_bonus = 8
                trend_desc += " - 📊 قمة حجم"
            elif recent_volume > avg_volume * 1.8:
                volume_spike_bonus = 4
                trend_desc += " - 📊 ارتفاع حجم"
        
        strength += volume_spike_bonus
        
        confirmation_bonus = 0
        if signal_type == "bottom" and volume_ratio > 1.3 and price_trend == "down":
            confirmation_bonus = 4
            trend_desc += " - مؤشر قاع"
        elif signal_type == "top" and volume_ratio > 1.3 and price_trend == "up":
            confirmation_bonus = 4
            trend_desc += " - مؤشر قمة"
        
        return {
            "trend": "rising" if volume_ratio > 1.1 else "falling" if volume_ratio < 0.9 else "stable",
            "strength": strength + confirmation_bonus,
            "description": trend_desc,
            "volume_ratio": volume_ratio,
            "volume_spike_bonus": volume_spike_bonus,
            "confirmation_bonus": confirmation_bonus
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
        if closest_level in ['0.0', '0.236', '0.382', '0.618', '0.786', '1.0'] and min_distance < 0.025:
            strength = 6
        elif closest_level == '0.5' and min_distance < 0.025:
            strength = 3
        
        return {
            'closest_level': closest_level,
            'distance': min_distance,
            'strength': strength
        }

    def _get_trend_direction(self, prices: List[float]) -> str:
        """تحديد اتجاه الاتجاه"""
        if len(prices) < 5:
            return "neutral"
        
        short_trend = (prices[-1] - prices[-5]) / prices[-5] * 100
        if short_trend > 0.5:
            return "up"
        elif short_trend < -0.5:
            return "down"
        else:
            return "neutral"

    def _analyze_market_structure(self, prices: List[float]) -> str:
        """تحليل هيكل السوق"""
        if len(prices) < 20:
            return "neutral"
    
        # تحليل القمم والقيعان
        highs = []
        lows = []
    
        # إنشاء قوائم القمم والقيعان
        for i in range(3, len(prices)-3):
            high_segment = prices[i-3:i+1]
            low_segment = prices[i-3:i+1]
            highs.append(max(high_segment))
            lows.append(min(low_segment))
    
        # حساب القمم الأعلى والقيعان الأدنى
        higher_highs = 0
        lower_lows = 0
    
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                higher_highs += 1
    
        for i in range(1, len(lows)):
            if lows[i] < lows[i-1]:
                lower_lows += 1
    
        if higher_highs > lower_lows + 2:
            return "uptrend"
        elif lower_lows > higher_highs + 2:
            return "downtrend"
        else:
            return "ranging"

    def _calculate_trend_alignment_scores(self, prices: List[float]) -> Dict[str, int]:
        """حساب نقاط محاذاة الاتجاه - تقليل التضارب"""
        
        if len(prices) < 20:
            return {"top": 0, "bottom": 0}
        
        # تحليل الاتجاه متعدد الإطارات
        short_trend = self._get_trend_direction(prices[-10:])
        medium_trend = self._get_trend_direction(prices[-20:])
        
        top_score = 0
        bottom_score = 0
        
        # مكافأة محاذاة الاتجاهات
        if short_trend == "down" and medium_trend == "down":
            top_score += 8  # الاتجاه هابط - تعزيز إشارات القمة
        elif short_trend == "up" and medium_trend == "up":  
            bottom_score += 8  # الاتجاه صاعد - تعزيز إشارات القاع
        else:
            # تضارب في الاتجاهات - تخفيف جميع الإشارات
            top_score -= 3
            bottom_score -= 3
        
        # تحليل هيكل السوق
        market_structure = self._analyze_market_structure(prices)
        if market_structure == "downtrend":
            top_score += 4
            bottom_score -= 2
        elif market_structure == "uptrend":
            bottom_score += 4  
            top_score -= 2
        
        return {
            "top": max(0, top_score),
            "bottom": max(0, bottom_score)
        }

    def _calculate_momentum_scores(self, indicators: Dict) -> Dict[str, int]:
        """حساب نقاط الزخم مع النظام الجديد"""
        top_score = 0
        bottom_score = 0
        
        rsi = indicators.get('rsi', 50)
        stoch = indicators.get('stochastic', {'k': 50, 'd': 50})
        macd = indicators.get('macd', {'histogram': 0})
        
        # RSI (12 نقطة)
        if rsi > 75: top_score += 8
        elif rsi > 65: top_score += 5
        elif rsi > 55: top_score += 2
        
        if rsi < 25: bottom_score += 8
        elif rsi < 35: bottom_score += 5
        elif rsi < 45: bottom_score += 2
        
        # Stochastic (10 نقاط)
        stoch_k = stoch.get('k', 50)
        if stoch_k > 80: top_score += 6
        elif stoch_k > 70: top_score += 4
        elif stoch_k > 60: top_score += 2
        
        if stoch_k < 20: bottom_score += 6
        elif stoch_k < 30: bottom_score += 4
        elif stoch_k < 40: bottom_score += 2
        
        # MACD (13 نقطة)
        macd_hist = macd.get('histogram', 0)
        if macd_hist < -0.015: top_score += 8
        elif macd_hist < -0.008: top_score += 5
        elif macd_hist < 0: top_score += 2
        
        if macd_hist > 0.015: bottom_score += 8
        elif macd_hist > 0.008: bottom_score += 5
        elif macd_hist > 0: bottom_score += 2
        
        return {"top": top_score, "bottom": bottom_score}

    def _calculate_price_action_scores(self, indicators: Dict, current_price: float) -> Dict[str, int]:
        """حساب نقاط حركة السعر مع النظام الجديد"""
        top_score = 0
        bottom_score = 0
        
        candle_pattern = indicators.get('candle_pattern', {})
        moving_averages = indicators.get('moving_averages', {})
        
        # أنماط الشموع (15 نقطة)
        if candle_pattern.get('direction') == "top":
            top_score += min(15, candle_pattern.get('strength', 0))
        elif candle_pattern.get('direction') == "bottom":
            bottom_score += min(15, candle_pattern.get('strength', 0))
        
        # المتوسطات المتحركة (10 نقاط)
        ema_20 = moving_averages.get('ema_20', current_price)
        ema_50 = moving_averages.get('ema_50', current_price)
        
        if current_price < ema_20 and current_price < ema_50:
            top_score += 8
        elif current_price < ema_20:
            top_score += 4
        
        if current_price > ema_20 and current_price > ema_50:
            bottom_score += 8
        elif current_price > ema_20:
            bottom_score += 4
        
        # قوة الاتجاه (5 نقاط)
        trend_data = indicators.get('trend_analysis', {})
        trend_strength = trend_data.get('strength', 0)
        if trend_data.get('trend') == "bearish":
            top_score += min(5, trend_strength // 2)
        elif trend_data.get('trend') == "bullish":
            bottom_score += min(5, trend_strength // 2)
        
        return {"top": top_score, "bottom": bottom_score}

    def _calculate_key_levels_scores(self, indicators: Dict) -> Dict[str, int]:
        """حساب نقاط المستويات الرئيسية مع النظام الجديد"""
        top_score = 0
        bottom_score = 0
        
        support_resistance = indicators.get('support_resistance', {})
        fibonacci = indicators.get('fibonacci', {})
        
        # الدعم والمقاومة (15 نقطة)
        if support_resistance.get('direction') == "top":
            top_score += support_resistance.get('strength', 0)
        elif support_resistance.get('direction') == "bottom":
            bottom_score += support_resistance.get('strength', 0)
        
        # فيبوناتشي (7 نقاط)
        fib_strength = fibonacci.get('strength', 0)
        fib_level = fibonacci.get('closest_level')
        
        if fib_level in ['0.618', '0.786', '1.0']:
            top_score += fib_strength
        elif fib_level in ['0.0', '0.236', '0.382']:
            bottom_score += fib_strength
        
        # نقاط المحور (3 نقاط)
        pivot_data = indicators.get('pivot_points', {})
        current_price = support_resistance.get('current_price', 0)
        if pivot_data:
            r1 = pivot_data.get('r1', current_price)
            s1 = pivot_data.get('s1', current_price)
            
            if abs(current_price - r1) / current_price < 0.01:
                top_score += 2
            if abs(current_price - s1) / current_price < 0.01:
                bottom_score += 2
        
        return {"top": top_score, "bottom": bottom_score}

    def _calculate_volume_scores(self, indicators: Dict, signal_type: str) -> Dict[str, int]:
        """حساب نقاط الحجم مع النظام الجديد"""
        top_score = 0
        bottom_score = 0
        
        volume_data = indicators.get('volume_trend', {})
        volume_strength = volume_data.get('strength', 0)
        
        # اتجاه الحجم (15 نقطة)
        if signal_type == "top":
            top_score += min(15, volume_strength)
        else:
            bottom_score += min(15, volume_strength)
        
        # قمم الحجم (10 نقاط)
        volume_spike_bonus = volume_data.get('volume_spike_bonus', 0)
        top_score += volume_spike_bonus
        bottom_score += volume_spike_bonus
        
        return {"top": top_score, "bottom": bottom_score}

    def calculate_enhanced_scores(self, indicators: Dict, current_price: float, prices: List[float], signal_type: str) -> Dict[str, Any]:
        """نظام حساب محسن يستغل كامل النقاط بشكل صحيح"""
    
        try:
            # حساب النقاط من كل قسم
            momentum_scores = self._calculate_momentum_scores(indicators)
            price_action_scores = self._calculate_price_action_scores(indicators, current_price)
            key_levels_scores = self._calculate_key_levels_scores(indicators)
            volume_scores = self._calculate_volume_scores(indicators, signal_type)
            trend_scores = self._calculate_trend_alignment_scores(prices)
        
            # تجميع النقاط الأساسية (الحد الأقصى النظري = 130 نقطة)
            base_top_score = (momentum_scores["top"] + price_action_scores["top"] + 
                             key_levels_scores["top"] + volume_scores["top"] + trend_scores["top"])
        
            base_bottom_score = (momentum_scores["bottom"] + price_action_scores["bottom"] + 
                               key_levels_scores["bottom"] + volume_scores["bottom"] + trend_scores["bottom"])
        
            # تحويل النقاط إلى مقياس 0-100 مع استغلال كامل النطاق
            max_possible_score = 130  # 35+30+25+25+15
        
            scaled_top_score = int((base_top_score / max_possible_score) * 100)
            scaled_bottom_score = int((base_bottom_score / max_possible_score) * 100)
        
            # تطبيق وزن الجلسة على النتيجة المحولة
            session_weight = get_session_weight()
            final_top_score = int(scaled_top_score * session_weight)
            final_bottom_score = int(scaled_bottom_score * session_weight)
        
            # تسجيل تفاصيل الحساب للتتبع
            safe_log_info(f"حساب النقاط المحسن - قاعدة: قمة={base_top_score}, قاع={base_bottom_score} -> محولة: قمة={scaled_top_score}, قاع={scaled_bottom_score} -> نهائية: قمة={final_top_score}, قاع={final_bottom_score} (وزن الجلسة: {session_weight})", 
                         "system", "score_calculation")
        
            return {
                "top_score": min(final_top_score, 100),
                "bottom_score": min(final_bottom_score, 100),
                "breakdown": {
                    "momentum": momentum_scores,
                    "price_action": price_action_scores,
                    "key_levels": key_levels_scores,
                    "volume": volume_scores,
                    "trend_alignment": trend_scores,
                    "session_weight": session_weight,
                    "base_scores": {
                        "top": base_top_score,
                        "bottom": base_bottom_score,
                        "max_possible": max_possible_score
                    },
                    "scaled_scores": {
                        "top": scaled_top_score,
                        "bottom": scaled_bottom_score
                    }
                }
            }
        
        except Exception as e:
            safe_log_error(f"خطأ في حساب النقاط المحسن: {e}", "system", "score_calculation")
            return {
                "top_score": 0,
                "bottom_score": 0,
                "breakdown": {}
            }
        
    
        

    def enhanced_conflict_filter(self, analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """مرشح تضارب محسن يعتمد على النظام الجديد"""
        
        if not CONFLICT_MANAGEMENT["ENABLE_ENHANCED_FILTERING"]:
            return analysis
        
        breakdown = analysis.get("breakdown", {})
        
        # 1. فحص تضارب المكونات الأساسية
        momentum_conflict = self._check_momentum_conflict(breakdown.get("momentum", {}))
        price_action_conflict = self._check_price_action_conflict(breakdown.get("price_action", {}))
        
        # 2. إذا كان هناك تضارب قوي في المكونات الأساسية
        if momentum_conflict and price_action_conflict:
            self.conflict_stats["signals_filtered"] += 1
            safe_log_info("🛑 تصفية إشارة due to core indicator conflict", "system", "conflict_filter")
            return None
        
        # 3. تطبيق عقوبة التضارب
        conflict_penalty = self._calculate_conflict_penalty(breakdown)
        if conflict_penalty > 0:
            analysis["top_score"] = max(0, analysis["top_score"] - conflict_penalty)
            analysis["bottom_score"] = max(0, analysis["bottom_score"] - conflict_penalty)
            analysis["conflict_penalty_applied"] = conflict_penalty
            system_stats["conflict_penalties_applied"] += 1
        
        self.conflict_stats["conflicts_resolved"] += 1
        return analysis

    def _check_momentum_conflict(self, momentum_data: Dict) -> bool:
        """التحقق من تضارب مؤشرات الزخم"""
        self.conflict_stats["total_conflicts_detected"] += 1
        
        # تحليل تباعد مؤشرات الزخم
        rsi_top = momentum_data.get('top', 0)
        rsi_bottom = momentum_data.get('bottom', 0)
        
        # تضارب عندما يكون كلا المؤشرين قويين
        if rsi_top > 8 and rsi_bottom > 8:
            return True
        
        return False

    def _check_price_action_conflict(self, price_action_data: Dict) -> bool:
        """التحقق من تضارب حركة السعر"""
        top_score = price_action_data.get('top', 0)
        bottom_score = price_action_data.get('bottom', 0)
        
        # تضارب عندما تكون إشارات حركة السعر متقاربة وقوية
        if abs(top_score - bottom_score) < 3 and (top_score > 10 or bottom_score > 10):
            return True
        
        return False

    def _calculate_conflict_penalty(self, breakdown: Dict) -> int:
        """حساب عقوبة التضارب"""
        penalty = 0
        
        momentum = breakdown.get('momentum', {})
        price_action = breakdown.get('price_action', {})
        
        # عقوبة تضارب الزخم
        if abs(momentum.get('top', 0) - momentum.get('bottom', 0)) < 5:
            penalty += 4
        
        # عقوبة تضارب حركة السعر
        if abs(price_action.get('top', 0) - price_action.get('bottom', 0)) < 4:
            penalty += 3
        
        # عقوبة تضارب الاتجاه
        trend_alignment = breakdown.get('trend_alignment', {})
        if trend_alignment.get('top', 0) > 0 and trend_alignment.get('bottom', 0) > 0:
            penalty += 2
        
        return min(penalty, CONFLICT_MANAGEMENT["MAX_CONFLICT_PENALTY"])

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
            
            # تحليل الاتجاه
            price_trend = "up" if prices[-1] > prices[-5] else "down" if prices[-1] < prices[-5] else "neutral"
            trend_analysis = self.simple_trend_analysis(prices)
            
            # تحليل الحجم المحسن
            strongest_signal_temp = "top" if rsi > 65 else "bottom" if rsi < 35 else "neutral"
            volume_analysis = self.volume_analysis(volumes, price_trend, strongest_signal_temp)
            
            # المؤشرات الإضافية
            fib_levels = self.calculate_fibonacci_levels(prices)
            pivot_points = self.calculate_pivot_points(highs[-1], lows[-1], prices[-1])
            
            # تجميع المؤشرات
            indicators = {
                "rsi": round(rsi, 2),
                "stochastic": stoch,
                "macd": macd,
                "moving_averages": moving_averages,
                "candle_pattern": candle_pattern,
                "support_resistance": support_resistance,
                "volume_trend": volume_analysis,
                "fibonacci": fib_levels,
                "pivot_points": pivot_points,
                "trend_analysis": trend_analysis
            }
            
            # استخدام النظام الجديد لحساب النقاط
            current_price = prices[-1]
            enhanced_scores = self.calculate_enhanced_scores(indicators, current_price, prices, strongest_signal_temp)
            
            # تحديد الإشارة الأقوى
            top_score = enhanced_scores["top_score"]
            bottom_score = enhanced_scores["bottom_score"]
            
            if top_score > bottom_score:
                strongest_signal = "top"
                strongest_score = top_score
            else:
                strongest_signal = "bottom"
                strongest_score = bottom_score
            
            initial_analysis = {
                "top_score": top_score,
                "bottom_score": bottom_score,
                "strongest_signal": strongest_signal,
                "strongest_score": strongest_score,
                "alert_level": get_alert_level(strongest_score),
                "indicators": indicators,
                "breakdown": enhanced_scores["breakdown"],
                "timestamp": time.time(),
                "prices": prices,
                "highs": highs,
                "lows": lows
            }
            
            # تطبيق مرشح التضارب المحسن
            filtered_analysis = self.enhanced_conflict_filter(initial_analysis)
            
            if filtered_analysis:
                system_stats["trend_alignment_applied"] += 1
                return filtered_analysis
            else:
                return self._get_empty_analysis()
            
        except Exception as e:
            safe_log_error(f"خطأ في تحليل السوق: {e}", "analyzer", "market_analysis")
            return self._get_empty_analysis()

    def simple_trend_analysis(self, prices: List[float]) -> Dict[str, Any]:
        """تحليل اتجاه بسيط"""
        if len(prices) < 10:
            return {"trend": "neutral", "strength": 0}
        
        short_trend = (prices[-1] - prices[-5]) / prices[-5] * 100
        medium_trend = (prices[-1] - prices[-10]) / prices[-10] * 100
        
        trend_strength = 0
        if abs(short_trend) > 2.5:
            trend_strength = 6
        elif abs(short_trend) > 1.2:
            trend_strength = 3
        
        if short_trend > 0.8 and medium_trend > 0.4:
            trend = "bullish"
        elif short_trend < -0.8 and medium_trend < -0.4:
            trend = "bearish"
        else:
            trend = "neutral"
        
        return {
            "trend": trend,
            "strength": trend_strength,
            "short_trend_percent": short_trend,
            "medium_trend_percent": medium_trend
        }

    def _get_empty_analysis(self) -> Dict[str, Any]:
        """تحليل افتراضي"""
        return {
            "top_score": 0,
            "bottom_score": 0,
            "strongest_signal": "none",
            "strongest_score": 0,
            "alert_level": get_alert_level(0),
            "indicators": {},
            "breakdown": {},
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
            message = self._build_enhanced_message(coin, timeframe, analysis, price)
            chart_image = self._create_beautiful_chart(coin, timeframe, prices, highs, lows, analysis, price)
            
            if chart_image:
                success = await self._send_photo_with_caption(message, chart_image)
                if success:
                    relaxed_note = " (بفضل الشروط المخففة)" if analysis.get('_relaxed') else ""
                    conflict_note = f" (عقوبة تضارب: -{analysis.get('conflict_penalty_applied', 0)} نقطة)" if analysis.get('conflict_penalty_applied', 0) > 0 else ""
                    safe_log_info(f"📨 تم إرسال إشعار{relaxed_note}{conflict_note} لـ {coin} ({timeframe}) - {strongest_signal} - {strongest_score} نقطة", 
                                coin, "telegram")
                    system_stats["total_alerts_sent"] += 1
                    return True
            else:
                success = await self._send_text_message(message)
                if success:
                    relaxed_note = " (بفضل الشروط المخففة)" if analysis.get('_relaxed') else ""
                    conflict_note = f" (عقوبة تضارب: -{analysis.get('conflict_penalty_applied', 0)} نقطة)" if analysis.get('conflict_penalty_applied', 0) > 0 else ""
                    safe_log_info(f"📨 تم إرسال إشعار نصي{relaxed_note}{conflict_note} لـ {coin} ({timeframe}) - {strongest_signal} - {strongest_score} نقطة", 
                                coin, "telegram")
                    system_stats["total_alerts_sent"] += 1
                    return True
            
            return False
                    
        except Exception as e:
            safe_log_error(f"خطأ في إرسال الإشعار: {e}", coin, "telegram")
            return False

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

📊 *إحصائيات النظام المتقدمة:*
• ⏱️ *مدة التشغيل:* `{uptime_str}`
• 🔍 *عدد عمليات المسح:* `{system_stats['total_scans']}`
• 📨 *التنبيهات المرسلة:* `{system_stats['total_alerts_sent']}`
• 📡 *الإشارات المرسلة:* `{system_stats['total_signals_sent']}`
• 💓 *نبضات المنفذ:* `{system_stats['total_heartbeats_sent']}`
• 🔗 *اتصال المنفذ:* `{'✅' if system_stats['executor_connected'] else '❌'}`
• 🚫 *إشارات متضاربة مخففة:* `{system_stats['conflicting_signals_filtered']}`
• 🎯 *إشارات محسنة:* `{system_stats['enhanced_signals_sent']}`
• 💎 *مرات تطبيق bonus:* `{system_stats['confirmation_bonus_applied']}`
• 🌟 *إشارات بفضل التخفيف:* `{system_stats['relaxed_signals_sent']}`
• 📈 *محاذاة اتجاه مطبقة:* `{system_stats['trend_alignment_applied']}`
• ⚠️ *عقوبات تضارب مطبقة:* `{system_stats['conflict_penalties_applied']}`
• 💾 *حجم الكاش:* `{len(data_fetcher.cache)}` عملة

🔄 *النظام المحسن:*
• 🎯 *تقليل التضارب:* `{CONFLICT_MANAGEMENT['ENABLE_ENHANCED_FILTERING']}`
• 📊 *محاذاة الاتجاه:* `{CONFLICT_MANAGEMENT['TREND_ALIGNMENT_BONUS']}`
• 🔊 *تأكيد الحجم:* `{CONFLICT_MANAGEMENT['REQUIRE_VOLUME_CONFIRMATION']}`

🪙 *العملات النشطة:* `{', '.join(SUPPORTED_COINS.keys())}`
⏰ *الأطر الزمنية:* `{', '.join(TIMEFRAMES)}`

🎯 *آخر تحديث:* `{system_stats['last_scan_time'] or 'لم يبدأ بعد'}`
💓 *آخر نبضة:* `{system_stats['last_heartbeat'] or 'لم يبدأ بعد'}`
🔗 *آخر نبضة منفذ:* `{system_stats['last_executor_heartbeat'] or 'لم يبدأ بعد'}`

✅ *الحالة:* النظام يعمل بشكل طبيعي مع النظام المحسن لتقليل التضارب
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

    def _build_enhanced_message(self, coin: str, timeframe: str, analysis: Dict[str, Any], price: float) -> str:
        """بناء رسالة محسنة مع تفاصيل النظام الجديد"""
        
        alert_level = analysis["alert_level"]
        strongest_signal = analysis["strongest_signal"]
        strongest_score = analysis["strongest_score"]
        indicators = analysis["indicators"]
        breakdown = analysis.get("breakdown", {})
        current_session = get_current_session()
        
        if strongest_signal == "top":
            signal_emoji = "🔴"
            signal_text = "قمة سعرية"
            signal_color = "🔴"
        else:
            signal_emoji = "🟢" 
            signal_text = "قاع سعري"
            signal_color = "🟢"
        
        message = f"{signal_emoji} *{signal_text} - {coin.upper()}* {signal_emoji}\n"
        message += "═" * 40 + "\n\n"
        
        # معلومات التضارب والعقوبات
        if analysis.get('conflict_penalty_applied', 0) > 0:
            message += f"⚠️ *ملاحظة:* تطبيق عقوبة تضارب `-{analysis['conflict_penalty_applied']} نقطة`\n\n"
        
        if analysis.get('_relaxed'):
            message += f"🌟 *ملاحظة:* هذه الإشارة مرسلة بفضل الشروط المخففة\n\n"
        
        message += f"💰 *السعر الحالي:* `${price:,.2f}`\n"
        message += f"⏰ *الإطار الزمني:* `{timeframe}`\n"
        message += f"🕒 *التوقيت السوري:* `{get_syria_time().strftime('%H:%M %d/%m/%Y')}`\n\n"
        
        message += f"🎯 *قوة الإشارة:* {alert_level['emoji']} *{strongest_score}/100*\n"
        message += f"📊 *مستوى الثقة:* `{alert_level['level']}`\n\n"
        
        # تفاصيل التحليل المحسن
        if breakdown:
            message += "📈 *تفصيل النقاط المحسنة:*\n"
            
            momentum = breakdown.get('momentum', {})
            message += f"• ⚡ الزخم: `{momentum.get('top', 0) if strongest_signal == 'top' else momentum.get('bottom', 0)}/35`\n"
            
            price_action = breakdown.get('price_action', {})
            message += f"• 📊 حركة السعر: `{price_action.get('top', 0) if strongest_signal == 'top' else price_action.get('bottom', 0)}/30`\n"
            
            key_levels = breakdown.get('key_levels', {})
            message += f"• 🎯 المستويات: `{key_levels.get('top', 0) if strongest_signal == 'top' else key_levels.get('bottom', 0)}/25`\n"
            
            volume = breakdown.get('volume', {})
            message += f"• 🔊 الحجم: `{volume.get('top', 0) if strongest_signal == 'top' else volume.get('bottom', 0)}/25`\n"
            
            trend = breakdown.get('trend_alignment', {})
            message += f"• 📈 محاذاة الاتجاه: `{trend.get('top', 0) if strongest_signal == 'top' else trend.get('bottom', 0)}/15`\n\n"
        
        if analysis.get('confirmed'):
            message += f"✅ *مؤكد بـ {CONFIRMATION_TIMEFRAME}:* `+{analysis.get('confirmation_bonus', 0)} نقطة`\n"
        if analysis.get('enhancement_bonus', 0) > 0:
            message += f"⚡ *تحسين النقاط:* `+{analysis.get('enhancement_bonus', 0)} نقطة`\n"
        message += "\n"
        
        message += f"🌍 *الجلسة:* {current_session['emoji']} {current_session['name']}\n"
        message += f"⚖️ *وزن الجلسة:* `{current_session['weight']*100}%`\n\n"
        
        message += "📊 *المؤشرات الفنية الرئيسية:*\n"
        
        if 'rsi' in indicators:
            rsi_emoji = "🔴" if indicators['rsi'] > 65 else "🟢" if indicators['rsi'] < 35 else "🟡"
            rsi_status = "تشبع شرائي" if indicators['rsi'] > 65 else "تشبع بيعي" if indicators['rsi'] < 35 else "محايد"
            message += f"• {rsi_emoji} *RSI:* `{indicators['rsi']}` ({rsi_status})\n"
        
        if 'stochastic' in indicators:
            stoch = indicators['stochastic']
            stoch_emoji = "🔴" if stoch.get('k', 50) > 75 else "🟢" if stoch.get('k', 50) < 25 else "🟡"
            stoch_status = "تشبع شرائي" if stoch.get('k', 50) > 75 else "تشبع بيعي" if stoch.get('k', 50) < 25 else "محايد"
            message += f"• {stoch_emoji} *Stochastic:* `K={stoch.get('k', 50)}, D={stoch.get('d', 50)}` ({stoch_status})\n"
        
        if 'macd' in indicators:
            macd_data = indicators['macd']
            macd_emoji = "🟢" if macd_data.get('histogram', 0) > 0 else "🔴"
            macd_trend = "صاعد" if macd_data.get('histogram', 0) > 0 else "هابط"
            message += f"• {macd_emoji} *MACD Hist:* `{macd_data.get('histogram', 0):.4f}` ({macd_trend})\n"
        
        if 'moving_averages' in indicators:
            ma_data = indicators['moving_averages']
            ema_status = "صاعد" if price > ma_data.get('ema_20', 0) and price > ma_data.get('ema_50', 0) else "هابط" if price < ma_data.get('ema_20', 0) and price < ma_data.get('ema_50', 0) else "متذبذب"
            ema_emoji = "🟢" if ema_status == "صاعد" else "🔴" if ema_status == "هابط" else "🟡"
            message += f"• {ema_emoji} *المتوسطات:* `{ema_status}`\n"
        
        if 'candle_pattern' in indicators and indicators['candle_pattern']['pattern'] != 'none':
            message += f"• 🕯️ *نمط الشموع:* {indicators['candle_pattern']['description']}\n"
        
        if 'volume_trend' in indicators:
            message += f"• 🔊 *الحجم:* {indicators['volume_trend']['description']}\n"
        
        if 'fibonacci' in indicators and indicators['fibonacci'].get('closest_level'):
            fib_level = indicators['fibonacci']['closest_level']
            fib_emoji = "🔴" if fib_level in ['0.618', '0.786', '1.0'] else "🟢"
            message += f"• {fib_emoji} *فيبوناتشي:* `مستوى {fib_level}`\n"
        
        message += "\n"
        
        if strongest_signal == "top":
            recommendation = "💡 *التوصية:* مراقبة فرص البيع والربح مع نظام إدارة المخاطر المحسن"
        else:
            recommendation = "💡 *التوصية:* مراقبة فرص الشراء والدخول مع نظام إدارة المخاطر المحسن"
        
        message += f"{recommendation}\n\n"
        
        message += "─" * 30 + "\n"
        message += f"⚡ *ماسح القمم والقيعان v3.0 - النظام المحسن*"
        
        return message

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
            
            plt.title(f'{coin.upper()} - إطار {timeframe}\nإشارة {analysis["strongest_signal"]} - قوة {analysis["strongest_score"]}/100\nالنظام المحسن v3.0', 
                     fontsize=16, fontweight='bold', color=colors["primary"], pad=20)
            
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


class ExecutorBotClient:
    """عميل للتواصل مع بوت التنفيذ - النسخة المحدثة"""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def send_trade_signal(self, signal_data: Dict[str, Any]) -> bool:
        """إرسال إشارة تداول إلى البوت المنفذ"""
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
                "source": "top_bottom_scanner_v3.0",
                "system_stats": {
                    "conflict_penalties_applied": system_stats["conflict_penalties_applied"],
                    "trend_alignment_applied": system_stats["trend_alignment_applied"],
                    "enhanced_signals_sent": system_stats["enhanced_signals_sent"]
                }
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
        """إرسال نبضة للبوت المنفذ للتحقق من الاتصال"""
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
                    "conflicting_signals_filtered": system_stats["conflicting_signals_filtered"],
                    "enhanced_signals_sent": system_stats["enhanced_signals_sent"],
                    "confirmation_bonus_applied": system_stats["confirmation_bonus_applied"],
                    "relaxed_signals_sent": system_stats["relaxed_signals_sent"],
                    "trend_alignment_applied": system_stats["trend_alignment_applied"],
                    "conflict_penalties_applied": system_stats["conflict_penalties_applied"],
                    "last_scan_time": system_stats["last_scan_time"],
                    "executor_connected": system_stats["executor_connected"]
                },
                "enhanced_system": {
                    "conflict_management": CONFLICT_MANAGEMENT,
                    "indicator_weights": ENHANCED_INDICATOR_WEIGHTS
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
                safe_log_info(f"✅ تم إرسال نبضة للبوت المنفذ بنجاح", 
                            "system", "executor_heartbeat")
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
        """فحص حالة البوت المنفذ"""
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
    """جلب البيانات من Binance - النسخة المحدثة"""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.analyzer = AdvancedMarketAnalyzer()
        self.cache = {}

    async def get_coin_data(self, coin_data: Dict[str, str], timeframe: str) -> Dict[str, Any]:
        """جلب بيانات العملة للإطار الزمني المحدد"""
        
        cache_key = f"{coin_data['binance_symbol']}_{timeframe}"
        current_time = time.time()
        
        # التحقق من الكاش
        if cache_key in self.cache:
            cache_data = self.cache[cache_key]
            if current_time - cache_data['timestamp'] < 300:  # 5 دقائق كاش
                return cache_data['data']
        
        try:
            # جلب البيانات من Binance
            data = await self._fetch_binance_data(coin_data['binance_symbol'], timeframe)
            
            if not data.get('prices'):
                safe_log_error(f"فشل جلب بيانات {timeframe} لـ {coin_data['symbol']}", 
                             coin_data['symbol'], "data_fetcher")
                return self._get_fallback_data()
            
            # تحليل البيانات باستخدام التحليل المحسن
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
            
            # تخزين في الكاش
            self.cache[cache_key] = {'data': result, 'timestamp': current_time}
            
            # تسجيل تفاصيل التحليل المحسن
            if analysis.get('breakdown'):
                breakdown = analysis['breakdown']
                safe_log_info(f"تم تحليل {coin_data['symbol']} ({timeframe}) - النظام المحسن - قمة: {analysis['top_score']} - قاع: {analysis['bottom_score']} - تفصيل: {breakdown}", 
                             coin_data['symbol'], "enhanced_analyzer")
            else:
                safe_log_info(f"تم تحليل {coin_data['symbol']} ({timeframe}) - قمة: {analysis['top_score']} - قاع: {analysis['bottom_score']}", 
                             coin_data['symbol'], "analyzer")
            
            return result
                
        except Exception as e:
            safe_log_error(f"خطأ في جلب بيانات {coin_data['symbol']}: {e}", 
                         coin_data['symbol'], "data_fetcher")
            return self._get_fallback_data()

    async def _fetch_binance_data(self, symbol: str, interval: str) -> Dict[str, List[float]]:
        """جلب البيانات من Binance API"""
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=100"
        
        try:
            response = await self.client.get(url)
            if response.status_code == 200:
                data = response.json()
                return {
                    'prices': [float(item[4]) for item in data],  # Close prices
                    'highs': [float(item[2]) for item in data],   # High prices
                    'lows': [float(item[3]) for item in data],    # Low prices
                    'volumes': [float(item[5]) for item in data]  # Volumes
                }
        except Exception as e:
            safe_log_error(f"خطأ في جلب البيانات من Binance: {e}", symbol, "binance")
        
        return {'prices': [], 'highs': [], 'lows': [], 'volumes': []}

    def _get_fallback_data(self) -> Dict[str, Any]:
        """بيانات افتراضية عند فشل الجلب"""
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


# =============================================================================
# الوظائف المساعدة والمهام
# =============================================================================

async def prepare_trade_signal(coin_key: str, coin_data: Dict, timeframe: str, 
                             data: Dict, analysis: Dict) -> Optional[Dict[str, Any]]:
    """تحضير بيانات إشارة التداول للبوت المنفذ"""
    try:
        signal_type = analysis["strongest_signal"]  # 'top' or 'bottom'
        score = analysis["strongest_score"]
        
        # تحديد اتجاه الصفقة
        if signal_type == "top":
            action = "SELL"
            reason = "إشارة قمة سعرية قوية - النظام المحسن v3.0"
        else:  # bottom
            action = "BUY" 
            reason = "إشارة قاع سعري قوية - النظام المحسن v3.0"
        
        # تحضير بيانات الإشارة
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
                "stoch_k": analysis["indicators"].get("stochastic", {}).get("k", 0),
                "stoch_d": analysis["indicators"].get("stochastic", {}).get("d", 0),
                "macd_histogram": analysis["indicators"].get("macd", {}).get("histogram", 0),
                "ema_20": analysis["indicators"].get("moving_averages", {}).get("ema_20", 0),
                "ema_50": analysis["indicators"].get("moving_averages", {}).get("ema_50", 0),
                "candle_pattern": analysis["indicators"].get("candle_pattern", {}),
                "volume_trend": analysis["indicators"].get("volume_trend", {}),
                "session_weight": analysis.get("breakdown", {}).get("session_weight", 1.0),
                "conflict_penalty": analysis.get("conflict_penalty_applied", 0)
            },
            "breakdown": analysis.get("breakdown", {}),
            "timestamp": time.time(),
            "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
            "current_session": get_current_session()["name"],
            "system_version": "3.0.0"
        }
        
        return signal_data
        
    except Exception as e:
        safe_log_error(f"خطأ في تحضير إشارة التداول: {e}", coin_key, "signal_prep")
        return None


async def relaxed_confirmation_check(coin_data):
    """نسخة محسنة من نظام التأكيد"""
    try:
        # الفحص في الإطار الرئيسي
        primary_data = await data_fetcher.get_coin_data(coin_data, PRIMARY_TIMEFRAME)
        primary_signal = primary_data['analysis']
        
        if (primary_signal['strongest_score'] < CONFIDENCE_THRESHOLD - 15 or
            not primary_signal['alert_level']['send_alert']):
            return None
        
        # الفحص في إطار التأكيد
        confirmation_data = await data_fetcher.get_coin_data(coin_data, CONFIRMATION_TIMEFRAME)
        confirmation_signal = confirmation_data['analysis']
        
        confirmation_conditions = (
            primary_signal['strongest_signal'] == confirmation_signal['strongest_signal'] and
            confirmation_signal['strongest_score'] >= CONFIRMATION_THRESHOLD and
            abs(primary_signal['strongest_score'] - confirmation_signal['strongest_score']) >= MIN_CONFIRMATION_GAP
        )
        
        if confirmation_conditions:
            base_bonus = CONFIRMATION_BONUS
            strength_bonus = min(8, confirmation_signal['strongest_score'] // 12)
            total_bonus = base_bonus + strength_bonus
            
            confirmed_score = min(95, primary_signal['strongest_score'] + total_bonus)
            
            safe_log_info(f"✅ إشارة مؤكدة محسنة لـ {coin_data['symbol']}: {primary_signal['strongest_score']} → {confirmed_score} نقطة (bonus: {total_bonus})", 
                         coin_data['symbol'], "enhanced_confirmation")
            
            system_stats["confirmation_bonus_applied"] += 1
            
            return {
                **primary_signal,
                'strongest_score': confirmed_score,
                'alert_level': get_alert_level(confirmed_score),
                'confirmed': True,
                'confirmation_score': confirmation_signal['strongest_score'],
                'confirmation_bonus': total_bonus,
                'price': primary_data['price'],
                'prices': primary_data['prices'],
                'highs': primary_data['highs'],
                'lows': primary_data['lows'],
                '_relaxed': True
            }
        
        return None
            
    except Exception as e:
        safe_log_error(f"خطأ في نظام التأكيد المحسن لـ {coin_data['symbol']}: {e}", coin_data['symbol'], "enhanced_confirmation")
        return None


def relaxed_conflict_filter(analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """تصفية محسنة للإشارات المتضاربة"""
    top_score = analysis["top_score"]
    bottom_score = analysis["bottom_score"]
    
    score_gap = abs(top_score - bottom_score)
    
    if score_gap < MIN_SIGNAL_GAP:
        if top_score > bottom_score:
            adjusted_bottom = max(0, bottom_score - 8)
            safe_log_info(f"⚠️  تخفيف إشارة متضاربة - قمة: {top_score}, قاع: {adjusted_bottom}, الفرق: {score_gap}", 
                         "system", "relaxed_conflict_filter")
            system_stats["conflicting_signals_filtered"] += 1
            return {**analysis, "bottom_score": adjusted_bottom, "strongest_signal": "top", "strongest_score": top_score, "_relaxed": True}
        else:
            adjusted_top = max(0, top_score - 8)
            safe_log_info(f"⚠️  تخفيف إشارة متضاربة - قمة: {adjusted_top}, قاع: {bottom_score}, الفرق: {score_gap}", 
                         "system", "relaxed_conflict_filter")
            system_stats["conflicting_signals_filtered"] += 1
            return {**analysis, "top_score": adjusted_top, "strongest_signal": "bottom", "strongest_score": bottom_score, "_relaxed": True}
    
    if top_score > bottom_score:
        enhanced_top = min(100, top_score + 2)
        return {**analysis, "strongest_signal": "top", "strongest_score": enhanced_top}
    else:
        enhanced_bottom = min(100, bottom_score + 2)
        return {**analysis, "strongest_signal": "bottom", "strongest_score": enhanced_bottom}


def get_market_bias(prices: List[float]) -> str:
    """تحديد الاتجاه العام للسوق"""
    if len(prices) < 20:
        return "neutral"
    
    short_trend = prices[-1] - prices[-5]
    long_trend = prices[-1] - prices[-20]
    
    if short_trend > 0 and long_trend > 0:
        return "bullish"
    elif short_trend < 0 and long_trend < 0:
        return "bearish"
    else:
        return "neutral"


def apply_market_bias(analysis: Dict[str, Any], market_bias: str) -> Dict[str, Any]:
    """تطبيق تحيز السوق على النتائج"""
    if market_bias == "bullish":
        analysis["top_score"] = max(0, analysis["top_score"] - 5)
    elif market_bias == "bearish":
        analysis["bottom_score"] = max(0, analysis["bottom_score"] - 5)
    
    if analysis["top_score"] > analysis["bottom_score"]:
        analysis["strongest_signal"] = "top"
        analysis["strongest_score"] = analysis["top_score"]
    else:
        analysis["strongest_signal"] = "bottom"
        analysis["strongest_score"] = analysis["bottom_score"]
    
    analysis["alert_level"] = get_alert_level(analysis["strongest_score"])
    
    return analysis


async def relaxed_enhanced_scan(coin_key, coin_data):
    """مسح محسن يجمع كل التحسينات"""
    try:
        # استخدام نظام التأكيد المحسن
        confirmed_signal = await relaxed_confirmation_check(coin_data)
        
        if not confirmed_signal:
            return None
        
        # تطبيق تحليل الاتجاه
        trend_analysis = data_fetcher.analyzer.simple_trend_analysis(confirmed_signal['prices'])
        
        # تطبيق التصفية المحسنة
        final_signal = relaxed_conflict_filter(confirmed_signal)
        
        if final_signal and final_signal['alert_level']['send_alert']:
            relaxed_bonus = final_signal.get('_relaxed', False)
            if relaxed_bonus:
                system_stats["relaxed_signals_sent"] += 1
                safe_log_info(f"🎯 إشارة محسنة لـ {coin_data['symbol']}: {final_signal['strongest_score']} نقطة (بفضل النظام المحسن)", 
                             coin_data['symbol'], "enhanced_scan")
            else:
                safe_log_info(f"🎯 إشارة قوية لـ {coin_data['symbol']}: {final_signal['strongest_score']} نقطة", 
                             coin_data['symbol'], "enhanced_scan")
            
            system_stats["enhanced_signals_sent"] += 1
            return final_signal
        
        return None
        
    except Exception as e:
        safe_log_error(f"خطأ في المسح المحسن لـ {coin_data['symbol']}: {e}", coin_data['symbol'], "enhanced_scan")
        return None


# =============================================================================
# المهام الأساسية
# =============================================================================

async def market_scanner_task():
    """المهمة الرئيسية للمسح الضوئي مع النظام المحسن"""
    safe_log_info("بدء مهمة مسح السوق كل 30 دقيقة مع النظام المحسن v3.0", "system", "scanner")
    
    while True:
        try:
            syria_time = get_syria_time()
            current_session = get_current_session()
            
            safe_log_info(f"بدء دورة المسح - التوقيت السوري: {syria_time.strftime('%H:%M %d/%m/%Y')} - الجلسة: {current_session['name']} - النظام: v3.0", 
                         "system", "scanner")
            
            alerts_sent = 0
            signals_sent = 0
            
            for coin_key, coin_data in SUPPORTED_COINS.items():
                try:
                    # استخدام النظام المحسن
                    enhanced_signal = await relaxed_enhanced_scan(coin_key, coin_data)
                    
                    if enhanced_signal:
                        market_bias = get_market_bias(enhanced_signal['prices'])
                        enhanced_signal = apply_market_bias(enhanced_signal, market_bias)
                        
                        if not enhanced_signal.get('_filtered'):
                            filtered_signal = relaxed_conflict_filter(enhanced_signal)
                        else:
                            filtered_signal = enhanced_signal
                            
                        if filtered_signal and filtered_signal['alert_level']['send_alert']:
                            success = await notifier.send_alert(
                                coin_key, f"1h (مؤكد بـ {CONFIRMATION_TIMEFRAME})", filtered_signal, 
                                filtered_signal['price'], 
                                filtered_signal['prices'],
                                filtered_signal['highs'],
                                filtered_signal['lows']
                            )
                            
                            if success:
                                alerts_sent += 1
                                
                                signal_data = await prepare_trade_signal(
                                    coin_key, coin_data, f"1h (مؤكد بـ {CONFIRMATION_TIMEFRAME})", 
                                    {
                                        'price': filtered_signal['price'],
                                        'prices': filtered_signal['prices'],
                                        'highs': filtered_signal['highs'], 
                                        'lows': filtered_signal['lows']
                                    }, 
                                    filtered_signal
                                )
                                if signal_data:
                                    sent = await executor_client.send_trade_signal(signal_data)
                                    if sent:
                                        signals_sent += 1
                                
                                await asyncio.sleep(3)
                    
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    safe_log_error(f"خطأ في معالجة {coin_key}: {e}", coin_key, "scanner")
                    continue
            
            system_stats["total_scans"] += 1
            system_stats["last_scan_time"] = syria_time.strftime('%H:%M %d/%m/%Y')
            
            safe_log_info(f"اكتملت دورة المسح - تم إرسال {alerts_sent} تنبيه و {signals_sent} إشارة تنفيذ - النظام v3.0", 
                         "system", "scanner")
            
            await asyncio.sleep(SCAN_INTERVAL)
            
        except Exception as e:
            safe_log_error(f"خطأ في المهمة الرئيسية: {e}", "system", "scanner")
            await asyncio.sleep(60)


async def health_check_task():
    """مهمة الفحص الصحي"""
    while True:
        try:
            current_time = time.time()
            cache_size = len(data_fetcher.cache)
            current_session = get_current_session()
            
            executor_health = await executor_client.health_check()
            
            safe_log_info(f"الفحص الصحي - الكاش: {cache_size} - الجلسة: {current_session['name']} - الوزن: {current_session['weight']} - المنفذ: {'متصل' if executor_health else 'غير متصل'} - إشارات مخففة: {system_stats['conflicting_signals_filtered']} - إشارات محسنة: {system_stats['enhanced_signals_sent']} - إشارات بفضل التخفيف: {system_stats['relaxed_signals_sent']} - عقوبات تضارب: {system_stats['conflict_penalties_applied']}", 
                         "system", "health")
            
            await asyncio.sleep(300)
            
        except Exception as e:
            safe_log_error(f"خطأ في الفحص الصحي: {e}", "system", "health")
            await asyncio.sleep(60)


async def heartbeat_task():
    """مهمة إرسال النبضات الدورية"""
    safe_log_info("بدء مهمة النبضات الدورية كل 30 دقيقة - النظام v3.0", "system", "heartbeat")
    
    while True:
        try:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            
            success = await notifier.send_heartbeat()
            
            if success:
                safe_log_info("تم إرسال النبضة بنجاح - النظام v3.0", "system", "heartbeat")
            else:
                safe_log_error("فشل إرسال النبضة", "system", "heartbeat")
                
        except Exception as e:
            safe_log_error(f"خطأ في مهمة النبضات: {e}", "system", "heartbeat")
            await asyncio.sleep(60)


async def executor_heartbeat_task():
    """مهمة إرسال النبضات الدورية للبوت المنفذ"""
    safe_log_info("بدء مهمة النبضات الدورية للبوت المنفذ كل ساعة - النظام v3.0", "system", "executor_heartbeat")
    
    while True:
        try:
            await asyncio.sleep(EXECUTOR_HEARTBEAT_INTERVAL)
            
            success = await executor_client.send_heartbeat()
            
            if success:
                safe_log_info("✅ تم إرسال النبضة للبوت المنفذ بنجاح - النظام v3.0", "system", "executor_heartbeat")
            else:
                safe_log_error("❌ فشل إرسال النبضة للبوت المنفذ", "system", "executor_heartbeat")
                
        except Exception as e:
            safe_log_error(f"❌ خطأ في مهمة نبضات المنفذ: {e}", "system", "executor_heartbeat")
            await asyncio.sleep(300)


# =============================================================================
# واجهات API
# =============================================================================

@app.get("/")
async def root():
    return {
        "message": "Crypto Top/Bottom Scanner - النظام المحسن v3.0",
        "version": "3.0.0",
        "status": "running",
        "enhanced_system": True,
        "conflict_reduction": True,
        "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y')
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
        "current_session": get_current_session()["name"],
        "system_version": "3.0.0"
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
        "trade_execution_enabled": EXECUTE_TRADES,
        "conflicting_signals_filtered": system_stats["conflicting_signals_filtered"],
        "enhanced_signals_sent": system_stats["enhanced_signals_sent"],
        "confirmation_bonus_applied": system_stats["confirmation_bonus_applied"],
        "relaxed_signals_sent": system_stats["relaxed_signals_sent"],
        "trend_alignment_applied": system_stats["trend_alignment_applied"],
        "conflict_penalties_applied": system_stats["conflict_penalties_applied"],
        "enhanced_system": {
            "conflict_management": CONFLICT_MANAGEMENT,
            "indicator_weights": ENHANCED_INDICATOR_WEIGHTS,
            "version": "3.0.0"
        }
    }


@app.get("/test-telegram")
async def test_telegram():
    """اختبار إرسال رسالة تجريبية للتليجرام"""
    try:
        test_message = """
🧪 *اختبار البوت - ماسح القمم والقيعان v3.0*

✅ *الحالة:* البوت يعمل بشكل صحيح مع النظام المحسن
🕒 *الوقت:* {}
🌍 *الجلسة:* {} {}
⚡ *الإصدار:* 3.0.0 - النظام المحسن

📊 *العملات المدعومة:* {}
⏰ *الأطر الزمنية:* {}

🔧 *الإعدادات المحسنة:*
• نظام الأوزان المتطور: `مفعل`
• إدارة التضارب المحسنة: `مفعل` 
• محاذاة الاتجاه: `مفعل`
• تأكيد الحجم: `مفعل`
• عتبة الثقة: `{} نقطة`
• فاصل المسح: `{} ثانية`
• التوقيت: `سوريا (GMT+3)`
• تنفيذ الصفقات: `{}`
• اتصال المنفذ: `{}`

🎯 *الوظيفة:* كشف القمم والقيعان تلقائياً مع النظام المحسن لتقليل التضارب
        """.format(
            get_syria_time().strftime('%H:%M %d/%m/%Y'),
            get_current_session()["emoji"],
            get_current_session()["name"],
            ", ".join(SUPPORTED_COINS.keys()),
            ", ".join(TIMEFRAMES),
            CONFIDENCE_THRESHOLD,
            SCAN_INTERVAL,
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
                return {"status": "success", "message": "تم إرسال رسالة الاختبار بنجاح", "system": "v3.0"}
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
            return {"status": "success", "message": "تم إرسال النبضة بنجاح", "system": "v3.0"}
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
            "system_version": "3.0.0",
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
                "system_version": "3.0.0",
                "timestamp": get_syria_time().strftime('%H:%M %d/%m/%Y')
            }
        else:
            return {
                "status": "error", 
                "message": "فشل إرسال النبضة للبوت المنفذ",
                "executor_connected": system_stats["executor_connected"],
                "system_version": "3.0.0",
                "timestamp": get_syria_time().strftime('%H:%M %d/%m/%Y')
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# التهيئة وتشغيل التطبيق
# =============================================================================

# التهيئة العالمية
data_fetcher = BinanceDataFetcher()
notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
executor_client = ExecutorBotClient(EXECUTOR_BOT_URL, EXECUTOR_BOT_API_KEY)

# وقت بدء التشغيل
start_time = time.time()

@app.on_event("startup")
async def startup_event():
    safe_log_info("بدء تشغيل ماسح القمم والقيعان الإصدار 3.0 مع النظام المحسن", "system", "startup")
    safe_log_info(f"العملات المدعومة: {list(SUPPORTED_COINS.keys())}", "system", "config")
    safe_log_info(f"الأطر الزمنية: {TIMEFRAMES}", "system", "config")
    safe_log_info(f"فاصل المسح: {SCAN_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"فاصل النبضات: {HEARTBEAT_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"فاصل نبضات المنفذ: {EXECUTOR_HEARTBEAT_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"حد الثقة المحسن: {CONFIDENCE_THRESHOLD} نقطة", "system", "config")
    safe_log_info(f"التوقيت: سوريا (GMT+3)", "system", "config")
    safe_log_info(f"تنفيذ الصفقات: {'مفعل' if EXECUTE_TRADES else 'معطل'}", "system", "config")
    safe_log_info(f"رابط البوت المنفذ: {EXECUTOR_BOT_URL}", "system", "config")
    safe_log_info(f"نظام الأوزان المحسن: مفعل", "system", "config")
    safe_log_info(f"إدارة التضارب المحسنة: {CONFLICT_MANAGEMENT['ENABLE_ENHANCED_FILTERING']}", "system", "config")
    safe_log_info(f"محاذاة الاتجاه: {CONFLICT_MANAGEMENT['TREND_ALIGNMENT_BONUS']}", "system", "config")
    
    # فحص اتصال البوت المنفذ
    executor_health = await executor_client.health_check()
    safe_log_info(f"اتصال البوت المنفذ: {'متصل' if executor_health else 'غير متصل'}", "system", "config")
    
    # بدء المهام
    asyncio.create_task(market_scanner_task())
    asyncio.create_task(health_check_task())
    asyncio.create_task(heartbeat_task())
    asyncio.create_task(executor_heartbeat_task())
    
    safe_log_info("✅ بدأت مهام المسح والفحص الصحي والنبضات مع النظام المحسن v3.0", "system", "startup")

@app.on_event("shutdown")
async def shutdown_event():
    safe_log_info("إيقاف ماسح السوق - النظام المحسن v3.0", "system", "shutdown")
    await data_fetcher.close()
    await executor_client.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
