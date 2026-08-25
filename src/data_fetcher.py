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
                df = yf.download(
                    ticker,
                    start=start_date.strftime('%Y-%m-%d'),
                    end=end_date.strftime('%Y-%m-%d'),
                    interval=self.interval,
                    progress=False,
                    auto_adjust=True
                )
                
                if df.empty:
                    logger.warning(f"⚠️ {symbol} için veri bulunamadı")
                    return pd.DataFrame()
                
                # MultiIndex düzeltme (yfinance bazen MultiIndex döndürür)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df = df.reset_index()
                if 'Date' in df.columns:
                    df = df.rename(columns={'Date': 'Datetime'})
                
                df['Symbol'] = symbol
                logger.info(f"✅ {symbol}: {len(df)} satır veri çekildi")
                return df
                
            except Exception as e:
                logger.error(f"❌ {symbol} veri çekme hatası: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
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
            time.sleep(0.5)  # Rate limit koruması
        return data
