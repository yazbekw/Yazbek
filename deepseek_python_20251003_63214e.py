import os
import pytz
from dotenv import load_dotenv

# تحميل متغيرات البيئة
load_dotenv()

# الإعدادات الزمنية
DAMASCUS_TZ = pytz.timezone('Asia/Damascus')

# إعدادات Binance
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
BINANCE_API_SECRET = os.environ.get('BINANCE_API_SECRET')

# إعدادات Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# إعدادات التداول
TRADING_SETTINGS = {
    'symbols': ["LINKUSDT", "SOLUSDT", "ETHUSDT", "BNBUSDT"],
    'weights': {'LINKUSDT': 1.4, 'SOLUSDT': 1.2, 'ETHUSDT': 1.0, 'BNBUSDT': 0.7},
    'total_capital': 50,
    'base_trade_size': 10,
    'max_leverage': 5,
    'margin_type': 'ISOLATED',
    'max_active_trades': 3,
    'data_interval': '30m',
    'rescan_interval_minutes': 10,
    'price_update_interval': 3,
    'trade_timeout_hours': 8.0,
    'min_signal_score': 4.5,
    'atr_stop_loss_multiplier': 1.5,
    'atr_take_profit_multiplier': 3.0,
    'min_trade_duration_minutes': 45,
    'min_notional_value': 10.0,
    'min_trend_strength': 0.5,
    'max_price_deviation': 8.0,
    'max_volatility': 5.0,
    'min_momentum_strength': 0.001,
    'min_volume_ratio': 0.9,
    'max_contradiction_score': 1,
    'continuous_monitor_interval': 10,
    'min_trade_age_for_monitor': 30,
    'exit_signal_threshold': 3.0,
}

# إعدادات Flask
FLASK_PORT = int(os.environ.get('PORT', 10000))
FLASK_HOST = '0.0.0.0'