from flask import Flask, jsonify, request
from datetime import datetime
from config import DAMASCUS_TZ, FLASK_HOST, FLASK_PORT
from utils import setup_logging

logger = setup_logging()

# إنشاء تطبيق Flask
app = Flask(__name__)

# متغير عالمي لتتبع حالة البوت
bot_instance = None

def set_bot_instance(bot):
    """تعيين نسخة البوت للاستخدام في API"""
    global bot_instance
    bot_instance = bot

@app.route('/')
def health_check():
    """فحص صحة الخدمة"""
    bot_status = "initialized" if bot_instance else "not_initialized"
    return {
        'status': 'healthy', 
        'service': 'futures-trading-bot', 
        'timestamp': datetime.now(DAMASCUS_TZ).isoformat(),
        'version': '2.0.0',
        'bot_status': bot_status
    }

@app.route('/active_trades')
def active_trades():
    """الحصول على الصفقات النشطة"""
    try:
        if bot_instance:
            trades = bot_instance.get_active_trades_details()
            return jsonify({
                'success': True,
                'data': trades,
                'count': len(trades),
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({
            'success': False, 
            'error': 'Bot not initialized yet',
            'status': 'initializing'
        })
    except Exception as e:
        logger.error(f"❌ خطأ في /active_trades: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/performance')
def performance():
    """الحصول على أداء البوت"""
    try:
        if bot_instance:
            performance_data = bot_instance.performance_reporter.get_performance_summary()
            return jsonify({
                'success': True,
                'data': performance_data,
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({
            'success': False, 
            'error': 'Bot not initialized yet',
            'status': 'initializing'
        })
    except Exception as e:
        logger.error(f"❌ خطأ في /performance: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/symbols')
def symbols():
    """الحصول على الرموز المتابعة"""
    try:
        if bot_instance:
            prices = bot_instance.price_manager.get_all_prices()
            symbols_data = {}
            for symbol in bot_instance.symbols:
                price = prices.get(symbol)
                symbols_data[symbol] = {
                    'price': price,
                    'price_fresh': bot_instance.price_manager.is_price_fresh(symbol),
                    'is_trading': bot_instance.trade_manager.is_symbol_trading(symbol)
                }
            
            return jsonify({
                'success': True,
                'data': symbols_data,
                'count': len(symbols_data),
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({
            'success': False, 
            'error': 'Bot not initialized yet',
            'status': 'initializing'
        })
    except Exception as e:
        logger.error(f"❌ خطأ في /symbols: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/status')
def bot_status():
    """الحصول على حالة البوت التفصيلية"""
    status_info = {
        'success': True,
        'bot_initialized': bool(bot_instance),
        'timestamp': datetime.now(DAMASCUS_TZ).isoformat(),
        'services': {
            'web_server': 'running',
            'price_updater': 'running' if bot_instance else 'waiting',
            'trade_sync': 'running' if bot_instance else 'waiting',
            'continuous_monitor': 'running' if bot_instance else 'waiting'
        }
    }
    
    if bot_instance:
        status_info.update({
            'active_trades': bot_instance.trade_manager.get_active_trades_count(),
            'symbols_tracking': len(bot_instance.symbols),
            'last_scan': 'active'  # يمكن إضافة وقت المسح الأخير
        })
    
    return jsonify(status_info)

def run_flask_app():
    """تشغيل تطبيق Flask"""
    try:
        logger.info(f"🚀 بدء خادم الويب على {FLASK_HOST}:{FLASK_PORT}")
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"❌ فشل تشغيل خادم الويب: {e}")

# معالجات الأخطاء
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500
