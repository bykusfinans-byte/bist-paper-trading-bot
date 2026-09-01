
"""
mail_gate.py
------------
GitHub Actions cron tetiklemeleri zaman zaman gecikir ya da atlanır.
Bu modül, portfolio.db içinde bir "son gönderim" kaydı tutarak:
  - Aynı zaman diliminde iki kez mail atılmasını engeller
  - Bir tetikleme kaçsa bile bir sonraki çalıştırmada normal akışa devam eder

main.py içinde kullanım:

    from mail_gate import should_send_now, mark_sent

    if should_send_now(db_path="data/portfolio.db", interval_minutes=30):
        # ... mail gönderme kodunuz ...
        mark_sent(db_path="data/portfolio.db")
    else:
        print("Henüz gönderim zamanı değil, atlanıyor.")
"""

import sqlite3
from datetime import datetime, timezone


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mail_log (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_sent_at TEXT
        )
        """
    )
    conn.commit()


def should_send_now(db_path: str, interval_minutes: int = 30) -> bool:
    """
    Son gönderimden bu yana en az `interval_minutes` dakika geçtiyse True döner.
    İlk çalıştırmada (kayıt yoksa) da True döner.
    """
    conn = sqlite3.connect(db_path)
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT last_sent_at FROM mail_log WHERE id = 1"
        ).fetchone()

        if row is None or row[0] is None:
            return True

        last_sent = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)
        elapsed_minutes = (now - last_sent).total_seconds() / 60
        return elapsed_minutes >= interval_minutes
    finally:
        conn.close()


def mark_sent(db_path: str) -> None:
    """Mail başarıyla gönderildikten sonra çağrılır; zaman damgasını günceller."""
    conn = sqlite3.connect(db_path)
    try:
        _ensure_table(conn)
        now_str = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO mail_log (id, last_sent_at) VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET last_sent_at = excluded.last_sent_at
            """,
            (now_str,),
        )
        conn.commit()
    finally:
        conn.close()
