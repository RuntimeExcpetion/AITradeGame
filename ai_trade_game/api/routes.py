"""REST API routes for the AI Trade Game application."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..config import (
    ACCOUNT_HISTORY_LIMIT,
    DEFAULT_COINS,
    MAX_CONVERSATIONS_RETURNED,
    MAX_TRADES_RETURNED,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _services():
    db = current_app.extensions["database"]
    market_fetcher = current_app.extensions["market_fetcher"]
    manager = current_app.extensions["trading_manager"]
    coins = current_app.config.get("DEFAULT_COINS", DEFAULT_COINS)
    return db, market_fetcher, manager, coins


@api_bp.route("/models", methods=["GET"])
def get_models():
    db, _, manager, _ = _services()
    models = db.get_all_models()
    active_ids = set(manager.list_engine_ids())
    for model in models:
        model["engine_active"] = model["id"] in active_ids
    return jsonify(models)


@api_bp.route("/models", methods=["POST"])
def add_model():
    db, _, manager, _ = _services()
    payload = request.get_json(force=True, silent=True) or {}

    required_fields = ["name", "api_key", "api_url", "model_name"]
    missing = [field for field in required_fields if not payload.get(field)]
    if missing:
        return (
            jsonify({"error": f"Missing required fields: {', '.join(missing)}"}),
            400,
        )

    try:
        initial_capital = float(payload.get("initial_capital", 100000))
    except (TypeError, ValueError):
        return jsonify({"error": "initial_capital must be numeric"}), 400

    model_id = db.add_model(
        name=payload["name"],
        api_key=payload["api_key"],
        api_url=payload["api_url"],
        model_name=payload["model_name"],
        initial_capital=initial_capital,
    )

    try:
        manager.register_model(model_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.exception("Failed to initialize trading engine for model %s", model_id)
        return jsonify({"id": model_id, "warning": str(exc)}), 201

    current_app.logger.info("Model %s registered successfully", model_id)
    return jsonify({"id": model_id, "message": "Model added successfully"}), 201


@api_bp.route("/models/<int:model_id>", methods=["DELETE"])
def delete_model(model_id: int):
    db, _, manager, _ = _services()
    model = db.get_model(model_id)
    if not model:
        return jsonify({"error": "Model not found"}), 404

    db.delete_model(model_id)
    manager.unregister_model(model_id)
    current_app.logger.info("Model %s deleted", model_id)
    return jsonify({"message": "Model deleted successfully"})


@api_bp.route("/models/<int:model_id>/portfolio", methods=["GET"])
def get_portfolio(model_id: int):
    db, market_fetcher, _, coins = _services()
    model = db.get_model(model_id)
    if not model:
        return jsonify({"error": "Model not found"}), 404

    prices_data = market_fetcher.get_current_prices(coins)
    current_prices = {coin: data["price"] for coin, data in prices_data.items()}

    try:
        portfolio = db.get_portfolio(model_id, current_prices)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    history_limit = request.args.get("history_limit", ACCOUNT_HISTORY_LIMIT, type=int)
    history = db.get_account_value_history(model_id, limit=history_limit)
    return jsonify({"portfolio": portfolio, "account_value_history": history})


@api_bp.route("/models/<int:model_id>/trades", methods=["GET"])
def get_trades(model_id: int):
    db, _, _, _ = _services()
    limit = request.args.get("limit", MAX_TRADES_RETURNED, type=int)
    trades = db.get_trades(model_id, limit=limit)
    return jsonify(trades)


@api_bp.route("/models/<int:model_id>/conversations", methods=["GET"])
def get_conversations(model_id: int):
    db, _, _, _ = _services()
    limit = request.args.get("limit", MAX_CONVERSATIONS_RETURNED, type=int)
    conversations = db.get_conversations(model_id, limit=limit)
    return jsonify(conversations)


@api_bp.route("/market/prices", methods=["GET"])
def get_market_prices():
    _, market_fetcher, _, coins = _services()
    prices = market_fetcher.get_current_prices(coins)
    return jsonify(prices)


@api_bp.route("/models/<int:model_id>/execute", methods=["POST"])
def execute_trading(model_id: int):
    db, _, manager, _ = _services()
    if not db.get_model(model_id):
        return jsonify({"error": "Model not found"}), 404

    try:
        result = manager.execute_cycle(model_id)
        return jsonify(result)
    except Exception as exc:  # pragma: no cover - surfaces to caller
        current_app.logger.exception("Manual trading execution failed for model %s", model_id)
        return jsonify({"error": str(exc)}), 500


@api_bp.route("/leaderboard", methods=["GET"])
def get_leaderboard():
    db, market_fetcher, _, coins = _services()
    models = db.get_all_models()
    prices_data = market_fetcher.get_current_prices(coins)
    current_prices = {coin: data["price"] for coin, data in prices_data.items()}

    leaderboard = []
    for model in models:
        portfolio = db.get_portfolio(model["id"], current_prices)
        account_value = portfolio.get("total_value", model["initial_capital"])
        returns = (
            ((account_value - model["initial_capital"]) / model["initial_capital"]) * 100
            if model["initial_capital"]
            else 0.0
        )
        leaderboard.append(
            {
                "model_id": model["id"],
                "model_name": model["name"],
                "account_value": account_value,
                "returns": returns,
                "initial_capital": model["initial_capital"],
            }
        )

    leaderboard.sort(key=lambda entry: entry["returns"], reverse=True)
    return jsonify(leaderboard)
