"""Coordinator responsible for managing multiple trading engines."""

from __future__ import annotations

import logging
import threading
from typing import Dict, Iterable, Optional

from .ai_client import AITrader
from .database import Database
from .market_data import MarketDataFetcher
from .trading_engine import TradingEngine


class TradingManager:
    """Manage lifecycle and background execution of trading engines."""

    def __init__(
        self,
        db: Database,
        market_fetcher: MarketDataFetcher,
        coins: Iterable[str],
        loop_interval: int,
        idle_interval: int,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.db = db
        self.market_fetcher = market_fetcher
        self.coins = list(coins)
        self.loop_interval = loop_interval
        self.idle_interval = idle_interval
        self.logger = logger or logging.getLogger(__name__)

        self._engines: Dict[int, TradingEngine] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Engine lifecycle management
    # ------------------------------------------------------------------
    def initialize_engines(self) -> None:
        models = self.db.get_all_models()
        if not models:
            self.logger.warning("No trading models found during initialization")
            return

        self.logger.info("Initializing trading engines")
        for model in models:
            model_id = model["id"]
            try:
                engine = self._build_engine(model)
                with self._lock:
                    self._engines[model_id] = engine
                self.logger.info("  [OK] Model %s (%s)", model_id, model.get("name"))
            except Exception as exc:  # pragma: no cover - defensive logging
                self.logger.exception("  [ERROR] Model %s (%s): %s", model_id, model.get("name"), exc)
        self.logger.info("Initialized %d engine(s)", len(self._engines))

    def register_model(self, model_id: int) -> TradingEngine:
        model = self.db.get_model(model_id)
        if not model:
            raise ValueError(f"Model {model_id} not found")

        engine = self._build_engine(model)
        with self._lock:
            self._engines[model_id] = engine
        self.logger.info("Registered trading engine for model %s", model_id)
        return engine

    def unregister_model(self, model_id: int) -> None:
        with self._lock:
            if model_id in self._engines:
                self._engines.pop(model_id, None)
                self.logger.info("Unregistered trading engine for model %s", model_id)

    def ensure_engine(self, model_id: int) -> TradingEngine:
        with self._lock:
            engine = self._engines.get(model_id)
        if engine:
            return engine
        return self.register_model(model_id)

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def execute_cycle(self, model_id: int) -> Dict:
        engine = self.ensure_engine(model_id)
        return engine.execute_trading_cycle()

    def list_engine_ids(self) -> Iterable[int]:
        with self._lock:
            return list(self._engines.keys())

    # ------------------------------------------------------------------
    # Background loop management
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="TradingLoop", daemon=True)
        self._thread.start()
        self.logger.info("Background trading loop started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
            self.logger.info("Background trading loop stopped")

    def _run_loop(self) -> None:
        self.logger.info("Trading loop running")
        while not self._stop_event.is_set():
            with self._lock:
                engines_snapshot = list(self._engines.items())

            if not engines_snapshot:
                self.logger.debug("No engines registered; sleeping")
                self._stop_event.wait(self.idle_interval)
                continue

            self.logger.info("Executing trading cycle for %d model(s)", len(engines_snapshot))
            for model_id, engine in engines_snapshot:
                if self._stop_event.is_set():
                    break
                self.logger.info("[EXEC] Model %s", model_id)
                result = engine.execute_trading_cycle()
                if not result.get("success"):
                    self.logger.warning("[WARN] Model %s failed: %s", model_id, result.get("error"))

            self.logger.info("Sleeping %d seconds before next cycle", self.loop_interval)
            self._stop_event.wait(self.loop_interval)

        self.logger.info("Trading loop terminated")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _build_engine(self, model: Dict) -> TradingEngine:
        trader = AITrader(
            api_key=model["api_key"],
            api_url=model["api_url"],
            model_name=model["model_name"],
        )
        return TradingEngine(
            model_id=model["id"],
            db=self.db,
            market_fetcher=self.market_fetcher,
            ai_trader=trader,
            coins=self.coins,
            logger=self.logger,
        )
