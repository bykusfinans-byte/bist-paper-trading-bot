import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class PortfolioManager:
    def __init__(self, db_path: str = "data/portfolio.db", initial_balance: float = 100000):
        self.db_path = db_path
        self.initial_balance = initial_balance
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _get_connection(self):
        return sqlite3.connect(self.db_path)
    
    def _init_db(self):
        """Veritabanı tablolarını oluştur"""
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    shares REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    entry_date TEXT NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    status TEXT DEFAULT 'OPEN'
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    shares REAL NOT NULL,
                    price REAL NOT NULL,
                    total_value REAL NOT NULL,
                    date TEXT NOT NULL,
                    reason TEXT
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS balance (
                    id INTEGER PRIMARY KEY,
                    cash REAL NOT NULL,
                    total_invested REAL DEFAULT 0,
                    last_updated TEXT NOT NULL
                )
            ''')
            
            # Başlangıç bakiyesi
            cursor = conn.execute("SELECT COUNT(*) FROM balance")
            if cursor.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO balance (id, cash, last_updated) VALUES (1, ?, ?)",
                    (self.initial_balance, datetime.now().isoformat())
                )
            conn.commit()
    
    def get_balance(self) -> dict:
        """Mevcut bakiyeyi getir"""
        with self._get_connection() as conn:
            row = conn.execute("SELECT cash, total_invested FROM balance WHERE id = 1").fetchone()
            return {
                'cash': row[0],
                'total_invested': row[1],
                'total_value': row[0] + row[1]
            }
    
    def get_open_positions(self) -> list:
        """Açık pozisyonları getir"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM portfolio WHERE status = 'OPEN'"
            ).fetchall()
            return [dict(row) for row in rows]
    
    def get_position(self, symbol: str) -> dict:
        """Belirli bir hissenin pozisyonunu getir"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM portfolio WHERE symbol = ? AND status = 'OPEN'",
                (symbol,)
            ).fetchone()
            return dict(row) if row else None
    
    def buy(self, symbol: str, price: float, reason: str, max_position_pct: float = 0.20) -> dict:
        """
        Hisse alımı yap
        max_position_pct: Portföyün max yüzde kaçı bu hisseye gidebilir
        """
        balance = self.get_balance()
        cash = balance['cash']
        
        # Mevcut pozisyon kontrolü
        existing = self.get_position(symbol)
        if existing:
            return {'success': False, 'message': f'{symbol} için zaten açık pozisyon var'}
        
        # Alım miktarı hesaplama (portföyün max_position_pct'si kadar)
        max_investment = balance['total_value'] * max_position_pct
        investment = min(cash, max_investment)
        
        if investment < 1000:  # Minimum işlem büyüklüğü
            return {'success': False, 'message': 'Yetersiz bakiye'}
        
        shares = investment / price
        
        stop_loss = price * 0.95   # %5 stop-loss
        take_profit = price * 1.10  # %10 take-profit
        
        with self._get_connection() as conn:
            # Pozisyon kaydet
            conn.execute('''
                INSERT INTO portfolio (symbol, shares, entry_price, entry_date, stop_loss, take_profit, status)
                VALUES (?, ?, ?, ?, ?, ?, 'OPEN')
            ''', (symbol, shares, price, datetime.now().isoformat(), stop_loss, take_profit))
            
            # İşlem kaydet
            conn.execute('''
                INSERT INTO transactions (symbol, action, shares, price, total_value, date, reason)
                VALUES (?, 'BUY', ?, ?, ?, ?, ?)
            ''', (symbol, shares, price, investment, datetime.now().isoformat(), reason))
            
            # Bakiye güncelle
            conn.execute(
                "UPDATE balance SET cash = cash - ?, total_invested = total_invested + ?, last_updated = ? WHERE id = 1",
                (investment, investment, datetime.now().isoformat())
            )
            conn.commit()
        
        logger.info(f"🟢 ALIM: {symbol} - {shares:.2f} lot @ {price:.2f} TL (Toplam: {investment:.2f} TL)")
        return {
            'success': True,
            'message': f'{symbol} alındı: {shares:.2f} lot @ {price:.2f} TL',
            'shares': shares,
            'investment': investment,
            'stop_loss': stop_loss,
            'take_profit': take_profit
        }
    
    def sell(self, symbol: str, price: float, reason: str) -> dict:
        """Hisse satımı yap"""
        position = self.get_position(symbol)
        if not position:
            return {'success': False, 'message': f'{symbol} için açık pozisyon yok'}
        
        shares = position['shares']
        entry_price = position['entry_price']
        total_value = shares * price
        pnl = total_value - (shares * entry_price)
        pnl_pct = (price - entry_price) / entry_price * 100
        
        with self._get_connection() as conn:
            # Pozisyonu kapat
            conn.execute(
                "UPDATE portfolio SET status = 'CLOSED' WHERE id = ?",
                (position['id'],)
            )
            
            # İşlem kaydet
            conn.execute('''
                INSERT INTO transactions (symbol, action, shares, price, total_value, date, reason)
                VALUES (?, 'SELL', ?, ?, ?, ?, ?)
            ''', (symbol, shares, price, total_value, datetime.now().isoformat(), reason))
            
            # Bakiye güncelle
            conn.execute(
                "UPDATE balance SET cash = cash + ?, total_invested = total_invested - ?, last_updated = ? WHERE id = 1",
                (total_value, shares * entry_price, datetime.now().isoformat())
            )
            conn.commit()
        
        emoji = "🟢" if pnl >= 0 else "🔴"
        logger.info(f"{emoji} SATIŞ: {symbol} - {shares:.2f} lot @ {price:.2f} TL | K/Z: {pnl:+.2f} TL ({pnl_pct:+.2f}%)")
        return {
            'success': True,
            'message': f'{symbol} satıldı: {shares:.2f} lot @ {price:.2f} TL',
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'total_value': total_value
        }
    
    def check_stop_loss_take_profit(self, symbol: str, current_price: float) -> dict:
        """Stop-loss ve take-profit kontrolü"""
        position = self.get_position(symbol)
        if not position:
            return {'action': 'NONE'}
        
        stop_loss = position['stop_loss']
        take_profit = position['take_profit']
        
        if current_price <= stop_loss:
            return {
                'action': 'SELL',
                'reason': f'Stop-loss tetiklendi: {current_price:.2f} <= {stop_loss:.2f}'
            }
        
        if current_price >= take_profit:
            return {
                'action': 'SELL',
                'reason': f'Take-profit tetiklendi: {current_price:.2f} >= {take_profit:.2f}'
            }
        
        return {'action': 'NONE'}
    
    def get_portfolio_summary(self) -> dict:
        """Portföy özetini getir"""
        balance = self.get_balance()
        positions = self.get_open_positions()
        
        total_pnl = 0
        for pos in positions:
            # Güncel fiyatı bilmediğimiz için entry_price baz alınır
            # Gerçek P&L için güncel fiyat gerekir
            pass
        
        return {
            'cash': balance['cash'],
            'total_invested': balance['total_invested'],
            'total_value': balance['total_value'],
            'open_positions_count': len(positions),
            'open_positions': positions
        }
    
    def get_transaction_history(self, limit: int = 50) -> list:
        """Son işlemleri getir"""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY date DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
