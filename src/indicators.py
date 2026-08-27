"""
Teknik gostergeleri hesaplama modulu.
"""
import pandas as pd
import numpy as np


def add_ema(df: pd.DataFrame, period: int, col: str = "Close") -> pd.DataFrame:
    df[f"EMA{period}"] = df[col].ewm(span=period, adjust=False).mean()
    return df


def add_sma(df: pd.DataFrame, period: int, col: str = "Close") -> pd.DataFrame:
    df[f"SMA{period}"] = df[col].rolling(window=period).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14, col: str = "Close") -> pd.DataFrame:
    delta = df[col].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


def add_macd(df: pd.DataFrame, col: str = "Close") -> pd.DataFrame:
    ema12 = df[col].ewm(span=12, adjust=False).mean()
    ema26 = df[col].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
    return df


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

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

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    df["ADX"] = dx.rolling(window=period).mean()
    df["+DI"] = plus_di
    df["-DI"] = minus_di
    return df


def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
    """Tum gostergeleri hesaplar."""
    df = add_ema(df, 9)
    df = add_ema(df, 21)
    df = add_sma(df, 50)
    df = add_rsi(df, 14)
    df = add_macd(df)
    df = add_adx(df, 14)
    return df
