from datetime import datetime, timedelta
from config import DAMASCUS_TZ
from utils import setup_logging

logger = setup_logging()

class PerformanceReporter:
    """كلاس محسن لتقارير أداء البوت"""
    
    def __init__(self, trade_manager, notifier):
        self.trade_manager = trade_manager
        self.notifier = notifier
        self.start_time = datetime.now(DAMASCUS_TZ)
        self.initial_balance = 0.0
        self.current_balance = 0.0
        self.daily_stats = {
            'trades_opened': 0,
            'trades_closed': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'total_fees': 0.0
        }
        self.daily_reset_time = self._get_next_reset_time()
        
    def _get_next_reset_time(self):
        """الحصول على وقت إعادة التعيين اليومي"""
        now = datetime.now(DAMASCUS_TZ)
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    
    def _reset_daily_stats_if_needed(self):
        """إعادة تعيين الإحصائيات اليومية إذا لزم الأمر"""
        now = datetime.now(DAMASCUS_TZ)
        if now >= self.daily_reset_time:
            self.daily_stats = {
                'trades_opened': 0,
                'trades_closed': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'total_pnl': 0.0,
                'total_fees': 0.0
            }
            self.daily_reset_time = self._get_next_reset_time()
            logger.info("🔄 تم إعادة تعيين الإحصائيات اليومية")
        
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
    
    def record_trade_opened(self):
        """تسجيل فتح صفقة جديدة"""
        self._reset_daily_stats_if_needed()
        self.daily_stats['trades_opened'] += 1
    
    def record_trade_closed(self, pnl, fees=0.0):
        """تسجيل إغلاق صفقة"""
        self._reset_daily_stats_if_needed()
        self.daily_stats['trades_closed'] += 1
        self.daily_stats['total_pnl'] += pnl
        self.daily_stats['total_fees'] += fees
        
        if pnl > 0:
            self.daily_stats['winning_trades'] += 1
        else:
            self.daily_stats['losing_trades'] += 1
    
    def generate_performance_report(self):
        """إنشاء تقرير أداء شامل"""
        if not self.notifier:
            return
            
        try:
            self._reset_daily_stats_if_needed()
            current_time = datetime.now(DAMASCUS_TZ)
            uptime = current_time - self.start_time
            hours = uptime.total_seconds() // 3600
            minutes = (uptime.total_seconds() % 3600) // 60
            
            active_trades = self.trade_manager.get_active_trades_count()
            trade_stats = self.trade_manager.get_trade_statistics()
            
            # حساب الأداء
            total_pnl = self.current_balance - self.initial_balance
            pnl_percentage = (total_pnl / self.initial_balance) * 100 if self.initial_balance > 0 else 0
            
            # حساب معدل النجاح اليومي
            daily_success_rate = 0
            if self.daily_stats['trades_closed'] > 0:
                daily_success_rate = (self.daily_stats['winning_trades'] / self.daily_stats['trades_closed']) * 100
            
            # حساب معدل النجاح العام
            total_closed = trade_stats['closed_trades']
            total_winning = self.daily_stats['winning_trades']  # يمكن تحسين هذا ليشمل التاريخ الكامل
            overall_success_rate = (total_winning / total_closed * 100) if total_closed > 0 else 0

            report = f"""
📊 <b>تقرير أداء البوت الشامل</b>

⏰ <b>معلومات الوقت:</b>
• وقت التشغيل: {hours:.0f} ساعة {minutes:.0f} دقيقة
• وقت التقرير: {current_time.strftime('%Y-%m-%d %H:%M:%S')}
• الإحصائية حتى: {self.daily_reset_time.strftime('%H:%M:%S')}

💰 <b>الأداء المالي:</b>
• الرصيد الأولي: ${self.initial_balance:.2f}
• الرصيد الحالي: ${self.current_balance:.2f}
• إجمالي الربح/الخسارة: ${total_pnl:+.2f} ({pnl_percentage:+.2f}%)

📈 <b>إحصائيات التداول:</b>
• الصفقات النشطة: {active_trades}
• إجمالي الصفقات: {trade_stats['total_trades']}
• الصفقات المغلقة: {trade_stats['closed_trades']}

📅 <b>أداء اليوم:</b>
• الصفقات المفتوحة: {self.daily_stats['trades_opened']}
• الصفقات المغلقة: {self.daily_stats['trades_closed']}
• الصفقات الرابحة: {self.daily_stats['winning_trades']}
• الصفقات الخاسرة: {self.daily_stats['losing_trades']}
• معدل النجاح: {daily_success_rate:.1f}%
• صافي الربح: ${self.daily_stats['total_pnl']:.2f}

🎯 <b>الصفقات النشطة حالياً:</b>
"""
            
            active_trades_details = self.trade_manager.get_all_trades()
            if active_trades_details:
                for symbol, trade in active_trades_details.items():
                    unrealized_pnl = trade.get('unrealized_pnl', 0)
                    pnl_icon = "🟢" if unrealized_pnl > 0 else "🔴"
                    report += f"• {symbol} ({trade['side']}) - الدخول: ${trade['entry_price']:.4f} {pnl_icon}\n"
            else:
                report += "• لا توجد صفقات نشطة\n"
                
            self.notifier.send_message(report, 'performance_report')
            logger.info("✅ تم إرسال تقرير الأداء")
            
        except Exception as e:
            logger.error(f"❌ خطأ في إنشاء تقرير الأداء: {e}")

    def get_performance_summary(self):
        """الحصول على ملخص الأداء"""
        self._reset_daily_stats_if_needed()
        
        total_pnl = self.current_balance - self.initial_balance
        pnl_percentage = (total_pnl / self.initial_balance) * 100 if self.initial_balance > 0 else 0
        
        return {
            'initial_balance': self.initial_balance,
            'current_balance': self.current_balance,
            'total_pnl': total_pnl,
            'pnl_percentage': pnl_percentage,
            'active_trades': self.trade_manager.get_active_trades_count(),
            'daily_trades_opened': self.daily_stats['trades_opened'],
            'daily_trades_closed': self.daily_stats['trades_closed'],
            'daily_winning_trades': self.daily_stats['winning_trades'],
            'daily_total_pnl': self.daily_stats['total_pnl'],
            'uptime_hours': (datetime.now(DAMASCUS_TZ) - self.start_time).total_seconds() / 3600
        }
