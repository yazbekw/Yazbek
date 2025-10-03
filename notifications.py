import requests
import time
import hashlib
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from utils import setup_logging

logger = setup_logging()

class TelegramNotifier:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.recent_messages = {}
        self.message_cooldown = 60
        
        # أنواع الإشعارات الجديدة
        self.message_types = {
            'strategy_agreement': '🎯 اتفاق استراتيجيات',
            'strategy_conflict': '⚠️ تعارض استراتيجيات', 
            'advanced_signal': '🚀 إشارة متقدمة',
            'traditional_signal': '🔔 إشارة تقليدية',
            'phase_analysis': '📊 تحليل المرحلة',
            'performance_advanced': '📈 أداء متقدم'
        }

    def send_strategy_agreement_notification(self, symbol, direction, traditional_strength, advanced_strength, market_phase):
        """إشعار اتفاق الاستراتيجيات"""
        message = (
            f"🎯 <b>اتفاق استراتيجيات - إشارة قوية</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {direction}\n"
            f"📊 قوة الإشارة التقليدية: {traditional_strength:.1f}%\n"
            f"🚀 قوة الإشارة المتقدمة: {advanced_strength:.1f}%\n"
            f"📈 مرحلة السوق: {market_phase}\n"
            f"💪 مستوى الثقة: <b>مرتفع جداً</b>\n"
            f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}\n\n"
            f"<b>ملاحظة:</b> هذه أقوى أنواع الإشارات حيث تتفق كلا الاستراتيجيتين"
        )
        return self.send_message(message, 'strategy_agreement')

    def send_strategy_conflict_notification(self, symbol, traditional_direction, advanced_direction, market_phase):
        """إشعار تعارض الاستراتيجيات"""
        message = (
            f"⚠️ <b>تعارض استراتيجيات - توخ الحذر</b>\n"
            f"العملة: {symbol}\n"
            f"📊 الاستراتيجية التقليدية: {traditional_direction}\n"
            f"🚀 الاستراتيجية المتقدمة: {advanced_direction}\n"
            f"📈 مرحلة السوق: {market_phase}\n"
            f"🔍 الحالة: <b>تعارض في التوقعات</b>\n"
            f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}\n\n"
            f"<b>توصية:</b> الانتظار لحين وضوح الصورة أو استخدام إطار زمني أعلى"
        )
        return self.send_message(message, 'strategy_conflict')

    def send_advanced_signal_notification(self, symbol, direction, phase_confidence, market_phase, signal_strength):
        """إشعار الإشارات المتقدمة فقط"""
        message = (
            f"🚀 <b>إشارة من التحليل المتقدم</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {direction}\n"
            f"📈 مرحلة السوق: {market_phase}\n"
            f"🎯 ثقة المرحلة: {phase_confidence*100:.1f}%\n"
            f"💪 قوة الإشارة: {signal_strength:.1f}%\n"
            f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}\n\n"
            f"<b>ملاحظة:</b> هذه الإشارة تعتمد على تحليل مراحل السوق المتقدم\n"
            f"وتحليلات وايكوف، إليوت، VSA، وإيشيموكو"
        )
        return self.send_message(message, 'advanced_signal')

    def send_phase_analysis_report(self, symbol, phase_analysis, price):
        """تقرير تحليل المرحلة المفصل"""
        phase = phase_analysis['phase']
        confidence = phase_analysis['confidence']
        scores = phase_analysis['scores']
        
        message = (
            f"📊 <b>تقرير تحليل المرحلة المتقدم</b>\n"
            f"العملة: {symbol}\n"
            f"💰 السعر الحالي: ${price:.4f}\n"
            f"📈 المرحلة الحالية: <b>{phase}</b>\n"
            f"🎯 مستوى الثقة: {confidence*100:.1f}%\n\n"
            f"<b>توزيع النقاط:</b>\n"
            f"• التجميع: {scores.get('accumulation', 0):.2f}\n"
            f"• الصعود القوي: {scores.get('markup', 0):.2f}\n"
            f"• التوزيع: {scores.get('distribution', 0):.2f}\n"
            f"• الهبوط القوي: {scores.get('markdown', 0):.2f}\n\n"
            f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}"
        )
        return self.send_message(message, 'phase_analysis')

    def send_enhanced_trade_signal_notification(self, symbol, direction, analysis, can_trade, reasons=None):
        """إشعار إشارة تداول محسن مع معلومات الاستراتيجية"""
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
        
        return self.send_message(message, 'trade_signal')
