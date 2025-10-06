import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TradingStrategy:
    """استراتيجية التداول المستخرجة من الكود الأصلي"""
    
    def __init__(self):
        self.settings = {
            'min_signal_confidence': 0.65,
            'data_interval': '5m',
            'risk_per_trade': 0.20,
            'max_portfolio_risk': 0.50
        }
        
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """حساب RSI"""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        return 100 - (100 / (1 + rs))
    
    def technical_analysis(self, data: pd.DataFrame) -> Dict:
        """التحليل الفني المتقدم"""
        df = data.copy()
        
        # المتوسطات المتحركة
        df['sma10'] = df['close'].rolling(10).mean()
        df['sma20'] = df['close'].rolling(20).mean()
        df['sma50'] = df['close'].rolling(50).mean()
        df['ema12'] = df['close'].ewm(span=12).mean()
        df['ema26'] = df['close'].ewm(span=26).mean()
        
        # RSI
        df['rsi'] = self.calculate_rsi(df['close'], 14)
        
        # MACD
        df['macd'] = df['ema12'] - df['ema26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']
        
        # الزخم
        df['momentum'] = df['close'].pct_change(5)
        
        # الحجم
        df['volume_sma'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # قوة الاتجاه
        df['trend_strength'] = (df['sma10'] - df['sma50']) / df['sma50'] * 100
        
        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(20).mean()
        df['bb_std'] = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (df['bb_std'] * 2)
        df['bb_lower'] = df['bb_middle'] - (df['bb_std'] * 2)
        
        latest = df.iloc[-1]
        
        return {
            'sma10': latest['sma10'],
            'sma20': latest['sma20'], 
            'sma50': latest['sma50'],
            'ema12': latest['ema12'],
            'ema26': latest['ema26'],
            'rsi': latest['rsi'],
            'macd': latest['macd'],
            'macd_signal': latest['macd_signal'],
            'macd_hist': latest['macd_hist'],
            'momentum': latest['momentum'],
            'volume_ratio': latest['volume_ratio'],
            'trend_strength': latest['trend_strength'],
            'price_vs_sma20': (latest['close'] - latest['sma20']) / latest['sma20'] * 100,
            'close': latest['close'],
            'bb_upper': latest['bb_upper'],
            'bb_lower': latest['bb_lower']
        }
    
    def analyze_phase(self, data: pd.DataFrame) -> Dict:
        """تحليل مرحلة السوق"""
        if len(data) < 50:
            return {"phase": "غير محدد", "confidence": 0, "action": "انتظار"}
        
        technical = self.technical_analysis(data)
        
        # شروط التجميع
        accumulation_signs = [
            technical['volume_ratio'] < 1.2,
            technical['rsi'] < 60,
            technical['macd_hist'] > -0.001,
            technical['close'] > technical['bb_lower'],
            technical['close'] > technical['sma20'] * 0.98,
        ]
        
        # شروط الصعود
        markup_signs = [
            technical['close'] > technical['sma20'] > technical['sma50'],
            technical['volume_ratio'] > 1.0,
            technical['rsi'] > 50,
            technical['macd'] > technical['macd_signal'],
            technical['close'] > data['close'].iloc[-10] if len(data) > 10 else True,
        ]
        
        # شروط التوزيع
        distribution_signs = [
            technical['volume_ratio'] > 1.5,
            technical['rsi'] > 70,
            technical['macd_hist'] < 0,
            technical['close'] < technical['bb_upper'],
            technical['close'] < technical['sma20'] * 1.02,
        ]
        
        # شروط الهبوط
        markdown_signs = [
            technical['close'] < technical['sma20'] < technical['sma50'],
            technical['volume_ratio'] > 1.0,
            technical['rsi'] < 40,
            technical['macd'] < technical['macd_signal'],
            technical['close'] < data['close'].iloc[-10] if len(data) > 10 else True,
        ]
        
        scores = {
            "تجميع": sum(accumulation_signs),
            "صعود": sum(markup_signs),
            "توزيع": sum(distribution_signs),
            "هبوط": sum(markdown_signs)
        }
        
        best_phase = max(scores, key=scores.get)
        confidence = scores[best_phase] / 5.0
        
        action = self._get_action(best_phase, confidence)
        
        return {
            "phase": best_phase,
            "confidence": round(confidence, 2),
            "action": action,
            "indicators": {
                "rsi": round(technical['rsi'], 1),
                "volume_ratio": round(technical['volume_ratio'], 2),
                "macd_hist": round(technical['macd_hist'], 4),
                "bb_position": round((technical['close'] - technical['bb_lower']) / (technical['bb_upper'] - technical['bb_lower']), 2),
                "trend": "صاعد" if technical['sma20'] > technical['sma50'] else "هابط"
            }
        }
    
    def _get_action(self, phase: str, confidence: float) -> str:
        """تحديد الإجراء المناسب"""
        actions = {
            "تجميع": "استعداد للشراء - مرحلة تجميع",
            "صعود": "شراء - اتجاه صاعد",
            "توزيع": "بيع - مرحلة توزيع", 
            "هبوط": "بيع - اتجاه هابط"
        }
        
        base_action = actions.get(phase, "انتظار")
        
        if confidence > 0.7:
            if phase == "تجميع":
                return f"🟢 {base_action} قوي"
            elif phase == "صعود":
                return f"🟢 {base_action} قوي"
            elif phase == "توزيع":
                return f"🔴 {base_action} قوي"
            elif phase == "هبوط":
                return f"🔴 {base_action} قوي"
        
        return f"⚪ {base_action}"
    
    def generate_signal(self, symbol: str, data: pd.DataFrame, current_price: float) -> Optional[Dict]:
        """توليد إشارة تداول"""
        try:
            if len(data) < 50:
                return None
            
            # تحليل مرحلة السوق
            phase_analysis = self.analyze_phase(data)
            
            # التحليل الفني
            technical = self.technical_analysis(data)
            
            # تحليل القوة
            strength = self._strength_analysis(data)
            
            # توليد الإشارات بشروط مخصصة
            long_signal = self._strict_long_signal(technical, strength, phase_analysis)
            short_signal = self._strict_short_signal(technical, strength, phase_analysis)
            
            # اختيار أفضل إشارة
            return self._select_signal(symbol, long_signal, short_signal, phase_analysis)
            
        except Exception as e:
            logger.error(f"❌ خطأ في توليد الإشارة لـ {symbol}: {e}")
            return None
    
    def _strict_long_signal(self, technical: Dict, strength: Dict, phase_analysis: Dict) -> Dict:
        """إشارة شراء بشروط مشددة"""
        strict_buy_conditions = [
            technical['sma10'] > technical['sma20'] > technical['sma50'],
            technical['ema12'] > technical['ema26'],
            technical['close'] > technical['sma20'] * 1.01,
            technical['rsi'] > 52 and technical['rsi'] < 68,
            technical['momentum'] > 0.003,
            technical['macd'] > technical['macd_signal'] * 1.02,
            technical['volume_ratio'] > 1.1,
            technical['trend_strength'] > 1.0,
            strength['volume_strength'] > 1.0,
            phase_analysis['phase'] in ['صعود'],
            phase_analysis['confidence'] > 0.7,
            technical['price_vs_sma20'] > 0.5,
            strength['volatility'] < 3.0,
        ]
        
        strict_weights = [3.0, 2.5, 2.0, 2.0, 2.5, 1.8, 1.5, 1.8, 1.2, 1.2, 1.2, 1.5, 1.2]
        
        signal_score = sum(cond * weight for cond, weight in zip(strict_buy_conditions, strict_weights))
        max_score = sum(strict_weights)
        
        return {
            'direction': 'LONG',
            'score': signal_score,
            'confidence': signal_score / max_score,
            'conditions_met': sum(strict_buy_conditions),
            'total_conditions': len(strict_buy_conditions),
            'strict_conditions': True
        }
    
    def _strict_short_signal(self, technical: Dict, strength: Dict, phase_analysis: Dict) -> Dict:
        """إشارة بيع بشروط مشددة"""
        strict_sell_conditions = [
            technical['sma10'] < technical['sma20'] < technical['sma50'],
            technical['ema12'] < technical['ema26'],
            technical['close'] < technical['sma20'] * 0.99,
            technical['rsi'] < 48 and technical['rsi'] > 25,
            technical['momentum'] < -0.003,
            technical['macd'] < technical['macd_signal'] * 0.98,
            technical['volume_ratio'] > 1.1,
            technical['trend_strength'] < -1.0,
            strength['volume_strength'] > 1.0,
            phase_analysis['phase'] in ['هبوط'],
            phase_analysis['confidence'] > 0.7,
            technical['price_vs_sma20'] < -0.5,
            strength['volatility'] < 3.0,
        ]
        
        strict_weights = [3.0, 2.0, 2.0, 2.0, 2.5, 1.8, 1.5, 1.8, 1.2, 1.2, 1.3, 1.5, 1.2]
        
        signal_score = sum(cond * weight for cond, weight in zip(strict_sell_conditions, strict_weights))
        max_score = sum(strict_weights)
        
        return {
            'direction': 'SHORT',
            'score': signal_score,
            'confidence': signal_score / max_score,
            'conditions_met': sum(strict_sell_conditions),
            'total_conditions': len(strict_sell_conditions),
            'strict_conditions': True
        }
    
    def _strength_analysis(self, data: pd.DataFrame) -> Dict:
        """تحليل قوة السوق"""
        volatility = data['close'].pct_change().std() * 100
        volume_strength = data['volume'].iloc[-1] / data['volume'].rolling(20).mean().iloc[-1]
        
        return {
            'volatility': volatility,
            'volume_strength': volume_strength
        }
    
    def _select_signal(self, symbol: str, long_signal: Dict, short_signal: Dict, phase_analysis: Dict) -> Optional[Dict]:
        """اختيار أفضل إشارة"""
        min_confidence = 0.72
        min_conditions = 9
        
        valid_signals = []
        
        if (long_signal['confidence'] >= min_confidence and 
            long_signal['conditions_met'] >= min_conditions):
            valid_signals.append(long_signal)
            
        if (short_signal['confidence'] >= min_confidence and 
            short_signal['conditions_met'] >= min_conditions):
            valid_signals.append(short_signal)
        
        if not valid_signals:
            return None
        
        best_signal = max(valid_signals, key=lambda x: x['confidence'])
        
        return {
            'symbol': symbol,
            'direction': best_signal['direction'],
            'confidence': best_signal['confidence'],
            'score': best_signal['score'],
            'phase_analysis': phase_analysis,
            'timestamp': datetime.now(),
            'conditions_met': best_signal['conditions_met'],
            'total_conditions': best_signal['total_conditions'],
            'strict_conditions': best_signal.get('strict_conditions', False)
        }

class BacktestEngine:
    """محرك Backtesting مع تتبع الصفقات"""
    
    def __init__(self, strategy: TradingStrategy, initial_balance: float = 1000.0):
        self.strategy = strategy
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.positions = {}
        self.trade_history = []
        self.performance_stats = {}
        
    def run_backtest(self, data: Dict[str, pd.DataFrame]) -> Dict:
        """تشغيل backtest على بيانات متعددة الرموز"""
        logger.info("🚀 بدء تشغيل Backtesting...")
        
        for symbol, symbol_data in data.items():
            self._backtest_symbol(symbol, symbol_data)
        
        self._calculate_performance()
        return self._generate_report()
    
    def _backtest_symbol(self, symbol: str, data: pd.DataFrame):
        """تشغيل backtest على رمز واحد"""
        logger.info(f"🔍 تحليل {symbol}...")
        
        for i in range(50, len(data)):
            current_data = data.iloc[:i]
            current_price = data['close'].iloc[i]
            current_time = data.index[i] if hasattr(data.index, 'iloc') else i
            
            # توليد الإشارة
            signal = self.strategy.generate_signal(symbol, current_data, current_price)
            
            if signal:
                self._execute_trade(symbol, signal, current_price, current_time)
            
            # إدارة الصفقات النشطة
            self._manage_active_trades(symbol, current_price, current_time)
    
    def _execute_trade(self, symbol: str, signal: Dict, price: float, timestamp):
        """تنفيذ صفقة في backtest"""
        if symbol in self.positions:
            return  # تخطي إذا كانت هناك صفقة نشطة
        
        # حساب حجم المركز
        position_size = self._calculate_position_size(price)
        
        if position_size <= 0:
            return
        
        # فتح الصفقة
        self.positions[symbol] = {
            'symbol': symbol,
            'direction': signal['direction'],
            'entry_price': price,
            'quantity': position_size / price,
            'entry_time': timestamp,
            'stop_loss': self._calculate_stop_loss(signal['direction'], price),
            'take_profit': self._calculate_take_profit(signal['direction'], price),
            'highest_price': price if signal['direction'] == 'LONG' else price,
            'lowest_price': price if signal['direction'] == 'SHORT' else price,
            'max_profit_pct': 0,
            'max_loss_pct': 0,
            'winning_duration': 0,
            'total_duration': 0
        }
        
        self.current_balance -= position_size
        
        logger.info(f"📈 فتح {signal['direction']} على {symbol} بسعر ${price:.4f}")
    
    def _manage_active_trades(self, symbol: str, current_price: float, timestamp):
        """إدارة الصفقات النشطة"""
        if symbol not in self.positions:
            return
        
        trade = self.positions[symbol]
        
        # تحديث أعلى/أقل سعر
        if trade['direction'] == 'LONG':
            trade['highest_price'] = max(trade['highest_price'], current_price)
            trade['lowest_price'] = min(trade['lowest_price'], current_price)
        else:
            trade['highest_price'] = min(trade['highest_price'], current_price)
            trade['lowest_price'] = max(trade['lowest_price'], current_price)
        
        # حساب الربح/الخسارة الحالية
        if trade['direction'] == 'LONG':
            current_pnl_pct = (current_price - trade['entry_price']) / trade['entry_price'] * 100
        else:
            current_pnl_pct = (trade['entry_price'] - current_price) / trade['entry_price'] * 100
        
        # تحديث أقصى ربح وخسارة
        trade['max_profit_pct'] = max(trade['max_profit_pct'], current_pnl_pct)
        trade['max_loss_pct'] = min(trade['max_loss_pct'], current_pnl_pct)
        
        # تحديث مدة الربح
        if current_pnl_pct > 0:
            trade['winning_duration'] += 1
        
        trade['total_duration'] += 1
        
        # التحقق من شروط الخروج
        if self._should_exit_trade(trade, current_price):
            self._close_trade(symbol, current_price, timestamp, "شرط خروج")
    
    def _should_exit_trade(self, trade: Dict, current_price: float) -> bool:
        """تحديد ما إذا كان يجب إغلاق الصفقة"""
        if trade['direction'] == 'LONG':
            if current_price <= trade['stop_loss']:
                return True
            if current_price >= trade['take_profit']:
                return True
        else:
            if current_price >= trade['stop_loss']:
                return True
            if current_price <= trade['take_profit']:
                return True
        
        return False
    
    def _close_trade(self, symbol: str, exit_price: float, timestamp, reason: str):
        """إغلاق الصفقة"""
        trade = self.positions[symbol]
        
        # حساب الربح/الخسارة النهائية
        if trade['direction'] == 'LONG':
            pnl_pct = (exit_price - trade['entry_price']) / trade['entry_price'] * 100
            pnl_amount = (exit_price - trade['entry_price']) * trade['quantity']
        else:
            pnl_pct = (trade['entry_price'] - exit_price) / trade['entry_price'] * 100
            pnl_amount = (trade['entry_price'] - exit_price) * trade['quantity']
        
        # تحديث الرصيد
        self.current_balance += (trade['quantity'] * trade['entry_price']) + pnl_amount
        
        # حفظ بيانات الصفقة
        trade_info = {
            **trade,
            'exit_price': exit_price,
            'exit_time': timestamp,
            'pnl_pct': pnl_pct,
            'pnl_amount': pnl_amount,
            'exit_reason': reason,
            'winning_ratio': trade['winning_duration'] / trade['total_duration'] if trade['total_duration'] > 0 else 0
        }
        
        self.trade_history.append(trade_info)
        del self.positions[symbol]
        
        logger.info(f"📉 إغلاق {trade['direction']} على {symbol}: {pnl_pct:+.2f}%")
    
    def _calculate_position_size(self, price: float) -> float:
        """حساب حجم المركز"""
        risk_amount = self.current_balance * self.strategy.settings['risk_per_trade']
        return min(risk_amount, self.current_balance * 0.1)  # 10% كحد أقصى
    
    def _calculate_stop_loss(self, direction: str, entry_price: float) -> float:
        """حساب وقف الخسارة"""
        if direction == 'LONG':
            return entry_price * 0.99  # وقف 1%
        else:
            return entry_price * 1.01  # وقف 1%
    
    def _calculate_take_profit(self, direction: str, entry_price: float) -> float:
        """حساب جني الأرباح"""
        if direction == 'LONG':
            return entry_price * 1.015  # ربح 1.5%
        else:
            return entry_price * 0.985  # ربح 1.5%
    
    def _calculate_performance(self):
        """حساب أداء التداول"""
        if not self.trade_history:
            self.performance_stats = {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_trade_duration': 0,
                'max_drawdown': 0
            }
            return
        
        winning_trades = [t for t in self.trade_history if t['pnl_pct'] > 0]
        losing_trades = [t for t in self.trade_history if t['pnl_pct'] <= 0]
        
        total_pnl = sum(t['pnl_amount'] for t in self.trade_history)
        avg_duration = np.mean([t['total_duration'] for t in self.trade_history])
        
        # حساب أقصى خسارة
        cumulative_pnl = 0
        max_drawdown = 0
        peak = self.initial_balance
        
        for trade in self.trade_history:
            cumulative_pnl += trade['pnl_amount']
            current_balance = self.initial_balance + cumulative_pnl
            if current_balance > peak:
                peak = current_balance
            drawdown = (peak - current_balance) / peak * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        self.performance_stats = {
            'total_trades': len(self.trade_history),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / len(self.trade_history),
            'total_pnl': total_pnl,
            'total_return_pct': (total_pnl / self.initial_balance) * 100,
            'avg_trade_duration': avg_duration,
            'max_drawdown': max_drawdown,
            'final_balance': self.current_balance,
            'profit_factor': abs(sum(t['pnl_amount'] for t in winning_trades)) / 
                            abs(sum(t['pnl_amount'] for t in losing_trades)) if losing_trades else float('inf')
        }
    
    def _generate_report(self) -> Dict:
        """إنشاء تقرير الأداء"""
        report = {
            'performance': self.performance_stats,
            'trade_history': self.trade_history,
            'detailed_trades': self._get_detailed_trades()
        }
        
        # طباعة التقرير
        print("\n" + "="*50)
        print("📊 تقرير أداء Backtesting")
        print("="*50)
        print(f"إجمالي الصفقات: {self.performance_stats['total_trades']}")
        print(f"الصفقات الرابحة: {self.performance_stats['winning_trades']}")
        print(f"الصفقات الخاسرة: {self.performance_stats['losing_trades']}")
        print(f"معدل الربح: {self.performance_stats['win_rate']:.2%}")
        print(f"إجمالي الربح: ${self.performance_stats['total_pnl']:.2f}")
        print(f"العائد الإجمالي: {self.performance_stats['total_return_pct']:.2f}%")
        print(f"أقصى خسارة: {self.performance_stats['max_drawdown']:.2f}%")
        print(f"عامل الربح: {self.performance_stats['profit_factor']:.2f}")
        print(f"متوسط مدة الصفقة: {self.performance_stats['avg_trade_duration']:.1f} فترة")
        print(f"الرصيد النهائي: ${self.performance_stats['final_balance']:.2f}")
        
        return report
    
    def _get_detailed_trades(self) -> List[Dict]:
        """الحصول على تفاصيل الصفقات المطلوبة"""
        detailed_trades = []
        
        for trade in self.trade_history:
            # حساب معلومات إضافية عن الصفقة
            trade_duration = trade['total_duration']
            winning_ratio = trade['winning_ratio']
            
            # أعلى سعر وصلته الصفقة أثناء الربح
            if trade['direction'] == 'LONG':
                highest_winning_price = trade['highest_price']
                price_at_max_profit = trade['entry_price'] * (1 + trade['max_profit_pct'] / 100)
            else:
                highest_winning_price = trade['lowest_price']
                price_at_max_profit = trade['entry_price'] * (1 - trade['max_profit_pct'] / 100)
            
            detailed_trade = {
                'symbol': trade['symbol'],
                'direction': trade['direction'],
                'entry_price': trade['entry_price'],
                'exit_price': trade['exit_price'],
                'entry_time': trade['entry_time'],
                'exit_time': trade['exit_time'],
                'pnl_percentage': trade['pnl_pct'],
                'pnl_amount': trade['pnl_amount'],
                'trade_duration': trade_duration,
                'winning_duration': trade['winning_duration'],
                'winning_ratio': winning_ratio,
                'highest_price_reached': highest_winning_price,
                'price_at_max_profit': price_at_max_profit,
                'max_profit_percentage': trade['max_profit_pct'],
                'max_loss_percentage': trade['max_loss_pct'],
                'stop_loss_price': trade['stop_loss'],
                'take_profit_price': trade['take_profit'],
                'exit_reason': trade['exit_reason']
            }
            
            detailed_trades.append(detailed_trade)
        
        return detailed_trades

# مثال على استخدام الكود
def generate_sample_data(symbols: List[str], periods: int = 1000) -> Dict[str, pd.DataFrame]:
    """توليد بيانات نموذجية للاختبار"""
    data = {}
    
    for symbol in symbols:
        # إنشاء بيانات سعر عشوائية مع اتجاهات
        np.random.seed(42)  # للتكرار
        prices = [100.0]
        
        for i in range(periods):
            # تقلب عشوائي مع بعض الاتجاهات
            change = np.random.normal(0.001, 0.02)
            if i > 200 and i < 400:
                change += 0.005  # اتجاه صاعد
            elif i > 600 and i < 800:
                change -= 0.005  # اتجاه هابط
            
            new_price = prices[-1] * (1 + change)
            prices.append(new_price)
        
        dates = pd.date_range(start='2024-01-01', periods=periods, freq='5T')
        
        df = pd.DataFrame({
            'open': prices[:-1],
            'high': [p * (1 + abs(np.random.normal(0, 0.01))) for p in prices[:-1]],
            'low': [p * (1 - abs(np.random.normal(0, 0.01))) for p in prices[:-1]],
            'close': prices[:-1],
            'volume': np.random.uniform(1000, 10000, periods)
        }, index=dates)
        
        data[symbol] = df
    
    return data

if __name__ == "__main__":
    # اختبار الاستراتيجية مع backtesting
    symbols = ["ETHUSDT", "BTCUSDT", "ADAUSDT"]
    
    # توليد بيانات نموذجية
    sample_data = generate_sample_data(symbols)
    
    # إنشاء واستراتيجية ومحرك backtesting
    strategy = TradingStrategy()
    backtester = BacktestEngine(strategy, initial_balance=1000.0)
    
    # تشغيل backtest
    report = backtester.run_backtest(sample_data)
    
    # عرض تفاصيل الصفقات
    print("\n" + "="*50)
    print("📋 تفاصيل الصفقات")
    print("="*50)
    
    for i, trade in enumerate(report['detailed_trades'][:5]):  # عرض أول 5 صفقات
        print(f"\nالصفقة #{i+1}:")
        print(f"  الرمز: {trade['symbol']}")
        print(f"  الاتجاه: {trade['direction']}")
        print(f"  سعر الدخول: ${trade['entry_price']:.4f}")
        print(f"  سعر الخروج: ${trade['exit_price']:.4f}")
        print(f"  الربح/الخسارة: {trade['pnl_percentage']:+.2f}%")
        print(f"  مدة الصفقة: {trade['trade_duration']} فترة")
        print(f"  مدة الربح: {trade['winning_duration']} فترة ({trade['winning_ratio']:.1%})")
        print(f"  أعلى سعر: ${trade['highest_price_reached']:.4f}")
        print(f"  السعر عند أقصى ربح: ${trade['price_at_max_profit']:.4f}")
        print(f"  أقصى ربح: {trade['max_profit_percentage']:.2f}%")
        print(f"  سبب الخروج: {trade['exit_reason']}")
