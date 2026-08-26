#!/usr/bin/env python3
"""
BIST Paper Trading Bot - Tek Dosya
"""

import yfinance as yf
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
    end = datetime.now()
    start = end - timedelta(days=days)
    try:
        # farkli yontem dene
        df = yf.download(ticker, start=start, end=end, interval=interval, progress=False, auto_adjust=True, prepost=False)
        if df.empty:
            return None
        df = df.reset_index()
        if 'Date' in df.columns:
            df = df.rename(columns={'Date': 'Datetime'})
        for col in ['Open','High','Low','Close','Volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=['Close','High','Low'])
        if len(df) < 55:
            return None
        return df
    except Exception as e:
        logger.error(f"{symbol} veri hatasi: {e}")
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
    df['MACD_Signal'] = df['MACD'].ewm(span=cfg['macd_signal'], adjust=False).mean()
    
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
        if price <= latest['EMA9']: r.append(f"Fiyat<=EMA9")
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
            
            # Pozisyon kontrol
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
    
    html = f"""<html><body style="font-family:Arial">
    <h1>📊 BIST Bot Raporu - {datetime.now().strftime('%d.%m.%Y %H:%M')}</h1>
    <p>Nakit: {bal['cash']:,.0f} TL | Yatirimda: {bal['total_invested']:,.0f} TL | Toplam: {bal['total_value']:,.0f} TL</p>
    <p>Aciq pozisyon: {len(pos_list)} | Islem: {trades}</p>
    <h2>Aciq Pozisyonlar</h2>
    <table border="1" cellpadding="6"><tr><th>Hisse</th><th>Lot</th><th>Alis</th><th>SL</th><th>TP</th></tr>
    {''.join(f"<tr><td>{p['symbol']}</td><td>{p['shares']:.2f}</td><td>{p['entry_price']:.2f}</td><td>{p['stop_loss']:.2f}</td><td>{p['take_profit']:.2f}</td></tr>" for p in pos_list)}
    </table>
    <h2>Sinyaller</h2>
    <table border="1" cellpadding="6"><tr><th>Hisse</th><th>Sinyal</th><th>Fiyat</th><th>Sebep</th></tr>
    {''.join(f"<tr><td>{s['symbol']}</td><td>{s['signal']}</td><td>{s['price']:.2f}</td><td>{s['reason'][:50]}</td></tr>" for s in signals)}
    </table></body></html>"""
    
    send_mail(f"📊 BIST Bot Raporu ({datetime.now().strftime('%d.%m %H:%M')})", html, email)
    
    Path("reports").mkdir(exist_ok=True)
    with open(f"reports/signals_{datetime.now().strftime('%Y%m%d_%H%M')}.json", 'w') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 OZET: {len(signals)} hisse | {trades} islem | {len(pos_list)} pozisyon | {bal['total_value']:,.0f} TL")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    run()
