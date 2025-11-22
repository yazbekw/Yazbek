import os
import pandas as pd
import numpy as np
import asyncio
import aiohttp
import hmac
import hashlib
import time
from datetime import datetime, timedelta
from binance.client import Client
from binance.enums import *
import matplotlib.pyplot as plt
import io
import base64
from typing import Dict, List, Tuple, Optional, Any
import urllib.parse
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

class BinanceFuturesReport:
    def __init__(self):
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("❌ مفاتيح API غير موجودة. تأكد من ملف .env")

        # ⭐⭐ استخدام testnet مثل البوت الحالي
        try:
            self.client = Client(
                self.api_key, 
                self.api_secret,
                testnet=True  # ⭐ هذا هو التغيير الأساسي
            )
        except Exception as e:
            print(f"❌ فشل تهيئة عميل Binance: {e}")
            raise

    def test_connection(self):
        """اختبار اتصال API"""
        try:
            # استخدام نفس الطريقة مثل البوت الحالي
            self.client.futures_time()
            print("✅ اتصال Binance Testnet API نشط")
            return True
        except Exception as e:
            print(f"❌ فشل الاتصال بـ Binance Testnet API: {e}")
            return False

    def get_account_info(self):
        """الحصول على معلومات الحساب - مثل البوت الحالي"""
        try:
            account_info = self.client.futures_account()
            return account_info
        except Exception as e:
            print(f"❌ خطأ في الحصول على معلومات الحساب: {e}")
            return None

    def get_positions(self):
        """الحصول على المراكز - مثل البوت الحالي"""
        try:
            positions = self.client.futures_account()['positions']
            active_positions = []
            
            for position in positions:
                position_amt = float(position['positionAmt'])
                if position_amt != 0:
                    active_positions.append({
                        'symbol': position['symbol'],
                        'position_amt': position_amt,
                        'entry_price': float(position['entryPrice']),
                        'unrealized_pnl': float(position['unRealizedProfit']),
                        'leverage': int(position['leverage']),
                        'direction': 'LONG' if position_amt > 0 else 'SHORT',
                        'liquidation_price': float(position.get('liquidationPrice', 0))
                    })
            
            return active_positions
        except Exception as e:
            print(f"❌ خطأ في الحصول على المراكز: {e}")
            return []

    def get_user_trades(self, symbol, limit=500):
        """الحصول على الصفقات - مثل البوت الحالي"""
        try:
            trades = self.client.futures_user_trades(symbol=symbol, limit=limit)
            return trades
        except Exception as e:
            print(f"❌ خطأ في الحصول على صفقات {symbol}: {e}")
            return []

    def get_all_trades_data(self):
        """جمع جميع بيانات الصفقات"""
        print("🔄 جاري جمع بيانات الصفقات من Testnet...")
        
        all_trades = []
        
        # الرموز التي يتابعها البوت الحالي
        symbols = ["BNBUSDT", "ETHUSDT", "SOLUSDT", "BTCUSDT", "XRPUSDT", 
                  "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]
        
        for symbol in symbols:
            try:
                print(f"📊 جاري جمع صفقات {symbol}...")
                trades = self.get_user_trades(symbol)
                
                if trades:
                    for trade in trades:
                        trade['symbol'] = symbol
                        all_trades.append(trade)
                    
                    # تأخير لتجنب rate limit
                    time.sleep(0.5)
                    
            except Exception as e:
                print(f"❌ خطأ في جلب صفقات {symbol}: {e}")
                continue
        
        return pd.DataFrame(all_trades) if all_trades else pd.DataFrame()

    def analyze_trades(self, trades_df):
        """تحليل الصفقات"""
        if trades_df.empty:
            return pd.DataFrame()
        
        try:
            # تحويل البيانات
            trades_df['time'] = pd.to_datetime(trades_df['time'], unit='ms')
            
            # تحويل الأعمدة الرقمية
            numeric_columns = ['price', 'qty', 'quoteQty', 'commission', 'realizedPnl']
            for col in numeric_columns:
                if col in trades_df.columns:
                    trades_df[col] = pd.to_numeric(trades_df[col], errors='coerce')
            
            # تنظيف البيانات
            trades_df = trades_df.dropna()
            
            return trades_df
            
        except Exception as e:
            print(f"❌ خطأ في تحليل الصفقات: {e}")
            return pd.DataFrame()

    def calculate_pnl(self, trades_df):
        """حساب الربح والخسارة"""
        if trades_df.empty:
            return pd.DataFrame()
        
        try:
            symbol_groups = trades_df.groupby('symbol')
            results = []
            
            for symbol, group in symbol_groups:
                # إجمالي الربح المحقق
                total_realized_pnl = group['realizedPnl'].sum() if 'realizedPnl' in group.columns else 0
                
                # العمولات
                total_commission = group['commission'].sum() if 'commission' in group.columns else 0
                
                # حجم التداول
                total_volume = group['quoteQty'].sum() if 'quoteQty' in group.columns else 0
                
                # إحصاءات الصفقات
                total_trades = len(group)
                winning_trades = len(group[group['realizedPnl'] > 0]) if 'realizedPnl' in group.columns else 0
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                
                # صافي الربح بعد العمولات
                net_pnl = total_realized_pnl - total_commission
                
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
                    'status': 'ربح' if net_pnl > 0 else 'خسارة'
                })
            
            return pd.DataFrame(results)
            
        except Exception as e:
            print(f"❌ خطأ في حساب PnL: {e}")
            return pd.DataFrame()

    def create_summary_plot(self, pnl_df, positions_df):
        """إنشاء رسم بياني"""
        try:
            if pnl_df.empty and positions_df.empty:
                return None
            
            plt.style.use('default')
            plt.figure(figsize=(15, 10))
            
            # إعداد البيانات للرسم
            has_pnl_data = not pnl_df.empty
            has_positions_data = len(positions_df) > 0
            
            if has_pnl_data:
                # الرسم البياني للربح/الخسارة
                plt.subplot(2, 2, 1)
                colors = ['#2ecc71' if x > 0 else '#e74c3c' for x in pnl_df['net_pnl']]
                bars = plt.bar(pnl_df['symbol'], pnl_df['net_pnl'], color=colors, alpha=0.8)
                plt.title('صافي الربح/الخسارة ($)', fontsize=12, fontweight='bold')
                plt.xticks(rotation=45)
                
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
            
            if has_positions_data:
                # تحويل positions_df إلى DataFrame للرسم
                positions_data = []
                for pos in positions_df:
                    positions_data.append({
                        'symbol': pos['symbol'],
                        'unrealized_pnl': pos['unrealized_pnl']
                    })
                positions_df_plot = pd.DataFrame(positions_data)
                
                # الربح غير المحقق
                plt.subplot(2, 2, 3)
                colors_unrealized = ['#2ecc71' if x > 0 else '#e74c3c' for x in positions_df_plot['unrealized_pnl']]
                plt.bar(positions_df_plot['symbol'], positions_df_plot['unrealized_pnl'], 
                       color=colors_unrealized, alpha=0.8)
                plt.title('الربح غير المحقق ($)', fontsize=12, fontweight='bold')
                plt.xticks(rotation=45)
                
                # حجم المراكز
                plt.subplot(2, 2, 4)
                position_sizes = [abs(pos['position_amt'] * pos['entry_price']) for pos in positions_df]
                symbols = [pos['symbol'] for pos in positions_df]
                colors_direction = ['#2ecc71' if pos['direction'] == 'LONG' else '#e74c3c' for pos in positions_df]
                plt.bar(symbols, position_sizes, color=colors_direction, alpha=0.8)
                plt.title('حجم المراكز ($)', fontsize=12, fontweight='bold')
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
            print("⚠️ إعدادات تلغرام غير مكتملة")
            return False
        
        try:
            if photo_base64:
                # إرسال الصورة
                photo_url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendPhoto"
                photo_data = base64.b64decode(photo_base64)
                
                form_data = aiohttp.FormData()
                form_data.add_field('chat_id', self.telegram_chat_id)
                form_data.add_field('caption', message, parse_mode='HTML')
                form_data.add_field('photo', photo_data, filename='futures_report.png')
                
                async with aiohttp.ClientSession() as session:
                    async with session.post(photo_url, data=form_data) as response:
                        if response.status == 200:
                            print("✅ تم إرسال التقرير إلى تلغرام")
                            return True
                        else:
                            error_text = await response.text()
                            print(f"❌ خطأ في إرسال التقرير: {response.status} - {error_text}")
                            return False
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
                            return True
                        else:
                            error_text = await response.text()
                            print(f"❌ خطأ في إرسال الرسالة: {response.status} - {error_text}")
                            return False
                            
        except Exception as e:
            print(f"❌ خطأ في إرسال تلغرام: {e}")
            return False

    def format_summary_report(self, pnl_df, positions_df, account_info):
        """تنسيق التقرير الملخص"""
        try:
            report = "📊 <b>تقرير أداء العقود الآجلة - TESTNET</b>\n"
            report += "════════════════════════════\n\n"
            
            # معلومات الحساب
            if account_info:
                total_balance = float(account_info.get('totalWalletBalance', 0))
                available_balance = float(account_info.get('availableBalance', 0))
                total_margin = float(account_info.get('totalMarginBalance', 0))
                
                report += f"💰 <b>معلومات الحساب:</b>\n"
                report += f"• الرصيد الإجمالي: <b>${total_balance:,.2f}</b>\n"
                report += f"• الرصيد المتاح: <b>${available_balance:,.2f}</b>\n"
                report += f"• هامش التداول: <b>${total_margin:,.2f}</b>\n\n"
            
            # إحصائيات التداول
            if not pnl_df.empty:
                total_net_pnl = pnl_df['net_pnl'].sum()
                total_volume = pnl_df['total_volume'].sum()
                total_trades = pnl_df['total_trades'].sum()
                profitable_symbols = len(pnl_df[pnl_df['net_pnl'] > 0])
                total_symbols = len(pnl_df)
                avg_win_rate = pnl_df['win_rate'].mean()
                
                report += f"📈 <b>إحصائيات التداول:</b>\n"
                report += f"• صافي الربح/الخسارة: <b>${total_net_pnl:,.2f}</b>\n"
                report += f"• حجم التداول: <b>${total_volume:,.2f}</b>\n"
                report += f"• إجمالي الصفقات: <b>{total_trades}</b>\n"
                report += f"• العملات الرابحة: <b>{profitable_symbols}/{total_symbols}</b>\n"
                report += f"• متوسط معدل الربح: <b>{avg_win_rate:.1f}%</b>\n\n"
            else:
                report += f"📈 <b>إحصائيات التداول:</b>\n"
                report += f"• لا توجد صفقات سابقة\n\n"
            
            # المراكز المفتوحة
            if positions_df:
                total_unrealized = sum(pos['unrealized_pnl'] for pos in positions_df)
                long_positions = len([pos for pos in positions_df if pos['direction'] == 'LONG'])
                short_positions = len([pos for pos in positions_df if pos['direction'] == 'SHORT'])
                
                report += f"📊 <b>المراكز المفتوحة:</b>\n"
                report += f"• إجمالي الربح غير المحقق: <b>${total_unrealized:,.2f}</b>\n"
                report += f"• مراكز شراء: <b>{long_positions}</b>\n"
                report += f"• مراكز بيع: <b>{short_positions}</b>\n"
                report += f"• إجمالي المراكز: <b>{len(positions_df)}</b>\n\n"
                
                # تفاصيل المراكز
                report += f"<b>تفاصيل المراكز:</b>\n"
                for pos in positions_df:
                    pnl_emoji = "🟢" if pos['unrealized_pnl'] > 0 else "🔴"
                    report += f"• {pos['symbol']} ({pos['direction']}): {pnl_emoji} ${pos['unrealized_pnl']:,.2f}\n"
                report += "\n"
            else:
                report += f"📊 <b>المراكز المفتوحة:</b>\n"
                report += f"• لا توجد مراكز مفتوحة\n\n"
            
            # أفضل وأسوأ الأداء
            if not pnl_df.empty:
                report += "🏆 <b>أفضل الأداء:</b>\n"
                top_winners = pnl_df.nlargest(3, 'net_pnl')
                if not top_winners.empty:
                    for i, (_, row) in enumerate(top_winners.iterrows(), 1):
                        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                        report += f"{emoji} {row['symbol']}: <b>${row['net_pnl']:,.2f}</b>\n"
                else:
                    report += "• لا توجد صفقات رابحة\n"
                
                report += "\n📉 <b>أسوأ الأداء:</b>\n"
                top_losers = pnl_df.nsmallest(3, 'net_pnl')
                if not top_losers.empty:
                    for i, (_, row) in enumerate(top_losers.iterrows(), 1):
                        emoji = "🔻"
                        report += f"{emoji} {row['symbol']}: <b>${row['net_pnl']:,.2f}</b>\n"
                else:
                    report += "• لا توجد صفقات خاسرة\n"
            
            report += f"\n⏰ تاريخ التقرير: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            report += f"\n🌐 البيئة: <b>TESTNET (تجريبي)</b>"
            
            return report
            
        except Exception as e:
            return f"❌ خطأ في تنسيق التقرير: {str(e)}"

    def format_detailed_report(self, pnl_df):
        """تقرير تفصيلي للصفقات"""
        if pnl_df.empty:
            return "📭 لا توجد بيانات للعرض"
        
        try:
            report = "📋 <b>التقرير التفصيلي للصفقات:</b>\n"
            report += "════════════════════════════\n\n"
            
            for _, row in pnl_df.iterrows():
                status_emoji = "✅" if row['status'] == 'ربح' else "❌"
                report += f"{status_emoji} <b>{row['symbol']}</b>:\n"
                report += f"   💰 صافي الربح/الخسارة: <b>${row['net_pnl']:,.2f}</b>\n"
                report += f"   📈 الربح المحقق: <b>${row['total_realized_pnl']:,.2f}</b>\n"
                report += f"   💸 العمولات: <b>${row['total_commission']:,.2f}</b>\n"
                report += f"   📊 حجم التداول: <b>${row['total_volume']:,.2f}</b>\n"
                report += f"   🎯 عدد الصفقات: <b>{row['total_trades']}</b>\n"
                report += f"   📈 معدل الربح: <b>{row['win_rate']:.1f}%</b>\n"
                report += f"   📊 الصفقات الرابحة: <b>{row['winning_trades']}/{row['total_trades']}</b>\n"
                report += "   ────────────────────\n\n"
            
            return report
            
        except Exception as e:
            return f"❌ خطأ في التقرير التفصيلي: {str(e)}"

    def generate_trading_advice(self, pnl_df, positions_df):
        """توليد نصائح تداول"""
        advice = "💡 <b>نصائح تداول:</b>\n"
        advice += "════════════════════════════\n"
        
        if not pnl_df.empty:
            total_pnl = pnl_df['net_pnl'].sum()
            win_rate_avg = pnl_df['win_rate'].mean()
            
            if total_pnl > 0:
                advice += "🎉 أداؤك جيد! استمر في استراتيجيتك الحالية.\n"
            else:
                advice += "⚠️ هناك مجال للتحسين. راجع استراتيجية إدارة المخاطر.\n"
            
            if win_rate_avg < 40:
                advice += "📊 معدل الربح منخفض. فكر في تحسين نقاط الدخول والخروج.\n"
            elif win_rate_avg > 60:
                advice += "📊 معدل الربح ممتاز! حافظ على هذا الأداء.\n"
        
        if positions_df:
            unrealized_pnl = sum(pos['unrealized_pnl'] for pos in positions_df)
            if unrealized_pnl < -100:
                advice += "🔔 لديك خسائر غير محققة كبيرة. فكر في إعادة تقييم المراكز.\n"
        
        advice += "\n📚 تذكر في العقود الآجلة:\n"
        advice += "• استخدم وقف الخسارة دائمًا\n• إدارة الرافعة المالية بحكمة\n• تنويع المراكز\n• مراقبة تمويل المراكز\n"
        
        return advice

    async def generate_full_report(self):
        """توليد التقرير الكامل"""
        try:
            print("🚀 بدء إنشاء تقرير Testnet...")
            
            # اختبار الاتصال أولاً
            if not self.test_connection():
                error_msg = "❌ فشل الاتصال بـ Binance Testnet"
                await self.send_telegram_message(error_msg)
                return
            
            # جمع البيانات
            print("📊 جاري جمع بيانات الحساب...")
            account_info = self.get_account_info()
            positions_df = self.get_positions()
            trades_df = self.get_all_trades_data()
            
            if trades_df.empty and not positions_df:
                message = "📭 لا توجد صفقات أو مراكز في حساب Testnet"
                await self.send_telegram_message(message)
                return
            
            # تحليل البيانات
            print("📈 جاري تحليل البيانات...")
            analyzed_trades = self.analyze_trades(trades_df)
            pnl_df = self.calculate_pnl(analyzed_trades)
            
            # إنشاء الرسم البياني
            print("🎨 جاري إنشاء الرسوم البيانية...")
            plot_base64 = self.create_summary_plot(pnl_df, positions_df)
            
            # إرسال التقارير
            print("📨 جاري إرسال التقارير إلى تلغرام...")
            
            # التقرير الملخص مع الرسم البياني
            summary_report = self.format_summary_report(pnl_df, positions_df, account_info)
            await self.send_telegram_message(summary_report, plot_base64)
            
            # انتظار قليل بين الرسائل
            await asyncio.sleep(2)
            
            # التقرير التفصيلي
            if not pnl_df.empty:
                detailed_report = self.format_detailed_report(pnl_df)
                await self.send_telegram_message(detailed_report)
            
            # انتظار قليل بين الرسائل
            await asyncio.sleep(1)
            
            # النصائح
            advice = self.generate_trading_advice(pnl_df, positions_df)
            await self.send_telegram_message(advice)
            
            print("✅ تم إكمال التقرير بنجاح!")
            
        except Exception as e:
            error_msg = f"❌ <b>خطأ في إنشاء التقرير:</b>\n{str(e)}"
            await self.send_telegram_message(error_msg)
            print(f"Error: {e}")

async def main():
    """الدالة الرئيسية"""
    try:
        reporter = BinanceFuturesReport()
        await reporter.generate_full_report()
    except ValueError as e:
        print(f"❌ خطأ في الإعدادات: {e}")
    except Exception as e:
        print(f"❌ خطأ في التشغيل: {e}")

if __name__ == "__main__":
    # تشغيل البرنامج
    asyncio.run(main())
