import pandas as pd
import numpy as np
from utils import setup_logging, calculate_indicators

logger = setup_logging()

class MarketAnalyzer:
    """محلل الأسواق والمؤشرات الفنية"""
    
    def __init__(self, client, trading_settings):
        self.client = client
        self.trading_settings = trading_settings
    
    def get_historical_data(self, symbol, interval='30m', limit=100):
        """جلب البيانات التاريخية"""
        try:
            klines = self.client.futures_klines(symbol=symbol, interval=interval, limit=limit)
            
            data = pd.DataFrame(klines, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                data[col] = data[col].astype(float)
            
            return data
        except Exception as e:
            logger.error(f"❌ خطأ في جلب البيانات لـ {symbol}: {e}")
            return None
    
    def analyze_symbol(self, symbol):
        """تحليل الرمز مع النظام المرجح المحسن"""
        try:
            data = self.get_historical_data(symbol, self.trading_settings['data_interval'])
            if data is None or len(data) < 50:
                return False, {}, None

            data = calculate_indicators(data)
            if len(data) == 0:
                return False, {}, None

            latest = data.iloc[-1]
            
            # شروط الدخول المحسنة بنظام مرجح
            buy_conditions = [
                (latest['sma10'] > latest['sma50']),  # شرط الاتجاه الرئيسي
                (latest['sma10'] > latest['sma20'] * 0.998),  # شرط مرن
                (45 <= latest['rsi'] <= 68),  # RSI في نطاق آمن
                (latest['momentum'] > 0.002),  # زخم إيجابي
                (latest['volume_ratio'] > 0.8),  # حجم معقول
                (latest['macd'] > latest['macd_signal'] * 0.95)  # MACD إيجابي
            ]
            
            sell_conditions = [
                (latest['sma10'] < latest['sma50']),
                (latest['sma10'] < latest['sma20'] * 1.002),
                (32 <= latest['rsi'] <= 55),
                (latest['momentum'] < -0.002),
                (latest['volume_ratio'] > 0.8),
                (latest['macd'] < latest['macd_signal'] * 1.05)
            ]
            
            # نظام الترجيح
            buy_score = sum([
                1.5 if buy_conditions[0] else 0,
                1.0 if buy_conditions[1] else 0,
                1.2 if buy_conditions[2] else 0,
                1.0 if buy_conditions[3] else 0,
                0.8 if buy_conditions[4] else 0,
                1.0 if buy_conditions[5] else 0,
            ])
            
            sell_score = sum([
                1.5 if sell_conditions[0] else 0,
                1.0 if sell_conditions[1] else 0,
                1.2 if sell_conditions[2] else 0,
                1.0 if sell_conditions[3] else 0,
                0.8 if sell_conditions[4] else 0,
                1.0 if sell_conditions[5] else 0,
            ])
            
            # تحديد الإشارة
            buy_signal = buy_score >= self.trading_settings['min_signal_score']
            sell_signal = sell_score >= self.trading_settings['min_signal_score']
            
            direction = None
            signal_strength = 0
            
            if buy_signal:
                direction = 'LONG'
                signal_strength = (buy_score / 6.5) * 100
            elif sell_signal:
                direction = 'SHORT'
                signal_strength = (sell_score / 6.5) * 100

            details = {
                'signal_strength': signal_strength,
                'sma10': latest['sma10'],
                'sma20': latest['sma20'],
                'sma50': latest['sma50'],
                'rsi': latest['rsi'],
                'price': latest['close'],
                'atr': latest['atr'],
                'momentum': latest['momentum'],
                'volume_ratio': latest['volume_ratio'],
                'buy_score': buy_score,
                'sell_score': sell_score,
                'direction': direction,
                'price_vs_sma20': (latest['close'] - latest['sma20']) / latest['sma20'] * 100,
                'trend_strength': (latest['sma10'] - latest['sma50']) / latest['sma50'] * 100,
            }

            return direction is not None, details, direction

        except Exception as e:
            logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
            return False, {}, None
    
    def _detect_contradictions(self, analysis, direction):
        """كشف التناقضات بين المؤشرات"""
        contradictions = 0
    
        # التناقض 1: اتجاه المتوسطات vs الزخم
        if direction == 'LONG':
            if analysis['sma10'] > analysis['sma50'] and analysis['momentum'] < -0.003:
                contradictions += 1
                logger.info("⚠️ تناقض: اتجاه صاعد لكن زخم سلبي قوي")
        else:  # SHORT
            if analysis['sma10'] < analysis['sma50'] and analysis['momentum'] > 0.003:
                contradictions += 1
                logger.info("⚠️ تناقض: اتجاه هابط لكن زخم إيجابي قوي")
    
        # التناقض 2: RSI vs الاتجاه
        if direction == 'LONG' and analysis['rsi'] > 65 and analysis['momentum'] < 0:
            contradictions += 1
            logger.info("⚠️ تناقض: RSI مرتفع في منطقة شراء لكن زخم سلبي")
    
        # التناقض 3: الحجم vs قوة الإشارة
        if analysis['signal_strength'] > 60 and analysis['volume_ratio'] < 1.0:
            contradictions += 1
            logger.info("⚠️ تناقض: إشارة قوية لكن حجم ضعيف")
    
        # التناقض 4: MACD vs المتوسطات
        if direction == 'LONG' and analysis['macd'] < analysis['macd_signal'] and analysis['sma10'] > analysis['sma20']:
            contradictions += 1
            logger.info("⚠️ تناقض: MACD هابط لكن المتوسطات صاعدة")
    
        return contradictions

    def _confirm_trend_multi_timeframe(self, symbol, direction):
        """تأكيد الاتجاه من إطارات زمنية متعددة"""
        try:
            # الحصول على بيانات من إطار زمني أعلى (1 ساعة) للتأكيد
            hourly_data = self.get_historical_data(symbol, '1h', 50)
            if hourly_data is None or len(hourly_data) < 20:
                return True  # إذا فشل الجلب، نعتبر أنه لا تناقض
            
            hourly_data = calculate_indicators(hourly_data)
            if len(hourly_data) == 0:
                return True
            
            latest_hourly = hourly_data.iloc[-1]
        
            # التحقق من تطابق الاتجاه
            if direction == 'LONG':
                trend_confirmed = latest_hourly['sma10'] > latest_hourly['sma50']
            else:  # SHORT
                trend_confirmed = latest_hourly['sma10'] < latest_hourly['sma50']
        
            return trend_confirmed
        
        except Exception as e:
            logger.error(f"❌ خطأ في تأكيد الاتجاه متعدد الإطار لـ {symbol}: {e}")
            return True  # في حالة الخطأ، نعتبر أنه لا مشكلة

    def get_market_health(self, symbol):
        """الحصول على صحة السوق للرمز"""
        try:
            data = self.get_historical_data(symbol, '1h', 100)
            if data is None:
                return {'health': 'unknown', 'volatility': 0, 'trend': 'neutral'}
            
            data = calculate_indicators(data)
            if len(data) < 20:
                return {'health': 'unknown', 'volatility': 0, 'trend': 'neutral'}
            
            latest = data.iloc[-1]
            
            # حساب التقلبات
            volatility = (latest['high'] - latest['low']) / latest['close'] * 100
            
            # تحديد الاتجاه
            if latest['sma10'] > latest['sma50']:
                trend = 'bullish'
            elif latest['sma10'] < latest['sma50']:
                trend = 'bearish'
            else:
                trend = 'neutral'
            
            # تقييم صحة السوق
            health_score = 0
            if 30 <= latest['rsi'] <= 70:
                health_score += 1
            if volatility < 10:  # تقلبات معقولة
                health_score += 1
            if latest['volume_ratio'] > 0.8:
                health_score += 1
            
            if health_score >= 2:
                health = 'healthy'
            elif health_score == 1:
                health = 'moderate'
            else:
                health = 'risky'
            
            return {
                'health': health,
                'volatility': volatility,
                'trend': trend,
                'rsi': latest['rsi'],
                'volume_ratio': latest['volume_ratio']
            }
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل صحة السوق لـ {symbol}: {e}")
            return {'health': 'unknown', 'volatility': 0, 'trend': 'neutral'}
