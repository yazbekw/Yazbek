import pandas as pd
import numpy as np
from scipy.signal import find_peaks
from typing import Dict, Any, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class AdvancedMarketAnalyzer:
    """محلل متقدم لمراحل السوق مع معالجة محسنة للأخطاء"""
    
    def __init__(self):
        self.phase_weights = {
            'accumulation': 0.25,      # مرحلة التجميع
            'markup': 0.30,            # مرحلة الصعود القوي
            'distribution': 0.25,      # مرحلة التوزيع
            'markdown': 0.20           # مرحلة الهبوط القوي
        }
        
        self.indicator_weights = {
            'wyckoff': 0.25,           # نظرية وايكوف
            'elliott': 0.20,           # موجات إليوت
            'volume_analysis': 0.20,   # تحليل الحجم (VSA)
            'ichimoku': 0.15,          # سحابة إيشيموكو
            'sentiment': 0.10,         # المشاعر السوقية
            'momentum': 0.10           # الزخم التقليدي
        }
    
    def analyze_market_phase(self, prices: List[float], highs: List[float], 
                           lows: List[float], volumes: List[float], 
                           opens: Optional[List[float]] = None) -> Dict[str, Any]:
        """تحليل متكامل لمرحلة السوق مع معالجة أخطاء محسنة"""
        
        # فحص جودة البيانات الأساسية
        data_validation = self._validate_input_data(prices, highs, lows, volumes, opens)
        if not data_validation["valid"]:
            logger.warning(f"⚠️ {data_validation['message']}")
            return self._default_analysis()
        
        try:
            # إنشاء DataFrame مع البيانات
            df = self._create_dataframe(prices, highs, lows, volumes, opens)
            
            # فحص جودة DataFrame
            if df.empty or len(df) < 20:
                logger.warning("⚠️ DataFrame فارغ أو صغير جداً للتحليل")
                return self._default_analysis()
            
            # فحص وجود الأعمدة الحرجة
            critical_columns = ['close', 'high', 'low', 'volume', 'open']
            missing_columns = [col for col in critical_columns if col not in df.columns]
            if missing_columns:
                logger.warning(f"⚠️ أعمدة مفقودة: {missing_columns}")
                return self._default_analysis()
            
            # فحص وجود قيم NaN في الأعمدة المهمة
            nan_check = self._check_nan_values(df, critical_columns)
            if not nan_check["valid"]:
                logger.warning(f"⚠️ {nan_check['message']}")
                return self._default_analysis()
            
            # إجراء التحليلات المختلفة
            analysis_results = self._perform_all_analyses(df)
            
            # دمج النتائج
            final_analysis = self._combine_analyses(analysis_results)
            
            # تسجيل النتيجة النهائية
            logger.info(f"✅ تحليل السوق: {final_analysis['phase_translation']} - ثقة: {final_analysis['confidence']}")
            
            return final_analysis
            
        except Exception as e:
            logger.error(f"❌ خطأ غير متوقع في التحليل المتقدم: {str(e)}", exc_info=True)
            return self._default_analysis()
    
    def _validate_input_data(self, prices: List[float], highs: List[float], 
                           lows: List[float], volumes: List[float], 
                           opens: Optional[List[float]] = None) -> Dict[str, Any]:
        """التحقق من صحة بيانات الإدخال"""
        
        # فحص الطول
        min_data_points = 30
        if len(prices) < min_data_points:
            return {"valid": False, "message": f"بيانات غير كافية: {len(prices)} نقطة فقط"}
        
        # فحص تطابق الأطوال
        data_lengths = [len(prices), len(highs), len(lows), len(volumes)]
        if opens is not None:
            data_lengths.append(len(opens))
        
        if len(set(data_lengths)) > 1:
            return {"valid": False, "message": "أطوال البيانات غير متطابقة"}
        
        # فحص القيم غير الصالحة
        for i, price in enumerate(prices[-10:]):
            if price <= 0 or np.isnan(price) or np.isinf(price):
                return {"valid": False, "message": f"قيم أسعار غير صالحة عند المؤشر {i}"}
        
        # فحص التنوع في البيانات
        if len(set(prices)) < 5:
            return {"valid": False, "message": "بيانات أسعار متطابقة أو شبه متطابقة"}
        
        # فحص التقلبات
        price_volatility = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 0
        if price_volatility < 0.001:
            return {"valid": False, "message": "بيانات سوق غير نشطة - تقلبات ضعيفة جداً"}
        
        return {"valid": True, "message": "البيانات صالحة للتحليل"}
    
    def _create_dataframe(self, prices: List[float], highs: List[float], 
                         lows: List[float], volumes: List[float], 
                         opens: Optional[List[float]] = None) -> pd.DataFrame:
        """إنشاء DataFrame مع جميع المؤشرات المطلوبة"""
        
        try:
            # إنشاء DataFrame أساسي
            data_dict = {
                'close': prices,
                'high': highs,
                'low': lows,
                'volume': volumes
            }
            
            # إضافة عمود open إذا كان متوفراً
            if opens is not None:
                data_dict['open'] = opens
            else:
                # إنشاء open افتراضي من البيانات المتاحة
                data_dict['open'] = self._calculate_default_opens(prices)
            
            df = pd.DataFrame(data_dict)
            
            # تنظيف البيانات
            df = self._clean_dataframe(df)
            
            # حساب جميع المؤشرات الفنية
            df = self._calculate_all_indicators(df)
            
            return df
            
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء DataFrame: {str(e)}")
            # إرجاع DataFrame أساسي كبديل
            return self._create_fallback_dataframe(prices, highs, lows, volumes)
    
    def _calculate_default_opens(self, prices: List[float]) -> List[float]:
        """حساب قيم افتتاح افتراضية من بيانات الأسعار"""
        opens = [prices[0]]  # أول قيمة افتتاح تساوي أول سعر إغلاق
        
        for i in range(1, len(prices)):
            # استخدام سعر الإغلاق السابق كسعر افتتاح افتراضي
            opens.append(prices[i-1])
        
        return opens
    
    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """تنظيف DataFrame من القيم غير الصالحة"""
        
        # استبدال القيم غير المنتهية
        df = df.replace([np.inf, -np.inf], np.nan)
        
        # حذف الصفوف التي تحتوي على NaN في الأعمدة الأساسية
        critical_cols = ['close', 'high', 'low', 'volume', 'open']
        existing_cols = [col for col in critical_cols if col in df.columns]
        df = df.dropna(subset=existing_cols)
        
        # تعبئة القيم المفقودة في الأعمدة الأخرى
        df = df.ffill().bfill()
        
        return df
    
    def _calculate_all_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب جميع المؤشرات الفنية"""
        
        try:
            # المتوسطات المتحركة
            df = self._calculate_moving_averages(df)
            
            # RSI
            df = self._calculate_rsi(df)
            
            # الحجم والنسب
            df = self._calculate_volume_indicators(df)
            
            # MACD
            df = self._calculate_macd(df)
            
            # Bollinger Bands
            df = self._calculate_bollinger_bands(df)
            
            # Ichimoku
            df = self._calculate_ichimoku(df)
            
            # التقلبات والإحصاءات
            df = self._calculate_volatility_indicators(df)
            
            return df
            
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب بعض المؤشرات: {str(e)}")
            return df  # إرجاع البيانات الأساسية إذا فشل حساب المؤشرات
    
    def _calculate_moving_averages(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب المتوسطات المتحركة"""
        try:
            df['sma20'] = df['close'].rolling(window=20, min_periods=10).mean()
            df['sma50'] = df['close'].rolling(window=50, min_periods=25).mean()
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب المتوسطات المتحركة: {str(e)}")
            df['sma20'] = df['close']
            df['sma50'] = df['close']
        
        return df
    
    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """حساب مؤشر RSI"""
        try:
            delta = df['close'].diff()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            
            avg_gain = gain.rolling(window=period, min_periods=period//2).mean()
            avg_loss = loss.rolling(window=period, min_periods=period//2).mean()
            
            # تجنب القسمة على صفر
            rs = avg_gain / (avg_loss + 1e-10)
            df['rsi'] = 100 - (100 / (1 + rs))
            
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب RSI: {str(e)}")
            df['rsi'] = 50
        
        return df
    
    def _calculate_volume_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب مؤشرات الحجم"""
        try:
            # نسبة الحجم
            df['volume_ratio'] = df['volume'] / df['volume'].rolling(window=20, min_periods=10).mean()
            
            # الانتشار (الفرق بين high و low)
            df['spread'] = df['high'] - df['low']
            
            # نسبة الانتشار
            df['spread_ratio'] = df['spread'] / df['close']
            
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب مؤشرات الحجم: {str(e)}")
            df['volume_ratio'] = 1.0
            df['spread'] = df['close'] * 0.01
            df['spread_ratio'] = 0.01
        
        return df
    
    def _calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب مؤشر MACD"""
        try:
            ema12 = df['close'].ewm(span=12, adjust=False, min_periods=6).mean()
            ema26 = df['close'].ewm(span=26, adjust=False, min_periods=13).mean()
            
            df['macd'] = ema12 - ema26
            df['macd_signal'] = df['macd'].ewm(span=9, adjust=False, min_periods=4).mean()
            df['macd_hist'] = df['macd'] - df['macd_signal']
            
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب MACD: {str(e)}")
            df['macd'] = 0
            df['macd_signal'] = 0
            df['macd_hist'] = 0
        
        return df
    
    def _calculate_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب Bollinger Bands"""
        try:
            df['bb_middle'] = df['close'].rolling(window=20, min_periods=10).mean()
            df['bb_std'] = df['close'].rolling(window=20, min_periods=10).std()
            df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
            df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
            
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب Bollinger Bands: {str(e)}")
            df['bb_middle'] = df['close']
            df['bb_std'] = df['close'] * 0.1
            df['bb_upper'] = df['close'] * 1.2
            df['bb_lower'] = df['close'] * 0.8
        
        return df
    
    def _calculate_ichimoku(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب مؤشر Ichimoku"""
        try:
            # Tenkan-sen (خط التحويل)
            high_9 = df['high'].rolling(window=9, min_periods=4).max()
            low_9 = df['low'].rolling(window=9, min_periods=4).min()
            df['tenkan_sen'] = (high_9 + low_9) / 2
            
            # Kijun-sen (خط الأساس)
            high_26 = df['high'].rolling(window=26, min_periods=13).max()
            low_26 = df['low'].rolling(window=26, min_periods=13).min()
            df['kijun_sen'] = (high_26 + low_26) / 2
            
            # Senkou Span A (المدى الأمامي أ)
            df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
            
            # Senkou Span B (المدى الأمامي ب)
            high_52 = df['high'].rolling(window=52, min_periods=26).max()
            low_52 = df['low'].rolling(window=52, min_periods=26).min()
            df['senkou_span_b'] = ((high_52 + low_52) / 2).shift(26)
            
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب Ichimoku: {str(e)}")
            df['tenkan_sen'] = df['close']
            df['kijun_sen'] = df['close']
            df['senkou_span_a'] = df['close']
            df['senkou_span_b'] = df['close']
        
        return df
    
    def _calculate_volatility_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """حساب مؤشرات التقلب"""
        try:
            df['volatility'] = df['close'].rolling(window=20, min_periods=10).std() / df['close'].rolling(window=20, min_periods=10).mean()
            df['price_change'] = df['close'].pct_change()
        except Exception as e:
            logger.warning(f"⚠️ خطأ في حساب مؤشرات التقلب: {str(e)}")
            df['volatility'] = 0.01
            df['price_change'] = 0.0
        
        return df
    
    def _perform_all_analyses(self, df: pd.DataFrame) -> Dict[str, Any]:
        """إجراء جميع التحليلات الفرعية"""
        
        analyses = {}
        
        try:
            analyses['wyckoff'] = self._wyckoff_analysis(df)
            analyses['elliott'] = self._elliott_wave_analysis(df['close'].tolist())
            analyses['volume_analysis'] = self._volume_spread_analysis(df)
            analyses['ichimoku'] = self._ichimoku_analysis(df)
            analyses['momentum'] = self._momentum_analysis(df)
            
        except Exception as e:
            logger.error(f"❌ خطأ في إجراء التحليلات: {str(e)}")
            # توفير تحليلات افتراضية في حالة الخطأ
            analyses = self._get_default_analyses()
        
        return analyses
    
    def _wyckoff_analysis(self, df: pd.DataFrame) -> Dict[str, Any]:
        """تحليل مراحل وايكوف"""
        try:
            if len(df) < 2:
                return self._get_default_wyckoff_analysis()
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            # مؤشرات التجميع (Accumulation)
            accumulation_signals = {
                'low_volatility': latest.get('volatility', 0.1) < 0.05,
                'volume_decrease': latest.get('volume_ratio', 1.0) < 1.2,
                'rsi_neutral': 30 <= latest.get('rsi', 50) <= 60,
                'price_consolidation': abs(latest.get('close', 0) - latest.get('sma20', latest.get('close', 0))) / latest.get('sma20', 1) < 0.05,
                'macd_improving': latest.get('macd_hist', 0) > prev.get('macd_hist', 0),
                'support_testing': latest.get('close', 0) > latest.get('bb_lower', latest.get('close', 0)) * 1.02,
            }
            
            # حساب النقاط المرجحة للتجميع
            accumulation_score = sum([
                0.15 if accumulation_signals['low_volatility'] else 0,
                0.15 if accumulation_signals['volume_decrease'] else 0,
                0.20 if accumulation_signals['rsi_neutral'] else 0,
                0.20 if accumulation_signals['price_consolidation'] else 0,
                0.15 if accumulation_signals['macd_improving'] else 0,
                0.15 if accumulation_signals['support_testing'] else 0,
            ])
            
            # مؤشرات الصعود القوي (Markup)
            markup_signals = {
                'trend_up': latest.get('sma20', 0) > latest.get('sma50', 0),
                'volume_increase': latest.get('volume_ratio', 1.0) > 1.0,
                'rsi_strong': latest.get('rsi', 50) > 50,
                'price_rising': latest.get('close', 0) > df['close'].iloc[-5] if len(df) > 5 else False,
                'macd_bullish': latest.get('macd', 0) > latest.get('macd_signal', 0),
                'bb_breakout': latest.get('close', 0) > latest.get('bb_middle', latest.get('close', 0)),
            }
            
            markup_score = sum([
                0.20 if markup_signals['trend_up'] else 0,
                0.20 if markup_signals['volume_increase'] else 0,
                0.15 if markup_signals['rsi_strong'] else 0,
                0.15 if markup_signals['price_rising'] else 0,
                0.15 if markup_signals['macd_bullish'] else 0,
                0.15 if markup_signals['bb_breakout'] else 0,
            ])
            
            # مؤشرات التوزيع (Distribution)
            distribution_signals = {
                'high_volatility': latest.get('volatility', 0.1) > 0.08,
                'volume_spike': latest.get('volume_ratio', 1.0) > 1.5,
                'rsi_overbought': latest.get('rsi', 50) > 70,
                'price_deviation': abs(latest.get('close', 0) - latest.get('sma20', latest.get('close', 0))) / latest.get('sma20', 1) > 0.1,
                'macd_divergence': latest.get('macd_hist', 0) < 0,
                'resistance_testing': latest.get('close', 0) < latest.get('bb_upper', latest.get('close', 0)) * 0.98,
            }
            
            distribution_score = sum([
                0.20 if distribution_signals['high_volatility'] else 0,
                0.20 if distribution_signals['volume_spike'] else 0,
                0.20 if distribution_signals['rsi_overbought'] else 0,
                0.15 if distribution_signals['price_deviation'] else 0,
                0.15 if distribution_signals['macd_divergence'] else 0,
                0.10 if distribution_signals['resistance_testing'] else 0,
            ])
            
            # مؤشرات الهبوط القوي (Markdown)
            markdown_signals = {
                'trend_down': latest.get('sma20', 0) < latest.get('sma50', 0),
                'volume_panic': latest.get('volume_ratio', 1.0) > 1.2,
                'rsi_oversold': latest.get('rsi', 50) < 30,
                'price_falling': latest.get('close', 0) < df['close'].iloc[-5] if len(df) > 5 else False,
                'macd_bearish': latest.get('macd', 0) < latest.get('macd_signal', 0),
                'bb_breakdown': latest.get('close', 0) < latest.get('bb_middle', latest.get('close', 0)),
            }
            
            markdown_score = sum([
                0.25 if markdown_signals['trend_down'] else 0,
                0.20 if markdown_signals['volume_panic'] else 0,
                0.20 if markdown_signals['rsi_oversold'] else 0,
                0.15 if markdown_signals['price_falling'] else 0,
                0.10 if markdown_signals['macd_bearish'] else 0,
                0.10 if markdown_signals['bb_breakdown'] else 0,
            ])
            
            return {
                'accumulation': accumulation_score,
                'markup': markup_score,
                'distribution': distribution_score,
                'markdown': markdown_score,
                'signals': {
                    'accumulation': accumulation_signals,
                    'markup': markup_signals,
                    'distribution': distribution_signals,
                    'markdown': markdown_signals
                }
            }
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل وايكوف: {str(e)}")
            return self._get_default_wyckoff_analysis()
    
    def _elliott_wave_analysis(self, prices: List[float]) -> Dict[str, Any]:
        """تحليل موجات إليوت"""
        if len(prices) < 20:
            return {'wave': 'غير محدد', 'confidence': 0}
        
        try:
            # كشف القمم والقيعان
            peaks, _ = find_peaks(prices, distance=10, prominence=np.std(prices)*0.5)
            troughs, _ = find_peaks([-p for p in prices], distance=10, prominence=np.std(prices)*0.5)
            
            if len(peaks) >= 2 and len(troughs) >= 2:
                last_peak = prices[peaks[-1]] if peaks.size > 0 else prices[-1]
                last_trough = prices[troughs[-1]] if troughs.size > 0 else prices[-1]
                
                if prices[-1] > last_peak and len(peaks) >= 3:
                    return {'wave': 'الموجة الثالثة الصاعدة', 'confidence': 0.7}
                elif prices[-1] < last_trough and len(troughs) >= 2:
                    return {'wave': 'الموجة الثانية التصحيحية', 'confidence': 0.6}
                elif prices[-1] > last_trough and prices[-1] < last_peak:
                    return {'wave': 'الموجة الرابعة التصحيحية', 'confidence': 0.5}
            
            return {'wave': 'موجة غير محددة', 'confidence': 0.3}
            
        except Exception as e:
            logger.warning(f"⚠️ خطأ في تحليل موجات إليوت: {str(e)}")
            return {'wave': 'غير محدد', 'confidence': 0}
    
    def _volume_spread_analysis(self, df: pd.DataFrame) -> Dict[str, Any]:
        """تحليل الحجم والانتشار (VSA) - الإصدار المصحح"""
        try:
            # فحص وجود الأعمدة المطلوبة
            required_columns = ['volume_ratio', 'spread', 'close', 'open']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                logger.warning(f"⚠️ أعمدة مفقودة في VSA: {missing_columns}")
                return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
            
            latest = df.iloc[-1]
            
            # مؤشرات VSA مع استخدام get للوصول الآمن للقيم
            vsa_signals = {
                'accumulation_volume': latest.get('volume_ratio', 1.0) < 1.2 and latest.get('spread', 0.0) < df['spread'].mean(),
                'markup_volume': latest.get('volume_ratio', 1.0) > 1.0 and latest.get('close', 0.0) > latest.get('open', 0.0),
                'distribution_volume': latest.get('volume_ratio', 1.0) > 1.5 and latest.get('spread', 0.0) > df['spread'].mean(),
                'markdown_volume': latest.get('volume_ratio', 1.0) > 1.2 and latest.get('close', 0.0) < latest.get('open', 0.0),
            }
            
            scores = {
                'accumulation': 0.7 if vsa_signals['accumulation_volume'] else 0,
                'markup': 0.8 if vsa_signals['markup_volume'] else 0,
                'distribution': 0.7 if vsa_signals['distribution_volume'] else 0,
                'markdown': 0.6 if vsa_signals['markdown_volume'] else 0,
            }
            
            return scores
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل VSA: {str(e)}")
            return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
    
    def _ichimoku_analysis(self, df: pd.DataFrame) -> Dict[str, Any]:
        """تحليل سحابة إيشيموكو"""
        try:
            required_columns = ['close', 'tenkan_sen', 'kijun_sen', 'senkou_span_a', 'senkou_span_b']
            if not all(col in df.columns for col in required_columns):
                return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
            
            latest = df.iloc[-1]
            
            ichimoku_signals = {
                'above_cloud': latest['close'] > latest['senkou_span_a'] and latest['close'] > latest['senkou_span_b'],
                'below_cloud': latest['close'] < latest['senkou_span_a'] and latest['close'] < latest['senkou_span_b'],
                'tenkan_above_kijun': latest['tenkan_sen'] > latest['kijun_sen'],
                'tenkan_below_kijun': latest['tenkan_sen'] < latest['kijun_sen'],
                'future_cloud_bullish': latest['senkou_span_a'] > latest['senkou_span_b'],
                'future_cloud_bearish': latest['senkou_span_a'] < latest['senkou_span_b'],
            }
            
            scores = {
                'accumulation': 0.4 if ichimoku_signals['above_cloud'] and ichimoku_signals['tenkan_above_kijun'] else 0,
                'markup': 0.8 if ichimoku_signals['above_cloud'] and ichimoku_signals['tenkan_above_kijun'] and ichimoku_signals['future_cloud_bullish'] else 0,
                'distribution': 0.6 if ichimoku_signals['below_cloud'] and ichimoku_signals['tenkan_below_kijun'] else 0,
                'markdown': 0.7 if ichimoku_signals['below_cloud'] and ichimoku_signals['tenkan_below_kijun'] and ichimoku_signals['future_cloud_bearish'] else 0,
            }
            
            return scores
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل إيشيموكو: {str(e)}")
            return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
    
    def _momentum_analysis(self, df: pd.DataFrame) -> Dict[str, Any]:
        """التحليل التقليدي للزخم"""
        try:
            required_columns = ['rsi', 'macd', 'macd_signal']
            if not all(col in df.columns for col in required_columns):
                return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
            
            latest = df.iloc[-1]
            
            momentum_signals = {
                'rsi_accumulation': 30 <= latest['rsi'] <= 50,
                'rsi_markup': 50 < latest['rsi'] <= 70,
                'rsi_distribution': latest['rsi'] > 70,
                'rsi_markdown': latest['rsi'] < 30,
                'macd_bullish': latest['macd'] > latest['macd_signal'],
                'macd_bearish': latest['macd'] < latest['macd_signal'],
            }
            
            scores = {
                'accumulation': 0.6 if momentum_signals['rsi_accumulation'] else 0,
                'markup': 0.7 if momentum_signals['rsi_markup'] and momentum_signals['macd_bullish'] else 0,
                'distribution': 0.6 if momentum_signals['rsi_distribution'] else 0,
                'markdown': 0.7 if momentum_signals['rsi_markdown'] and momentum_signals['macd_bearish'] else 0,
            }
            
            return scores
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل الزخم: {str(e)}")
            return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
    
    def _combine_analyses(self, analyses: Dict[str, Dict]) -> Dict[str, Any]:
        """دمج جميع التحليلات مع الأوزان"""
        try:
            final_scores = {phase: 0.0 for phase in ['accumulation', 'markup', 'distribution', 'markdown']}
            
            for phase in final_scores.keys():
                for analysis_type, analysis_data in analyses.items():
                    weight = self.indicator_weights.get(analysis_type, 0.1)
                    if isinstance(analysis_data, dict) and phase in analysis_data:
                        phase_score = analysis_data[phase]
                        if isinstance(phase_score, (int, float)):
                            final_scores[phase] += phase_score * weight
            
            # تحديد المرحلة الأقوى
            best_phase = max(final_scores, key=final_scores.get)
            confidence = final_scores[best_phase]
            
            # تحسين الثقة بناءً على اتفاق المؤشرات
            agreement_count = sum(1 for phase, score in final_scores.items() 
                                if score > confidence * 0.7)
            confidence_boost = min(0.2, agreement_count * 0.05)
            final_confidence = min(1.0, confidence + confidence_boost)
            
            return {
                'phase': best_phase,
                'confidence': round(final_confidence, 2),
                'scores': final_scores,
                'phase_translation': self._translate_phase(best_phase),
                'trading_decision': self._get_trading_decision(best_phase, final_confidence),
                'detailed_analysis': analyses
            }
            
        except Exception as e:
            logger.error(f"❌ خطأ في دمج التحليلات: {str(e)}")
            return self._default_analysis()
    
    def _check_nan_values(self, df: pd.DataFrame, columns: List[str]) -> Dict[str, Any]:
        """فحص وجود قيم NaN في الأعمدة المحددة"""
        try:
            for col in columns:
                if col in df.columns and (df[col].isnull().any() or df[col].isna().any()):
                    return {"valid": False, "message": f"قيم NaN في العمود {col}"}
            return {"valid": True, "message": "لا توجد قيم NaN"}
        except Exception as e:
            return {"valid": False, "message": f"خطأ في فحص NaN: {str(e)}"}
    
    def _create_fallback_dataframe(self, prices: List[float], highs: List[float], 
                                 lows: List[float], volumes: List[float]) -> pd.DataFrame:
        """إنشاء DataFrame بديل في حالة الفشل"""
        data = {
            'close': prices[-50:],
            'high': highs[-50:], 
            'low': lows[-50:],
            'volume': volumes[-50:],
            'open': prices[-50:],  # استخدام close ك open افتراضي
        }
        
        df = pd.DataFrame(data)
        return df
    
    def _get_default_analyses(self) -> Dict[str, Any]:
        """تحليلات افتراضية في حالة الخطأ"""
        return {
            'wyckoff': self._get_default_wyckoff_analysis(),
            'elliott': {'wave': 'غير محدد', 'confidence': 0},
            'volume_analysis': {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0},
            'ichimoku': {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0},
            'momentum': {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
        }
    
    def _get_default_wyckoff_analysis(self) -> Dict[str, Any]:
        """تحليل وايكوف افتراضي"""
        return {
            'accumulation': 0,
            'markup': 0,
            'distribution': 0,
            'markdown': 0,
            'signals': {}
        }
    
    def _translate_phase(self, phase: str) -> str:
        """ترجمة المرحلة للعربية"""
        translations = {
            'accumulation': 'تجميع',
            'markup': 'صعود قوي', 
            'distribution': 'توزيع',
            'markdown': 'هبوط قوي'
        }
        return translations.get(phase, phase)
    
    def _get_trading_decision(self, phase: str, confidence: float) -> str:
        """تحديد قرار التداول المناسب"""
        decisions = {
            'accumulation': 'استعداد للشراء عند كسر المقاومة' if confidence > 0.6 else 'مراقبة للشراء',
            'markup': 'شراء على الارتدادات' if confidence > 0.7 else 'استمرار في الشراء بحذر',
            'distribution': 'استعداد للبيع عند كسر الدعم' if confidence > 0.6 else 'مراقبة للبيع',
            'markdown': 'بيع على الارتدادات' if confidence > 0.7 else 'استمرار في البيع بحذر'
        }
        return decisions.get(phase, 'انتظار')
    
    def _default_analysis(self) -> Dict[str, Any]:
        """تحليل افتراضي عند عدم وجود بيانات كافية"""
        return {
            'phase': 'غير محدد',
            'confidence': 0,
            'scores': {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0},
            'phase_translation': 'غير محدد',
            'trading_decision': 'انتظار',
            'detailed_analysis': {}
        }
