#!/usr/bin/env python3
"""
BIST Paper Trading Bot
======================
Borsa Istanbul hisselerinde paper trading yapar.
"""

import yaml
import logging
import sys
from datetime import datetime
from pathlib import Path

# src klasörünü Python path'ine ekle
sys.path.insert(0, str(Path(__file__).parent))

from src.data_fetcher import DataFetcher
from src.signal_engine import SignalEngine
from src.portfolio_manager import PortfolioManager
from src.notifier import Notifier
from src.reporter import Reporter

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def is_bist_open() -> bool:
    """BIST açık mı kontrol et (hafta içi 10:00-18:00)"""
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    
    # Hafta sonu kontrolü
    if weekday >= 5:  # Cumartesi=5, Pazar=6
        return False
    
    # Saat kontrolü (Türkiye saati)
    if not (10 <= hour < 18):
        return False
    
    return True


def run_bot():
    """Botu çalıştır"""
    logger.info("=" * 60)
    logger.info("🚀 BIST Paper Trading Bot Başlatılıyor...")
    logger.info(f"⏰ Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)
    
    # Konfigürasyonu yükle
    config = load_config()
    
    # BIST saat kontrolü (opsiyonel - test için kapatabilirsiniz)
    # if not is_bist_open():
    #     logger.info("📅 BIST kapalı. Bot çalışmayacak.")
    #     return
    
    # Modülleri başlat
    data_fetcher = DataFetcher(
        interval=config['data']['interval'],
        lookback_days=config['data']['lookback_days']
    )
    signal_engine = SignalEngine(
        indicator_config=config['indicators'],
        volume_threshold=config['data']['volume_threshold']
    )
    portfolio = PortfolioManager(
        db_path="data/portfolio.db",
        initial_balance=config['portfolio']['initial_balance']
    )
    notifier = Notifier(email_config=config['notifications']['email'])
    reporter = Reporter(output_dir="reports")
    
    # Verileri çek
    logger.info(f"📊 {len(config['watchlist'])} hisse için veri çekiliyor...")
    stock_data = data_fetcher.fetch_all_stocks(config['watchlist'])
    
    if not stock_data:
        logger.error("❌ Hiç veri çekilemedi!")
        return
    
    signals_list = []
    executed_trades = []
    
    # Her hisse için sinyal üret ve işlem yap
    for symbol, df in stock_data.items():
        try:
            logger.info(f"\n🔍 {symbol} analiz ediliyor...")
            
            # Sinyal üret
            signal = signal_engine.generate_signal(df)
            signal['symbol'] = symbol
            signals_list.append(signal)
            
            current_price = signal['price']
            
            # Açık pozisyon var mı kontrol et
            position = portfolio.get_position(symbol)
            
            if position:
                # Stop-loss / Take-profit kontrolü
                sl_tp = portfolio.check_stop_loss_take_profit(symbol, current_price)
                
                if sl_tp['action'] == 'SELL':
                    result = portfolio.sell(symbol, current_price, sl_tp['reason'])
                    if result['success']:
                        notifier.send_trade_notification(
                            'SELL', symbol, current_price,
                            {'reason': sl_tp['reason']},
                            result.get('pnl')
                        )
                        executed_trades.append(result)
                    continue
                
                # Strateji satış sinyali
                if signal['signal'] == 'SELL':
                    result = portfolio.sell(symbol, current_price, signal['reason'])
                    if result['success']:
                        notifier.send_trade_notification(
                            'SELL', symbol, current_price,
                            {'reason': signal['reason']},
                            result.get('pnl')
                        )
                        executed_trades.append(result)
            
            else:
                # Alım sinyali
                if signal['signal'] == 'BUY':
                    result = portfolio.buy(
                        symbol, current_price, signal['reason'],
                        max_position_pct=config['portfolio']['max_position_per_stock']
                    )
                    if result['success']:
                        notifier.send_trade_notification(
                            'BUY', symbol, current_price,
                            {'reason': signal['reason']}
                        )
                        executed_trades.append(result)
            
            logger.info(f"📌 {symbol} | Sinyal: {signal['signal']} | Fiyat: {current_price:.2f}")
            
        except Exception as e:
            logger.error(f"❌ {symbol} işlenirken hata: {e}")
            continue
    
    # Raporlama
    portfolio_summary = portfolio.get_portfolio_summary()
    transactions = portfolio.get_transaction_history(limit=20)
    
    # HTML rapor oluştur
    report_path = reporter.generate_html_report(
        portfolio_summary, signals_list, transactions
    )
    
    # E-posta raporu gönder
    notifier.send_portfolio_report(portfolio_summary, signals_list)
    
    # Sinyalleri kaydet
    reporter.save_signals(signals_list)
    
    # Özet log
    logger.info("\n" + "=" * 60)
    logger.info("📊 GÜN ÖZETİ")
    logger.info(f"   İşlem yapılan hisse: {len(stock_data)}")
    logger.info(f"   Alım/Satım işlemi: {len(executed_trades)}")
    logger.info(f"   Açık pozisyon: {portfolio_summary['open_positions_count']}")
    logger.info(f"   Toplam değer: {portfolio_summary['total_value']:,.2f} TL")
    logger.info(f"   Rapor: {report_path}")
    logger.info("=" * 60)
    logger.info("🏁 Bot tamamlandı.\n")


if __name__ == "__main__":
    run_bot()
