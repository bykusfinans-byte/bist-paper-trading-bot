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
        """Bir hissenin 4 saatlik verisini çek"""
        ticker = f"{symbol}.IS"
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days)
        
        for attempt in range(retries):
            try:
                logger.info(f"📥 {symbol} verisi çekiliyor... (Deneme {attempt + 1})")
                
                # Daha stabil yöntem: Ticker objesi kullan
                stock = yf.Ticker(ticker)
                df = stock.history(
                    start=start_date.strftime('%Y-%m-%d'),
                    end=end_date.strftime('%Y-%m-%d'),
                    interval=self.interval
                )
                
                if df.empty:
                    logger.warning(f"⚠️ {symbol} için veri bulunamadı")
                    return pd.DataFrame()
                
                # Sütun adlarını düzelt
                df = df.reset_index()
                
                # yfinance farklı sütun adları döndürebilir (Close / Adj Close)
                if 'Adj Close' in df.columns and 'Close' not in df.columns:
                    df['Close'] = df['Adj Close']
                
                # Tüm fiyat sütunlarının sayısal olduğundan emin ol
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # NaN satırları temizle (indikatör hesaplaması için şart)
                df = df.dropna(subset=['Close', 'High', 'Low'])
                
                if len(df) < 55:
                    logger.warning(f"⚠️ {symbol}: Yetersiz veri ({len(df)} satır)")
                    return pd.DataFrame()
                
                df['Symbol'] = symbol
                logger.info(f"✅ {symbol}: {len(df)} satır veri çekildi")
                return df
                
            except Exception as e:
                logger.error(f"❌ {symbol} veri çekme hatası: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return pd.DataFrame()
        
        return pd.DataFrame()
    
    def fetch_all_stocks(self, symbols: list) -> dict:
        """Tüm hisselerin verisini çek"""
        data = {}
        for symbol in symbols:
            df = self.fetch_stock_data(symbol)
            if not df.empty:
                data[symbol] = df
            time.sleep(0.5)
        return data
