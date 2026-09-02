#!/usr/bin/env python3
"""
app.py
------
Render'in ucretsiz Web Service'inde calisacak kucuk bir Flask sunucusu.

Nasil calisir:
- cron-job.org gibi ucretsiz bir dis servis, her ~10 dakikada bir
  https://<render-adresin>.onrender.com/run adresine istek atar.
- Bu istek hem Render'daki servisi "uyanik" tutar (free plan 15 dk
  hareketsizlikte servisi uyutur), hem de asagidaki /run endpoint'ini tetikler.
- mail_gate.py sayesinde, /run her 10 dakikada bir cagrilsa bile gercek
  analiz + mail gonderimi sadece son gonderimden bu yana 30 dakika
  gectiyse yapilir. Yani mail sikligi degismez, sadece "uyandirma"
  sikligi daha yuksek.

Render kurulumu:
  Build Command : pip install -r requirements.txt
  Start Command : gunicorn app:app
  Environment   : SENDER_EMAIL, SENDER_PASSWORD, RECIPIENT_EMAIL (main.py zaten bunlari okuyor)
"""

import logging
from datetime import datetime

from flask import Flask, jsonify

import main as bot
from mail_gate import should_send_now, mark_sent

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

DB_PATH = "data/portfolio.db"
INTERVAL_MINUTES = 30


@app.route("/")
def home():
    """Basit saglik kontrolu - cron-job.org bu adrese de bakabilir."""
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})


@app.route("/run")
def trigger_run():
    """Dis cron servisinin tetikledigi asil endpoint."""
    bot.init_db(DB_PATH)

    if not should_send_now(db_path=DB_PATH, interval_minutes=INTERVAL_MINUTES):
        return jsonify({"status": "skipped", "ran": False, "time": datetime.now().isoformat()})

    try:
        bot.run()
        mark_sent(db_path=DB_PATH)
        return jsonify({"status": "ok", "ran": True, "time": datetime.now().isoformat()})
    except Exception as e:
        logger.error(f"Run hatasi: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
