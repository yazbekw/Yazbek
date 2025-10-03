from flask import Flask, jsonify, request
from datetime import datetime
from config import DAMASCUS_TZ, FLASK_HOST, FLASK_PORT
from utils import setup_logging

logger = setup_logging()

# إنشاء تطبيق Flask
app = Flask(__name__)

@app.route('/')
def health_check():
    """فحص صحة الخدمة"""
    return {
        'status': 'healthy', 
        'service': 'futures-trading-bot', 
        'timestamp': datetime.now(DAMASCUS_TZ).isoformat(),
        'version': '2.0.0'
    }

@app.route('/active_trades')
def active_trades():
    """الحصول على الصفقات النشطة"""
    try:
        from main import FuturesTradingBot
        bot = FuturesTradingBot.get_instance()
        if bot:
            trades = bot.get_active_trades_details()
            return jsonify({
                'success': True,
                'data': trades,
                'count': len(trades),
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({'success': False, 'error': 'Bot not initialized', 'data': []})
    except Exception as e:
        logger.error(f"❌ خطأ في /active_trades: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/trade_history')
def trade_history():
    """الحصول على سجل الصفقات"""
    try:
        from main import FuturesTradingBot
        bot = FuturesTradingBot.get_instance()
        if bot:
            limit = request.args.get('limit', 50, type=int)
            history = bot.trade_manager.get_trade_history(limit)
            return jsonify({
                'success': True,
                'data': history,
                'count': len(history),
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({'success': False, 'error': 'Bot not initialized'})
    except Exception as e:
        logger.error(f"❌ خطأ في /trade_history: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/performance')
def performance():
    """الحصول على أداء البوت"""
    try:
        from main import FuturesTradingBot
        bot = FuturesTradingBot.get_instance()
        if bot:
            performance_data = bot.performance_reporter.get_performance_summary()
            return jsonify({
                'success': True,
                'data': performance_data,
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({'success': False, 'error': 'Bot not initialized'})
    except Exception as e:
        logger.error(f"❌ خطأ في /performance: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/symbols')
def symbols():
    """الحصول على الرموز المتابعة"""
    try:
        from main import FuturesTradingBot
        bot = FuturesTradingBot.get_instance()
        if bot:
            prices = bot.price_manager.get_all_prices()
            symbols_data = {}
            for symbol in bot.symbols:
                price = prices.get(symbol)
                symbols_data[symbol] = {
                    'price': price,
                    'price_fresh': bot.price_manager.is_price_fresh(symbol),
                    'is_trading': bot.trade_manager.is_symbol_trading(symbol)
                }
            
            return jsonify({
                'success': True,
                'data': symbols_data,
                'count': len(symbols_data),
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({'success': False, 'error': 'Bot not initialized'})
    except Exception as e:
        logger.error(f"❌ خطأ في /symbols: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/analyze/<symbol>')
def analyze_symbol(symbol):
    """تحليل رمز معين"""
    try:
        from main import FuturesTradingBot
        bot = FuturesTradingBot.get_instance()
        if bot:
            has_signal, analysis, direction = bot.analyze_symbol(symbol)
            market_health = bot.market_analyzer.get_market_health(symbol)
            
            return jsonify({
                'success': True,
                'data': {
                    'symbol': symbol,
                    'has_signal': has_signal,
                    'direction': direction,
                    'analysis': analysis,
                    'market_health': market_health,
                    'can_trade': not bot.trade_manager.is_symbol_trading(symbol)
                },
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({'success': False, 'error': 'Bot not initialized'})
    except Exception as e:
        logger.error(f"❌ خطأ في /analyze/{symbol}: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/monitor/<symbol>')
def monitor_symbol(symbol):
    """مراقبة صفقة معينة"""
    try:
        from main import FuturesTradingBot
        bot = FuturesTradingBot.get_instance()
        if bot:
            should_exit, reason = bot.continuous_monitor.force_monitor_trade(symbol)
            
            return jsonify({
                'success': True,
                'data': {
                    'symbol': symbol,
                    'should_exit': should_exit,
                    'reason': reason,
                    'has_active_trade': bot.trade_manager.is_symbol_trading(symbol)
                },
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({'success': False, 'error': 'Bot not initialized'})
    except Exception as e:
        logger.error(f"❌ خطأ في /monitor/{symbol}: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/scan')
def scan_all():
    """مسح جميع الرموز"""
    try:
        from main import FuturesTradingBot
        bot = FuturesTradingBot.get_instance()
        if bot:
            results = {}
            for symbol in bot.symbols:
                has_signal, analysis, direction = bot.analyze_symbol(symbol)
                results[symbol] = {
                    'has_signal': has_signal,
                    'direction': direction,
                    'signal_strength': analysis.get('signal_strength', 0) if analysis else 0,
                    'can_trade': not bot.trade_manager.is_symbol_trading(symbol)
                }
            
            return jsonify({
                'success': True,
                'data': results,
                'timestamp': datetime.now(DAMASCUS_TZ).isoformat()
            })
        return jsonify({'success': False, 'error': 'Bot not initialized'})
    except Exception as e:
        logger.error(f"❌ خطأ في /scan: {e}")
        return jsonify({'success': False, 'error': str(e)})

def run_flask_app():
    """تشغيل تطبيق Flask"""
    try:
        logger.info(f"🚀 بدء خادم الويب على {FLASK_HOST}:{FLASK_PORT}")
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)
    except Exception as e:
        logger.error(f"❌ فشل تشغيل خادم الويب: {e}")

# معالجات الأخطاء
@app.errorhandler(404)
def not_found(error):
    return jsonify({'success': False, 'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'success': False, 'error': 'Internal server error'}), 500
