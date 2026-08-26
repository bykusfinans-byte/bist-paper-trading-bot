#!/usr/bin/env python3
"""
BIST Paper Trading Bot - Tek Dosya Versiyonu
Tum moduller main.py icinde, hic import sorunu yok.
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
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# =============================================================================
# LOGGING AYARLARI
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# =============================================================================
# KONFIGURASYON
# =============================================================================
def load_config(path="config/config.yaml"):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Config okuma hatasi: {e}")
        sys.exit(1)

# =============================================================================
# VERI CEKME
# =============================================================================
def fetch_stock_data(symbol, interval="4h", lookback_days=60):
    ticker = f"{symbol}.IS"
    end = datetime.now()
    start = end - timedelta(days=lookback_days)
    
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(start=start, end=end, interval=interval, auto_adjust=False)
        
        if df.empty:
            return None
        
        df = df.reset_index()
        
        # Sayisal veri
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.dropna(subset=['Close', 'High', 'Low'])
        
        if len(df) < 55:
            return None
            
        return df
    except Exception as e:
        logger.error(f"{symbol} veri hatasi: {e}")
        return None

# =============================================================================
# INDIKATORLER
# =============================================================================
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_sma(series, period):
    return series.rolling(window=period).mean()

def calc_adx(df, period=14):
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx.rolling(window=period).mean()

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def calc_bb(series, period=20, std_dev=2):
    sma = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower

def add_indicators(df, cfg):
    close = df['Close']
    
    df['EMA9'] = calc_ema(close, cfg['ema_fast'])
    df['EMA21'] = calc_ema(close, cfg['ema_slow'])
    df['SMA50'] = calc_sma(close, cfg['sma_trend'])
    df['ADX'] = calc_adx(df, cfg['adx_period'])
    
    macd, sig, hist = calc_macd(close, cfg['macd_fast'], cfg['macd_slow'], cfg['macd_signal'])
    df['MACD'] = macd
    df['MACD_Signal'] = sig
    df['MACD_Hist'] = hist
    
    bb_up, bb_mid, bb_low = calc_bb(close, cfg['bb_period'], cfg['bb_std'])
    df['BB_Upper'] = bb_up
    df['BB_Middle'] = bb_mid
    df['BB_Lower'] = bb_low
    
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    return df

# =============================================================================
# SINYAL MOTORU
# =============================================================================
def check_signal(df, cfg):
    if len(df) < 55:
        return 'HOLD', 'Yetersiz veri', None
    
    df = add_indicators(df, cfg)
    latest = df.iloc[-1]
    price = float(latest['Close'])
    
    # KOULLAR
    trend_ok = price > latest['EMA9'] > latest['EMA21'] > latest['SMA50']
    adx_ok = latest['ADX'] > cfg['adx_threshold']
    macd_ok = latest['MACD'] > 0
    bb_ok = latest['BB_Lower'] <= price <= latest['BB_Upper']
    vol_ok = latest['Volume'] >= latest['Volume_MA'] * 0.8
    
    reasons = []
    if not trend_ok:
        r = []
        if price <= latest['EMA9']: r.append(f"Fiyat({price:.1f})<=EMA9({latest['EMA9']:.1f})")
        if latest['EMA9'] <= latest['EMA21']: r.append(f"EMA9<=EMA21")
        if latest['EMA21'] <= latest['SMA50']: r.append(f"EMA21<=SMA50")
        reasons.append("Trend:" + ",".join(r))
    if not adx_ok:
        reasons.append(f"ADX({latest['ADX']:.1f})<={cfg['adx_threshold']}")
    if not macd_ok:
        reasons.append(f"MACD({latest['MACD']:.2f})<=0")
    if not bb_ok:
        reasons.append(f"BB disinda")
    if not vol_ok:
        reasons.append(f"Hacim dusuk")
    
    if trend_ok and adx_ok and macd_ok and bb_ok and vol_ok:
        return 'BUY', 'Tum kosullar saglandi', price
    else:
        return 'HOLD', ' | '.join(reasons), price

# =============================================================================
# PORTFOY YONETIMI (SQLite)
# =============================================================================
def init_db(db_path="data/portfolio.db"):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS portfolio (
        id INTEGER PRIMARY KEY, symbol TEXT, shares REAL, entry_price REAL,
        entry_date TEXT, stop_loss REAL, take_profit REAL, status TEXT DEFAULT 'OPEN')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY, symbol TEXT, action TEXT, shares REAL,
        price REAL, total_value REAL, date TEXT, reason TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS balance (
        id INTEGER PRIMARY KEY, cash REAL, total_invested REAL, last_updated TEXT)''')
    
    c = conn.execute("SELECT COUNT(*) FROM balance")
    if c.fetchone()[0] == 0:
        conn.execute("INSERT INTO balance VALUES (1, 100000, 0, ?)", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()

def get_balance(db_path="data/portfolio.db"):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT cash, total_invested FROM balance WHERE id=1").fetchone()
    conn.close()
    return {'cash': row[0], 'total_invested': row[1], 'total_value': row[0]+row[1]}

def get_open_positions(db_path="data/portfolio.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM portfolio WHERE status='OPEN'").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def buy_stock(symbol, price, reason, max_pct=0.20, db_path="data/portfolio.db"):
    bal = get_balance(db_path)
    max_inv = bal['total_value'] * max_pct
    investment = min(bal['cash'], max_inv)
    
    if investment < 1000:
        return False, 'Yetersiz bakiye'
    
    shares = investment / price
    sl = price * 0.95
    tp = price * 1.10
    
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO portfolio (symbol,shares,entry_price,entry_date,stop_loss,take_profit) VALUES (?,?,?,?,?,?)",
                 (symbol, shares, price, datetime.now().isoformat(), sl, tp))
    conn.execute("INSERT INTO transactions (symbol,action,shares,price,total_value,date,reason) VALUES (?,?,?,?,?,?,?)",
                 (symbol, 'BUY', shares, price, investment, datetime.now().isoformat(), reason))
    conn.execute("UPDATE balance SET cash=cash-?, total_invested=total_invested+?, last_updated=? WHERE id=1",
                 (investment, investment, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True, f'{symbol}: {shares:.2f} lot @ {price:.2f} TL'

def sell_stock(symbol, price, reason, db_path="data/portfolio.db"):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    pos = conn.execute("SELECT * FROM portfolio WHERE symbol=? AND status='OPEN'", (symbol,)).fetchone()
    if not pos:
        conn.close()
        return False, 'Pozisyon yok'
    
    shares = pos['shares']
    entry = pos['entry_price']
    total = shares * price
    pnl = total - (shares * entry)
    
    conn.execute("UPDATE portfolio SET status='CLOSED' WHERE id=?", (pos['id'],))
    conn.execute("INSERT INTO transactions (symbol,action,shares,price,total_value,date,reason) VALUES (?,?,?,?,?,?,?)",
                 (symbol, 'SELL', shares, price, total, datetime.now().isoformat(), reason))
    conn.execute("UPDATE balance SET cash=cash+?, total_invested=total_invested-?, last_updated=? WHERE id=1",
                 (total, shares*entry, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True, f'{symbol} satildi, K/Z: {pnl:+.2f} TL'

# =============================================================================
# E-POSTA
# =============================================================================
def send_email(subject, body_html, cfg):
    if not cfg.get('enabled'):
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = cfg['sender_email']
        msg['To'] = cfg['recipient_email']
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))
        
        with smtplib.SMTP(cfg['smtp_server'], cfg['smtp_port']) as s:
            s.starttls()
            s.login(cfg['sender_email'], cfg['sender_password'])
            s.send_message(msg)
        logger.info(f"✅ E-posta gonderildi: {subject}")
        return True
    except Exception as e:
        logger.error(f"❌ E-posta hatasi: {e}")
        return False

# =============================================================================
# ANA CALISTIRMA
# =============================================================================
def run():
    logger.info("=" * 60)
    logger.info("🚀 BIST Paper Trading Bot - Tek Dosya Versiyonu")
    logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    cfg = load_config()
    init_db()
    
    # E-posta config'i env'den al (GitHub Secrets icin)
    email_cfg = cfg['notifications']['email']
    for k in ['sender_email', 'sender_password', 'recipient_email']:
        env_key = k.upper()
        if os.environ.get(env_key):
            email_cfg[k] = os.environ[env_key]
    
    watchlist = cfg['watchlist']
    ind_cfg = cfg['indicators']
    port_cfg = cfg['portfolio']
    
    signals = []
    trades = 0
    
    for symbol in watchlist:
        try:
            logger.info(f"\n🔍 {symbol} analiz ediliyor...")
            df = fetch_stock_data(symbol, cfg['data']['interval'], cfg['data']['lookback_days'])
            
            if df is None:
                logger.warning(f"⚠️ {symbol}: Veri yok")
                continue
            
            sig, reason, price = check_signal(df, ind_cfg)
            signals.append({'symbol': symbol, 'signal': sig, 'price': price, 'reason': reason})
            
            logger.info(f"📌 {symbol} | Sinyal: {sig} | Fiyat: {price:.2f}")
            if sig == 'HOLD' and reason != 'Yetersiz veri':
                logger.info(f"   ↳ Neden: {reason}")
            
            # Mevcut pozisyon varsa kontrol et
            positions = get_open_positions()
            pos = next((p for p in positions if p['symbol'] == symbol), None)
            
            if pos:
                # Stop-loss / Take-profit
                if price <= pos['stop_loss']:
                    ok, msg = sell_stock(symbol, price, f"Stop-loss: {price:.2f} <= {pos['stop_loss']:.2f}")
                    if ok:
                        send_email(f"🔴 SATIS: {symbol}", f"<h2>SATIS: {symbol}</h2><p>{msg}</p>", email_cfg)
                        trades += 1
                elif price >= pos['take_profit']:
                    ok, msg = sell_stock(symbol, price, f"Take-profit: {price:.2f} >= {pos['take_profit']:.2f}")
                    if ok:
                        send_email(f"🟢 SATIS: {symbol}", f"<h2>SATIS: {symbol}</h2><p>{msg}</p>", email_cfg)
                        trades += 1
                elif sig == 'BUY':
                    # Zaten var, bir sey yapma
                    pass
            else:
                # Yeni alim
                if sig == 'BUY':
                    ok, msg = buy_stock(symbol, price, reason, port_cfg['max_position_per_stock'])
                    if ok:
                        send_email(f"🟢 ALIM: {symbol}", f"<h2>ALIM: {symbol}</h2><p>{msg}</p>", email_cfg)
                        trades += 1
                        logger.info(f"✅ {msg}")
        
        except Exception as e:
            logger.error(f"❌ {symbol} hata: {e}")
            continue
    
    # Rapor
    bal = get_balance()
    positions = get_open_positions()
    
    # HTML rapor
    html = f"""<html><body style="font-family:Arial">
    <h1>📊 BIST Bot Raporu - {datetime.now().strftime('%d.%m.%Y %H:%M')}</h1>
    <p>Nakit: {bal['cash']:,.0f} TL | Yatirimda: {bal['total_invested']:,.0f} TL | Toplam: {bal['total_value']:,.0f} TL</p>
    <p>Aciq pozisyon: {len(positions)} | Islem: {trades}</p>
    <h2>Aciq Pozisyonlar</h2>
    <table border="1" cellpadding="8"><tr><th>Hisse</th><th>Lot</th><th>Alis</th><th>SL</th><th>TP</th></tr>
    {''.join(f"<tr><td>{p['symbol']}</td><td>{p['shares']:.2f}</td><td>{p['entry_price']:.2f}</td><td>{p['stop_loss']:.2f}</td><td>{p['take_profit']:.2f}</td></tr>" for p in positions)}
    </table>
    <h2>Sinyaller</h2>
    <table border="1" cellpadding="8"><tr><th>Hisse</th><th>Sinyal</th><th>Fiyat</th><th>Sebep</th></tr>
    {''.join(f"<tr><td>{s['symbol']}</td><td>{s['signal']}</td><td>{s['price']:.2f}</td><td>{s['reason'][:60]}</td></tr>" for s in signals)}
    </table></body></html>"""
    
    send_email(f"📊 BIST Bot - Rapor ({datetime.now().strftime('%d.%m %H:%M')})", html, email_cfg)
    
    # JSON kaydet
    Path("reports").mkdir(exist_ok=True)
    with open(f"reports/signals_{datetime.now().strftime('%Y%m%d_%H%M')}.json", 'w') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 OZET: {len(signals)} hisse | {trades} islem | {len(positions)} pozisyon")
    logger.info(f"💰 Toplam: {bal['total_value']:,.0f} TL")
    logger.info(f"{'='*60}")

if __name__ == "__main__":
    run()
