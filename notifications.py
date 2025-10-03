import requests
import time
import hashlib
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from utils import setup_logging

logger = setup_logging()

class TelegramNotifier:
    """مدير إشعارات التلغرام"""
    
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.recent_messages = {}
        self.message_cooldown = 60

    def send_message(self, message, message_type='info'):
        """إرسال رسالة عبر Telegram"""
        try:
            if not self.token or not self.chat_id:
                logger.warning("⚠️ إعدادات Telegram غير مكتملة")
                return False

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
            success = response.status_code == 200
            
            if success:
                logger.info(f"✅ تم إرسال رسالة {message_type}")
            else:
                logger.error(f"❌ فشل إرسال الرسالة: {response.status_code}")
                
            return success
                
        except Exception as e:
            logger.error(f"❌ خطأ في إرسال رسالة تلغرام: {e}")
            return False

    def send_trade_signal(self, symbol, direction, signal_strength, price, available_balance):
        """إرسال إشعار إشارة تداول"""
        message = (
            f"🔔 <b>إشارة تداول جديدة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {direction}\n"
            f"قوة الإشارة: {signal_strength:.1f}%\n"
            f"السعر الحالي: ${price:.4f}\n"
            f"الرصيد المتاح: ${available_balance:.2f}"
        )
        return self.send_message(message, 'trade_signal')

    def send_trade_executed(self, symbol, direction, quantity, entry_price, stop_loss, take_profit):
        """إرسال إشعار تنفيذ صفقة"""
        message = (
            f"✅ <b>تم تنفيذ الصفقة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {direction}\n"
            f"الكمية: {quantity:.6f}\n"
            f"سعر الدخول: ${entry_price:.4f}\n"
            f"وقف الخسارة: ${stop_loss:.4f}\n"
            f"جني الأرباح: ${take_profit:.4f}"
        )
        return self.send_message(message, 'trade_executed')

    def send_trade_closed(self, symbol, direction, entry_price, exit_price, reason):
        """إرسال إشعار إغلاق صفقة"""
        pnl = exit_price - entry_price
        pnl_percentage = (pnl / entry_price) * 100
        pnl_icon = "🟢" if pnl > 0 else "🔴"
        
        message = (
            f"🔒 <b>تم إغلاق الصفقة</b>\n"
            f"العملة: {symbol}\n"
            f"الاتجاه: {direction}\n"
            f"سعر الدخول: ${entry_price:.4f}\n"
            f"سعر الخروج: ${exit_price:.4f}\n"
            f"الربح/الخسارة: {pnl_icon} ${pnl:.4f} ({pnl_percentage:+.2f}%)\n"
            f"السبب: {reason}"
        )
        return self.send_message(message, 'trade_closed')

    def send_error(self, error_message, context=None):
        """إرسال إشعار خطأ"""
        message = f"❌ <b>خطأ في النظام</b>\n{error_message}"
        if context:
            message += f"\nالسياق: {context}"
        return self.send_message(message, 'error')

    def send_heartbeat(self, active_trades, status="🟢 نشط"):
        """إرسال نبضة حياة"""
        from utils import get_current_time
        current_time = get_current_time().strftime('%H:%M:%S')
        
        message = (
            f"💓 <b>نبضة البوت</b>\n"
            f"الوقت: {current_time}\n"
            f"الصفقات النشطة: {active_trades}\n"
            f"الحالة: {status}"
        )
        return self.send_message(message, 'heartbeat')
