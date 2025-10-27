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
# الإعدادات الرئيسية المحدثة
# =============================================================================

# إعدادات التطبيق
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PORT = int(os.getenv("PORT", 8000))

# إعدادات البوت المنفذ
EXECUTOR_BOT_URL = os.getenv("EXECUTOR_BOT_URL", "https://your-executor-bot.onrender.com")
EXECUTOR_BOT_API_KEY = os.getenv("EXECUTOR_BOT_API_KEY", "")
EXECUTE_TRADES = os.getenv("EXECUTE_TRADES", "false").lower() == "true"

# إعدادات التداول المحدثة
SCAN_INTERVAL = 1800  # 30 دقيقة بين كل فحص (بالثواني)
HEARTBEAT_INTERVAL = 1800  # 30 دقيقة بين كل نبضة (بالثواني)
EXECUTOR_HEARTBEAT_INTERVAL = 3600  # ساعة بين كل نبضة للمنفذ (بالثواني)
CONFIDENCE_THRESHOLD = 50  # ⬅️ تحديث: خفض من 60 إلى 55 (إشارات أقوى)

# إعدادات نظام التأكيد المحدثة
PRIMARY_TIMEFRAME = '1h'
CONFIRMATION_TIMEFRAME = '15m'
CONFIRMATION_THRESHOLD = 30  # ⬅️ تحديث: خفض من 40 إلى 35
CONFIRMATION_BONUS = 10      # ⬅️ تحديث: زيادة من 10 إلى 12
MIN_CONFIRMATION_GAP = 3     # ⬅️ جديد: فرق نقاط minimum للتأكيد

# إعدادات تصفية الإشارات المتضاربة المحدثة
MIN_SIGNAL_GAP = 10          # ⬅️ تحديث: زيادة من 10 إلى 12
CONFLICTING_SIGNAL_PENALTY = 15

# ⬅️ جديد: إعدادات التحسينات الطفيفة
ENHANCEMENT_SETTINGS = {
    'ENABLE_QUICK_ENHANCE': True,
    'MIN_STRENGTH_FOR_ENHANCE': 45,  # أقل قوة للتطبيق التحسين
    'MAX_ENHANCEMENT_BONUS': 10      # أقصى نقاط تحسين
}

