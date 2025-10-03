import pandas as pd
import numpy as np
from scipy.signal import find_peaks
from typing import Dict, Any, List, Tuple
import logging

logger = logging.getLogger(__name__)

class AdvancedMarketAnalyzer:
    """محلل متقدم لمراحل السوق بناءً على نظريات متعددة"""
    
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
                           lows: List[float], volumes: List[float]) -> Dict[str, Any]:
        """تحليل متكامل لمرحلة السوق مع معالجة أخطاء محسنة"""
        
        # فحص جودة البيانات بشكل محسن
        if len(prices) < 30:  # تقليل الحد الأدنى من 50 إلى 30
            logger.warning(f"⚠️ بيانات غير كافية للتحليل المتقدم: {len(prices)} نقطة")
            return self._default_analysis()
        
        # فحص وجود قيم صفرية أو غير صالحة
        if not prices or any(price <= 0 for price in prices[-10:]) or len(set(prices)) < 5:
            logger.error("❌ بيانات أسعار غير صالحة للتحليل - قيم متطابقة أو صفرية")
            return self._default_analysis()
        
        # فحص أن البيانات ليست ثابتة (لا توجد حركة)
        price_volatility = np.std(prices) / np.mean(prices) if np.mean(prices) > 0 else 0
        if price_volatility < 0.001:  # إذا كانت التقلبات أقل من 0.1%
            logger.warning("⚠️ بيانات سوق غير نشطة - تقلبات ضعيفة جداً")
            return self._default_analysis()
        
        try:
            df = self._create_dataframe(prices, highs, lows, volumes)
            
            # فحص جودة DataFrame بشكل أعمق
            if df.empty or len(df) < 20:
                logger.warning("⚠️ DataFrame فارغ أو صغير جداً")
                return self._default_analysis()
                
            # فحص وجود قيم NaN في الأعمدة المهمة
            critical_columns = ['close', 'high', 'low', 'volume']
            for col in critical_columns:
                if df[col].isnull().any() or df[col].isna().any():
                    logger.warning(f"⚠️ قيم NaN في العمود {col}")
                    return self._default_analysis()
            
            # متابعة التحليل الطبيعي
            analysis_results = {}
            
            # تحليل وايكوف (الأهم)
            analysis_results['wyckoff'] = self._wyckoff_analysis(df)
            
            # موجات إليوت
            analysis_results['elliott'] = self._elliott_wave_analysis(prices)
            
            # تحليل الحجم VSA
            analysis_results['volume_analysis'] = self._volume_spread_analysis(df)
            
            # إيشيموكو
            analysis_results['ichimoku'] = self._ichimoku_analysis(df)
            
            # الزخم التقليدي
            analysis_results['momentum'] = self._momentum_analysis(df)
            
            # دمج النتائج
            final_analysis = self._combine_analyses(analysis_results)
            
            # فحص جودة النتيجة النهائية
            if final_analysis['confidence'] < 0.1:  # إذا كانت الثقة ضعيفة جداً
                logger.warning(f"⚠️ ثقة تحليل منخفضة: {final_analysis['confidence']}")
                
            return final_analysis
                
        except Exception as e:
            logger.error(f"❌ خطأ في التحليل المتقدم: {e}")
            return self._default_analysis()
    
    def _wyckoff_analysis(self, df) -> Dict[str, Any]:
        """تحليل مراحل وايكوف مع نسب مساهمة - الإصدار المصحح"""
        try:
            latest = df.iloc[-1]
            
            # ✅ الإصلاح: استخدام df بدلاً من latest للعمليات التاريخية
            prev_macd_hist = df['macd_hist'].iloc[-2] if len(df) > 1 else 0
            
            wyckoff_signals = {}
            
            # مؤشرات التجميع (Accumulation)
            accumulation_signals = {
                'low_volatility': latest['volatility'] < 0.05,
                'volume_decrease': latest['volume_ratio'] < 1.2,
                'rsi_neutral': 30 <= latest['rsi'] <= 60,
                'price_consolidation': abs(latest['close'] - latest['sma20']) / latest['sma20'] < 0.05,
                'macd_improving': latest['macd_hist'] > prev_macd_hist,  # ✅ الإصلاح هنا
                'support_testing': latest['close'] > latest['bb_lower'] * 1.02,
            }
            
            # مؤشرات الصعود القوي (Markup)
            markup_signals = {
                'trend_up': latest['sma20'] > latest['sma50'],
                'volume_increase': latest['volume_ratio'] > 1.0,
                'rsi_strong': latest['rsi'] > 50,
                'price_rising': latest['close'] > df['close'].iloc[-5] if len(df) > 5 else False,  # ✅ الإصلاح
                'macd_bullish': latest['macd'] > latest['macd_signal'],
                'bb_breakout': latest['close'] > latest['bb_middle'],
            }
            
            # مؤشرات التوزيع (Distribution)
            distribution_signals = {
                'high_volatility': latest['volatility'] > 0.08,
                'volume_spike': latest['volume_ratio'] > 1.5,
                'rsi_overbought': latest['rsi'] > 70,
                'price_deviation': abs(latest['close'] - latest['sma20']) / latest['sma20'] > 0.1,
                'macd_divergence': latest['macd_hist'] < 0,
                'resistance_testing': latest['close'] < latest['bb_upper'] * 0.98,
            }
            
            # مؤشرات الهبوط القوي (Markdown)
            markdown_signals = {
                'trend_down': latest['sma20'] < latest['sma50'],
                'volume_panic': latest['volume_ratio'] > 1.2,
                'rsi_oversold': latest['rsi'] < 30,
                'price_falling': latest['close'] < df['close'].iloc[-5] if len(df) > 5 else False,  # ✅ الإصلاح
                'macd_bearish': latest['macd'] < latest['macd_signal'],
                'bb_breakdown': latest['close'] < latest['bb_middle'],
            }
            
            # حساب النقاط المرجحة
            accumulation_score = sum([
                0.15 if accumulation_signals['low_volatility'] else 0,
                0.15 if accumulation_signals['volume_decrease'] else 0,
                0.20 if accumulation_signals['rsi_neutral'] else 0,
                0.20 if accumulation_signals['price_consolidation'] else 0,
                0.15 if accumulation_signals['macd_improving'] else 0,
                0.15 if accumulation_signals['support_testing'] else 0,
            ])
            
            markup_score = sum([
                0.20 if markup_signals['trend_up'] else 0,
                0.20 if markup_signals['volume_increase'] else 0,
                0.15 if markup_signals['rsi_strong'] else 0,
                0.15 if markup_signals['price_rising'] else 0,
                0.15 if markup_signals['macd_bullish'] else 0,
                0.15 if markup_signals['bb_breakout'] else 0,
            ])
            
            distribution_score = sum([
                0.20 if distribution_signals['high_volatility'] else 0,
                0.20 if distribution_signals['volume_spike'] else 0,
                0.20 if distribution_signals['rsi_overbought'] else 0,
                0.15 if distribution_signals['price_deviation'] else 0,
                0.15 if distribution_signals['macd_divergence'] else 0,
                0.10 if distribution_signals['resistance_testing'] else 0,
            ])
            
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
            logger.error(f"❌ خطأ في تحليل وايكوف: {e}")
            return {
                'accumulation': 0,
                'markup': 0,
                'distribution': 0,
                'markdown': 0,
                'signals': {}
            }
    
    def _elliott_wave_analysis(self, prices: List[float]) -> Dict[str, Any]:
        """تحليل موجات إليوت"""
        if len(prices) < 20:
            return {'wave': 'غير محدد', 'confidence': 0}
        
        try:
            # كشف القمم والقيعان
            peaks, _ = find_peaks(prices, distance=10, prominence=np.std(prices)*0.5)
            troughs, _ = find_peaks([-p for p in prices], distance=10, prominence=np.std(prices)*0.5)
            
            if len(peaks) >= 2 and len(troughs) >= 2:
                # تحليل الاتجاه
                last_peak = prices[peaks[-1]] if len(peaks) > 0 else prices[-1]
                last_trough = prices[troughs[-1]] if len(troughs) > 0 else prices[-1]
                
                if prices[-1] > last_peak and len(peaks) >= 3:
                    return {'wave': 'الموجة الثالثة الصاعدة', 'confidence': 0.7}
                elif prices[-1] < last_trough and len(troughs) >= 2:
                    return {'wave': 'الموجة الثانية التصحيحية', 'confidence': 0.6}
                elif prices[-1] > last_trough and prices[-1] < last_peak:
                    return {'wave': 'الموجة الرابعة التصحيحية', 'confidence': 0.5}
            
            return {'wave': 'موجة غير محددة', 'confidence': 0.3}
            
        except Exception:
            return {'wave': 'غير محدد', 'confidence': 0}
    
    def _volume_spread_analysis(self, df) -> Dict[str, Any]:
        """تحليل الحجم والانتشار (VSA)"""
        try:
            latest = df.iloc[-1]
            
            # مؤشرات VSA
            vsa_signals = {
                'accumulation_volume': latest['volume_ratio'] < 1.2 and latest['spread'] < df['spread'].mean(),
                'markup_volume': latest['volume_ratio'] > 1.0 and latest['close'] > latest['open'],
                'distribution_volume': latest['volume_ratio'] > 1.5 and latest['spread'] > df['spread'].mean(),
                'markdown_volume': latest['volume_ratio'] > 1.2 and latest['close'] < latest['open'],
            }
            
            scores = {
                'accumulation': 0.7 if vsa_signals['accumulation_volume'] else 0,
                'markup': 0.8 if vsa_signals['markup_volume'] else 0,
                'distribution': 0.7 if vsa_signals['distribution_volume'] else 0,
                'markdown': 0.6 if vsa_signals['markdown_volume'] else 0,
            }
            
            return scores
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل VSA: {e}")
            return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
    
    def _ichimoku_analysis(self, df) -> Dict[str, Any]:
        """تحليل سحابة إيشيموكو"""
        try:
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
            logger.error(f"❌ خطأ في تحليل إيشيموكو: {e}")
            return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
    
    def _momentum_analysis(self, df) -> Dict[str, Any]:
        """التحليل التقليدي للزخم"""
        try:
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
            logger.error(f"❌ خطأ في تحليل الزخم: {e}")
            return {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0}
    
    def _combine_analyses(self, analyses: Dict[str, Dict]) -> Dict[str, Any]:
        """دمج جميع التحليلات مع الأوزان"""
        try:
            final_scores = {phase: 0 for phase in ['accumulation', 'markup', 'distribution', 'markdown']}
            
            for phase in final_scores.keys():
                for analysis_type, analysis_data in analyses.items():
                    weight = self.indicator_weights.get(analysis_type, 0.1)
                    if phase in analysis_data:
                        phase_score = analysis_data[phase]
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
            logger.error(f"❌ خطأ في دمج التحليلات: {e}")
            return self._default_analysis()
    
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
    
    def _create_dataframe(self, prices, highs, lows, volumes):
        """إنشاء DataFrame مع جميع المؤشرات ومعالجة الأخطاء"""
        try:
            df = pd.DataFrame({
                'close': prices, 'high': highs, 'low': lows, 'volume': volumes
            })
            
            # تنظيف البيانات - إزالة القيم غير الصالحة
            df = df.replace([np.inf, -np.inf], np.nan)
            df = df.dropna()
            
            if len(df) < 20:
                return df  # إرجاع ما تبقى من البيانات
            
            # المؤشرات الأساسية مع معالجة الأخطاء
            try:
                df['sma20'] = df['close'].rolling(20, min_periods=10).mean()
                df['sma50'] = df['close'].rolling(50, min_periods=20).mean()
            except Exception as e:
                logger.warning(f"⚠️ خطأ في حساب المتوسطات: {e}")
                df['sma20'] = df['close']
                df['sma50'] = df['close']
            
            # RSI مع معالجة الأخطاء
            try:
                delta = df['close'].diff()
                gain = delta.where(delta > 0, 0)
                loss = (-delta).where(delta < 0, 0)
                avg_gain = gain.rolling(14, min_periods=7).mean()
                avg_loss = loss.rolling(14, min_periods=7).mean()
                rs = avg_gain / (avg_loss + 1e-10)  # تجنب القسمة على صفر
                df['rsi'] = 100 - (100 / (1 + rs))
            except Exception as e:
                logger.warning(f"⚠️ خطأ في حساب RSI: {e}")
                df['rsi'] = 50  # قيمة محايدة
            
            # الحجم والمتغيرات الأخرى
            try:
                df['volume_ratio'] = df['volume'] / df['volume'].rolling(20, min_periods=10).mean()
                df['volatility'] = df['close'].rolling(20, min_periods=10).std() / df['close'].rolling(20, min_periods=10).mean()
                df['spread'] = df['high'] - df['low']
            except Exception as e:
                logger.warning(f"⚠️ خطأ في حساب الحجم والتقلبات: {e}")
                df['volume_ratio'] = 1.0
                df['volatility'] = 0.01
                df['spread'] = df['close'] * 0.01
            
            # MACD مع معالجة الأخطاء
            try:
                ema12 = df['close'].ewm(span=12, adjust=False, min_periods=6).mean()
                ema26 = df['close'].ewm(span=26, adjust=False, min_periods=13).mean()
                df['macd'] = ema12 - ema26
                df['macd_signal'] = df['macd'].ewm(span=9, adjust=False, min_periods=4).mean()
                df['macd_hist'] = df['macd'] - df['macd_signal']
            except Exception as e:
                logger.warning(f"⚠️ خطأ في حساب MACD: {e}")
                df['macd'] = 0
                df['macd_signal'] = 0
                df['macd_hist'] = 0
            
            # Bollinger Bands مع معالجة الأخطاء
            try:
                df['bb_middle'] = df['close'].rolling(20, min_periods=10).mean()
                df['bb_std'] = df['close'].rolling(20, min_periods=10).std()
                df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
                df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
            except Exception as e:
                logger.warning(f"⚠️ خطأ في حساب Bollinger Bands: {e}")
                df['bb_middle'] = df['close']
                df['bb_std'] = df['close'] * 0.1
                df['bb_upper'] = df['close'] * 1.2
                df['bb_lower'] = df['close'] * 0.8
            
            # Ichimoku مع معالجة الأخطاء
            try:
                df['tenkan_sen'] = (df['high'].rolling(9, min_periods=4).max() + df['low'].rolling(9, min_periods=4).min()) / 2
                df['kijun_sen'] = (df['high'].rolling(26, min_periods=13).max() + df['low'].rolling(26, min_periods=13).min()) / 2
                df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(26)
                df['senkou_span_b'] = ((df['high'].rolling(52, min_periods=26).max() + df['low'].rolling(52, min_periods=26).min()) / 2).shift(26)
            except Exception as e:
                logger.warning(f"⚠️ خطأ في حساب Ichimoku: {e}")
                df['tenkan_sen'] = df['close']
                df['kijun_sen'] = df['close']
                df['senkou_span_a'] = df['close']
                df['senkou_span_b'] = df['close']
            
            return df.fillna(method='ffill').fillna(method='bfill')
            
        except Exception as e:
            logger.error(f"❌ خطأ فادح في إنشاء DataFrame: {e}")
            # إرجاع DataFrame أساسي كبديل
            return pd.DataFrame({
                'close': prices[-50:], 'high': highs[-50:], 'low': lows[-50:], 'volume': volumes[-50:],
                'sma20': prices[-50:], 'sma50': prices[-50:], 'rsi': 50, 'volume_ratio': 1.0,
                'volatility': 0.01, 'spread': 0.0, 'macd': 0, 'macd_signal': 0, 'macd_hist': 0
            })
    
    def _default_analysis(self):
        """تحليل افتراضي عند عدم وجود بيانات كافية"""
        return {
            'phase': 'غير محدد',
            'confidence': 0,
            'scores': {'accumulation': 0, 'markup': 0, 'distribution': 0, 'markdown': 0},
            'phase_translation': 'غير محدد',
            'trading_decision': 'انتظار',
            'detailed_analysis': {}
        }
