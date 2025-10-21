"""Application factory for the AI Trade Game platform."""

from __future__ import annotations

from flask import Flask, render_template
from flask_cors import CORS

from .api import api_bp
from .config import DEFAULT_COINS, DEFAULT_LOOP_INTERVAL, IDLE_LOOP_INTERVAL
from .services import Database, MarketDataFetcher, TradingManager


def create_app(auto_trading: bool = True, loop_interval: int = DEFAULT_LOOP_INTERVAL) -> Flask:
    """Create and configure the Flask application."""

    app = Flask(__name__)
    CORS(app)

    db = Database()
    try:
        db.init_db()
    except Exception as exc:  # pragma: no cover - defensive logging
        app.logger.error("Database initialization failed: %s", exc)

    market_fetcher = MarketDataFetcher()
    manager = TradingManager(
        db=db,
        market_fetcher=market_fetcher,
        coins=DEFAULT_COINS,
        loop_interval=loop_interval,
        idle_interval=IDLE_LOOP_INTERVAL,
        logger=app.logger,
    )
    manager.initialize_engines()

    app.extensions["database"] = db
    app.extensions["market_fetcher"] = market_fetcher
    app.extensions["trading_manager"] = manager
    app.config["DEFAULT_COINS"] = DEFAULT_COINS
    app.config["AUTO_TRADING"] = auto_trading

    app.register_blueprint(api_bp)

    @app.route("/")
    def index():
        return render_template("index.html")

    if auto_trading:
        manager.start()

    return app


__all__ = ["create_app"]
