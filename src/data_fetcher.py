import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataFetcher:
    def __init__(self, interval: str = "4h", lookback_days: int = 60):
        self.interval = interval
        self.lookback_days = lookback_days
    
    def fetch_stock_data(self, symbol: str, retries: int = 3) -> pd.DataFrame:
        ticker = f"{symbol}.IS"
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days)
        
        for attempt in range(retries):
            try:
                logger.info(f"📥 {symbol} verisi cekiliyor... (Deneme {attempt + 1})")
                
                # Daha stabil yontem
                stock = yf.Ticker(ticker)
                df = stock.history(
                    start=start_date.strftime('%Y-%m-%d'),
                    end=end_date.strftime('%Y-%m-%d'),
                    interval=self.interval,
                    auto_adjust=False
                )
                
                if df.empty:
                    logger.warning(f"⚠️ {symbol} icin veri bulunamadi")
                    return pd.DataFrame()
                
                # Sutun adlarini duzelt
                df = df.reset_index()
                
                # Sayisal veri kontrolu
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # NaN satirlari temizle
                df = df.dropna(subset=['Close', 'High', 'Low'])
                
                if len(df) < 55:
                    logger.warning(f"⚠️ {symbol}: Yetersiz veri ({len(df)} satir)")
                    return pd.DataFrame()
                
                df['Symbol'] = symbol
                logger.info(f"✅ {symbol}: {len(df)} satir veri cekildi")
                return df
                
            except Exception as e:
                logger.error(f"❌ {symbol} veri cekme hatasi: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return pd.DataFrame()
        
        return pd.DataFrame()
    
    def fetch_all_stocks(self, symbols: list) -> dict:
        data = {}
        for symbol in symbols:
            df = self.fetch_stock_data(symbol)
            if not df.empty:
                data[symbol] = df
            time.sleep(0.5)
        return data
