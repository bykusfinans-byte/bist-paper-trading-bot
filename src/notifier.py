"""
E-posta bildirimleri. Gmail SMTP onerilir.
"""
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASS = os.getenv("EMAIL_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", EMAIL_USER)


def send_email(subject: str, body_html: str):
    if not EMAIL_USER or not EMAIL_PASS:
        print("[UYARI] E-posta ayarlari eksik, bildirim gonderilemedi.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO

    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(EMAIL_USER, EMAIL_PASS)
            server.sendmail(EMAIL_USER, EMAIL_TO, msg.as_string())
        print(f"[BILGI] E-posta gonderildi: {subject}")
    except Exception as e:
        print(f"[HATA] E-posta gonderimi basarisiz: {e}")


def build_report(portfolio_data: dict, actions: list, watchlist: list) -> str:
    """HTML formatinda rapor olusturur."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            h2 {{ color: #2c3e50; }}
            table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            .buy {{ color: green; font-weight: bold; }}
            .sell {{ color: red; font-weight: bold; }}
            .profit {{ color: green; }}
            .loss {{ color: red; }}
        </style>
    </head>
    <body>
        <h2>BIST Trading Bot - 4 Saatlik Rapor</h2>
        <p><strong>Zaman:</strong> {now}</p>

        <h3>Portfoy Ozeti</h3>
        <table>
            <tr><th>Bakiye (TL)</th><th>Pozisyon Degeri (TL)</th><th>Toplam Deger (TL)</th><th>Toplam Kar/Zarar</th></tr>
            <tr>
                <td>{portfolio_data['balance']:,.2f}</td>
                <td>{portfolio_data['position_value']:,.2f}</td>
                <td>{portfolio_data['total_value']:,.2f}</td>
                <td class="{'profit' if portfolio_data['total_profit'] >= 0 else 'loss'}">
                    {portfolio_data['total_profit']:,.2f} TL (%{portfolio_data['total_profit_pct']})
                </td>
            </tr>
        </table>

        <h3>Aktif Pozisyonlar</h3>
        <table>
            <tr><th Hisse</th><th>Adet</th><th>Alis Fiyati</th><th>Guncel Fiyat</th><th>Piyasa Degeri</th><th>Kar/Zarar</th></tr>
    """

    if portfolio_data["positions"]:
        for pos in portfolio_data["positions"]:
            html += f"""
            <tr>
                <td>{pos['ticker']}</td>
                <td>{pos['quantity']}</td>
                <td>{pos['avg_price']:,.2f}</td>
                <td>{pos['current_price']:,.2f}</td>
                <td>{pos['market_value']:,.2f}</td>
                <td class="{'profit' if pos['profit'] >= 0 else 'loss'}">{pos['profit']:,.2f} (%{pos['profit_pct']})</td>
            </tr>
            """
    else:
        html += "<tr><td colspan='6'>Aktif pozisyon yok.</td></tr>"

    html += "</table>"

    if actions:
        html += "<h3>Gerceklesen Islemler</h3><table>"
        html += "<tr><th>Zaman</th><th>Islem</th><th>Hisse</th><th>Fiyat</th><th>Adet</th><th>Tutar</th></tr>"
        for act in actions:
            cls = "buy" if act["action"] == "BUY" else "sell"
            html += f"""
            <tr>
                <td>{act['date']}</td>
                <td class="{cls}">{act['action']}</td>
                <td>{act['ticker']}</td>
                <td>{act['price']:,.2f}</td>
                <td>{act['quantity']}</td>
                <td>{act['amount']:,.2f}</td>
            </tr>
            """
        html += "</table>"
    else:
        html += "<p><em>Bu periyotta islem gerceklesmedi.</em></p>"

    html += f"<p><em>Izlenen Hisseler: {', '.join(watchlist)}</em></p>"
    html += "</body></html>"
    return html
