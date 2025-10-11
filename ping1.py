import requests
import time
import logging

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def try_different_ports(base_url):
    """تجربة منافذ مختلفة للعثور على المنفذ الصحيح"""
    common_ports = [10000, 8080, 3000, 5000, 8000, 443, 80]
    
    for port in common_ports:
        url_with_port = f"{base_url}:{port}"
        try:
            logging.info(f"🔍 جرب المنفذ {port}...")
            response = requests.get(url_with_port, timeout=10)
            if response.status_code == 200:
                logging.info(f"✅ وجد المنفذ الصحيح: {port}")
                return url_with_port
        except:
            continue
    
    # إذا لم يعمل أي منفذ، نعود للرابط الأساسي
    logging.warning("⚠️ لم يتم العثور على منفذ صحيح، استخدام الرابط الأساسي")
    return base_url

def send_ping(target_url):
    try:
        response = requests.get(target_url, timeout=30)
        
        if response.status_code == 200:
            logging.info(f"✅ النبض ناجح - الحالة: {response.status_code}")
            return True
        else:
            logging.warning(f"⚠️ استجابة غير متوقعة - الحالة: {response.status_code}")
            return False
    
    except requests.exceptions.Timeout:
        logging.error("⏰ انتهت مهلة الطلب")
        return False
    except requests.exceptions.ConnectionError:
        logging.error("🔌 خطأ في الاتصال")
        return False
    except Exception as e:
        logging.error(f"❌ خطأ غير متوقع: {e}")
        return False

if __name__ == "__main__":
    base_url = "https://mybot-1-61u6.onrender.com"
    
    # اكتشاف المنفذ الصحيح
    target_url = try_different_ports(base_url)
    logging.info(f"🎯 الرابط المستهدف: {target_url}")
    
    logging.info("🚀 بدأ إرسال النبضات كل 5 دقائق...")
    
    while True:
        send_ping(target_url)
        logging.info("⏳ انتظار 5 دقائق للنبض التالي...")
        time.sleep(300)
