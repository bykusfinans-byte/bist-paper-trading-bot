#!/usr/bin/env python3
# === BIST BOT - BASLANGIC ===

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
            return None
        logger.info(f"✅ {symbol}: {len(df)} satir veri")
        return df
    except Exception as e:
        logger.error(f"❌ {symbol} veri hatasi: {e}")
        return None

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def add_indicators(df, cfg):
    c = df['Close']
    df['EMA9'] = c.ewm(span=cfg['ema_fast'], adjust=False).mean()
    df['EMA21'] = c.ewm(span=cfg['ema_slow'], adjust=False).mean()
    df['SMA50'] = c.rolling(window=cfg['sma_trend']).mean()
    df['RSI'] = calc_rsi(c, 14)
    
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
        return 'HOLD', 'Yetersiz veri', None, {}
    df = add_indicators(df, cfg)
    latest = df.iloc[-1]
    price = float(latest['Close'])
    
    trend = price > latest['EMA9'] > latest['EMA21'] > latest['SMA50']
    adx = latest['ADX'] > cfg['adx_threshold']
    macd = latest['MACD'] > 0
    bb = latest['BB_Lower'] <= price <= latest['BB_Upper']
    vol = latest['Volume'] >= latest['Volume_MA'] * 0.5
    
    reasons = []
    if not trend:
        r = []
        if price <= latest['EMA9']: r.append("Fiyat<=EMA9")
        if latest['EMA9'] <= latest['EMA21']: r.append("EMA9<=EMA21")
        if latest['EMA21'] <= latest['SMA50']: r.append("EMA21<=SMA50")
        reasons.append("Trend:" + ",".join(r))
    if not adx: reasons.append(f"ADX({latest['ADX']:.1f})<={cfg['adx_threshold']}")
    if not macd: reasons.append(f"MACD({latest['MACD']:.2f})<=0")
    if not bb: reasons.append("BB disinda")
    if not vol: reasons.append("Hacim dusuk")
    
    indicators = {
        'price': price,
        'ema9': float(latest['EMA9']),
        'ema21': float(latest['EMA21']),
        'sma50': float(latest['SMA50']),
        'rsi': float(latest['RSI']),
        'macd': float(latest['MACD']),
        'adx': float(latest['ADX']),
    }
    
    if trend and adx and macd and bb and vol:
        return 'BUY', 'Tum kosullar saglandi', price, indicators
    return 'HOLD', ' | '.join(reasons), price, indicators

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
    logger.info("🚀 BIST Bot v2.0 Baslatiliyor...")
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
            
            sig, reason, price, ind = check_signal(df, cfg['indicators'])
            signals.append({
                'symbol': sym, 
                'signal': sig, 
                'price': price, 
                'reason': reason,
                'indicators': ind
            })
            logger.info(f"📌 {sym} | Sinyal: {sig} | Fiyat: {price:.2f}")
            if sig == 'HOLD' and reason != 'Yetersiz veri':
                logger.info(f"   ↳ {reason}")
            
            pos = next((p for p in get_pos() if p['symbol'] == sym), None)
            if pos:
                if price <= pos['stop_loss']:
                    ok, msg = sell(sym, price, f"Stop-loss", "data/portfolio.db")
                    if ok: send_mail(f"🔴 SATIS: {sym}", f"<h2>SATIS: {sym}</h2><p>{msg}</p>", email); trades += 1
                elif price >= pos['take_profit']:
                    ok, msg = sell(sym, price, f"Take-profit", "data/portfolio.db")
                    if ok: send_mail(f"🟢 KAR SATISI: {sym}", f"<h2>KAR SATISI: {sym}</h2><p>{msg}</p>", email); trades += 1
            else:
                if sig == 'BUY':
                    ok, msg = buy(sym, price, reason, cfg['portfolio']['max_position_per_stock'])
                    if ok:
                        buy_html = f"""<!DOCTYPE html>
<html><body style="margin:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="20"><tr><td align="center">
<table width="520" cellpadding="0" cellspacing="0" style="background:#fff;border:1px solid #d1d5db;">
<tr><td bgcolor="#16A34A" style="padding:22px;text-align:center;">
<h1 style="margin:0;color:#fff;">🟢 AL SİNYALİ</h1>
<div style="color:#dcfce7;margin-top:8px;">{sym} • {price:.2f} ₺</div></td></tr>
<tr><td style="padding:20px;">
<table width="100%" cellpadding="8">
<tr><td><b>Hisse</b></td><td align="right">{sym}</td></tr>
<tr><td><b>Fiyat</b></td><td align="right">{price:.2f} ₺</td></tr>
<tr><td><b>İşlem</b></td><td align="right" style="color:#16A34A;font-weight:bold;">AL</td></tr>
<tr><td><b>Sebep</b></td><td align="right">{reason}</td></tr>
</table></td></tr>
<tr><td bgcolor="#F8FAFC" style="padding:12px;text-align:center;font-size:11px;color:#64748b;">BIST AI PRO</td></tr>
</table></td></tr></table></body></html>"""
                        send_mail(f"🟢 ALIM: {sym}", buy_html, email)
                        trades += 1
                        logger.info(f"✅ {msg}")
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"❌ {sym} hata: {e}")
    
    bal = get_bal()
    pos_list = get_pos()
    
    # === INDIKATOR TABLOSU ===
    ind_rows = ""
    for s in signals:
        i = s.get("indicators", {})
        if not i:
            ind_rows += f"<tr><td style='padding:8px;border:1px solid #e5e7eb;'>{s['symbol']}</td><td colspan='7' align='center' style='padding:8px;border:1px solid #e5e7eb;color:#999;'>Veri yok</td></tr>"
            continue
        sig_color = "#16A34A" if s["signal"]=="BUY" else "#64748B"
        sig_text = "AL" if s["signal"]=="BUY" else "BEKLE"
        rsi_color = "#DC2626" if i["rsi"]>70 else "#16A34A" if i["rsi"]<30 else "#111827"
        macd_color = "#16A34A" if i["macd"]>0 else "#DC2626"
        adx_color = "#16A34A" if i["adx"]>20 else "#DC2626"
        ind_rows += f"""<tr>
<td style='padding:8px;border:1px solid #e5e7eb;font-weight:bold;'>{s['symbol']}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;color:{sig_color};font-weight:bold;'>{sig_text}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;'>{i['price']:.2f}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;'>{i['ema9']:.2f}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;'>{i['ema21']:.2f}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;'>{i['sma50']:.2f}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;color:{rsi_color};font-weight:bold;'>{i['rsi']:.1f}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;color:{macd_color};font-weight:bold;'>{i['macd']:.2f}</td>
<td align='center' style='padding:8px;border:1px solid #e5e7eb;color:{adx_color};font-weight:bold;'>{i['adx']:.1f}</td>
</tr>"""

    # === ACIK POZISYONLAR ===
    pos_rows = ""
    for p in pos_list:
        pos_rows += f"""
        <tr style="border-bottom:1px solid #e0e0e0;">
            <td style="padding:12px;font-weight:bold;">{p['symbol']}</td>
            <td style="padding:12px;text-align:center;">{p['shares']:.2f}</td>
            <td style="padding:12px;text-align:center;">{p['entry_price']:.2f}</td>
            <td style="padding:12px;text-align:center;color:#e74c3c;">{p['stop_loss']:.2f}</td>
            <td style="padding:12px;text-align:center;color:#27ae60;">{p['take_profit']:.2f}</td>
        </tr>"""
    
    if not pos_rows:
        pos_rows = '<tr><td colspan="5" style="padding:20px;text-align:center;">Açık pozisyon yok</td></tr>'
    
    # === RAPOR HTML ===
    html = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'></head>
