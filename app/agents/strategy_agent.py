"""
Strategy Agent.

Takes a MarketAnalysis, finds a real bull call spread via OptionsService,
and asks the LLM to estimate the net debit (as a fraction of spread
width) to size max_loss/max_profit. The strike/contract selection is
deterministic (OptionsService); only the premium estimate comes from
the LLM.

MVP scope: bull call spreads only, for bullish calls. Bearish/neutral
calls are rejected for now — extending to bear put spreads is a
post-hackathon improvement, not required for this submission.
"""

import json
from typing import Callable

from app.models.market import MarketAnalysis, MarketDirection
from app.models.strategy import TradeProposal, SpreadType
from app.services.options_service import OptionsService

LLMCallable = Callable[[str], str]
OPTIONS_MULTIPLIER = 100  # standard equity options contract multiplier


class StrategyAgentError(Exception):
    """Raised when the LLM response can't be parsed, or the market call is unsupported."""


SYSTEM_INSTRUCTIONS = (
    "You are an options strategy agent. Given a bullish market call and a "
    "candidate bull call spread (strikes, expiration), estimate how much of "
    "the strike width would typically be paid as net debit for this spread. "
    "Output ONLY a JSON object (no markdown, no commentary) with exactly "
    "these fields:\n"
    '{"estimated_net_debit_pct": <float strictly between 0.0 and 1.0>, '
    '"rationale": <short string explaining the trade choice>}'
)


def build_strategy_prompt(market_analysis: MarketAnalysis, spread: dict) -> str:
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"Ticker: {market_analysis.ticker}\n"
        f"Market direction: {market_analysis.direction.value}\n"
        f"Confidence: {market_analysis.confidence:.2f}\n"
        f"Long strike: {spread['long_strike']}\n"
        f"Short strike: {spread['short_strike']}\n"
        f"Expiration: {spread['expiration']}\n"
    )


class StrategyAgent:
    def __init__(self, options_service: OptionsService, llm_call: LLMCallable) -> None:
        self.options_service = options_service
        self.llm_call = llm_call

    def propose(self, market_analysis: MarketAnalysis, quantity: int = 1) -> TradeProposal:
        if market_analysis.direction != MarketDirection.BULLISH:
            raise StrategyAgentError(
                "StrategyAgent currently only builds bull call spreads for "
                f"bullish calls; got direction={market_analysis.direction.value}"
            )
        if quantity <= 0:
            raise StrategyAgentError(f"quantity must be positive, got {quantity}")

        spread = self.options_service.build_vertical_spread(
            market_analysis.ticker, current_price=market_analysis.current_price
        )

        prompt = build_strategy_prompt(market_analysis, spread)
        raw_response = self.llm_call(prompt)
        data = self._parse_llm_json(raw_response)

        try:
            debit_pct = float(data["estimated_net_debit_pct"])
            rationale = str(data["rationale"])
        except (KeyError, ValueError, TypeError) as e:
            raise StrategyAgentError(
                f"LLM response missing or invalid fields ({e}). Raw response: {raw_response!r}"
            )

        if not (0.0 < debit_pct < 1.0):
            raise StrategyAgentError(
                f"estimated_net_debit_pct must be strictly between 0 and 1, got {debit_pct}. "
                f"Raw response: {raw_response!r}"
            )

        spread_width = spread["short_strike"] - spread["long_strike"]
        net_debit_per_share = debit_pct * spread_width
        max_loss = round(net_debit_per_share * OPTIONS_MULTIPLIER * quantity, 2)
        max_profit = round((spread_width - net_debit_per_share) * OPTIONS_MULTIPLIER * quantity, 2)

        try:
            return TradeProposal(
                ticker=market_analysis.ticker,
                strategy=SpreadType.BULL_CALL_SPREAD,
                expiration=spread["expiration"],
                long_strike=spread["long_strike"],
                short_strike=spread["short_strike"],
                long_symbol=spread["long_symbol"],
                short_symbol=spread["short_symbol"],
                max_loss=max_loss,
                max_profit=max_profit,
                quantity=quantity,
                rationale=rationale,
                based_on=f"{market_analysis.ticker} {market_analysis.direction.value} conf={market_analysis.confidence:.2f}",
            )
        except Exception as e:
            raise StrategyAgentError(f"TradeProposal validation failed: {e}")

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
            raise StrategyAgentError(
                f"Could not parse LLM response as JSON: {e}. Raw response: {raw_response!r}"
            )