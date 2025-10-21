"""SQLite-backed persistence layer for the trading application."""

from __future__ import annotations

import os
import sqlite3
from typing import Dict, List, Optional


class Database:
    """Lightweight helper for interacting with the SQLite database."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = self._resolve_db_path(db_path)

    @staticmethod
    def _resolve_db_path(provided_path: Optional[str]) -> str:
        """Determine the database path with sensible environment-aware defaults."""

        path = provided_path or os.getenv("DATABASE_PATH")

        if not path:
            if os.getenv("VERCEL"):
                path = os.path.join("/tmp", "trading_bot.db")
            else:
                path = "trading_bot.db"

        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        return path

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_db(self) -> None:
        """Ensure that the database schema exists."""

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS models (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                api_key TEXT NOT NULL,
                api_url TEXT NOT NULL,
                model_name TEXT NOT NULL,
                initial_capital REAL DEFAULT 10000,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id INTEGER NOT NULL,
                coin TEXT NOT NULL,
                quantity REAL NOT NULL,
                avg_price REAL NOT NULL,
                leverage INTEGER DEFAULT 1,
                side TEXT DEFAULT 'long',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (model_id) REFERENCES models(id),
                UNIQUE(model_id, coin, side)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id INTEGER NOT NULL,
                coin TEXT NOT NULL,
                signal TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                leverage INTEGER DEFAULT 1,
                side TEXT DEFAULT 'long',
                pnl REAL DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (model_id) REFERENCES models(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id INTEGER NOT NULL,
                user_prompt TEXT NOT NULL,
                ai_response TEXT NOT NULL,
                cot_trace TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (model_id) REFERENCES models(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS account_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id INTEGER NOT NULL,
                total_value REAL NOT NULL,
                cash REAL NOT NULL,
                positions_value REAL NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (model_id) REFERENCES models(id)
            )
            """
        )

        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------
    def add_model(
        self,
        name: str,
        api_key: str,
        api_url: str,
        model_name: str,
        initial_capital: float = 10000,
    ) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO models (name, api_key, api_url, model_name, initial_capital)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, api_key, api_url, model_name, initial_capital),
        )
        model_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return model_id

    def get_model(self, model_id: int) -> Optional[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_models(self) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM models ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def delete_model(self, model_id: int) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM models WHERE id = ?", (model_id,))
        cursor.execute("DELETE FROM portfolios WHERE model_id = ?", (model_id,))
        cursor.execute("DELETE FROM trades WHERE model_id = ?", (model_id,))
        cursor.execute("DELETE FROM conversations WHERE model_id = ?", (model_id,))
        cursor.execute("DELETE FROM account_values WHERE model_id = ?", (model_id,))
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Portfolio management
    # ------------------------------------------------------------------
    def update_position(
        self,
        model_id: int,
        coin: str,
        quantity: float,
        avg_price: float,
        leverage: int = 1,
        side: str = "long",
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO portfolios (model_id, coin, quantity, avg_price, leverage, side, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(model_id, coin, side) DO UPDATE SET
                quantity = excluded.quantity,
                avg_price = excluded.avg_price,
                leverage = excluded.leverage,
                updated_at = CURRENT_TIMESTAMP
            """,
            (model_id, coin, quantity, avg_price, leverage, side),
        )
        conn.commit()
        conn.close()

    def get_portfolio(self, model_id: int, current_prices: Optional[Dict[str, float]] = None) -> Dict:
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM portfolios WHERE model_id = ? AND quantity > 0
            """,
            (model_id,),
        )
        positions = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT initial_capital FROM models WHERE id = ?", (model_id,))
        model_row = cursor.fetchone()
        if model_row is None:
            conn.close()
            raise ValueError(f"Model {model_id} not found")
        initial_capital = model_row["initial_capital"]

        cursor.execute(
            """
            SELECT COALESCE(SUM(pnl), 0) as total_pnl FROM trades WHERE model_id = ?
            """,
            (model_id,),
        )
        realized_pnl = cursor.fetchone()["total_pnl"]

        margin_used = sum(p["quantity"] * p["avg_price"] / p["leverage"] for p in positions)

        unrealized_pnl = 0.0
        if current_prices:
            for pos in positions:
                coin = pos["coin"]
                if coin in current_prices:
                    current_price = current_prices[coin]
                    entry_price = pos["avg_price"]
                    quantity = pos["quantity"]

                    pos["current_price"] = current_price
                    if pos["side"] == "long":
                        pos_pnl = (current_price - entry_price) * quantity
                    else:
                        pos_pnl = (entry_price - current_price) * quantity
                    pos["pnl"] = pos_pnl
                    unrealized_pnl += pos_pnl
                else:
                    pos["current_price"] = None
                    pos["pnl"] = 0.0
        else:
            for pos in positions:
                pos["current_price"] = None
                pos["pnl"] = 0.0

        cash = initial_capital + realized_pnl - margin_used
        positions_value = sum(p["quantity"] * p["avg_price"] for p in positions)
        total_value = initial_capital + realized_pnl + unrealized_pnl

        conn.close()

        return {
            "model_id": model_id,
            "cash": cash,
            "positions": positions,
            "positions_value": positions_value,
            "margin_used": margin_used,
            "total_value": total_value,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": unrealized_pnl,
        }

    def close_position(self, model_id: int, coin: str, side: str = "long") -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM portfolios WHERE model_id = ? AND coin = ? AND side = ?
            """,
            (model_id, coin, side),
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Trade history
    # ------------------------------------------------------------------
    def add_trade(
        self,
        model_id: int,
        coin: str,
        signal: str,
        quantity: float,
        price: float,
        leverage: int = 1,
        side: str = "long",
        pnl: float = 0.0,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO trades (model_id, coin, signal, quantity, price, leverage, side, pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (model_id, coin, signal, quantity, price, leverage, side, pnl),
        )
        conn.commit()
        conn.close()

    def get_trades(self, model_id: int, limit: int = 50) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM trades WHERE model_id = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (model_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------
    def add_conversation(
        self,
        model_id: int,
        user_prompt: str,
        ai_response: str,
        cot_trace: str = "",
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO conversations (model_id, user_prompt, ai_response, cot_trace)
            VALUES (?, ?, ?, ?)
            """,
            (model_id, user_prompt, ai_response, cot_trace),
        )
        conn.commit()
        conn.close()

    def get_conversations(self, model_id: int, limit: int = 20) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM conversations WHERE model_id = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (model_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Account values
    # ------------------------------------------------------------------
    def record_account_value(
        self,
        model_id: int,
        total_value: float,
        cash: float,
        positions_value: float,
    ) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO account_values (model_id, total_value, cash, positions_value)
            VALUES (?, ?, ?, ?)
            """,
            (model_id, total_value, cash, positions_value),
        )
        conn.commit()
        conn.close()

    def get_account_value_history(self, model_id: int, limit: int = 100) -> List[Dict]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM account_values WHERE model_id = ?
            ORDER BY timestamp DESC LIMIT ?
            """,
            (model_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
