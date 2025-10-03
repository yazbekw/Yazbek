from datetime import datetime
from config import DAMASCUS_TZ
from utils import setup_logging

logger = setup_logging()

class TradeManager:
    """مدير محسن للصفقات مع تتبع دقيق"""
    
    def __init__(self, client, notifier):
        self.client = client
        self.notifier = notifier
        self.active_trades = {}
        self.trade_history = []
        self.last_sync = datetime.now(DAMASCUS_TZ)
        
    def sync_with_exchange(self):
        """مزامنة الصفقات مع المنصة بدقة"""
        try:
            logger.info("🔄 مزامنة الصفقات مع المنصة...")
            
            # جلب جميع المراكز من المنصة
            account_info = self.client.futures_account()
            positions = account_info['positions']
            
            # جلب الأوامر المفتوحة
            open_orders = self.client.futures_get_open_orders()
            
            active_symbols = set()
            valid_trades = {}
            
            # تحليل المراكز النشطة
            for position in positions:
                symbol = position['symbol']
                quantity = float(position['positionAmt'])
                
                if quantity != 0:  # مركز نشط
                    active_symbols.add(symbol)
                    
                    # البحث عن أمر فتح مرتبط
                    entry_order = None
                    for order in open_orders:
                        if order['symbol'] == symbol and order['type'] == 'MARKET' and order['side'] in ['BUY', 'SELL']:
                            entry_order = order
                            break
                    
                    # إنشاء بيانات الصفقة
                    side = "LONG" if quantity > 0 else "SHORT"
                    entry_price = float(position['entryPrice'])
                    leverage = float(position['leverage'])
                    
                    trade_data = {
                        'symbol': symbol,
                        'quantity': abs(quantity),
                        'entry_price': entry_price,
                        'leverage': leverage,
                        'side': side,
                        'timestamp': datetime.now(DAMASCUS_TZ),
                        'status': 'open',
                        'trade_type': 'futures',
                        'position_amt': quantity,
                        'unrealized_pnl': float(position['unrealizedProfit']),
                        'order_id': entry_order['orderId'] if entry_order else None
                    }
                    
                    valid_trades[symbol] = trade_data
                    logger.info(f"✅ تمت مزامنة صفقة نشطة: {symbol} - {side}")
            
            # تحديث الصفقات النشطة
            self.active_trades = valid_trades
            
            # تسجيل الصفقات المغلقة
            self.record_closed_trades(active_symbols)
            
            self.last_sync = datetime.now(DAMASCUS_TZ)
            logger.info(f"✅ اكتملت المزامنة: {len(self.active_trades)} صفقات نشطة")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ خطأ في مزامنة الصفقات: {e}")
            return False
    
    def record_closed_trades(self, current_active_symbols):
        """تسجيل الصفقات المغلقة"""
        previous_symbols = set(self.active_trades.keys())
        closed_symbols = previous_symbols - current_active_symbols
        
        for symbol in closed_symbols:
            if symbol in self.active_trades:
                closed_trade = self.active_trades[symbol]
                closed_trade['status'] = 'closed'
                closed_trade['close_time'] = datetime.now(DAMASCUS_TZ)
                self.trade_history.append(closed_trade)
                logger.info(f"📝 تم تسجيل إغلاق صفقة: {symbol}")
    
    def get_active_trades_count(self):
        """الحصول على عدد الصفقات النشطة بدقة"""
        return len(self.active_trades)
    
    def is_symbol_trading(self, symbol):
        """التحقق مما إذا كان الرمز يتداول حالياً"""
        return symbol in self.active_trades
    
    def add_trade(self, symbol, trade_data):
        """إضافة صفقة جديدة"""
        self.active_trades[symbol] = trade_data
    
    def remove_trade(self, symbol):
        """إزالة صفقة"""
        if symbol in self.active_trades:
            del self.active_trades[symbol]
    
    def get_trade(self, symbol):
        """الحصول على بيانات صفقة"""
        return self.active_trades.get(symbol)
    
    def get_all_trades(self):
        """الحصول على جميع الصفقات النشطة"""
        return self.active_trades.copy()
