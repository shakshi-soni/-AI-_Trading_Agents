"""
Adversarial Agent.

Takes a TradeProposal plus the MarketAnalysis it was built from, and
asks the LLM to actively argue against the trade. This is the
signature component of the project: nothing executes without
surviving this challenge.
"""

import json
from typing import Callable

from app.models.adversarial import AdversarialReport, AdversarialVerdict
from app.models.market import MarketAnalysis
from app.models.strategy import TradeProposal

LLMCallable = Callable[[str], str]


class AdversarialAgentError(Exception):
    """Raised when the LLM response can't be parsed into a valid AdversarialReport."""


SYSTEM_INSTRUCTIONS = (
    "You are an adversarial risk-challenge agent. Your job is to try to "
    "prove the following proposed options trade is a BAD idea. Consider "
    "market regime, volatility, distance to strikes, time to expiration, "
    "and weaknesses in the original bullish thesis. Be genuinely critical "
    "— do not simply rubber-stamp the trade. Output ONLY a JSON object "
    "(no markdown, no commentary) with exactly these fields:\n"
    '{"verdict": "survive" | "reject", '
    '"thesis_survival": <float 0.0-1.0, how well the trade holds up>, '
    '"weaknesses": [<short string reasons the trade might fail>], '
    '"strengths": [<short string reasons the trade might still hold>], '
    '"reasoning": <short string summary of your overall judgment>}'
)


def build_adversarial_prompt(proposal: TradeProposal, market_analysis: MarketAnalysis) -> str:
    return (
        f"{SYSTEM_INSTRUCTIONS}\n\n"
        f"Ticker: {proposal.ticker}\n"
        f"Strategy: {proposal.strategy.value}\n"
        f"Long strike: {proposal.long_strike}\n"
        f"Short strike: {proposal.short_strike}\n"
        f"Expiration: {proposal.expiration}\n"
        f"Max loss: ${proposal.max_loss:.2f}\n"
        f"Max profit: ${proposal.max_profit:.2f}\n"
        f"Strategy agent's rationale: {proposal.rationale}\n"
        f"Original market call: {market_analysis.direction.value}, "
        f"confidence={market_analysis.confidence:.2f}\n"
        f"Market evidence cited: {', '.join(market_analysis.evidence) if market_analysis.evidence else 'none'}\n"
    )


class AdversarialAgent:
    def __init__(self, llm_call: LLMCallable) -> None:
        self.llm_call = llm_call

    def attack(self, proposal: TradeProposal, market_analysis: MarketAnalysis) -> AdversarialReport:
        prompt = build_adversarial_prompt(proposal, market_analysis)
        raw_response = self.llm_call(prompt)
        data = self._parse_llm_json(raw_response)

        try:
            verdict = AdversarialVerdict(data["verdict"])
            thesis_survival = float(data["thesis_survival"])
            weaknesses = data.get("weaknesses", [])
            strengths = data.get("strengths", [])
            reasoning = str(data["reasoning"])
            if not isinstance(weaknesses, list):
                weaknesses = [str(weaknesses)]
            if not isinstance(strengths, list):
                strengths = [str(strengths)]
        except (KeyError, ValueError, TypeError) as e:
            raise AdversarialAgentError(
                f"LLM response missing or invalid fields ({e}). Raw response: {raw_response!r}"
            )

        try:
            return AdversarialReport(
                verdict=verdict,
                thesis_survival=thesis_survival,
                weaknesses=weaknesses,
                strengths=strengths,
                reasoning=reasoning,
            )
        except Exception as e:
            raise AdversarialAgentError(f"AdversarialReport validation failed: {e}. Raw response: {raw_response!r}")

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
            raise AdversarialAgentError(
                f"Could not parse LLM response as JSON: {e}. Raw response: {raw_response!r}"
            )