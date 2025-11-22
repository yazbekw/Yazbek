import pandas as pd
import numpy as np
import asyncio
import aiohttp
import hmac
import hashlib
import time
from datetime import datetime, timedelta
import json
import os
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import io
import base64
from typing import Dict, List, Tuple, Optional, Any
import urllib.parse

# تحميل المتغيرات البيئية
load_dotenv()

class BinanceFuturesAnalyzer:
    def __init__(self):
        self.api_key = os.getenv('BINANCE_FUTURES_API_KEY')
        self.api_secret = os.getenv('BINANCE_FUTURES_API_SECRET')
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.base_url = 'https://fapi.binance.com'
        
        # التحقق من وجود API keys
        if not self.api_key or not self.api_secret:
            raise ValueError("❌ مفاتيح API غير موجودة. تأكد من ملف .env")

    def generate_signature(self, params: Dict) -> str:
        """توليد توقيع HMAC SHA256"""
        query_string = urllib.parse.urlencode(params)
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def make_signed_request(self, endpoint: str, params: Dict = None) -> Any:
        """تنفيذ طلب موقّع للـ Futures API"""
        if params is None:
            params = {}
        
        params['timestamp'] = int(time.time() * 1000)
        params['recvWindow'] = 60000
        
        signature = self.generate_signature(params)
        params['signature'] = signature
        
        url = f"{self.base_url}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers) as response:
                    data = await response.json()
                    
                    # التحقق من وجود أخطاء في API
                    if isinstance(data, dict) and 'code' in data and data['code'] != 200:
                        error_msg = f"API Error {data['code']}: {data.get('msg', 'Unknown error')}"
                        print(f"❌ {error_msg}")
                        return None
                    
                    return data
                    
        except Exception as e:
            print(f"❌ Error in API request to {endpoint}: {e}")
            return None

    async def test_api_connection(self) -> bool:
        """اختبار اتصال API"""
        print("🔍 اختبار اتصال API...")
        
        # اختبار بسيط لجلب معلومات الحساب
        endpoint = '/fapi/v2/account'
        data = await self.make_signed_request(endpoint)
        
        if data is None:
            print("❌ فشل اختبار الاتصال")
            return False
        
        if isinstance(data, dict) and 'assets' in data:
            print("✅ اتصال API ناجح")
            return True
        else:
            print("❌ استجابة API غير متوقعة")
            return False

    async def get_account_balance(self) -> List[Dict]:
        """جلب أرصدة حساب العقود الآجلة"""
        endpoint = '/fapi/v2/balance'
        data = await self.make_signed_request(endpoint)
        
        if data is None or not isinstance(data, list):
            print("❌ لا يمكن جلب الأرصدة")
            return []
        
        return [asset for asset in data if float(asset.get('balance', 0)) != 0]

    async def get_positions(self) -> List[Dict]:
        """جلب المراكز المفتوحة"""
        endpoint = '/fapi/v2/positionRisk'
        data = await self.make_signed_request(endpoint)
        
        if data is None or not isinstance(data, list):
            print("❌ لا يمكن جلب المراكز")
            return []
        
        return data

    async def get_income_history(self, symbol: str = None, limit: int = 100) -> List[Dict]:
        """جلب سجل الدخل"""
        endpoint = '/fapi/v1/income'
        params = {'limit': limit}
        if symbol:
            params['symbol'] = symbol
            
        data = await self.make_signed_request(endpoint, params)
        
        if data is None or not isinstance(data, list):
            return []
        
        return data

    async def get_user_trades(self, symbol: str, limit: int = 500) -> List[Dict]:
        """جلب سجل الصفقات لرمز محدد"""
        endpoint = '/fapi/v1/userTrades'
        params = {
            'symbol': symbol,
            'limit': limit
        }
        
        data = await self.make_signed_request(endpoint, params)
        
        if data is None or not isinstance(data, list):
            return []
        
        return data

    async def get_all_symbols(self) -> List[str]:
        """جلب جميع الرموز المتاحة"""
        endpoint = '/fapi/v1/exchangeInfo'
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}{endpoint}") as response:
                    data = await response.json()
                    if 'symbols' in data:
                        return [symbol['symbol'] for symbol in data['symbols']]
                    return []
        except Exception as e:
            print(f"❌ Error getting symbols: {e}")
            return []

    async def simulate_futures_trades(self) -> pd.DataFrame:
        """محاكاة بيانات الصفقات للعقود الآجلة (للتجربة)"""
        print("🔧 استخدام بيانات محاكاة للعقود الآجلة...")
        
        symbols = ['BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'DOTUSDT', 'BNBUSDT', 'XRPUSDT', 'SOLUSDT']
        trades = []
        
        for symbol in symbols:
            # إنشاء بيانات محاكاة واقعية للعقود الآجلة
            for i in range(np.random.randint(5, 15)):
                is_buyer = np.random.choice([True, False])
                side = 'BUY' if is_buyer else 'SELL'
                position_side = np.random.choice(['LONG', 'SHORT', 'BOTH'])
                
                price = np.random.uniform(10, 50000)
                qty = np.random.uniform(0.1, 5)
                commission = price * qty * 0.0004  # عمولة العقود الآجلة
                realized_pnl = np.random.uniform(-200, 300)
                
                trade = {
                    'symbol': symbol,
                    'id': i + 1,
                    'orderId': np.random.randint(100000, 999999),
                    'price': price,
                    'qty': qty,
                    'quoteQty': price * qty,
                    'commission': commission,
                    'commissionAsset': 'USDT',
                    'time': int((datetime.now() - timedelta(days=np.random.randint(1, 30))).timestamp() * 1000),
                    'isBuyer': is_buyer,
                    'isMaker': np.random.choice([True, False]),
                    'side': side,
                    'positionSide': position_side,
                    'realizedPnl': realized_pnl
                }
                trades.append(trade)
        
        return pd.DataFrame(trades)

    async def get_real_trades_data(self) -> pd.DataFrame:
        """جلب بيانات الصفقات الحقيقية من API"""
        print("🔄 جاري جمع بيانات الصفقات الحقيقية...")
        
        all_trades = []
        
        # جلب الرموز النشطة من المراكز أولاً
        positions = await self.get_positions()
        active_symbols = []
        
        for pos in positions:
            if isinstance(pos, dict) and float(pos.get('positionAmt', 0)) != 0:
                active_symbols.append(pos.get('symbol'))
        
        # إضافة رموز شائعة
        common_symbols = ['BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'BNBUSDT', 'XRPUSDT']
        target_symbols = list(set(active_symbols + common_symbols))
        
        for symbol in target_symbols[:10]:  # تحديد للكفاءة
            try:
                print(f"📊 جاري جمع صفقات {symbol}...")
                trades = await self.get_user_trades(symbol, limit=100)
                
                if trades:
                    for trade in trades:
                        if isinstance(trade, dict):
                            trade['symbol'] = symbol
                            all_trades.append(trade)
                    
                    await asyncio.sleep(0.2)  # تجنب rate limit
                    
            except Exception as e:
                print(f"❌ خطأ في جلب صفقات {symbol}: {e}")
                continue
        
        return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    def analyze_futures_trades(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """تحليل صفقات العقود الآجلة"""
        if trades_df.empty:
            return pd.DataFrame()
        
        try:
            # تحويل البيانات
            trades_df['time'] = pd.to_datetime(trades_df['time'], unit='ms')
            trades_df['price'] = pd.to_numeric(trades_df['price'], errors='coerce')
            trades_df['qty'] = pd.to_numeric(trades_df['qty'], errors='coerce')
            trades_df['quoteQty'] = pd.to_numeric(trades_df['quoteQty'], errors='coerce')
            trades_df['commission'] = pd.to_numeric(trades_df['commission'], errors='coerce')
            trades_df['realizedPnl'] = pd.to_numeric(trades_df['realizedPnl'], errors='coerce')
            
            # تنظيف البيانات
            trades_df = trades_df.dropna()
            
            return trades_df
            
        except Exception as e:
            print(f"❌ خطأ في تحليل الصفقات: {e}")
            return pd.DataFrame()

    def calculate_futures_pnl(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """حساب الربح والخسارة للعقود الآجلة"""
        if trades_df.empty:
            return pd.DataFrame()
        
        try:
            symbol_groups = trades_df.groupby('symbol')
            results = []
            
            for symbol, group in symbol_groups:
                # إجمالي الربح المحقق
                total_realized_pnl = group['realizedPnl'].sum()
                
                # العمولات
                total_commission = group['commission'].sum()
                
                # حجم التداول
                total_volume = group['quoteQty'].sum()
                
                # إحصاءات الصفقات
                total_trades = len(group)
                winning_trades = len(group[group['realizedPnl'] > 0])
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                
                # صافي الربح بعد العمولات
                net_pnl = total_realized_pnl - total_commission
                
                # تحليل اتجاه الصفقات
                long_trades = len(group[group['positionSide'] == 'LONG'])
                short_trades = len(group[group['positionSide'] == 'SHORT'])
                both_trades = len(group[group['positionSide'] == 'BOTH'])
                
                results.append({
                    'symbol': symbol,
                    'total_volume': total_volume,
                    'total_trades': total_trades,
                    'winning_trades': winning_trades,
                    'win_rate': win_rate,
                    'total_realized_pnl': total_realized_pnl,
                    'total_commission': total_commission,
                    'net_pnl': net_pnl,
                    'pnl_percentage': (net_pnl / total_volume * 100) if total_volume > 0 else 0,
                    'status': 'ربح' if net_pnl > 0 else 'خسارة',
                    'avg_trade_size': total_volume / total_trades if total_trades > 0 else 0,
                    'long_trades': long_trades,
                    'short_trades': short_trades,
                    'both_trades': both_trades
                })
            
            return pd.DataFrame(results)
            
        except Exception as e:
            print(f"❌ خطأ في حساب PnL: {e}")
            return pd.DataFrame()

    async def get_current_positions(self) -> pd.DataFrame:
        """جلب المراكز الحالية"""
        positions = await self.get_positions()
        if not positions:
            return pd.DataFrame()
        
        current_positions = []
        for pos in positions:
            if isinstance(pos, dict) and float(pos.get('positionAmt', 0)) != 0:
                current_positions.append({
                    'symbol': pos.get('symbol', 'Unknown'),
                    'position_amt': float(pos.get('positionAmt', 0)),
                    'entry_price': float(pos.get('entryPrice', 0)),
                    'unrealized_pnl': float(pos.get('unRealizedProfit', 0)),
                    'leverage': int(pos.get('leverage', 1)),
                    'side': 'LONG' if float(pos.get('positionAmt', 0)) > 0 else 'SHORT',
                    'liquidation_price': float(pos.get('liquidationPrice', 0))
                })
        
        return pd.DataFrame(current_positions)

    def create_futures_summary_plot(self, pnl_df: pd.DataFrame, positions_df: pd.DataFrame) -> str:
        """إنشاء رسم بياني للعقود الآجلة"""
        try:
            if pnl_df.empty and positions_df.empty:
                return None
            
            plt.style.use('default')
            plt.figure(figsize=(15, 10))
            
            if not pnl_df.empty:
                # الرسم البياني للربح/الخسارة
                plt.subplot(2, 2, 1)
                colors = ['#2ecc71' if x > 0 else '#e74c3c' for x in pnl_df['net_pnl']]
                bars = plt.bar(pnl_df['symbol'], pnl_df['net_pnl'], color=colors, alpha=0.8)
                plt.title('صافي الربح/الخسارة ($)', fontsize=12, fontweight='bold')
                plt.xticks(rotation=45)
                
                # إضافة القيم على الأعمدة
                for bar in bars:
                    height = bar.get_height()
                    plt.text(bar.get_x() + bar.get_width()/2., height,
                            f'${height:.0f}',
                            ha='center', va='bottom' if height > 0 else 'top', fontsize=8)
                
                # معدل الربح
                plt.subplot(2, 2, 2)
                plt.bar(pnl_df['symbol'], pnl_df['win_rate'], color='#3498db', alpha=0.7)
                plt.title('معدل الصفقات الرابحة (%)', fontsize=12, fontweight='bold')
                plt.xticks(rotation=45)
                plt.ylim(0, 100)
            
            if not positions_df.empty:
                # الربح غير المحقق
                plt.subplot(2, 2, 3)
                colors_unrealized = ['#2ecc71' if x > 0 else '#e74c3c' for x in positions_df['unrealized_pnl']]
                plt.bar(positions_df['symbol'], positions_df['unrealized_pnl'], color=colors_unrealized, alpha=0.8)
                plt.title('الربح غير المحقق ($)', fontsize=12, fontweight='bold')
                plt.xticks(rotation=45)
                
                # حجم المراكز
                plt.subplot(2, 2, 4)
                colors_side = ['#2ecc71' if x == 'LONG' else '#e74c3c' for x in positions_df['side']]
                plt.bar(positions_df['symbol'], positions_df['position_amt'].abs(), color=colors_side, alpha=0.8)
                plt.title('حجم المركز', fontsize=12, fontweight='bold')
                plt.xticks(rotation=45)
            
            plt.tight_layout()
            
            # تحويل الرسم إلى base64
            buffer = io.BytesIO()
            plt.savefig(buffer, format='png', dpi=200, bbox_inches='tight')
            buffer.seek(0)
            plot_base64 = base64.b64encode(buffer.getvalue()).decode()
            plt.close()
            
            return plot_base64
            
        except Exception as e:
            print(f"❌ خطأ في إنشاء الرسم البياني: {e}")
            return None

    async def send_telegram_message(self, message: str, photo_base64: str = None):
        """إرسال رسالة إلى تلغرام"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            print("⚠️  إعدادات تلغرام غير مكتملة")
            return
        
        try:
            if photo_base64:
                # إرسال الصورة
                photo_url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendPhoto"
                photo_data = base64.b64decode(photo_base64)
                
                form_data = aiohttp.FormData()
                form_data.add_field('chat_id', self.telegram_chat_id)
                form_data.add_field('caption', message, parse_mode='HTML')
                form_data.add_field('photo', photo_data, filename='futures_chart.png')
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(photo_url, data=form_data) as response:
                        if response.status == 200:
                            print("✅ تم إرسال الرسم البياني إلى تلغرام")
                        else:
                            print(f"❌ خطأ في إرسال الرسم البياني: {await response.text()}")
            else:
                # إرسال الرسالة النصية فقط
                url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
                payload = {
                    'chat_id': self.telegram_chat_id,
                    'text': message,
                    'parse_mode': 'HTML'
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload) as response:
                        if response.status == 200:
                            print("✅ تم إرسال الرسالة إلى تلغرام")
                        else:
                            print(f"❌ خطأ في إرسال الرسالة: {await response.text()}")
                            
        except Exception as e:
            print(f"❌ خطأ في إرسال تلغرام: {e}")

    def format_futures_summary_report(self, pnl_df: pd.DataFrame, positions_df: pd.DataFrame) -> str:
        """تنسيق التقرير الملخص للعقود الآجلة"""
        try:
            if pnl_df.empty and positions_df.empty:
                return "❌ لا توجد بيانات للتحليل"
            
            report = "📊 <b>تقرير العقود الآجلة - بينانس</b>\n"
            report += "────────────────────\n"
            
            if not pnl_df.empty:
                total_net_pnl = pnl_df['net_pnl'].sum()
                total_volume = pnl_df['total_volume'].sum()
                total_commission = pnl_df['total_commission'].sum()
                profitable_symbols = len(pnl_df[pnl_df['net_pnl'] > 0])
                total_symbols = len(pnl_df)
                avg_win_rate = pnl_df['win_rate'].mean()
                
                report += f"📈 <b>إحصائيات التداول:</b>\n"
                report += f"• صافي الربح/الخسارة: <b>${total_net_pnl:,.2f}</b>\n"
                report += f"• إجمالي العمولات: <b>${total_commission:,.2f}</b>\n"
                report += f"• حجم التداول: <b>${total_volume:,.2f}</b>\n"
                report += f"• العملات الرابحة: <b>{profitable_symbols}/{total_symbols}</b>\n"
                report += f"• متوسط معدل الربح: <b>{avg_win_rate:.1f}%</b>\n"
                report += f"• إجمالي الصفقات: <b>{pnl_df['total_trades'].sum()}</b>\n\n"
            
            if not positions_df.empty:
                total_unrealized = positions_df['unrealized_pnl'].sum()
                long_positions = len(positions_df[positions_df['side'] == 'LONG'])
                short_positions = len(positions_df[positions_df['side'] == 'SHORT'])
                
                report += f"📊 <b>المراكز المفتوحة:</b>\n"
                report += f"• إجمالي الربح غير المحقق: <b>${total_unrealized:,.2f}</b>\n"
                report += f"• مراكز شراء: <b>{long_positions}</b>\n"
                report += f"• مراكز بيع: <b>{short_positions}</b>\n"
                report += f"• إجمالي المراكز: <b>{len(positions_df)}</b>\n\n"
            
            # أفضل وأسوأ الأداء
            if not pnl_df.empty:
                report += "🏆 <b>أفضل الأداء:</b>\n"
                top_winners = pnl_df.nlargest(3, 'net_pnl')
                for i, (_, row) in enumerate(top_winners.iterrows(), 1):
                    emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                    report += f"{emoji} {row['symbol']}: <b>${row['net_pnl']:,.2f}</b>\n"
                
                report += "\n📉 <b>أسوأ الأداء:</b>\n"
                top_losers = pnl_df.nsmallest(3, 'net_pnl')
                for i, (_, row) in enumerate(top_losers.iterrows(), 1):
                    emoji = "🔻"
                    report += f"{emoji} {row['symbol']}: <b>${row['net_pnl']:,.2f}</b>\n"
            
            report += f"\n⏰ تاريخ التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            return report
            
        except Exception as e:
            return f"❌ خطأ في تنسيق التقرير: {str(e)}"

    def format_detailed_futures_report(self, pnl_df: pd.DataFrame) -> str:
        """تنسيق التقرير التفصيلي للعقود الآجلة"""
        try:
            if pnl_df.empty:
                return "❌ لا توجد بيانات للتحليل"
            
            report = "📋 <b>التقرير التفصيلي للعقود الآجلة:</b>\n"
            report += "────────────────────\n"
            
            for _, row in pnl_df.iterrows():
                status_emoji = "✅" if row['status'] == 'ربح' else "❌"
                report += f"\n{status_emoji} <b>{row['symbol']}</b>:\n"
                report += f"   💰 صافي الربح/الخسارة: <b>${row['net_pnl']:,.2f}</b>\n"
                report += f"   📈 الربح المحقق: <b>${row['total_realized_pnl']:,.2f}</b>\n"
                report += f"   💸 العمولات: <b>${row['total_commission']:,.2f}</b>\n"
                report += f"   📊 حجم التداول: <b>${row['total_volume']:,.2f}</b>\n"
                report += f"   🎯 عدد الصفقات: <b>{row['total_trades']}</b>\n"
                report += f"   📈 معدل الربح: <b>{row['win_rate']:.1f}%</b>\n"
                report += f"   ⚖️  صفقات شراء: <b>{row['long_trades']}</b>\n"
                report += f"   ⚖️  صفقات بيع: <b>{row['short_trades']}</b>\n"
                report += "   ────────────────────\n"
            
            return report
            
        except Exception as e:
            return f"❌ خطأ في التقرير التفصيلي: {str(e)}"

    def generate_futures_advice(self, pnl_df: pd.DataFrame, positions_df: pd.DataFrame) -> str:
        """توليد نصائح تداول للعقود الآجلة"""
        advice = "💡 <b>نصائح تداول العقود الآجلة:</b>\n"
        advice += "────────────────────\n"
        
        if not pnl_df.empty:
            total_pnl = pnl_df['net_pnl'].sum()
            win_rate_avg = pnl_df['win_rate'].mean()
            
            if total_pnl > 0:
                advice += "🎉 أداؤك جيد في التداول! استمر في استراتيجيتك.\n"
            else:
                advice += "⚠️  راجع استراتيجية إدارة المخاطر ونقاط الدخول.\n"
            
            if win_rate_avg < 40:
                advice += "📊 معدل الربح منخفض. فكر في تحسين توقيت الدخول.\n"
            elif win_rate_avg > 60:
                advice += "📊 معدل الربح ممتاز! حافظ على دقة التوقيت.\n"
        
        if not positions_df.empty:
            unrealized_pnl = positions_df['unrealized_pnl'].sum()
            if unrealized_pnl < -100:
                advice += "🔔 لديك خسائر غير محققة كبيرة. فكر في إعادة تقييم المراكز.\n"
        
        advice += "\n📚 تذكر في العقود الآجلة:\n"
        advice += "• استخدم وقف الخسارة دائمًا\n• إدارة الرافعة المالية بحكمة\n• تنويع المراكز\n• مراقبة تمويل المراكز\n"
        
        return advice

    async def generate_full_futures_report(self):
        """توليد التقرير الكامل للعقود الآجلة"""
        try:
            print("🚀 بدء إنشاء تقرير العقود الآجلة...")
            
            # اختبار الاتصال أولاً
            if not await self.test_api_connection():
                # استخدام بيانات محاكاة إذا فشل الاتصال
                print("🔄 استخدام بيانات محاكاة للتقرير...")
                trades_df = await self.simulate_futures_trades()
                positions_df = pd.DataFrame()  # لا توجد مراكز في المحاكاة
            else:
                # جلب البيانات الحقيقية
                trades_df = await self.get_real_trades_data()
                positions_df = await self.get_current_positions()
            
            if trades_df.empty and positions_df.empty:
                error_msg = "❌ لم يتم العثور على أي صفقات أو مراكز في حساب العقود الآجلة"
                await self.send_telegram_message(error_msg)
                return
            
            print("📊 جاري تحليل البيانات...")
            analyzed_trades = self.analyze_futures_trades(trades_df)
            pnl_df = self.calculate_futures_pnl(analyzed_trades)
            
            print("🎨 جاري إنشاء الرسوم البيانية...")
            plot_base64 = self.create_futures_summary_plot(pnl_df, positions_df)
            
            print("📨 جاري إرسال التقارير إلى تلغرام...")
            
            # إرسال التقرير الملخص مع الرسم البياني
            summary_report = self.format_futures_summary_report(pnl_df, positions_df)
            await self.send_telegram_message(summary_report, plot_base64)
            
            # انتظار قليل ثم إرسال التقرير التفصيلي
            await asyncio.sleep(2)
            
            if not pnl_df.empty:
                detailed_report = self.format_detailed_futures_report(pnl_df)
                await self.send_telegram_message(detailed_report)
            
            # إرسال نصيحة تداول
            await asyncio.sleep(1)
            advice = self.generate_futures_advice(pnl_df, positions_df)
            await self.send_telegram_message(advice)
            
            print("✅ تم إكمال عملية التقرير بنجاح!")
            
        except Exception as e:
            error_msg = f"❌ <b>خطأ في إنشاء التقرير:</b>\n{str(e)}"
            await self.send_telegram_message(error_msg)
            print(f"Error: {e}")

async def main():
    """الدالة الرئيسية"""
    try:
        analyzer = BinanceFuturesAnalyzer()
        await analyzer.generate_full_futures_report()
    except Exception as e:
        print(f"❌ خطأ في التشغيل: {e}")

if __name__ == "__main__":
    asyncio.run(main())
