import requests
import time
import logging

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def send_ping():
    url = "https://mon-1.onrender.com"
    
    try:
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            logging.info(f"✅ النبض ناجح - الحالة: {response.status_code}")
            return True
        else:
            logging.warning(f"⚠️ استجابة غير متوقعة - الحالة: {response.status_code}")
            return False
    
    except requests.exceptions.Timeout:
        logging.error("⏰ انتهت مهلة الطلب")
        return False
    except Exception as e:
        logging.error(f"❌ خطأ: {e}")
        return False

if __name__ == "__main__":
    logging.info("🚀 بدأ إرسال النبضات كل 5 دقائق...")
    
    # عدادات للإحصاء
    successful_pings = 0
    total_pings = 0
    
    while True:
        total_pings += 1
        success = send_ping()
        
        if success:
            successful_pings += 1
        
        # عرض إحصائيات
        success_rate = (successful_pings / total_pings) * 100
        logging.info(f"📊 الإحصائيات: {successful_pings}/{total_pings} نجاح ({success_rate:.1f}%)")
        logging.info("⏳ انتظار 5 دقائق للنبض التالي...\n")
        
        time.sleep(300)  # 5 
