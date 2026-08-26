import pandas as pd
import numpy as np


def _safe_series(df, col):
    """MultiIndex veya bozuk sütunlardan güvenli Series çeker"""
    if col not in df.columns:
        return pd.Series([np.nan] * len(df), index=df.index)
    val = df[col]
    if isinstance(val, pd.DataFrame):
        val = val.iloc[:, 0]
    val = pd.to_numeric(val, errors='coerce')
    return val


def calculate_ema(df, period):
    close = _safe_series(df, 'Close')
    if close.isna().all() or len(close.dropna()) < period:
        return pd.Series([np.nan] * len(df), index=df.index)
    return close.ewm(span=period, adjust=False).mean()


def calculate_sma(df, period):
    close = _safe_series(df, 'Close')
    if close.isna().all() or len(close.dropna()) < period:
        return pd.Series([np.nan] * len(df), index=df.index)
    return close.rolling(window=period).mean()


def calculate_adx(df, period=14):
    high = _safe_series(df, 'High')
    low = _safe_series(df, 'Low')
    close = _safe_series(df, 'Close')
    
    if high.isna().all() or low.isna().all() or close.isna().all():
        return pd.Series([np.nan] * len(df), index=df.index)
    
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.rolling(window=period).mean()
    if atr.isna().all():
        return pd.Series([np.nan] * len(df), index=df.index)
    
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=period).mean()
    return adx


def calculate_macd(df, fast=12, slow=26, signal=9):
    close = _safe_series(df, 'Close')
    if close.isna().all():
        empty = pd.Series([np.nan] * len(df), index=df.index)
        return empty, empty, empty
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(df, period=20, std_dev=2):
    close = _safe_series(df, 'Close')
    if close.isna().all() or len(close.dropna()) < period:
        empty = pd.Series([np.nan] * len(df), index=df.index)
        return empty, empty, empty
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


def calculate_all_indicators(df, config):
    df = df.copy()
    
    # MultiIndex düzeltme
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # Sayısal veri dönüşümü
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # NaN temizleme
    df = df.dropna(subset=['Close', 'High', 'Low'])
    
    if len(df) < 55:
        return df
    
    df['EMA9'] = calculate_ema(df, config['ema_fast'])
    df['EMA21'] = calculate_ema(df, config['ema_slow'])
    df['SMA50'] = calculate_sma(df, config['sma_trend'])
    df['ADX'] = calculate_adx(df, config['adx_period'])
    
    macd, signal, hist = calculate_macd(
        df, config['macd_fast'], config['macd_slow'], config['macd_signal']
    )
    df['MACD'] = macd
    df['MACD_Signal'] = signal
    df['MACD_Hist'] = hist
    
    df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = calculate_bollinger_bands(
        df, config['bb_period'], config['bb_std']
    )
    
    if 'Volume' in df.columns:
        df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    
    return df