# الأصول والأطر الزمنية
SUPPORTED_COINS = {
    #'btc': {'name': 'Bitcoin', 'binance_symbol': 'BTCUSDT', 'symbol': 'BTC'},
    'eth': {'name': 'Ethereum', 'binance_symbol': 'ETHUSDT', 'symbol': 'ETH'},
    'bnb': {'name': 'Binance Coin', 'binance_symbol': 'BNBUSDT', 'symbol': 'BNB'},
    #'sol': {'name': 'Solana', 'binance_symbol': 'SOLUSDT', 'symbol': 'SOL'},
    #'xrp': {'name': 'Ripple', 'binance_symbol': 'XRPUSDT', 'symbol': 'XRP'},
    #'ltc': {'name': 'Litecoin', 'binance_symbol': 'LTCUSDT', 'symbol': 'LTC'},
    #'ada': {'name': 'Cardano', 'binance_symbol': 'ADAUSDT', 'symbol': 'ADA'},
    #'avax': {'name': 'Avalanche', 'binance_symbol': 'AVAXUSDT', 'symbol': 'AVAX'},
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

# أوزان المؤشرات المحدثة (من 100 نقطة)
INDICATOR_WEIGHTS = {
    "MOMENTUM": 40,
    "PRICE_ACTION": 25,
    "KEY_LEVELS": 25,
    "VOLUME_CONFIRMATION": 20
}

# مستويات التنبيه المحدثة
ALERT_LEVELS = {
    "LOW": {"min": 0, "max": 40, "emoji": "⚪", "send_alert": False, "color": "gray"},
    "MEDIUM": {"min": 41, "max": 49, "emoji": "🟡", "send_alert": True, "color": "gold"},
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

app = FastAPI(title="Crypto Top/Bottom Scanner", version="2.4.0")  # ⬅️ تحديث الإصدار

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
    "enhanced_signals_sent": 0,  # ⬅️ جديد: الإشارات المحسنة
    "confirmation_bonus_applied": 0  # ⬅️ جديد: مرات تطبيق bonus التأكيد
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

# ⬅️ جديد: نظام التأكيد المحسن
async def enhanced_confirmation_check(coin_data):
    """نسخة محسنة من نظام التأكيد"""
    try:
        # الفحص في الإطار الرئيسي
        primary_data = await data_fetcher.get_coin_data(coin_data, PRIMARY_TIMEFRAME)
        primary_signal = primary_data['analysis']
        
        # اشتراط إشارة واضحة في الإطار الرئيسي
        if (primary_signal['strongest_score'] < CONFIDENCE_THRESHOLD - 10 or
            not primary_signal['alert_level']['send_alert']):
            return None
        
        # الفحص في إطار التأكيد
        confirmation_data = await data_fetcher.get_coin_data(coin_data, CONFIRMATION_TIMEFRAME)
        confirmation_signal = confirmation_data['analysis']
        
        # اشتراطات أقوى للتأكيد
        confirmation_conditions = (
            primary_signal['strongest_signal'] == confirmation_signal['strongest_signal'] and
            confirmation_signal['strongest_score'] >= CONFIRMATION_THRESHOLD and
            abs(primary_signal['strongest_score'] - confirmation_signal['strongest_score']) >= MIN_CONFIRMATION_GAP
        )
        
        if confirmation_conditions:
            # حساب النقاط المحسنة
            base_bonus = CONFIRMATION_BONUS
            strength_bonus = min(10, confirmation_signal['strongest_score'] // 10)  # bonus إضافي حسب قوة التأكيد
            total_bonus = base_bonus + strength_bonus
            
            confirmed_score = min(95, primary_signal['strongest_score'] + total_bonus)  # حد أقصى 95
            
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
                'lows': primary_data['lows']
            }
        
        return None
            
    except Exception as e:
        safe_log_error(f"خطأ في نظام التأكيد المحسن لـ {coin_data['symbol']}: {e}", coin_data['symbol'], "enhanced_confirmation")
        return None

def filter_conflicting_signals(analysis: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """تصفية الإشارات المتضاربة - النسخة المحسنة"""
    top_score = analysis["top_score"]
    bottom_score = analysis["bottom_score"]
    strongest_signal = analysis["strongest_signal"]
    strongest_score = analysis["strongest_score"]
    
    # ⬅️ تحديث: زيادة الفرق المطلوب بين الإشارات
    score_gap = abs(top_score - bottom_score)
    
    if score_gap < MIN_SIGNAL_GAP:
        safe_log_info(f"🚫 تجاهل إشارة متضاربة - قمة: {top_score}, قاع: {bottom_score}, الفرق: {score_gap} (مطلوب: {MIN_SIGNAL_GAP})", 
                     "system", "conflict_filter")
        system_stats["conflicting_signals_filtered"] += 1
        return None
    
    # ⬅️ تحديث: تعزيز طفيف للإشارة الأقوى
    if top_score > bottom_score:
        enhanced_top = min(100, top_score + 3)  # تعزيز طفيف
        return {**analysis, "strongest_signal": "top", "strongest_score": enhanced_top}
    else:
        enhanced_bottom = min(100, bottom_score + 3)  # تعزيز طفيف
        return {**analysis, "strongest_signal": "bottom", "strongest_score": enhanced_bottom}

def get_market_bias(prices: List[float]) -> str:
    """تحديد الاتجاه العام للسوق"""
    if len(prices) < 20:
        return "neutral"
    
    # حساب الاتجاه قصير وطويل المدى
    short_trend = prices[-1] - prices[-5]  # آخر 5 فترات
    long_trend = prices[-1] - prices[-20]  # آخر 20 فترة
    
    if short_trend > 0 and long_trend > 0:
        return "bullish"
    elif short_trend < 0 and long_trend < 0:
        return "bearish"
    else:
        return "neutral"

def apply_market_bias(analysis: Dict[str, Any], market_bias: str) -> Dict[str, Any]:
    """تطبيق تحيز السوق على النتائج"""
    if market_bias == "bullish":
        # في السوق الصاعد، نقلل من ثقة إشارات القمة
        analysis["top_score"] = max(0, analysis["top_score"] - 10)
    elif market_bias == "bearish":
        # في السوق الهابط، نقلل من ثقة إشارات القاع
        analysis["bottom_score"] = max(0, analysis["bottom_score"] - 10)
    
    # إعادة حساب الإشارة الأقوى
    if analysis["top_score"] > analysis["bottom_score"]:
        analysis["strongest_signal"] = "top"
        analysis["strongest_score"] = analysis["top_score"]
    else:
        analysis["strongest_signal"] = "bottom"
        analysis["strongest_score"] = analysis["bottom_score"]
    
    analysis["alert_level"] = get_alert_level(analysis["strongest_score"])
    
    return analysis

class AdvancedMarketAnalyzer:
    """محلل متقدم للقمم والقيعان - النسخة المحدثة مع التحسينات الطفيفة"""
    
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
        
        # نمط المطرقة (Hammer) - إشارة قاع
        is_hammer = (current_lower_wick > 2 * current_body and 
                    current_upper_wick < current_body * 0.3 and
                    current_close > prev_close)
        
        # نمط النجم الساقط (Shooting Star) - إشارة قمة
        is_shooting_star = (current_upper_wick > 2 * current_body and 
                           current_lower_wick < current_body * 0.3 and
                           current_close < prev_close)
        
        # نمط الابتلاع (Engulfing)
        is_bullish_engulfing = (prev_close < prev2_close and current_close > prev_high and prev_close < prev_low)
        is_bearish_engulfing = (prev_close > prev2_close and current_close < prev_low and prev_close > prev_high)
        
        # نمط دوجي (Doji)
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
        
        # استخدام أدنى وأعلى 20 شمعة
        recent_lows = min(prices[-20:])
        recent_highs = max(prices[-20:])
        current_price = prices[-1]
        
        # حساب القرب من المستويات كنسبة مئوية
        distance_to_support = abs(current_price - recent_lows) / current_price
        distance_to_resistance = abs(current_price - recent_highs) / current_price
        
        strength = 0
        direction = "none"
        closest_distance = min(distance_to_support, distance_to_resistance)
        
        if distance_to_support < 0.01:  # within 1%
            strength = 12
            direction = "bottom"
        elif distance_to_support < 0.02:  # within 2%
            strength = 8
            direction = "bottom"
        elif distance_to_support < 0.03:  # within 3%
            strength = 4
            direction = "bottom"
        elif distance_to_resistance < 0.01:  # within 1%
            strength = 12
            direction = "top"
        elif distance_to_resistance < 0.02:  # within 2%
            strength = 8
            direction = "top"
        elif distance_to_resistance < 0.03:  # within 3%
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

    # ⬅️ تحديث: تحليل حجم محسن
    def enhanced_volume_analysis(self, volumes: List[float], price_trend: str, signal_type: str) -> Dict[str, Any]:
        """تحليل حجم محسن"""
        if len(volumes) < 10:
            return {"trend": "stable", "strength": 0, "description": "⚪ حجم مستقر", "volume_ratio": 1.0}
        
        # حساب نسبة الحجم مع نافذة أطول
        recent_volume = np.mean(volumes[-3:])  # آخر 3 فترات بدلاً من 5
        previous_volume = np.mean(volumes[-6:-3])  # 3 فترات سابقة
        
        volume_ratio = recent_volume / (previous_volume + 1e-10)
        
        # تحسين تقييم قوة الحجم
        strength = 0
        if volume_ratio > 2.5:  # حجم قوي جداً
            strength = 12
            trend_desc = "📈 حجم متزايد بقوة"
        elif volume_ratio > 1.8:
            strength = 9
            trend_desc = "📈 حجم متزايد"
        elif volume_ratio > 1.3:
            strength = 6
            trend_desc = "📈 حجم متزايد قليلاً"
        elif volume_ratio < 0.4:  # حجم منخفض جداً
            strength = 8
            trend_desc = "📉 حجم متراجع بقوة"
        elif volume_ratio < 0.7:
            strength = 5
            trend_desc = "📉 حجم متراجع"
        else:
            strength = 2
            trend_desc = "⚪ حجم مستقر"
        
        # تحسين نقاط التأكيد بناءً على نوع الإشارة
        confirmation_bonus = 0
        if signal_type == "bottom" and volume_ratio > 1.5 and price_trend == "down":
            confirmation_bonus = 6  # حجم مرتفع في هبوط → قاع محتمل
            trend_desc += " - مؤشر قاع"
        elif signal_type == "top" and volume_ratio > 1.5 and price_trend == "up":
            confirmation_bonus = 6  # حجم مرتفع في صعود → قمة محتملة
            trend_desc += " - مؤشر قمة"
        
        return {
            "trend": "rising" if volume_ratio > 1.2 else "falling" if volume_ratio < 0.8 else "stable",
            "strength": strength + confirmation_bonus,
            "description": trend_desc,
            "volume_ratio": volume_ratio,
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
        
        # إيجاد أقرب مستوى
        closest_level = None
        min_distance = float('inf')
        
        for level_name, level_price in levels.items():
            distance = abs(current - level_price) / current
            if distance < min_distance:
                min_distance = distance
                closest_level = level_name
        
        # قوة مستوى فيبوناتشي
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

    # ⬅️ جديد: تحسين سريع لنظام النقاط
    def quick_enhance_scores(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """تحسين سريع لنظام النقاط"""
        indicators = analysis["indicators"]
        
        # تعزيز إضافي لتقارب المؤشرات
        convergence_bonus = self._calculate_convergence_bonus(indicators)
        
        # تعزيز للإشارات القوية جداً
        strength_bonus = 0
        if analysis["strongest_score"] > 75:
            strength_bonus = 5
        elif analysis["strongest_score"] > 65:
            strength_bonus = 3
        
        total_bonus = convergence_bonus + strength_bonus
        
        if total_bonus > 0:
            enhanced_top = min(100, analysis["top_score"] + total_bonus)
            enhanced_bottom = min(100, analysis["bottom_score"] + total_bonus)
            
            # تحديث الإشارة الأقوى
            if enhanced_top > enhanced_bottom:
                strongest_signal = "top"
                strongest_score = enhanced_top
            else:
                strongest_signal = "bottom"
                strongest_score = enhanced_bottom
            
            return {
                **analysis,
                "top_score": enhanced_top,
                "bottom_score": enhanced_bottom,
                "strongest_signal": strongest_signal,
                "strongest_score": strongest_score,
                "alert_level": get_alert_level(strongest_score),
                "enhancement_bonus": total_bonus
            }
        
        return analysis

    def _calculate_convergence_bonus(self, indicators: Dict) -> int:
        """حساب نقاط التقارب بين المؤشرات"""
        bonus = 0
        
        # تقارب RSI و Stochastic
        rsi = indicators.get('rsi', 50)
        stoch_k = indicators.get('stoch_k', 50)
        
        if (rsi > 70 and stoch_k > 80) or (rsi < 30 and stoch_k < 20):
            bonus += 4  # تقارب في مناطق التشبع
        
        # تقارب MACD مع السعر
        macd_histogram = indicators.get('macd_histogram', 0)
        if abs(macd_histogram) > 0.01:  # إشارة MACD قوية
            bonus += 3
        
        # نمط شمعة قوي + حجم
        candle_pattern = indicators.get('candle_pattern', {})
        volume_trend = indicators.get('volume_trend', {})
        
        if (candle_pattern.get('strength', 0) > 8 and 
            volume_trend.get('volume_ratio', 1) > 1.5):
            bonus += 3
        
        return min(bonus, 8)  # حد أقصى 8 نقاط

    # ⬅️ جديد: تحليل اتجاه بسيط
    def simple_trend_analysis(self, prices: List[float]) -> Dict[str, Any]:
        """تحليل اتجاه بسيط ولكن فعال"""
        if len(prices) < 10:
            return {"trend": "neutral", "strength": 0}
        
        # اتجاه قصير المدى (آخر 5 فترات)
        short_trend = (prices[-1] - prices[-5]) / prices[-5] * 100
        
        # اتجاه متوسط المدى (آخر 10 فترات)
        medium_trend = (prices[-1] - prices[-10]) / prices[-10] * 100
        
        trend_strength = 0
        if abs(short_trend) > 3.0:  # حركة قوية
            trend_strength = 8
        elif abs(short_trend) > 1.5:
            trend_strength = 4
        
        # تحديد الاتجاه
        if short_trend > 1.0 and medium_trend > 0.5:
            trend = "bullish"
        elif short_trend < -1.0 and medium_trend < -0.5:
            trend = "bearish"
        else:
            trend = "neutral"
        
        return {
            "trend": trend,
            "strength": trend_strength,
            "short_trend_percent": short_trend,
            "medium_trend_percent": medium_trend
        }

    def analyze_market_condition(self, prices: List[float], volumes: List[float], 
                               highs: List[float], lows: List[float]) -> Dict[str, Any]:
        """تحليل شامل لحالة السوق للكشف عن القمم والقيعان"""
        
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
            
            # تحديد اتجاه السعر للمساعدة في تحليل الحجم
            price_trend = "up" if prices[-1] > prices[-5] else "down" if prices[-1] < prices[-5] else "neutral"
            
            # ⬅️ تحديث: استخدام تحليل الحجم المحسن
            strongest_signal_temp = "top" if rsi > 70 else "bottom" if rsi < 30 else "neutral"
            volume_analysis = self.enhanced_volume_analysis(volumes, price_trend, strongest_signal_temp)
            
            fib_levels = self.calculate_fibonacci_levels(prices)
            
            # تحليل القمة (Top)
            top_score = self._calculate_top_score(rsi, stoch, macd, moving_averages, candle_pattern, 
                                                support_resistance, volume_analysis, fib_levels, prices[-1])
            
            # تحليل القاع (Bottom)
            bottom_score = self._calculate_bottom_score(rsi, stoch, macd, moving_averages, candle_pattern,
                                                      support_resistance, volume_analysis, fib_levels, prices[-1])
            
            # تطبيق وزن الجلسة
            session_weight = get_session_weight()
            top_score = int(top_score * session_weight)
            bottom_score = int(bottom_score * session_weight)
            
            # تحديد الإشارة الأقوى
            strongest_signal = "top" if top_score > bottom_score else "bottom"
            strongest_score = max(top_score, bottom_score)
            
            # ⬅️ جديد: تطبيق التحسين السريع للنقاط
            initial_analysis = {
                "top_score": min(top_score, 100),
                "bottom_score": min(bottom_score, 100),
                "strongest_signal": strongest_signal,
                "strongest_score": strongest_score,
                "alert_level": get_alert_level(strongest_score),
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
                    "session_weight": session_weight
                },
                "timestamp": time.time()
            }
            
            # تطبيق التحسينات إذا كانت الإشارة قوية بما يكفي
            if strongest_score >= ENHANCEMENT_SETTINGS['MIN_STRENGTH_FOR_ENHANCE']:
                enhanced_analysis = self.quick_enhance_scores(initial_analysis)
                if enhanced_analysis != initial_analysis:
                    safe_log_info(f"🎯 تطبيق تحسين النقاط: +{enhanced_analysis.get('enhancement_bonus', 0)} نقطة", "analyzer", "quick_enhance")
                    return enhanced_analysis
            
            return initial_analysis
            
        except Exception as e:
            safe_log_error(f"خطأ في تحليل السوق: {e}", "analyzer", "market_analysis")
            return self._get_empty_analysis()

    def analyze_market_condition_enhanced(self, prices: List[float], volumes: List[float], 
                                        highs: List[float], lows: List[float]) -> Dict[str, Any]:
        """تحليل محسن يتجنب الإشارات المتضاربة"""
        
        # التحليل الأساسي
        analysis = self.analyze_market_condition(prices, volumes, highs, lows)
        
        # تطبيق منطق الاستبعاد المتبادل
        top_score = analysis["top_score"]
        bottom_score = analysis["bottom_score"]
        
        # إذا كانت كلا الإشارتين قويتين، نفضل الإشارة الأقوى فقط
        if top_score > 45 and bottom_score > 45:
            if top_score > bottom_score:
                analysis["bottom_score"] = max(0, bottom_score - CONFLICTING_SIGNAL_PENALTY)
            else:
                analysis["top_score"] = max(0, top_score - CONFLICTING_SIGNAL_PENALTY)
        
        # إعادة حساب الإشارة الأقوى
        if analysis["top_score"] > analysis["bottom_score"]:
            analysis["strongest_signal"] = "top"
            analysis["strongest_score"] = analysis["top_score"]
        else:
            analysis["strongest_signal"] = "bottom" 
            analysis["strongest_score"] = analysis["bottom_score"]
        
        analysis["alert_level"] = get_alert_level(analysis["strongest_score"])
        
        return analysis

    def _calculate_top_score(self, rsi: float, stoch: Dict, macd: Dict, moving_averages: Dict,
                           candle_pattern: Dict, support_resistance: Dict,
                           volume_analysis: Dict, fib_levels: Dict, current_price: float) -> int:
        """حساب نقاط القمة"""
        score = 0
        
        # MOMENTUM (35 نقطة)
        # RSI (0-12 نقطة)
        if rsi > 80: score += 12
        elif rsi > 70: score += 8
        elif rsi > 60: score += 4
        
        # Stochastic (0-12 نقطة)
        if stoch['k'] > 85 and stoch['d'] > 85: score += 12
        elif stoch['k'] > 75 and stoch['d'] > 75: score += 8
        elif stoch['k'] > 65 and stoch['d'] > 65: score += 4
        
        # MACD (0-11 نقطة)
        if macd['histogram'] < -0.02: score += 6
        elif macd['histogram'] < -0.01: score += 4
        elif macd['histogram'] < 0: score += 1
        
        # إشارات إضافية للمؤشرات
        if macd['histogram'] < 0 and macd['macd'] < macd['signal']: score += 5
        
        # PRICE_ACTION (25 نقطة)
        # أنماط الشموع (0-15 نقطة)
        if candle_pattern["direction"] == "top":
            score += candle_pattern["strength"]
        
        # اختراق المتوسطات (0-10 نقطة)
        if current_price < moving_averages['ema_20'] and current_price < moving_averages['ema_50']:
            score += 10  # اختراق هابط قوي
        elif current_price < moving_averages['ema_20']:
            score += 5   # اختراق المتوسط القصير
        
        # KEY_LEVELS (25 نقطة)
        # الدعم/المقاومة (0-12 نقطة)
        if support_resistance["direction"] == "top":
            score += support_resistance["strength"]
        
        # فيبوناتشي (0-8 نقطة)
        score += fib_levels["strength"]
        
        # مستويات قوية إضافية (0-5 نقاط)
        if fib_levels.get('closest_level') in ['0.618', '0.786', '1.0'] and fib_levels['distance'] < 0.015:
            score += 5
        
        # VOLUME_CONFIRMATION (15 نقطة)
        # قوة الحجم (0-10 نقطة)
        score += volume_analysis["strength"]
        
        # تأكيد الحجم للهبوط (0-5 نقاط إضافية)
        if volume_analysis["volume_ratio"] > 1.2 and volume_analysis["trend"] == "rising":
            score += 5
        
        return min(score, 100)

    def _calculate_bottom_score(self, rsi: float, stoch: Dict, macd: Dict, moving_averages: Dict,
                              candle_pattern: Dict, support_resistance: Dict,
                              volume_analysis: Dict, fib_levels: Dict, current_price: float) -> int:
        """حساب نقاط القاع"""
        score = 0
        
        # MOMENTUM (35 نقطة)
        # RSI (0-12 نقطة)
        if rsi < 20: score += 12
        elif rsi < 30: score += 8
        elif rsi < 40: score += 4
        
        # Stochastic (0-12 نقطة)
        if stoch['k'] < 15 and stoch['d'] < 15: score += 12
        elif stoch['k'] < 25 and stoch['d'] < 25: score += 8
        elif stoch['k'] < 35 and stoch['d'] < 35: score += 4
        
        # MACD (0-11 نقطة)
        if macd['histogram'] > 0.02: score += 6
        elif macd['histogram'] > 0.01: score += 4
        elif macd['histogram'] > 0: score += 1
        
        # إشارات إضافية للمؤشرات
        if macd['histogram'] > 0 and macd['macd'] > macd['signal']: score += 5
        
        # PRICE_ACTION (25 نقطة)
        # أنماط الشموع (0-15 نقطة)
        if candle_pattern["direction"] == "bottom":
            score += candle_pattern["strength"]
        
        # اختراق المتوسطات (0-10 نقطة)
        if current_price > moving_averages['ema_20'] and current_price > moving_averages['ema_50']:
            score += 10  # اختراق صاعد قوي
        elif current_price > moving_averages['ema_20']:
            score += 5   # اختراق المتوسط القصير
        
        # KEY_LEVELS (25 نقطة)
        # الدعم/المقاومة (0-12 نقطة)
        if support_resistance["direction"] == "bottom":
            score += support_resistance["strength"]
        
        # فيبوناتشي (0-8 نقطة)
        score += fib_levels["strength"]
        
        # مستويات قوية إضافية (0-5 نقاط)
        if fib_levels.get('closest_level') in ['0.0', '0.236', '0.382'] and fib_levels['distance'] < 0.015:
            score += 5
        
        # VOLUME_CONFIRMATION (15 نقطة)
        # قوة الحجم (0-10 نقطة)
        score += volume_analysis["strength"]
        
        # تأكيد الحجم للصعود (0-5 نقاط إضافية)
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

# ⬅️ جديد: مسح سريع محسن يجمع كل التحسينات الطفيفة
async def quick_enhanced_scan(coin_key, coin_data):
    """مسح سريع محسن يجمع كل التحسينات الطفيفة"""
    try:
        # استخدام نظام التأكيد المحسن
        confirmed_signal = await enhanced_confirmation_check(coin_data)
        
        if not confirmed_signal:
            return None
        
        # تطبيق تحليل الاتجاه
        trend_analysis = data_fetcher.analyzer.simple_trend_analysis(confirmed_signal['prices'])
        
        # تطبيق تحسين التصفية
        final_signal = filter_conflicting_signals(confirmed_signal)
        
        if final_signal and final_signal['alert_level']['send_alert']:
            safe_log_info(f"🎯 إشارة محسنة لـ {coin_data['symbol']}: {final_signal['strongest_score']} نقطة (تحسين: {confirmed_signal.get('confirmation_bonus', 0)})", 
                         coin_data['symbol'], "quick_enhance")
            system_stats["enhanced_signals_sent"] += 1
            return final_signal
        
        return None
        
    except Exception as e:
        safe_log_error(f"خطأ في المسح المحسن لـ {coin_data['symbol']}: {e}", coin_data['symbol'], "quick_enhance")
        return None

class TelegramNotifier:
    """إشعارات التليجرام مع صور الشارت"""
    
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
            # بناء الرسالة النصية
            message = self._build_beautiful_message(coin, timeframe, analysis, price)
            
            # إنشاء صورة الشارت
            chart_image = self._create_beautiful_chart(coin, timeframe, prices, highs, lows, analysis, price)
            
            if chart_image:
                # إرسال الصورة مع التسمية التوضيحية
                success = await self._send_photo_with_caption(message, chart_image)
                if success:
                    safe_log_info(f"📨 تم إرسال إشعار بصورة لـ {coin} ({timeframe}) - {strongest_signal} - {strongest_score} نقطة", 
                                coin, "telegram")
                    system_stats["total_alerts_sent"] += 1
                    return True
            else:
                # إرسال رسالة نصية فقط إذا فشل إنشاء الصورة
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

    async def send_heartbeat(self) -> bool:
        """إرسال نبضة عن حالة النظام"""
        try:
            uptime_seconds = time.time() - system_stats["start_time"]
            uptime_str = self._format_uptime(uptime_seconds)
            
            current_session = get_current_session()
            syria_time = get_syria_time()
            
            message = f"""
💓 *نبضة النظام - ماسح القمم والقيعان v2.4*

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
• 🚫 *إشارات متضاربة مفلترة:* `{system_stats['conflicting_signals_filtered']}`
• 🎯 *إشارات محسنة:* `{system_stats['enhanced_signals_sent']}`
• 💎 *مرات تطبيق bonus:* `{system_stats['confirmation_bonus_applied']}`
• 💾 *حجم الكاش:* `{len(data_fetcher.cache)}` عملة

🪙 *العملات النشطة:* `{', '.join(SUPPORTED_COINS.keys())}`
⏰ *الأطر الزمنية:* `{', '.join(TIMEFRAMES)}`

🎯 *آخر تحديث:* `{system_stats['last_scan_time'] or 'لم يبدأ بعد'}`
💓 *آخر نبضة:* `{system_stats['last_heartbeat'] or 'لم يبدأ بعد'}`
🔗 *آخر نبضة منفذ:* `{system_stats['last_executor_heartbeat'] or 'لم يبدأ بعد'}`

✅ *الحالة:* النظام يعمل بشكل طبيعي مع التحسينات الطفيفة
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

    def _build_beautiful_message(self, coin: str, timeframe: str, analysis: Dict[str, Any], price: float) -> str:
        """بناء رسالة جميلة ومفصلة"""
        
        alert_level = analysis["alert_level"]
        strongest_signal = analysis["strongest_signal"]
        strongest_score = analysis["strongest_score"]
        indicators = analysis["indicators"]
        current_session = get_current_session()
        
        # الرأس حسب نوع الإشارة
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
        
        # معلومات السعر والإطار
        message += f"💰 *السعر الحالي:* `${price:,.2f}`\n"
        message += f"⏰ *الإطار الزمني:* `{timeframe}`\n"
        message += f"🕒 *التوقيت السوري:* `{get_syria_time().strftime('%H:%M %d/%m/%Y')}`\n\n"
        
        # قوة الإشارة
        message += f"🎯 *قوة الإشارة:* {alert_level['emoji']} *{strongest_score}/100*\n"
        message += f"📊 *مستوى الثقة:* `{alert_level['level']}`\n\n"
        
        # معلومات التحسين إذا وجدت
        if analysis.get('confirmed'):
            message += f"✅ *مؤكد بـ {CONFIRMATION_TIMEFRAME}:* `+{analysis.get('confirmation_bonus', 0)} نقطة`\n"
        if analysis.get('enhancement_bonus', 0) > 0:
            message += f"⚡ *تحسين النقاط:* `+{analysis.get('enhancement_bonus', 0)} نقطة`\n"
        message += "\n"
        
        # الجلسة الحالية
        message += f"🌍 *الجلسة:* {current_session['emoji']} {current_session['name']}\n"
        message += f"⚖️ *وزن الجلسة:* `{current_session['weight']*100}%`\n\n"
        
        # المؤشرات الفنية
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
        
        if 'ema_20' in indicators and 'ema_50' in indicators:
            ema_status = "صاعد" if price > indicators['ema_20'] and price > indicators['ema_50'] else "هابط" if price < indicators['ema_20'] and price < indicators['ema_50'] else "متذبذب"
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
        
        # التوصية
        if strongest_signal == "top":
            recommendation = "💡 *التوصية:* مراقبة فرص البيع والربح"
        else:
            recommendation = "💡 *التوصية:* مراقبة فرص الشراء والدخول"
        
        message += f"{recommendation}\n\n"
        
        # التوقيع
        message += "─" * 30 + "\n"
        message += f"⚡ *ماسح القمم والقيعان v2.4*"
        
        return message

    def _create_beautiful_chart(self, coin: str, timeframe: str, prices: List[float], 
                              highs: List[float], lows: List[float], analysis: Dict[str, Any], 
                              current_price: float) -> Optional[str]:
        """إنشاء رسم بياني جميل"""
        try:
            if len(prices) < 10:
                return None
            
            # إعداد الألوان حسب نوع الإشارة
            if analysis["strongest_signal"] == "top":
                colors = COLORS["top"]
            else:
                colors = COLORS["bottom"]
            
            # إنشاء الشكل
            plt.figure(figsize=(12, 8))
            
            # خلفية جميلة
            plt.gca().set_facecolor(colors["bg"])
            plt.grid(True, alpha=0.3, linestyle='--')
            
            # تحديد عدد البيانات للعرض (آخر 50 نقطة)
            display_prices = prices[-50:] if len(prices) > 50 else prices
            x_values = list(range(len(display_prices)))
            
            # رسم السعر
            plt.plot(x_values, display_prices, color=colors["primary"], linewidth=3, 
                    label=f'سعر {coin.upper()}', alpha=0.8, marker='o', markersize=3)
            
            # إضافة نقطة السعر الحالي
            plt.scatter([x_values[-1]], [display_prices[-1]], color=colors["primary"], 
                      s=200, zorder=5, edgecolors='white', linewidth=2)
            
            # إضافة خطوط الدعم والمقاومة إذا كانت موجودة
            if 'support_resistance' in analysis["indicators"]:
                sr_data = analysis["indicators"]["support_resistance"]
                if sr_data["support"] > 0:
                    plt.axhline(y=sr_data["support"], color='green', linestyle='--', 
                              alpha=0.7, label=f'دعم: ${sr_data["support"]:,.2f}')
                if sr_data["resistance"] > 0:
                    plt.axhline(y=sr_data["resistance"], color='red', linestyle='--', 
                              alpha=0.7, label=f'مقاومة: ${sr_data["resistance"]:,.2f}')
            
            # تخصيص المظهر
            plt.title(f'{coin.upper()} - إطار {timeframe}\nإشارة {analysis["strongest_signal"]} - قوة {analysis["strongest_score"]}/100', 
                     fontsize=16, fontweight='bold', color=colors["primary"], pad=20)
            
            plt.xlabel('الوقت', fontsize=12)
            plt.ylabel('السعر (USDT)', fontsize=12)
            plt.legend()
            
            # تحسين المظهر
            plt.tight_layout()
            
            # حفظ الصورة
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
            # تنظيف التسمية التوضيحية
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
        # إزالة أي أحخاص قد تسبب مشاكل في Markdown
        clean_message = message.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
        return clean_message

class ExecutorBotClient:
    """عميل للتواصل مع بوت التنفيذ"""
    
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
                "source": "top_bottom_scanner_v2.4"
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
                "source": "top_bottom_scanner_v2.4",
                "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
                "system_stats": {
                    "total_scans": system_stats["total_scans"],
                    "total_alerts_sent": system_stats["total_alerts_sent"],
                    "total_signals_sent": system_stats["total_signals_sent"],
                    "total_heartbeats_sent": system_stats["total_heartbeats_sent"],
                    "conflicting_signals_filtered": system_stats["conflicting_signals_filtered"],
                    "enhanced_signals_sent": system_stats["enhanced_signals_sent"],
                    "confirmation_bonus_applied": system_stats["confirmation_bonus_applied"],
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
    """جلب البيانات من Binance"""
    
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
            analysis = self.analyzer.analyze_market_condition_enhanced(
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

async def prepare_trade_signal(coin_key: str, coin_data: Dict, timeframe: str, 
                             data: Dict, analysis: Dict) -> Optional[Dict[str, Any]]:
    """تحضير بيانات إشارة التداول للبوت المنفذ"""
    try:
        signal_type = analysis["strongest_signal"]  # 'top' or 'bottom'
        score = analysis["strongest_score"]
        
        # تحديد اتجاه الصفقة
        if signal_type == "top":
            action = "SELL"
            reason = "إشارة قمة سعرية قوية"
        else:  # bottom
            action = "BUY" 
            reason = "إشارة قاع سعري قوية"
        
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

# التهيئة العالمية
data_fetcher = BinanceDataFetcher()
notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
executor_client = ExecutorBotClient(EXECUTOR_BOT_URL, EXECUTOR_BOT_API_KEY)

# المهام الأساسية المحدثة
async def market_scanner_task():
    """المهمة الرئيسية للمسح الضوئي مع التحسينات الطفيفة"""
    safe_log_info("بدء مهمة مسح السوق كل 30 دقيقة مع التحسينات الطفيفة", "system", "scanner")
    
    while True:
        try:
            syria_time = get_syria_time()
            current_session = get_current_session()
            
            safe_log_info(f"بدء دورة المسح - التوقيت السوري: {syria_time.strftime('%H:%M %d/%m/%Y')} - الجلسة: {current_session['name']}", 
                         "system", "scanner")
            
            alerts_sent = 0
            signals_sent = 0
            
            # مسح جميع العملات
            for coin_key, coin_data in SUPPORTED_COINS.items():
                try:
                    # 🔄 استخدام النظام المحسن إذا كان مفعلاً
                    if ENHANCEMENT_SETTINGS['ENABLE_QUICK_ENHANCE']:
                        enhanced_signal = await quick_enhanced_scan(coin_key, coin_data)
                    else:
                        # استخدام النظام القديم للتوافق
                        enhanced_signal = await enhanced_confirmation_check(coin_data)
                    
                    if enhanced_signal:
                        # 🔴 تطبيق تحليل الاتجاه العام
                        market_bias = get_market_bias(enhanced_signal['prices'])
                        enhanced_signal = apply_market_bias(enhanced_signal, market_bias)
                        
                        # 🔴 تطبيق تصفية الإشارات المتضاربة (إذا لم يتم تطبيقها مسبقاً)
                        if not enhanced_signal.get('_filtered'):
                            filtered_signal = filter_conflicting_signals(enhanced_signal)
                        else:
                            filtered_signal = enhanced_signal
                            
                        if filtered_signal and filtered_signal['alert_level']['send_alert']:
                            # إرسال التنبيه
                            success = await notifier.send_alert(
                                coin_key, f"1h (مؤكد بـ {CONFIRMATION_TIMEFRAME})", filtered_signal, 
                                filtered_signal['price'], 
                                filtered_signal['prices'],
                                filtered_signal['highs'],
                                filtered_signal['lows']
                            )
                            
                            if success:
                                alerts_sent += 1
                                
                                # إرسال إشارة للبوت المنفذ
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
                                
                                await asyncio.sleep(3)  # فواصل بين الإشعارات
                    
                    await asyncio.sleep(1)  # فواصل بين الطلبات
                    
                except Exception as e:
                    safe_log_error(f"خطأ في معالجة {coin_key}: {e}", coin_key, "scanner")
                    continue
            
            # تحديث إحصائيات النظام
            system_stats["total_scans"] += 1
            system_stats["last_scan_time"] = syria_time.strftime('%H:%M %d/%m/%Y')
            
            safe_log_info(f"اكتملت دورة المسح - تم إرسال {alerts_sent} تنبيه و {signals_sent} إشارة تنفيذ", 
                         "system", "scanner")
            
            # انتظار حتى الفحص التالي
            await asyncio.sleep(SCAN_INTERVAL)
            
        except Exception as e:
            safe_log_error(f"خطأ في المهمة الرئيسية: {e}", "system", "scanner")
            await asyncio.sleep(60)
        
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
            
            safe_log_info(f"الفحص الصحي - الكاش: {cache_size} - الجلسة: {current_session['name']} - الوزن: {current_session['weight']} - المنفذ: {'متصل' if executor_health else 'غير متصل'} - إشارات مفلترة: {system_stats['conflicting_signals_filtered']} - إشارات محسنة: {system_stats['enhanced_signals_sent']}", 
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

# endpoints للـ API المحدثة
@app.get("/")
async def root():
    return {
        "message": "ماسح القمم والقيعان للكريبتو",
        "version": "2.4.0",  # ⬅️ تحديث الإصدار
        "supported_coins": list(SUPPORTED_COINS.keys()),
        "timeframes": TIMEFRAMES,
        "scan_interval": f"{SCAN_INTERVAL} ثانية",
        "heartbeat_interval": f"{HEARTBEAT_INTERVAL} ثانية",
        "executor_heartbeat_interval": f"{EXECUTOR_HEARTBEAT_INTERVAL} ثانية",
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "syria_time": get_syria_time().strftime('%H:%M %d/%m/%Y'),
        "current_session": get_current_session()["name"],
        "executor_enabled": EXECUTE_TRADES,
        "executor_connected": system_stats["executor_connected"],
        "conflicting_signals_filtered": system_stats["conflicting_signals_filtered"],
        "enhanced_signals_sent": system_stats["enhanced_signals_sent"],  # ⬅️ جديد
        "enhancement_enabled": ENHANCEMENT_SETTINGS['ENABLE_QUICK_ENHANCE']  # ⬅️ جديد
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
        "trade_execution_enabled": EXECUTE_TRADES,
        "conflicting_signals_filtered": system_stats["conflicting_signals_filtered"],
        "enhanced_signals_sent": system_stats["enhanced_signals_sent"],  # ⬅️ جديد
        "confirmation_bonus_applied": system_stats["confirmation_bonus_applied"]  # ⬅️ جديد
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
        "trade_execution_enabled": EXECUTE_TRADES,
        "conflicting_signals_filtered": system_stats["conflicting_signals_filtered"],
        "enhanced_signals_sent": system_stats["enhanced_signals_sent"],  # ⬅️ جديد
        "confirmation_bonus_applied": system_stats["confirmation_bonus_applied"]  # ⬅️ جديد
    }

@app.get("/test-telegram")
async def test_telegram():
    """اختبار إرسال رسالة تجريبية للتليجرام"""
    try:
        test_message = """
🧪 *اختبار البوت - ماسح القمم والقيعان v2.4*

✅ *الحالة:* البوت يعمل بشكل صحيح مع التحسينات الطفيفة
🕒 *الوقت:* {}
🌍 *الجلسة:* {} {}
⚡ *الإصدار:* 2.4.0

📊 *العملات المدعومة:* {}
⏰ *الأطر الزمنية:* {}

🔧 *الإعدادات المحسنة:*
• عتبة الثقة: {} نقطة (إشارات أقوى)
• فاصل المسح: {} ثانية
• فاصل النبضات: {} ثانية
• فاصل نبضات المنفذ: {} ثانية
• التوقيت: سوريا (GMT+3)
• تنفيذ الصفقات: {}
• اتصال المنفذ: {}
• تصفية الإشارات المتضاربة: {} نقطة فرق
• نظام التأكيد المحسن: {} نقطة bonus
• تحسين النقاط: مفعل

🎯 *الوظيفة:* كشف القمم والقيعان تلقائياً مع التحسينات الطفيفة
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
            "متصل" if system_stats["executor_connected"] else "غير متصل",
            MIN_SIGNAL_GAP,
            CONFIRMATION_BONUS
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
    safe_log_info("بدء تشغيل ماسح القمم والقيعان الإصدار 2.4 مع التحسينات الطفيفة", "system", "startup")
    safe_log_info(f"العملات المدعومة: {list(SUPPORTED_COINS.keys())}", "system", "config")
    safe_log_info(f"الأطر الزمنية: {TIMEFRAMES}", "system", "config")
    safe_log_info(f"فاصل المسح: {SCAN_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"فاصل النبضات: {HEARTBEAT_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"فاصل نبضات المنفذ: {EXECUTOR_HEARTBEAT_INTERVAL} ثانية", "system", "config")
    safe_log_info(f"حد الثقة: {CONFIDENCE_THRESHOLD} نقطة", "system", "config")
    safe_log_info(f"التوقيت: سوريا (GMT+3)", "system", "config")
    safe_log_info(f"تنفيذ الصفقات: {'مفعل' if EXECUTE_TRADES else 'معطل'}", "system", "config")
    safe_log_info(f"رابط البوت المنفذ: {EXECUTOR_BOT_URL}", "system", "config")
    safe_log_info(f"تصفية الإشارات المتضاربة: فرق {MIN_SIGNAL_GAP} نقطة على الأقل", "system", "config")
    safe_log_info(f"نظام التأكيد المحسن: {CONFIRMATION_BONUS} نقطة bonus", "system", "config")
    safe_log_info(f"تحسين النقاط: {'مفعل' if ENHANCEMENT_SETTINGS['ENABLE_QUICK_ENHANCE'] else 'معطل'}", "system", "config")
    
    # فحص اتصال البوت المنفذ
    executor_health = await executor_client.health_check()
    safe_log_info(f"اتصال البوت المنفذ: {'متصل' if executor_health else 'غير متصل'}", "system", "config")
    
    # بدء المهام
    asyncio.create_task(market_scanner_task())
    asyncio.create_task(health_check_task())
    asyncio.create_task(heartbeat_task())
    asyncio.create_task(executor_heartbeat_task())
    
    safe_log_info("✅ بدأت مهام المسح والفحص الصحي والنبضات مع التحسينات الطفيفة", "system", "startup")

@app.on_event("shutdown")
async def shutdown_event():
    safe_log_info("إيقاف ماسح السوق", "system", "shutdown")
    await data_fetcher.close()
    await executor_client.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