<body style='margin:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;'>
<table width='100%' cellpadding='20'><tr><td align='center'>
<table width='680' cellpadding='0' cellspacing='0' style='background:#fff;border:1px solid #d1d5db;'>
<tr><td bgcolor='#0F766E' style='padding:22px;text-align:center;'>
<h1 style='margin:0;color:#fff;'>📈 BIST AI PRO</h1>
<div style='color:#d1fae5;font-size:13px;'>{datetime.now().strftime('%d.%m.%Y %H:%M')}</div></td></tr>
<tr><td style='padding:18px;'>
<table width='100%' cellpadding='6'><tr>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>NAKİT</div><b>{bal['cash']:,.0f} ₺</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>YATIRIM</div><b>{bal['total_invested']:,.0f} ₺</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>TOPLAM</div><b>{bal['total_value']:,.0f} ₺</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>POZİSYON</div><b>{len(pos_list)}</b></td>
</tr></table>
<h2 style='color:#1e293b;'>📊 Teknik Analiz</h2>
<table width='100%' cellpadding='9' cellspacing='0' style='border-collapse:collapse;border:1px solid #d1d5db;'>
<tr bgcolor='#1E293B'><th align='left' style='color:#fff;'>Hisse</th><th style='color:#fff;'>Sinyal</th><th style='color:#fff;'>Fiyat</th><th style='color:#fff;'>EMA9</th><th style='color:#fff;'>EMA21</th><th style='color:#fff;'>SMA50</th><th style='color:#fff;'>RSI</th><th style='color:#fff;'>MACD</th><th style='color:#fff;'>ADX</th></tr>
{ind_rows}
</table>
<h2 style='color:#1e293b;margin-top:22px;'>📋 Açık Pozisyonlar</h2>
<table width='100%' cellpadding='8' cellspacing='0' style='border-collapse:collapse;border:1px solid #d1d5db;'>
<tr bgcolor='#1E293B'><th align='left' style='color:#fff;'>Hisse</th><th style='color:#fff;'>Lot</th><th style='color:#fff;'>Alış</th><th style='color:#fff;'>Stop</th><th style='color:#fff;'>Hedef</th></tr>
{pos_rows}
</table>
</td></tr>
<tr><td bgcolor='#F8FAFC' style='padding:12px;text-align:center;color:#64748b;font-size:11px;'>BIST AI PRO • Otomatik Teknik Analiz Sistemi</td></tr>
</table></td></tr></table></body></html>"""

    send_mail(f"📊 BIST Bot Raporu ({datetime.now().strftime('%d.%m %H:%M')})", html, email)
    
    Path("reports").mkdir(exist_ok=True)
    with open(f"reports/signals_{datetime.now().strftime('%Y%m%d_%H%M')}.json", 'w') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 OZET: {len(signals)} hisse | {trades} islem | {len(pos_list)} pozisyon | {bal['total_value']:,.0f} TL")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    run()
# === BIST BOT - BITIS ===
