"""Market data access layer built on top of public crypto APIs."""

from __future__ import annotations

import time
from typing import Dict, List

import requests


class MarketDataFetcher:
    """Fetch real-time and historical cryptocurrency data."""

    def __init__(self) -> None:
        self.binance_base_url = "https://api.binance.com/api/v3"
        self.coingecko_base_url = "https://api.coingecko.com/api/v3"
        self.binance_symbols = {
            "BTC": "BTCUSDT",
            "ETH": "ETHUSDT",
            "SOL": "SOLUSDT",
            "BNB": "BNBUSDT",
            "XRP": "XRPUSDT",
            "DOGE": "DOGEUSDT",
        }
        self.coingecko_mapping = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "BNB": "binancecoin",
            "XRP": "ripple",
            "DOGE": "dogecoin",
        }
        self._cache: Dict[str, Dict] = {}
        self._cache_time: Dict[str, float] = {}
        self._cache_duration = 5  # seconds

    # ------------------------------------------------------------------
    # Current prices
    # ------------------------------------------------------------------
    def get_current_prices(self, coins: List[str]) -> Dict[str, Dict[str, float]]:
        cache_key = "prices_" + "_".join(sorted(coins))
        if cache_key in self._cache:
            if time.time() - self._cache_time[cache_key] < self._cache_duration:
                return self._cache[cache_key]

        try:
            prices = self._fetch_from_binance(coins)
            self._cache[cache_key] = prices
            self._cache_time[cache_key] = time.time()
            return prices
        except Exception as exc:  # pragma: no cover - network failure path
            print(f"[ERROR] Binance API failed: {exc}")
            return self._get_prices_from_coingecko(coins)

    def _fetch_from_binance(self, coins: List[str]) -> Dict[str, Dict[str, float]]:
        prices: Dict[str, Dict[str, float]] = {}
        symbols = [self.binance_symbols.get(coin) for coin in coins if coin in self.binance_symbols]
        if not symbols:
            return prices

        symbols_param = "[" + ",".join(f'"{symbol}"' for symbol in symbols) + "]"
        response = requests.get(
            f"{self.binance_base_url}/ticker/24hr",
            params={"symbols": symbols_param},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()

        for item in data:
            symbol = item["symbol"]
            for coin, binance_symbol in self.binance_symbols.items():
                if binance_symbol == symbol:
                    prices[coin] = {
                        "price": float(item["lastPrice"]),
                        "change_24h": float(item["priceChangePercent"]),
                    }
                    break

        return prices

    def _get_prices_from_coingecko(self, coins: List[str]) -> Dict[str, Dict[str, float]]:
        coin_ids = [self.coingecko_mapping.get(coin, coin.lower()) for coin in coins]
        response = requests.get(
            f"{self.coingecko_base_url}/simple/price",
            params={
                "ids": ",".join(coin_ids),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        prices: Dict[str, Dict[str, float]] = {}
        for coin in coins:
            coin_id = self.coingecko_mapping.get(coin, coin.lower())
            if coin_id in data:
                prices[coin] = {
                    "price": data[coin_id]["usd"],
                    "change_24h": data[coin_id].get("usd_24h_change", 0.0),
                }
        return prices

    # ------------------------------------------------------------------
    # Extended market data
    # ------------------------------------------------------------------
    def get_market_data(self, coin: str) -> Dict:
        coin_id = self.coingecko_mapping.get(coin, coin.lower())
        response = requests.get(
            f"{self.coingecko_base_url}/coins/{coin_id}",
            params={
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        market_data = data.get("market_data", {})
        return {
            "current_price": market_data.get("current_price", {}).get("usd", 0.0),
            "market_cap": market_data.get("market_cap", {}).get("usd", 0.0),
            "total_volume": market_data.get("total_volume", {}).get("usd", 0.0),
            "price_change_24h": market_data.get("price_change_percentage_24h", 0.0),
            "price_change_7d": market_data.get("price_change_percentage_7d", 0.0),
            "high_24h": market_data.get("high_24h", {}).get("usd", 0.0),
            "low_24h": market_data.get("low_24h", {}).get("usd", 0.0),
        }

    def get_historical_prices(self, coin: str, days: int = 14) -> List[Dict]:
        coin_id = self.coingecko_mapping.get(coin, coin.lower())
        response = requests.get(
            f"{self.coingecko_base_url}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        prices: List[Dict] = []
        for price_data in data.get("prices", []):
            prices.append({"timestamp": price_data[0], "price": price_data[1]})
        return prices

    def calculate_technical_indicators(self, coin: str) -> Dict[str, float]:
        historical = self.get_historical_prices(coin, days=14)
        if not historical or len(historical) < 14:
            return {}

        prices = [entry["price"] for entry in historical]
        sma_7 = sum(prices[-7:]) / 7 if len(prices) >= 7 else prices[-1]
        sma_14 = sum(prices[-14:]) / 14 if len(prices) >= 14 else prices[-1]

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [change if change > 0 else 0 for change in changes]
        losses = [-change if change < 0 else 0 for change in changes]

        avg_gain = sum(gains[-14:]) / 14 if gains else 0.0
        avg_loss = sum(losses[-14:]) / 14 if losses else 0.0

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))

        return {
            "sma_7": sma_7,
            "sma_14": sma_14,
            "rsi_14": rsi,
            "current_price": prices[-1],
            "price_change_7d": ((prices[-1] - prices[0]) / prices[0]) * 100 if prices[0] > 0 else 0.0,
        }
