import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class Reporter:
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
    
    def save_signals(self, signals: list, filename: str = None) -> str:
        """Sinyalleri JSON olarak kaydet"""
        if filename is None:
            filename = f"signals_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(signals, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Sinyaller kaydedildi: {filepath}")
        return str(filepath)
    
    def generate_html_report(self, portfolio_summary: dict, signals: list, 
                           transactions: list, filename: str = None) -> str:
        """HTML rapor oluştur"""
        if filename is None:
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
        
        filepath = self.output_dir / filename
        
        # Basit HTML rapor
        html = f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>BIST Bot Raporu - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1000px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .summary-box {{ display: flex; gap: 20px; margin: 20px 0; }}
        .summary-item {{ flex: 1; background: #ecf0f1; padding: 20px; border-radius: 8px; text-align: center; }}
        .summary-item h3 {{ margin: 0; color: #7f8c8d; font-size: 14px; }}
        .summary-item p {{ margin: 10px 0 0 0; font-size: 24px; font-weight: bold; color: #2c3e50; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }}
        th {{ background: #2c3e50; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid #ecf0f1; }}
        tr:hover {{ background: #f8f9fa; }}
        .buy {{ color: #27ae60; font-weight: bold; }}
        .sell {{ color: #e74c3c; font-weight: bold; }}
        .hold {{ color: #95a5a6; }}
        .footer {{ margin-top: 40px; text-align: center; color: #bdc3c7; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 BIST Paper Trading Bot - Rapor</h1>
        <p style="color: #7f8c8d;">{datetime.now().strftime('%d %B %Y %H:%M')}</p>
        
        <div class="summary-box">
            <div class="summary-item">
                <h3>Nakit</h3>
                <p>{portfolio_summary['cash']:,.0f} ₺</p>
            </div>
            <div class="summary-item">
                <h3>Yatırımda</h3>
                <p>{portfolio_summary['total_invested']:,.0f} ₺</p>
            </div>
            <div class="summary-item">
                <h3>Toplam</h3>
                <p>{portfolio_summary['total_value']:,.0f} ₺</p>
            </div>
            <div class="summary-item">
                <h3>Pozisyon</h3>
                <p>{portfolio_summary['open_positions_count']}</p>
            </div>
        </div>
        
        <h2>🎯 Sinyaller</h2>
        <table>
            <tr><th>Hisse</th><th>Sinyal</th><th>Fiyat</th><th>Sebep</th></tr>
            {''.join(f"<tr><td>{s['symbol']}</td><td class='{s['signal'].lower()}'>{s['signal']}</td><td>{s.get('price', 'N/A')}</td><td>{s.get('reason', '')[:60]}...</td></tr>" for s in signals)}
        </table>
        
        <h2>📋 Son İşlemler</h2>
        <table>
            <tr><th>Tarih</th><th>Hisse</th><th>İşlem</th><th>Fiyat</th><th>Tutar</th><th>Sebep</th></tr>
            {''.join(f"<tr><td>{t['date'][:16]}</td><td>{t['symbol']}</td><td class='{t['action'].lower()}'>{t['action']}</td><td>{t['price']:.2f}</td><td>{t['total_value']:,.0f}</td><td>{t.get('reason', '')[:40]}</td></tr>" for t in transactions[:10])}
        </table>
        
        <div class="footer">
            BIST Paper Trading Bot | Otomatik Rapor
        </div>
    </div>
</body>
</html>"""
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"📄 HTML rapor oluşturuldu: {filepath}")
        return str(filepath)
