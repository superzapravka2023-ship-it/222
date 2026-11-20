import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "bot.db")


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        c = self.conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value REAL
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                price_detected REAL,
                price_current REAL,
                pct_at_detection REAL,
                timeframe TEXT,
                detected_at TEXT,
                alerted_target INTEGER DEFAULT 0,
                alerted_near INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

        # Default settings
        defaults = {
            "min_tf": 1,
            "max_tf": 36,
            "min_pct": 50,
            "target_pct": 80,
        }
        for k, v in defaults.items():
            c.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))

        # Default stats
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stat_defaults = {
            "total_found": "0",
            "last_scan": "—",
            "started": now,
            "reached_target": "0",
        }
        for k, v in stat_defaults.items():
            c.execute("INSERT OR IGNORE INTO stats VALUES (?, ?)", (k, v))

        self.conn.commit()

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self):
        c = self.conn.cursor()
        rows = c.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def update_setting(self, key: str, value: float):
        self.conn.execute(
            "INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value)
        )
        self.conn.commit()

    # ── Watchlist ─────────────────────────────────────────────────────────────

    def get_watchlist(self):
        c = self.conn.cursor()
        rows = c.execute("SELECT symbol FROM watchlist").fetchall()
        return [r["symbol"] for r in rows]

    def add_to_watchlist(self, symbol, price, pct, timeframe):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.conn.execute("""
            INSERT OR IGNORE INTO watchlist
            (symbol, price_detected, price_current, pct_at_detection, timeframe, detected_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (symbol, price, price, pct, timeframe, now))
        self.conn.commit()

    def remove_from_watchlist(self, symbol):
        self.conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        self.conn.commit()

    def update_watchlist_price(self, symbol, price):
        self.conn.execute(
            "UPDATE watchlist SET price_current = ? WHERE symbol = ?",
            (price, symbol)
        )
        self.conn.commit()

    def get_pnl(self, symbol):
        c = self.conn.cursor()
        row = c.execute(
            "SELECT price_detected, price_current FROM watchlist WHERE symbol = ?",
            (symbol,)
        ).fetchone()
        if not row or row["price_detected"] == 0:
            return 0.0
        return ((row["price_current"] - row["price_detected"]) / row["price_detected"]) * 100

    def get_coin_info(self, symbol):
        c = self.conn.cursor()
        row = c.execute("SELECT * FROM watchlist WHERE symbol = ?", (symbol,)).fetchone()
        if not row:
            return None
        pd = row["price_detected"]
        pc = row["price_current"]
        pct_current = ((pc - pd) / pd * 100) if pd else 0
        return {
            "symbol": symbol,
            "price_detected": pd,
            "price_current": pc,
            "pct_at_detection": row["pct_at_detection"],
            "pct_current": pct_current,
            "timeframe": row["timeframe"],
            "detected_at": row["detected_at"],
            "alerted_target": row["alerted_target"],
            "alerted_near": row["alerted_near"],
        }

    def mark_target_alerted(self, symbol):
        self.conn.execute(
            "UPDATE watchlist SET alerted_target = 1 WHERE symbol = ?", (symbol,)
        )
        self.conn.execute(
            "UPDATE stats SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'reached_target'"
        )
        self.conn.commit()

    def mark_near_alerted(self, symbol):
        self.conn.execute(
            "UPDATE watchlist SET alerted_near = 1 WHERE symbol = ?", (symbol,)
        )
        self.conn.commit()

    # ── Stats ─────────────────────────────────────────────────────────────────

    def get_stats(self):
        c = self.conn.cursor()
        rows = c.execute("SELECT key, value FROM stats").fetchall()
        d = {r["key"]: r["value"] for r in rows}
        wl = self.get_watchlist()
        d["in_watchlist"] = len(wl)
        return d

    def update_last_scan(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "UPDATE stats SET value = ? WHERE key = 'last_scan'", (now,)
        )
        self.conn.commit()

    def increment_found(self):
        self.conn.execute(
            "UPDATE stats SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT) WHERE key = 'total_found'"
        )
        self.conn.commit()
