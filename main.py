import threading
import time
import schedule
from datetime import datetime
import numpy as np
import pandas as pd
import random

from config import *
from utils import setup_logging
from notifications import TelegramNotifier
from trade_manager import TradeManager
from market_analyzer import MarketAnalyzer
from price_manager import PriceManager
from performance_reporter import PerformanceReporter
from continuous_monitor import ContinuousMonitor
from web_server import run_flask_app
from advanced_indicators import AdvancedMarketAnalyzer

logger = setup_logging()

class FuturesTradingBot:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        return cls._instance

    def __init__(self):
        if FuturesTradingBot._instance is not None:
            raise Exception("هذه الفئة تستخدم نمط Singleton")

        # التحقق من المفاتيح
        if not all([BINANCE_API_KEY, BINANCE_API_SECRET]):
            raise ValueError("مفاتيح Binance مطلوبة")

        # تهيئة العميل
        try:
            from binance.client import Client
            self.client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)
            self.test_api_connection()
        except Exception as e:
            logger.error(f"❌ فشل تهيئة العميل: {e}")
            raise

        # تهيئة المكونات
        self.notifier = self._initialize_notifier()
        self.symbols = TRADING_SETTINGS['symbols']
        
        # تهيئة المدراء
        self.trade_manager = TradeManager(self.client, self.notifier)
        self.price_manager = PriceManager(self.symbols, self.client)
        self.market_analyzer = MarketAnalyzer(self.client, TRADING_SETTINGS)
        self.performance_reporter = PerformanceReporter(self.trade_manager, self.notifier)
        self.continuous_monitor = ContinuousMonitor(self)
        self.advanced_analyzer = AdvancedMarketAnalyzer()  # المحلل المتقدم
        
        # تهيئة الأرصدة
        self.symbol_balances = self.initialize_symbol_balances()
        self.performance_reporter.initialize_balances(self.client)
        
        # المزامنة الأولية
        self.trade_manager.sync_with_exchange()
        
        # بدء الخدمات
        self._start_services()
        self._send_startup_message()

        FuturesTradingBot._instance = self
        logger.info("✅ تم تهيئة البوت بنجاح")

    def _initialize_notifier(self):
        """تهيئة نظام الإشعارات"""
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            try:
                notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                logger.info("✅ تهيئة Telegram Notifier ناجحة")
                return notifier
            except Exception as e:
                logger.error(f"❌ فشل تهيئة Telegram: {e}")
        return None

    def _start_services(self):
        """بدء الخدمات المساعدة"""
        # بدء خادم Flask
        flask_thread = threading.Thread(target=run_flask_app, daemon=True)
        flask_thread.start()
        
        # بدء تحديث الأسعار
        self._start_price_updater()
        
        # بدء مزامنة الصفقات
        self._start_trade_sync()
        
        # بدء المراقبة المستمرة
        self._start_continuous_monitoring()
        
        # جدولة المهام
        self._schedule_tasks()
        
        logger.info("✅ تم بدء جميع الخدمات المساعدة")

    def _start_price_updater(self):
        """بدء تحديث الأسعار"""
        def price_update_thread():
            while True:
                try:
                    self.price_manager.update_prices()
                    time.sleep(TRADING_SETTINGS['price_update_interval'] * 60)
                except Exception as e:
                    logger.error(f"❌ خطأ في تحديث الأسعار: {str(e)}")
                    time.sleep(30)

        threading.Thread(target=price_update_thread, daemon=True).start()

    def _start_trade_sync(self):
        """بدء مزامنة الصفقات"""
        def sync_thread():
            while True:
                try:
                    self.trade_manager.sync_with_exchange()
                    time.sleep(60)  # مزامنة كل دقيقة
                except Exception as e:
                    logger.error(f"❌ خطأ في مزامنة الصفقات: {str(e)}")
                    time.sleep(30)

        threading.Thread(target=sync_thread, daemon=True).start()

    def _start_continuous_monitoring(self):
        """بدء خدمة المراقبة المستمرة"""
        def monitor_thread():
            while True:
                try:
                    self.continuous_monitor.monitor_active_trades()
                    time.sleep(60)  # فحص كل دقيقة
                except Exception as e:
                    logger.error(f"❌ خطأ في مراقبة الصفقات: {e}")
                    time.sleep(30)
    
        threading.Thread(target=monitor_thread, daemon=True).start()
        logger.info("✅ بدء خدمة المراقبة المستمرة")

    def _schedule_tasks(self):
        """جدولة المهام الدورية مع التقارير الجديدة"""
        if self.notifier:
            # التقارير الأساسية
            schedule.every(3).hours.do(self.send_performance_report)
            schedule.every(30).minutes.do(self.send_heartbeat)
            schedule.every(1).hours.do(self.check_trade_timeout)
            
            # التقارير المتقدمة الجديدة
            schedule.every(6).hours.do(self.send_advanced_performance_report)
            schedule.every(2).hours.do(self.send_phase_analysis_summary)
            
            logger.info("✅ تم جدولة المهام الدورية المتقدمة")

    def _send_startup_message(self):
        """إرسال رسالة بدء التشغيل"""
        if self.notifier:
            message = (
                "🚀 <b>بدء تشغيل بوت العقود الآجلة - النسخة المتقدمة</b>\n\n"
                f"📊 <b>الميزات الجديدة:</b>\n"
                f"• نظام تحليل مراحل السوق المتقدم\n"
                f"• دمج نظريات وايكوف، إليوت، VSA، إيشيموكو\n"
                f"• نظام إشعارات متكامل للاستراتيجيات\n"
                f"• تقارير أداء مفصلة لكل استراتيجية\n\n"
                f"🎯 <b>نسب المساهمة في القرار:</b>\n"
                f"• الصعود القوي: 30%\n"
                f"• الهبوط القوي: 25%\n"
                f"• التجميع: 10%\n"
                f"• التوزيع: 10%\n\n"
                f"🔔 <b>أنواع الإشعارات الجديدة:</b>\n"
                f"• اتفاق استراتيجيات 🎯\n"
                f"• تعارض استراتيجيات ⚠️\n"
                f"• إشارات متقدمة 🚀\n"
                f"• تحليل المراحل 📊\n\n"
                f"🕒 <b>وقت البدء:</b>\n"
                f"{datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
            )
            self.notifier.send_message(message, 'startup')

    def test_api_connection(self):
        """اختبار اتصال API"""
        try:
            server_time = self.client.futures_time()
            logger.info("✅ اتصال Binance API نشط")
            return True
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بـ Binance API: {e}")
            raise

    def initialize_symbol_balances(self):
        """تهيئة أرصدة الرموز"""
        weight_sum = sum(TRADING_SETTINGS['weights'].values())
        return {
            symbol: (weight / weight_sum) * TRADING_SETTINGS['total_capital']
            for symbol, weight in TRADING_SETTINGS['weights'].items()
        }

    def get_current_price(self, symbol):
        """الحصول على السعر الحالي"""
        return self.price_manager.get_price(symbol)

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

    def calculate_indicators(self, data):
        """حساب المؤشرات الفنية"""
        from utils import calculate_indicators
        return calculate_indicators(data)

    def analyze_symbol(self, symbol):
        """تحليل الرمز التقليدي"""
        return self.market_analyzer.analyze_symbol(symbol)

    def advanced_analyze_symbol(self, symbol):
        """تحليل متقدم يجمع بين التحليل التقليدي ومراحل السوق"""
        try:
            # التحليل التقليدي
            has_technical_signal, technical_analysis, technical_direction = self.analyze_symbol(symbol)
            
            # التحليل المتقدم لمراحل السوق (بيانات يومية للرؤية طويلة المدى)
            daily_data = self.get_historical_data(symbol, '1d', 100)
            if daily_data is not None:
                advanced_analysis = self.advanced_analyzer.analyze_market_phase(
                    daily_data['close'].tolist(),
                    daily_data['high'].tolist(), 
                    daily_data['low'].tolist(),
                    daily_data['volume'].tolist()
                )
                
                # تسجيل تحليل المرحلة
                self.performance_reporter.record_phase_analysis()
                
                # دمج القرارات بناءً على نسب المساهمة المطلوبة
                final_decision = self._combine_strategies_with_notifications(
                    symbol, has_technical_signal, technical_direction, technical_analysis, advanced_analysis
                )
                return final_decision
            
            # إذا فشل التحليل المتقدم، نعود للتحليل التقليدي
            return has_technical_signal, technical_analysis, technical_direction
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحليل المتقدم لـ {symbol}: {e}")
            # العودة للتحليل التقليدي في حالة الخطأ
            return self.analyze_symbol(symbol)

    def _combine_strategies_with_notifications(self, symbol, has_traditional_signal, traditional_direction, 
                                             traditional_analysis, advanced_analysis):
        """دمج الاستراتيجيات مع الإشعارات المتكاملة"""
        
        has_advanced_signal, advanced_direction = True, advanced_analysis.get('phase')
        market_phase = advanced_analysis.get('market_phase', 'غير محدد')
        phase_confidence = advanced_analysis.get('phase_confidence', 0)
        
        # إرسال تقرير تحليل المرحلة بشكل عشوائي (20% فرصة)
        if random.random() < 0.2:
            current_price = self.get_current_price(symbol)
            if current_price:
                self.notifier.send_phase_analysis_report(symbol, advanced_analysis, current_price)
        
        # 1. ✅ اتفاق تام بين الاستراتيجيتين (أقوى إشارة)
        if (has_traditional_signal and has_advanced_signal and 
            traditional_direction == advanced_direction):
            
            # إشعار الاتفاق
            self.notifier.send_strategy_agreement_notification(
                symbol, traditional_direction,
                traditional_analysis.get('signal_strength', 50),
                advanced_analysis.get('signal_strength', 50),
                market_phase
            )
            
            # تعزيز قوة الإشارة
            combined_strength = (traditional_analysis.get('signal_strength', 50) + 
                                advanced_analysis.get('signal_strength', 50)) / 2 * 1.2
            
            enhanced_analysis = {
                **traditional_analysis,
                'signal_strength': min(combined_strength, 100),
                'strategy_type': 'agreement',
                'strategy_agreement': True,
                'traditional_strength': traditional_analysis.get('signal_strength', 50),
                'advanced_strength': advanced_analysis.get('signal_strength', 50),
                'market_phase': market_phase,
                'phase_confidence': phase_confidence
            }
            
            logger.info(f"🎯 اتفاق تام على {symbol}: {traditional_direction} - القوة: {combined_strength:.1f}%")
            self.performance_reporter.record_trade_strategy('agreement', symbol)
            return True, enhanced_analysis, traditional_direction
        
        # 2. ⚠️ إشارة تقليدية فقط
        elif has_traditional_signal and not has_advanced_signal:
            logger.info(f"⚠️ إشارة تقليدية فقط لـ {symbol}: {traditional_direction}")
            
            # تخفيف قوة الإشارة
            base_strength = traditional_analysis.get('signal_strength', 50)
            adjusted_strength = base_strength * 0.9  # تخفيف 10%
            
            traditional_analysis['signal_strength'] = adjusted_strength
            traditional_analysis['strategy_type'] = 'traditional'
            traditional_analysis['strategy_agreement'] = False
            traditional_analysis['market_phase'] = market_phase
            traditional_analysis['phase_confidence'] = phase_confidence
            
            self.performance_reporter.record_trade_strategy('traditional', symbol)
            return True, traditional_analysis, traditional_direction
        
        # 3. 🚀 إشارة متقدمة فقط
        elif not has_traditional_signal and has_advanced_signal:
            logger.info(f"🚀 إشارة متقدمة فقط لـ {symbol}: {advanced_direction}")
            
            # الإشارات المتقدمة تحتاج ثقة أعلى
            if phase_confidence > 0.7:  # ثقة عالية في مرحلة السوق
                self.notifier.send_advanced_signal_notification(
                    symbol, advanced_direction, phase_confidence, 
                    market_phase, advanced_analysis.get('signal_strength', 50)
                )
                
                advanced_analysis['strategy_type'] = 'advanced'
                advanced_analysis['strategy_agreement'] = False
                advanced_analysis['signal_strength'] = phase_confidence * 80
                
                self.performance_reporter.record_trade_strategy('advanced', symbol)
                return True, advanced_analysis, advanced_direction
            else:
                logger.info(f"⏸️ تخطي إشارة متقدمة ضعيفة لـ {symbol} - الثقة: {phase_confidence}")
                return False, advanced_analysis, advanced_direction
        
        # 4. ❌ تعارض بين الاستراتيجيتين
        elif (has_traditional_signal and has_advanced_signal and 
              traditional_direction != advanced_direction):
            
            logger.warning(f"❌ تعارض بين الاستراتيجيتين لـ {symbol}")
            
            # إشعار التعارض
            self.notifier.send_strategy_conflict_notification(
                symbol, traditional_direction, advanced_direction, market_phase
            )
            
            self.performance_reporter.record_conflict_avoided(symbol)
            return False, traditional_analysis, None
        
        # 5. 📭 لا توجد إشارات
        else:
            return False, {}, None

    def _is_phase_contradiction(self, direction, market_phase):
        """التحقق من تعارض الاتجاه مع مرحلة السوق"""
        contradictions = {
            'LONG': ['distribution', 'markdown'],  # شراء في توزيع أو هبوط
            'SHORT': ['accumulation', 'markup']    # بيع في تجميع أو صعود
        }
        return market_phase in contradictions.get(direction, [])

    def should_accept_signal(self, symbol, direction, analysis):
        """فلاتر الجودة المحسنة مع مراعاة مراحل السوق"""
        # تجنب الذروة في RSI
        if analysis['rsi'] > 70 and direction == 'LONG':
            logger.info(f"⏸️ تجنب LONG - RSI مرتفع: {analysis['rsi']:.1f}")
            return False
        
        if analysis['rsi'] < 30 and direction == 'SHORT':
            logger.info(f"⏸️ تجنب SHORT - RSI منخفض: {analysis['rsi']:.1f}")
            return False
    
        # قوة الاتجاه
        if abs(analysis['trend_strength']) < TRADING_SETTINGS['min_trend_strength']:
            logger.info(f"⏸️ إشارة ضعيفة - اتجاه ضعيف: {analysis['trend_strength']:.2f}%")
            return False
    
        # تقلبات السعر
        if analysis['atr'] / analysis['price'] > TRADING_SETTINGS['max_volatility'] / 100:
            logger.info(f"⏸️ تقلبات عالية - ATR: {(analysis['atr']/analysis['price']*100):.1f}%")
            return False
        
        # انحراف السعر عن المتوسط
        if abs(analysis['price_vs_sma20']) > TRADING_SETTINGS['max_price_deviation']:
            logger.info(f"⏸️ سعر بعيد عن المتوسط: {analysis['price_vs_sma20']:.1f}%")
            return False
    
        # شرط الزخم
        if direction == 'LONG' and analysis['momentum'] < 0.001:
            logger.info(f"⏸️ تجنب LONG - زخم ضعيف: {analysis['momentum']:.4f}")
            return False
        
        if direction == 'SHORT' and analysis['momentum'] > -0.001:
            logger.info(f"⏸️ تجنب SHORT - زخم ضعيف: {analysis['momentum']:.4f}")
            return False
    
        # شرط حجم
        if analysis['volume_ratio'] < 0.9:
            logger.info(f"⏸️ حجم تداول ضعيف: {analysis['volume_ratio']:.2f}")
            return False
    
        # كشف التناقضات بين المؤشرات
        contradiction_score = self.market_analyzer._detect_contradictions(analysis, direction)
        if contradiction_score >= 2:
            logger.info(f"⏸️ إشارة متناقضة - درجة التناقض: {contradiction_score}")
            return False
    
        # تأكيد الاتجاه من متعدد الإطار الزمني
        if not self.market_analyzer._confirm_trend_multi_timeframe(symbol, direction):
            logger.info(f"⏸️ اتجاه غير مؤكد في الإطارات الزمنية المتعددة")
            return False
    
        return True

    def send_enhanced_trade_signal_notification(self, symbol, direction, analysis, can_trade, reasons=None):
        """إشعار إشارة تداول محسن مع معلومات الاستراتيجية"""
        if not self.notifier:
            return
        
        try:
            strategy_type = analysis.get('strategy_type', 'غير محدد')
            market_phase = analysis.get('market_phase', 'غير محدد')
            phase_confidence = analysis.get('phase_confidence', 0)
            signal_strength = analysis.get('signal_strength', 0)
            
            if can_trade:
                if strategy_type == 'agreement':
                    message = (
                        f"🎯 <b>إشارة تداول قوية - اتفاق استراتيجيات</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"📊 قوة الإشارة: {signal_strength:.1f}%\n"
                        f"📈 مرحلة السوق: {market_phase}\n"
                        f"🎯 ثقة المرحلة: {phase_confidence*100:.1f}%\n"
                        f"💪 نوع الإشارة: <b>اتفاق تام بين الاستراتيجيات</b>\n"
                        f"💰 الرصيد المتاح: ${self.symbol_balances.get(symbol, 0):.2f}\n"
                        f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                elif strategy_type == 'traditional':
                    message = (
                        f"🔔 <b>إشارة تداول تقليدية</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"📊 قوة الإشارة: {signal_strength:.1f}%\n"
                        f"📈 مرحلة السوق: {market_phase}\n"
                        f"💪 نوع الإشارة: <b>إشارة تقليدية فقط</b>\n"
                        f"💰 الرصيد المتاح: ${self.symbol_balances.get(symbol, 0):.2f}\n"
                        f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                elif strategy_type == 'advanced':
                    message = (
                        f"🚀 <b>إشارة تداول متقدمة</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"📊 قوة الإشارة: {signal_strength:.1f}%\n"
                        f"📈 مرحلة السوق: {market_phase}\n"
                        f"🎯 ثقة المرحلة: {phase_confidence*100:.1f}%\n"
                        f"💪 نوع الإشارة: <b>إشارة متقدمة فقط</b>\n"
                        f"💰 الرصيد المتاح: ${self.symbol_balances.get(symbol, 0):.2f}\n"
                        f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    message = (
                        f"🔔 <b>إشارة تداول</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"📊 قوة الإشارة: {signal_strength:.1f}%\n"
                        f"💰 الرصيد المتاح: ${self.symbol_balances.get(symbol, 0):.2f}\n"
                        f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                    )
            else:
                message = (
                    f"⏸️ <b>إشارة تداول - غير قابلة للتنفيذ</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"📊 قوة الإشارة: {signal_strength:.1f}%\n"
                    f"📈 مرحلة السوق: {market_phase}\n"
                    f"<b>أسباب عدم التنفيذ:</b>\n"
                )
                for reason in reasons:
                    message += f"• {reason}\n"
                message += f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
        
            self.notifier.send_message(message, 'trade_signal')
        
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال إشعار الإشارة المحسن: {e}")

    def can_open_trade(self, symbol):
        """التحقق من إمكانية فتح صفقة"""
        reasons = []
        
        # التحقق من الحد الأقصى للصفقات
        if self.trade_manager.get_active_trades_count() >= TRADING_SETTINGS['max_active_trades']:
            reasons.append(f"الحد الأقصى للصفقات ({TRADING_SETTINGS['max_active_trades']})")
            
        # التحقق من وجود صفقة نشطة لنفس الرمز
        if self.trade_manager.is_symbol_trading(symbol):
            reasons.append("صفقة نشطة موجودة")
            
        # التحقق من الرصيد المتاح
        available_balance = self.symbol_balances.get(symbol, 0)
        if available_balance < 5:
            reasons.append(f"رصيد غير كافي: ${available_balance:.2f}")
            
        return len(reasons) == 0, reasons

    def get_futures_precision(self, symbol):
        """الحصول على معلومات الدقة"""
        try:
            info = self.client.futures_exchange_info()
            symbol_info = next((s for s in info['symbols'] if s['symbol'] == symbol), None)
            
            if symbol_info:
                lot_size = next((f for f in symbol_info['filters'] if f['filterType'] == 'LOT_SIZE'), None)
                price_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'PRICE_FILTER'), None)
                min_notional_filter = next((f for f in symbol_info['filters'] if f['filterType'] == 'MIN_NOTIONAL'), None)
                
                min_notional = float(min_notional_filter['notional']) if min_notional_filter else TRADING_SETTINGS['min_notional_value']
                step_size = float(lot_size['stepSize']) if lot_size else 0.001
                
                precision = 0
                if step_size < 1:
                    precision = int(round(-np.log10(step_size)))
                
                return {
                    'step_size': step_size,
                    'tick_size': float(price_filter['tickSize']) if price_filter else 0.001,
                    'precision': precision,
                    'min_qty': float(lot_size['minQty']) if lot_size else 0.001,
                    'min_notional': min_notional
                }
            
            return {
                'step_size': 0.001, 
                'tick_size': 0.001, 
                'precision': 3, 
                'min_qty': 0.001, 
                'min_notional': TRADING_SETTINGS['min_notional_value']
            }
        except Exception as e:
            logger.error(f"❌ خطأ في جلب دقة العقود: {e}")
            return {
                'step_size': 0.001, 
                'tick_size': 0.001, 
                'precision': 3, 
                'min_qty': 0.001, 
                'min_notional': TRADING_SETTINGS['min_notional_value']
            }

    def calculate_position_size(self, symbol, direction, analysis, available_balance):
        """حساب حجم المركز"""
        try:
            current_price = self.get_current_price(symbol)
            if not current_price:
                return None, None, None

            precision_info = self.get_futures_precision(symbol)
            step_size = precision_info['step_size']
            min_notional = precision_info['min_notional']
            
            leverage = TRADING_SETTINGS['max_leverage']
            position_value = min(available_balance * leverage, TRADING_SETTINGS['base_trade_size'])
            
            if position_value < min_notional:
                position_value = min_notional * 1.1
            
            quantity = position_value / current_price
            
            if step_size > 0:
                quantity = round(quantity / step_size) * step_size
            
            if quantity < precision_info['min_qty']:
                quantity = precision_info['min_qty']
                position_value = quantity * current_price
            
            if position_value < min_notional:
                return None, None, None
            
            atr = analysis.get('atr', current_price * 0.02)
            stop_loss_pct = (TRADING_SETTINGS['atr_stop_loss_multiplier'] * atr / current_price)
            take_profit_pct = (TRADING_SETTINGS['atr_take_profit_multiplier'] * atr / current_price)
            
            if direction == 'LONG':
                stop_loss_price = current_price * (1 - stop_loss_pct)
                take_profit_price = current_price * (1 + take_profit_pct)
            else:
                stop_loss_price = current_price * (1 + stop_loss_pct)
                take_profit_price = current_price * (1 - take_profit_pct)
            
            return quantity, stop_loss_price, take_profit_price
            
        except Exception as e:
            logger.error(f"❌ خطأ في حساب حجم المركز لـ {symbol}: {e}")
            return None, None, None

    def set_leverage(self, symbol, leverage):
        """ضبط الرافعة المالية"""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            logger.warning(f"⚠️ خطأ في ضبط الرافعة لـ {symbol}: {e}")
            return True

    def set_margin_type(self, symbol, margin_type):
        """ضبط نوع الهامش"""
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
            return True
        except Exception as e:
            error_msg = str(e)
            if "No need to change margin type" in error_msg:
                return True
            elif "Account has open positions" in error_msg:
                return True
            else:
                logger.warning(f"⚠️ فشل ضبط نوع الهامش لـ {symbol}: {error_msg}")
                return True

    def execute_trade(self, symbol, direction, quantity, stop_loss_price, take_profit_price, analysis):
        """تنفيذ الصفقة"""
        try:
            current_price = self.get_current_price(symbol)
            if not current_price:
                raise Exception("لا يمكن الحصول على السعر الحالي")
                
            notional_value = quantity * current_price
            min_notional = self.get_futures_precision(symbol)['min_notional']
            
            if notional_value < min_notional:
                raise Exception(f"القيمة الاسمية ${notional_value:.2f} أقل من الحد الأدنى ${min_notional:.2f}")
            
            if not self.set_leverage(symbol, TRADING_SETTINGS['max_leverage']):
                raise Exception("فشل ضبط الرافعة")
                
            if not self.set_margin_type(symbol, TRADING_SETTINGS['margin_type']):
                raise Exception("فشل ضبط نوع الهامش")
            
            side = 'BUY' if direction == 'LONG' else 'SELL'
            
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity,
                reduceOnly=False
            )
            
            # انتظار التنفيذ
            executed_qty = 0
            for i in range(10):
                time.sleep(0.5)
                order_status = self.client.futures_get_order(symbol=symbol, orderId=order['orderId'])
                executed_qty = float(order_status.get('executedQty', 0))
                if executed_qty > 0:
                    break
            
            if executed_qty == 0:
                try:
                    self.client.futures_cancel_order(symbol=symbol, orderId=order['orderId'])
                except:
                    pass
                raise Exception("الأمر لم ينفذ")
            
            # الحصول على سعر الدخول الفعلي
            avg_price = float(order_status.get('avgPrice', 0))
            if avg_price == 0:
                avg_price = current_price
            
            # تسجيل الصفقة
            trade_data = {
                'symbol': symbol,
                'quantity': quantity,
                'entry_price': avg_price,
                'leverage': TRADING_SETTINGS['max_leverage'],
                'side': direction,
                'timestamp': datetime.now(DAMASCUS_TZ),
                'status': 'open',
                'trade_type': 'futures',
                'stop_loss': stop_loss_price,
                'take_profit': take_profit_price,
                'order_id': order['orderId'],
                'market_phase': analysis.get('market_phase', 'غير محدد'),
                'strategy_type': analysis.get('strategy_type', 'غير محدد')
            }
            
            self.trade_manager.add_trade(symbol, trade_data)
            
            # تحديث الرصيد
            trade_value_leverage = notional_value / TRADING_SETTINGS['max_leverage']
            self.symbol_balances[symbol] = max(0, self.symbol_balances[symbol] - trade_value_leverage)
            
            if self.notifier:
                message = (
                    f"✅ <b>تم فتح الصفقة بنجاح</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"مرحلة السوق: {analysis.get('market_phase', 'غير محدد')}\n"
                    f"نوع الاستراتيجية: {analysis.get('strategy_type', 'غير محدد')}\n"
                    f"الكمية: {quantity:.6f}\n"
                    f"سعر الدخول: ${avg_price:.4f}\n"
                    f"وقف الخسارة: ${stop_loss_price:.4f}\n"
                    f"جني الأرباح: ${take_profit_price:.4f}\n"
                    f"الرافعة: {TRADING_SETTINGS['max_leverage']}x\n"
                    f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                )
                self.notifier.send_message(message, 'trade_open')
            
            logger.info(f"✅ تم فتح صفقة {direction} لـ {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ فشل تنفيذ صفقة {symbol}: {e}")
            
            if self.notifier:
                message = (
                    f"❌ <b>فشل تنفيذ صفقة</b>\n"
                    f"العملة: {symbol}\n"
                    f"الاتجاه: {direction}\n"
                    f"السبب: {str(e)}"
                )
                self.notifier.send_message(message, 'trade_failed')
            
            return False

    def check_trade_timeout(self):
        """فحص انتهاء وقت الصفقات"""
        current_time = datetime.now(DAMASCUS_TZ)
        symbols_to_close = []
        
        for symbol, trade in self.trade_manager.get_all_trades().items():
            trade_age = current_time - trade['timestamp']
            hours_open = trade_age.total_seconds() / 3600
            
            if hours_open >= TRADING_SETTINGS['trade_timeout_hours']:
                symbols_to_close.append(symbol)
                logger.info(f"⏰ انتهاء وقت الصفقة لـ {symbol}")
        
        for symbol in symbols_to_close:
            self.close_trade(symbol, 'timeout')

    def close_trade(self, symbol, reason='manual'):
        """إغلاق الصفقة"""
        try:
            trade = self.trade_manager.get_trade(symbol)
            if not trade:
                return False

            current_price = self.get_current_price(symbol)
            if not current_price:
                return False

            side = 'SELL' if trade['side'] == 'LONG' else 'BUY'
            
            order =
