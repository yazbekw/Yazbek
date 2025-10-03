import time
from datetime import datetime
from config import DAMASCUS_TZ, TRADING_SETTINGS
from utils import setup_logging

logger = setup_logging()

class ContinuousMonitor:
    """مراقب مستمر للصفقات النشطة بناءً على المؤشرات"""
    
    def __init__(self, bot):
        self.bot = bot
        self.monitor_interval = TRADING_SETTINGS['continuous_monitor_interval']
        self.last_monitor_time = {}
        self.exit_threshold = TRADING_SETTINGS['exit_signal_threshold']

    def is_trade_old_enough(self, trade):
        """التحقق من أن الصفقة قديمة بما يكفي للمراقبة"""
        trade_age = datetime.now(DAMASCUS_TZ) - trade['timestamp']
        min_age_minutes = TRADING_SETTINGS.get('min_trade_age_for_monitor', 30)
        return trade_age.total_seconds() >= min_age_minutes * 60
        
    def should_monitor_trade(self, symbol, trade):
        """التحقق من الحاجة لمراقبة الصفقة"""
        # أولاً تحقق من عمر الصفقة
        if not self.is_trade_old_enough(trade):
            return False
            
        current_time = time.time()
        last_time = self.last_monitor_time.get(symbol, 0)
        
        if current_time - last_time >= self.monitor_interval * 60:
            self.last_monitor_time[symbol] = current_time
            return True
        return False
    
    def analyze_trade_for_exit(self, symbol, trade):
        """تحليل الصفقة لتحديد إذا كانت تحتاج للإغلاق"""
        try:
            # الحصول على البيانات الحالية
            data = self.bot.get_historical_data(symbol, TRADING_SETTINGS['data_interval'], 50)
            if data is None or len(data) < 20:
                return False, "لا توجد بيانات كافية"
            
            data = self.bot.calculate_indicators(data)
            if len(data) == 0:
                return False, "فشل حساب المؤشرات"
            
            latest = data.iloc[-1]
            current_price = self.bot.get_current_price(symbol)
            
            if current_price is None:
                return False, "لا يمكن الحصول على السعر الحالي"
            
            # تحليل الإشارات بناءً على اتجاه الصفقة
            if trade['side'] == 'LONG':
                exit_signal, exit_score = self._check_long_exit_signals(latest, current_price, trade)
                reason = self._get_exit_reason(exit_score, 'LONG')
            else:  # SHORT
                exit_signal, exit_score = self._check_short_exit_signals(latest, current_price, trade)
                reason = self._get_exit_reason(exit_score, 'SHORT')
            
            return exit_signal, reason
            
        except Exception as e:
            logger.error(f"❌ خطأ في تحليل الخروج لـ {symbol}: {e}")
            return False, f"خطأ في التحليل: {e}"
    
    def _check_long_exit_signals(self, latest, current_price, trade):
        """فحص إشارات الخروج لصفقات LONG"""
        exit_conditions = [
            # انعكاس الاتجاه
            latest['sma10'] < latest['sma20'],
            # ضعف الزخم
            latest['momentum'] < -0.005,
            # RSI في منطقة ذروة الشراء
            latest['rsi'] > 70,
            # انعكاس MACD
            latest['macd'] < latest['macd_signal'],
            # اختراق المتوسط المتحرك الرئيسي
            current_price < latest['sma50'] * 0.995,
            # تحقيق هدف الربح (إذا وجد)
            'take_profit' in trade and current_price >= trade['take_profit'],
            # اختراق وقف الخسارة (إذا وجد)
            'stop_loss' in trade and current_price <= trade['stop_loss']
        ]
        
        # نظام ترجيح للإشارات
        exit_score = sum([
            1.5 if exit_conditions[0] else 0,  # انعكاس الاتجاه القصير
            1.2 if exit_conditions[1] else 0,  # زخم سلبي قوي
            1.0 if exit_conditions[2] else 0,  # RSI مرتفع
            0.8 if exit_conditions[3] else 0,  # انعكاس MACD
            1.0 if exit_conditions[4] else 0,  # اختراق المتوسط الرئيسي
            2.0 if exit_conditions[5] else 0,  # تحقيق هدف الربح
            2.5 if exit_conditions[6] else 0   # اختراق وقف الخسارة
        ])
        
        return exit_score >= self.exit_threshold, exit_score
    
    def _check_short_exit_signals(self, latest, current_price, trade):
        """فحص إشارات الخروج لصفقات SHORT"""
        exit_conditions = [
            # انعكاس الاتجاه
            latest['sma10'] > latest['sma20'],
            # قوة الزخم الإيجابي
            latest['momentum'] > 0.005,
            # RSI في منطقة ذروة البيع
            latest['rsi'] < 30,
            # انعكاس MACD
            latest['macd'] > latest['macd_signal'],
            # اختراق المتوسط المتحرك الرئيسي
            current_price > latest['sma50'] * 1.005,
            # تحقيق هدف الربح (إذا وجد)
            'take_profit' in trade and current_price <= trade['take_profit'],
            # اختراق وقف الخسارة (إذا وجد)
            'stop_loss' in trade and current_price >= trade['stop_loss']
        ]
        
        exit_score = sum([
            1.5 if exit_conditions[0] else 0,
            1.2 if exit_conditions[1] else 0,
            1.0 if exit_conditions[2] else 0,
            0.8 if exit_conditions[3] else 0,
            1.0 if exit_conditions[4] else 0,
            2.0 if exit_conditions[5] else 0,
            2.5 if exit_conditions[6] else 0
        ])
        
        return exit_score >= self.exit_threshold, exit_score
    
    def _get_exit_reason(self, exit_score, direction):
        """الحصول على سبب الخروج بناءً على النقاط"""
        if exit_score >= 4:
            return f"إشارة خروج قوية جداً لـ {direction}"
        elif exit_score >= 3:
            return f"إشارة خروج قوية لـ {direction}"
        elif exit_score >= 2:
            return f"إشارة خروج متوسطة لـ {direction}"
        else:
            return f"إشارة خروج ضعيفة لـ {direction}"
    
    def monitor_active_trades(self):
        """مراقبة جميع الصفقات النشطة"""
        try:
            active_trades = self.bot.trade_manager.get_all_trades()
            monitored_count = 0
            exit_signals = 0
            
            for symbol, trade in active_trades.items():
                if not self.should_monitor_trade(symbol, trade):
                    continue
                
                monitored_count += 1
                should_exit, reason = self.analyze_trade_for_exit(symbol, trade)
                
                if should_exit:
                    exit_signals += 1
                    logger.info(f"🔄 إغلاق صفقة {symbol} بناءً على المراقبة: {reason}")
                    success = self.bot.close_trade(symbol, f"مراقبة_مستمرة: {reason}")
                    
                    if success and self.bot.notifier:
                        message = (
                            f"🔄 <b>إغلاق تلقائي للصفقة</b>\n"
                            f"العملة: {symbol}\n"
                            f"الاتجاه: {trade['side']}\n"
                            f"السبب: {reason}\n"
                            f"وقت المراقبة: {datetime.now(DAMASCUS_TZ).strftime('%H:%M:%S')}"
                        )
                        self.bot.notifier.send_message(message, 'auto_close')
            
            if monitored_count > 0:
                logger.info(f"🔍 تم مراقبة {monitored_count} صفقة، {exit_signals} إشارة خروج")
                    
        except Exception as e:
            logger.error(f"❌ خطأ في مراقبة الصفقات: {e}")

    def force_monitor_trade(self, symbol):
        """إجبار مراقبة صفقة معينة (للاستخدام اليدوي)"""
        trade = self.bot.trade_manager.get_trade(symbol)
        if not trade:
            logger.error(f"❌ لا توجد صفقة نشطة للرمز {symbol}")
            return False, "لا توجد صفقة نشطة"
        
        should_exit, reason = self.analyze_trade_for_exit(symbol, trade)
        return should_exit, reason
