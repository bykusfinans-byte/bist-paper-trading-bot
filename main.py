#!/usr/bin/env python3
# === BIST BOT - BASLANGIC ===
import requests
import pandas as pd
import numpy as np
import sqlite3
import yaml
import logging
import sys
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

def load_config(path="config/config.yaml"):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def market_is_open(cfg):
    """BIST'in normal seans saatleri icinde miyiz? (varsayilan: hafta ici 10:00-18:00 TSI)"""
    mh = cfg.get('market_hours', {})
    start = mh.get('start', '10:00')
    end = mh.get('end', '18:00')
    now = datetime.now(ISTANBUL_TZ)
    if now.weekday() >= 5:  # 5=Cumartesi, 6=Pazar
        return False
    start_t = datetime.strptime(start, "%H:%M").time()
    end_t = datetime.strptime(end, "%H:%M").time()
    return start_t <= now.time() <= end_t

CACHE_DIR = Path("cache")
CACHE_TTL_MINUTES = 90  # 4 saatlik mum kullandigimiz icin bu kadar sik tazelemeye gerek yok

def load_cache(symbol):
    f = CACHE_DIR / f"{symbol}.json"
    if not f.exists():
        return None, None
    try:
        obj = json.loads(f.read_text())
        ts = datetime.fromisoformat(obj['ts'])
        df = pd.read_json(json.dumps(obj['data']), orient='records')
        df['Datetime'] = pd.to_datetime(df['Datetime'])
        return df, ts
    except Exception:
        return None, None

def save_cache(symbol, df):
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        f = CACHE_DIR / f"{symbol}.json"
        payload = {'ts': datetime.now().isoformat(), 'data': json.loads(df.to_json(orient='records', date_format='iso'))}
        f.write_text(json.dumps(payload))
    except Exception as e:
        logger.warning(f"⚠️ {symbol}: Onbellege yazilamadi: {e}")

