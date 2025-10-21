"""Core execution engine responsible for a single model."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from .ai_client import AITrader
from .database import Database
from .market_data import MarketDataFetcher


class TradingEngine:
    """Executes trading cycles for a specific model."""

    def __init__(
        self,
        model_id: int,
        db: Database,
        market_fetcher: MarketDataFetcher,
        ai_trader: AITrader,
        coins: Iterable[str],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.model_id = model_id
        self.db = db
        self.market_fetcher = market_fetcher
        self.ai_trader = ai_trader
        self.coins = list(coins)
        self.logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def execute_trading_cycle(self) -> Dict:
        try:
            market_state = self._get_market_state()
            current_prices = {coin: info["price"] for coin, info in market_state.items() if "price" in info}
            portfolio = self.db.get_portfolio(self.model_id, current_prices)
            account_info = self._build_account_info(portfolio)

            decisions = self.ai_trader.make_decision(market_state, portfolio, account_info)
            self.db.add_conversation(
                self.model_id,
                user_prompt=self._format_prompt_summary(market_state, portfolio, account_info),
                ai_response=json.dumps(decisions, ensure_ascii=False),
                cot_trace="",
            )

            execution_results = self._execute_decisions(decisions, market_state, portfolio)
            updated_portfolio = self.db.get_portfolio(self.model_id, current_prices)
            self.db.record_account_value(
                self.model_id,
                updated_portfolio["total_value"],
                updated_portfolio["cash"],
                updated_portfolio["positions_value"],
            )

            return {
                "success": True,
                "decisions": decisions,
                "executions": execution_results,
                "portfolio": updated_portfolio,
            }
        except Exception as exc:
            self.logger.exception("Trading cycle failed for model %s", self.model_id)
            return {"success": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_market_state(self) -> Dict[str, Dict]:
        market_state: Dict[str, Dict] = {}
        prices = self.market_fetcher.get_current_prices(self.coins)
        for coin in self.coins:
            if coin in prices:
                market_state[coin] = prices[coin].copy()
                indicators = self.market_fetcher.calculate_technical_indicators(coin)
                if indicators:
                    market_state[coin]["indicators"] = indicators
        return market_state

    def _build_account_info(self, portfolio: Dict) -> Dict:
        model = self.db.get_model(self.model_id)
        if not model:
            raise ValueError(f"Model {self.model_id} not found")

        initial_capital = model["initial_capital"]
        total_value = portfolio["total_value"]
        total_return = ((total_value - initial_capital) / initial_capital) * 100 if initial_capital else 0.0
        return {
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_return": total_return,
            "initial_capital": initial_capital,
        }

    def _format_prompt_summary(self, market_state: Dict, portfolio: Dict, account_info: Dict) -> str:
        return (
            f"Market State: {len(market_state)} coins, "
            f"Portfolio: {len(portfolio['positions'])} positions, "
            f"Return: {account_info['total_return']:.2f}%"
        )

    def _execute_decisions(self, decisions: Dict, market_state: Dict, portfolio: Dict) -> List[Dict]:
        results: List[Dict] = []
        for coin, decision in decisions.items():
            if coin not in self.coins:
                continue

            signal = str(decision.get("signal", "")).lower()
            try:
                if signal == "buy_to_enter":
                    result = self._execute_buy(coin, decision, market_state, portfolio)
                elif signal == "sell_to_enter":
                    result = self._execute_sell(coin, decision, market_state, portfolio)
                elif signal == "close_position":
                    result = self._execute_close(coin, decision, market_state, portfolio)
                elif signal == "hold":
                    result = {"coin": coin, "signal": "hold", "message": "Hold position"}
                else:
                    result = {"coin": coin, "error": f"Unknown signal: {signal}"}
            except Exception as exc:
                result = {"coin": coin, "error": str(exc)}

            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Trade execution helpers
    # ------------------------------------------------------------------
    def _execute_buy(self, coin: str, decision: Dict, market_state: Dict, portfolio: Dict) -> Dict:
        quantity = float(decision.get("quantity", 0))
        leverage = max(int(decision.get("leverage", 1)), 1)
        price = market_state[coin]["price"]

        if quantity <= 0:
            raise ValueError("Invalid quantity")

        required_margin = (quantity * price) / leverage
        if required_margin > portfolio["cash"]:
            raise ValueError("Insufficient cash")

        self.db.update_position(self.model_id, coin, quantity, price, leverage, "long")
        self.db.add_trade(self.model_id, coin, "buy_to_enter", quantity, price, leverage, "long", pnl=0.0)
        return {
            "coin": coin,
            "signal": "buy_to_enter",
            "quantity": quantity,
            "price": price,
            "leverage": leverage,
            "message": f"Long {quantity:.4f} {coin} @ ${price:.2f}",
        }

    def _execute_sell(self, coin: str, decision: Dict, market_state: Dict, portfolio: Dict) -> Dict:
        quantity = float(decision.get("quantity", 0))
        leverage = max(int(decision.get("leverage", 1)), 1)
        price = market_state[coin]["price"]

        if quantity <= 0:
            raise ValueError("Invalid quantity")

        required_margin = (quantity * price) / leverage
        if required_margin > portfolio["cash"]:
            raise ValueError("Insufficient cash")

        self.db.update_position(self.model_id, coin, quantity, price, leverage, "short")
        self.db.add_trade(self.model_id, coin, "sell_to_enter", quantity, price, leverage, "short", pnl=0.0)
        return {
            "coin": coin,
            "signal": "sell_to_enter",
            "quantity": quantity,
            "price": price,
            "leverage": leverage,
            "message": f"Short {quantity:.4f} {coin} @ ${price:.2f}",
        }

    def _execute_close(self, coin: str, decision: Dict, market_state: Dict, portfolio: Dict) -> Dict:
        position = next((pos for pos in portfolio["positions"] if pos["coin"] == coin), None)
        if not position:
            raise ValueError("Position not found")

        current_price = market_state[coin]["price"]
        entry_price = position["avg_price"]
        quantity = position["quantity"]
        side = position["side"]

        if side == "long":
            pnl = (current_price - entry_price) * quantity
        else:
            pnl = (entry_price - current_price) * quantity

        self.db.close_position(self.model_id, coin, side)
        self.db.add_trade(
            self.model_id,
            coin,
            "close_position",
            quantity,
            current_price,
            position["leverage"],
            side,
            pnl=pnl,
        )
        return {
            "coin": coin,
            "signal": "close_position",
            "quantity": quantity,
            "price": current_price,
            "pnl": pnl,
            "message": f"Close {coin}, P&L: ${pnl:.2f}",
        }
