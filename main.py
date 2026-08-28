#!/usr/bin/env python3
"""
BIST Paper Trading Bot - Tek Dosya, Sifirdan
"""

import requests
import pandas as pd
import numpy as np
import sqlite3
import smtplib
import yaml
import logging
import sys
import json
import os
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

def load_config(path="config/config.yaml"):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def fetch_stock(symbol, interval="4h", days=60):
    ticker = f"{symbol}.IS"
    end_ts = int(datetime.now().timestamp())
    start_ts = end_ts - (days * 24 * 60 * 60)
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": start_ts, "period2": end_ts, "interval": interval, "events": "history"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        data = r.json()
        
        if "chart" not in data or not data["chart"]["result"]:
            logger.warning(f"⚠️ {symbol}: API bos yanıt")
            return None
        
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        
        df = pd.DataFrame({
            "Datetime": [datetime.fromtimestamp(t) for t in timestamps],
            "Open": quote["open"],
            "High": quote["high"],
            "Low": quote["low"],
            "Close": quote["close"],
            "Volume": quote["volume"]
        })
        
        df = df.dropna()
        if len(df) < 55:
            logger.warning(f"⚠️ {symbol}: Yetersiz veri ({len(df)})")
            return None
        
        logger.info(f"✅ {symbol}: {len(df)} satir veri")
        return df
    except Exception as e:
        logger.error(f"❌ {symbol} veri hatasi: {e}")
        return None

