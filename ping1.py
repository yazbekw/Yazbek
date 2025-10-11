import requests
import time
import logging

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class PingMonitor:
    def __init__(self, urls, interval=300):
        self.urls = urls
        self.interval = interval
        self.stats = {url: {'success': 0, 'total': 0, 'response_times': []} for url in urls}
    
    def ping_url(self, url):
        """إرسال نبض إلى رابط معين"""
        try:
            start_time = time.time()
            response = requests.get(url, timeout=30)
            response_time = round((time.time() - start_time) * 1000, 2)
            
            if response.status_code == 200:
                logging.info(f"✅ {self.get_display_name(url)} - ناجح ({response_time}ms)")
                return True, response_time
            else:
                logging.warning(f"⚠️ {self.get_display_name(url)} - حالة غير متوقعة: {response.status_code}")
                return False, response_time
        
        except requests.exceptions.Timeout:
            logging.error(f"⏰ {self.get_display_name(url)} - انتهت المهلة")
            return False, 0
        except Exception as e:
            logging.error(f"❌ {self.get_display_name(url)} - خطأ: {e}")
            return False, 0
    
    def get_display_name(self, url):
        """استخراج اسم مختصر من الرابط"""
        return url.split('//')[1].split('.')[0]
    
    def run_cycle(self):
        """تشغيل دورة كاملة من النبضات"""
        logging.info(f"🔗 بدء جولة النبضات لـ {len(self.urls)} روابط...")
        
        for url in self.urls:
            success, response_time = self.ping_url(url)
            self.stats[url]['total'] += 1
            if success:
                self.stats[url]['success'] += 1
                if response_time > 0:
                    self.stats[url]['response_times'].append(response_time)
            time.sleep(1)  # فاصل بين الطلبات
    
    def show_stats(self):
        """عرض الإحصائيات"""
        logging.info("📊 إحصائيات المراقبة:")
        for url in self.urls:
            s = self.stats[url]
            name = self.get_display_name(url)
            rate = (s['success'] / s['total'] * 100) if s['total'] > 0 else 0
            avg_time = sum(s['response_times']) / len(s['response_times']) if s['response_times'] else 0
            
            status = "✅" if rate > 90 else "⚠️" if rate > 70 else "❌"
            
            logging.info(f"   {status} {name:<15} | النجاح: {s['success']:>2}/{s['total']:<2} | المعدل: {rate:>5.1f}% | متوسط الوقت: {avg_time:>5.0f}ms")

# إعداد المراقبة
if __name__ == "__main__":
    # قائمة الروابط - يمكنك إضافة المزيد هنا بسهولة
    MONITOR_URLS = [
        "https://mybot-1-61u6.onrender.com",
        "https://mon-1.onrender.com"
        # يمكنك إضافة المزيد: "https://example.com"
    ]
    
    monitor = PingMonitor(MONITOR_URLS, interval=300)
    
    logging.info(f"🚀 بدء مراقبة {len(MONITOR_URLS)} روابط كل 5 دقائق...")
    
    while True:
        monitor.run_cycle()
        monitor.show_stats()
        
        next_time = time.time() + monitor.interval
        logging.info(f"⏰ الجولة التالية: {time.strftime('%H:%M:%S', time.localtime(next_time))}\n")
        
        time.sleep(monitor.interval)
