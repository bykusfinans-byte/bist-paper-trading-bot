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

from flask import Flask, jsonify, request

import main as bot
from mail_gate import should_send_now, mark_sent

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

DB_PATH = "data/portfolio.db"
INTERVAL_MINUTES = 30

# config.yaml'a deploy gerektirmeden degistirilebilen ayarlar (deploy = disk sifirlanmasi demek)
ALLOWED_SETTINGS = {
    'min_position_size', 'max_position_size', 'macd_strength_threshold',
    'volume_strength_threshold', 'trailing_activation_pct', 'trailing_stop_pct',
}


@app.route("/")
def home():
    """Basit saglik kontrolu - cron-job.org bu adrese de bakabilir."""
    return jsonify({"status": "alive", "time": datetime.now().isoformat()})


@app.route("/settings", methods=["GET"])
def get_settings():
    """Su anki (veritabaninda kayitli veya config.yaml'dan gelen) ayar degerlerini gosterir."""
    bot.init_db(DB_PATH)
    cfg = bot.load_config()
    defaults = cfg.get('portfolio', {})
    values = {k: bot.get_setting(k, defaults.get(k), DB_PATH) for k in ALLOWED_SETTINGS}
    return jsonify({"status": "ok", "settings": values})


@app.route("/set-setting", methods=["GET"])
def set_setting_route():
    """Ornek kullanim: /set-setting?key=trailing_stop_pct&value=0.03
    Deploy gerektirmez, aninda etkili olur, portfoyu SIFIRLAMAZ."""
    key = request.args.get('key')
    value = request.args.get('value')
    if not key or value is None:
        return jsonify({"status": "error", "message": "key ve value parametreleri gerekli"}), 400
    if key not in ALLOWED_SETTINGS:
        return jsonify({"status": "error", "message": f"desteklenmeyen key. izin verilenler: {sorted(ALLOWED_SETTINGS)}"}), 400
    try:
        value = float(value)
    except ValueError:
        return jsonify({"status": "error", "message": "value sayisal olmali"}), 400

    bot.init_db(DB_PATH)
    bot.set_setting(key, value, DB_PATH)
    return jsonify({"status": "ok", "key": key, "value": value})


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