def get_stock_data(symbol, interval, days):
    """Once onbellege bakar (90 dk icinde ise Yahoo'ya hic gitmez).
    Onbellek eskiyse tazelemeye calisir; basarisiz olursa (rate-limit vb.)
    'Veri Yok' yerine elde ne kadar eski veri varsa onu kullanir."""
    cached_df, cached_ts = load_cache(symbol)
    if cached_df is not None and cached_ts and (datetime.now() - cached_ts) < timedelta(minutes=CACHE_TTL_MINUTES):
        age_min = int((datetime.now() - cached_ts).total_seconds() // 60)
        logger.info(f"🗄️ {symbol}: Onbellekten ({age_min} dk once)")
        return cached_df

    fresh_df = fetch_stock(symbol, interval, days)
    if fresh_df is not None:
        save_cache(symbol, fresh_df)
        return fresh_df

    if cached_df is not None:
        age_min = int((datetime.now() - cached_ts).total_seconds() // 60)
        logger.warning(f"⚠️ {symbol}: Guncel veri alinamadi, {age_min} dk eski onbellek kullaniliyor")
        return cached_df

    return None

def fetch_stock(symbol, interval="4h", days=60, retries=1):
    """Yahoo Finance IP basina saatlik istek siniri koyuyor; Render'in paylasimli IP'si
    yuzunden ara sira 429/bos yanit gelebilir. Retry sayisi kasitli dusuk tutuluyor,
    aksi halde toplam calisma suresi gunicorn timeout'unu asabiliyor."""
    ticker = f"{symbol}.IS"
    end_ts = int(datetime.now().timestamp())
    start_ts = end_ts - (days * 24 * 60 * 60)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"period1": start_ts, "period2": end_ts, "interval": interval, "events": "history"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code == 429:
                if attempt < retries:
                    logger.warning(f"⏳ {symbol}: Rate limit (429), 3s bekleniyor...")
                    time.sleep(3)
                    continue
                logger.error(f"❌ {symbol}: Rate limit (429), vazgeciliyor")
                return None
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
            if attempt < retries:
                logger.warning(f"⚠️ {symbol}: Veri hatasi ({e}), 2s sonra tekrar denenecek...")
                time.sleep(2)
            else:
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
    rsi_ok = latest['RSI'] < cfg.get('rsi_overbought', 70)
    # bb = latest['BB_Lower'] <= price <= latest['BB_Upper']   # PASIF (alim kararinda kullanilmiyor)

    # Hacim artik AL/HOLD kararini engellemiyor, sadece pozisyon buyuklugu icin
    # bir "guc" gostergesi olarak kullaniliyor (bkz: calc_position_size).
    vol_ratio = float(latest['Volume'] / latest['Volume_MA']) if latest['Volume_MA'] else 0.0
    macd_strength = (latest['MACD'] / price) * 100 if price else 0.0

    reasons = []
    if not trend:
        r = []
        if price <= latest['EMA9']: r.append("Fiyat<=EMA9")
        if latest['EMA9'] <= latest['EMA21']: r.append("EMA9<=EMA21")
        if latest['EMA21'] <= latest['SMA50']: r.append("EMA21<=SMA50")
        reasons.append("Trend:" + ",".join(r))
    if not adx: reasons.append(f"ADX({latest['ADX']:.1f})<={cfg['adx_threshold']}")
    if not macd: reasons.append(f"MACD({latest['MACD']:.2f})<=0")
    if not rsi_ok: reasons.append(f"RSI asiri alim ({latest['RSI']:.1f})")

    indicators = {
        'price': price,
        'ema9': float(latest['EMA9']),
        'ema21': float(latest['EMA21']),
        'sma50': float(latest['SMA50']),
        'rsi': float(latest['RSI']),
        'macd': float(latest['MACD']),
        'adx': float(latest['ADX']),
        'vol_ratio': vol_ratio,
        'macd_strength': macd_strength,
    }

    if trend and adx and macd and rsi_ok:
        return 'BUY', 'Tum kosullar saglandi', price, indicators
    return 'HOLD', ' | '.join(reasons), price, indicators

def calc_position_size(macd_strength, vol_ratio, cfg):
    """MACD gucu ve hacim gucune gore pozisyon buyuklugunu (TL) belirler."""
    p = cfg['portfolio']
    min_size = p['min_position_size']
    max_size = p['max_position_size']
    strong_macd = macd_strength >= p['macd_strength_threshold']
    strong_vol = vol_ratio >= p['volume_strength_threshold']

    if strong_macd and strong_vol:
        return max_size
    if not strong_macd and not strong_vol:
        return min_size
    return (min_size + max_size) / 2

def init_db(path="data/portfolio.db"):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS portfolio (id INTEGER PRIMARY KEY, symbol TEXT, shares REAL, entry_price REAL, entry_date TEXT, stop_loss REAL, take_profit REAL, status TEXT DEFAULT "OPEN", peak_price REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY, symbol TEXT, action TEXT, shares REAL, price REAL, total_value REAL, date TEXT, reason TEXT, pnl REAL, pnl_pct REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS balance (id INTEGER PRIMARY KEY, cash REAL, total_invested REAL, last_updated TEXT)')

    # Eski veritabanlarinda eksik olabilecek kolonlari ekle (basit migration)
    for table, cols in [('portfolio', ['peak_price']), ('transactions', ['pnl', 'pnl_pct'])]:
        existing = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        for col in cols:
            if col not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} REAL")

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

def update_peak(symbol, peak, path="data/portfolio.db"):
    conn = sqlite3.connect(path)
    conn.execute("UPDATE portfolio SET peak_price=? WHERE symbol=? AND status='OPEN'", (peak, symbol))
    conn.commit()
    conn.close()

def get_performance_stats(path="data/portfolio.db"):
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT pnl FROM transactions WHERE action='SELL' AND pnl IS NOT NULL").fetchall()
    conn.close()
    pnls = [r[0] for r in rows]
    total = len(pnls)
    wins = len([p for p in pnls if p > 0])
    losses = len([p for p in pnls if p <= 0])
    win_rate = (wins / total * 100) if total else 0.0
    total_pnl = sum(pnls)
    return {'total_trades': total, 'wins': wins, 'losses': losses, 'win_rate': win_rate, 'total_pnl': total_pnl}

def buy(symbol, price, reason, size, path="data/portfolio.db"):
    """size: TL cinsinden hedeflenen sabit yatirim tutari (calc_position_size'dan gelir)."""
    bal = get_bal(path)
    inv = min(bal['cash'], size)
    if inv < 1000:
        return False, 'Yetersiz bakiye'
    shares = inv / price
    conn = sqlite3.connect(path)
    conn.execute("INSERT INTO portfolio (symbol,shares,entry_price,entry_date,stop_loss,take_profit,peak_price) VALUES (?,?,?,?,?,?,?)", (symbol, shares, price, datetime.now().isoformat(), price*0.95, price*1.10, price))
    conn.execute("INSERT INTO transactions (symbol,action,shares,price,total_value,date,reason) VALUES (?,?,?,?,?,?,?)", (symbol, 'BUY', shares, price, inv, datetime.now().isoformat(), reason))
    conn.execute("UPDATE balance SET cash=cash-?, total_invested=total_invested+?, last_updated=? WHERE id=1", (inv, inv, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True, f'{symbol}: {shares:.2f} lot @ {price:.2f} TL ({inv:,.0f} TL)'

def sell(symbol, price, reason, path="data/portfolio.db"):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    p = conn.execute("SELECT * FROM portfolio WHERE symbol=? AND status='OPEN'", (symbol,)).fetchone()
    if not p:
        conn.close()
        return False, 'Pozisyon yok'
    total = p['shares'] * price
    cost = p['shares'] * p['entry_price']
    pnl = total - cost
    pnl_pct = (price / p['entry_price'] - 1) * 100
    conn.execute("UPDATE portfolio SET status='CLOSED' WHERE id=?", (p['id'],))
    conn.execute("INSERT INTO transactions (symbol,action,shares,price,total_value,date,reason,pnl,pnl_pct) VALUES (?,?,?,?,?,?,?,?,?)", (symbol, 'SELL', p['shares'], price, total, datetime.now().isoformat(), reason, pnl, pnl_pct))
    conn.execute("UPDATE balance SET cash=cash+?, total_invested=total_invested-?, last_updated=? WHERE id=1", (total, cost, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return True, f'{symbol} satildi ({pnl:+,.0f} TL / %{pnl_pct:+.1f})'

def send_mail(subject, html, cfg):
    """Brevo (Sendinblue) HTTP API uzerinden mail gonderir.
    Render'in ucretsiz plani SMTP portlarini (25/465/587) engelledigi icin
    HTTPS (443) uzerinden calisan bu API kullaniliyor."""
    if not cfg.get('enabled'):
        return False
    api_key = os.environ.get('BREVO_API_KEY')
    if not api_key:
        logger.error("❌ E-posta hatasi: BREVO_API_KEY tanimli degil")
        return False
    try:
        payload = {
            "sender": {"email": cfg['sender_email']},
            "to": [{"email": cfg['recipient_email']}],
            "subject": subject,
            "htmlContent": html,
        }
        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        }
        r = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=20)
        if r.status_code in (200, 201):
            logger.info(f"✅ E-posta: {subject}")
            return True
        logger.error(f"❌ E-posta hatasi: {r.status_code} {r.text}")
        return False
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

    m_open = market_is_open(cfg)
    logger.info(f"🏛️  Piyasa durumu: {'ACIK' if m_open else 'KAPALI'}")

    email = cfg['notifications']['email']
    for k in ['sender_email','sender_password','recipient_email']:
        env = k.upper()
        if os.environ.get(env):
            email[k] = os.environ[env]

    trail_activation = cfg['portfolio'].get('trailing_activation_pct', 0.03)
    trail_pct = cfg['portfolio'].get('trailing_stop_pct', 0.05)

    signals = []
    trades = 0

    for sym in cfg['watchlist']:
        try:
            logger.info(f"\n🔍 {sym} analiz ediliyor...")
            df = get_stock_data(sym, cfg['data']['interval'], cfg['data']['lookback_days'])
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
            if ind:
                logger.info(f"   ↳ MACD gucu: %{ind['macd_strength']:.2f} | Hacim orani: {ind['vol_ratio']:.2f}x")

            pos = next((p for p in get_pos() if p['symbol'] == sym), None)

            if pos:
                # --- Trailing stop guncelle ---
                peak = max(pos['peak_price'] or pos['entry_price'], price)
                if peak != pos['peak_price']:
                    update_peak(sym, peak, "data/portfolio.db")
                    pos['peak_price'] = peak

                activation_price = pos['entry_price'] * (1 + trail_activation)
                if peak >= activation_price:
                    trailing_stop = peak * (1 - trail_pct)
                    effective_stop = max(pos['stop_loss'], trailing_stop)
                    stop_reason = "Trailing Stop" if trailing_stop > pos['stop_loss'] else "Stop-loss"
                else:
                    effective_stop = pos['stop_loss']
                    stop_reason = "Stop-loss"

                # Satis kararlari - piyasa saatinden bagimsiz, koruma her zaman aktif
                if price <= effective_stop:
                    ok, msg = sell(sym, price, stop_reason, "data/portfolio.db")
                    if ok:
                        icon = "🟡" if stop_reason == "Trailing Stop" else "🔴"
                        send_mail(f"{icon} {stop_reason.upper()}: {sym}", f"<h2>{stop_reason}: {sym}</h2><p>{msg}</p>", email)
                        trades += 1
                # Not: sabit take-profit kaldirildi, kazanclar artik trailing stop ile korunuyor (tavan yok).
            else:
                if sig == 'BUY' and not m_open:
                    logger.info(f"   ↳ Piyasa kapali, yeni alim ertelendi")
                elif sig == 'BUY' and m_open:
                    size = calc_position_size(ind['macd_strength'], ind['vol_ratio'], cfg)
                    ok, msg = buy(sym, price, reason, size)
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
<tr><td><b>Yatirim</b></td><td align="right">{size:,.0f} ₺</td></tr>
<tr><td><b>MACD Gucu</b></td><td align="right">%{ind['macd_strength']:.2f}</td></tr>
<tr><td><b>Hacim Orani</b></td><td align="right">{ind['vol_ratio']:.2f}x</td></tr>
<tr><td><b>İşlem</b></td><td align="right" style="color:#16A34A;font-weight:bold;">AL</td></tr>
<tr><td><b>Sebep</b></td><td align="right">{reason}</td></tr>
</table></td></tr>
<tr><td bgcolor="#F8FAFC" style="padding:12px;text-align:center;font-size:11px;color:#64748b;">BIST AI PRO</td></tr>
</table></td></tr></table></body></html>"""
                        send_mail(f"🟢 ALIM: {sym}", buy_html, email)
                        trades += 1
                        logger.info(f"✅ {msg}")

            time.sleep(1.0)
        except Exception as e:
            logger.error(f"❌ {sym} hata: {e}")

    bal = get_bal()
    pos_list = get_pos()
    stats = get_performance_stats()

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

    # === ACIK POZISYONLAR (guncel K/Z ile) ===
    price_map = {s['symbol']: s['price'] for s in signals if s.get('price') is not None}
    pos_rows = ""
    for p in pos_list:
        if p['symbol'] in price_map:
            current = price_map[p['symbol']]
            unreal_pnl = (current - p['entry_price']) * p['shares']
            unreal_pct = (current / p['entry_price'] - 1) * 100
            pnl_row_color = "#16A34A" if unreal_pnl >= 0 else "#DC2626"
            current_cell = f"{current:.2f}"
            pnl_cell = f"{unreal_pnl:+,.0f} ₺<br><span style='font-size:11px;'>(%{unreal_pct:+.1f})</span>"
        else:
            # Bu run'da veri cekilemedi (rate-limit vb.) - yanlis %0 gostermek yerine acikca belirt
            current_cell = "Veri Yok"
            pnl_row_color = "#94A3B8"
            pnl_cell = "-"
        pos_rows += f"""
<tr style="border-bottom:1px solid #e0e0e0;">
<td style="padding:12px;font-weight:bold;">{p['symbol']}</td>
<td style="padding:12px;text-align:center;">{p['shares']:.2f}</td>
<td style="padding:12px;text-align:center;">{p['entry_price']:.2f}</td>
<td style="padding:12px;text-align:center;">{current_cell}</td>
<td style="padding:12px;text-align:center;">{(p['peak_price'] or p['entry_price']):.2f}</td>
<td style="padding:12px;text-align:center;color:#e74c3c;">{p['stop_loss']:.2f}</td>
<td style="padding:12px;text-align:center;color:{pnl_row_color};font-weight:bold;">{pnl_cell}</td>
</tr>"""
    if not pos_rows:
        pos_rows = '<tr><td colspan="7" style="padding:20px;text-align:center;">Açık pozisyon yok</td></tr>'

    pnl_color = "#16A34A" if stats['total_pnl'] >= 0 else "#DC2626"

    # === RAPOR HTML ===
    html = f"""<!DOCTYPE html><html><head><meta charset='UTF-8'></head>
<body style='margin:0;background:#eef2f7;font-family:Arial,Helvetica,sans-serif;'>
<table width='100%' cellpadding='20'><tr><td align='center'>
<table width='680' cellpadding='0' cellspacing='0' style='background:#fff;border:1px solid #d1d5db;'>
<tr><td bgcolor='#0F766E' style='padding:22px;text-align:center;'>
<h1 style='margin:0;color:#fff;'>📈 BIST AI PRO</h1>
<div style='color:#d1fae5;font-size:13px;'>{datetime.now().strftime('%d.%m.%Y %H:%M')} • Piyasa: {'AÇIK' if m_open else 'KAPALI'}</div></td></tr>
<tr><td style='padding:18px;'>
<table width='100%' cellpadding='6'><tr>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>NAKİT</div><b>{bal['cash']:,.0f} ₺</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>YATIRIM</div><b>{bal['total_invested']:,.0f} ₺</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>TOPLAM</div><b>{bal['total_value']:,.0f} ₺</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>POZİSYON</div><b>{len(pos_list)}</b></td>
</tr></table>

<h2 style='color:#1e293b;margin-top:22px;'>🏆 Performans Özeti</h2>
<table width='100%' cellpadding='6'><tr>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>TOPLAM İŞLEM</div><b>{stats['total_trades']}</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>KAZANAN/KAYIP</div><b>{stats['wins']}/{stats['losses']}</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>BAŞARI ORANI</div><b>%{stats['win_rate']:.1f}</b></td>
<td width='25%' align='center' style='border:1px solid #e5e7eb;'><div style='font-size:11px;color:#64748b;'>TOPLAM K/Z</div><b style='color:{pnl_color};'>{stats['total_pnl']:+,.0f} ₺</b></td>
</tr></table>

<h2 style='color:#1e293b;margin-top:22px;'>📊 Teknik Analiz</h2>
<table width='100%' cellpadding='9' cellspacing='0' style='border-collapse:collapse;border:1px solid #d1d5db;'>
<tr bgcolor='#1E293B'><th align='left' style='color:#fff;'>Hisse</th><th style='color:#fff;'>Sinyal</th><th style='color:#fff;'>Fiyat</th><th style='color:#fff;'>EMA9</th><th style='color:#fff;'>EMA21</th><th style='color:#fff;'>SMA50</th><th style='color:#fff;'>RSI</th><th style='color:#fff;'>MACD</th><th style='color:#fff;'>ADX</th></tr>
{ind_rows}
</table>
<h2 style='color:#1e293b;margin-top:22px;'>📋 Açık Pozisyonlar</h2>
<table width='100%' cellpadding='8' cellspacing='0' style='border-collapse:collapse;border:1px solid #d1d5db;'>
<tr bgcolor='#1E293B'><th align='left' style='color:#fff;'>Hisse</th><th style='color:#fff;'>Lot</th><th style='color:#fff;'>Alış</th><th style='color:#fff;'>Güncel</th><th style='color:#fff;'>Zirve</th><th style='color:#fff;'>Stop</th><th style='color:#fff;'>K/Z</th></tr>
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
