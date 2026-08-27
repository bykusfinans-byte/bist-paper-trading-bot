"""
Ana bot dosyasi.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from data_fetcher import fetch_4h_data, get_watchlist
from indicators import calculate_all
from strategy import check_buy_signal, check_sell_signal
from portfolio import Portfolio
from notifier import send_email, build_report


def main():
    print(f"=== BIST Trading Bot Basladi: {datetime.now()} ===")
    portfolio = Portfolio()
    watchlist = get_watchlist()

    actions_today = []
    current_prices = {}

    for ticker in watchlist:
        print(f"\n--- {ticker} kontrol ediliyor ---")
        df = fetch_4h_data(ticker)

        if df.empty or len(df) < 60:
            print(f"[UYARI] {ticker} icin yeterli veri yok.")
            continue

        df = calculate_all(df)
        last_row = df.iloc[-1]
        last_date = df.index[-1].strftime("%Y-%m-%d %H:%M")
        current_price = round(last_row["Close"], 2)
        current_prices[ticker] = current_price

        print(f"Fiyat: {current_price} | EMA9: {last_row['EMA9']:.2f} | "
              f"EMA21: {last_row['EMA21']:.2f} | SMA50: {last_row['SMA50']:.2f} | "
              f"RSI: {last_row['RSI']:.2f} | MACD: {last_row['MACD']:.2f} | "
              f"ADX: {last_row['ADX']:.2f}")

        # Satim kontrolu (onceki pozisyon varsa)
        if ticker in portfolio.positions:
            if check_sell_signal(last_row):
                print(f"[SATIM SINYALI] {ticker}")
                if portfolio.sell(ticker, current_price, last_date):
                    actions_today.append(portfolio.trades[-1])
                    print(f"  -> Satim gerceklesti: {current_price} TL")
            else:
                print(f"  -> Pozisyon devam ediyor, satim kosulu yok.")

        # Alim kontrolu (pozisyon yoksa)
        else:
            if check_buy_signal(last_row):
                print(f"[ALIM SINYALI] {ticker}")
                if portfolio.buy(ticker, current_price, last_date):
                    actions_today.append(portfolio.trades[-1])
                    print(f"  -> Alim gerceklesti: {current_price} TL")
            else:
                print(f"  -> Alim kosulu saglanmadi.")

    portfolio.save()

    # Portfoy raporu
    portfolio_data = portfolio.get_portfolio_value(current_prices)

    print("\n=== PORTFOY OZETI ===")
    print(f"Bakiye: {portfolio_data['balance']:,.2f} TL")
    print(f"Pozisyon Degeri: {portfolio_data['position_value']:,.2f} TL")
    print(f"Toplam: {portfolio_data['total_value']:,.2f} TL")
    print(f"Kar/Zarar: {portfolio_data['total_profit']:,.2f} TL (%{portfolio_data['total_profit_pct']})")

    # E-posta gonder
    subject = f"BIST Bot Raporu | Toplam: {portfolio_data['total_value']:,.0f} TL | Kar/Zarar: {portfolio_data['total_profit']:,.0f} TL"
    html_body = build_report(portfolio_data, actions_today, watchlist)
    send_email(subject, html_body)

    print("\n=== Bot tamamlandi ===")


if __name__ == "__main__":
    main()
