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
        """تحليل الرمز مع النظام المرجح المحسن والشروط المخففة"""
        try:
            data = self.get_historical_data(symbol, self.trading_settings['data_interval'])
            if data is None or len(data) < 50:
                return False, {}, None

            data = calculate_indicators(data)
            if len(data) == 0:
                return False, {}, None

            latest = data.iloc[-1]
            
            # شروط الدخول المخففة بنظام مرجح
            buy_conditions = [
                (latest['sma10'] > latest['sma50'] * 0.995),  # شرط الاتجاه الرئيسي مخفف
                (latest['sma10'] > latest['sma20'] * 0.996),  # شرط مرن مخفف
                (42 <= latest['rsi'] <= 70),  # RSI في نطاق آمن موسع
                (latest['momentum'] > 0.001),  # زخم إيجابي مخفف
                (latest['volume_ratio'] > 0.7),  # حجم معقول مخفف
                (latest['macd'] > latest['macd_signal'] * 0.93)  # MACD إيجابي مخفف
            ]
            
            sell_conditions = [
                (latest['sma10'] < latest['sma50'] * 1.005),  # مخفف
                (latest['sma10'] < latest['sma20'] * 1.004),  # مخفف
                (30 <= latest['rsi'] <= 58),  # RSI موسع
                (latest['momentum'] < -0.001),  # زخم سلبي مخفف
                (latest['volume_ratio'] > 0.7),  # حجم معقول مخفف
                (latest['macd'] < latest['macd_signal'] * 1.07)  # MACD سلبي مخفف
            ]
            
            # نظام الترجيح (يمكن تخفيفه أيضاً)
            buy_score = sum([
                1.4 if buy_conditions[0] else 0,  # مخفف من 1.5
                1.0 if buy_conditions[1] else 0,
                1.1 if buy_conditions[2] else 0,  # مخفف من 1.2
                1.0 if buy_conditions[3] else 0,
                0.9 if buy_conditions[4] else 0,  # مخفف من 0.8
                1.0 if buy_conditions[5] else 0,
            ])
            
            sell_score = sum([
                1.4 if sell_conditions[0] else 0,  # مخفف من 1.5
                1.0 if sell_conditions[1] else 0,
                1.1 if sell_conditions[2] else 0,  # مخفف من 1.2
                1.0 if sell_conditions[3] else 0,
                0.9 if sell_conditions[4] else 0,  # مخفف من 0.8
                1.0 if sell_conditions[5] else 0,
            ])
            
            # تحديد الإشارة مع عتبة مخففة
            min_score = self.trading_settings.get('min_signal_score_loose', 4.2)  # عتبة مخففة
            
            buy_signal = buy_score >= min_score
            sell_signal = sell_score >= min_score
            
            direction = None
            signal_strength = 0
            
            if buy_signal:
                direction = 'LONG'
                signal_strength = (buy_score / 6.4) * 100  # معدل لتتناسب مع الأوزان الجديدة
            elif sell_signal:
                direction = 'SHORT'
                signal_strength = (sell_score / 6.4) * 100

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
                'conditions_met': {
                    'buy_conditions': [bool(cond) for cond in buy_conditions],
                    'sell_conditions': [bool(cond) for cond in sell_conditions]
                }
            }

            return direction is not None, details, direction

        except Exception as e:
            logger.error(f"❌ خطأ في تحليل {symbol}: {e}")
            return False, {}, None
    
    def analyze_symbol_strict(self, symbol):
        """تحليل الرمز بالشروط الأصلية (للحالات عالية المخاطرة)"""
        try:
            data = self.get_historical_data(symbol, self.trading_settings['data_interval'])
            if data is None or len(data) < 50:
                return False, {}, None

            data = calculate_indicators(data)
            if len(data) == 0:
                return False, {}, None

            latest = data.iloc[-1]
            
            # الشروط الأصلية (الصارمة)
            buy_conditions_strict = [
                (latest['sma10'] > latest['sma50']),
                (latest['sma10'] > latest['sma20'] * 0.998),
                (45 <= latest['rsi'] <= 68),
                (latest['momentum'] > 0.002),
                (latest['volume_ratio'] > 0.8),
                (latest['macd'] > latest['macd_signal'] * 0.95)
            ]
            
            sell_conditions_strict = [
                (latest['sma10'] < latest['sma50']),
                (latest['sma10'] < latest['sma20'] * 1.002),
                (32 <= latest['rsi'] <= 55),
                (latest['momentum'] < -0.002),
                (latest['volume_ratio'] > 0.8),
                (latest['macd'] < latest['macd_signal'] * 1.05)
            ]
            
            # نظام الترجيح الأصلي
            buy_score_strict = sum([
                1.5 if buy_conditions_strict[0] else 0,
                1.0 if buy_conditions_strict[1] else 0,
                1.2 if buy_conditions_strict[2] else 0,
                1.0 if buy_conditions_strict[3] else 0,
                0.8 if buy_conditions_strict[4] else 0,
                1.0 if buy_conditions_strict[5] else 0,
            ])
            
            sell_score_strict = sum([
                1.5 if sell_conditions_strict[0] else 0,
                1.0 if sell_conditions_strict[1] else 0,
                1.2 if sell_conditions_strict[2] else 0,
                1.0 if sell_conditions_strict[3] else 0,
                0.8 if sell_conditions_strict[4] else 0,
                1.0 if sell_conditions_strict[5] else 0,
            ])
            
            min_score_strict = self.trading_settings.get('min_signal_score_strict', 5.0)
            
            buy_signal_strict = buy_score_strict >= min_score_strict
            sell_signal_strict = sell_score_strict >= min_score_strict
            
            direction_strict = None
            if buy_signal_strict:
                direction_strict = 'LONG'
            elif sell_signal_strict:
                direction_strict = 'SHORT'

            details_strict = {
                'signal_strength': (buy_score_strict if buy_signal_strict else sell_score_strict) / 6.5 * 100,
                'buy_score': buy_score_strict,
                'sell_score': sell_score_strict,
                'direction': direction_strict,
                'strict_conditions_met': {
                    'buy_conditions': [bool(cond) for cond in buy_conditions_strict],
                    'sell_conditions': [bool(cond) for cond in sell_conditions_strict]
                }
            }

            return direction_strict is not None, details_strict, direction_strict

        except Exception as e:
            logger.error(f"❌ خطأ في التحليل الصارم لـ {symbol}: {e}")
            return False, {}, None
    
    def _detect_contradictions(self, analysis, direction):
        """كشف التناقضات بين المؤشرات (مخفض الحساسية)"""
        contradictions = 0
    
        # التناقض 1: اتجاه المتوسطات vs الزخم (مخفف)
        if direction == 'LONG':
            if analysis['sma10'] > analysis['sma50'] and analysis['momentum'] < -0.005:  # مخفف من -0.003
                contradictions += 1
                logger.info("⚠️ تناقض: اتجاه صاعد لكن زخم سلبي قوي")
        else:  # SHORT
            if analysis['sma10'] < analysis['sma50'] and analysis['momentum'] > 0.005:  # مخفف من 0.003
                contradictions += 1
                logger.info("⚠️ تناقض: اتجاه هابط لكن زخم إيجابي قوي")
    
        # التناقض 2: RSI vs الاتجاه (مخفف)
        if direction == 'LONG' and analysis['rsi'] > 72 and analysis['momentum'] < 0:  # مخفف من 65
            contradictions += 1
            logger.info("⚠️ تناقض: RSI مرتفع في منطقة شراء لكن زخم سلبي")
    
        # التناقض 3: الحجم vs قوة الإشارة (مخفف)
        if analysis['signal_strength'] > 65 and analysis['volume_ratio'] < 0.6:  # مخفف من 60 و1.0
            contradictions += 1
            logger.info("⚠️ تناقض: إشارة قوية لكن حجم ضعيف")
    
        # التناقض 4: MACD vs المتوسطات (مخفف)
        if direction == 'LONG' and analysis['macd'] < analysis['macd_signal'] * 0.90 and analysis['sma10'] > analysis['sma20']:  # مخفف
            contradictions += 1
            logger.info("⚠️ تناقض: MACD هابط لكن المتوسطات صاعدة")
    
        return contradictions

    def _confirm_trend_multi_timeframe(self, symbol, direction):
        """تأكيد الاتجاه من إطارات زمنية متعددة (مخفف)"""
        try:
            # الحصول على بيانات من إطار زمني أعلى (1 ساعة) للتأكيد
            hourly_data = self.get_historical_data(symbol, '1h', 50)
            if hourly_data is None or len(hourly_data) < 20:
                return True  # إذا فشل الجلب، نعتبر أنه لا تناقض
            
            hourly_data = calculate_indicators(hourly_data)
            if len(hourly_data) == 0:
                return True
            
            latest_hourly = hourly_data.iloc[-1]
        
            # التحقق من تطابق الاتجاه (مخفف)
            if direction == 'LONG':
                trend_confirmed = latest_hourly['sma10'] > latest_hourly['sma50'] * 0.995  # مخفف
            else:  # SHORT
                trend_confirmed = latest_hourly['sma10'] < latest_hourly['sma50'] * 1.005  # مخفف
        
            return trend_confirmed
        
        except Exception as e:
            logger.error(f"❌ خطأ في تأكيد الاتجاه متعدد الإطار لـ {symbol}: {e}")
            return True  # في حالة الخطأ، نعتبر أنه لا مشكلة

    def get_market_health(self, symbol):
        """الحصول على صحة السوق للرمز (معايير مخففة)"""
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
            
            # تحديد الاتجاه (مخفف)
            if latest['sma10'] > latest['sma50'] * 0.995:  # مخفف
                trend = 'bullish'
            elif latest['sma10'] < latest['sma50'] * 1.005:  # مخفف
                trend = 'bearish'
            else:
                trend = 'neutral'
            
            # تقييم صحة السوق (معايير مخففة)
            health_score = 0
            if 28 <= latest['rsi'] <= 72:  # موسع
                health_score += 1
            if volatility < 12:  # تقلبات معقولة موسعة
                health_score += 1
            if latest['volume_ratio'] > 0.7:  # مخفف
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
                'volume_ratio': latest['volume_ratio'],
                'health_score': health_score
            }
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل صحة السوق لـ {symbol}: {e}")
            return {'health': 'unknown', 'volatility': 0, 'trend': 'neutral'}

    def get_trading_recommendation(self, symbol):
        """الحصول على توصية تداول شاملة مع الخيارين (مخفف وصارم)"""
        try:
            # التحليل المخفف (الافتراضي)
            has_signal_loose, details_loose, direction_loose = self.analyze_symbol(symbol)
            
            # التحليل الصارم (كخيار بديل)
            has_signal_strict, details_strict, direction_strict = self.analyze_symbol_strict(symbol)
            
            # صحة السوق
            market_health = self.get_market_health(symbol)
            
            recommendation = {
                'symbol': symbol,
                'loose_analysis': {
                    'has_signal': has_signal_loose,
                    'direction': direction_loose,
                    'signal_strength': details_loose.get('signal_strength', 0),
                    'buy_score': details_loose.get('buy_score', 0),
                    'sell_score': details_loose.get('sell_score', 0),
                    'conditions_met': details_loose.get('conditions_met', {})
                },
                'strict_analysis': {
                    'has_signal': has_signal_strict,
                    'direction': direction_strict,
                    'signal_strength': details_strict.get('signal_strength', 0),
                    'buy_score': details_strict.get('buy_score', 0),
                    'sell_score': details_strict.get('sell_score', 0),
                    'conditions_met': details_strict.get('strict_conditions_met', {})
                },
                'market_health': market_health,
                'price': details_loose.get('price', 0),
                'rsi': details_loose.get('rsi', 0),
                'timestamp': pd.Timestamp.now()
            }
            
            return recommendation
            
        except Exception as e:
            logger.error(f"❌ خطأ في التوصية الشاملة لـ {symbol}: {e}")
            return None
