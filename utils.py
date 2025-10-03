import logging
import warnings
import hashlib
import time
import pandas as pd
import numpy as np
from datetime import datetime
from config import LOG_LEVEL, LOG_FORMAT, LOG_FILE, DAMASCUS_TZ

# إخفاء التحذيرات
warnings.filterwarnings('ignore')

def setup_logging():
    """إعداد نظام التسجيل"""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format=LOG_FORMAT,
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

def calculate_indicators(data):
    """حساب المؤشرات الفنية"""
    try:
        df = data.copy()
        if len(df) < 50:
            return df

        # المتوسطات المتحركة
        df['sma10'] = df['close'].rolling(10).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['sma20'] = df['close'].rolling(20).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / (avg_loss + 1e-6)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = np.maximum(np.maximum(high_low, high_close), low_close)
        df['atr'] = tr.rolling(14).mean()
        
        # الزخم والحجم
        df['momentum'] = df['close'] / df['close'].shift(5) - 1
        df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        
        # MACD
        exp12 = df['close'].ewm(span=12, adjust=False).mean()
        exp26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp12 - exp26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        
        return df.dropna()
    except Exception as e:
        logging.error(f"❌ خطأ في حساب المؤشرات: {e}")
        return data

def generate_message_hash(message_type, message):
    """إنشاء هاش للرسائل لمنع التكرار"""
    return hashlib.md5(f"{message_type}_{message}".encode()).hexdigest()

def format_currency(amount):
    """تنسيق المبالغ المالية"""
    return f"${amount:.2f}"

def format_percentage(value):
    """تنسيق النسب المئوية"""
    return f"{value:.2f}%"

def get_current_time():
    """الحصول على الوقت الحالي بتوقيت دمشق"""
    return datetime.now(DAMASCUS_TZ)

def calculate_trade_age(trade_timestamp):
    """حساب عمر الصفقة"""
    current_time = get_current_time()
    age = current_time - trade_timestamp
    return age.total_seconds() / 3600  # العمر بالساعات
