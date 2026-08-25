import pandas as pd
import logging
from src.indicators import calculate_all_indicators

logger = logging.getLogger(__name__)


class SignalEngine:
    def __init__(self, indicator_config: dict, volume_threshold: float = 1.0):
        self.config = indicator_config
        self.volume_threshold = volume_threshold
    
    def generate_signal(self, df: pd.DataFrame) -> dict:
        """
        Alım/Satım sinyali üret
        Dönüş: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'price': float}
        """
        if len(df) < 55:  # SMA50 için minimum veri
            return {'signal': 'HOLD', 'reason': 'Yetersiz veri', 'price': None}
        
        # Göstergeleri hesapla
        df = calculate_all_indicators(df, self.config)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        
        price = float(latest['Close'])
        
        # --- ALIM KOŞULLARI ---
        # 1. Fiyat > EMA9 > EMA21 > SMA50
        trend_condition = (
            price > latest['EMA9'] > latest['EMA21'] > latest['SMA50']
        )
        
        # 2. ADX > 25 (güçlü trend)
        adx_condition = latest['ADX'] > self.config['adx_threshold']
        
        # 3. MACD > 0 (pozitif momentum)
        macd_condition = latest['MACD'] > 0
        
        # 4. Fiyat BB içinde (aşırı alım/satım değil)
        bb_condition = latest['BB_Lower'] <= price <= latest['BB_Upper']
        
        # 5. Hacim kontrolü
        volume_condition = latest['Volume'] >= latest['Volume_MA'] * self.volume_threshold
        
        buy_conditions = {
            'trend': trend_condition,
            'adx': adx_condition,
            'macd': macd_condition,
            'bb': bb_condition,
            'volume': volume_condition
        }
        
        # --- SATIM KOŞULLARI (Stop-loss / Take-profit ayrı kontrol edilir) ---
        # Strateji bazlı satış: Trend bozulduğunda
        sell_condition = (
            price < latest['EMA9'] or  # Fiyat EMA9 altına düştü
            latest['MACD'] < 0 or       # MACD negatif oldu
            latest['ADX'] < 20          # Trend gücü azaldı
        )
        
        # Sinyal belirleme
        if all(buy_conditions.values()):
            return {
                'signal': 'BUY',
                'reason': f"ALIM: Trend={trend_condition}, ADX={latest['ADX']:.1f}, MACD={latest['MACD']:.2f}, BB={bb_condition}, Hacim={volume_condition}",
                'price': price,
                'indicators': {
                    'ema9': float(latest['EMA9']),
                    'ema21': float(latest['EMA21']),
                    'sma50': float(latest['SMA50']),
                    'adx': float(latest['ADX']),
                    'macd': float(latest['MACD']),
                    'bb_upper': float(latest['BB_Upper']),
                    'bb_lower': float(latest['BB_Lower']),
                    'volume': float(latest['Volume']),
                    'volume_ma': float(latest['Volume_MA'])
                }
            }
        
        elif sell_condition:
            return {
                'signal': 'SELL',
                'reason': f"SATIŞ: Fiyat<EMA9={price < latest['EMA9']}, MACD<0={latest['MACD'] < 0}, ADX<20={latest['ADX'] < 20}",
                'price': price,
                'indicators': {
                    'ema9': float(latest['EMA9']),
                    'ema21': float(latest['EMA21']),
                    'sma50': float(latest['SMA50']),
                    'adx': float(latest['ADX']),
                    'macd': float(latest['MACD'])
                }
            }
        
        return {
            'signal': 'HOLD',
            'reason': f"Bekleme modu. Koşullar: {buy_conditions}",
            'price': price,
            'indicators': {
                'ema9': float(latest['EMA9']),
                'ema21': float(latest['EMA21']),
                'sma50': float(latest['SMA50']),
                'adx': float(latest['ADX']),
                'macd': float(latest['MACD'])
            }
        }
