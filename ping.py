import requests
import schedule
import time
import logging

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_ping():
    url = "https://mybot-1-61u6.onrender.com"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            logging.info(f"✅ النبض ناجح - الحالة: {response.status_code}")
        else:
            logging.warning(f"⚠️  استجابة غير متوقعة - الحالة: {response.status_code}")
    
    except requests.exceptions.Timeout:
        logging.error("⏰ انتهت مهلة الطلب")
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ فشل في إرسال النبض: {e}")

# جدولة المهمة كل 5 دقائق
schedule.every(5).minutes.do(send_ping)

if __name__ == "__main__":
    logging.info("🚀 بدأ إرسال النبضات كل 5 دقائق...")
    
    # إرسال النبض الأول فوراً
    send_ping()
    
    # تشغيل الجدولة
    while True:
        schedule.run_pending()
        time.sleep(1)
