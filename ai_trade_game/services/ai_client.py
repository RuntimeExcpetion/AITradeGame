"""LLM-backed trading decision helper."""

from __future__ import annotations

import json
from typing import Dict

from openai import APIConnectionError, APIError, OpenAI


class AITrader:
    """Thin wrapper around the OpenAI client used to produce trade decisions."""

    def __init__(self, api_key: str, api_url: str, model_name: str) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.model_name = model_name

    def make_decision(self, market_state: Dict, portfolio: Dict, account_info: Dict) -> Dict:
        prompt = self._build_prompt(market_state, portfolio, account_info)
        response = self._call_llm(prompt)
        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------
    def _build_prompt(self, market_state: Dict, portfolio: Dict, account_info: Dict) -> str:
        prompt = "You are a professional cryptocurrency trader. Analyze the market and make trading decisions.\n\n"
        prompt += "MARKET DATA:\n"
        for coin, data in market_state.items():
            prompt += f"{coin}: ${data['price']:.2f} ({data['change_24h']:+.2f}%)\n"
            indicators = data.get("indicators") or {}
            if indicators:
                prompt += (
                    "  "
                    f"SMA7: ${indicators.get('sma_7', 0):.2f}, "
                    f"SMA14: ${indicators.get('sma_14', 0):.2f}, "
                    f"RSI: {indicators.get('rsi_14', 0):.1f}\n"
                )

        prompt += "\nACCOUNT STATUS:\n"
        prompt += f"- Initial Capital: ${account_info['initial_capital']:.2f}\n"
        prompt += f"- Total Value: ${portfolio['total_value']:.2f}\n"
        prompt += f"- Cash: ${portfolio['cash']:.2f}\n"
        prompt += f"- Total Return: {account_info['total_return']:.2f}%\n\n"

        prompt += "CURRENT POSITIONS:\n"
        if portfolio["positions"]:
            for pos in portfolio["positions"]:
                prompt += (
                    f"- {pos['coin']} {pos['side']}: {pos['quantity']:.4f} "
                    f"@ ${pos['avg_price']:.2f} ({pos['leverage']}x)\n"
                )
        else:
            prompt += "None\n"

        prompt += "\nTRADING RULES:\n"
        prompt += "1. Signals: buy_to_enter (long), sell_to_enter (short), close_position, hold\n"
        prompt += "2. Risk Management:\n   - Max 3 positions\n   - Risk 1-5% per trade\n   - Use appropriate leverage (1-20x)\n"
        prompt += "3. Position Sizing:\n   - Conservative: 1-2% risk\n   - Moderate: 2-4% risk\n   - Aggressive: 4-5% risk\n"
        prompt += "4. Exit Strategy:\n   - Close losing positions quickly\n   - Let winners run\n   - Use technical indicators\n\n"

        prompt += "OUTPUT FORMAT (JSON only):\n````json\n{\n  \"COIN\": {\n    \"signal\": \"buy_to_enter|sell_to_enter|hold|close_position\",\n    \"quantity\": 0.5,\n    \"leverage\": 10,\n    \"profit_target\": 45000.0,\n    \"stop_loss\": 42000.0,\n    \"confidence\": 0.75,\n    \"justification\": \"Brief reason\"\n  }\n}\n````\n\nAnalyze and output JSON only."
        return prompt

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------
    def _call_llm(self, prompt: str) -> str:
        try:
            base_url = self.api_url.rstrip("/")
            if not base_url.endswith("/v1"):
                if "/v1" in base_url:
                    base_url = base_url.split("/v1")[0] + "/v1"
                else:
                    base_url = base_url + "/v1"

            client = OpenAI(api_key=self.api_key, base_url=base_url)
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional cryptocurrency trader. Output JSON format only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
                max_tokens=2000,
            )
            return response.choices[0].message.content or ""
        except APIConnectionError as exc:
            error_msg = f"API connection failed: {exc}"
            print(f"[ERROR] {error_msg}")
            raise RuntimeError(error_msg) from exc
        except APIError as exc:
            error_msg = f"API error ({exc.status_code}): {exc.message}"
            print(f"[ERROR] {error_msg}")
            raise RuntimeError(error_msg) from exc
        except Exception as exc:  # pragma: no cover - defensive catch
            error_msg = f"LLM call failed: {exc}"
            print(f"[ERROR] {error_msg}")
            raise RuntimeError(error_msg) from exc

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    def _parse_response(self, response: str) -> Dict:
        response = response.strip()
        if "```json" in response:
            response = response.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in response:
            response = response.split("```", 1)[1].split("```", 1)[0]

        try:
            return json.loads(response.strip())
        except json.JSONDecodeError as exc:
            print(f"[ERROR] JSON parse failed: {exc}")
            print(f"[DATA] Response:\n{response}")
            return {}
