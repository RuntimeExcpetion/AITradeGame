"""Application-level configuration constants."""

from __future__ import annotations

DEFAULT_COINS = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
"""List of coins tracked by the trading engine."""

DEFAULT_LOOP_INTERVAL = 180
"""Seconds to wait between automated trading cycles."""

IDLE_LOOP_INTERVAL = 30
"""Seconds to wait when no engines are registered."""

MAX_TRADES_RETURNED = 50
"""Default number of trades returned by the API."""

MAX_CONVERSATIONS_RETURNED = 20
"""Default number of conversation snippets returned by the API."""

ACCOUNT_HISTORY_LIMIT = 100
"""Default number of account value entries returned by the API."""