def add_indicators(df, cfg):
    c = df['Close']
    df['EMA9'] = c.ewm(span=cfg['ema_fast'], adjust=False).mean()
    df['EMA21'] = c.ewm(span=cfg['ema_slow'], adjust=False).mean()
    df['SMA50'] = c.rolling(window=cfg['sma_trend']).mean()
    
    h, l, cl = df['High'], df['Low'], df['Close']
    pdm = h.diff().clip(lower=0)
    mdm = (-l.diff()).clip(lower=0)
    tr1, tr2, tr3 = h-l, abs(h-cl.shift(1)), abs(l-cl.shift(1))
    tr = pd.concat([tr1,tr2,tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=cfg['adx_period']).mean()
    pdi = 100*(pdm.rolling(window=cfg['adx_period']).mean()/atr)
    mdi = 100*(mdm.rolling(window=cfg['adx_period']).mean()/atr)
    dx = 100*abs(pdi-mdi)/(pdi+mdi)
    df['ADX'] = dx.rolling(window=cfg['adx_period']).mean()
    
    emaf = c.ewm(span=cfg['macd_fast'], adjust=False).mean()
    emas = c.ewm(span=cfg['macd_slow'], adjust=False).mean()
    df['MACD'] = emaf - emas
    
    sma20 = c.rolling(window=cfg['bb_period']).mean()
    std20 = c.rolling(window=cfg['bb_period']).std()
    df['BB_Upper'] = sma20 + std20*cfg['bb_std']
    df['BB_Lower'] = sma20 - std20*cfg['bb_std']
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    return df

def check_signal(df, cfg):
    if len(df) < 55:
        return 'HOLD', 'Yetersiz veri', None
    df = add_indicators(df, cfg)
    latest = df.iloc[-1]
    price = float(latest['Close'])
    
    trend = price > latest['EMA9'] > latest['EMA21'] > latest['SMA50']
    adx = latest['ADX'] > cfg['adx_threshold']
    macd = latest['MACD'] > 0
    bb = latest['BB_Lower'] <= price <= latest['BB_Upper']
    vol = latest['Volume'] >= latest['Volume_MA'] * 0.8
    
    reasons = []
    if not trend:
        r = []
        if price <= latest['EMA9']: r.append(f"Fiyat({price:.1f})<=EMA9({latest['EMA9']:.1f})")
        if latest['EMA9'] <= latest['EMA21']: r.append("EMA9<=EMA21")
        if latest['EMA21'] <= latest['SMA50']: r.append("EMA21<=SMA50")
        reasons.append("Trend:" + ",".join(r))
    if not adx: reasons.append(f"ADX({latest['ADX']:.1f})<={cfg['adx_threshold']}")
    if not macd: reasons.append(f"MACD({latest['MACD']:.2f})<=0")
    if not bb: reasons.append("BB disinda")
    if not vol: reasons.append("Hacim dusuk")
    
    if trend and adx and macd and bb and vol:
        return 'BUY', 'Tum kosullar saglandi', price
    return 'HOLD', ' | '.join(reasons), price

def init_db(path="data/portfolio.db"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY, symbol TEXT, shares REAL, entry_price REAL, entry_date TEXT, stop_loss REAL, take_profit REAL, status TEXT DEFAULT "OPEN")')
    conn.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, symbol TEXT, action TEXT, shares REAL, price REAL, total_value REAL, date TEXT, reason TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS balance (id INTEGER PRIMARY KEY, cash REAL, total_invested REAL, last_updated TEXT)')
    c = conn.execute("SELECT COUNT(*) FROM balance")
    if c.fetchone()[0] == 0:
        conn.execute("INSERT INTO balance VALUES (1, 100000, 0, ?)", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()

def get_bal(path="data/portfolio.db"):
    conn = sqlite3.connect(path)
    r = conn.execute("SELECT cash, total_invested FROM balance WHERE id=1").fetchone()
    conn.close()
    return {'cash': r[0], 'total_invested': r[1], 'total_value': r[0]+r[1]}

def get_pos(path="data/portfolio.db"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM portfolio WHERE status='OPEN'").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def buy(symbol, price, reason, max_pct=0.20, path="data/portfolio.db"):
    bal = get_bal(path)
    inv = min(bal['cash'], bal['total_value'] * max_pct)
    if inv < 1000:
        return False, 'Yetersiz bakiye'
    shares = inv / price
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO portfolio (symbol,shares,entry_price,entry_date,stop_loss,take_profit) VALUES (?,?,?,?,?,?)", (symbol, shares, price, datetime.now().isoformat(), price*0.95, price*1.10))
    conn.execute("INSERT INTO transactions VALUES (NULL,?,?,?,?,?,?,?)", (symbol, 'BUY', shares, price, inv, datetime.now().isoformat(), reason))
    conn.execute("UPDATE balance SET cash=cash-?, total_invested=total_invested+?, last_updated=? WHERE id=1", (inv, inv, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True, f'{symbol}: {shares:.2f} lot @ {price:.2f} TL'

def sell(symbol, price, reason, path="data/portfolio.db"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    p = conn.execute("SELECT * FROM portfolio WHERE symbol=? AND status='OPEN'", (symbol,)).fetchone()
    if not p:
        conn.close()
        return False, 'Pozisyon yok'
    total = p['shares'] * price
    conn.execute("UPDATE portfolio SET status='CLOSED' WHERE id=?", (p['id'],))
    conn.execute("INSERT INTO transactions VALUES (NULL,?,?,?,?,?,?,?)", (symbol, 'SELL', p['shares'], price, total, datetime.now().isoformat(), reason))
    conn.execute("UPDATE balance SET cash=cash+?, total_invested=total_invested-?, last_updated=? WHERE id=1", (total, p['shares']*p['entry_price'], datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True, f'{symbol} satildi'

def send_mail(subject, html, cfg):
    if not cfg.get('enabled'):
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = cfg['sender_email']
        msg['To'] = cfg['recipient_email']
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        with smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port']) as s:
            s.starttls()
            s.login(cfg['sender_email'], cfg['sender_password'])
            s.send_message(msg)
        logger.info(f"✅ E-posta: {subject}")
        return True
    except Exception as e:
        logger.error(f"❌ E-posta hatasi: {e}")
        return False

def run():
    logger.info("="*60)
    logger.info("🚀 BIST Bot Baslatiliyor...")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*60)
    
    cfg = load_config()
    init_db()
    
    email = cfg['notifications']['email']
    for k in ['sender_email','sender_password','recipient_email']:
        env = k.upper()
        if os.environ.get(env):
            email[k] = os.environ[env]
    
    signals = []
    trades = 0
    
    for sym in cfg['watchlist']:
        try:
            logger.info(f"\n🔍 {sym} analiz ediliyor...")
            df = fetch_stock(sym, cfg['data']['interval'], cfg['data']['lookback_days'])
            if df is None:
                logger.warning(f"⚠️ {sym}: Veri yok")
                continue
            
            sig, reason, price = check_signal(df, cfg['indicators'])
            signals.append({'symbol': sym, 'signal': sig, 'price': price, 'reason': reason})
            logger.info(f"📌 {sym} | Sinyal: {sig} | Fiyat: {price:.2f}")
            if sig == 'HOLD' and reason != 'Yetersiz veri':
                logger.info(f"   ↳ {reason}")
            
            pos = next((p for p in get_pos() if p['symbol'] == sym), None)
            if pos:
                if price <= pos['stop_loss']:
                    ok, msg = sell(sym, price, f"Stop-loss", "data/portfolio.db")
                    if ok:
                        send_mail(f"🔴 SATIS: {sym}", f"<h2>SATIS: {sym}</h2><p>{msg}</p>", email)
                        trades += 1
                elif price >= pos['take_profit']:
                    ok, msg = sell(sym, price, f"Take-profit", "data/portfolio.db")
                    if ok:
                        send_mail(f"🟢 SATIS: {sym}", f"<h2>SATIS: {sym}</h2><p>{msg}</p>", email)
                        trades += 1
            else:
                if sig == 'BUY':
                    ok, msg = buy(sym, price, reason, cfg['portfolio']['max_position_per_stock'])
                    if ok:
                        send_mail(f"🟢 ALIM: {sym}", f"<h2>ALIM: {sym}</h2><p>{msg}</p>", email)
                        trades += 1
                        logger.info(f"✅ {msg}")
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"❌ {sym} hata: {e}")
    
    bal = get_bal()
    pos_list = get_pos()
    
        # RAPOR HTML - Profesyonel Tasarim
    pos_rows = ""
    for p in pos_list:
        pos_rows += f"""
        <tr style="border-bottom:1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;color:#2c3e50;">{p['symbol']}.IS</td>
            <td style="padding:12px;text-align:center;">{p['shares']:.2f}</td>
            <td style="padding:12px;text-align:center;">{p['entry_price']:.2f} ₺</td>
            <td style="padding:12px;text-align:center;">{p['stop_loss']:.2f} ₺</td>
            <td style="padding:12px;text-align:center;">{p['take_profit']:.2f} ₺</td>
        </tr>"""
    
    if not pos_rows:
        pos_rows = '<tr><td colspan="5" style="padding:20px;text-align:center;color:#888;">Açık pozisyon yok</td></tr>'
    
    sig_rows = ""
    colors = {"BUY": "#27ae60", "SELL": "#e74c3c", "HOLD": "#95a5a6"}
    icons = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}
    for s in signals:
        c = colors.get(s['signal'], "#888")
        i = icons.get(s['signal'], "⚪")
        sig_rows += f"""
        <tr style="border-bottom:1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;">{s['symbol']}</td>
            <td style="padding:12px;text-align:center;color:{c};font-weight:bold;">{i} {s['signal']}</td>
            <td style="padding:12px;text-align:center;">{s['price']:.2f} ₺</td>
            <td style="padding:12px;font-size:12px;color:#555;">{s['reason'][:70]}</td>
        </tr>"""
    
    if not sig_rows:
        sig_rows = '<tr><td colspan="4" style="padding:20px;text-align:center;color:#888;">Sinyal yok</td></tr>'
    
    html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BIST Bot Raporu</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:'Segoe UI',Roboto,Arial,sans-serif;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
            <td align="center" style="padding:20px 0;">
                <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
                    
                    <!-- HEADER -->
                    <tr>
                        <td style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);padding:30px;text-align:center;">
                            <h1 style="margin:0;color:#ffffff;font-size:24px;">📈 BIST Paper Trading Bot</h1>
                            <p style="margin:8px 0 0 0;color:#e0e0e0;font-size:14px;">Portföy Raporu • {datetime.now().strftime('%d %B %Y, %H:%M')}</p>
                        </td>
                    </tr>
                    
                    <!-- SUMMARY CARDS -->
                    <tr>
                        <td style="padding:25px 20px;background:#f8f9fa;">
                            <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                    <td width="25%" style="padding:5px;">
                                        <div style="background:#ffffff;padding:15px;border-radius:8px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                            <p style="margin:0 0 5px 0;color:#7f8c8d;font-size:11px;text-transform:uppercase;letter-spacing:1px;">💰 Nakit</p>
                                            <p style="margin:0;font-size:18px;font-weight:bold;color:#2c3e50;">{bal['cash']:,.0f} ₺</p>
                                        </div>
                                    </td>
                                    <td width="25%" style="padding:5px;">
                                        <div style="background:#ffffff;padding:15px;border-radius:8px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                            <p style="margin:0 0 5px 0;color:#7f8c8d;font-size:11px;text-transform:uppercase;letter-spacing:1px;">📊 Yatırımda</p>
                                            <p style="margin:0;font-size:18px;font-weight:bold;color:#2c3e50;">{bal['total_invested']:,.0f} ₺</p>
                                        </div>
                                    </td>
                                    <td width="25%" style="padding:5px;">
                                        <div style="background:#ffffff;padding:15px;border-radius:8px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                            <p style="margin:0 0 5px 0;color:#7f8c8d;font-size:11px;text-transform:uppercase;letter-spacing:1px;">💎 Toplam</p>
                                            <p style="margin:0;font-size:18px;font-weight:bold;color:#2c3e50;">{bal['total_value']:,.0f} ₺</p>
                                        </div>
                                    </td>
                                    <td width="25%" style="padding:5px;">
                                        <div style="background:#ffffff;padding:15px;border-radius:8px;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,0.04);">
                                            <p style="margin:0 0 5px 0;color:#7f8c8d;font-size:11px;text-transform:uppercase;letter-spacing:1px;">📋 Pozisyon</p>
                                            <p style="margin:0;font-size:18px;font-weight:bold;color:#2c3e50;">{len(pos_list)}</p>
                                        </div>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    
                    <!-- ACIK POZISYONLAR -->
                    <tr>
                        <td style="padding:20px;">
                            <h2 style="margin:0 0 15px 0;color:#2c3e50;font-size:16px;border-left:4px solid #667eea;padding-left:10px;">📋 Açık Pozisyonlar</h2>
                            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:13px;">
                                <tr style="background:#34495e;color:#ffffff;">
                                    <th style="padding:10px;text-align:left;border-radius:6px 0 0 0;">Hisse</th>
                                    <th style="padding:10px;text-align:center;">Lot</th>
                                    <th style="padding:10px;text-align:center;">Alış</th>
                                    <th style="padding:10px;text-align:center;">Stop-Loss</th>
                                    <th style="padding:10px;text-align:center;border-radius:0 6px 0 0;">Take-Profit</th>
                                </tr>
                                {pos_rows}
                            </table>
                        </td>
                    </tr>
                    
                    <!-- SINYALLER -->
                    <tr>
                        <td style="padding:0 20px 20px 20px;">
                            <h2 style="margin:0 0 15px 0;color:#2c3e50;font-size:16px;border-left:4px solid #667eea;padding-left:10px;">🎯 Teknik Analiz Sinyalleri</h2>
                            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:13px;">
                                <tr style="background:#34495e;color:#ffffff;">
                                    <th style="padding:10px;text-align:left;border-radius:6px 0 0 0;">Hisse</th>
                                    <th style="padding:10px;text-align:center;">Sinyal</th>
                                    <th style="padding:10px;text-align:center;">Fiyat</th>
                                    <th style="padding:10px;text-align:left;border-radius:0 6px 0 0;">Analiz</th>
                                </tr>
                                {sig_rows}
                            </table>
                        </td>
                    </tr>
                    
                    <!-- FOOTER -->
                    <tr>
                        <td style="background:#f8f9fa;padding:15px;text-align:center;border-top:1px solid #e0e0e0;">
                            <p style="margin:0;color:#95a5a6;font-size:11px;">BIST Paper Trading Bot • Otomatik Raporlama</p>
                            <p style="margin:5px 0 0 0;color:#bdc3c7;font-size:10px;">Bu rapor sanal (paper) trading verilerini içerir.</p>
                        </td>
                    </tr>
                    
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""
    
    send_mail(f"📊 BIST Bot Raporu ({datetime.now().strftime('%d.%m %H:%M')})", html, email)
    
    Path("reports").mkdir(exist_ok=True)
    with open(f"reports/signals_{datetime.now().strftime('%Y%m%d_%H%M')}.json", 'w') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 OZET: {len(signals)} hisse | {trades} islem | {len(pos_list)} pozisyon | {bal['total_value']:,.0f} TL")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    run()
