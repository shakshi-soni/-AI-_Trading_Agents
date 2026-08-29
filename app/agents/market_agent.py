"""
Market Agent.

Pulls recent price/volume data via MarketDataService, hands it to an
LLM, and parses the response into a structured MarketAnalysis. The
LLM call itself is injected as a plain callable so this file has no
hard dependency on Groq or Gemini specifically.
"""

import json
from typing import Callable

from app.models.market import MarketAnalysis, MarketDirection
from app.services.market_data_service import MarketDataService

LLMCallable = Callable[[str], str]


class MarketAgentError(Exception):
    """Raised when the LLM response can't be parsed into a valid MarketAnalysis."""


SYSTEM_INSTRUCTIONS = (
    "You are a market analysis agent. Analyze recent price and volume data "
    "to make a decisive market direction call. Output ONLY a JSON object "
    "(no markdown, no commentary) with exactly these fields:\n"
    '{"direction": "bullish" | "bearish" | "neutral", '
    '"confidence": <float 0.0-1.0>, '
    '"evidence": [<short string reasons>]}\n\n'
    "IMPORTANT:\n"
    "- Be decisive: use the full range 0.0-1.0 confidence, not clustering around 0.5\n"
    "- Bullish: call bullish when price_change > +0.2% OR volume is elevated (2x normal)\n"
    "- Bearish: call bearish when price_change < -0.2% OR volume collapses\n"
    "- Neutral: only if price_change is -0.2% to +0.2% AND volume is normal\n"
    "- Higher confidence when technical signals align (price + volume agree)\n"
    "- Lower confidence when signals conflict\n"
    "- For bullish/bearish calls, set confidence 0.55+; for neutral, 0.35-0.55"
)


def build_market_prompt(ticker: str, current_price: float, price_change_pct: float, avg_volume: float) -> str:
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"Ticker: {ticker}\n"
        f"Current price: ${current_price:.2f}\n"
        f"Price change over lookback window: {price_change_pct:.2f}%\n"
        f"Average daily volume over lookback window: {avg_volume:,.0f}\n"
    )


class MarketAgent:
    def __init__(self, market_data_service: MarketDataService, llm_call: LLMCallable) -> None:
        self.market_data = market_data_service
        self.llm_call = llm_call

    def analyze(self, ticker: str, lookback_days: int = 10) -> MarketAnalysis:
        current_price = self.market_data.get_latest_price(ticker)
        price_change_pct = self.market_data.get_price_change_pct(ticker, lookback_days=lookback_days)
        avg_volume = self.market_data.get_average_volume(ticker, lookback_days=lookback_days)

        prompt = build_market_prompt(ticker, current_price, price_change_pct, avg_volume)
        raw_response = self.llm_call(prompt)
        data = self._parse_llm_json(raw_response)

        try:
            direction = MarketDirection(data["direction"])
            confidence = float(data["confidence"])
            evidence = data.get("evidence", [])
            if not isinstance(evidence, list):
                evidence = [str(evidence)]
        except (KeyError, ValueError, TypeError) as e:
            raise MarketAgentError(
                f"LLM response missing or invalid fields ({e}). Raw response: {raw_response!r}"
            )

        try:
            return MarketAnalysis(
                ticker=ticker,
                direction=direction,
                confidence=confidence,
                evidence=evidence,
                current_price=current_price,
            )
        except Exception as e:
            raise MarketAgentError(f"MarketAnalysis validation failed: {e}. Raw response: {raw_response!r}")

    @staticmethod
    def _parse_llm_json(raw_response: str) -> dict:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise MarketAgentError(
                f"Could not parse LLM response as JSON: {e}. Raw response: {raw_response!r}"
            )