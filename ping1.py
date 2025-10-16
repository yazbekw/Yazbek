from flask import Flask
import requests
import time
import threading
import logging

app = Flask(__name__)

# إعداد التسجيل
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# كل الروابط هنا
URLS = [
    "https://mybot-1-61u6.onrender.com",
    "https://yazbek-1j7v.onrender.com",
    "https://yazbekw965.onrender.com",
    "https://crypto-scalping.onrender.com",
    "https://mon-1.onrender.com"
]

def send_pings():
    """دالة إرسال النبضات في الخلفية"""
    while True:
        logging.info("🔗 بدء جولة النبضات...")
        
        for url in URLS:
            try:
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    logging.info(f"✅ {url} - ناجح")
                else:
                    logging.info(f"⚠️  {url} - حالة: {response.status_code}")
            except Exception as e:
                logging.info(f"❌ {url} - خطأ: {e}")
            
            time.sleep(1)  # انتظار بين الروابط
        
        logging.info("⏳ انتظار 5 دقائق للجولة التالية...")
        time.sleep(300)  # 5 دقائق

# بدء النبضات في thread منفصل
ping_thread = threading.Thread(target=send_pings, daemon=True)
ping_thread.start()

@app.route('/')
def home():
    return """
    <h1>🚀 بوت النبضات يعمل</h1>
    <p>إرسال نبضات كل 5 دقائق إلى:</p>
    <ul>
        <li>https://mybot-1-61u6.onrender.com</li>
        <li>https://monitor-ocgp.onrender.com</li>
    </ul>
    <p>🟢 البوت يعمل في الخلفية</p>
    """

# لا حاجة لتغيير هذا - Render يتعامل مع البورت تلقائياً
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
