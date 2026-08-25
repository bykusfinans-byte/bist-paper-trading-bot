import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, email_config: dict):
        self.email_config = email_config
    
    def send_email(self, subject: str, body: str, is_html: bool = False) -> bool:
        """E-posta gönder"""
        if not self.email_config.get('enabled'):
            logger.info("📧 E-posta bildirimi devre dışı")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.email_config['sender_email']
            msg['To'] = self.email_config['recipient_email']
            
            content_type = 'html' if is_html else 'plain'
            msg.attach(MIMEText(body, content_type, 'utf-8'))
            
            with smtplib.SMTP(self.email_config['smtp_server'], self.email_config['smtp_port']) as server:
                server.starttls()
                server.login(
                    self.email_config['sender_email'],
                    self.email_config['sender_password']
                )
                server.send_message(msg)
            
            logger.info(f"✅ E-posta gönderildi: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"❌ E-posta gönderme hatası: {e}")
            return False
    
    def send_trade_notification(self, action: str, symbol: str, price: float, 
                                 details: dict, pnl: float = None) -> bool:
        """Alım/satım bildirimi gönder"""
        emoji = "🟢" if action == "BUY" else "🔴"
        subject = f"{emoji} BIST Bot - {action}: {symbol} @ {price:.2f} TL"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2>{emoji} İşlem Bildirimi</h2>
            <table style="border-collapse: collapse; width: 100%; max-width: 500px;">
                <tr style="background: #f5f5f5;">
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>İşlem</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{action}</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Hisse</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{symbol}</td>
                </tr>
                <tr style="background: #f5f5f5;">
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Fiyat</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{price:.2f} TL</td>
                </tr>
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Tarih</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td>
                </tr>
        """
        
        if pnl is not None:
            color = "green" if pnl >= 0 else "red"
            body += f"""
                <tr style="background: #f5f5f5;">
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Kâr/Zarar</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd; color: {color};">{pnl:+.2f} TL</td>
                </tr>
            """
        
        body += f"""
                <tr>
                    <td style="padding: 10px; border: 1px solid #ddd;"><strong>Detay</strong></td>
                    <td style="padding: 10px; border: 1px solid #ddd;">{details.get('reason', '')}</td>
                </tr>
            </table>
            <p style="margin-top: 20px; color: #666; font-size: 12px;">
                Bu bir otomatik bildirimdir. BIST Paper Trading Bot.
            </p>
        </body>
        </html>
        """
        
        return self.send_email(subject, body, is_html=True)
    
    def send_portfolio_report(self, portfolio_summary: dict, signals: list) -> bool:
        """Portföy raporu gönder"""
        subject = f"📊 BIST Bot - Portföy Raporu ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
        
        positions_html = ""
        for pos in portfolio_summary.get('open_positions', []):
            positions_html += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">{pos['symbol']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{pos['shares']:.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{pos['entry_price']:.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{pos['stop_loss']:.2f}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{pos['take_profit']:.2f}</td>
                </tr>
            """
        
        signals_html = ""
        for sig in signals:
            color = "green" if sig['signal'] == 'BUY' else "orange" if sig['signal'] == 'SELL' else "gray"
            signals_html += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">{sig['symbol']}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; color: {color};"><strong>{sig['signal']}</strong></td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{sig.get('price', 'N/A')}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; font-size: 11px;">{sig.get('reason', '')[:80]}...</td>
                </tr>
            """
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2>📊 Portföy Özeti</h2>
            
            <div style="background: #f9f9f9; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                <p><strong>Nakit:</strong> {portfolio_summary['cash']:,.2f} TL</p>
                <p><strong>Yatırımda:</strong> {portfolio_summary['total_invested']:,.2f} TL</p>
                <p><strong>Toplam Değer:</strong> {portfolio_summary['total_value']:,.2f} TL</p>
                <p><strong>Açık Pozisyon:</strong> {portfolio_summary['open_positions_count']} adet</p>
            </div>
            
            <h3>📈 Açık Pozisyonlar</h3>
            <table style="border-collapse: collapse; width: 100%; font-size: 13px;">
                <tr style="background: #333; color: white;">
                    <th style="padding: 8px; border: 1px solid #ddd;">Hisse</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Lot</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Giriş</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Stop-Loss</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Take-Profit</th>
                </tr>
                {positions_html if positions_html else '<tr><td colspan="5" style="padding: 8px; text-align: center;">Açık pozisyon yok</td></tr>'}
            </table>
            
            <h3>🎯 Son Sinyaller</h3>
            <table style="border-collapse: collapse; width: 100%; font-size: 13px;">
                <tr style="background: #333; color: white;">
                    <th style="padding: 8px; border: 1px solid #ddd;">Hisse</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Sinyal</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Fiyat</th>
                    <th style="padding: 8px; border: 1px solid #ddd;">Sebep</th>
                </tr>
                {signals_html if signals_html else '<tr><td colspan="4" style="padding: 8px; text-align: center;">Sinyal yok</td></tr>'}
            </table>
            
            <p style="margin-top: 20px; color: #666; font-size: 12px;">
                Rapor Zamanı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
                BIST Paper Trading Bot
            </p>
        </body>
        </html>
        """
        
        return self.send_email(subject, body, is_html=True)
