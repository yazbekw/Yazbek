import logging
from datetime import datetime, timedelta
from config import DAMASCUS_TZ

logger = logging.getLogger(__name__)

class PerformanceReporter:
    """مدير محسن لتقارير أداء البوت مع إحصائيات الاستراتيجيات المتقدمة"""
    
    def __init__(self, trade_manager, notifier):
        self.trade_manager = trade_manager
        self.notifier = notifier
        self.start_time = datetime.now(DAMASCUS_TZ)
        self.initial_balance = 0.0
        self.current_balance = 0.0
        
        # إحصائيات الاستراتيجيات الجديدة
        self.strategy_stats = {
            'agreement_trades': 0,
            'traditional_trades': 0, 
            'advanced_trades': 0,
            'conflict_avoided': 0,
            'phase_analysis_count': 0,
            'successful_agreement_trades': 0,
            'successful_traditional_trades': 0,
            'successful_advanced_trades': 0
        }
        
        self.daily_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'total_fees': 0.0,
            'agreement_trades': 0,
            'traditional_trades': 0,
            'advanced_trades': 0,
            'date': datetime.now(DAMASCUS_TZ).date()
        }
        
        self.phase_stats = {
            'accumulation_trades': 0,
            'markup_trades': 0,
            'distribution_trades': 0,
            'markdown_trades': 0
        }

    def initialize_balances(self, client):
        """تهيئة الأرصدة من المنصة"""
        try:
            account_info = client.futures_account()
            self.initial_balance = float(account_info['totalWalletBalance'])
            self.current_balance = self.initial_balance
            logger.info(f"💰 تم تهيئة الرصيد: ${self.initial_balance:.2f}")
        except Exception as e:
            logger.error(f"❌ خطأ في تهيئة الأرصدة: {e}")

    def update_balance(self, new_balance):
        """تحديث الرصيد الحالي"""
        self.current_balance = new_balance

    def record_trade_opened(self, symbol, strategy_type, market_phase):
        """تسجيل فتح صفقة جديدة"""
        self.daily_stats['trades_opened'] += 1
        
        # تسجيل إحصائيات الاستراتيجية
        if strategy_type == 'agreement':
            self.strategy_stats['agreement_trades'] += 1
            self.daily_stats['agreement_trades'] += 1
        elif strategy_type == 'traditional':
            self.strategy_stats['traditional_trades'] += 1
            self.daily_stats['traditional_trades'] += 1
        elif strategy_type == 'advanced':
            self.strategy_stats['advanced_trades'] += 1
            self.daily_stats['advanced_trades'] += 1
        
        # تسجيل إحصائيات المرحلة
        if market_phase == 'accumulation':
            self.phase_stats['accumulation_trades'] += 1
        elif market_phase == 'markup':
            self.phase_stats['markup_trades'] += 1
        elif market_phase == 'distribution':
            self.phase_stats['distribution_trades'] += 1
        elif market_phase == 'markdown':
            self.phase_stats['markdown_trades'] += 1
            
        logger.info(f"📊 تم تسجيل صفقة {symbol} - استراتيجية: {strategy_type} - مرحلة: {market_phase}")

    def record_trade_closed(self, symbol, pnl, strategy_type, success=True):
        """تسجيل إغلاق صفقة"""
        self.daily_stats['trades_closed'] += 1
        self.daily_stats['total_pnl'] += pnl
        
        if pnl > 0:
            self.daily_stats['winning_trades'] += 1
        else:
            self.daily_stats['losing_trades'] += 1
        
        # تسجيل نجاح الاستراتيجية
        if success and pnl > 0:
            if strategy_type == 'agreement':
                self.strategy_stats['successful_agreement_trades'] += 1
            elif strategy_type == 'traditional':
                self.strategy_stats['successful_traditional_trades'] += 1
            elif strategy_type == 'advanced':
                self.strategy_stats['successful_advanced_trades'] += 1
        
        logger.info(f"📊 تم إغلاق صفقة {symbol} - PnL: ${pnl:.2f} - استراتيجية: {strategy_type}")

    def record_trade_strategy(self, strategy_type, symbol):
        """تسجيل إحصائيات الاستراتيجية (للتوافق مع الكود السابق)"""
        if strategy_type == 'agreement':
            self.strategy_stats['agreement_trades'] += 1
            self.daily_stats['agreement_trades'] += 1
        elif strategy_type == 'traditional':
            self.strategy_stats['traditional_trades'] += 1
            self.daily_stats['traditional_trades'] += 1
        elif strategy_type == 'advanced':
            self.strategy_stats['advanced_trades'] += 1
            self.daily_stats['advanced_trades'] += 1
            
        logger.info(f"📊 تم تسجيل صفقة {symbol} بنوع استراتيجية: {strategy_type}")

    def record_conflict_avoided(self, symbol):
        """تسجيل تعارض متجنب"""
        self.strategy_stats['conflict_avoided'] += 1
        logger.info(f"⚠️ تم تجنب تعارض استراتيجيات لـ {symbol}")

    def record_phase_analysis(self):
        """تسجيل تحليل مرحلة"""
        self.strategy_stats['phase_analysis_count'] += 1

    def generate_performance_report(self):
        """إنشاء تقرير أداء أساسي"""
        if not self.notifier:
            return
            
        try:
            current_time = datetime.now(DAMASCUS_TZ)
            uptime = current_time - self.start_time
            hours = uptime.total_seconds() // 3600
            minutes = (uptime.total_seconds() % 3600) // 60
            
            active_trades = self.trade_manager.get_active_trades_count()
            
            report = f"""
📊 <b>تقرير أداء البوت الأساسي</b>

⏰ <b>معلومات الوقت:</b>
• وقت التشغيل: {hours:.0f} ساعة {minutes:.0f} دقيقة
• وقت التقرير: {current_time.strftime('%Y-%m-%d %H:%M:%S')}

💰 <b>الأداء المالي:</b>
• الرصيد الأولي: ${self.initial_balance:.2f}
• الرصيد الحالي: ${self.current_balance:.2f}
• التغير: ${(self.current_balance - self.initial_balance):+.2f}
• نسبة التغير: {((self.current_balance - self.initial_balance) / self.initial_balance * 100):+.2f}%

📈 <b>إحصائيات التداول:</b>
• الصفقات النشطة: {active_trades}
• الصفقات المفتوحة اليوم: {self.daily_stats['trades_opened']}
• الصفقات المغلقة اليوم: {self.daily_stats['trades_closed']}
• الصفقات الرابحة: {self.daily_stats['winning_trades']}
• الصفقات الخاسرة: {self.daily_stats['losing_trades']}
• إجمالي PnL: ${self.daily_stats['total_pnl']:+.2f}

🎯 <b>الصفقات النشطة حالياً:</b>
"""
            
            active_trades_details = self.trade_manager.get_all_trades()
            if active_trades_details:
                for symbol, trade in active_trades_details.items():
                    strategy = trade.get('strategy_type', 'غير محدد')
                    phase = trade.get('market_phase', 'غير محدد')
                    report += f"• {symbol} ({trade['side']}) - {strategy} - {phase}\n"
            else:
                report += "• لا توجد صفقات نشطة\n"
                
            self.notifier.send_message(report, 'performance_report')
            logger.info("✅ تم إرسال تقرير الأداء الأساسي")
            
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء تقرير الأداء الأساسي: {e}")

    def generate_advanced_performance_report(self):
        """تقرير أداء متقدم مع إحصائيات الاستراتيجيات"""
        if not self.notifier:
            return
            
        try:
            current_time = datetime.now(DAMASCUS_TZ)
            uptime = current_time - self.start_time
            hours = uptime.total_seconds() // 3600
            minutes = (uptime.total_seconds() % 3600) // 60
            
            active_trades = self.trade_manager.get_active_trades_count()
            
            # تحليل الصفقات النشطة حسب الاستراتيجية
            strategy_breakdown = self._analyze_active_trades_strategy()
            
            # حساب نسب نجاح الاستراتيجيات
            agreement_success_rate = self._calculate_success_rate('agreement')
            traditional_success_rate = self._calculate_success_rate('traditional')
            advanced_success_rate = self._calculate_success_rate('advanced')
            
            report = f"""
📊 <b>تقرير أداء البوت المتقدم</b>

⏰ <b>معلومات الوقت:</b>
• وقت التشغيل: {hours:.0f} ساعة {minutes:.0f} دقيقة
• وقت التقرير: {current_time.strftime('%Y-%m-%d %H:%M:%S')}

💰 <b>الأداء المالي:</b>
• الرصيد الأولي: ${self.initial_balance:.2f}
• الرصيد الحالي: ${self.current_balance:.2f}
• التغير: ${(self.current_balance - self.initial_balance):+.2f}
• نسبة التغير: {((self.current_balance - self.initial_balance) / self.initial_balance * 100):+.2f}%

🎯 <b>إحصائيات الاستراتيجيات:</b>
• الصفقات النشطة: {active_trades}
• إتفاق استراتيجيات: {self.strategy_stats['agreement_trades']} (نجاح: {agreement_success_rate}%)
• إشارات تقليدية: {self.strategy_stats['traditional_trades']} (نجاح: {traditional_success_rate}%)
• إشارات متقدمة: {self.strategy_stats['advanced_trades']} (نجاح: {advanced_success_rate}%)
• تعارضات متجنبة: {self.strategy_stats['conflict_avoided']}

📈 <b>تحليل المراحل:</b>
• عدد التحليلات: {self.strategy_stats['phase_analysis_count']}
• صفقات التجميع: {self.phase_stats['accumulation_trades']}
• صفقات الصعود: {self.phase_stats['markup_trades']}
• صفقات التوزيع: {self.phase_stats['distribution_trades']}
• صفقات الهبوط: {self.phase_stats['markdown_trades']}

🔍 <b>تفصيل الصفقات النشطة:</b>
{strategy_breakdown}

💡 <b>ملاحظات الأداء:</b>
{self._generate_performance_insights()}
"""

            self.notifier.send_message(report, 'performance_advanced')
            logger.info("✅ تم إرسال تقرير الأداء المتقدم")
            
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء تقرير الأداء المتقدم: {e}")

    def _analyze_active_trades_strategy(self):
        """تحليل الصفقات النشطة حسب نوع الاستراتيجية"""
        active_trades = self.trade_manager.get_all_trades()
        strategy_count = {
            'agreement': 0,
            'traditional': 0,
            'advanced': 0,
            'unknown': 0
        }
        
        phase_count = {
            'accumulation': 0,
            'markup': 0, 
            'distribution': 0,
            'markdown': 0,
            'unknown': 0
        }
        
        details = ""
        for symbol, trade in active_trades.items():
            strategy = trade.get('strategy_type', 'unknown')
            strategy_count[strategy] += 1
            
            phase = trade.get('market_phase', 'unknown')
            phase_count[phase] += 1
            
            details += f"• {symbol} ({trade['side']}) - {strategy} - مرحلة: {phase}\n"
        
        if not details:
            details = "• لا توجد صفقات نشطة\n"
            
        summary = f"استراتيجيات: اتفاق {strategy_count['agreement']} | تقليدي {strategy_count['traditional']} | متقدم {strategy_count['advanced']}\n"
        summary += f"مراحل: تجميع {phase_count['accumulation']} | صعود {phase_count['markup']} | توزيع {phase_count['distribution']} | هبوط {phase_count['markdown']}\n"
        return summary + details

    def _calculate_success_rate(self, strategy_type):
        """حساب نسبة نجاح الاستراتيجية"""
        if strategy_type == 'agreement':
            total = self.strategy_stats['agreement_trades']
            successful = self.strategy_stats['successful_agreement_trades']
        elif strategy_type == 'traditional':
            total = self.strategy_stats['traditional_trades']
            successful = self.strategy_stats['successful_traditional_trades']
        elif strategy_type == 'advanced':
            total = self.strategy_stats['advanced_trades']
            successful = self.strategy_stats['successful_advanced_trades']
        else:
            return 0
        
        if total == 0:
            return 0
        return round((successful / total) * 100, 1)

    def _generate_performance_insights(self):
        """توليد ملاحظات أداء ذكية"""
        insights = []
        
        total_trades = (self.strategy_stats['agreement_trades'] + 
                       self.strategy_stats['traditional_trades'] + 
                       self.strategy_stats['advanced_trades'])
        
        if total_trades == 0:
            return "• لا توجد صفقات كافية لتحليل الأداء"
        
        # تحليل أداء الاستراتيجيات
        agreement_rate = self._calculate_success_rate('agreement')
        traditional_rate = self._calculate_success_rate('traditional') 
        advanced_rate = self._calculate_success_rate('advanced')
        
        if agreement_rate > traditional_rate and agreement_rate > advanced_rate:
            insights.append("• استراتيجية الاتفاق تتفوق في الأداء ✅")
        elif advanced_rate > agreement_rate and advanced_rate > traditional_rate:
            insights.append("• الاستراتيجية المتقدمة تظهر نتائج واعدة 🚀")
        
        if self.strategy_stats['conflict_avoided'] > 5:
            insights.append("• نظام تجنب التعارض يعمل بفعالية ⚠️")
        
        # تحليل توزيع المراحل
        total_phase_trades = sum(self.phase_stats.values())
        if total_phase_trades > 0:
            markup_percentage = (self.phase_stats['markup_trades'] / total_phase_trades) * 100
            if markup_percentage > 40:
                insights.append("• التركيز على مراحل الصعود القوي يحقق نتائج جيدة 📈")
        
        if not insights:
            insights.append("• الأداء متوازن across جميع الاستراتيجيات")
        
        return "\n".join(insights)

    def reset_daily_stats(self):
        """إعادة تعيين الإحصائيات اليومية"""
        today = datetime.now(DAMASCUS_TZ).date()
        if today != self.daily_stats['date']:
            self.daily_stats = {
                'trades_opened': 0,
                'trades_closed': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_pnl': 0.0,
                'total_fees': 0.0,
                'agreement_trades': 0,
                'traditional_trades': 0,
                'advanced_trades': 0,
                'date': today
            }
            logger.info("🔄 تم إعادة تعيين الإحصائيات اليومية")

    def get_strategy_performance_summary(self):
        """الحصول على ملخص أداء الاستراتيجيات"""
        return {
            'agreement_trades': self.strategy_stats['agreement_trades'],
            'traditional_trades': self.strategy_stats['traditional_trades'],
            'advanced_trades': self.strategy_stats['advanced_trades'],
            'agreement_success_rate': self._calculate_success_rate('agreement'),
            'traditional_success_rate': self._calculate_success_rate('traditional'),
            'advanced_success_rate': self._calculate_success_rate('advanced'),
            'conflicts_avoided': self.strategy_stats['conflict_avoided'],
            'phase_analyses': self.strategy_stats['phase_analysis_count']
        }

    def generate_phase_analysis_report(self, symbol, phase_analysis, price):
        """تقرير تحليل المرحلة المفصل"""
        if not self.notifier:
            return
            
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
            
            self.notifier.send_message(message, 'phase_analysis')
            
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء تقرير تحليل المرحلة: {e}")
