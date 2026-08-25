import pandas as pd
import numpy as np


def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return df['Close'].ewm(span=period, adjust=False).mean()


def calculate_sma(df: pd.DataFrame, period: int) -> pd.Series:
    return df['Close'].rolling(window=period).mean()


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index hesaplama"""
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
    adx = dx.rolling(window=period).mean()
    
    return adx


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: int = 2):
    sma = df['Close'].rolling(window=period).mean()
    std = df['Close'].rolling(window=period).std()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return upper, sma, lower


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    return tr.rolling(window=period).mean()


def calculate_all_indicators(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Tüm göstergeleri hesapla ve DataFrame'e ekle"""
    df = df.copy()
    
    # EMA ve SMA
    df['EMA9'] = calculate_ema(df, config['ema_fast'])
    df['EMA21'] = calculate_ema(df, config['ema_slow'])
    df['SMA50'] = calculate_sma(df, config['sma_trend'])
    
    # ADX
    df['ADX'] = calculate_adx(df, config['adx_period'])
    
    # MACD
    macd, signal, hist = calculate_macd(
        df, config['macd_fast'], config['macd_slow'], config['macd_signal']
    )
    df['MACD'] = macd
    df['MACD_Signal'] = signal
    df['MACD_Hist'] = hist
    
    # Bollinger Bands
    df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = calculate_bollinger_bands(
        df, config['bb_period'], config['bb_std']
    )
    
    # Hacim ortalaması
    df['Volume_MA'] = df['Volume'].rolling(window=20).mean()
    
    return df
