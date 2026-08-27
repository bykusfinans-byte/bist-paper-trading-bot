"""
BIST hisse verilerini Yahoo Finance'dan ceker.
4 saatlik veri icin 1h verileri cekilip resample edilir.
"""
import yfinance as yf
import pandas as pd


def fetch_4h_data(ticker: str, period: str = "60d") -> pd.DataFrame:
    """
    Belirtilen hissenin 4 saatlik verilerini dondurur.
    Yahoo Finance 4h interval desteklemez, bu yuzden 1h veriler
    cekilip 4 saatlik OHLCV gruplarina bolunur.
    
    BIST ticker formati: THYAO.IS, GARAN.IS vb.
    """
    try:
        # 1 saatlik veri cek (max 60 gun)
        df = yf.download(ticker, period=period, interval="1h", progress=False)
        if df.empty:
            return pd.DataFrame()

        # MultiIndex kolonlari duzlestir (yfinance yeni versiyon)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 4 saatlik resample
        df_4h = df.resample('4H').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        }).dropna()

        return df_4h
    except Exception as e:
        print(f"[HATA] {ticker} verisi cekilemedi: {e}")
        return pd.DataFrame()


def get_watchlist() -> list:
    """
    Izlenen BIST hisseleri. Kendi listenizi buraya ekleyin.
    """
    return [
        "THYAO.IS",   # Turk Hava Yollari
        "GARAN.IS",   # Garanti BBVA
        "ASELS.IS",   # Aselsan
        "KCHOL.IS",   # Koc Holding
        "SISE.IS",    # Sisecam
        "EREGL.IS",   # Eregli Demir Celik
        "BIMAS.IS",   # Bim
        "TUPRS.IS",   # Tupras
        "SAHOL.IS",   # Sabanci Holding
        "ISCTR.IS",   # Is Bankasi
    ]
