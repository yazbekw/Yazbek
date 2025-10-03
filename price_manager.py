import time
from utils import setup_logging

logger = setup_logging()

class PriceManager:
    """مدير محسن للأسعار"""
    
    def __init__(self, symbols, client):
        self.symbols = symbols
        self.client = client
        self.prices = {}
        self.last_update = {}
        self.update_attempts = {}
        
    def update_prices(self):
        """تحديث الأسعار لجميع الرموز"""
        try:
            success_count = 0
            for symbol in self.symbols:
                try:
                    ticker = self.client.futures_symbol_ticker(symbol=symbol)
                    price = float(ticker.get('price', 0))
                    if price > 0:
                        self.prices[symbol] = price
                        self.last_update[symbol] = time.time()
                        self.update_attempts[symbol] = 0
                        success_count += 1
                    else:
                        self._handle_price_error(symbol, "سعر غير صالح")
                except Exception as e:
                    self._handle_price_error(symbol, str(e))
            
            logger.info(f"✅ تم تحديث أسعار {success_count}/{len(self.symbols)} رمز")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"❌ خطأ عام في تحديث الأسعار: {str(e)}")
            return False

    def _handle_price_error(self, symbol, error_msg):
        """معالجة أخطاء تحديث الأسعار"""
        if symbol not in self.update_attempts:
            self.update_attempts[symbol] = 0
        
        self.update_attempts[symbol] += 1
        logger.warning(f"⚠️ فشل تحديث سعر {symbol} (المحاولة {self.update_attempts[symbol]}): {error_msg}")

    def get_price(self, symbol):
        """الحصول على سعر رمز"""
        price = self.prices.get(symbol)
        if price is None:
            logger.warning(f"⚠️ سعر {symbol} غير متوفر")
        return price

    def get_all_prices(self):
        """الحصول على جميع الأسعار"""
        return self.prices.copy()

    def get_price_with_age(self, symbol):
        """الحصول على السعر وعمر التحديث"""
        price = self.prices.get(symbol)
        last_update = self.last_update.get(symbol)
        
        if price is None or last_update is None:
            return None, None
        
        age = time.time() - last_update
        return price, age

    def is_price_fresh(self, symbol, max_age_seconds=300):
        """التحقق من حداثة السعر"""
        price, age = self.get_price_with_age(symbol)
        if price is None or age is None:
            return False
        return age <= max_age_seconds

    def get_symbols_with_fresh_prices(self, max_age_seconds=300):
        """الحصول على الرموز ذات الأسعار الحديثة"""
        fresh_symbols = []
        for symbol in self.symbols:
            if self.is_price_fresh(symbol, max_age_seconds):
                fresh_symbols.append(symbol)
        return fresh_symbols

    def get_price_change(self, symbol, previous_price):
        """حساب التغير في السعر"""
        current_price = self.get_price(symbol)
        if current_price is None or previous_price is None:
            return None
        
        change = current_price - previous_price
        change_percent = (change / previous_price) * 100
        return {
            'absolute': change,
            'percent': change_percent,
            'current': current_price,
            'previous': previous_price
        }
