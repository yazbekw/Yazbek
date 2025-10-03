import requests
import time
import hashlib
import base64
import logging
from datetime import datetime
from io import BytesIO
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

from config import DAMASCUS_TZ

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """مدير إشعارات التلغرام المحسن مع الإشعارات المتقدمة"""
    
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
            'performance_advanced': '📈 أداء متقدم',
            'trade_open': '✅ فتح صفقة',
            'trade_close': '🔒 إغلاق صفقة',
            'trade_failed': '❌ فشل صفقة',
            'performance_report': '📊 تقرير أداء',
            'heartbeat': '💓 نبضة',
            'startup': '🚀 بدء تشغيل',
            'trade_signal': '🔔 إشارة تداول'
        }

    def send_message(self, message, message_type='info'):
        """إرسال رسالة نصية"""
        try:
            if len(message) > 4096:
                message = message[:4090] + "..."

            current_time = time.time()
            message_hash = hashlib.md5(f"{message_type}_{message}".encode()).hexdigest()
            
            # منع تكرار الرسائل
            if message_hash in self.recent_messages:
                if current_time - self.recent_messages[message_hash] < self.message_cooldown:
                    return True

            self.recent_messages[message_hash] = current_time
            
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': self.chat_id, 
                'text': message, 
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
            
            response = requests.post(url, data=payload, timeout=15)
            if response.status_code == 200:
                logger.info(f"✅ تم إرسال إشعار {self.message_types.get(message_type, message_type)}")
                return True
            else:
                logger.error(f"❌ فشل إرسال إشعار {message_type}: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False

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
        try:
            phase = phase_analysis.get('phase', 'غير محدد')
            confidence = phase_analysis.get('confidence', 0)
            scores = phase_analysis.get('scores', {})
            decision = phase_analysis.get('trading_decision', 'انتظار')
            
            message = (
                f"📊 <b>تقرير تحليل المرحلة المتقدم</b>\n"
                f"العملة: {symbol}\n"
                f"💰 السعر الحالي: ${price:.4f}\n"
                f"📈 المرحلة الحالية: <b>{phase}</b>\n"
                f"🎯 مستوى الثقة: {confidence*100:.1f}%\n"
                f"⚡ توصية التداول: {decision}\n\n"
                f"<b>توزيع النقاط:</b>\n"
                f"• التجميع: {scores.get('accumulation', 0):.2f}\n"
                f"• الصعود القوي: {scores.get('markup', 0):.2f}\n"
                f"• التوزيع: {scores.get('distribution', 0):.2f}\n"
                f"• الهبوط القوي: {scores.get('markdown', 0):.2f}\n\n"
                f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}"
            )
            
            # إنشاء رسم بياني للمراحل
            chart_base64 = self._generate_phase_chart(scores, phase)
            if chart_base64:
                return self._send_photo_with_caption(message, chart_base64, 'phase_analysis')
            else:
                return self.send_message(message, 'phase_analysis')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال تقرير تحليل المرحلة: {e}")
            return False

    def send_enhanced_trade_signal_notification(self, symbol, direction, analysis, can_trade, reasons=None):
        """إشعار إشارة تداول محسن مع معلومات الاستراتيجية"""
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
                        f"💰 الرصيد المتاح: ${analysis.get('available_balance', 0):.2f}\n"
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
                        f"💰 الرصيد المتاح: ${analysis.get('available_balance', 0):.2f}\n"
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
                        f"💰 الرصيد المتاح: ${analysis.get('available_balance', 0):.2f}\n"
                        f"⏰ الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    message = (
                        f"🔔 <b>إشارة تداول</b>\n"
                        f"العملة: {symbol}\n"
                        f"الاتجاه: {direction}\n"
                        f"📊 قوة الإشارة: {signal_strength:.1f}%\n"
                        f"💰 الرصيد المتاح: ${analysis.get('available_balance', 0):.2f}\n"
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
        
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال إشعار الإشارة المحسن: {e}")
            return False

    def send_trade_open_notification(self, symbol, direction, quantity, entry_price, stop_loss, take_profit, leverage, market_phase, strategy_type):
        """إشعار فتح صفقة محسن"""
        message = (
            f"✅ <b>تم فتح الصفقة بنجاح</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {direction}\n"
            f"مرحلة السوق: {market_phase}\n"
            f"نوع الاستراتيجية: {strategy_type}\n"
            f"الكمية: {quantity:.6f}\n"
            f"سعر الدخول: ${entry_price:.4f}\n"
            f"وقف الخسارة: ${stop_loss:.4f}\n"
            f"جني الأرباح: ${take_profit:.4f}\n"
            f"الرافعة: {leverage}x\n"
            f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message, 'trade_open')

    def send_trade_close_notification(self, symbol, side, reason, entry_price, exit_price, market_phase, strategy_type):
        """إشعار إغلاق صفقة محسن"""
        pnl = exit_price - entry_price
        pnl_percentage = (pnl / entry_price) * 100
        
        message = (
            f"🔒 <b>تم إغلاق الصفقة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {side}\n"
            f"السبب: {reason}\n"
            f"مرحلة السوق عند الدخول: {market_phase}\n"
            f"نوع الاستراتيجية: {strategy_type}\n"
            f"سعر الدخول: ${entry_price:.4f}\n"
            f"سعر الخروج: ${exit_price:.4f}\n"
            f"الربح/الخسارة: ${pnl:+.2f} ({pnl_percentage:+.2f}%)\n"
            f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message, 'trade_close')

    def send_trade_failed_notification(self, symbol, direction, error_message):
        """إشعار فشل صفقة"""
        message = (
            f"❌ <b>فشل تنفيذ صفقة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {direction}\n"
            f"السبب: {error_message}\n"
            f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return self.send_message(message, 'trade_failed')

    def send_performance_report(self, report_data):
        """إرسال تقرير أداء"""
        return self.send_message(report_data, 'performance_report')

    def send_advanced_performance_report(self, report_data):
        """إرسال تقرير أداء متقدم"""
        return self.send_message(report_data, 'performance_advanced')

    def send_heartbeat(self, active_trades, status="نشط"):
        """إرسال نبضة محسنة"""
        heartbeat_msg = (
            f"💓 <b>نبضة البوت - النسخة المتقدمة</b>\n"
            f"الوقت: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}\n"
            f"الصفقات النشطة: {active_trades}\n"
            f"الحالة: 🟢 {status}\n"
            f"الميزة: تحليل مراحل السوق المتقدم"
        )
        return self.send_message(heartbeat_msg, 'heartbeat')

    def send_startup_message(self, message):
        """إرسال رسالة بدء التشغيل"""
        return self.send_message(message, 'startup')

    def _generate_phase_chart(self, scores, current_phase):
        """إنشاء رسم بياني لتحليل المراحل"""
        try:
            phases = ['التجميع', 'الصعود القوي', 'التوزيع', 'الهبوط القوي']
            values = [
                scores.get('accumulation', 0),
                scores.get('markup', 0),
                scores.get('distribution', 0),
                scores.get('markdown', 0)
            ]
            
            # تحديد الألوان بناءً على المرحلة الحالية
            colors = ['lightblue'] * 4
            if current_phase == 'accumulation':
                colors[0] = 'blue'
            elif current_phase == 'markup':
                colors[1] = 'green'
            elif current_phase == 'distribution':
                colors[2] = 'orange'
            elif current_phase == 'markdown':
                colors[3] = 'red'
            
            plt.figure(figsize=(10, 6))
            bars = plt.bar(phases, values, color=colors, alpha=0.7)
            
            # إضافة القيم على الأعمدة
            for bar, value in zip(bars, values):
                plt.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                        f'{value:.2f}', ha='center', va='bottom')
            
            plt.title('تحليل مراحل السوق - توزيع النقاط')
            plt.ylabel('النقاط')
            plt.ylim(0, max(values) + 0.2 if max(values) > 0 else 1)
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            
            buffer = BytesIO()
            plt.savefig(buffer, format='png', dpi=80)
            buffer.seek(0)
            plt.close()
            
            return base64.b64encode(buffer.read()).decode('utf-8')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء الرسم البياني للمراحل: {e}")
            return None

    def _send_photo_with_caption(self, caption, photo_base64, message_type):
        """إرسال صورة مع تعليق"""
        try:
            if len(caption) > 1024:
                caption = caption[:1018] + "..."
                
            url = f"{self.base_url}/sendPhoto"
            
            files = {
                'photo': ('chart.png', base64.b64decode(photo_base64), 'image/png')
            }
            
            data = {
                'chat_id': self.chat_id,
                'caption': caption,
                'parse_mode': 'HTML'
            }
            
            response = requests.post(url, files=files, data=data, timeout=20)
            
            if response.status_code == 200:
                logger.info(f"✅ تم إرسال صورة {self.message_types.get(message_type, message_type)}")
                return True
            else:
                logger.error(f"❌ فشل إرسال صورة {message_type}: {response.status_code}")
                # محاولة إرسال الرسالة نصية فقط
                return self.send_message(caption, message_type)
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال الصورة: {e}")
            # العودة للإرسال النصي في حالة الخطأ
            return self.send_message(caption, message_type)

    def send_market_analysis_summary(self, analysis_data):
        """إرسال ملخص تحليل السوق لجميع الرموز"""
        try:
            message = "📊 <b>ملخص تحليل السوق - جميع الرموز</b>\n\n"
            
            for symbol, data in analysis_data.items():
                phase = data.get('phase', 'غير محدد')
                confidence = data.get('confidence', 0)
                price = data.get('price', 0)
                decision = data.get('decision', 'انتظار')
                
                message += (
                    f"<b>{symbol}</b>\n"
                    f"• السعر: ${price:.4f}\n"
                    f"• المرحلة: {phase}\n"
                    f"• الثقة: {confidence*100:.1f}%\n"
                    f"• التوصية: {decision}\n"
                    f"────────────────────\n"
                )
            
            message += f"\n⏰ آخر تحديث: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}"
            
            return self.send_message(message, 'phase_analysis')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال ملخص تحليل السوق: {e}")
            return False

    def cleanup_old_messages(self):
        """تنظيف الرسائل القديمة من الذاكرة"""
        current_time = time.time()
        expired_messages = []
        
        for message_hash, timestamp in self.recent_messages.items():
            if current_time - timestamp > self.message_cooldown * 2:  # ضعف وقت التبريد
                expired_messages.append(message_hash)
        
        for message_hash in expired_messages:
            del self.recent_messages[message_hash]
        
        if expired_messages:
            logger.info(f"🧹 تم تنظيف {len(expired_messages)} رسالة قديمة")

    def test_connection(self):
        """اختبار اتصال التلغرام"""
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                logger.info("✅ اتصال Telegram Bot نشط")
                return True
            else:
                logger.error(f"❌ فشل اختبار اتصال Telegram: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"❌ خطأ في اختبار اتصال Telegram: {e}")
            return False
