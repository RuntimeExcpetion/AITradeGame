"""WSGI entry-point for the AI Trade Game application."""

from __future__ import annotations

from ai_trade_game import create_app

app = create_app()


if __name__ == "__main__":
    app.logger.info("AI Trading Platform starting at http://localhost:5000")
    app.run(debug=False, host="0.0.0.0", port=5000, use_reloader=False)
