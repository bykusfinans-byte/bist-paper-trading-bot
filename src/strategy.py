"""
Alim/Satim stratejisi.
Kosullar:
- Alim: Fiyat > EMA9 > EMA21 > SMA50
         ADX > 20
         MACD > 0.20
         40 < RSI < 80
- Satim: Yukaridaki kosullardan herhangi biri bozuldugunda
"""
import pandas as pd


def check_buy_signal(row: pd.Series) -> bool:
    """Son satira gore alim sinyali kontrolu."""
    try:
        price = row["Close"]
        ema9 = row["EMA9"]
        ema21 = row["EMA21"]
        sma50 = row["SMA50"]
        adx = row["ADX"]
        macd = row["MACD"]
        rsi = row["RSI"]

        # EMA/SMA siralamasi
        trend_ok = price > ema9 > ema21 > sma50

        # ADX guclu trend
        adx_ok = adx > 20

        # MACD pozitif ve esik ustunde
        macd_ok = macd > 0.20

        # RSI orta seviyede (asiri alim/satim disinda)
        rsi_ok = 40 < rsi < 80

        return trend_ok and adx_ok and macd_ok and rsi_ok
    except KeyError:
        return False


def check_sell_signal(row: pd.Series) -> bool:
    """Satim sinyali: alim kosullarindan herhangi biri bozuldugunda."""
    try:
        price = row["Close"]
        ema9 = row["EMA9"]
        ema21 = row["EMA21"]
        sma50 = row["SMA50"]
        adx = row["ADX"]
        macd = row["MACD"]
        rsi = row["RSI"]

        trend_broken = price < ema9 or ema9 < ema21 or ema21 < sma50
        adx_broken = adx <= 20
        macd_broken = macd <= 0.20
        rsi_broken = rsi <= 40 or rsi >= 80

        return trend_broken or adx_broken or macd_broken or rsi_broken
    except KeyError:
        return False
